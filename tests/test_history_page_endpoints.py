"""
Tests for history page API endpoints.

These tests verify the API endpoints used by the history page:
- GET /api/tests (list with filters)
- GET /api/tests/{id} (test details)
- GET /api/tests/{id}/metrics (aggregated metrics)
- GET /api/tests/search (search tests)
- DELETE /api/tests/{id} (delete test)
- POST /api/tests/{id}/rerun (re-run test)

Run with: uv run pytest tests/test_history_page_endpoints.py -v
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _MockPool:
    """Stub pool for testing database queries."""

    def __init__(self, query_results: dict[str, list[tuple[Any, ...]]]) -> None:
        self._query_results = query_results
        self.calls: list[tuple[str, list[object] | None]] = []

    async def execute_query(
        self, query: str, params: list[object] | None = None
    ) -> list[tuple[Any, ...]]:
        self.calls.append((query, params))
        sql_upper = " ".join(str(query).split()).upper()

        if "SELECT COUNT(*)" in sql_upper:
            return self._query_results.get("COUNT", [(0,)])
        if "SELECT RUN_ID FROM" in sql_upper and "TEST_RESULTS" in sql_upper:
            return self._query_results.get("RUN_ID", [])

        for key, result in self._query_results.items():
            if key.upper() in sql_upper:
                return result
        return []


class TestListTestsEndpoint:
    """Tests for GET /api/tests endpoint."""

    @pytest.mark.asyncio
    async def test_returns_paginated_results(self) -> None:
        """Returns paginated test results with correct structure."""
        from backend.api.routes.test_results import list_tests

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        mock_pool = _MockPool({
            "FROM": [
                (
                    "test-123",  # TEST_ID
                    "test-123",  # RUN_ID
                    "My Test",  # TEST_NAME
                    "STANDARD",  # TABLE_TYPE
                    "MEDIUM",  # WAREHOUSE_SIZE
                    now,  # START_TIME
                    1500.0,  # QPS
                    5.0,  # P95_LATENCY_MS
                    10.0,  # P99_LATENCY_MS
                    0.001,  # ERROR_RATE
                    "COMPLETED",  # STATUS
                    10,  # CONCURRENT_CONNECTIONS
                    120.0,  # DURATION_SECONDS
                    None,  # FAILURE_REASON
                    "COMPLETED",  # ENRICHMENT_STATUS
                    None,  # POSTGRES_INSTANCE_SIZE
                    "CONCURRENCY",  # LOAD_MODE
                    None,  # TARGET_QPS
                    10,  # START_CONCURRENCY
                    5,  # CONCURRENCY_INCREMENT
                    {"mode": "FIXED"},  # SCALING_CONFIG
                    25,  # CUSTOM_POINT_LOOKUP_PCT
                    25,  # CUSTOM_RANGE_SCAN_PCT
                    25,  # CUSTOM_INSERT_PCT
                    25,  # CUSTOM_UPDATE_PCT
                    None,  # RUN_STATUS
                    None,  # RUN_PHASE
                ),
            ],
            "COUNT": [(1,)],
        })

        with patch(
            "backend.api.routes.test_results.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            result = await list_tests(page=1, page_size=20, status_filter="")

        assert "results" in result
        assert "total_pages" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["test_id"] == "test-123"
        assert result["results"][0]["test_name"] == "My Test"
        assert result["results"][0]["table_type"] == "STANDARD"
        assert result["results"][0]["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_filters_by_table_type(self) -> None:
        """Filters results by table_type parameter."""
        from backend.api.routes.test_results import list_tests

        mock_pool = _MockPool({
            "FROM": [],
        })

        with patch(
            "backend.api.routes.test_results.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            await list_tests(page=1, page_size=20, table_type="HYBRID", status_filter="")

        query_call = mock_pool.calls[0][0]
        assert "TABLE_TYPE = ?" in query_call

    @pytest.mark.asyncio
    async def test_filters_by_status(self) -> None:
        """Filters results by status parameter."""
        from backend.api.routes.test_results import list_tests

        mock_pool = _MockPool({
            "FROM": [],
        })

        with patch(
            "backend.api.routes.test_results.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            await list_tests(page=1, page_size=20, status_filter="COMPLETED")

        query_call = mock_pool.calls[0][0]
        assert "STATUS = ?" in query_call

    @pytest.mark.asyncio
    async def test_search_query_filters_multiple_fields(self) -> None:
        """Search query applies LIKE filter to multiple fields."""
        from backend.api.routes.test_results import list_tests

        mock_pool = _MockPool({
            "FROM": [],
        })

        with patch(
            "backend.api.routes.test_results.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            await list_tests(page=1, page_size=20, search_query="my test", status_filter="")

        query_call = mock_pool.calls[0][0]
        assert "LIKE ?" in query_call
        assert "TEST_NAME" in query_call


class TestGetTestEndpoint:
    """Tests for GET /api/tests/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_returns_test_details(self) -> None:
        """Returns complete test details."""
        from backend.api.routes.test_results import get_test, _test_details_cache

        _test_details_cache.invalidate("test_details:test-123")

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        test_config = {
            "template_id": "tmpl-1",
            "template_config": {"load_mode": "CONCURRENCY"},
        }

        mock_pool = _MockPool({
            "TEST_RESULTS": [
                (
                    "test-123",  # TEST_ID
                    "test-123",  # RUN_ID
                    "My Test",  # TEST_NAME
                    "scenario-1",  # SCENARIO_NAME
                    "test_table",  # TABLE_NAME
                    "STANDARD",  # TABLE_TYPE
                    "COMPUTE_WH",  # WAREHOUSE
                    "MEDIUM",  # WAREHOUSE_SIZE
                    "COMPLETED",  # STATUS
                    now,  # START_TIME
                    now,  # END_TIME
                    120.0,  # DURATION_SECONDS
                    10,  # CONCURRENT_CONNECTIONS
                    test_config,  # TEST_CONFIG
                    {},  # CUSTOM_METRICS
                    180000,  # TOTAL_OPERATIONS
                    90000,  # READ_OPERATIONS
                    90000,  # WRITE_OPERATIONS
                    10,  # FAILED_OPERATIONS
                    1500.0,  # QPS
                    750.0,  # READS_PER_SECOND
                    750.0,  # WRITES_PER_SECOND
                    100000,  # ROWS_READ
                    100000,  # ROWS_WRITTEN
                    3.0,  # AVG_LATENCY_MS
                    2.0,  # P50_LATENCY_MS
                    4.0,  # P90_LATENCY_MS
                    5.0,  # P95_LATENCY_MS
                    10.0,  # P99_LATENCY_MS
                    1.0,  # MIN_LATENCY_MS
                    50.0,  # MAX_LATENCY_MS
                    *([None] * 40),  # Remaining latency columns
                ),
            ],
        })

        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
        ):
            result = await get_test("test-123")

        assert result["test_id"] == "test-123"
        assert result["test_name"] == "My Test"
        assert result["table_type"] == "STANDARD"
        assert result["status"] == "COMPLETED"
        assert result["ops_per_sec"] == 1500.0
        assert result["p95_latency"] == 5.0

    @pytest.mark.asyncio
    async def test_returns_cached_result(self) -> None:
        """Returns cached result on subsequent calls."""
        from backend.api.routes.test_results import get_test, _test_details_cache

        cached_data = {"test_id": "test-123", "cached": True}
        _test_details_cache.set("test_details:test-123", cached_data)

        result = await get_test("test-123")
        assert result["cached"] is True

        _test_details_cache.invalidate("test_details:test-123")


class TestSearchTestsEndpoint:
    """Tests for GET /api/tests/search endpoint."""

    @pytest.mark.asyncio
    async def test_returns_matching_results(self) -> None:
        """Returns tests matching search query."""
        from backend.api.routes.test_results import search_tests

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        mock_pool = _MockPool({
            "TEST_RESULTS": [
                (
                    "test-123",  # TEST_ID
                    "My Test",  # TEST_NAME
                    "STANDARD",  # TABLE_TYPE
                    "MEDIUM",  # WAREHOUSE_SIZE
                    now,  # START_TIME
                    1500.0,  # QPS
                    2.0,  # P50_LATENCY_MS
                    5.0,  # P95_LATENCY_MS
                    10.0,  # P99_LATENCY_MS
                    0.001,  # ERROR_RATE
                    120.0,  # DURATION_SECONDS
                    None,  # POSTGRES_INSTANCE_SIZE
                ),
            ],
        })

        with patch(
            "backend.api.routes.test_results.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            result = await search_tests(q="my test")

        assert "results" in result
        assert len(result["results"]) == 1
        assert result["results"][0]["test_id"] == "test-123"
        assert result["results"][0]["test_name"] == "My Test"

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty_results(self) -> None:
        """Empty search query returns empty results."""
        from backend.api.routes.test_results import search_tests

        result = await search_tests(q="")
        assert result == {"results": []}

    @pytest.mark.asyncio
    async def test_whitespace_query_returns_empty_results(self) -> None:
        """Whitespace-only query returns empty results."""
        from backend.api.routes.test_results import search_tests

        result = await search_tests(q="   ")
        assert result == {"results": []}


class TestGetMetricsEndpoint:
    """Tests for GET /api/tests/{id}/metrics endpoint."""

    @pytest.mark.asyncio
    async def test_caches_results(self) -> None:
        """Caches results for subsequent calls."""
        from backend.api.routes.test_results import get_test_metrics, _metrics_cache

        cached_data = {"snapshots": [{"cached": True}], "test_cached": True}
        _metrics_cache.set("test-cached", cached_data)

        result = await get_test_metrics("test-cached")
        assert result.get("test_cached") is True

        _metrics_cache.invalidate("test-cached")


class TestDeleteTestEndpoint:
    """Tests for DELETE /api/tests/{id} endpoint."""

    @pytest.mark.asyncio
    async def test_deletes_parent_test_cascades(self) -> None:
        """Deleting parent test cascades to all related data."""
        from backend.api.routes.test_results import delete_test

        mock_pool = _MockPool({
            "RUN_ID": [("test-123",)],  # run_id == test_id means parent
            "TEST_ID": [("test-123",), ("test-123-worker-0",)],
        })

        with patch(
            "backend.api.routes.test_results.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            await delete_test("test-123")

        delete_calls = [c for c in mock_pool.calls if "DELETE" in c[0].upper()]
        assert len(delete_calls) >= 3

        tables_deleted = [c[0] for c in delete_calls]
        assert any("WORKER_METRICS_SNAPSHOTS" in t for t in tables_deleted)
        assert any("TEST_RESULTS" in t for t in tables_deleted)

    @pytest.mark.asyncio
    async def test_delete_nonexistent_test_returns_none(self) -> None:
        """Deleting nonexistent test returns None gracefully."""
        from backend.api.routes.test_results import delete_test

        mock_pool = _MockPool({
            "RUN_ID": [],
        })

        with patch(
            "backend.api.routes.test_results.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            result = await delete_test("nonexistent-test")

        assert result is None


class TestRerunTestEndpoint:
    """Tests for POST /api/tests/{id}/rerun endpoint."""

    @pytest.mark.asyncio
    async def test_rerun_nonexistent_test_raises_404(self) -> None:
        """Re-running nonexistent test raises 404."""
        from fastapi import HTTPException

        from backend.api.routes.test_results import rerun_test

        mock_pool = _MockPool({
            "TEST_CONFIG": [],
        })

        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await rerun_test("nonexistent-test")

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_rerun_missing_template_id_raises_400(self) -> None:
        """Re-running test without template_id raises 400."""
        from fastapi import HTTPException

        from backend.api.routes.test_results import rerun_test

        mock_pool = _MockPool({
            "TEST_CONFIG": [({},)],  # Empty config, no template_id
        })

        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await rerun_test("test-no-template")

        assert exc_info.value.status_code == 400
        assert "template_id" in str(exc_info.value.detail)


class TestCostFieldsCalculation:
    """Tests for cost field calculations in API responses."""

    def test_build_cost_fields_standard_warehouse(self) -> None:
        """Cost fields calculated correctly for standard warehouse."""
        from backend.api.routes.test_results import _build_cost_fields

        result = _build_cost_fields(
            duration_seconds=3600.0,
            warehouse_size="MEDIUM",
            total_operations=100000,
            qps=27.78,
            table_type="STANDARD",
        )

        assert "credits_used" in result
        assert "estimated_cost_usd" in result
        assert result["credits_used"] > 0
        assert result["estimated_cost_usd"] > 0

    def test_build_cost_fields_postgres(self) -> None:
        """Cost fields calculated correctly for Postgres."""
        from backend.api.routes.test_results import _build_cost_fields

        result = _build_cost_fields(
            duration_seconds=3600.0,
            warehouse_size=None,
            total_operations=100000,
            qps=27.78,
            table_type="POSTGRES",
            postgres_instance_size="STANDARD_M",
        )

        assert "credits_used" in result
        assert result["credits_used"] > 0

    def test_build_cost_fields_includes_efficiency_metrics(self) -> None:
        """Cost fields include efficiency metrics when operations provided."""
        from backend.api.routes.test_results import _build_cost_fields

        result = _build_cost_fields(
            duration_seconds=3600.0,
            warehouse_size="MEDIUM",
            total_operations=100000,
            qps=27.78,
            table_type="STANDARD",
        )

        assert "cost_per_1k_ops" in result or "cost_per_1000_ops" in result
