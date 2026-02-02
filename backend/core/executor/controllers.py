"""
QPS and FIND_MAX_CONCURRENCY controllers for test executor.
"""

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional

from backend.config import settings
from backend.connectors import snowflake_pool

logger = logging.getLogger(__name__)


@dataclass
class StepResult:
    """Result from a single FIND_MAX_CONCURRENCY step."""

    step_num: int
    concurrency: int
    qps: float
    p95_latency_ms: float
    p99_latency_ms: float
    error_rate_pct: float
    kind_metrics: dict[str, dict[str, float | None]]
    stable: bool
    stop_reason: Optional[str]
    is_backoff: bool = False


class ControllersMixin:
    """Mixin providing QPS and FIND_MAX controller functionality."""

    # These attributes are defined in the main TestExecutor class
    scenario: Any
    _stop_event: asyncio.Event
    _metrics_lock: asyncio.Lock
    _metrics_epoch: int
    _measurement_active: bool
    metrics: Any
    _latencies_ms: Any
    _qps_windowed: Optional[float]
    _qps_smoothed: Optional[float]
    _target_workers: int
    _qps_controller_state: dict[str, Any]
    _find_max_controller_state: dict[str, Any]
    _find_max_step_collecting: bool
    _find_max_step_lat_by_kind_ms: dict[str, Any]
    _find_max_step_ops_by_kind: dict[str, int]
    _find_max_step_errors_by_kind: dict[str, int]
    _warehouse_query_status: dict[str, Any]
    workers: list[asyncio.Task]

    async def _run_qps_controller(
        self,
        *,
        target_qps: float,
        min_workers: int,
        max_workers: int,
        warmup_seconds: int,
        duration_seconds: int,
    ) -> None:
        """
        Run QPS-targeting controller that scales workers to meet throughput target.

        Args:
            target_qps: Target queries per second
            min_workers: Minimum number of workers
            max_workers: Maximum number of workers
            warmup_seconds: Warmup duration before measurement
            duration_seconds: Measurement duration
        """
        controller_logger = logging.LoggerAdapter(logger, {"worker_id": "QPS_CONTROLLER"})

        qps_workers: dict[int, tuple[asyncio.Task, asyncio.Event]] = {}
        next_worker_id = 0

        def _sync_worker_list() -> None:
            self.workers = [t for t, _ in qps_workers.values() if not t.done()]

        def _prune_done() -> None:
            for wid, (t, _) in list(qps_workers.items()):
                if t.done():
                    qps_workers.pop(wid, None)

        def _running_worker_ids() -> list[int]:
            out: list[int] = []
            for wid, (t, stop_signal) in qps_workers.items():
                if t.done():
                    continue
                if stop_signal.is_set():
                    continue
                out.append(int(wid))
            return out

        def _active_worker_count() -> int:
            return len(_running_worker_ids())

        async def _spawn_one(*, warmup: bool) -> None:
            nonlocal next_worker_id
            wid = int(next_worker_id)
            next_worker_id += 1
            stop_signal = asyncio.Event()
            task = asyncio.create_task(
                self._controlled_worker(worker_id=wid, warmup=warmup, stop_signal=stop_signal)
            )
            qps_workers[wid] = (task, stop_signal)
            _sync_worker_list()

        async def _scale_to(*, target: int, warmup: bool) -> None:
            _prune_done()
            target = max(min_workers, min(max_workers, target))
            self._target_workers = target

            running_ids = sorted(_running_worker_ids())
            running = len(running_ids)

            if running < target:
                spawn_n = target - running
                for _ in range(spawn_n):
                    await _spawn_one(warmup=warmup)
            elif running > target:
                stop_n = running - target
                stop_ids = list(reversed(running_ids))[:stop_n]
                for wid in stop_ids:
                    _, stop_signal = qps_workers.get(wid, (None, None))
                    if isinstance(stop_signal, asyncio.Event):
                        stop_signal.set()
                _sync_worker_list()

        async def _stop_all_workers(*, timeout_seconds: float) -> None:
            _prune_done()
            for _, stop_signal in qps_workers.values():
                stop_signal.set()
            _sync_worker_list()
            tasks = [t for t, _ in qps_workers.values()]
            if not tasks:
                qps_workers.clear()
                return
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                controller_logger.warning("Timeout waiting for workers to stop")
            qps_workers.clear()
            _sync_worker_list()

        # Start with minimum workers in warmup
        controller_logger.info("Starting QPS controller (target=%s QPS)", target_qps)
        await _scale_to(target=min_workers, warmup=True)

        # Warmup phase
        if warmup_seconds > 0:
            controller_logger.info("Warmup phase (%ds)...", warmup_seconds)
            warmup_end = asyncio.get_running_loop().time() + warmup_seconds
            while asyncio.get_running_loop().time() < warmup_end and not self._stop_event.is_set():
                await asyncio.sleep(1.0)

        # Transition to measurement
        async with self._metrics_lock:
            self._metrics_epoch += 1
            self._measurement_active = True
            # Reset metrics for measurement window
            from backend.models import Metrics
            self.metrics = Metrics()
            self.metrics.timestamp = datetime.now(UTC)
            self._latencies_ms.clear()

        controller_logger.info("Measurement phase (%ds)...", duration_seconds)
        measurement_end = asyncio.get_running_loop().time() + duration_seconds

        # Controller loop
        loop_interval = 2.0
        while asyncio.get_running_loop().time() < measurement_end and not self._stop_event.is_set():
            await asyncio.sleep(loop_interval)

            # Get current QPS
            current_qps = self._qps_windowed or self._qps_smoothed or 0.0
            current_workers = _active_worker_count()

            # Calculate desired workers based on QPS gap
            if current_qps > 0:
                qps_per_worker = current_qps / max(1, current_workers)
                if qps_per_worker > 0:
                    desired = int(math.ceil(target_qps / qps_per_worker))
                else:
                    desired = current_workers + 1
            else:
                desired = current_workers + 1

            # Clamp to bounds
            desired = max(min_workers, min(max_workers, desired))

            # Update controller state for WebSocket
            self._qps_controller_state = {
                "mode": "QPS",
                "target_qps": target_qps,
                "current_qps": current_qps,
                "current_workers": current_workers,
                "desired_workers": desired,
                "min_workers": min_workers,
                "max_workers": max_workers,
            }

            # Scale if needed
            if desired != current_workers:
                controller_logger.debug(
                    "Scaling: %d -> %d workers (QPS: %.1f / %.1f)",
                    current_workers, desired, current_qps, target_qps
                )
                await _scale_to(target=desired, warmup=False)

        # Stop all workers
        controller_logger.info("Stopping workers...")
        self._stop_event.set()
        await _stop_all_workers(timeout_seconds=5.0)

    async def _run_find_max_controller(
        self,
        *,
        start_cc: int,
        increment: int,
        step_dur: int,
        max_cc: int,
        qps_stability_pct: float,
        latency_stability_pct: float,
        max_error_rate_pct: float,
    ) -> dict[str, Any]:
        """
        Run FIND_MAX_CONCURRENCY controller to find optimal worker count.

        Args:
            start_cc: Starting concurrency
            increment: Concurrency increment per step
            step_dur: Duration per step in seconds
            max_cc: Maximum concurrency to test
            qps_stability_pct: Max QPS drop percentage before degradation
            latency_stability_pct: Max latency increase percentage before degradation
            max_error_rate_pct: Max error rate percentage before degradation

        Returns:
            Dict with find_max results including best_concurrency and step_history
        """
        controller_logger = logging.LoggerAdapter(logger, {"worker_id": "FIND_MAX"})

        fmc_workers: dict[int, tuple[asyncio.Task, asyncio.Event]] = {}
        next_worker_id = 0

        def _sync_worker_list() -> None:
            self.workers = [t for t, _ in fmc_workers.values() if not t.done()]

        def _running_worker_ids() -> list[int]:
            out: list[int] = []
            for wid, (t, stop_signal) in fmc_workers.items():
                if t.done() or stop_signal.is_set():
                    continue
                out.append(wid)
            return out

        def _active_worker_count() -> int:
            return len(_running_worker_ids())

        async def _spawn_one() -> None:
            nonlocal next_worker_id
            wid = int(next_worker_id)
            next_worker_id += 1
            stop_signal = asyncio.Event()
            task = asyncio.create_task(
                self._controlled_worker(worker_id=wid, warmup=False, stop_signal=stop_signal)
            )
            fmc_workers[wid] = (task, stop_signal)
            _sync_worker_list()

        async def _scale_to(target: int) -> None:
            running_ids = sorted(_running_worker_ids())
            running = len(running_ids)
            self._target_workers = target

            if running < target:
                for _ in range(target - running):
                    await _spawn_one()
            elif running > target:
                stop_ids = list(reversed(running_ids))[: running - target]
                for wid in stop_ids:
                    _, stop_signal = fmc_workers.get(wid, (None, None))
                    if isinstance(stop_signal, asyncio.Event):
                        stop_signal.set()
                _sync_worker_list()

        async def _stop_all_workers(timeout_seconds: float) -> None:
            for _, stop_signal in fmc_workers.values():
                stop_signal.set()
            _sync_worker_list()
            tasks = [t for t, _ in fmc_workers.values()]
            if tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.gather(*tasks, return_exceptions=True),
                        timeout=timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    pass
            fmc_workers.clear()
            _sync_worker_list()

        def _pctile(values: list[float], pct: float) -> float | None:
            if not values:
                return None
            s = sorted(values)
            idx = int(len(s) * (pct / 100.0))
            idx = min(max(idx, 0), len(s) - 1)
            return float(s[idx])

        # Initialize
        controller_logger.info(
            "Starting FIND_MAX controller (start=%d, increment=%d, max=%d)",
            start_cc, increment, max_cc
        )

        step_results: list[StepResult] = []
        best_concurrency = start_cc
        best_qps = 0.0
        baseline_p95_latency: Optional[float] = None
        baseline_p99_latency: Optional[float] = None
        current_cc = start_cc
        step_num = 0
        max_backoff_attempts = 3
        backoff_attempts = 0
        termination_reason: Optional[str] = None

        # Get SLO config from template
        fmc_slo_by_kind = self._get_fmc_slo_config()

        async def run_step(cc: int, is_backoff: bool = False) -> StepResult:
            nonlocal step_num, baseline_p95_latency, baseline_p99_latency

            step_num += 1
            step_label = f"Step {step_num}" + (" (backoff)" if is_backoff else "")
            controller_logger.info(f"FIND_MAX: {step_label} - scaling to {cc} workers")

            await _scale_to(cc)
            await asyncio.sleep(0.5)  # Let workers stabilize

            # Reset per-step metrics
            async with self._metrics_lock:
                self._find_max_step_collecting = True
                for k in self._find_max_step_lat_by_kind_ms:
                    self._find_max_step_lat_by_kind_ms[k].clear()
                for k in self._find_max_step_ops_by_kind:
                    self._find_max_step_ops_by_kind[k] = 0
                for k in self._find_max_step_errors_by_kind:
                    self._find_max_step_errors_by_kind[k] = 0

            step_start_ops = self.metrics.total_operations
            step_start_errors = self.metrics.failed_operations
            step_start_time = asyncio.get_running_loop().time()

            # Update controller state
            self._find_max_controller_state = {
                "mode": "FIND_MAX_CONCURRENCY",
                "status": "STEP_RUNNING",
                "current_step": step_num,
                "current_concurrency": cc,
                "active_worker_count": _active_worker_count(),
                "step_duration_seconds": step_dur,
                "best_concurrency": best_concurrency,
                "best_qps": best_qps,
            }

            # Run for step duration
            step_elapsed = 0.0
            while step_elapsed < step_dur and not self._stop_event.is_set():
                await asyncio.sleep(1.0)
                step_elapsed = asyncio.get_running_loop().time() - step_start_time

            # Capture metrics
            async with self._metrics_lock:
                self._find_max_step_collecting = False
                step_latencies = list(self._latencies_ms)
                step_kind_latencies = {k: list(v) for k, v in self._find_max_step_lat_by_kind_ms.items()}
                step_kind_ops = dict(self._find_max_step_ops_by_kind)
                step_kind_errors = dict(self._find_max_step_errors_by_kind)

            step_end_ops = self.metrics.total_operations
            step_end_errors = self.metrics.failed_operations
            step_ops = step_end_ops - step_start_ops
            step_errors = step_end_errors - step_start_errors
            step_qps = step_ops / step_dur if step_dur > 0 else 0.0
            step_error_rate = (step_errors / step_ops * 100.0) if step_ops > 0 else 0.0

            # Calculate latency percentiles
            step_p95_latency = 0.0
            step_p99_latency = 0.0
            if step_latencies:
                sorted_lat = sorted(step_latencies)
                p95_idx = int(len(sorted_lat) * 0.95)
                step_p95_latency = sorted_lat[min(p95_idx, len(sorted_lat) - 1)]
                p99_idx = int(len(sorted_lat) * 0.99)
                step_p99_latency = sorted_lat[min(p99_idx, len(sorted_lat) - 1)]

            # Calculate per-kind metrics
            step_kind_metrics: dict[str, dict[str, float | None]] = {}
            for kind, values in step_kind_latencies.items():
                ops = step_kind_ops.get(kind, 0)
                errs = step_kind_errors.get(kind, 0)
                p95 = _pctile(values, 95.0)
                p99 = _pctile(values, 99.0)
                err_rate = (errs / ops * 100.0) if ops > 0 else None
                step_kind_metrics[kind] = {
                    "p95_latency_ms": p95,
                    "p99_latency_ms": p99,
                    "error_rate_pct": err_rate,
                }

            # Set baseline from first step
            if baseline_p95_latency is None:
                baseline_p95_latency = step_p95_latency
            if baseline_p99_latency is None:
                baseline_p99_latency = step_p99_latency

            # Determine stability
            stable = True
            stop_reason = None

            # Check error rate
            if step_error_rate > max_error_rate_pct:
                stable = False
                stop_reason = f"Error rate {step_error_rate:.2f}% > {max_error_rate_pct}%"

            # Check queue buildup
            if stable and self._warehouse_query_status:
                queued = int(self._warehouse_query_status.get("queued", 0) or 0)
                blocked = int(self._warehouse_query_status.get("blocked", 0) or 0)
                if queued > 0 or blocked > 0:
                    stable = False
                    stop_reason = f"Queue buildup: {queued} queued, {blocked} blocked"

            # Check SLO constraints
            if stable:
                stable, stop_reason = self._check_fmc_slo_constraints(
                    fmc_slo_by_kind, step_kind_ops, step_kind_errors, step_kind_latencies, _pctile
                )

            # Compare to previous stable step
            prev_stable = [r for r in step_results if r.stable and not r.is_backoff]
            if stable and prev_stable:
                prev = prev_stable[-1]
                if prev.qps > 0:
                    qps_change_pct = ((step_qps - prev.qps) / prev.qps) * 100.0
                    if qps_change_pct < -qps_stability_pct:
                        stable = False
                        stop_reason = f"QPS dropped {-qps_change_pct:.1f}% vs previous"

                if stable and prev.p95_latency_ms > 0 and step_p95_latency > 0:
                    latency_change_pct = ((step_p95_latency - prev.p95_latency_ms) / prev.p95_latency_ms) * 100.0
                    if latency_change_pct > latency_stability_pct:
                        stable = False
                        stop_reason = f"P95 latency increased {latency_change_pct:.1f}%"

            result = StepResult(
                step_num=step_num,
                concurrency=cc,
                qps=step_qps,
                p95_latency_ms=step_p95_latency,
                p99_latency_ms=step_p99_latency,
                error_rate_pct=step_error_rate,
                kind_metrics=step_kind_metrics,
                stable=stable,
                stop_reason=stop_reason,
                is_backoff=is_backoff,
            )

            controller_logger.info(
                f"FIND_MAX: {step_label} complete - {cc} workers: {step_qps:.1f} QPS, "
                f"p95={step_p95_latency:.1f}ms, errors={step_error_rate:.2f}%, stable={stable}"
            )

            return result

        # Main loop
        while current_cc <= max_cc and not self._stop_event.is_set():
            step_result = await run_step(current_cc)
            step_results.append(step_result)

            if step_result.stable and step_result.qps >= best_qps:
                best_concurrency = current_cc
                best_qps = step_result.qps

            if not step_result.stable:
                if termination_reason is None and step_result.stop_reason:
                    termination_reason = step_result.stop_reason

                # Try backoff
                if backoff_attempts < max_backoff_attempts and best_concurrency < current_cc:
                    backoff_attempts += 1
                    controller_logger.info(f"FIND_MAX: Backing off to {best_concurrency}")
                    backoff_result = await run_step(best_concurrency, is_backoff=True)
                    step_results.append(backoff_result)

                    if backoff_result.stable:
                        # Try midpoint
                        midpoint = best_concurrency + (current_cc - best_concurrency) // 2
                        if midpoint > best_concurrency and midpoint < current_cc:
                            mid_result = await run_step(midpoint)
                            step_results.append(mid_result)
                            if mid_result.stable and mid_result.qps >= best_qps:
                                best_concurrency = midpoint
                                best_qps = mid_result.qps
                                current_cc = midpoint + increment
                                continue

                controller_logger.info(f"FIND_MAX: Stopping - {step_result.stop_reason}")
                break

            current_cc += increment

        # Stop workers
        controller_logger.info("FIND_MAX: Stopping workers...")
        self._stop_event.set()
        await _stop_all_workers(timeout_seconds=2.0)

        # Build result
        final_reason = termination_reason or (
            step_results[-1].stop_reason if step_results and not step_results[-1].stable
            else "Reached max workers"
        )

        controller_logger.info(
            f"✅ FIND_MAX complete: Best concurrency = {best_concurrency} workers @ {best_qps:.1f} QPS"
        )

        return {
            "best_concurrency": best_concurrency,
            "best_qps": best_qps,
            "baseline_p95_latency_ms": baseline_p95_latency,
            "baseline_p99_latency_ms": baseline_p99_latency,
            "termination_reason": final_reason,
            "step_history": [
                {
                    "step_num": r.step_num,
                    "concurrency": r.concurrency,
                    "qps": r.qps,
                    "p95_latency_ms": r.p95_latency_ms,
                    "p99_latency_ms": r.p99_latency_ms,
                    "error_rate_pct": r.error_rate_pct,
                    "stable": r.stable,
                    "stop_reason": r.stop_reason,
                    "is_backoff": r.is_backoff,
                }
                for r in step_results
            ],
        }

    def _get_fmc_slo_config(self) -> dict[str, dict[str, Any]]:
        """Get SLO configuration for FIND_MAX from template config."""
        tpl_cfg = getattr(self, "_template_config", None)
        if not isinstance(tpl_cfg, dict):
            return {}

        slo_by_kind: dict[str, dict[str, Any]] = {}
        kind_map = {
            "POINT_LOOKUP": ("custom_point_lookup_pct", "target_point_lookup_p95_latency_ms",
                             "target_point_lookup_p99_latency_ms", "target_point_lookup_error_rate_pct"),
            "RANGE_SCAN": ("custom_range_scan_pct", "target_range_scan_p95_latency_ms",
                           "target_range_scan_p99_latency_ms", "target_range_scan_error_rate_pct"),
            "INSERT": ("custom_insert_pct", "target_insert_p95_latency_ms",
                       "target_insert_p99_latency_ms", "target_insert_error_rate_pct"),
            "UPDATE": ("custom_update_pct", "target_update_p95_latency_ms",
                       "target_update_p99_latency_ms", "target_update_error_rate_pct"),
        }

        for kind, (pct_key, p95_key, p99_key, err_key) in kind_map.items():
            slo_by_kind[kind] = {
                "weight_pct": float(tpl_cfg.get(pct_key, 0) or 0),
                "target_p95_ms": float(tpl_cfg.get(p95_key, -1) or -1),
                "target_p99_ms": float(tpl_cfg.get(p99_key, -1) or -1),
                "target_err_pct": float(tpl_cfg.get(err_key, -1) or -1),
            }

        return slo_by_kind

    def _check_fmc_slo_constraints(
        self,
        slo_by_kind: dict[str, dict[str, Any]],
        step_kind_ops: dict[str, int],
        step_kind_errors: dict[str, int],
        step_kind_latencies: dict[str, list[float]],
        pctile_fn,
    ) -> tuple[bool, Optional[str]]:
        """Check SLO constraints for FIND_MAX step."""
        kind_labels = {
            "POINT_LOOKUP": "Point Lookup",
            "RANGE_SCAN": "Range Scan",
            "INSERT": "Insert",
            "UPDATE": "Update",
        }

        for kind in ["POINT_LOOKUP", "RANGE_SCAN", "INSERT", "UPDATE"]:
            cfg = slo_by_kind.get(kind) or {}
            weight = float(cfg.get("weight_pct", 0) or 0)
            if not math.isfinite(weight) or weight <= 0:
                continue

            t95 = float(cfg.get("target_p95_ms", -1) or -1)
            t99 = float(cfg.get("target_p99_ms", -1) or -1)
            terr = float(cfg.get("target_err_pct", -1) or -1)

            p95_enabled = math.isfinite(t95) and t95 > 0
            p99_enabled = math.isfinite(t99) and t99 > 0
            err_enabled = math.isfinite(terr) and terr >= 0

            if not (p95_enabled or p99_enabled or err_enabled):
                continue

            ops = step_kind_ops.get(kind, 0)
            errs = step_kind_errors.get(kind, 0)
            label = kind_labels.get(kind, kind)

            if ops <= 0:
                return False, f"{label}: no operations observed"

            err_pct = (errs / ops * 100.0) if ops > 0 else 0.0
            if err_enabled and err_pct > terr:
                return False, f"{label}: error rate {err_pct:.2f}% > {terr}%"

            samples = step_kind_latencies.get(kind) or []
            if p99_enabled:
                o99 = pctile_fn(samples, 99.0)
                if o99 is None:
                    return False, f"{label}: no samples for P99"
                if o99 > t99:
                    return False, f"{label}: P99 {o99:.1f}ms > {t99:.1f}ms"

            if p95_enabled:
                o95 = pctile_fn(samples, 95.0)
                if o95 is None:
                    return False, f"{label}: no samples for P95"
                if o95 > t95:
                    return False, f"{label}: P95 {o95:.1f}ms > {t95:.1f}ms"

        return True, None
