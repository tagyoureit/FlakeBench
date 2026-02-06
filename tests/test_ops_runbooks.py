"""
Tests for Section 2.12: Ops & Runbooks.

Covers:
- Fail-fast checks (DB connectivity, schema existence, template validity)
- Health endpoint behavior
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from backend.core.orchestrator import OrchestratorService


# ---------------------------------------------------------------------------
# Mock Pool Classes for Fail-Fast Tests
# ---------------------------------------------------------------------------


class _FailFastPool:
    """Mock pool for fail-fast check tests."""

    def __init__(
        self,
        *,
        db_connected: bool = True,
        existing_tables: set[str] | None = None,
        template_exists: bool = True,
        template_lookup_fails: bool = False,
    ) -> None:
        self.db_connected = db_connected
        self.existing_tables = existing_tables or {
            "RUN_STATUS",
            "TEST_RESULTS",
            "RUN_CONTROL_EVENTS",
            "WORKER_HEARTBEATS",
            "WORKER_METRICS_SNAPSHOTS",
            "TEST_TEMPLATES",
        }
        self.template_exists = template_exists
        self.template_lookup_fails = template_lookup_fails
        self.calls: list[tuple[str, list[object] | None]] = []

    async def execute_query(
        self, query: str, params: list[object] | None = None
    ) -> list[tuple[Any, ...]]:
        self.calls.append((query, params))
        sql = " ".join(str(query).split()).upper()

        # DB connectivity check
        if sql.strip() == "SELECT 1":
            if not self.db_connected:
                raise ConnectionError("Snowflake connection failed")
            return [(1,)]

        # Template lookup (check before schema check since TEST_TEMPLATES is a table too)
        if "TEST_TEMPLATES" in sql and "WHERE TEMPLATE_ID" in sql:
            if self.template_lookup_fails:
                raise Exception("Template lookup query failed")
            if self.template_exists:
                return [(1,)]
            return []

        # Schema existence check - extract table name from fully qualified path
        # e.g., "SELECT 1 FROM FLAKEBENCH.TEST_RESULTS.RUN_STATUS LIMIT 1"
        if "SELECT 1 FROM" in sql and "LIMIT 1" in sql:
            # Extract the table name (last part after the last dot before LIMIT)
            import re

            match = re.search(
                r"SELECT 1 FROM [A-Z0-9_]+\.[A-Z0-9_]+\.([A-Z0-9_]+)", sql
            )
            if match:
                table_name = match.group(1)
                if table_name in self.existing_tables:
                    return [(1,)]
            raise Exception("Table does not exist")

        return []


# ---------------------------------------------------------------------------
# Section 2.12: Fail-Fast Checks Tests
# ---------------------------------------------------------------------------


class TestFailFastDBConnectivity:
    """Tests for fail-fast DB connectivity check."""

    @pytest.mark.asyncio
    async def test_db_connectivity_success(self) -> None:
        """Fail-fast passes when DB connection succeeds."""
        pool = _FailFastPool(db_connected=True)
        svc = OrchestratorService()
        svc._pool = pool

        # Should not raise
        await svc._run_fail_fast_checks()

        # Verify DB check was called
        db_check_calls = [c for c in pool.calls if c[0].strip() == "SELECT 1"]
        assert len(db_check_calls) == 1

    @pytest.mark.asyncio
    async def test_db_connectivity_failure_raises(self) -> None:
        """Fail-fast raises ValueError when DB connection fails."""
        pool = _FailFastPool(db_connected=False)
        svc = OrchestratorService()
        svc._pool = pool

        with pytest.raises(ValueError, match="Failed to connect to Snowflake"):
            await svc._run_fail_fast_checks()

    @pytest.mark.asyncio
    async def test_db_check_runs_first(self) -> None:
        """DB connectivity is checked before schema checks."""
        pool = _FailFastPool(db_connected=True)
        svc = OrchestratorService()
        svc._pool = pool

        await svc._run_fail_fast_checks()

        # First call should be the DB check
        assert pool.calls[0][0].strip() == "SELECT 1"


class TestFailFastSchemaExistence:
    """Tests for fail-fast schema existence checks."""

    @pytest.mark.asyncio
    async def test_all_required_tables_checked(self) -> None:
        """Fail-fast checks all required control plane tables."""
        pool = _FailFastPool()
        svc = OrchestratorService()
        svc._pool = pool

        await svc._run_fail_fast_checks()

        # Extract table checks from calls
        table_check_calls = [
            c[0] for c in pool.calls if "SELECT 1 FROM" in c[0] and "LIMIT 1" in c[0]
        ]

        # Required tables per implementation
        required_tables = {
            "RUN_STATUS",
            "TEST_RESULTS",
            "RUN_CONTROL_EVENTS",
            "WORKER_HEARTBEATS",
            "WORKER_METRICS_SNAPSHOTS",
        }

        for table in required_tables:
            found = any(table in call for call in table_check_calls)
            assert found, f"Missing schema check for {table}"

    @pytest.mark.asyncio
    async def test_missing_run_status_raises(self) -> None:
        """Fail-fast raises when RUN_STATUS table is missing."""
        pool = _FailFastPool(
            existing_tables={
                "TEST_RESULTS",
                "RUN_CONTROL_EVENTS",
                "WORKER_HEARTBEATS",
                "WORKER_METRICS_SNAPSHOTS",
            }
        )
        svc = OrchestratorService()
        svc._pool = pool

        with pytest.raises(ValueError, match="Missing required table.*RUN_STATUS"):
            await svc._run_fail_fast_checks()

    @pytest.mark.asyncio
    async def test_missing_test_results_raises(self) -> None:
        """Fail-fast raises when TEST_RESULTS table is missing."""
        pool = _FailFastPool(
            existing_tables={
                "RUN_STATUS",
                "RUN_CONTROL_EVENTS",
                "WORKER_HEARTBEATS",
                "WORKER_METRICS_SNAPSHOTS",
            }
        )
        svc = OrchestratorService()
        svc._pool = pool

        with pytest.raises(ValueError, match="Missing required table.*TEST_RESULTS"):
            await svc._run_fail_fast_checks()

    @pytest.mark.asyncio
    async def test_missing_control_events_raises(self) -> None:
        """Fail-fast raises when RUN_CONTROL_EVENTS table is missing."""
        pool = _FailFastPool(
            existing_tables={
                "RUN_STATUS",
                "TEST_RESULTS",
                "WORKER_HEARTBEATS",
                "WORKER_METRICS_SNAPSHOTS",
            }
        )
        svc = OrchestratorService()
        svc._pool = pool

        with pytest.raises(
            ValueError, match="Missing required table.*RUN_CONTROL_EVENTS"
        ):
            await svc._run_fail_fast_checks()

    @pytest.mark.asyncio
    async def test_missing_worker_heartbeats_raises(self) -> None:
        """Fail-fast raises when WORKER_HEARTBEATS table is missing."""
        pool = _FailFastPool(
            existing_tables={
                "RUN_STATUS",
                "TEST_RESULTS",
                "RUN_CONTROL_EVENTS",
                "WORKER_METRICS_SNAPSHOTS",
            }
        )
        svc = OrchestratorService()
        svc._pool = pool

        with pytest.raises(
            ValueError, match="Missing required table.*WORKER_HEARTBEATS"
        ):
            await svc._run_fail_fast_checks()

    @pytest.mark.asyncio
    async def test_missing_metrics_snapshots_raises(self) -> None:
        """Fail-fast raises when WORKER_METRICS_SNAPSHOTS table is missing."""
        pool = _FailFastPool(
            existing_tables={
                "RUN_STATUS",
                "TEST_RESULTS",
                "RUN_CONTROL_EVENTS",
                "WORKER_HEARTBEATS",
            }
        )
        svc = OrchestratorService()
        svc._pool = pool

        with pytest.raises(
            ValueError, match="Missing required table.*WORKER_METRICS_SNAPSHOTS"
        ):
            await svc._run_fail_fast_checks()

    @pytest.mark.asyncio
    async def test_schema_check_uses_limit_1(self) -> None:
        """Schema checks use LIMIT 1 for efficiency."""
        pool = _FailFastPool()
        svc = OrchestratorService()
        svc._pool = pool

        await svc._run_fail_fast_checks()

        # All table checks should have LIMIT 1
        table_check_calls = [c[0] for c in pool.calls if "SELECT 1 FROM" in c[0]]
        for call in table_check_calls:
            assert "LIMIT 1" in call, f"Missing LIMIT 1 in: {call}"


class TestFailFastTemplateValidity:
    """Tests for fail-fast template validity checks."""

    @pytest.mark.asyncio
    async def test_template_check_skipped_when_no_template_id(self) -> None:
        """Template check is skipped when template_id is not provided."""
        pool = _FailFastPool()
        svc = OrchestratorService()
        svc._pool = pool

        await svc._run_fail_fast_checks(template_id=None)

        # No template lookup should occur
        template_calls = [
            c for c in pool.calls if "TEST_TEMPLATES" in c[0] and "WHERE" in c[0]
        ]
        assert len(template_calls) == 0

    @pytest.mark.asyncio
    async def test_template_check_skipped_when_empty_string(self) -> None:
        """Template check is skipped when template_id is empty string."""
        pool = _FailFastPool()
        svc = OrchestratorService()
        svc._pool = pool

        await svc._run_fail_fast_checks(template_id="")

        # No template lookup should occur
        template_calls = [
            c for c in pool.calls if "TEST_TEMPLATES" in c[0] and "WHERE" in c[0]
        ]
        assert len(template_calls) == 0

    @pytest.mark.asyncio
    async def test_template_check_skipped_when_whitespace_only(self) -> None:
        """Template check is skipped when template_id is whitespace only."""
        pool = _FailFastPool()
        svc = OrchestratorService()
        svc._pool = pool

        await svc._run_fail_fast_checks(template_id="   ")

        # No template lookup should occur
        template_calls = [
            c for c in pool.calls if "TEST_TEMPLATES" in c[0] and "WHERE" in c[0]
        ]
        assert len(template_calls) == 0

    @pytest.mark.asyncio
    async def test_template_exists_passes(self) -> None:
        """Fail-fast passes when template exists."""
        pool = _FailFastPool(template_exists=True)
        svc = OrchestratorService()
        svc._pool = pool

        # Should not raise
        await svc._run_fail_fast_checks(template_id="test-template-123")

        # Verify template lookup was called
        template_calls = [
            c for c in pool.calls if "TEST_TEMPLATES" in c[0] and "WHERE" in c[0]
        ]
        assert len(template_calls) == 1

    @pytest.mark.asyncio
    async def test_template_not_found_raises(self) -> None:
        """Fail-fast raises when template does not exist."""
        pool = _FailFastPool(template_exists=False)
        svc = OrchestratorService()
        svc._pool = pool

        with pytest.raises(ValueError, match="Template.*not found"):
            await svc._run_fail_fast_checks(template_id="nonexistent-template")

    @pytest.mark.asyncio
    async def test_template_lookup_failure_raises(self) -> None:
        """Fail-fast raises when template lookup query fails."""
        pool = _FailFastPool(template_lookup_fails=True)
        svc = OrchestratorService()
        svc._pool = pool

        with pytest.raises(ValueError, match="Template lookup failed"):
            await svc._run_fail_fast_checks(template_id="some-template")

    @pytest.mark.asyncio
    async def test_template_check_uses_limit_1(self) -> None:
        """Template check uses LIMIT 1 for efficiency."""
        pool = _FailFastPool(template_exists=True)
        svc = OrchestratorService()
        svc._pool = pool

        await svc._run_fail_fast_checks(template_id="test-template")

        # Template lookup should have LIMIT 1
        template_calls = [
            c[0] for c in pool.calls if "TEST_TEMPLATES" in c[0] and "WHERE" in c[0]
        ]
        assert len(template_calls) == 1
        assert "LIMIT 1" in template_calls[0]

    @pytest.mark.asyncio
    async def test_template_check_uses_parameterized_query(self) -> None:
        """Template check uses parameterized query for safety."""
        pool = _FailFastPool(template_exists=True)
        svc = OrchestratorService()
        svc._pool = pool

        template_id = "test-template-456"
        await svc._run_fail_fast_checks(template_id=template_id)

        # Find the template lookup call
        template_calls = [
            c for c in pool.calls if "TEST_TEMPLATES" in c[0] and "WHERE" in c[0]
        ]
        assert len(template_calls) == 1

        # Should use ? placeholder and pass template_id as param
        query, params = template_calls[0]
        assert "?" in query
        assert params == [template_id]


class TestFailFastIntegration:
    """Integration tests for fail-fast check ordering and behavior."""

    @pytest.mark.asyncio
    async def test_fail_fast_order_db_then_schema_then_template(self) -> None:
        """Fail-fast checks run in order: DB -> Schema -> Template."""
        pool = _FailFastPool(template_exists=True)
        svc = OrchestratorService()
        svc._pool = pool

        await svc._run_fail_fast_checks(template_id="test-template")

        # First call: DB check
        assert pool.calls[0][0].strip() == "SELECT 1"

        # Middle calls: Schema checks (5 tables)
        schema_calls = pool.calls[1:6]
        for call in schema_calls:
            assert "SELECT 1 FROM" in call[0]
            assert "LIMIT 1" in call[0]

        # Last call: Template check
        assert "TEST_TEMPLATES" in pool.calls[-1][0]
        assert "WHERE TEMPLATE_ID" in pool.calls[-1][0]

    @pytest.mark.asyncio
    async def test_fail_fast_stops_on_first_failure(self) -> None:
        """Fail-fast stops checking after first failure."""
        pool = _FailFastPool(db_connected=False)
        svc = OrchestratorService()
        svc._pool = pool

        with pytest.raises(ValueError):
            await svc._run_fail_fast_checks(template_id="test-template")

        # Only DB check should have been called
        assert len(pool.calls) == 1
        assert pool.calls[0][0].strip() == "SELECT 1"


# ---------------------------------------------------------------------------
# Section 2.12: Health Endpoint Tests
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
    """Tests for /health endpoint behavior."""

    @pytest.mark.asyncio
    async def test_health_endpoint_returns_healthy_status(self) -> None:
        """Health endpoint returns healthy status when all checks pass."""
        from backend.main import health_check

        # Mock the snowflake_pool
        mock_pool = AsyncMock()
        mock_pool.get_pool_stats = AsyncMock(
            return_value={"initialized": True, "size": 5}
        )

        with patch(
            "backend.connectors.snowflake_pool.get_default_pool", return_value=mock_pool
        ):
            result = await health_check()

        assert result["status"] == "healthy"
        assert result["service"] == "flakebench"
        assert "checks" in result

    @pytest.mark.asyncio
    async def test_health_endpoint_includes_snowflake_check(self) -> None:
        """Health endpoint includes Snowflake connection check."""
        from backend.main import health_check

        mock_pool = AsyncMock()
        mock_pool.get_pool_stats = AsyncMock(
            return_value={"initialized": True, "size": 5, "available": 3}
        )

        with patch(
            "backend.connectors.snowflake_pool.get_default_pool", return_value=mock_pool
        ):
            result = await health_check()

        assert "snowflake" in result["checks"]
        assert result["checks"]["snowflake"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_endpoint_degraded_on_snowflake_failure(self) -> None:
        """Health endpoint returns degraded when Snowflake check fails."""
        from backend.main import health_check

        mock_pool = AsyncMock()
        mock_pool.get_pool_stats = AsyncMock(side_effect=Exception("Connection failed"))

        with patch(
            "backend.connectors.snowflake_pool.get_default_pool", return_value=mock_pool
        ):
            result = await health_check()

        assert result["status"] == "degraded"
        assert result["checks"]["snowflake"]["status"] == "unhealthy"

    @pytest.mark.asyncio
    async def test_health_endpoint_not_initialized_status(self) -> None:
        """Health endpoint reports not_initialized when pool not ready."""
        from backend.main import health_check

        mock_pool = AsyncMock()
        mock_pool.get_pool_stats = AsyncMock(
            return_value={"initialized": False, "size": 0}
        )

        with patch(
            "backend.connectors.snowflake_pool.get_default_pool", return_value=mock_pool
        ):
            result = await health_check()

        assert result["checks"]["snowflake"]["status"] == "not_initialized"

    @pytest.mark.asyncio
    async def test_health_endpoint_includes_version(self) -> None:
        """Health endpoint includes service version."""
        from backend.main import health_check

        mock_pool = AsyncMock()
        mock_pool.get_pool_stats = AsyncMock(
            return_value={"initialized": True, "size": 5}
        )

        with patch(
            "backend.connectors.snowflake_pool.get_default_pool", return_value=mock_pool
        ):
            result = await health_check()

        assert "version" in result
        assert result["version"] == "0.1.0"

    @pytest.mark.asyncio
    async def test_health_endpoint_includes_environment(self) -> None:
        """Health endpoint includes environment indicator."""
        from backend.main import health_check

        mock_pool = AsyncMock()
        mock_pool.get_pool_stats = AsyncMock(
            return_value={"initialized": True, "size": 5}
        )

        with patch(
            "backend.connectors.snowflake_pool.get_default_pool", return_value=mock_pool
        ):
            result = await health_check()

        assert "environment" in result
        assert result["environment"] in {"development", "production"}


class TestHealthEndpointPostgres:
    """Tests for /health endpoint Postgres checks."""

    @pytest.mark.asyncio
    async def test_health_includes_postgres_when_enabled(self) -> None:
        """Health endpoint includes Postgres check when enabled."""
        from backend.main import health_check

        mock_sf_pool = AsyncMock()
        mock_sf_pool.get_pool_stats = AsyncMock(
            return_value={"initialized": True, "size": 5}
        )

        mock_pg_pool = AsyncMock()
        mock_pg_pool.get_pool_stats = AsyncMock(
            return_value={"initialized": True, "size": 3}
        )
        mock_pg_pool.is_healthy = AsyncMock(return_value=True)

        with (
            patch(
                "backend.connectors.snowflake_pool.get_default_pool",
                return_value=mock_sf_pool,
            ),
            patch(
                "backend.connectors.postgres_pool.get_default_pool",
                return_value=mock_pg_pool,
            ),
            patch("backend.main.settings.ENABLE_POSTGRES", True),
        ):
            result = await health_check()

        assert "postgres" in result["checks"]
        assert result["checks"]["postgres"]["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_postgres_unhealthy(self) -> None:
        """Health endpoint reports unhealthy Postgres."""
        from backend.main import health_check

        mock_sf_pool = AsyncMock()
        mock_sf_pool.get_pool_stats = AsyncMock(
            return_value={"initialized": True, "size": 5}
        )

        mock_pg_pool = AsyncMock()
        mock_pg_pool.get_pool_stats = AsyncMock(
            return_value={"initialized": True, "size": 3}
        )
        mock_pg_pool.is_healthy = AsyncMock(return_value=False)

        with (
            patch(
                "backend.connectors.snowflake_pool.get_default_pool",
                return_value=mock_sf_pool,
            ),
            patch(
                "backend.connectors.postgres_pool.get_default_pool",
                return_value=mock_pg_pool,
            ),
            patch("backend.main.settings.ENABLE_POSTGRES", True),
        ):
            result = await health_check()

        assert result["checks"]["postgres"]["status"] == "unhealthy"
