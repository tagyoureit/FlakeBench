"""
File-based worker metrics logger for high-throughput benchmarks.

This module provides FileBasedMetricsLogger, which logs worker metrics snapshots
to local Parquet files during benchmark execution, then bulk loads to Snowflake
during the PROCESSING phase via PUT + COPY INTO.

This approach eliminates Snowflake lock contention by:
1. Buffering metrics in memory (no network I/O during benchmark)
2. Writing to local Parquet files in background thread
3. Deferring Snowflake writes to PROCESSING phase via bulk COPY INTO

The real-time dashboard continues to work via LiveMetricsCache (HTTP POST),
while WORKER_METRICS_SNAPSHOTS is populated for historical queries only.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pyarrow as pa

from backend.core.file_logger_base import FileBasedLoggerBase

if TYPE_CHECKING:
    from backend.models.metrics import Metrics


class FileBasedMetricsLogger(FileBasedLoggerBase):
    """
    Logs worker metrics snapshots to local Parquet files during benchmark,
    then bulk loads to Snowflake during the PROCESSING phase.

    This eliminates lock contention on WORKER_METRICS_SNAPSHOTS by:
    1. Buffering metrics locally (no Snowflake INSERTs during benchmark)
    2. Writing Parquet files in background thread (decouples disk I/O)
    3. Bulk loading via PUT + COPY INTO after benchmark completes

    Usage:
        logger = FileBasedMetricsLogger(test_id, worker_id, results_prefix, ...)

        # During benchmark - called from metrics callback
        logger.append_metrics(metrics, phase=phase, target_connections=target)

        # During PROCESSING phase
        await logger.finalize(pool)  # PUT + COPY INTO + cleanup
    """

    # Metrics snapshots are smaller, use lower thresholds
    DEFAULT_MAX_ROWS_PER_FILE = 100_000
    DEFAULT_BUFFER_SIZE = 10_000

    def __init__(
        self,
        test_id: str,
        worker_id: str | int,
        results_prefix: str,
        *,
        run_id: str,
        worker_group_id: int,
        worker_group_count: int,
        max_rows_per_file: int | None = None,
        buffer_size: int | None = None,
    ) -> None:
        """
        Initialize the file-based metrics logger.

        Args:
            test_id: Unique identifier for the test run.
            worker_id: Worker identifier (e.g., "worker-0" or integer).
            results_prefix: Snowflake schema prefix (e.g., "DB.SCHEMA").
            run_id: Run identifier for all snapshots.
            worker_group_id: Worker group ID.
            worker_group_count: Total workers in group.
            max_rows_per_file: Max rows before rotating to new file.
            buffer_size: Rows to buffer before flushing to disk.
        """
        # Store run-level context needed for every record
        self._run_id = run_id
        self._worker_group_id = worker_group_id
        self._worker_group_count = worker_group_count

        super().__init__(
            test_id,
            worker_id,
            results_prefix,
            max_rows_per_file=max_rows_per_file,
            buffer_size=buffer_size,
        )

    @property
    def _file_prefix(self) -> str:
        """Return prefix for temp files."""
        return "wm"

    @property
    def _stage_name(self) -> str:
        """Return Snowflake stage name."""
        return "WORKER_METRICS_STAGE"

    @property
    def _table_name(self) -> str:
        """Return target table name."""
        return "WORKER_METRICS_SNAPSHOTS"

    @property
    def _json_columns(self) -> list[str]:
        """Return columns that need JSON parsing after COPY INTO."""
        return ["CUSTOM_METRICS"]

    def _build_schema(self) -> pa.Schema:
        """Build PyArrow schema matching WORKER_METRICS_SNAPSHOTS table.

        NOTE: Timestamps use pa.timestamp("us", "UTC") to set isAdjustedToUTC=true
        in the Parquet schema. This ensures Snowflake COPY INTO correctly interprets
        the microsecond values.
        """
        return pa.schema(
            [
                ("snapshot_id", pa.string()),
                ("run_id", pa.string()),
                ("test_id", pa.string()),
                ("worker_id", pa.string()),
                ("worker_group_id", pa.int64()),
                ("worker_group_count", pa.int64()),
                ("timestamp", pa.timestamp("us", "UTC")),
                ("elapsed_seconds", pa.float64()),
                ("phase", pa.string()),
                ("total_queries", pa.int64()),
                ("read_count", pa.int64()),
                ("write_count", pa.int64()),
                ("error_count", pa.int64()),
                ("qps", pa.float64()),
                ("p50_latency_ms", pa.float64()),
                ("p95_latency_ms", pa.float64()),
                ("p99_latency_ms", pa.float64()),
                ("avg_latency_ms", pa.float64()),
                ("min_latency_ms", pa.float64()),
                ("max_latency_ms", pa.float64()),
                ("active_connections", pa.int64()),
                ("target_connections", pa.int64()),
                ("cpu_percent", pa.float64()),
                ("memory_percent", pa.float64()),
                ("custom_metrics", pa.string()),  # JSON string, parsed during COPY INTO
            ]
        )

    def append_metrics(
        self,
        metrics: Metrics,
        *,
        phase: str | None = None,
        target_connections: int = 0,
    ) -> None:
        """
        Add a metrics snapshot to the buffer.

        This is a convenience method that wraps append() with metrics-specific
        context. The run_id, worker_group_id, etc. are set at initialization.

        Args:
            metrics: Metrics object with snapshot data.
            phase: Current phase (WARMUP, MEASUREMENT, etc.).
            target_connections: Current target connection count.
        """
        self.append((metrics, phase, target_connections))

    def _transform_record(self, record: Any) -> dict[str, Any]:
        """Transform (Metrics, phase, target_connections) tuple to schema-compatible dict."""
        metrics, phase, target_connections = record

        # Extract cpu/memory from custom_metrics if available
        cpu_percent = metrics.cpu_percent
        memory_percent = None

        resources = (metrics.custom_metrics or {}).get("resources")
        if isinstance(resources, dict):
            mem_pct = resources.get("cgroup_memory_percent") or resources.get(
                "host_memory_percent"
            )
            if mem_pct is not None:
                memory_percent = float(mem_pct)

            cpu_pct = resources.get("cgroup_cpu_percent") or resources.get(
                "host_cpu_percent"
            )
            if cpu_pct is not None:
                cpu_percent = float(cpu_pct)

        return {
            "snapshot_id": str(uuid4()),
            "run_id": self._run_id,
            "test_id": self.test_id,
            "worker_id": str(self.worker_id),
            "worker_group_id": self._worker_group_id,
            "worker_group_count": self._worker_group_count,
            "timestamp": metrics.timestamp,
            "elapsed_seconds": float(metrics.elapsed_seconds),
            "phase": str(phase).upper() if phase else None,
            "total_queries": int(metrics.total_operations),
            "read_count": int(metrics.read_metrics.count),
            "write_count": int(metrics.write_metrics.count),
            "error_count": int(metrics.failed_operations),
            "qps": float(metrics.current_qps),
            "p50_latency_ms": float(metrics.overall_latency.p50),
            "p95_latency_ms": float(metrics.overall_latency.p95),
            "p99_latency_ms": float(metrics.overall_latency.p99),
            "avg_latency_ms": float(metrics.overall_latency.avg),
            "min_latency_ms": float(metrics.overall_latency.min),
            "max_latency_ms": float(metrics.overall_latency.max),
            "active_connections": int(metrics.active_connections),
            "target_connections": int(target_connections),
            "cpu_percent": float(cpu_percent) if cpu_percent is not None else None,
            "memory_percent": memory_percent,
            "custom_metrics": json.dumps(metrics.custom_metrics or {}),
        }
