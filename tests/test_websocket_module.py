"""
Comprehensive tests for the WebSocket module.

Tests all components:
1. helpers.py - Utility functions
2. metrics.py - Metrics aggregation functions
3. queries.py - Database query functions (mocked)

Note: streaming.py tests are in E2E tests (tests/e2e/test_websocket_streaming.py)
The stream_run_metrics function requires a full async WebSocket loop
which is better tested with actual WebSocket connections.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.websocket.helpers import (
    _avg_dicts,
    _coerce_datetime,
    _health_from,
    _parse_variant_dict,
    _sum_dicts,
    _to_float,
    _to_int,
)
from backend.websocket.metrics import (
    build_aggregate_metrics,
    build_run_snapshot,
)


# =============================================================================
# Tests for helpers.py
# =============================================================================


class TestCoerceDatetime:
    """Tests for _coerce_datetime helper."""

    def test_coerce_datetime_from_datetime_with_tz(self) -> None:
        """datetime with timezone is returned as-is."""
        dt = datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC)
        result = _coerce_datetime(dt)
        assert result == dt
        assert result.tzinfo == UTC

    def test_coerce_datetime_from_datetime_without_tz(self) -> None:
        """datetime without timezone gets UTC added."""
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = _coerce_datetime(dt)
        assert result is not None
        assert result.tzinfo == UTC
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15

    def test_coerce_datetime_from_iso_string(self) -> None:
        """ISO string is parsed to datetime."""
        result = _coerce_datetime("2024-01-15T10:30:00")
        assert result is not None
        assert result.year == 2024
        assert result.month == 1
        assert result.day == 15
        assert result.hour == 10
        assert result.minute == 30

    def test_coerce_datetime_from_iso_string_with_z(self) -> None:
        """ISO string with Z suffix is parsed correctly."""
        result = _coerce_datetime("2024-01-15T10:30:00Z")
        assert result is not None
        assert result.tzinfo == UTC

    def test_coerce_datetime_from_none(self) -> None:
        """None returns None."""
        assert _coerce_datetime(None) is None

    def test_coerce_datetime_from_invalid_string(self) -> None:
        """Invalid string returns None."""
        assert _coerce_datetime("not-a-date") is None

    def test_coerce_datetime_from_number(self) -> None:
        """Number returns None (not supported)."""
        assert _coerce_datetime(12345) is None


class TestParseVariantDict:
    """Tests for _parse_variant_dict helper."""

    def test_parse_dict_passthrough(self) -> None:
        """Dict is returned as-is."""
        d = {"key": "value", "num": 42}
        result = _parse_variant_dict(d)
        assert result == d

    def test_parse_json_string(self) -> None:
        """JSON string is parsed to dict."""
        json_str = '{"key": "value", "num": 42}'
        result = _parse_variant_dict(json_str)
        assert result == {"key": "value", "num": 42}

    def test_parse_invalid_json(self) -> None:
        """Invalid JSON returns None."""
        assert _parse_variant_dict("not json") is None

    def test_parse_json_array(self) -> None:
        """JSON array returns None (not a dict)."""
        assert _parse_variant_dict("[1, 2, 3]") is None

    def test_parse_none(self) -> None:
        """None returns None."""
        assert _parse_variant_dict(None) is None

    def test_parse_number(self) -> None:
        """Number returns None."""
        assert _parse_variant_dict(123) is None


class TestToInt:
    """Tests for _to_int helper."""

    def test_to_int_from_int(self) -> None:
        """Int is returned as-is."""
        assert _to_int(42) == 42

    def test_to_int_from_float(self) -> None:
        """Float is truncated to int."""
        assert _to_int(42.9) == 42

    def test_to_int_from_string(self) -> None:
        """Numeric string is converted."""
        assert _to_int("42") == 42

    def test_to_int_from_none(self) -> None:
        """None returns 0."""
        assert _to_int(None) == 0

    def test_to_int_from_invalid(self) -> None:
        """Invalid value returns 0."""
        assert _to_int("not a number") == 0


class TestToFloat:
    """Tests for _to_float helper."""

    def test_to_float_from_float(self) -> None:
        """Float is returned as-is."""
        assert _to_float(42.5) == 42.5

    def test_to_float_from_int(self) -> None:
        """Int is converted to float."""
        assert _to_float(42) == 42.0

    def test_to_float_from_string(self) -> None:
        """Numeric string is converted."""
        assert _to_float("42.5") == 42.5

    def test_to_float_from_none(self) -> None:
        """None returns 0.0."""
        assert _to_float(None) == 0.0

    def test_to_float_from_invalid(self) -> None:
        """Invalid value returns 0.0."""
        assert _to_float("not a number") == 0.0


class TestSumDicts:
    """Tests for _sum_dicts helper."""

    def test_sum_single_dict(self) -> None:
        """Single dict returns its values."""
        result = _sum_dicts([{"a": 1, "b": 2}])
        assert result == {"a": 1.0, "b": 2.0}

    def test_sum_multiple_dicts(self) -> None:
        """Multiple dicts are summed by key."""
        result = _sum_dicts([{"a": 1, "b": 2}, {"a": 3, "b": 4}])
        assert result == {"a": 4.0, "b": 6.0}

    def test_sum_dicts_with_missing_keys(self) -> None:
        """Missing keys default to 0."""
        result = _sum_dicts([{"a": 1}, {"b": 2}])
        assert result == {"a": 1.0, "b": 2.0}

    def test_sum_empty_list(self) -> None:
        """Empty list returns empty dict."""
        assert _sum_dicts([]) == {}

    def test_sum_dicts_with_non_numeric(self) -> None:
        """Non-numeric values are skipped."""
        result = _sum_dicts([{"a": 1, "b": "text"}, {"a": 2}])
        assert result == {"a": 3.0}


class TestAvgDicts:
    """Tests for _avg_dicts helper."""

    def test_avg_single_dict(self) -> None:
        """Single dict returns its values."""
        result = _avg_dicts([{"a": 10, "b": 20}])
        assert result == {"a": 10.0, "b": 20.0}

    def test_avg_multiple_dicts(self) -> None:
        """Multiple dicts are averaged by key."""
        result = _avg_dicts([{"a": 10, "b": 20}, {"a": 30, "b": 40}])
        assert result == {"a": 20.0, "b": 30.0}

    def test_avg_empty_list(self) -> None:
        """Empty list returns empty dict."""
        assert _avg_dicts([]) == {}


class TestHealthFrom:
    """Tests for _health_from helper."""

    def test_health_dead_status(self) -> None:
        """DEAD status always returns DEAD."""
        assert _health_from("DEAD", 5.0) == "DEAD"
        assert _health_from("dead", 5.0) == "DEAD"

    def test_health_none_age(self) -> None:
        """None age returns STALE."""
        assert _health_from("RUNNING", None) == "STALE"

    def test_health_very_old_heartbeat(self) -> None:
        """60+ seconds age returns DEAD."""
        assert _health_from("RUNNING", 60.0) == "DEAD"
        assert _health_from("RUNNING", 120.0) == "DEAD"

    def test_health_stale_heartbeat(self) -> None:
        """30-60 seconds age returns STALE."""
        assert _health_from("RUNNING", 30.0) == "STALE"
        assert _health_from("RUNNING", 45.0) == "STALE"

    def test_health_healthy_heartbeat(self) -> None:
        """Under 30 seconds age returns HEALTHY."""
        assert _health_from("RUNNING", 0.0) == "HEALTHY"
        assert _health_from("RUNNING", 15.0) == "HEALTHY"
        assert _health_from("RUNNING", 29.9) == "HEALTHY"


# =============================================================================
# Tests for metrics.py
# =============================================================================


class TestBuildAggregateMetrics:
    """Tests for build_aggregate_metrics function."""

    def test_build_with_all_metrics(self) -> None:
        """All metric components are included in output."""
        result = build_aggregate_metrics(
            ops={"total": 1000, "current_per_sec": 50.5},
            latency={"p50": 10.0, "p95": 25.0, "p99": 100.0, "avg": 15.0},
            errors={"count": 5, "rate": 0.005},
            connections={"active": 10, "target": 20},
            operations={"reads": 800, "writes": 200},
        )

        assert result["total_ops"] == 1000
        assert result["qps"] == 50.5
        assert result["p50_latency_ms"] == 10.0
        assert result["p95_latency_ms"] == 25.0
        assert result["p99_latency_ms"] == 100.0
        assert result["avg_latency_ms"] == 15.0
        assert result["error_rate"] == 0.005
        assert result["total_errors"] == 5
        assert result["active_connections"] == 10
        assert result["target_connections"] == 20
        assert result["read_count"] == 800
        assert result["write_count"] == 200

    def test_build_with_none_components(self) -> None:
        """None components result in zero values."""
        result = build_aggregate_metrics(
            ops=None,
            latency=None,
            errors=None,
            connections=None,
            operations=None,
        )

        assert result["total_ops"] == 0
        assert result["qps"] == 0.0
        assert result["p50_latency_ms"] == 0.0
        assert result["p95_latency_ms"] == 0.0
        assert result["p99_latency_ms"] == 0.0
        assert result["avg_latency_ms"] == 0.0
        assert result["error_rate"] == 0.0
        assert result["total_errors"] == 0
        assert result["active_connections"] == 0
        assert result["target_connections"] == 0
        assert result["read_count"] == 0
        assert result["write_count"] == 0

    def test_build_with_partial_data(self) -> None:
        """Partial data uses defaults for missing fields."""
        result = build_aggregate_metrics(
            ops={"total": 500},  # Missing current_per_sec
            latency={"p50": 10.0},  # Missing other percentiles
            errors=None,
            connections={"active": 5},  # Missing target
            operations=None,
        )

        assert result["total_ops"] == 500
        assert result["qps"] == 0.0  # Default
        assert result["p50_latency_ms"] == 10.0
        assert result["p95_latency_ms"] == 0.0  # Default
        assert result["active_connections"] == 5
        assert result["target_connections"] == 0  # Default


class TestBuildRunSnapshot:
    """Tests for build_run_snapshot function."""

    def test_build_basic_snapshot(self) -> None:
        """Basic snapshot with required fields."""
        aggregate_metrics = {
            "total_ops": 1000,
            "qps": 50.0,
            "p50_latency_ms": 10.0,
            "p95_latency_ms": 25.0,
            "p99_latency_ms": 100.0,
        }

        result = build_run_snapshot(
            run_id="run-123",
            status="RUNNING",
            phase="MEASUREMENT",
            elapsed_seconds=60.0,
            worker_count=5,
            aggregate_metrics=aggregate_metrics,
        )

        assert result["run_id"] == "run-123"
        assert result["status"] == "RUNNING"
        assert result["phase"] == "MEASUREMENT"
        assert result["worker_count"] == 5
        assert result["elapsed_seconds"] == 60.0
        assert result["aggregate_metrics"] == aggregate_metrics

    def test_build_snapshot_with_none_values(self) -> None:
        """None values use defaults."""
        result = build_run_snapshot(
            run_id="run-123",
            status=None,
            phase=None,
            elapsed_seconds=None,
            worker_count=0,
            aggregate_metrics={},
        )

        assert result["status"] == "RUNNING"
        assert result["phase"] == "RUNNING"
        assert result["elapsed_seconds"] == 0.0

    def test_build_snapshot_with_run_status(self) -> None:
        """run_status dict adds worker tracking fields."""
        result = build_run_snapshot(
            run_id="run-123",
            status="RUNNING",
            phase="MEASUREMENT",
            elapsed_seconds=60.0,
            worker_count=5,
            aggregate_metrics={},
            run_status={
                "total_workers_expected": 10,
                "workers_registered": 8,
                "workers_active": 5,
                "workers_completed": 3,
                "start_time": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                "end_time": None,
            },
        )

        assert result["workers_expected"] == 10
        assert result["workers_registered"] == 8
        assert result["workers_active"] == 5
        assert result["workers_completed"] == 3
        assert result["start_time"] == "2024-01-15T10:00:00+00:00"
        assert result["end_time"] is None


# =============================================================================
# Tests for queries.py (mocked database)
# =============================================================================


class TestFetchRunStatus:
    """Tests for fetch_run_status query function."""

    @pytest.mark.asyncio
    async def test_fetch_run_status_returns_dict(self) -> None:
        """fetch_run_status returns a properly structured dict."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                (
                    "RUNNING",  # STATUS
                    "MEASUREMENT",  # PHASE
                    datetime(2024, 1, 15, 10, 0, 0),  # START_TIME
                    None,  # END_TIME
                    datetime(2024, 1, 15, 10, 5, 0),  # WARMUP_END_TIME
                    10,  # TOTAL_WORKERS_EXPECTED
                    8,  # WORKERS_REGISTERED
                    5,  # WORKERS_ACTIVE
                    3,  # WORKERS_COMPLETED
                    '{"current_step": 2}',  # FIND_MAX_STATE
                    None,  # QPS_CONTROLLER_STATE
                    None,  # CANCELLATION_REASON
                    300,  # ELAPSED_SECONDS
                    None,  # FAILURE_REASON
                )
            ]
        )

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_run_status

            result = await fetch_run_status("run-123")

        assert result is not None
        assert result["status"] == "RUNNING"
        assert result["phase"] == "MEASUREMENT"
        assert result["total_workers_expected"] == 10
        assert result["workers_active"] == 5
        assert result["elapsed_seconds"] == 300.0

    @pytest.mark.asyncio
    async def test_fetch_run_status_not_found(self) -> None:
        """fetch_run_status returns None when run not found."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_run_status

            result = await fetch_run_status("nonexistent")

        assert result is None


class TestGetParentTestStatus:
    """Tests for get_parent_test_status query function."""

    @pytest.mark.asyncio
    async def test_get_parent_test_status_returns_uppercase(self) -> None:
        """Status is returned in uppercase."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[("completed",)])

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import get_parent_test_status

            result = await get_parent_test_status("test-123")

        assert result == "COMPLETED"

    @pytest.mark.asyncio
    async def test_get_parent_test_status_not_found(self) -> None:
        """Returns None when test not found."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import get_parent_test_status

            result = await get_parent_test_status("nonexistent")

        assert result is None


class TestFetchRunTestIds:
    """Tests for fetch_run_test_ids query function."""

    @pytest.mark.asyncio
    async def test_fetch_run_test_ids_returns_list(self) -> None:
        """Returns list of test IDs including parent."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[("test-1",), ("test-2",), ("test-3",)]
        )

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_run_test_ids

            result = await fetch_run_test_ids("run-123")

        assert "run-123" in result
        assert "test-1" in result
        assert "test-2" in result
        assert "test-3" in result

    @pytest.mark.asyncio
    async def test_fetch_run_test_ids_empty_returns_parent(self) -> None:
        """Empty result includes at least the parent run ID."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_run_test_ids

            result = await fetch_run_test_ids("run-123")

        assert result == ["run-123"]


class TestFetchWarehouseContext:
    """Tests for fetch_warehouse_context query function."""

    @pytest.mark.asyncio
    async def test_fetch_warehouse_context_returns_tuple(self) -> None:
        """Returns (warehouse_name, table_type) tuple."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[("MY_WH", "snowflake")])

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_warehouse_context

            warehouse, table_type = await fetch_warehouse_context("test-123")

        assert warehouse == "MY_WH"
        assert table_type == "snowflake"

    @pytest.mark.asyncio
    async def test_fetch_warehouse_context_postgres(self) -> None:
        """Postgres table type is normalized to lowercase."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[("PG_SERVER", "POSTGRES")])

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_warehouse_context

            warehouse, table_type = await fetch_warehouse_context("test-123")

        assert warehouse == "PG_SERVER"
        assert table_type == "postgres"

    @pytest.mark.asyncio
    async def test_fetch_warehouse_context_not_found(self) -> None:
        """Returns (None, None) when not found."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[])

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_warehouse_context

            warehouse, table_type = await fetch_warehouse_context("nonexistent")

        assert warehouse is None
        assert table_type is None


class TestFetchParentEnrichmentStatus:
    """Tests for fetch_parent_enrichment_status query function."""

    @pytest.mark.asyncio
    async def test_fetch_parent_enrichment_completed(self) -> None:
        """Returns COMPLETED status."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[("COMPLETED",)])

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_parent_enrichment_status

            result = await fetch_parent_enrichment_status("run-123")

        assert result == "COMPLETED"

    @pytest.mark.asyncio
    async def test_fetch_parent_enrichment_failed(self) -> None:
        """Returns FAILED status."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(return_value=[("FAILED",)])

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_parent_enrichment_status

            result = await fetch_parent_enrichment_status("run-123")

        assert result == "FAILED"


class TestFetchLogsSinceSeq:
    """Tests for fetch_logs_since_seq query function."""

    @pytest.mark.asyncio
    async def test_fetch_logs_returns_list(self) -> None:
        """Returns list of log dicts."""
        mock_pool = MagicMock()
        mock_pool.execute_query = AsyncMock(
            return_value=[
                (
                    "log-1",
                    "test-123",
                    "worker-1",
                    1,
                    datetime(2024, 1, 15, 10, 0, 0),
                    "INFO",
                    "test.logger",
                    "Test message",
                    None,
                ),
                (
                    "log-2",
                    "test-123",
                    "worker-1",
                    2,
                    datetime(2024, 1, 15, 10, 0, 1),
                    "ERROR",
                    "test.logger",
                    "Error message",
                    "Traceback...",
                ),
            ]
        )

        with patch(
            "backend.websocket.queries.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            from backend.websocket.queries import fetch_logs_since_seq

            result = await fetch_logs_since_seq("test-123", 0)

        assert len(result) == 2
        assert result[0]["log_id"] == "log-1"
        assert result[0]["kind"] == "log"
        assert result[0]["level"] == "INFO"
        assert result[0]["message"] == "Test message"
        assert result[1]["level"] == "ERROR"
        assert result[1]["exception"] == "Traceback..."
