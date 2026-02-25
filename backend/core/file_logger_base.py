"""
Abstract base class for file-based Snowflake bulk loaders.

This module provides FileBasedLoggerBase, an abstract base class that handles:
- In-memory buffering with configurable thresholds
- Background thread disk writes (decouples I/O from main loop)
- Parquet file generation with PyArrow
- PUT + COPY INTO bulk loading to Snowflake
- Cleanup of temporary files and stage data

Subclasses must implement:
- _build_schema(): Define PyArrow schema for Parquet files
- _transform_record(): Convert input records to schema-compatible dicts
- _stage_name: Property returning the Snowflake stage name
- _table_name: Property returning the target table name
- _file_prefix: Property returning prefix for temp files

See file_query_logger.py and file_metrics_logger.py for concrete implementations.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pyarrow as pa
import pyarrow.parquet as pq

if TYPE_CHECKING:
    from backend.connectors.snowflake_pool import SnowflakeConnectionPool

logger = logging.getLogger(__name__)


class FileBasedLoggerBase(ABC):
    """
    Abstract base class for file-based Snowflake bulk loaders.

    This approach eliminates event loop contention by:
    1. Using plain Python list for buffer (no async lock)
    2. Writing to local disk (no network I/O during benchmark)
    3. Deferring Snowflake writes to finalization phase

    Subclasses define schema, table/stage names, and record transformation.
    """

    # Default configuration - subclasses can override
    DEFAULT_MAX_ROWS_PER_FILE = 500_000
    DEFAULT_BUFFER_SIZE = 50_000

    def __init__(
        self,
        test_id: str,
        worker_id: int,
        results_prefix: str,
        *,
        max_rows_per_file: int | None = None,
        buffer_size: int | None = None,
    ) -> None:
        """
        Initialize the file-based logger.

        Args:
            test_id: Unique identifier for the test run.
            worker_id: Worker identifier (integer).
            results_prefix: Snowflake schema prefix (e.g., "DB.SCHEMA").
            max_rows_per_file: Max rows before rotating to new file.
            buffer_size: Rows to buffer before flushing to disk.
        """
        self.test_id = test_id
        self.worker_id = worker_id
        self.results_prefix = results_prefix
        self._max_rows_per_file = max_rows_per_file or self.DEFAULT_MAX_ROWS_PER_FILE
        self._buffer_size = buffer_size or self.DEFAULT_BUFFER_SIZE

        # In-memory buffer (plain list, no lock needed - single-threaded access)
        self._buffer: list[dict[str, Any]] = []

        # File management
        self._temp_dir = Path(
            tempfile.mkdtemp(prefix=f"{self._file_prefix}_{test_id}_{worker_id}_")
        )
        self._file_index = 0
        self._rows_in_current_file = 0
        self._total_rows = 0
        self._files_written: list[Path] = []

        # Parquet writer for incremental row group appends
        self._current_writer: pq.ParquetWriter | None = None

        # Background thread executor for disk writes
        self._write_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix=f"{self._file_prefix}_writer_{worker_id}"
        )
        self._pending_write = None
        self._write_lock = threading.Lock()

        # Build schema (subclass-defined)
        self._schema = self._build_schema()

        logger.info(
            "%s initialized: test_id=%s, worker_id=%s, temp_dir=%s",
            self.__class__.__name__,
            test_id,
            worker_id,
            self._temp_dir,
        )

    # -------------------------------------------------------------------------
    # Abstract methods - subclasses MUST implement
    # -------------------------------------------------------------------------

    @property
    @abstractmethod
    def _file_prefix(self) -> str:
        """Return prefix for temp files (e.g., 'qe' for query executions)."""
        ...

    @property
    @abstractmethod
    def _stage_name(self) -> str:
        """Return Snowflake stage name (e.g., 'QUERY_EXECUTIONS_STAGE')."""
        ...

    @property
    @abstractmethod
    def _table_name(self) -> str:
        """Return target table name (e.g., 'QUERY_EXECUTIONS')."""
        ...

    @abstractmethod
    def _build_schema(self) -> pa.Schema:
        """Build PyArrow schema matching target table columns."""
        ...

    @abstractmethod
    def _transform_record(self, record: Any) -> dict[str, Any]:
        """
        Transform input record to schema-compatible dict.

        Args:
            record: Input record (dataclass, dict, or domain object).

        Returns:
            Dict with keys matching schema field names.
        """
        ...

    @property
    def _json_columns(self) -> list[str]:
        """
        Return list of column names that contain JSON strings needing parsing.

        When Parquet files with string columns are COPY INTO'd to VARIANT columns,
        Snowflake stores the string as VARCHAR inside the VARIANT. This property
        identifies columns that should be parsed as JSON after COPY INTO.

        Override in subclasses that have JSON string columns mapped to VARIANT.

        Returns:
            List of column names (uppercase) to parse as JSON after COPY INTO.
        """
        return []

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

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
        """Wait for any pending background writes to complete."""
        if self._pending_write is not None:
            self._pending_write.result()
            self._pending_write = None

    def append(self, record: Any) -> None:
        """
        Add a record to the buffer.

        Designed to be extremely fast - no locks, no I/O during normal operation.
        Disk writes only occur when buffer reaches threshold.

        Args:
            record: Record to append (transformed via _transform_record).
        """
        record_dict = self._transform_record(record)
        self._buffer.append(record_dict)
        self._total_rows += 1

        # Flush to disk when buffer is full
        if len(self._buffer) >= self._buffer_size:
            self._flush_buffer_to_disk()

        # Start new file if current file is too large
        if self._rows_in_current_file >= self._max_rows_per_file:
            self._start_new_file()

    async def finalize(self, pool: SnowflakeConnectionPool) -> dict[str, Any]:
        """
        Finalize logging: flush buffer, upload to stage, COPY INTO, cleanup.

        Called after benchmark completes.

        Args:
            pool: Snowflake connection pool for stage operations.

        Returns:
            Stats dict with rows loaded, files processed, etc.
        """
        # 1. Final buffer flush
        self._flush_buffer_to_disk()

        # 2. Wait for pending background write
        if self._pending_write is not None:
            self._pending_write.result()
            self._pending_write = None

        # 3. Shut down write executor
        self._write_executor.shutdown(wait=True)

        # 4. Close writer to finalize Parquet file
        with self._write_lock:
            if self._current_writer is not None:
                self._current_writer.close()
                self._current_writer = None

        if not self._files_written:
            logger.info(
                "No %s records to upload for worker %s",
                self._table_name,
                self.worker_id,
            )
            return {"rows_loaded": 0, "files_processed": 0}

        stage_path = (
            f"@{self.results_prefix}.{self._stage_name}/{self.test_id}/{self.worker_id}"
        )

        try:
            # 5. PUT files to stage
            for file_path in self._files_written:
                put_sql = f"""
                    PUT file://{file_path} {stage_path}/
                    AUTO_COMPRESS=FALSE OVERWRITE=TRUE
                """
                await pool.execute_query(put_sql)
                logger.info("Uploaded %s to stage", file_path.name)

            # 6. COPY INTO target table
            copy_sql = f"""
                COPY INTO {self.results_prefix}.{self._table_name}
                FROM {stage_path}/
                FILE_FORMAT = (TYPE = PARQUET)
                MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
                ON_ERROR = CONTINUE
            """
            result = await pool.execute_query(copy_sql)

            rows_loaded = self._parse_copy_result(result)

            logger.info(
                "COPY INTO %s completed: %d rows from %d files",
                self._table_name,
                rows_loaded,
                len(self._files_written),
            )

            # 6b. Parse JSON columns that were loaded as VARCHAR strings
            # When Parquet string columns are COPY INTO'd to VARIANT columns,
            # Snowflake stores them as VARCHAR inside VARIANT. This step
            # converts them to proper parsed JSON for semi-structured access.
            json_cols = self._json_columns
            if json_cols:
                for col in json_cols:
                    parse_sql = f"""
                        UPDATE {self.results_prefix}.{self._table_name}
                        SET {col} = TRY_PARSE_JSON({col})
                        WHERE TEST_ID = '{self.test_id}'
                          AND WORKER_ID = {self.worker_id}
                          AND TYPEOF({col}) = 'VARCHAR'
                    """
                    await pool.execute_query(parse_sql)
                    logger.info(
                        "Parsed JSON column %s for test_id=%s, worker_id=%s",
                        col,
                        self.test_id,
                        self.worker_id,
                    )

            # 7. Cleanup stage files
            remove_sql = f"REMOVE {stage_path}/"
            await pool.execute_query(remove_sql)
            logger.info("Cleaned up stage files at %s", stage_path)

            return {
                "rows_loaded": rows_loaded,
                "files_processed": len(self._files_written),
                "total_rows_captured": self._total_rows,
            }

        finally:
            # 8. Cleanup local temp directory
            self._cleanup_local_files()

    def cleanup_on_error(self) -> None:
        """
        Cleanup method for error scenarios where finalize() won't be called.

        Call this in exception handlers to avoid orphaned temp files.
        """
        try:
            self._write_executor.shutdown(wait=False)
        except Exception:
            pass

        with self._write_lock:
            if self._current_writer is not None:
                try:
                    self._current_writer.close()
                except Exception:
                    pass
                self._current_writer = None

        self._cleanup_local_files()

    # -------------------------------------------------------------------------
    # Internal methods
    # -------------------------------------------------------------------------

    def _flush_buffer_to_disk(self) -> None:
        """Flush in-memory buffer to Parquet file using background thread."""
        if not self._buffer:
            return

        # Wait for pending write before starting new one
        if self._pending_write is not None:
            self._pending_write.result()
            self._pending_write = None

        rows_to_write = len(self._buffer)

        # Convert buffer to PyArrow table
        table = pa.Table.from_pylist(self._buffer, schema=self._schema)

        # Clear buffer immediately so append() can continue
        self._buffer = []

        # Track rows for file rotation
        self._rows_in_current_file += rows_to_write

        # Submit disk write to background thread
        self._pending_write = self._write_executor.submit(
            self._write_table_to_disk, table, rows_to_write
        )

    def _write_table_to_disk(self, table: pa.Table, rows_to_write: int) -> None:
        """Write PyArrow table to disk (runs in background thread)."""
        start_time = time.perf_counter()

        with self._write_lock:
            if self._current_writer is None:
                file_path = self._current_file_path()
                self._current_writer = pq.ParquetWriter(
                    file_path, self._schema, compression="snappy"
                )
                self._files_written.append(file_path)

            self._current_writer.write_table(table)

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        logger.debug(
            "Background flush: %d rows to %s in %.2fms",
            rows_to_write,
            self._current_file_path().name,
            elapsed_ms,
        )

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
            / f"{self._file_prefix}_{self.test_id}_{self.worker_id}_{self._file_index:04d}.parquet"
        )

    def _start_new_file(self) -> None:
        """Start a new file (when MAX_ROWS_PER_FILE reached)."""
        if self._pending_write is not None:
            self._pending_write.result()
            self._pending_write = None

        with self._write_lock:
            if self._current_writer is not None:
                self._current_writer.close()
                self._current_writer = None

        self._file_index += 1
        self._rows_in_current_file = 0
        logger.info("Starting new Parquet file: index=%d", self._file_index)

    def _parse_copy_result(self, result: Any) -> int:
        """Parse COPY INTO result to extract rows loaded."""
        try:
            if isinstance(result, list) and len(result) > 0:
                return sum(r.get("rows_loaded", 0) for r in result)
            return self._total_rows
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
