"""
File-based query execution logger for high-throughput benchmarks.

This module provides FileBasedQueryLogger, which logs query execution records
to local Parquet files during benchmark execution, then bulk loads to Snowflake
during the PROCESSING phase via PUT + COPY INTO.

This approach eliminates event loop contention by:
1. Using plain Python list for buffer (no async lock)
2. Writing to local disk (no network I/O during benchmark)
3. Deferring Snowflake writes to PROCESSING phase

See docs/plan/file-based-query-logging.md for architecture details.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

import pyarrow as pa

from backend.core.file_logger_base import FileBasedLoggerBase

# Re-export constants for backward compatibility with tests
MAX_ROWS_PER_FILE = FileBasedLoggerBase.DEFAULT_MAX_ROWS_PER_FILE
BUFFER_SIZE = FileBasedLoggerBase.DEFAULT_BUFFER_SIZE


class FileBasedQueryLogger(FileBasedLoggerBase):
    """
    Logs query execution records to local Parquet files during benchmark,
    then bulk loads to Snowflake during the PROCESSING phase.

    This approach eliminates event loop contention by:
    1. Using plain Python list for buffer (no async lock)
    2. Writing to local disk (no network I/O during benchmark)
    3. Deferring Snowflake writes to PROCESSING phase

    Usage:
        logger = FileBasedQueryLogger(test_id, worker_id, results_prefix)

        # During benchmark (WARMUP + MEASUREMENT phases)
        logger.append(record)  # Fast, synchronous, no I/O

        # During PROCESSING phase
        await logger.finalize(pool)  # PUT + COPY INTO + cleanup
    """

    @property
    def _file_prefix(self) -> str:
        """Return prefix for temp files."""
        return "qe"

    @property
    def _stage_name(self) -> str:
        """Return Snowflake stage name."""
        return "QUERY_EXECUTIONS_STAGE"

    @property
    def _table_name(self) -> str:
        """Return target table name."""
        return "QUERY_EXECUTIONS"

    @property
    def _json_columns(self) -> list[str]:
        """Return columns that need JSON parsing after COPY INTO."""
        return ["CUSTOM_METADATA"]

    def _build_schema(self) -> pa.Schema:
        """Build PyArrow schema matching QUERY_EXECUTIONS table.

        NOTE: Timestamps use pa.timestamp("us", "UTC") to set isAdjustedToUTC=true
        in the Parquet schema. This ensures Snowflake COPY INTO correctly interprets
        the microsecond values. Without UTC, Snowflake misinterprets the values as
        seconds, causing year overflow (e.g., year 56098631).
        """
        return pa.schema(
            [
                ("execution_id", pa.string()),
                ("test_id", pa.string()),
                ("query_id", pa.string()),
                ("query_text", pa.string()),
                ("start_time", pa.timestamp("us", "UTC")),
                ("end_time", pa.timestamp("us", "UTC")),
                ("duration_ms", pa.float64()),
                ("rows_affected", pa.int64()),
                ("bytes_scanned", pa.int64()),
                ("warehouse", pa.string()),
                ("success", pa.bool_()),
                ("error", pa.string()),
                ("connection_id", pa.int64()),
                ("custom_metadata", pa.string()),  # JSON string -> VARIANT
                ("query_kind", pa.string()),
                ("worker_id", pa.int64()),
                ("warmup", pa.bool_()),
                ("app_elapsed_ms", pa.float64()),
                ("sf_rows_inserted", pa.int64()),
                ("sf_rows_updated", pa.int64()),
                ("sf_rows_deleted", pa.int64()),
            ]
        )

    def _transform_record(self, record: Any) -> dict[str, Any]:
        """Transform QueryExecutionRecord to schema-compatible dict."""
        # Convert dataclass to dict if needed
        if hasattr(record, "__dataclass_fields__"):
            record_dict = asdict(record)
        else:
            record_dict = dict(record)

        # Derive sf_rows_* fields from rows_affected based on query_kind
        query_kind = (record_dict.get("query_kind") or "").strip().upper()
        rows_affected = record_dict.get("rows_affected")
        record_dict["sf_rows_inserted"] = (
            rows_affected if query_kind == "INSERT" else None
        )
        record_dict["sf_rows_updated"] = (
            rows_affected if query_kind == "UPDATE" else None
        )
        record_dict["sf_rows_deleted"] = (
            rows_affected if query_kind == "DELETE" else None
        )

        # Serialize custom_metadata to JSON string (will become VARIANT in Snowflake)
        custom_metadata = record_dict.get("custom_metadata")
        record_dict["custom_metadata"] = json.dumps(custom_metadata or {})

        # Remove fields not in our schema (sf_execution_ms, queue_wait_ms are
        # populated later from query history enrichment, not during logging)
        record_dict.pop("sf_execution_ms", None)
        record_dict.pop("queue_wait_ms", None)

        return record_dict
