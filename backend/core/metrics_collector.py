"""
Metrics Collector

Real-time metrics collection, aggregation, and percentile calculation.
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional
from datetime import UTC, datetime
from collections import deque
from enum import Enum


from backend.models import (
    Metrics,
    MetricsSnapshot,
    LatencyPercentiles,
    OperationMetrics,
)

logger = logging.getLogger(__name__)


class OperationType(str, Enum):
    """Operation types for tracking."""

    READ = "read"
    WRITE = "write"
    UPDATE = "update"
    DELETE = "delete"


class QueryKind(str, Enum):
    """Query kind for per-kind latency tracking (maps to SLO categories)."""

    POINT_LOOKUP = "POINT_LOOKUP"
    RANGE_SCAN = "RANGE_SCAN"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    GENERIC_SQL = "GENERIC_SQL"


class OperationResult:
    """Result of a single operation."""

    def __init__(
        self,
        operation_type: OperationType,
        success: bool,
        latency_ms: float,
        rows_affected: int = 0,
        bytes_transferred: int = 0,
        timestamp: Optional[datetime] = None,
        query_kind: Optional[QueryKind] = None,
    ):
        self.operation_type = operation_type
        self.success = success
        self.latency_ms = latency_ms
        self.rows_affected = rows_affected
        self.bytes_transferred = bytes_transferred
        self.timestamp = timestamp or datetime.now(UTC)
        self.query_kind = query_kind


class MetricsCollector:
    """
    Collects and aggregates performance metrics in real-time.

    Features:
    - Latency percentile calculation
    - Operation type breakdown
    - Time-series snapshots
    - Rolling window for recent operations
    - Thread-safe metrics access
    """

    def __init__(
        self,
        window_size: int = 10000,
        snapshot_interval_seconds: float = 1.0,
    ):
        """
        Initialize metrics collector.

        Args:
            window_size: Max operations to keep for percentile calculation
            snapshot_interval_seconds: Interval for creating snapshots
        """
        self.window_size = window_size
        self.snapshot_interval_seconds = snapshot_interval_seconds

        # Current metrics
        self.metrics = Metrics()
        self._metrics_lock = asyncio.Lock()

        # Operation history (for percentile calculation)
        self._operation_history: deque = deque(maxlen=window_size)
        self._read_latencies: deque = deque(maxlen=window_size)
        self._write_latencies: deque = deque(maxlen=window_size)
        self._update_latencies: deque = deque(maxlen=window_size)
        self._delete_latencies: deque = deque(maxlen=window_size)

        # Per-kind latency tracking (for SLO evaluation)
        # Maps QueryKind -> deque of latencies
        self._latencies_by_kind: Dict[str, deque] = {
            QueryKind.POINT_LOOKUP.value: deque(maxlen=window_size),
            QueryKind.RANGE_SCAN.value: deque(maxlen=window_size),
            QueryKind.INSERT.value: deque(maxlen=window_size),
            QueryKind.UPDATE.value: deque(maxlen=window_size),
            QueryKind.GENERIC_SQL.value: deque(maxlen=window_size),
        }
        # Per-kind operation counts and error counts
        self._counts_by_kind: Dict[str, int] = {k: 0 for k in self._latencies_by_kind}
        self._errors_by_kind: Dict[str, int] = {k: 0 for k in self._latencies_by_kind}

        # Time-series snapshots
        self.snapshots: List[MetricsSnapshot] = []
        self._max_snapshots = 3600  # ~1 hour at 1s intervals

        # Start time for elapsed calculation
        self.start_time: Optional[datetime] = None

        # Peak tracking
        self._last_snapshot_time: Optional[datetime] = None
        self._last_snapshot_ops: int = 0
        self._process = None
        try:
            import psutil as psutil_mod

            self._process = psutil_mod.Process()
            # Prime cpu_percent so subsequent calls return a delta.
            self._process.cpu_percent(interval=None)
        except Exception:
            self._process = None

        logger.info(
            f"MetricsCollector initialized: window={window_size}, interval={snapshot_interval_seconds}s"
        )

    def start(self):
        """Start metrics collection."""
        self.start_time = datetime.now(UTC)
        self.metrics.timestamp = self.start_time
        logger.info("✅ Metrics collection started")

    async def record_operation(self, result: OperationResult):
        """
        Record a single operation result.

        Args:
            result: Operation result to record
        """
        async with self._metrics_lock:
            # Update overall counters
            self.metrics.total_operations += 1

            if result.success:
                self.metrics.successful_operations += 1
            else:
                self.metrics.failed_operations += 1

            # Store latency for percentile calculation
            self._operation_history.append(result.latency_ms)

            # Track per-kind latencies for SLO evaluation
            if result.query_kind is not None:
                kind_key = (
                    result.query_kind.value
                    if isinstance(result.query_kind, QueryKind)
                    else str(result.query_kind).upper()
                )
                if kind_key in self._latencies_by_kind:
                    self._counts_by_kind[kind_key] += 1
                    if result.success:
                        self._latencies_by_kind[kind_key].append(result.latency_ms)
                    else:
                        self._errors_by_kind[kind_key] += 1

            # Update operation-specific metrics
            if result.operation_type == OperationType.READ:
                self._update_operation_metrics(
                    self.metrics.read_metrics, self._read_latencies, result
                )
                self.metrics.rows_read += result.rows_affected
                self.metrics.bytes_read += result.bytes_transferred

            elif result.operation_type == OperationType.WRITE:
                self._update_operation_metrics(
                    self.metrics.write_metrics, self._write_latencies, result
                )
                self.metrics.rows_written += result.rows_affected
                self.metrics.bytes_written += result.bytes_transferred

            elif result.operation_type == OperationType.UPDATE:
                self._update_operation_metrics(
                    self.metrics.update_metrics, self._update_latencies, result
                )

            elif result.operation_type == OperationType.DELETE:
                self._update_operation_metrics(
                    self.metrics.delete_metrics, self._delete_latencies, result
                )

    def _update_operation_metrics(
        self,
        op_metrics: OperationMetrics,
        latency_queue: deque,
        result: OperationResult,
    ):
        """Update metrics for a specific operation type."""
        op_metrics.count += 1

        if result.success:
            op_metrics.success_count += 1
            op_metrics.total_duration_ms += result.latency_ms
            latency_queue.append(result.latency_ms)
        else:
            op_metrics.error_count += 1

    async def calculate_metrics(self) -> Metrics:
        """
        Calculate current metrics with percentiles.

        Returns:
            Current metrics snapshot
        """
        async with self._metrics_lock:
            # Update timestamp and elapsed time
            self.metrics.timestamp = datetime.now(UTC)
            if self.start_time:
                self.metrics.elapsed_seconds = (
                    self.metrics.timestamp - self.start_time
                ).total_seconds()

            # Calculate overall latency percentiles
            if self._operation_history:
                self.metrics.overall_latency = self._calculate_percentiles(
                    list(self._operation_history)
                )

            # Calculate per-operation latency percentiles
            if self._read_latencies:
                self.metrics.read_metrics.latency = self._calculate_percentiles(
                    list(self._read_latencies)
                )

            if self._write_latencies:
                self.metrics.write_metrics.latency = self._calculate_percentiles(
                    list(self._write_latencies)
                )

            if self._update_latencies:
                self.metrics.update_metrics.latency = self._calculate_percentiles(
                    list(self._update_latencies)
                )

            if self._delete_latencies:
                self.metrics.delete_metrics.latency = self._calculate_percentiles(
                    list(self._delete_latencies)
                )

            # Calculate per-kind latencies for SLO evaluation (no lock needed, we're inside one)
            self.metrics.latencies_by_kind = self._get_latencies_by_kind_unlocked()

            # Calculate current QPS (since last snapshot)
            if self._last_snapshot_time:
                time_delta = (
                    self.metrics.timestamp - self._last_snapshot_time
                ).total_seconds()

                if time_delta > 0:
                    ops_delta = self.metrics.total_operations - self._last_snapshot_ops
                    self.metrics.current_qps = ops_delta / time_delta

                    # Update peak
                    if self.metrics.current_qps > self.metrics.peak_qps:
                        self.metrics.peak_qps = self.metrics.current_qps

            # Calculate average QPS
            if self.metrics.elapsed_seconds > 0:
                self.metrics.avg_qps = (
                    self.metrics.total_operations / self.metrics.elapsed_seconds
                )

            # Calculate throughput
            if self.metrics.elapsed_seconds > 0:
                self.metrics.bytes_per_second = (
                    self.metrics.bytes_read + self.metrics.bytes_written
                ) / self.metrics.elapsed_seconds
                self.metrics.rows_per_second = (
                    self.metrics.rows_read + self.metrics.rows_written
                ) / self.metrics.elapsed_seconds

            # Best-effort host resource sampling (per-process).
            if self._process is not None:
                try:
                    self.metrics.cpu_percent = float(
                        self._process.cpu_percent(interval=None)
                    )
                    self.metrics.memory_mb = float(self._process.memory_info().rss) / (
                        1024 * 1024
                    )
                except Exception:
                    pass

            # Update last snapshot tracking
            self._last_snapshot_time = self.metrics.timestamp
            self._last_snapshot_ops = self.metrics.total_operations

            return self.metrics

    def _calculate_percentiles(self, latencies: List[float]) -> LatencyPercentiles:
        """
        Calculate latency percentiles from a list of latency values.

        Args:
            latencies: List of latency values in milliseconds

        Returns:
            LatencyPercentiles with calculated values
        """
        if not latencies:
            return LatencyPercentiles()

        # Sort latencies
        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)

        # Calculate percentiles
        def percentile(p: float) -> float:
            """Calculate the p-th percentile (0.0 to 1.0)."""
            if n == 0:
                return 0.0

            k = (n - 1) * p
            f = int(k)
            c = k - f

            if f + 1 < n:
                return sorted_latencies[f] * (1 - c) + sorted_latencies[f + 1] * c
            else:
                return sorted_latencies[f]

        return LatencyPercentiles(
            p50=percentile(0.50),
            p75=percentile(0.75),
            p90=percentile(0.90),
            p95=percentile(0.95),
            p99=percentile(0.99),
            p999=percentile(0.999),
            min=sorted_latencies[0],
            max=sorted_latencies[-1],
            avg=sum(sorted_latencies) / n,
        )

    def _get_latencies_by_kind_unlocked(self) -> Dict[str, Dict[str, Any]]:
        """
        Get per-kind latency percentiles (internal, no lock).

        Must be called while holding _metrics_lock.

        Returns:
            Dict mapping query kind to latency stats
        """
        result: Dict[str, Dict[str, Any]] = {}
        for kind_key, latency_deque in self._latencies_by_kind.items():
            count = self._counts_by_kind.get(kind_key, 0)
            error_count = self._errors_by_kind.get(kind_key, 0)
            error_rate_pct = (error_count / count * 100) if count > 0 else 0.0

            if latency_deque:
                percentiles = self._calculate_percentiles(list(latency_deque))
                result[kind_key] = {
                    "p50": percentiles.p50,
                    "p95": percentiles.p95,
                    "p99": percentiles.p99,
                    "avg": percentiles.avg,
                    "min": percentiles.min,
                    "max": percentiles.max,
                    "count": count,
                    "error_count": error_count,
                    "error_rate_pct": error_rate_pct,
                }
            else:
                result[kind_key] = {
                    "p50": None,
                    "p95": None,
                    "p99": None,
                    "avg": None,
                    "min": None,
                    "max": None,
                    "count": count,
                    "error_count": error_count,
                    "error_rate_pct": error_rate_pct,
                }
        return result

    async def create_snapshot(self) -> MetricsSnapshot:
        """
        Create a snapshot of current metrics.

        Returns:
            MetricsSnapshot for time-series storage
        """
        # Calculate current metrics
        metrics = await self.calculate_metrics()

        # Create snapshot
        snapshot = MetricsSnapshot.from_metrics(metrics)

        # Store snapshot
        self.snapshots.append(snapshot)

        # Limit snapshot history
        if len(self.snapshots) > self._max_snapshots:
            self.snapshots.pop(0)

        return snapshot

    async def get_metrics(self) -> Metrics:
        """
        Get current metrics (thread-safe).

        Returns:
            Current metrics
        """
        async with self._metrics_lock:
            return self.metrics

    def get_snapshots(
        self,
        limit: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[MetricsSnapshot]:
        """
        Get time-series snapshots with optional filtering.

        Args:
            limit: Max number of snapshots to return
            start_time: Filter snapshots after this time
            end_time: Filter snapshots before this time

        Returns:
            List of snapshots
        """
        snapshots = self.snapshots

        # Filter by time
        if start_time:
            snapshots = [s for s in snapshots if s.timestamp >= start_time]

        if end_time:
            snapshots = [s for s in snapshots if s.timestamp <= end_time]

        # Limit results
        if limit:
            snapshots = snapshots[-limit:]

        return snapshots

    def get_summary(self) -> Dict[str, Any]:
        """
        Get summary statistics.

        Returns:
            Dict with summary statistics
        """
        return {
            "total_operations": self.metrics.total_operations,
            "successful_operations": self.metrics.successful_operations,
            "failed_operations": self.metrics.failed_operations,
            "success_rate": self.metrics.success_rate,
            "error_rate": self.metrics.error_rate,
            "elapsed_seconds": self.metrics.elapsed_seconds,
            "avg_qps": self.metrics.avg_qps,
            "peak_qps": self.metrics.peak_qps,
            "current_qps": self.metrics.current_qps,
            "overall_latency": self.metrics.overall_latency.to_dict(),
            "read_operations": self.metrics.read_metrics.count,
            "write_operations": self.metrics.write_metrics.count,
            "update_operations": self.metrics.update_metrics.count,
            "delete_operations": self.metrics.delete_metrics.count,
            "snapshots_collected": len(self.snapshots),
        }

    def get_latencies_by_kind(self) -> Dict[str, Dict[str, Any]]:
        """
        Get per-kind latency percentiles for SLO evaluation.

        Returns:
            Dict mapping query kind to latency stats:
            {
                "POINT_LOOKUP": {
                    "p50": 12.5, "p95": 45.2, "p99": 78.1,
                    "count": 1000, "error_count": 5, "error_rate_pct": 0.5
                },
                ...
            }
        """
        result: Dict[str, Dict[str, Any]] = {}
        for kind_key, latency_deque in self._latencies_by_kind.items():
            count = self._counts_by_kind.get(kind_key, 0)
            error_count = self._errors_by_kind.get(kind_key, 0)
            error_rate_pct = (error_count / count * 100) if count > 0 else 0.0

            if latency_deque:
                percentiles = self._calculate_percentiles(list(latency_deque))
                result[kind_key] = {
                    "p50": percentiles.p50,
                    "p95": percentiles.p95,
                    "p99": percentiles.p99,
                    "avg": percentiles.avg,
                    "min": percentiles.min,
                    "max": percentiles.max,
                    "count": count,
                    "error_count": error_count,
                    "error_rate_pct": error_rate_pct,
                }
            else:
                # No latencies recorded yet for this kind
                result[kind_key] = {
                    "p50": None,
                    "p95": None,
                    "p99": None,
                    "avg": None,
                    "min": None,
                    "max": None,
                    "count": count,
                    "error_count": error_count,
                    "error_rate_pct": error_rate_pct,
                }
        return result

    async def reset(self):
        """Reset all metrics (useful for warmup)."""
        async with self._metrics_lock:
            self.metrics = Metrics()
            self.metrics.timestamp = datetime.now(UTC)
            self._operation_history.clear()
            self._read_latencies.clear()
            self._write_latencies.clear()
            self._update_latencies.clear()
            self._delete_latencies.clear()
            # Reset per-kind tracking
            for kind_key in self._latencies_by_kind:
                self._latencies_by_kind[kind_key].clear()
                self._counts_by_kind[kind_key] = 0
                self._errors_by_kind[kind_key] = 0
            self.snapshots.clear()
            self.start_time = datetime.now(UTC)
            self._last_snapshot_time = None
            self._last_snapshot_ops = 0

            logger.info("Metrics reset")
