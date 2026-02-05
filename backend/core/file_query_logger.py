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
import logging
import shutil
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from backend.connectors.snowflake_pool import SnowflakeConnectionPool

logger = logging.getLogger(__name__)

# Configuration - see docs/plan/file-based-query-logging.md for sizing rationale
MAX_ROWS_PER_FILE = 500_000  # ~100-250MB per file (Snowflake optimal for COPY INTO)
BUFFER_SIZE = 50_000  # Flush to disk every 50K records (~25MB buffer)


class FileBasedQueryLogger:
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

    def __init__(
        self,
        test_id: str,
        worker_id: int,
        results_prefix: str,
    ) -> None:
        """
        Initialize the file-based query logger.

        Args:
            test_id: Unique identifier for the test run.
            worker_id: Worker identifier (integer).
            results_prefix: Snowflake schema prefix for results tables (e.g., "DB.SCHEMA").
        """
        self.test_id = test_id
        self.worker_id = worker_id
        self.results_prefix = results_prefix

        # In-memory buffer (plain list, no lock needed - single-threaded access)
        self._buffer: list[dict[str, Any]] = []

        # File management
        self._temp_dir = Path(
            tempfile.mkdtemp(prefix=f"qe_{test_id}_{worker_id}_")
        )
        self._file_index = 0
        self._rows_in_current_file = 0
        self._total_rows = 0
        self._files_written: list[Path] = []
        
        # Parquet writer for incremental row group appends (O(1) per flush)
        self._current_writer: pq.ParquetWriter | None = None
        
        # Background thread executor for disk writes (decouples I/O from query loop)
        self._write_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"qe_writer_{worker_id}")
        self._pending_write = None  # Track pending write future
        self._write_lock = threading.Lock()  # Protect writer access across threads

        # Schema for Parquet files (matches QUERY_EXECUTIONS table)
        self._schema = self._build_schema()

        logger.info(
            "FileBasedQueryLogger initialized: test_id=%s, worker_id=%s, temp_dir=%s",
            test_id,
            worker_id,
            self._temp_dir,
        )

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

    @property
    def stats(self) -> dict[str, Any]:
        """Return current logger statistics."""
        return {
            "total_rows": self._total_rows,
            "buffered_rows": len(self._buffer),
            "files_written": len(self._files_written),
            "current_file_rows": self._rows_in_current_file,
        }

    def wait_for_pending_writes(self) -> None:
        """Wait for any pending background writes to complete.
        
        Useful for testing and for ensuring writes complete before reading files.
        """
        if self._pending_write is not None:
            self._pending_write.result()
            self._pending_write = None

    def append(self, record: Any) -> None:
        """
        Add a record to the buffer.

        This is designed to be extremely fast - no locks, no I/O during normal
        operation. Disk writes only occur when buffer reaches BUFFER_SIZE.

        Args:
            record: QueryExecutionRecord dataclass or dict with execution data.
        """
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

        self._buffer.append(record_dict)
        self._total_rows += 1

        # Flush to disk when buffer is full
        if len(self._buffer) >= BUFFER_SIZE:
            self._flush_buffer_to_disk()

        # Start new file if current file is too large
        if self._rows_in_current_file >= MAX_ROWS_PER_FILE:
            self._start_new_file()

    def _flush_buffer_to_disk(self) -> None:
        """Flush in-memory buffer to current Parquet file using background thread.
        
        The actual disk I/O is offloaded to a background thread to avoid blocking
        the query loop. This completely decouples disk write latency from query
        execution throughput.
        """
        if not self._buffer:
            return

        # Wait for any pending write to complete before starting new one
        if self._pending_write is not None:
            self._pending_write.result()  # Block until previous write completes
            self._pending_write = None

        rows_to_write = len(self._buffer)
        
        # Convert buffer to PyArrow table (serialization happens in main thread)
        # This is fast (~10-20ms) and doesn't block queries much
        table = pa.Table.from_pylist(self._buffer, schema=self._schema)
        
        # Clear buffer immediately so append() can continue
        self._buffer = []
        
        # Track rows for file rotation logic
        self._rows_in_current_file += rows_to_write
        
        # Submit disk write to background thread
        self._pending_write = self._write_executor.submit(
            self._write_table_to_disk, table, rows_to_write
        )

    def _write_table_to_disk(self, table: pa.Table, rows_to_write: int) -> None:
        """Write PyArrow table to disk (runs in background thread)."""
        start_time = time.perf_counter()
        
        with self._write_lock:
            # Create writer if needed (lazy initialization)
            if self._current_writer is None:
                file_path = self._current_file_path()
                self._current_writer = pq.ParquetWriter(
                    file_path, self._schema, compression="snappy"
                )
                self._files_written.append(file_path)

            # Append as new row group - O(1), no read needed
            self._current_writer.write_table(table)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "Background flush: %d rows to %s in %.2fms",
            rows_to_write,
            self._current_file_path().name,
            elapsed_ms,
        )

        # Warn if flush is slow (but it no longer blocks queries!)
        if elapsed_ms > 100:
            logger.info(
                "Background flush took %.2fms for %d rows (non-blocking)",
                elapsed_ms,
                rows_to_write,
            )

    def _current_file_path(self) -> Path:
        """Get path to current Parquet file."""
        return (
            self._temp_dir
            / f"qe_{self.test_id}_{self.worker_id}_{self._file_index:04d}.parquet"
        )

    def _start_new_file(self) -> None:
        """Start a new file for subsequent records (when MAX_ROWS_PER_FILE reached)."""
        # Wait for any pending write to complete
        if self._pending_write is not None:
            self._pending_write.result()
            self._pending_write = None
        
        # Close current writer before starting new file
        with self._write_lock:
            if self._current_writer is not None:
                self._current_writer.close()
                self._current_writer = None
        
        self._file_index += 1
        self._rows_in_current_file = 0
        logger.info("Starting new Parquet file: index=%d", self._file_index)

    async def finalize(self, pool: SnowflakeConnectionPool) -> dict[str, Any]:
        """
        Finalize logging: flush buffer, upload to stage, COPY INTO, cleanup.

        Called during PROCESSING phase after benchmark completes.

        Args:
            pool: Snowflake connection pool for stage operations.

        Returns:
            Stats dict with rows loaded, files processed, etc.
        """
        # 1. Final buffer flush
        self._flush_buffer_to_disk()
        
        # 2. Wait for any pending background write to complete
        if self._pending_write is not None:
            self._pending_write.result()
            self._pending_write = None
        
        # 3. Shut down the write executor
        self._write_executor.shutdown(wait=True)
        
        # 4. Close writer to finalize the Parquet file
        with self._write_lock:
            if self._current_writer is not None:
                self._current_writer.close()
                self._current_writer = None

        if not self._files_written:
            logger.info(
                "No query execution records to upload for worker %s",
                self.worker_id,
            )
            return {"rows_loaded": 0, "files_processed": 0}

        stage_path = (
            f"@{self.results_prefix}.QUERY_EXECUTIONS_STAGE"
            f"/{self.test_id}/{self.worker_id}"
        )

        try:
            # 2. PUT files to stage
            for file_path in self._files_written:
                put_sql = f"""
                    PUT file://{file_path} {stage_path}/
                    AUTO_COMPRESS=FALSE OVERWRITE=TRUE
                """
                await pool.execute_query(put_sql)
                logger.info("Uploaded %s to stage", file_path.name)

            # 3. COPY INTO QUERY_EXECUTIONS
            copy_sql = f"""
                COPY INTO {self.results_prefix}.QUERY_EXECUTIONS
                FROM {stage_path}/
                FILE_FORMAT = (TYPE = PARQUET)
                MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
                ON_ERROR = CONTINUE
            """
            result = await pool.execute_query(copy_sql)

            # Parse COPY result for loaded row count
            rows_loaded = self._parse_copy_result(result)

            logger.info(
                "COPY INTO completed: %d rows from %d files",
                rows_loaded,
                len(self._files_written),
            )

            # 4. Cleanup stage files
            remove_sql = f"REMOVE {stage_path}/"
            await pool.execute_query(remove_sql)
            logger.info("Cleaned up stage files at %s", stage_path)

            return {
                "rows_loaded": rows_loaded,
                "files_processed": len(self._files_written),
                "total_rows_captured": self._total_rows,
            }

        finally:
            # 5. Cleanup local temp directory
            self._cleanup_local_files()

    def _parse_copy_result(self, result: Any) -> int:
        """Parse COPY INTO result to extract rows loaded."""
        try:
            if isinstance(result, list) and len(result) > 0:
                # COPY INTO returns list of dicts with file stats
                return sum(r.get("rows_loaded", 0) for r in result)
            return self._total_rows  # Fallback to tracked count
        except Exception:
            return self._total_rows

    def _cleanup_local_files(self) -> None:
        """Remove local temp directory and files."""
        try:
            if self._temp_dir.exists():
                shutil.rmtree(self._temp_dir)
                logger.info("Cleaned up local temp dir: %s", self._temp_dir)
        except Exception as e:
            logger.warning("Failed to cleanup temp dir %s: %s", self._temp_dir, e)

    def cleanup_on_error(self) -> None:
        """
        Cleanup method for error scenarios where finalize() won't be called.

        Call this in exception handlers to avoid orphaned temp files.
        """
        # Shut down background write executor
        try:
            self._write_executor.shutdown(wait=False)
        except Exception:
            pass
        
        # Close writer if open
        with self._write_lock:
            if self._current_writer is not None:
                try:
                    self._current_writer.close()
                except Exception:
                    pass  # Ignore errors during error cleanup
                self._current_writer = None
        
        self._cleanup_local_files()
