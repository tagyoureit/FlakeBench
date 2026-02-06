"""
Metrics collection mixin for test execution.

Handles real-time metrics gathering, QPS calculation, and resource sampling.
"""

import asyncio
import math
import time
import logging
from collections import deque
from datetime import datetime, UTC
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.models import Metrics

from backend.connectors import snowflake_pool

logger = logging.getLogger(__name__)


class MetricsCollectorMixin:
    """Mixin providing metrics collection functionality."""

    # These attributes are expected from TestExecutor
    scenario: Any
    metrics: "Metrics"
    table_managers: list
    _metrics_lock: asyncio.Lock
    _stop_event: asyncio.Event
    _latencies_ms: deque
    _latencies_measurement_ms: deque
    _last_snapshot_time: Optional[datetime]
    _last_snapshot_mono: Optional[float]
    _last_snapshot_ops: int
    _qps_smoothed: Optional[float]
    _qps_windowed: Optional[float]
    _qps_window_seconds: float
    _qps_samples: deque
    _benchmark_warehouse_name: Optional[str]
    _benchmark_query_tag: Optional[str]
    _warehouse_query_status: dict
    _last_warehouse_query_status_mono: Optional[float]
    _warehouse_query_status_task: Optional[asyncio.Task]
    _postgres_query_status: dict
    _last_postgres_query_status_mono: Optional[float]
    _postgres_query_status_task: Optional[asyncio.Task]
    _postgres_pool_for_polling: Any
    _qps_controller_state: dict
    _find_max_controller_state: dict
    _target_workers: int
    _latency_sf_execution_ms: deque
    _latency_network_overhead_ms: deque
    _psutil: Any
    _process: Any
    _host_cpu_cores: Optional[int]
    _cgroup_prev_usage: Optional[float]
    _cgroup_prev_time_mono: Optional[float]
    metrics_callback: Any
    workers: list

    def _sample_cgroup_cpu_percent(self) -> float | None:
        """
        Sample CPU usage from cgroup v2 (container-aware).

        Returns CPU percentage (0-100+) or None if unavailable.
        This is more accurate than psutil in containers where psutil
        sees host CPUs but cgroup limits actual usage.
        """
        try:
            with open("/sys/fs/cgroup/cpu.stat", "r") as f:
                for line in f:
                    if line.startswith("usage_usec"):
                        usage_usec = int(line.split()[1])
                        break
                else:
                    return None

            now_mono = time.monotonic()
            if self._cgroup_prev_usage is None or self._cgroup_prev_time_mono is None:
                self._cgroup_prev_usage = float(usage_usec)
                self._cgroup_prev_time_mono = now_mono
                return None

            delta_usec = float(usage_usec) - self._cgroup_prev_usage
            delta_time = now_mono - self._cgroup_prev_time_mono

            self._cgroup_prev_usage = float(usage_usec)
            self._cgroup_prev_time_mono = now_mono

            if delta_time <= 0:
                return None

            # Convert microseconds to percentage
            # delta_usec / 1_000_000 = seconds of CPU time
            # (seconds of CPU time / wall time) * 100 = percentage
            cpu_pct = (delta_usec / 1_000_000.0) / delta_time * 100.0
            return cpu_pct
        except Exception:
            return None

    async def _collect_metrics(self):
        """Collect metrics at regular intervals."""
        interval = float(getattr(self.scenario, "metrics_interval_seconds", 1.0) or 1.0)
        if not math.isfinite(interval) or interval <= 0:
            interval = 1.0

        loop = asyncio.get_running_loop()
        qps_tau_seconds = 5.0

        first_iteration = True
        try:
            while True:
                if first_iteration:
                    first_iteration = False
                else:
                    await asyncio.sleep(interval)

                now = datetime.now(UTC)
                now_mono = float(loop.time())
                self.metrics.timestamp = now

                # Derive "in-flight queries" from underlying pools
                in_use_total = 0
                idle_total = 0
                seen_pools: set[int] = set()
                for manager in self.table_managers:
                    pool = getattr(manager, "pool", None)
                    if pool is None or not hasattr(pool, "get_pool_stats"):
                        continue
                    pid = id(pool)
                    if pid in seen_pools:
                        continue
                    seen_pools.add(pid)
                    try:
                        stats = await pool.get_pool_stats()
                        in_use_total += int(stats.get("in_use") or 0)
                        idle_total += int(stats.get("available") or 0)
                    except Exception:
                        continue

                # Schedule Snowflake query-status telemetry sampling
                if self._benchmark_warehouse_name and self._benchmark_query_tag:
                    last = self._last_warehouse_query_status_mono
                    due = last is None or (now_mono - float(last)) >= 5.0
                    task = self._warehouse_query_status_task
                    if due and (task is None or task.done()):
                        self._warehouse_query_status_task = asyncio.create_task(
                            self._sample_warehouse_query_status(
                                self._benchmark_warehouse_name,
                                self._benchmark_query_tag,
                            )
                        )
                        self._last_warehouse_query_status_mono = now_mono

                # Schedule Postgres query-status telemetry sampling
                if self._postgres_pool_for_polling is not None:
                    last_pg = self._last_postgres_query_status_mono
                    due_pg = last_pg is None or (now_mono - float(last_pg)) >= 5.0
                    task_pg = self._postgres_query_status_task
                    if due_pg and (task_pg is None or task_pg.done()):
                        self._postgres_query_status_task = asyncio.create_task(
                            self._sample_postgres_query_status()
                        )
                        self._last_postgres_query_status_mono = now_mono

                # Calculate QPS
                async with self._metrics_lock:
                    total_ops = int(self.metrics.total_operations)

                qps_instant: float | None = None
                if self._last_snapshot_mono is not None:
                    dt_mono = now_mono - self._last_snapshot_mono
                    if dt_mono > 0:
                        delta_ops = total_ops - self._last_snapshot_ops
                        qps_instant = float(delta_ops) / dt_mono
                        self._qps_samples.append((now_mono, total_ops))

                        # EWMA smoothing
                        alpha = 1.0 - math.exp(-dt_mono / qps_tau_seconds)
                        if self._qps_smoothed is None:
                            self._qps_smoothed = qps_instant
                        else:
                            self._qps_smoothed = (
                                alpha * qps_instant + (1.0 - alpha) * self._qps_smoothed
                            )

                        # Windowed QPS
                        cutoff = now_mono - self._qps_window_seconds
                        while self._qps_samples and self._qps_samples[0][0] < cutoff:
                            self._qps_samples.popleft()
                        if len(self._qps_samples) >= 2:
                            t0, ops0 = self._qps_samples[0]
                            t1, ops1 = self._qps_samples[-1]
                            if t1 > t0:
                                self._qps_windowed = float(ops1 - ops0) / (t1 - t0)

                self._last_snapshot_time = now
                self._last_snapshot_mono = now_mono
                self._last_snapshot_ops = total_ops

                # Update metrics with computed values
                async with self._metrics_lock:
                    self.metrics.current_qps = (
                        float(self._qps_smoothed)
                        if self._qps_smoothed is not None
                        else 0.0
                    )

                    # Latency percentiles
                    if self._latencies_ms:
                        sorted_lat = sorted(self._latencies_ms)
                        n = len(sorted_lat)
                        self.metrics.avg_latency_ms = sum(sorted_lat) / n
                        self.metrics.p50_latency_ms = sorted_lat[int(n * 0.50)]
                        self.metrics.p95_latency_ms = sorted_lat[int(n * 0.95)]
                        self.metrics.p99_latency_ms = sorted_lat[int(n * 0.99)]

                    # Concurrency tracking
                    self.metrics.active_connections = in_use_total
                    self.metrics.idle_connections = idle_total
                    self.metrics.active_workers = len(
                        [t for t in self.workers if not t.done()]
                    )
                    self.metrics.target_workers = self._target_workers

                # Resource sampling
                if self._psutil and self._process:
                    try:
                        mem_info = self._process.memory_info()
                        self.metrics.memory_mb = mem_info.rss / (1024 * 1024)

                        cgroup_cpu = self._sample_cgroup_cpu_percent()
                        if cgroup_cpu is not None:
                            self.metrics.cpu_percent = cgroup_cpu
                        else:
                            self.metrics.cpu_percent = self._process.cpu_percent(
                                interval=None
                            )

                        if self._host_cpu_cores:
                            host_cpu = self._psutil.cpu_percent(interval=None)
                            self.metrics.host_cpu_percent = host_cpu
                    except Exception:
                        pass

                # Invoke callback
                if self.metrics_callback:
                    try:
                        self.metrics_callback(self.metrics)
                    except Exception as e:
                        logger.debug("Metrics callback error: %s", e)

        except asyncio.CancelledError:
            pass

    async def _sample_warehouse_query_status(
        self, warehouse_name: str, query_tag: str
    ) -> None:
        """Sample Snowflake warehouse query status for telemetry."""
        try:
            sample_mono = float(asyncio.get_running_loop().time())
            rows = await snowflake_pool.get_telemetry_pool().execute_query(
                """
                SELECT
                  SUM(IFF(UPPER(EXECUTION_STATUS) = 'RUNNING', 1, 0)) AS RUNNING,
                  SUM(IFF(UPPER(EXECUTION_STATUS) = 'QUEUED', 1, 0)) AS QUEUED,
                  SUM(IFF(UPPER(EXECUTION_STATUS) = 'BLOCKED', 1, 0)) AS BLOCKED,
                  SUM(IFF(UPPER(EXECUTION_STATUS) = 'RESUMING_WAREHOUSE', 1, 0)) AS RESUMING_WAREHOUSE,
                  SUM(IFF(
                    UPPER(EXECUTION_STATUS) = 'RUNNING'
                    AND CONTAINS(QUERY_TEXT, 'UB_KIND=POINT_LOOKUP'),
                    1, 0
                  )) AS RUNNING_POINT_LOOKUP,
                  SUM(IFF(
                    UPPER(EXECUTION_STATUS) = 'RUNNING'
                    AND CONTAINS(QUERY_TEXT, 'UB_KIND=RANGE_SCAN'),
                    1, 0
                  )) AS RUNNING_RANGE_SCAN,
                  SUM(IFF(
                    UPPER(EXECUTION_STATUS) = 'RUNNING'
                    AND CONTAINS(QUERY_TEXT, 'UB_KIND=INSERT'),
                    1, 0
                  )) AS RUNNING_INSERT,
                  SUM(IFF(
                    UPPER(EXECUTION_STATUS) = 'RUNNING'
                    AND CONTAINS(QUERY_TEXT, 'UB_KIND=UPDATE'),
                    1, 0
                  )) AS RUNNING_UPDATE
                FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY(
                  RESULT_LIMIT => 10000
                ))
                WHERE QUERY_TAG = ?
                  AND WAREHOUSE_NAME = ?
                  AND UPPER(EXECUTION_STATUS) IN (
                    'RUNNING', 'QUEUED', 'BLOCKED', 'RESUMING_WAREHOUSE'
                  )
                """,
                params=[str(query_tag), str(warehouse_name)],
            )
            if rows:
                row = rows[0]
                running = int(row[0] or 0)
                queued = int(row[1] or 0)
                blocked = int(row[2] or 0)
                resuming = int(row[3] or 0)
                running_pl = int(row[4] or 0)
                running_rs = int(row[5] or 0)
                running_ins = int(row[6] or 0)
                running_upd = int(row[7] or 0)
                running_read = int(running_pl + running_rs)
                running_write = int(running_ins + running_upd)

                self._warehouse_query_status = {
                    "running": running,
                    "queued": queued,
                    "blocked": blocked,
                    "resuming_warehouse": resuming,
                    "sample_mono": sample_mono,
                    "running_by_kind": {
                        "POINT_LOOKUP": running_pl,
                        "RANGE_SCAN": running_rs,
                        "INSERT": running_ins,
                        "UPDATE": running_upd,
                        "READ": running_read,
                        "WRITE": running_write,
                    },
                }
        except Exception as e:
            logger.debug("Failed to sample warehouse query status: %s", e)

    async def _sample_postgres_query_status(self) -> None:
        """Sample Postgres query status from pg_stat_activity."""
        pool = self._postgres_pool_for_polling
        if pool is None:
            return
        try:
            sample_mono = float(asyncio.get_running_loop().time())
            rows = await pool.execute_query(
                """
                SELECT
                  COUNT(*) FILTER (WHERE state = 'active') AS running,
                  COUNT(*) FILTER (WHERE wait_event_type = 'Lock') AS blocked
                FROM pg_stat_activity
                WHERE datname = current_database()
                  AND pid != pg_backend_pid()
                """
            )
            if rows:
                row = rows[0]
                self._postgres_query_status = {
                    "running": int(row[0] or 0),
                    "blocked": int(row[1] or 0),
                    "sample_mono": sample_mono,
                }
        except Exception as e:
            logger.debug("Failed to sample Postgres query status: %s", e)
