#!/usr/bin/env python3
"""
Unit tests for FileBasedQueryLogger.

Tests file-based query execution logging with local Parquet files
and deferred bulk loading to Snowflake.
"""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from datetime import datetime, UTC
from dataclasses import dataclass
from typing import Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
import pyarrow.parquet as pq

from backend.core.file_query_logger import (
    FileBasedQueryLogger,
    BUFFER_SIZE,
)

pytestmark = pytest.mark.asyncio

# Default test prefix to avoid settings import
TEST_PREFIX = "TEST_DB.TEST_SCHEMA"


@dataclass
class MockQueryExecutionRecord:
    """Mock query execution record dataclass for testing."""

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


def _make_mock_record(
    query_id: str = "test-query-001",
    query_kind: str = "POINT_LOOKUP",
    rows_affected: int = 1,
) -> MockQueryExecutionRecord:
    """Create a mock query execution record as a dataclass."""
    now = datetime.now(UTC)
    return MockQueryExecutionRecord(
        execution_id=f"exec-{query_id}",
        test_id="test-123",
        query_id=query_id,
        query_text="SELECT * FROM test WHERE id = 1",
        start_time=now,
        end_time=now,
        duration_ms=15.5,
        success=True,
        error=None,
        warehouse="TEST_WH",
        rows_affected=rows_affected,
        bytes_scanned=100,
        connection_id=0,
        custom_metadata={"bind_values": {"id": 1}},
        query_kind=query_kind,
        worker_id=1,
        warmup=False,
        app_elapsed_ms=15.5,
    )


def _make_mock_dict_record(
    query_id: str = "test-query-001",
    query_kind: str = "POINT_LOOKUP",
) -> dict:
    """Create a mock query execution record as a dict."""
    now = datetime.now(UTC)
    return {
        "execution_id": f"exec-{query_id}",
        "test_id": "test-123",
        "query_id": query_id,
        "query_text": "SELECT * FROM test WHERE id = 1",
        "start_time": now,
        "end_time": now,
        "duration_ms": 15.5,
        "success": True,
        "error": None,
        "warehouse": "TEST_WH",
        "rows_affected": 1,
        "bytes_scanned": 100,
        "connection_id": 0,
        "custom_metadata": {"bind_values": {"id": 1}},
        "query_kind": query_kind,
        "worker_id": 1,
        "warmup": False,
        "app_elapsed_ms": 15.5,
    }


def _make_mock_pool() -> AsyncMock:
    """Create a mock Snowflake connection pool."""
    pool = AsyncMock()
    pool.execute_query = AsyncMock(return_value=[{"rows_loaded": 100}])
    return pool


class TestFileBasedQueryLoggerCreation:
    """Tests for FileBasedQueryLogger initialization."""

    def test_logger_creation(self):
        """Test FileBasedQueryLogger initialization."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        assert logger.test_id == "test-123"
        assert logger.worker_id == 1
        assert logger.results_prefix == TEST_PREFIX
        assert logger._total_rows == 0
        assert len(logger._buffer) == 0
        assert len(logger._files_written) == 0
        assert logger._temp_dir.exists()

        # Cleanup
        logger.cleanup_on_error()

    def test_temp_directory_created(self):
        """Test that temp directory is created with correct naming."""
        logger = FileBasedQueryLogger(
            test_id="abc-123",
            worker_id=5,
            results_prefix=TEST_PREFIX,
        )

        assert logger._temp_dir.exists()
        assert "qe_abc-123_5_" in str(logger._temp_dir)

        # Cleanup
        logger.cleanup_on_error()


class TestAppendRecords:
    """Tests for appending records to buffer."""

    def test_append_dataclass_record(self):
        """Test appending a dataclass record."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        record = _make_mock_record("query-001")
        logger.append(record)

        assert logger._total_rows == 1
        assert len(logger._buffer) == 1
        assert logger._buffer[0]["query_id"] == "query-001"

        logger.cleanup_on_error()

    def test_append_dict_record(self):
        """Test appending a dict record."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        record = _make_mock_dict_record("query-002")
        logger.append(record)

        assert logger._total_rows == 1
        assert len(logger._buffer) == 1
        assert logger._buffer[0]["query_id"] == "query-002"

        logger.cleanup_on_error()

    def test_sf_rows_fields_derived_for_insert(self):
        """Test sf_rows_inserted is set for INSERT queries."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        record = _make_mock_record("query-001", query_kind="INSERT", rows_affected=100)
        logger.append(record)

        assert logger._buffer[0]["sf_rows_inserted"] == 100
        assert logger._buffer[0]["sf_rows_updated"] is None
        assert logger._buffer[0]["sf_rows_deleted"] is None

        logger.cleanup_on_error()

    def test_sf_rows_fields_derived_for_update(self):
        """Test sf_rows_updated is set for UPDATE queries."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        record = _make_mock_record("query-001", query_kind="UPDATE", rows_affected=50)
        logger.append(record)

        assert logger._buffer[0]["sf_rows_inserted"] is None
        assert logger._buffer[0]["sf_rows_updated"] == 50
        assert logger._buffer[0]["sf_rows_deleted"] is None

        logger.cleanup_on_error()

    def test_sf_rows_fields_derived_for_delete(self):
        """Test sf_rows_deleted is set for DELETE queries."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        record = _make_mock_record("query-001", query_kind="DELETE", rows_affected=25)
        logger.append(record)

        assert logger._buffer[0]["sf_rows_inserted"] is None
        assert logger._buffer[0]["sf_rows_updated"] is None
        assert logger._buffer[0]["sf_rows_deleted"] == 25

        logger.cleanup_on_error()

    def test_custom_metadata_serialized_to_json(self):
        """Test custom_metadata is serialized to JSON string."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        record = _make_mock_record("query-001")
        logger.append(record)

        # Should be JSON string, not dict
        assert isinstance(logger._buffer[0]["custom_metadata"], str)
        assert '"bind_values"' in logger._buffer[0]["custom_metadata"]

        logger.cleanup_on_error()

    def test_multiple_appends(self):
        """Test appending multiple records."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        for i in range(100):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        assert logger._total_rows == 100
        assert len(logger._buffer) == 100

        logger.cleanup_on_error()


class TestBufferFlushing:
    """Tests for buffer flushing to disk."""

    def test_buffer_flush_at_threshold(self):
        """Test buffer flushes to disk when threshold reached."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        # Add exactly BUFFER_SIZE records to trigger flush
        for i in range(BUFFER_SIZE):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        # Wait for background write to complete
        logger.wait_for_pending_writes()

        # Buffer should be empty (flushed to disk)
        assert len(logger._buffer) == 0
        assert logger._total_rows == BUFFER_SIZE
        assert len(logger._files_written) == 1

        # Verify Parquet file exists
        assert logger._files_written[0].exists()

        logger.cleanup_on_error()

    def test_buffer_flush_creates_parquet(self):
        """Test that flush creates valid Parquet file."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        # Add enough records to trigger flush
        for i in range(BUFFER_SIZE):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        # Wait for background write to complete
        logger.wait_for_pending_writes()

        # Close writer to finalize the file before reading
        parquet_path = logger._files_written[0]
        logger._current_writer.close()
        logger._current_writer = None
        
        # Read back the Parquet file
        table = pq.read_table(parquet_path)

        assert table.num_rows == BUFFER_SIZE
        assert "query_id" in table.column_names
        assert "test_id" in table.column_names
        assert "success" in table.column_names

        logger.cleanup_on_error()

    def test_multiple_flushes_to_same_file(self):
        """Test that multiple flushes append row groups to same file (O(1) per flush)."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        # Trigger two flushes
        for i in range(BUFFER_SIZE * 2):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        # Wait for background writes to complete
        logger.wait_for_pending_writes()

        # Should have ONE file (row groups appended) - not 2 separate files
        assert len(logger._files_written) == 1
        assert logger._rows_in_current_file == BUFFER_SIZE * 2

        # Close writer before reading
        logger._current_writer.close()
        logger._current_writer = None
        
        # Verify total rows in single file
        table = pq.read_table(logger._files_written[0])
        assert table.num_rows == BUFFER_SIZE * 2

        logger.cleanup_on_error()

class TestFileSplitting:
    """Tests for file splitting at MAX_ROWS_PER_FILE threshold."""

    def test_file_splitting_at_threshold(self):
        """Test new file is created when MAX_ROWS_PER_FILE is reached."""
        # Use smaller thresholds for testing
        with patch(
            "backend.core.file_query_logger.MAX_ROWS_PER_FILE", 100
        ), patch("backend.core.file_query_logger.BUFFER_SIZE", 50):
            # Re-import to get patched values
            from backend.core.file_query_logger import FileBasedQueryLogger

            logger = FileBasedQueryLogger(
                test_id="test-123",
                worker_id=1,
                results_prefix=TEST_PREFIX,
            )

            # Add 150 records (should create 2 files with threshold of 100)
            for i in range(150):
                record = _make_mock_record(f"query-{i}")
                logger.append(record)

            # Should have started a new file after 100 rows
            assert logger._file_index >= 1

            logger.cleanup_on_error()


class TestStats:
    """Tests for statistics tracking."""

    def test_stats_initial(self):
        """Test initial stats values."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        stats = logger.stats
        assert stats["total_rows"] == 0
        assert stats["buffered_rows"] == 0
        assert stats["files_written"] == 0
        assert stats["current_file_rows"] == 0

        logger.cleanup_on_error()

    def test_stats_after_appends(self):
        """Test stats update after appending records."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        for i in range(50):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        stats = logger.stats
        assert stats["total_rows"] == 50
        assert stats["buffered_rows"] == 50
        assert stats["files_written"] == 0

        logger.cleanup_on_error()

    def test_stats_after_flush(self):
        """Test stats update after buffer flush."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        # Trigger a flush
        for i in range(BUFFER_SIZE):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        # Wait for background write to complete
        logger.wait_for_pending_writes()

        stats = logger.stats
        assert stats["total_rows"] == BUFFER_SIZE
        assert stats["buffered_rows"] == 0  # Flushed
        assert stats["files_written"] == 1
        assert stats["current_file_rows"] == BUFFER_SIZE

        logger.cleanup_on_error()


class TestFinalize:
    """Tests for finalize() method."""

    async def test_finalize_empty_logger(self):
        """Test finalize with no records."""
        pool = _make_mock_pool()
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        result = await logger.finalize(pool)

        assert result["rows_loaded"] == 0
        assert result["files_processed"] == 0
        # No PUT or COPY should be called
        pool.execute_query.assert_not_called()

    async def test_finalize_flushes_remaining_buffer(self):
        """Test finalize flushes remaining buffer before upload."""
        pool = _make_mock_pool()
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        # Add records below flush threshold
        for i in range(100):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        assert len(logger._buffer) == 100  # Not flushed yet

        result = await logger.finalize(pool)

        # Buffer should be flushed
        assert len(logger._buffer) == 0
        assert len(logger._files_written) == 1
        assert result["files_processed"] == 1

    async def test_finalize_calls_put_and_copy(self):
        """Test finalize calls PUT and COPY INTO."""
        pool = _make_mock_pool()
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        # Add some records
        for i in range(100):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        await logger.finalize(pool)

        # Should have called: PUT, COPY INTO, REMOVE
        assert pool.execute_query.call_count == 3

        calls = [str(call) for call in pool.execute_query.call_args_list]
        assert any("PUT" in call for call in calls)
        assert any("COPY INTO" in call for call in calls)
        assert any("REMOVE" in call for call in calls)

    async def test_finalize_cleans_up_temp_dir(self):
        """Test finalize removes temp directory."""
        pool = _make_mock_pool()
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        temp_dir = logger._temp_dir
        assert temp_dir.exists()

        # Add some records
        for i in range(100):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        await logger.finalize(pool)

        # Temp dir should be removed
        assert not temp_dir.exists()


class TestCleanup:
    """Tests for cleanup methods."""

    def test_cleanup_on_error_removes_temp_dir(self):
        """Test cleanup_on_error removes temp directory."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        temp_dir = logger._temp_dir
        assert temp_dir.exists()

        # Add some records and trigger flush
        for i in range(BUFFER_SIZE):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        # Wait for background write to complete
        logger.wait_for_pending_writes()

        assert len(logger._files_written) == 1
        assert logger._files_written[0].exists()

        logger.cleanup_on_error()

        # Temp dir and files should be removed
        assert not temp_dir.exists()

    def test_cleanup_on_error_safe_if_already_cleaned(self):
        """Test cleanup_on_error is safe to call multiple times."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        logger.cleanup_on_error()
        # Should not raise
        logger.cleanup_on_error()


class TestParquetSchema:
    """Tests for Parquet schema correctness."""

    def test_parquet_schema_has_required_columns(self):
        """Test Parquet files have all required columns."""
        logger = FileBasedQueryLogger(
            test_id="test-123",
            worker_id=1,
            results_prefix=TEST_PREFIX,
        )

        # Trigger flush to create Parquet file
        for i in range(BUFFER_SIZE):
            record = _make_mock_record(f"query-{i}")
            logger.append(record)

        # Wait for background write to complete
        logger.wait_for_pending_writes()

        # Close writer before reading
        logger._current_writer.close()
        logger._current_writer = None

        table = pq.read_table(logger._files_written[0])
        columns = set(table.column_names)

        required_columns = {
            "execution_id",
            "test_id",
            "query_id",
            "query_text",
            "start_time",
            "end_time",
            "duration_ms",
            "rows_affected",
            "bytes_scanned",
            "warehouse",
            "success",
            "error",
            "connection_id",
            "custom_metadata",
            "query_kind",
            "worker_id",
            "warmup",
            "app_elapsed_ms",
            "sf_rows_inserted",
            "sf_rows_updated",
            "sf_rows_deleted",
        }

        assert required_columns.issubset(columns)

        logger.cleanup_on_error()


def main():
    """Run all FileBasedQueryLogger tests."""
    print("=" * 60)
    print("Running FileBasedQueryLogger Tests")
    print("=" * 60)

    # Run with pytest
    import subprocess

    result = subprocess.run(
        ["python", "-m", "pytest", __file__, "-v"],
        cwd=Path(__file__).parent.parent,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
