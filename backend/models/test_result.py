"""
Test Result Models

Defines Pydantic models for test results and runs.
"""

from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class TestStatus(str, Enum):
    """Test execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorInfo(BaseModel):
    """Information about an error that occurred."""

    timestamp: datetime = Field(..., description="When the error occurred")
    error_type: str = Field(..., description="Type of error")
    error_message: str = Field(..., description="Error message")
    query: Optional[str] = Field(None, description="Query that caused error")
    connection_id: Optional[int] = Field(None, description="Connection ID")
    stack_trace: Optional[str] = Field(None, description="Stack trace")


class QueryExecution(BaseModel):
    """Details of a single query execution."""

    query_id: str = Field(..., description="Unique query ID")
    query_text: str = Field(..., description="Query text")
    start_time: datetime = Field(..., description="Query start time")
    end_time: datetime = Field(..., description="Query end time")
    duration_ms: float = Field(..., description="Execution duration (ms)")
    rows_affected: Optional[int] = Field(None, description="Rows affected")
    bytes_scanned: Optional[int] = Field(None, description="Bytes scanned")
    warehouse: Optional[str] = Field(None, description="Warehouse used")
    success: bool = Field(..., description="Query succeeded")
    error: Optional[str] = Field(None, description="Error message if failed")


class TestResult(BaseModel):
    """
    Results from a single test execution.

    Contains aggregated metrics and detailed results.
    """

    # Identification
    test_id: UUID = Field(default_factory=uuid4, description="Unique test ID")
    test_name: str = Field(..., description="Test name")
    scenario_name: str = Field(..., description="Scenario that was executed")

    # Test configuration summary
    table_name: str = Field(..., description="Table tested")
    table_type: str = Field(..., description="Type of table")
    warehouse: Optional[str] = Field(None, description="Warehouse used")
    warehouse_size: Optional[str] = Field(None, description="Warehouse size")

    # Execution metadata
    status: TestStatus = Field(..., description="Test status")
    start_time: datetime = Field(..., description="Test start time")
    end_time: Optional[datetime] = Field(None, description="Test end time")
    duration_seconds: Optional[float] = Field(
        None, description="Actual duration (seconds)"
    )

    # Workload summary
    # Note: "total_threads" is the new canonical name; "concurrent_connections" is kept as alias
    total_threads: int = Field(
        ..., alias="concurrent_connections", description="Number of concurrent threads"
    )
    total_operations: int = Field(0, description="Total operations executed")
    read_operations: int = Field(0, description="Read operations")
    write_operations: int = Field(0, description="Write operations")
    failed_operations: int = Field(0, description="Failed operations")

    # Performance metrics
    qps: float = Field(0.0, description="Average QPS")
    reads_per_second: float = Field(0.0, description="Reads/sec")
    writes_per_second: float = Field(0.0, description="Writes/sec")

    # Latency metrics (milliseconds)
    avg_latency_ms: float = Field(0.0, description="Average latency")
    p50_latency_ms: float = Field(0.0, description="50th percentile")
    p90_latency_ms: float = Field(0.0, description="90th percentile")
    p95_latency_ms: float = Field(0.0, description="95th percentile")
    p99_latency_ms: float = Field(0.0, description="99th percentile")
    max_latency_ms: float = Field(0.0, description="Max latency")
    min_latency_ms: float = Field(0.0, description="Min latency")

    # Read vs write latency (end-to-end, measured by the app)
    read_p50_latency_ms: float = Field(0.0, description="Read p50 latency (ms)")
    read_p95_latency_ms: float = Field(0.0, description="Read p95 latency (ms)")
    read_p99_latency_ms: float = Field(0.0, description="Read p99 latency (ms)")
    read_min_latency_ms: float = Field(0.0, description="Read min latency (ms)")
    read_max_latency_ms: float = Field(0.0, description="Read max latency (ms)")

    write_p50_latency_ms: float = Field(0.0, description="Write p50 latency (ms)")
    write_p95_latency_ms: float = Field(0.0, description="Write p95 latency (ms)")
    write_p99_latency_ms: float = Field(0.0, description="Write p99 latency (ms)")
    write_min_latency_ms: float = Field(0.0, description="Write min latency (ms)")
    write_max_latency_ms: float = Field(0.0, description="Write max latency (ms)")

    # Per query kind latency (end-to-end, measured by the app)
    point_lookup_p50_latency_ms: float = Field(
        0.0, description="Point lookup p50 latency (ms)"
    )
    point_lookup_p95_latency_ms: float = Field(
        0.0, description="Point lookup p95 latency (ms)"
    )
    point_lookup_p99_latency_ms: float = Field(
        0.0, description="Point lookup p99 latency (ms)"
    )
    point_lookup_min_latency_ms: float = Field(
        0.0, description="Point lookup min latency (ms)"
    )
    point_lookup_max_latency_ms: float = Field(
        0.0, description="Point lookup max latency (ms)"
    )

    range_scan_p50_latency_ms: float = Field(
        0.0, description="Range scan p50 latency (ms)"
    )
    range_scan_p95_latency_ms: float = Field(
        0.0, description="Range scan p95 latency (ms)"
    )
    range_scan_p99_latency_ms: float = Field(
        0.0, description="Range scan p99 latency (ms)"
    )
    range_scan_min_latency_ms: float = Field(
        0.0, description="Range scan min latency (ms)"
    )
    range_scan_max_latency_ms: float = Field(
        0.0, description="Range scan max latency (ms)"
    )

    insert_p50_latency_ms: float = Field(0.0, description="Insert p50 latency (ms)")
    insert_p95_latency_ms: float = Field(0.0, description="Insert p95 latency (ms)")
    insert_p99_latency_ms: float = Field(0.0, description="Insert p99 latency (ms)")
    insert_min_latency_ms: float = Field(0.0, description="Insert min latency (ms)")
    insert_max_latency_ms: float = Field(0.0, description="Insert max latency (ms)")

    update_p50_latency_ms: float = Field(0.0, description="Update p50 latency (ms)")
    update_p95_latency_ms: float = Field(0.0, description="Update p95 latency (ms)")
    update_p99_latency_ms: float = Field(0.0, description="Update p99 latency (ms)")
    update_min_latency_ms: float = Field(0.0, description="Update min latency (ms)")
    update_max_latency_ms: float = Field(0.0, description="Update max latency (ms)")

    generic_sql_p50_latency_ms: float = Field(
        0.0, description="Generic SQL p50 latency (ms)"
    )
    generic_sql_p95_latency_ms: float = Field(
        0.0, description="Generic SQL p95 latency (ms)"
    )
    generic_sql_p99_latency_ms: float = Field(
        0.0, description="Generic SQL p99 latency (ms)"
    )
    generic_sql_min_latency_ms: float = Field(
        0.0, description="Generic SQL min latency (ms)"
    )
    generic_sql_max_latency_ms: float = Field(
        0.0, description="Generic SQL max latency (ms)"
    )

    # GENERIC_SQL throughput metrics
    generic_sql_rows_per_sec: Optional[float] = Field(
        None, description="Generic SQL rows processed per second"
    )
    generic_sql_bytes_scanned_per_sec: Optional[float] = Field(
        None, description="Generic SQL bytes scanned per second"
    )

    # Aggregate OLAP metrics (across all GENERIC_SQL queries)
    olap_total_operations: int = Field(0, description="Total OLAP/GENERIC_SQL operations")
    olap_total_rows_processed: int = Field(
        0, description="Total rows processed by OLAP queries"
    )
    olap_total_bytes_scanned: int = Field(
        0, description="Total bytes scanned by OLAP queries"
    )
    olap_metrics: Optional[Dict[str, Any]] = Field(
        None, description="Extensible per-kind OLAP metrics payload"
    )

    # Derived overhead percentiles (filled after enrichment)
    app_overhead_p50_ms: float = Field(0.0, description="App overhead p50 (ms)")
    app_overhead_p95_ms: float = Field(0.0, description="App overhead p95 (ms)")
    app_overhead_p99_ms: float = Field(0.0, description="App overhead p99 (ms)")

    # Throughput metrics
    bytes_read: int = Field(0, description="Total bytes read")
    bytes_written: int = Field(0, description="Total bytes written")
    rows_read: int = Field(0, description="Total rows read")
    rows_written: int = Field(0, description="Total rows written")

    # Resource utilization
    warehouse_credits_used: Optional[float] = Field(
        None, description="Snowflake credits consumed"
    )
    avg_cpu_percent: Optional[float] = Field(
        None, description="Average CPU utilization"
    )
    avg_memory_mb: Optional[float] = Field(
        None, description="Average memory usage (MB)"
    )

    # Errors and issues
    error_count: int = Field(0, description="Number of errors")
    error_rate: float = Field(0.0, description="Error rate (0.0-1.0)")
    failure_reason: Optional[str] = Field(
        None, description="Reason for test failure (setup/validation errors)"
    )
    errors: Optional[List[ErrorInfo]] = Field(
        None, description="Detailed error information"
    )

    # Query history (if collected)
    query_executions: Optional[List[QueryExecution]] = Field(
        None, description="Detailed query execution history"
    )

    # Time-series metrics (snapshots every N seconds)
    metrics_snapshots: Optional[List[Dict[str, Any]]] = Field(
        None, description="Time-series metrics snapshots"
    )

    # Configuration used
    test_config: Optional[Dict[str, Any]] = Field(
        None, description="Full test configuration"
    )

    # Custom metrics
    custom_metrics: Optional[Dict[str, Any]] = Field(
        None, description="Custom metrics specific to test"
    )

    # Tags and metadata
    tags: Optional[Dict[str, str]] = Field(None, description="Custom tags")
    notes: Optional[str] = Field(None, description="Additional notes")

    # Methodology metadata (benchmark reproducibility)
    run_temperature: Optional[float] = Field(
        None,
        description="Cache warmup temperature: 0.0=cold, 1.0=fully warmed",
    )
    trial_index: Optional[int] = Field(
        None,
        description="Trial index within a multi-trial run (1-based)",
    )
    realism_profile: Optional[str] = Field(
        None,
        description="Named realism profile (BASELINE, COLD_START, WARM_CACHE, etc.)",
    )

    model_config = ConfigDict(
        use_enum_values=True,
        populate_by_name=True,
        json_encoders={
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        },
    )


class TestRun(BaseModel):
    """
    A collection of related test results (e.g., comparing multiple configurations).
    """

    # Identification
    run_id: UUID = Field(default_factory=uuid4, description="Unique run ID")
    run_name: str = Field(..., description="Run name")
    description: Optional[str] = Field(None, description="Run description")

    # Execution metadata
    status: TestStatus = Field(..., description="Run status")
    start_time: datetime = Field(..., description="Run start time")
    end_time: Optional[datetime] = Field(None, description="Run end time")
    duration_seconds: Optional[float] = Field(None, description="Total duration")

    # Test results
    test_results: List[TestResult] = Field(
        default_factory=list, description="Individual test results"
    )

    # Summary statistics
    total_tests: int = Field(0, description="Total tests executed")
    successful_tests: int = Field(0, description="Successful tests")
    failed_tests: int = Field(0, description="Failed tests")

    # Comparison data (for side-by-side comparisons)
    comparison_baseline: Optional[UUID] = Field(
        None, description="Baseline test_id for comparison"
    )
    comparison_metrics: Optional[Dict[str, Any]] = Field(
        None, description="Computed comparison metrics"
    )

    # Environment information
    snowflake_account: Optional[str] = Field(None, description="Snowflake account")
    snowflake_region: Optional[str] = Field(None, description="Snowflake region")
    client_version: Optional[str] = Field(None, description="Benchmark tool version")
    client_platform: Optional[str] = Field(None, description="Client platform (OS)")

    # Tags and metadata
    tags: Optional[Dict[str, str]] = Field(None, description="Custom tags")
    notes: Optional[str] = Field(None, description="Additional notes")

    # User information
    created_by: Optional[str] = Field(None, description="User who created run")

    model_config = ConfigDict(
        use_enum_values=True,
        json_encoders={
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v),
        },
    )

    def add_test_result(self, result: TestResult):
        """Add a test result to this run."""
        self.test_results.append(result)
        self.total_tests += 1
        if result.status == TestStatus.COMPLETED:
            self.successful_tests += 1
        elif result.status == TestStatus.FAILED:
            self.failed_tests += 1

    def calculate_summary(self):
        """Calculate summary statistics from test results."""
        if not self.test_results:
            return

        # Update counts
        self.total_tests = len(self.test_results)
        self.successful_tests = sum(
            1 for r in self.test_results if r.status == TestStatus.COMPLETED
        )
        self.failed_tests = sum(
            1 for r in self.test_results if r.status == TestStatus.FAILED
        )

        # Calculate duration
        if self.start_time and self.end_time:
            self.duration_seconds = (self.end_time - self.start_time).total_seconds()
