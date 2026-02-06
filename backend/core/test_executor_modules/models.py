"""
Data models for test execution.
"""

from dataclasses import dataclass
from datetime import datetime
from collections.abc import Iterator
from typing import Any, Optional

from backend.core.table_profiler import TableProfile


@dataclass
class TableRuntimeState:
    """Runtime state for a table during test execution."""
    profile: Optional[TableProfile] = None
    next_insert_id: Optional[int] = None
    insert_id_seq: Optional[Iterator[int]] = None
    # Per-worker insert sequences to avoid PK conflicts
    insert_id_seqs: Optional[dict[int, Iterator[int]]] = None


@dataclass
class QueryExecutionRecord:
    """Record of a single query execution."""
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
