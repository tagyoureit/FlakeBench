"""
Tests for _validate_generic_sql_preflight() in TestExecutor (Item 7).

Covers:
- DDL blocking (CREATE/ALTER/DROP/TRUNCATE/RENAME/GRANT/REVOKE/COMMENT)
- DML-write detection for READ operations (INSERT/UPDATE/DELETE/MERGE/COPY)
- DML-write allowed for WRITE operations
- Valid SELECT passes
- EXPLAIN validation via mocked pool
- Zero-weight queries are skipped
- No GENERIC_SQL queries returns None
- Mixed valid/invalid — error aggregation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.models import TestScenario, WorkloadType, TableType


def _build_executor(custom_queries: list[dict], table_managers=None):
    """
    Build a TestExecutor with custom_queries injected into the scenario,
    bypassing heavy __init__ side effects where possible.
    """
    from backend.models.test_config import TableConfig
    from backend.core.test_executor import TestExecutor

    table_cfg = TableConfig(
        name="T1",
        table_type=TableType.STANDARD,
        columns={"id": "INT", "val": "VARCHAR"},
    )
    scenario = TestScenario(
        name="preflight-test",
        workload_type=WorkloadType.MIXED,
        duration_seconds=10,
        concurrent_connections=1,
        custom_queries=custom_queries,
        table_configs=[table_cfg],
    )
    executor = TestExecutor(scenario)
    if table_managers is not None:
        executor.table_managers = table_managers
    return executor


def _mock_sf_table_manager(*, full_name="DB.SCH.T1", pool=None):
    """Create a mock table manager with a Snowflake-like pool."""
    mgr = MagicMock()
    mgr.get_full_table_name.return_value = full_name
    mgr.pool = pool
    return mgr


class TestDDLBlocking:
    """DDL statements (CREATE, ALTER, DROP, etc.) are always blocked."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "CREATE TABLE t (id INT)",
            "ALTER TABLE t ADD COLUMN x INT",
            "DROP TABLE t",
            "TRUNCATE TABLE t",
            "RENAME TABLE t TO t2",
            "GRANT SELECT ON t TO role_x",
            "REVOKE SELECT ON t FROM role_x",
            "COMMENT ON TABLE t IS 'hello'",
        ],
        ids=[
            "create",
            "alter",
            "drop",
            "truncate",
            "rename",
            "grant",
            "revoke",
            "comment",
        ],
    )
    async def test_ddl_rejected(self, sql: str) -> None:
        queries = [{"query_kind": "GENERIC_SQL", "weight_pct": 50, "sql": sql}]
        executor = _build_executor(queries)
        error = await executor._validate_generic_sql_preflight()
        assert error is not None
        assert "DDL" in error

    @pytest.mark.asyncio
    async def test_ddl_case_insensitive(self) -> None:
        queries = [
            {"query_kind": "GENERIC_SQL", "weight_pct": 50, "sql": "  drop TABLE t  "}
        ]
        executor = _build_executor(queries)
        error = await executor._validate_generic_sql_preflight()
        assert error is not None
        assert "DDL" in error


class TestDMLWriteDetection:
    """DML-write statements blocked for READ operations, allowed for WRITE."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO t VALUES (1)",
            "UPDATE t SET x = 1",
            "DELETE FROM t WHERE id = 1",
            "MERGE INTO t USING s ON t.id = s.id WHEN MATCHED THEN UPDATE SET x = 1",
            "COPY INTO t FROM @stage",
        ],
        ids=["insert", "update", "delete", "merge", "copy"],
    )
    async def test_dml_write_rejected_for_read(self, sql: str) -> None:
        queries = [
            {
                "query_kind": "GENERIC_SQL",
                "weight_pct": 50,
                "sql": sql,
                "operation_type": "READ",
            }
        ]
        executor = _build_executor(queries)
        error = await executor._validate_generic_sql_preflight()
        assert error is not None
        assert "operation_type is READ" in error

    @pytest.mark.asyncio
    async def test_insert_allowed_for_write(self) -> None:
        queries = [
            {
                "query_kind": "GENERIC_SQL",
                "weight_pct": 50,
                "sql": "INSERT INTO {table} VALUES (1)",
                "operation_type": "WRITE",
            }
        ]
        mgr = _mock_sf_table_manager()
        executor = _build_executor(queries, table_managers=[mgr])
        # No sf_pool means EXPLAIN is skipped — only prefix checks run.
        error = await executor._validate_generic_sql_preflight()
        assert error is None


class TestValidSelectPasses:
    """A clean SELECT query should return None (no error)."""

    @pytest.mark.asyncio
    async def test_select_passes(self) -> None:
        queries = [
            {
                "query_kind": "GENERIC_SQL",
                "weight_pct": 50,
                "sql": "SELECT * FROM {table} LIMIT 10",
            }
        ]
        mgr = _mock_sf_table_manager()
        executor = _build_executor(queries, table_managers=[mgr])
        error = await executor._validate_generic_sql_preflight()
        assert error is None


class TestExplainValidation:
    """EXPLAIN-based syntax validation via mocked Snowflake pool."""

    @pytest.mark.asyncio
    async def test_explain_failure_returns_error(self) -> None:
        pool = AsyncMock()
        pool.execute_query = AsyncMock(
            side_effect=Exception("object 'BAD_TABLE' does not exist")
        )
        mgr = _mock_sf_table_manager(pool=pool)
        # Ensure the manager is NOT an instance of PostgresTableManager
        mgr.__class__ = MagicMock
        queries = [
            {
                "query_kind": "GENERIC_SQL",
                "weight_pct": 50,
                "sql": "SELECT * FROM BAD_TABLE",
            }
        ]
        executor = _build_executor(queries, table_managers=[mgr])
        error = await executor._validate_generic_sql_preflight()
        assert error is not None
        assert "syntax validation failed" in error.lower()

    @pytest.mark.asyncio
    async def test_explain_success_passes(self) -> None:
        pool = AsyncMock()
        pool.execute_query = AsyncMock(return_value=[])  # EXPLAIN success
        mgr = _mock_sf_table_manager(pool=pool)
        mgr.__class__ = MagicMock
        queries = [
            {
                "query_kind": "GENERIC_SQL",
                "weight_pct": 50,
                "sql": "SELECT 1 FROM {table}",
            }
        ]
        executor = _build_executor(queries, table_managers=[mgr])
        error = await executor._validate_generic_sql_preflight()
        assert error is None

    @pytest.mark.asyncio
    async def test_explain_null_type_mismatch_ignored(self) -> None:
        """NULL-substitution type mismatches should be suppressed."""
        pool = AsyncMock()
        pool.execute_query = AsyncMock(
            side_effect=Exception("Numeric value 'NULL' is not recognized")
        )
        mgr = _mock_sf_table_manager(pool=pool)
        mgr.__class__ = MagicMock
        queries = [
            {
                "query_kind": "GENERIC_SQL",
                "weight_pct": 50,
                "sql": "SELECT * FROM {table} WHERE id = ?",
            }
        ]
        executor = _build_executor(queries, table_managers=[mgr])
        error = await executor._validate_generic_sql_preflight()
        # NULL mismatch => suppressed => no error
        assert error is None


class TestZeroWeightSkipped:
    """Queries with weight_pct <= 0 are skipped entirely."""

    @pytest.mark.asyncio
    async def test_zero_weight_skipped(self) -> None:
        queries = [
            {"query_kind": "GENERIC_SQL", "weight_pct": 0, "sql": "DROP TABLE evil"},
        ]
        executor = _build_executor(queries)
        error = await executor._validate_generic_sql_preflight()
        assert error is None

    @pytest.mark.asyncio
    async def test_negative_weight_skipped(self) -> None:
        queries = [
            {"query_kind": "GENERIC_SQL", "weight_pct": -5, "sql": "DROP TABLE evil"},
        ]
        executor = _build_executor(queries)
        error = await executor._validate_generic_sql_preflight()
        assert error is None


class TestNoGenericSQLQueries:
    """When no GENERIC_SQL queries are present, returns None."""

    @pytest.mark.asyncio
    async def test_empty_custom_queries(self) -> None:
        executor = _build_executor([])
        error = await executor._validate_generic_sql_preflight()
        assert error is None

    @pytest.mark.asyncio
    async def test_only_oltp_kinds(self) -> None:
        queries = [
            {
                "query_kind": "POINT_LOOKUP",
                "weight_pct": 50,
                "sql": "SELECT * FROM t WHERE id = ?",
            },
            {
                "query_kind": "RANGE_SCAN",
                "weight_pct": 50,
                "sql": "SELECT * FROM t LIMIT 100",
            },
        ]
        executor = _build_executor(queries)
        error = await executor._validate_generic_sql_preflight()
        assert error is None


class TestMixedValidInvalid:
    """Multiple entries where one fails — error aggregation."""

    @pytest.mark.asyncio
    async def test_mixed_entries_aggregated(self) -> None:
        queries = [
            {
                "query_kind": "GENERIC_SQL",
                "weight_pct": 50,
                "sql": "SELECT 1",
                "operation_type": "READ",
            },
            {
                "query_kind": "GENERIC_SQL",
                "weight_pct": 50,
                "sql": "DROP TABLE t",
                "operation_type": "READ",
            },
            {
                "query_kind": "GENERIC_SQL",
                "weight_pct": 50,
                "sql": "INSERT INTO t VALUES (1)",
                "operation_type": "READ",
            },
        ]
        executor = _build_executor(queries)
        error = await executor._validate_generic_sql_preflight()
        assert error is not None
        # Should contain both errors
        assert "DDL" in error
        assert "operation_type is READ" in error
