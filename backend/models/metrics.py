"""
Metrics Models

Defines Pydantic models for real-time performance metrics.
"""

from typing import Optional, Dict, Any
from datetime import UTC, datetime

from pydantic import BaseModel, Field


class LatencyPercentiles(BaseModel):
    """Latency percentile metrics (in milliseconds)."""

    p50: float = Field(0.0, description="50th percentile (median)")
    p75: float = Field(0.0, description="75th percentile")
    p90: float = Field(0.0, description="90th percentile")
    p95: float = Field(0.0, description="95th percentile")
    p99: float = Field(0.0, description="99th percentile")
    p999: float = Field(0.0, description="99.9th percentile")
    min: float = Field(0.0, description="Minimum latency")
    max: float = Field(0.0, description="Maximum latency")
    avg: float = Field(0.0, description="Average latency")

    def to_dict(self) -> Dict[str, float]:
        """Convert to dictionary."""
        return {
            "p50": self.p50,
            "p75": self.p75,
            "p90": self.p90,
            "p95": self.p95,
            "p99": self.p99,
            "p999": self.p999,
            "min": self.min,
            "max": self.max,
            "avg": self.avg,
        }


class OperationMetrics(BaseModel):
    """Metrics for a specific operation type."""

    count: int = Field(0, description="Number of operations")
    success_count: int = Field(0, description="Successful operations")
    error_count: int = Field(0, description="Failed operations")
    total_duration_ms: float = Field(0.0, description="Total duration (ms)")
    latency: LatencyPercentiles = Field(
        default_factory=LatencyPercentiles, description="Latency percentiles"
    )

    @property
    def success_rate(self) -> float:
        """Calculate success rate (0.0-1.0)."""
        if self.count == 0:
            return 0.0
        return self.success_count / self.count

    @property
    def error_rate(self) -> float:
        """Calculate error rate (0.0-1.0)."""
        if self.count == 0:
            return 0.0
        return self.error_count / self.count

    @property
    def avg_latency_ms(self) -> float:
        """Calculate average latency."""
        if self.success_count == 0:
            return 0.0
        return self.total_duration_ms / self.success_count


class Metrics(BaseModel):
    """
    Real-time performance metrics collected during a test.

    These metrics are updated continuously during test execution
    and can be streamed to the UI via WebSocket.
    """

    # Timestamp
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Metrics timestamp (UTC)"
    )
    elapsed_seconds: float = Field(0.0, description="Elapsed time since test start")

    # Overall metrics
    total_operations: int = Field(0, description="Total operations")
    successful_operations: int = Field(0, description="Successful operations")
    failed_operations: int = Field(0, description="Failed operations")

    # QPS (queries per second)
    current_qps: float = Field(0.0, description="Current QPS")
    avg_qps: float = Field(0.0, description="Average QPS")
    peak_qps: float = Field(0.0, description="Peak QPS")

    # Operation breakdown
    read_metrics: OperationMetrics = Field(
        default_factory=OperationMetrics, description="Read operation metrics"
    )
    write_metrics: OperationMetrics = Field(
        default_factory=OperationMetrics, description="Write operation metrics"
    )
    update_metrics: OperationMetrics = Field(
        default_factory=OperationMetrics, description="Update operation metrics"
    )
    delete_metrics: OperationMetrics = Field(
        default_factory=OperationMetrics, description="Delete operation metrics"
    )

    # Overall latency
    overall_latency: LatencyPercentiles = Field(
        default_factory=LatencyPercentiles, description="Overall latency percentiles"
    )

    # Throughput metrics
    bytes_read: int = Field(0, description="Total bytes read")
    bytes_written: int = Field(0, description="Total bytes written")
    rows_read: int = Field(0, description="Total rows read")
    rows_written: int = Field(0, description="Total rows written")
    bytes_per_second: float = Field(0.0, description="Bytes/sec throughput")
    rows_per_second: float = Field(0.0, description="Rows/sec throughput")

    # Connection pool metrics
    active_connections: int = Field(0, description="Active connections")
    target_workers: int = Field(
        0, description="Target worker count (desired concurrency)"
    )
    idle_connections: int = Field(0, description="Idle connections")
    connection_errors: int = Field(0, description="Connection errors")
    connection_timeouts: int = Field(0, description="Connection timeouts")

    # Resource utilization (optional)
    cpu_percent: Optional[float] = Field(None, description="CPU utilization %")
    memory_mb: Optional[float] = Field(None, description="Memory usage (MB)")
    network_bytes_sent: Optional[int] = Field(None, description="Network bytes sent")
    network_bytes_recv: Optional[int] = Field(
        None, description="Network bytes received"
    )

    # Snowflake-specific metrics
    warehouse_name: Optional[str] = Field(None, description="Warehouse name")
    warehouse_size: Optional[str] = Field(None, description="Warehouse size")
    warehouse_running: Optional[bool] = Field(None, description="Warehouse running")
    queries_queued: Optional[int] = Field(None, description="Queued queries")

    # Custom metrics
    custom_metrics: Optional[Dict[str, Any]] = Field(None, description="Custom metrics")

    # Per-kind latencies for SLO evaluation (populated from MetricsCollector)
    latencies_by_kind: Optional[Dict[str, Dict[str, Any]]] = Field(
        None, description="Latencies by query kind (POINT_LOOKUP, RANGE_SCAN, etc.)"
    )

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    @property
    def success_rate(self) -> float:
        """Calculate overall success rate (0.0-1.0)."""
        if self.total_operations == 0:
            return 0.0
        return self.successful_operations / self.total_operations

    @property
    def error_rate(self) -> float:
        """Calculate overall error rate (0.0-1.0)."""
        if self.total_operations == 0:
            return 0.0
        return self.failed_operations / self.total_operations

    def to_websocket_payload(self) -> Dict[str, Any]:
        """
        Convert metrics to WebSocket payload format.

        Returns a simplified dict optimized for real-time streaming.
        """
        return {
            "timestamp": self.timestamp.isoformat(),
            "elapsed": self.elapsed_seconds,
            "ops": {
                "total": self.total_operations,
                "current_per_sec": self.current_qps,
                "avg_per_sec": self.avg_qps,
                "peak_per_sec": self.peak_qps,
            },
            "operations": {
                "reads": self.read_metrics.count,
                "writes": self.write_metrics.count,
                "updates": self.update_metrics.count,
                "deletes": self.delete_metrics.count,
            },
            "latency": {
                "p50": self.overall_latency.p50,
                "p95": self.overall_latency.p95,
                "p99": self.overall_latency.p99,
                "avg": self.overall_latency.avg,
            },
            # Per-kind latencies for SLO evaluation
            "latency_by_kind": self.latencies_by_kind or {},
            "throughput": {
                "bytes_per_sec": self.bytes_per_second,
                "rows_per_sec": self.rows_per_second,
            },
            "errors": {
                "count": self.failed_operations,
                "rate": self.error_rate,
            },
            "connections": {
                "active": self.active_connections,
                "target": self.target_workers,
                "idle": self.idle_connections,
            },
            # Extension point for control-loop + warehouse telemetry.
            # Persisted in METRICS_SNAPSHOTS.CUSTOM_METRICS as well.
            "custom_metrics": self.custom_metrics or {},
        }


class MetricsSnapshot(BaseModel):
    """
    A snapshot of metrics at a specific point in time.

    Used for storing time-series metrics data.
    """

    timestamp: datetime = Field(..., description="Snapshot timestamp")
    elapsed_seconds: float = Field(..., description="Elapsed time")

    # Core metrics
    total_operations: int = Field(..., description="Total operations")
    qps: float = Field(..., description="QPS")

    # Latency (simplified)
    p50_latency_ms: float = Field(..., description="P50 latency")
    p95_latency_ms: float = Field(..., description="P95 latency")
    p99_latency_ms: float = Field(..., description="P99 latency")
    avg_latency_ms: float = Field(..., description="Avg latency")

    # Operation counts
    read_count: int = Field(0, description="Read operations")
    write_count: int = Field(0, description="Write operations")
    error_count: int = Field(0, description="Failed operations")

    # Throughput
    bytes_per_second: float = Field(0.0, description="Bytes/sec")
    rows_per_second: float = Field(0.0, description="Rows/sec")

    # Connections
    active_connections: int = Field(0, description="Active connections")

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }

    @classmethod
    def from_metrics(cls, metrics: Metrics) -> "MetricsSnapshot":
        """Create a snapshot from full metrics."""
        return cls(
            timestamp=metrics.timestamp,
            elapsed_seconds=metrics.elapsed_seconds,
            total_operations=metrics.total_operations,
            qps=metrics.current_qps,
            p50_latency_ms=metrics.overall_latency.p50,
            p95_latency_ms=metrics.overall_latency.p95,
            p99_latency_ms=metrics.overall_latency.p99,
            avg_latency_ms=metrics.overall_latency.avg,
            read_count=metrics.read_metrics.count,
            write_count=metrics.write_metrics.count,
            error_count=metrics.failed_operations,
            bytes_per_second=metrics.bytes_per_second,
            rows_per_second=metrics.rows_per_second,
            active_connections=metrics.active_connections,
        )
