"""
Type definitions and dataclasses for test executor.
"""

from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from typing import TYPE_CHECKING, Any, Iterator, Optional

if TYPE_CHECKING:
    from backend.core.table_profiler import TableProfile


@dataclass
class TableRuntimeState:
    """Runtime state for a table during test execution."""

    profile: Optional["TableProfile"] = None
    next_insert_id: Optional[int] = None
    insert_id_seq: Optional[Iterator[int]] = None


@dataclass
class QueryExecutionRecord:
    """Record of a single query execution for persistence."""

    execution_id: str
    test_id: str
    query_id: str
    query_text: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    success: bool
    error: Optional[str]
    warehouse: Optional[str]
    rows_affected: Optional[int]
    bytes_scanned: Optional[int]
    connection_id: Optional[int]
    custom_metadata: dict[str, Any]
    query_kind: str
    worker_id: int
    warmup: bool
    app_elapsed_ms: float
    sf_execution_ms: Optional[float] = None
    queue_wait_ms: Optional[float] = None


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
