"""
Tests for file_logger_base.py COPY INTO JSON parsing.

These tests verify that JSON columns are properly wrapped with TRY_PARSE_JSON
during COPY INTO, ensuring VARIANT columns store proper JSON objects instead
of double-encoded VARCHAR strings.

Run with: uv run pytest tests/test_file_logger_json_parsing.py -v
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pyarrow as pa
import pytest

from backend.core.file_logger_base import FileBasedLoggerBase


class _TestLogger(FileBasedLoggerBase):
    """Concrete test implementation of FileBasedLoggerBase."""

    @property
    def _file_prefix(self) -> str:
        return "test"

    @property
    def _stage_name(self) -> str:
        return "TEST_STAGE"

    @property
    def _table_name(self) -> str:
        return "TEST_TABLE"

    def _build_schema(self) -> pa.Schema:
        return pa.schema([
            ("id", pa.string()),
            ("value", pa.float64()),
            ("custom_metrics", pa.string()),  # JSON string -> VARIANT
            ("metadata", pa.string()),  # Another JSON column
        ])

    def _transform_record(self, record: Any) -> dict[str, Any]:
        return record

    @property
    def _json_columns(self) -> list[str]:
        return ["CUSTOM_METRICS", "METADATA"]


class _TestLoggerNoJson(FileBasedLoggerBase):
    """Test logger with no JSON columns."""

    @property
    def _file_prefix(self) -> str:
        return "test"

    @property
    def _stage_name(self) -> str:
        return "TEST_STAGE"

    @property
    def _table_name(self) -> str:
        return "TEST_TABLE"

    def _build_schema(self) -> pa.Schema:
        return pa.schema([
            ("id", pa.string()),
            ("value", pa.float64()),
        ])

    def _transform_record(self, record: Any) -> dict[str, Any]:
        return record


class TestCopyIntoJsonParsing:
    """Tests for COPY INTO SQL generation with JSON parsing."""

    @pytest.mark.asyncio
    async def test_copy_into_wraps_json_columns_with_try_parse_json(self) -> None:
        """JSON columns are wrapped with TRY_PARSE_JSON in COPY INTO SELECT."""
        logger = _TestLogger(
            test_id="test-123",
            worker_id=0,
            results_prefix="DB.SCHEMA",
        )

        executed_queries: list[str] = []

        async def mock_execute_query(query: str, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
            executed_queries.append(query)
            if "COPY INTO" in query:
                return [("test.parquet", "LOADED", 10, 10, None, None, None, None)]
            return []

        mock_pool = AsyncMock()
        mock_pool.execute_query = mock_execute_query

        logger._files_written = [logger._temp_dir / "test.parquet"]
        (logger._temp_dir / "test.parquet").touch()

        with patch(
            "backend.connectors.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            await logger.finalize(mock_pool)

        copy_query = next((q for q in executed_queries if "COPY INTO" in q), None)
        assert copy_query is not None, "COPY INTO query not found"

        assert "TRY_PARSE_JSON($1:CUSTOM_METRICS) AS CUSTOM_METRICS" in copy_query
        assert "TRY_PARSE_JSON($1:METADATA) AS METADATA" in copy_query
        assert "$1:ID AS ID" in copy_query
        assert "$1:VALUE AS VALUE" in copy_query

    @pytest.mark.asyncio
    async def test_copy_into_no_json_columns_uses_plain_select(self) -> None:
        """When no JSON columns, COPY INTO uses plain column references."""
        logger = _TestLoggerNoJson(
            test_id="test-123",
            worker_id=0,
            results_prefix="DB.SCHEMA",
        )

        executed_queries: list[str] = []

        async def mock_execute_query(query: str, *args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
            executed_queries.append(query)
            if "COPY INTO" in query:
                return [("test.parquet", "LOADED", 10, 10, None, None, None, None)]
            return []

        mock_pool = AsyncMock()
        mock_pool.execute_query = mock_execute_query

        logger._files_written = [logger._temp_dir / "test.parquet"]
        (logger._temp_dir / "test.parquet").touch()

        with patch(
            "backend.connectors.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            await logger.finalize(mock_pool)

        copy_query = next((q for q in executed_queries if "COPY INTO" in q), None)
        assert copy_query is not None

        assert "TRY_PARSE_JSON" not in copy_query
        assert "$1:ID AS ID" in copy_query
        assert "$1:VALUE AS VALUE" in copy_query

    def test_json_columns_property_returns_uppercase(self) -> None:
        """_json_columns should return uppercase column names."""
        logger = _TestLogger(
            test_id="test-123",
            worker_id=0,
            results_prefix="DB.SCHEMA",
        )

        json_cols = logger._json_columns
        assert json_cols == ["CUSTOM_METRICS", "METADATA"]
        for col in json_cols:
            assert col == col.upper()

    def test_default_json_columns_empty(self) -> None:
        """Base class _json_columns returns empty list by default."""
        logger = _TestLoggerNoJson(
            test_id="test-123",
            worker_id=0,
            results_prefix="DB.SCHEMA",
        )

        assert logger._json_columns == []
