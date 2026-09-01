"""
Tests for pre-flight warning generation (orchestrator_modules.preflight).

Covers:
- Config extraction from the nested SCENARIO_CONFIG shape written by create_run
- Backwards compatibility with legacy flat keys in persisted rows
- Lock contention warnings firing on realistic nested configs
- Orchestrator delegating to the single module implementation
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.orchestrator_modules.preflight import (
    LOCK_WAITER_LIMIT,
    extract_preflight_config,
    generate_preflight_warnings,
)
from backend.core.warehouse_info import WarehouseInfo


def _nested_config(
    *,
    table_type: str = "standard",
    concurrent_connections: int = 10,
    write_weight_pct: float = 0.0,
    warehouse: str = "",
    table_name: str = "DB.SCH.ORDERS",
    custom_sql: str | None = None,
) -> dict[str, Any]:
    """Build a scenario config matching the shape Orchestrator.create_run writes.

    ``warehouse`` defaults to empty so warehouse-dependent checks short-circuit
    without a live lookup. Tests that need it inject ``warehouse_info``.
    """
    custom_queries: list[dict[str, Any]] = []
    if write_weight_pct > 0:
        custom_queries.append({"query_kind": "UPDATE", "weight_pct": write_weight_pct})
        custom_queries.append(
            {"query_kind": "SELECT", "weight_pct": 100.0 - write_weight_pct}
        )
    if custom_sql is not None:
        custom_queries.append(
            {"query_kind": "GENERIC_SQL", "weight_pct": 100.0, "sql": custom_sql}
        )
    return {
        "template_id": "tpl-1",
        "target": {
            "table_name": table_name,
            "table_type": table_type,
            "warehouse": warehouse,
            "database": "DB",
            "schema": "SCH",
        },
        "workload": {
            "concurrent_connections": concurrent_connections,
            "custom_queries": custom_queries,
        },
    }


def _warehouse(
    *,
    name: str = "IW_DEMO",
    warehouse_type: str = "INTERACTIVE",
    size: str | None = "X-Small",
    state: str = "STARTED",
    attached: tuple[str, ...] = (),
) -> WarehouseInfo:
    """Build warehouse metadata for injection, avoiding a live lookup."""
    return WarehouseInfo(
        name=name,
        state=state,
        warehouse_type=warehouse_type,
        size=size,
        attached_tables=attached,
    )


def _titles(warnings: list[dict[str, Any]]) -> set[str]:
    """Collect warning titles for concise assertions."""
    return {w["title"] for w in warnings}


class TestExtractPreflightConfig:
    """Config extraction must read the nested shape actually persisted."""

    def test_reads_nested_target_and_workload(self):
        # Arrange
        config = _nested_config(
            table_type="interactive",
            concurrent_connections=64,
            write_weight_pct=25.0,
            warehouse="IW_DEMO",
            table_name="DB.SCH.EVENTS",
        )

        # Act
        cfg = extract_preflight_config(config)

        # Assert
        assert cfg.table_type == "interactive"
        assert cfg.table_name == "DB.SCH.EVENTS"
        assert cfg.warehouse == "IW_DEMO"
        assert cfg.total_threads == 64
        assert cfg.write_pct == pytest.approx(0.25)
        assert cfg.expected_concurrent_writes == pytest.approx(16.0)

    def test_falls_back_to_legacy_flat_keys(self):
        # Arrange - shape of older persisted rows
        config = {
            "table_type": "HYBRID",
            "table_name": "LEGACY.T",
            "warehouse": "OLD_WH",
            "total_threads": 40,
            "workload": {},
        }

        # Act
        cfg = extract_preflight_config(config)

        # Assert
        assert cfg.table_type == "hybrid"
        assert cfg.table_name == "LEGACY.T"
        assert cfg.warehouse == "OLD_WH"
        assert cfg.total_threads == 40

    def test_applies_defaults_for_empty_config(self):
        # Act
        cfg = extract_preflight_config({})

        # Assert
        assert cfg.table_type == "standard"
        assert cfg.table_name == ""
        assert cfg.warehouse == ""
        assert cfg.total_threads == 10
        assert cfg.write_pct == 0.0

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("48", 48),
            (48.7, 48),
            (None, 10),
            ("", 10),
            ("not-a-number", 10),
        ],
        ids=["str", "float", "none", "empty", "garbage"],
    )
    def test_thread_count_coercion(self, raw: Any, expected: int):
        # Arrange
        config = {"workload": {"concurrent_connections": raw}}

        # Act
        cfg = extract_preflight_config(config)

        # Assert
        assert cfg.total_threads == expected


class TestLockContentionWarnings:
    """Lock contention checks must fire on the nested config, not silently pass."""

    @pytest.mark.asyncio
    async def test_high_severity_when_over_waiter_limit(self):
        # Arrange - 100 threads x 50% writes = 50 concurrent writers > 20
        config = _nested_config(concurrent_connections=100, write_weight_pct=50.0)

        # Act
        warnings = await generate_preflight_warnings(config)

        # Assert
        assert len(warnings) == 1
        warning = warnings[0]
        assert warning["severity"] == "high"
        assert warning["title"] == "Lock Contention Risk"
        assert warning["details"]["total_threads"] == 100
        assert warning["details"]["expected_concurrent_writes"] == pytest.approx(50.0)
        assert warning["details"]["lock_waiter_limit"] == LOCK_WAITER_LIMIT
        assert warning["recommendations"]

    @pytest.mark.asyncio
    async def test_medium_severity_when_approaching_limit(self):
        # Arrange - 30 threads x 50% writes = 15 concurrent writers (>10, <=20)
        config = _nested_config(concurrent_connections=30, write_weight_pct=50.0)

        # Act
        warnings = await generate_preflight_warnings(config)

        # Assert
        assert len(warnings) == 1
        assert warnings[0]["severity"] == "medium"
        assert warnings[0]["title"] == "Potential Lock Contention"

    @pytest.mark.asyncio
    async def test_no_warning_for_read_only_workload(self):
        # Arrange
        config = _nested_config(concurrent_connections=200, write_weight_pct=0.0)

        # Act
        warnings = await generate_preflight_warnings(config)

        # Assert
        assert warnings == []

    @pytest.mark.asyncio
    async def test_no_lock_warning_for_non_standard_table(self):
        # Arrange - hybrid tables use row-level locking
        config = _nested_config(
            table_type="hybrid", concurrent_connections=100, write_weight_pct=50.0
        )

        # Act
        warnings = await generate_preflight_warnings(config)

        # Assert
        assert not any(w["title"].endswith("Lock Contention") for w in warnings)
        assert not any(w["title"] == "Lock Contention Risk" for w in warnings)


class TestInteractiveWarehouseWarnings:
    """Interactive and zero-copy checks branch on warehouse type, not table type.

    ``clustering_key`` is always passed explicitly ("" means known-absent) so no
    live metadata lookup occurs.
    """

    @pytest.mark.asyncio
    async def test_mismatch_when_interactive_table_on_standard_warehouse(self):
        # Arrange
        config = _nested_config(table_type="interactive", warehouse="STD_WH")

        # Act
        warnings = await generate_preflight_warnings(
            config,
            warehouse_info=_warehouse(
                name="STD_WH", warehouse_type="STANDARD", size="Medium"
            ),
            clustering_key="(ID)",
        )

        # Assert
        assert "Warehouse Type Mismatch" in _titles(warnings)
        mismatch = next(w for w in warnings if w["title"] == "Warehouse Type Mismatch")
        assert mismatch["severity"] == "high"
        assert mismatch["details"]["warehouse_type"] == "STANDARD"

    @pytest.mark.asyncio
    async def test_no_mismatch_when_interactive_table_on_interactive_warehouse(self):
        # Arrange
        config = _nested_config(table_type="interactive", warehouse="IW_DEMO")

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key="(ID)"
        )

        # Assert
        assert "Warehouse Type Mismatch" not in _titles(warnings)

    @pytest.mark.asyncio
    async def test_timeout_and_billing_warnings_on_interactive_warehouse(self):
        # Arrange
        config = _nested_config(table_type="interactive", warehouse="IW_DEMO")

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key="(ID)"
        )

        # Assert
        titles = _titles(warnings)
        assert "Interactive Warehouse Query Timeout" in titles
        assert "Interactive Warehouse Billing Model" in titles

    @pytest.mark.asyncio
    async def test_no_interactive_warnings_on_standard_warehouse(self):
        # Arrange
        config = _nested_config(warehouse="STD_WH")

        # Act
        warnings = await generate_preflight_warnings(
            config,
            warehouse_info=_warehouse(name="STD_WH", warehouse_type="STANDARD"),
            clustering_key="",
        )

        # Assert - no interactive-specific noise on a plain standard scenario
        assert warnings == []

    @pytest.mark.asyncio
    async def test_missing_clustering_key_flagged_for_zero_copy(self):
        # Arrange - standard table, interactive warehouse, no clustering key
        config = _nested_config(table_type="standard", warehouse="IW_DEMO")

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key=""
        )

        # Assert
        assert "No Clustering Key for Interactive Queries" in _titles(warnings)

    @pytest.mark.asyncio
    async def test_clustering_key_present_suppresses_warning(self):
        # Arrange
        config = _nested_config(table_type="standard", warehouse="IW_DEMO")

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key="LINEAR(O_ORDERKEY)"
        )

        # Assert
        assert "No Clustering Key for Interactive Queries" not in _titles(warnings)

    @pytest.mark.asyncio
    async def test_writes_flagged_on_interactive_warehouse(self):
        # Arrange
        config = _nested_config(
            table_type="interactive", warehouse="IW_DEMO", write_weight_pct=30.0
        )

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key="(ID)"
        )

        # Assert
        assert "Writes on Interactive Path" in _titles(warnings)

    @pytest.mark.asyncio
    async def test_read_only_workload_not_flagged_for_writes(self):
        # Arrange
        config = _nested_config(table_type="interactive", warehouse="IW_DEMO")

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key="(ID)"
        )

        # Assert
        assert "Writes on Interactive Path" not in _titles(warnings)

    @pytest.mark.parametrize(
        "sql,expected_construct",
        [
            ("CALL my_proc(1)", "CALL (stored procedures)"),
            ("SELECT a ->> b FROM t", "->> pipe operator"),
        ],
        ids=["call", "pipe-operator"],
    )
    @pytest.mark.asyncio
    async def test_unsupported_sql_flagged(self, sql: str, expected_construct: str):
        # Arrange
        config = _nested_config(warehouse="IW_DEMO", custom_sql=sql)

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key="(ID)"
        )

        # Assert
        warning = next(
            w
            for w in warnings
            if w["title"] == "Unsupported SQL on Interactive Warehouse"
        )
        assert expected_construct in warning["details"]["unsupported_constructs"]

    @pytest.mark.asyncio
    async def test_plain_select_not_flagged_as_unsupported(self):
        # Arrange
        config = _nested_config(warehouse="IW_DEMO", custom_sql="SELECT 1 FROM t")

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key="(ID)"
        )

        # Assert
        assert "Unsupported SQL on Interactive Warehouse" not in _titles(warnings)

    @pytest.mark.asyncio
    async def test_zero_copy_info_when_standard_table_unattached(self):
        # Arrange
        config = _nested_config(table_type="standard", warehouse="IW_DEMO")

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key="(ID)"
        )

        # Assert
        info = next(
            w for w in warnings if w["title"] == "Zero-Copy Interactive Analytics"
        )
        assert info["severity"] == "info"
        assert info["details"]["table_attached"] is False
        assert any("ADD TABLES" in r for r in info["recommendations"])

    @pytest.mark.asyncio
    async def test_zero_copy_info_reports_attached_table(self):
        # Arrange
        config = _nested_config(table_type="standard", warehouse="IW_DEMO")

        # Act
        warnings = await generate_preflight_warnings(
            config,
            warehouse_info=_warehouse(attached=("DB.SCH.ORDERS",)),
            clustering_key="(ID)",
        )

        # Assert
        info = next(
            w for w in warnings if w["title"] == "Zero-Copy Interactive Analytics"
        )
        assert info["details"]["table_attached"] is True
        assert not any("ADD TABLES" in r for r in info["recommendations"])

    @pytest.mark.asyncio
    async def test_no_zero_copy_info_for_interactive_table(self):
        # Arrange
        config = _nested_config(table_type="interactive", warehouse="IW_DEMO")

        # Act
        warnings = await generate_preflight_warnings(
            config, warehouse_info=_warehouse(), clustering_key="(ID)"
        )

        # Assert
        assert "Zero-Copy Interactive Analytics" not in _titles(warnings)

    @pytest.mark.asyncio
    async def test_warnings_skipped_when_warehouse_type_unknown(self):
        # Arrange - no warehouse configured, so nothing can be resolved
        config = _nested_config(table_type="interactive", warehouse="")

        # Act
        warnings = await generate_preflight_warnings(config, clustering_key="")

        # Assert - indeterminate warehouse type must not produce false warnings
        assert warnings == []


class TestOrchestratorDelegation:
    """The orchestrator must not carry a second divergent implementation."""

    @pytest.mark.asyncio
    async def test_orchestrator_matches_module_output(self):
        # Arrange
        from backend.core.orchestrator import OrchestratorService

        config = _nested_config(concurrent_connections=100, write_weight_pct=50.0)
        orchestrator = OrchestratorService.__new__(OrchestratorService)

        # Act
        via_method = await orchestrator.generate_preflight_warnings(config)
        via_module = await generate_preflight_warnings(config)

        # Assert
        assert via_method == via_module
        assert via_method[0]["severity"] == "high"
