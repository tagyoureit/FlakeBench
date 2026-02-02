"""
Metrics collection and result building for test executor.
"""

import asyncio
import logging
import math
import os
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from backend.models import Metrics

logger = logging.getLogger(__name__)


class MetricsMixin:
    """Mixin providing metrics collection functionality for TestExecutor."""

    # These attributes are defined in the main TestExecutor class
    metrics: "Metrics"
    _metrics_lock: asyncio.Lock
    _stop_event: asyncio.Event
    _latencies_ms: Any
    _last_snapshot_time: Optional[datetime]
    _last_snapshot_mono: Optional[float]
    _last_snapshot_ops: int
    _qps_smoothed: Optional[float]
    _qps_windowed: Optional[float]
    _qps_window_seconds: float
    _qps_samples: Any
    _psutil: Any
    _process: Any
    _host_cpu_cores: Optional[int]
    _cgroup_prev_usage: Optional[float]
    _cgroup_prev_time_mono: Optional[float]
    _latency_sf_execution_ms: Any
    _latency_network_overhead_ms: Any
    _target_workers: int
    _qps_controller_state: dict[str, Any]
    _find_max_controller_state: dict[str, Any]
    _warehouse_query_status: dict[str, Any]
    metrics_callback: Optional[Callable[["Metrics"], None]]
    scenario: Any

    async def _collect_metrics(self) -> None:
        """Background task to collect and report metrics."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(1.0)
                await self._update_metrics_snapshot()

                if self.metrics_callback:
                    self.metrics_callback(self.metrics)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning("Metrics collection error: %s", e)

    async def _update_metrics_snapshot(self) -> None:
        """Update metrics with current snapshot data."""
        async with self._metrics_lock:
            now = datetime.now(UTC)
            now_mono = time.monotonic()

            # Calculate QPS from operations delta
            if self._last_snapshot_mono is not None:
                elapsed = now_mono - self._last_snapshot_mono
                if elapsed > 0:
                    ops_delta = self.metrics.total_operations - self._last_snapshot_ops
                    instant_qps = ops_delta / elapsed

                    # EMA smoothing for display
                    alpha = 0.3
                    if self._qps_smoothed is None:
                        self._qps_smoothed = instant_qps
                    else:
                        self._qps_smoothed = alpha * instant_qps + (1 - alpha) * self._qps_smoothed

                    # Windowed QPS for controller stability
                    self._qps_samples.append((now_mono, self.metrics.total_operations))
                    cutoff = now_mono - self._qps_window_seconds
                    while self._qps_samples and self._qps_samples[0][0] < cutoff:
                        self._qps_samples.popleft()
                    if len(self._qps_samples) >= 2:
                        oldest_time, oldest_ops = self._qps_samples[0]
                        newest_time, newest_ops = self._qps_samples[-1]
                        window_elapsed = newest_time - oldest_time
                        if window_elapsed > 0:
                            self._qps_windowed = (newest_ops - oldest_ops) / window_elapsed

                    self.metrics.current_qps = self._qps_smoothed or 0.0

            self._last_snapshot_time = now
            self._last_snapshot_mono = now_mono
            self._last_snapshot_ops = self.metrics.total_operations

            # Calculate latency percentiles from rolling buffer
            if self._latencies_ms:
                sorted_lat = sorted(self._latencies_ms)
                n = len(sorted_lat)
                self.metrics.p50_latency_ms = sorted_lat[int(n * 0.50)]
                self.metrics.p95_latency_ms = sorted_lat[int(n * 0.95)]
                self.metrics.p99_latency_ms = sorted_lat[min(int(n * 0.99), n - 1)]

            # Calculate average QPS over measurement window
            if hasattr(self, "_measurement_start_time") and self._measurement_start_time:
                measurement_elapsed = (now - self._measurement_start_time).total_seconds()
                if measurement_elapsed > 0:
                    self.metrics.avg_qps = self.metrics.total_operations / measurement_elapsed

            # System resource metrics
            self._collect_system_metrics()

            # Attach controller state for WebSocket
            self.metrics.qps_controller_state = dict(self._qps_controller_state)
            self.metrics.find_max_controller_state = dict(self._find_max_controller_state)
            self.metrics.warehouse_query_status = dict(self._warehouse_query_status)
            self.metrics.target_workers = self._target_workers

            # Latency breakdown (SF execution vs network overhead)
            if self._latency_sf_execution_ms:
                sf_sorted = sorted(self._latency_sf_execution_ms)
                n = len(sf_sorted)
                self.metrics.sf_execution_p50_ms = sf_sorted[int(n * 0.50)]
                self.metrics.sf_execution_p95_ms = sf_sorted[int(n * 0.95)]
            if self._latency_network_overhead_ms:
                net_sorted = sorted(self._latency_network_overhead_ms)
                n = len(net_sorted)
                self.metrics.network_overhead_p50_ms = net_sorted[int(n * 0.50)]
                self.metrics.network_overhead_p95_ms = net_sorted[int(n * 0.95)]

    def _collect_system_metrics(self) -> None:
        """Collect system resource metrics (CPU, memory)."""
        if self._psutil is None or self._process is None:
            return

        try:
            # Process CPU (non-blocking, returns delta since last call)
            cpu_pct = self._process.cpu_percent(interval=None)
            if cpu_pct is not None and math.isfinite(cpu_pct):
                self.metrics.cpu_percent = cpu_pct

            # Process memory
            mem_info = self._process.memory_info()
            if mem_info:
                self.metrics.memory_mb = mem_info.rss / (1024 * 1024)

            # Host CPU (for container awareness)
            host_cpu = self._psutil.cpu_percent(interval=None)
            if host_cpu is not None and math.isfinite(host_cpu):
                self.metrics.host_cpu_percent = host_cpu

            # cgroup limits (for container environments)
            cgroup = self._read_cgroup_limits()
            if cgroup:
                self.metrics.cgroup_cpu_quota_cores = cgroup.get("cpu_quota_cores")
                self.metrics.cgroup_memory_limit_mb = cgroup.get("memory_limit_mb")
                if cgroup.get("memory_mb") and cgroup.get("memory_limit_mb"):
                    self.metrics.cgroup_memory_percent = (
                        cgroup["memory_mb"] / cgroup["memory_limit_mb"] * 100.0
                    )
                # Calculate cgroup CPU percent from usage delta
                cgroup_cpu_pct = self._sample_cgroup_cpu_percent(
                    usage=cgroup.get("cpu_usage"),
                    usage_unit=cgroup.get("cpu_usage_unit"),
                    cpu_cores=cgroup.get("cpu_quota_cores"),
                )
                if cgroup_cpu_pct is not None:
                    self.metrics.cgroup_cpu_percent = cgroup_cpu_pct

        except Exception as e:
            logger.debug("System metrics collection error: %s", e)

    def _read_text(self, path: str) -> str | None:
        """Read text from a file path."""
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except Exception:
            return None

    def _read_int(self, path: str) -> int | None:
        """Read an integer from a file path."""
        raw = self._read_text(path)
        if raw is None:
            return None
        try:
            return int(raw.strip())
        except Exception:
            return None

    def _read_cgroup_limits(self) -> dict[str, Any] | None:
        """Read cgroup resource limits."""
        root = "/sys/fs/cgroup"
        if not os.path.isdir(root):
            return None
        # cgroup v2 has cgroup.controllers at the root.
        if os.path.exists(os.path.join(root, "cgroup.controllers")):
            return self._read_cgroup_v2(root)
        return self._read_cgroup_v1()

    def _read_cgroup_v2(self, root: str) -> dict[str, Any] | None:
        """Read cgroup v2 limits."""
        cpu_max = self._read_text(os.path.join(root, "cpu.max"))
        cpu_stat = self._read_text(os.path.join(root, "cpu.stat"))
        mem_current = self._read_text(os.path.join(root, "memory.current"))
        mem_max = self._read_text(os.path.join(root, "memory.max"))

        cpu_quota_cores: float | None = None
        if cpu_max:
            parts = cpu_max.split()
            if len(parts) >= 2 and parts[0] != "max":
                try:
                    quota = float(parts[0])
                    period = float(parts[1])
                    if period > 0:
                        cpu_quota_cores = quota / period
                except Exception:
                    cpu_quota_cores = None

        cpu_usage: float | None = None
        if cpu_stat:
            for line in cpu_stat.splitlines():
                if line.startswith("usage_usec"):
                    try:
                        cpu_usage = float(line.split()[1])
                    except Exception:
                        cpu_usage = None
                    break

        memory_mb: float | None = None
        if mem_current:
            try:
                memory_mb = float(mem_current) / (1024 * 1024)
            except Exception:
                memory_mb = None

        memory_limit_mb: float | None = None
        if mem_max and mem_max != "max":
            try:
                memory_limit_mb = float(mem_max) / (1024 * 1024)
            except Exception:
                memory_limit_mb = None

        if (
            cpu_quota_cores is None
            and cpu_usage is None
            and memory_mb is None
            and memory_limit_mb is None
        ):
            return None

        return {
            "cpu_quota_cores": cpu_quota_cores,
            "cpu_usage": cpu_usage,
            "cpu_usage_unit": "usec",
            "memory_mb": memory_mb,
            "memory_limit_mb": memory_limit_mb,
        }

    def _read_cgroup_v1(self) -> dict[str, Any] | None:
        """Read cgroup v1 limits."""
        cpu_dir = "/sys/fs/cgroup/cpu"
        cpuacct_dir = "/sys/fs/cgroup/cpuacct"
        mem_dir = "/sys/fs/cgroup/memory"

        cpu_quota_cores: float | None = None
        quota_us = self._read_int(os.path.join(cpu_dir, "cpu.cfs_quota_us"))
        period_us = self._read_int(os.path.join(cpu_dir, "cpu.cfs_period_us"))
        if (
            quota_us is not None
            and period_us is not None
            and quota_us > 0
            and period_us > 0
        ):
            cpu_quota_cores = float(quota_us) / float(period_us)

        cpu_usage: float | None = None
        usage_ns = self._read_int(os.path.join(cpuacct_dir, "cpuacct.usage"))
        if usage_ns is not None:
            cpu_usage = float(usage_ns)

        memory_mb: float | None = None
        mem_usage = self._read_int(os.path.join(mem_dir, "memory.usage_in_bytes"))
        if mem_usage is not None:
            memory_mb = float(mem_usage) / (1024 * 1024)

        memory_limit_mb: float | None = None
        mem_limit = self._read_int(os.path.join(mem_dir, "memory.limit_in_bytes"))
        if mem_limit is not None:
            # Ignore "unlimited" sentinel values.
            if mem_limit < (1 << 60):
                memory_limit_mb = float(mem_limit) / (1024 * 1024)

        if (
            cpu_quota_cores is None
            and cpu_usage is None
            and memory_mb is None
            and memory_limit_mb is None
        ):
            return None

        return {
            "cpu_quota_cores": cpu_quota_cores,
            "cpu_usage": cpu_usage,
            "cpu_usage_unit": "nsec",
            "memory_mb": memory_mb,
            "memory_limit_mb": memory_limit_mb,
        }

    def _sample_cgroup_cpu_percent(
        self,
        *,
        usage: float | None,
        usage_unit: str | None,
        cpu_cores: float | None,
    ) -> float | None:
        """Sample cgroup CPU percent from usage delta."""
        if usage is None or cpu_cores is None or cpu_cores <= 0:
            return None
        now_mono = time.monotonic()
        if self._cgroup_prev_usage is None or self._cgroup_prev_time_mono is None:
            self._cgroup_prev_usage = usage
            self._cgroup_prev_time_mono = now_mono
            return None
        delta_t = now_mono - self._cgroup_prev_time_mono
        delta_usage = usage - self._cgroup_prev_usage
        self._cgroup_prev_usage = usage
        self._cgroup_prev_time_mono = now_mono
        if delta_t <= 0 or delta_usage < 0:
            return None
        if usage_unit == "nsec":
            used_seconds = delta_usage / 1e9
        else:
            used_seconds = delta_usage / 1e6
        pct = (used_seconds / (delta_t * cpu_cores)) * 100.0
        if math.isfinite(pct):
            return pct
        return None

    def set_metrics_callback(self, callback: Callable[["Metrics"], None]) -> None:
        """
        Set callback for real-time metrics updates.

        Args:
            callback: Function to call with metrics updates
        """
        self.metrics_callback = callback
