"""
Tests for history page worker-metrics API endpoint.

These tests verify that historical worker metrics are correctly retrieved
and parsed, including resource metrics from CUSTOM_METRICS.

Run with: uv run pytest tests/test_history_worker_metrics.py -v
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

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

        # Match by query pattern
        if "FROM" in sql_upper and "TEST_RESULTS" in sql_upper and "WHERE TEST_ID" in sql_upper:
            return self._query_results.get("RUN_ID_LOOKUP", [])
        if "FROM" in sql_upper and "WORKER_METRICS_SNAPSHOTS" in sql_upper:
            return self._query_results.get("WORKER_METRICS", [])
        
        # Fallback to key matching
        for key, result in self._query_results.items():
            if key.upper() in sql_upper:
                return result
        return []


class TestWorkerMetricsEndpoint:
    """Tests for /api/tests/{test_id}/worker-metrics endpoint."""

    @pytest.mark.asyncio
    async def test_returns_resource_metrics_from_parsed_json(self) -> None:
        """Resource metrics are extracted from CUSTOM_METRICS VARIANT column."""
        from datetime import datetime, timezone

        from backend.api.routes.test_results import get_worker_metrics

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        custom_metrics = {
            "resources": {
                "cpu_percent": 15.5,
                "memory_mb": 256.75,
                "host_cpu_percent": 45.2,
                "host_memory_mb": 8192.5,
                "cgroup_cpu_percent": 12.3,
                "cgroup_memory_mb": 200.0,
            },
            "qps": {"raw": 100.0, "smoothed": 105.0},
        }

        mock_pool = _MockPool(
            {
                "RUN_ID_LOOKUP": [("run-123",)],
                "WORKER_METRICS": [
                    (
                        "worker-0",  # WORKER_ID
                        0,  # WORKER_GROUP_ID
                        1,  # WORKER_GROUP_COUNT
                        now,  # TIMESTAMP
                        30.0,  # ELAPSED_SECONDS
                        150.5,  # QPS
                        5.0,  # P50_LATENCY_MS
                        15.0,  # P95_LATENCY_MS
                        25.0,  # P99_LATENCY_MS
                        10,  # ACTIVE_CONNECTIONS
                        20,  # TARGET_CONNECTIONS
                        custom_metrics,  # CUSTOM_METRICS (dict - properly parsed VARIANT)
                        "MEASUREMENT",  # PHASE
                    )
                ],
            }
        )

        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.get",
                return_value=None,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.set",
            ),
        ):
            result = await get_worker_metrics("test-123", nocache=True)

        assert result["available"] is True
        assert len(result["workers"]) == 1

        worker = result["workers"][0]
        assert worker["worker_id"] == "worker-0"
        assert len(worker["snapshots"]) == 1

        snapshot = worker["snapshots"][0]
        assert snapshot["qps"] == 150.5
        assert snapshot["resources_cpu_percent"] == 15.5
        assert snapshot["resources_memory_mb"] == 256.75
        assert snapshot["resources_host_cpu_percent"] == 45.2
        assert snapshot["resources_host_memory_mb"] == 8192.5
        assert snapshot["resources_cgroup_cpu_percent"] == 12.3
        assert snapshot["resources_cgroup_memory_mb"] == 200.0

    @pytest.mark.asyncio
    async def test_handles_json_string_custom_metrics(self) -> None:
        """Handles CUSTOM_METRICS stored as JSON string (legacy data)."""
        from datetime import datetime, timezone

        from backend.api.routes.test_results import get_worker_metrics

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        custom_metrics_str = json.dumps({
            "resources": {
                "cpu_percent": 10.0,
                "memory_mb": 128.0,
            }
        })

        mock_pool = _MockPool(
            {
                "RUN_ID_LOOKUP": [("run-123",)],
                "WORKER_METRICS": [
                    (
                        "worker-0",
                        0,
                        1,
                        now,
                        30.0,
                        100.0,
                        5.0,
                        15.0,
                        25.0,
                        10,
                        20,
                        custom_metrics_str,  # JSON string instead of dict
                        "MEASUREMENT",
                    )
                ],
            }
        )

        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.get",
                return_value=None,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.set",
            ),
        ):
            result = await get_worker_metrics("test-123", nocache=True)

        snapshot = result["workers"][0]["snapshots"][0]
        assert snapshot["resources_cpu_percent"] == 10.0
        assert snapshot["resources_memory_mb"] == 128.0

    @pytest.mark.asyncio
    async def test_handles_null_custom_metrics(self) -> None:
        """Handles NULL CUSTOM_METRICS gracefully."""
        from datetime import datetime, timezone

        from backend.api.routes.test_results import get_worker_metrics

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        mock_pool = _MockPool(
            {
                "RUN_ID_LOOKUP": [("run-123",)],
                "WORKER_METRICS": [
                    (
                        "worker-0",
                        0,
                        1,
                        now,
                        30.0,
                        100.0,
                        5.0,
                        15.0,
                        25.0,
                        10,
                        20,
                        None,  # NULL CUSTOM_METRICS
                        "MEASUREMENT",
                    )
                ],
            }
        )

        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.get",
                return_value=None,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.set",
            ),
        ):
            result = await get_worker_metrics("test-123", nocache=True)

        snapshot = result["workers"][0]["snapshots"][0]
        assert snapshot["resources_cpu_percent"] == 0.0
        assert snapshot["resources_memory_mb"] == 0.0

    @pytest.mark.asyncio
    async def test_handles_empty_resources_dict(self) -> None:
        """Handles CUSTOM_METRICS with no resources key."""
        from datetime import datetime, timezone

        from backend.api.routes.test_results import get_worker_metrics

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        custom_metrics = {"qps": {"raw": 50.0}}  # No resources key

        mock_pool = _MockPool(
            {
                "RUN_ID_LOOKUP": [("run-123",)],
                "WORKER_METRICS": [
                    (
                        "worker-0",
                        0,
                        1,
                        now,
                        30.0,
                        100.0,
                        5.0,
                        15.0,
                        25.0,
                        10,
                        20,
                        custom_metrics,
                        "MEASUREMENT",
                    )
                ],
            }
        )

        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.get",
                return_value=None,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.set",
            ),
        ):
            result = await get_worker_metrics("test-123", nocache=True)

        snapshot = result["workers"][0]["snapshots"][0]
        assert snapshot["resources_cpu_percent"] == 0.0
        assert snapshot["resources_memory_mb"] == 0.0

    @pytest.mark.asyncio
    async def test_multi_worker_snapshots_grouped_correctly(self) -> None:
        """Multiple workers' snapshots are grouped by worker key."""
        from datetime import datetime, timedelta, timezone

        from backend.api.routes.test_results import get_worker_metrics

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        custom_metrics_w0 = {"resources": {"cpu_percent": 10.0, "memory_mb": 100.0}}
        custom_metrics_w1 = {"resources": {"cpu_percent": 20.0, "memory_mb": 200.0}}

        mock_pool = _MockPool(
            {
                "RUN_ID_LOOKUP": [("run-123",)],
                "WORKER_METRICS": [
                    # Worker 0, snapshot 1
                    ("worker-0", 0, 2, now, 10.0, 100.0, 5.0, 15.0, 25.0, 10, 20, custom_metrics_w0, "MEASUREMENT"),
                    # Worker 0, snapshot 2
                    ("worker-0", 0, 2, now + timedelta(seconds=10), 20.0, 110.0, 5.5, 16.0, 26.0, 11, 20, custom_metrics_w0, "MEASUREMENT"),
                    # Worker 1, snapshot 1
                    ("worker-1", 1, 2, now, 10.0, 200.0, 4.0, 14.0, 24.0, 20, 40, custom_metrics_w1, "MEASUREMENT"),
                ],
            }
        )

        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.get",
                return_value=None,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.set",
            ),
        ):
            result = await get_worker_metrics("test-123", nocache=True)

        assert len(result["workers"]) == 2

        workers_by_id = {w["worker_id"]: w for w in result["workers"]}
        
        w0 = workers_by_id["worker-0"]
        assert len(w0["snapshots"]) == 2
        assert w0["snapshots"][0]["resources_cpu_percent"] == 10.0
        
        w1 = workers_by_id["worker-1"]
        assert len(w1["snapshots"]) == 1
        assert w1["snapshots"][0]["resources_cpu_percent"] == 20.0
        assert w1["snapshots"][0]["resources_memory_mb"] == 200.0

    @pytest.mark.asyncio
    async def test_nocache_bypasses_cache(self) -> None:
        """nocache=True parameter bypasses the cache."""
        from datetime import datetime, timezone

        from backend.api.routes.test_results import get_worker_metrics

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        cached_result = {"available": True, "workers": [], "cached": True}
        
        mock_pool = _MockPool(
            {
                "RUN_ID_LOOKUP": [("run-123",)],
                "WORKER_METRICS": [
                    ("worker-0", 0, 1, now, 30.0, 100.0, 5.0, 15.0, 25.0, 10, 20, {}, "MEASUREMENT"),
                ],
            }
        )

        cache_get_mock = AsyncMock(return_value=cached_result)
        
        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.get",
                return_value=cached_result,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.set",
            ),
        ):
            # With nocache=False, should return cached result
            result_cached = await get_worker_metrics("test-123", nocache=False)
            assert result_cached.get("cached") is True
            
            # With nocache=True, should fetch fresh data
            result_fresh = await get_worker_metrics("test-123", nocache=True)
            assert result_fresh.get("cached") is None
            assert len(result_fresh["workers"]) == 1

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_data(self) -> None:
        """Returns available=False when no worker metrics exist."""
        from backend.api.routes.test_results import get_worker_metrics

        mock_pool = _MockPool(
            {
                "RUN_ID_LOOKUP": [("run-123",)],
                "WORKER_METRICS": [],  # No data
            }
        )

        with (
            patch(
                "backend.api.routes.test_results.snowflake_pool.get_default_pool",
                return_value=mock_pool,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.get",
                return_value=None,
            ),
            patch(
                "backend.api.routes.test_results._worker_metrics_cache.set",
            ),
        ):
            result = await get_worker_metrics("test-123", nocache=True)

        assert result["available"] is False
        assert result["workers"] == []
