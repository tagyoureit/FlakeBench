"""
Tests for interactive analytics support.

Covers:
- WarehouseInfo parsing of SHOW WAREHOUSES rows, including the attached tables
  column used for cache-warming attachment checks
- InteractiveTableManager detection of interactive tables vs zero-copy standard
  tables, attachment checks, and cache warming
- Cost routing by warehouse type and the provisioned break-even comparison
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from backend.core.cost_calculator import (
    CREDIT_RATE_BASIS,
    calculate_estimated_cost,
    calculate_interactive_breakeven,
    get_table_type_category,
)
from backend.core.table_managers.interactive import InteractiveTableManager
from backend.core.warehouse_info import (
    get_warehouse_info,
    is_interactive_warehouse,
    parse_warehouse_row,
)
from backend.models.test_config import TableConfig, TableType


def _show_warehouses_row(
    name: str = "IW_DEMO",
    state: str = "SUSPENDED",
    wh_type: str = "INTERACTIVE",
    size: str = "X-Small",
    tables: str = "",
) -> tuple:
    """Build a 38-column SHOW WAREHOUSES row matching live output layout."""
    row: list[Any] = [None] * 38
    row[0] = name
    row[1] = state
    row[2] = wh_type
    row[3] = size
    row[37] = tables
    return tuple(row)


def _table_config(name: str = "ORDERS") -> TableConfig:
    """Build a minimal table config for the interactive manager."""
    return TableConfig(
        name=name,
        table_type=TableType.INTERACTIVE,
        database="DB",
        schema_name="SCH",
        columns={"ID": "NUMBER"},
    )


def _manager(pool: AsyncMock) -> InteractiveTableManager:
    """Build an InteractiveTableManager with an injected mock pool."""
    manager = InteractiveTableManager.__new__(InteractiveTableManager)
    config = _table_config()
    manager.config = config
    manager.table_name = config.name
    manager.database = config.database
    manager.schema_name = config.schema_name
    manager.object_type = None
    manager._stats = {}
    manager.is_interactive_table = None
    manager.pool = pool
    return manager


class TestWarehouseInfo:
    """Warehouse metadata parsing drives every type-dependent decision."""

    def test_parses_interactive_warehouse(self):
        # Act
        info = parse_warehouse_row(_show_warehouses_row())

        # Assert
        assert info.name == "IW_DEMO"
        assert info.warehouse_type == "INTERACTIVE"
        assert info.is_interactive is True
        assert info.is_adaptive is False
        assert info.is_suspended is True
        assert info.size == "X-Small"

    def test_parses_adaptive_warehouse_with_empty_size(self):
        # Act
        info = parse_warehouse_row(
            _show_warehouses_row(state="ENABLED", wh_type="ADAPTIVE", size="")
        )

        # Assert
        assert info.is_adaptive is True
        assert info.is_interactive is False
        assert info.size is None
        # ENABLED is not SUSPENDED, so it must not be treated as needing resume
        assert info.is_suspended is False

    def test_parses_attached_tables(self):
        # Arrange
        tables = "DB.SCH.ORDERS,DB.SCH.CUSTOMERS"

        # Act
        info = parse_warehouse_row(_show_warehouses_row(tables=tables))

        # Assert
        assert info.attached_tables == ("DB.SCH.ORDERS", "DB.SCH.CUSTOMERS")
        assert info.has_table_attached("db.sch.orders") is True
        assert info.has_table_attached("DB.SCH.LINEITEM") is False

    def test_tolerates_truncated_row(self):
        # Arrange - a shorter row, as if Snowflake reordered later columns
        row = ("SMALL_WH", "STARTED", "STANDARD", "Small")

        # Act
        info = parse_warehouse_row(row)

        # Assert
        assert info.warehouse_type == "STANDARD"
        assert info.attached_tables == ()

    @pytest.mark.asyncio
    async def test_get_warehouse_info_returns_none_when_not_found(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.return_value = []

        # Act
        info = await get_warehouse_info(pool, "MISSING_WH")

        # Assert
        assert info is None

    @pytest.mark.asyncio
    async def test_get_warehouse_info_returns_none_on_error(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.side_effect = RuntimeError("no privileges")

        # Act
        info = await get_warehouse_info(pool, "IW_DEMO")

        # Assert - failure is indeterminate, not a negative answer
        assert info is None

    @pytest.mark.asyncio
    async def test_is_interactive_warehouse_returns_none_when_unknown(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.return_value = []

        # Act
        result = await is_interactive_warehouse(pool, "MISSING_WH")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_is_interactive_warehouse_true(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.return_value = [_show_warehouses_row()]

        # Act
        result = await is_interactive_warehouse(pool, "IW_DEMO")

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_empty_warehouse_name_skips_query(self):
        # Arrange
        pool = AsyncMock()

        # Act
        info = await get_warehouse_info(pool, "   ")

        # Assert
        assert info is None
        pool.execute_query.assert_not_awaited()


class TestInteractiveTableManagerExistence:
    """Detection must support both interactive tables and zero-copy standard tables."""

    @pytest.mark.asyncio
    async def test_detects_interactive_table(self):
        # Arrange - SHOW INTERACTIVE TABLES returns a row with cluster_by at idx 4
        pool = AsyncMock()
        row: list[Any] = [None] * 5
        row[4] = "(O_ORDERKEY)"
        pool.execute_query.return_value = [tuple(row)]
        manager = _manager(pool)

        # Act
        exists = await manager.table_exists()

        # Assert
        assert exists is True
        assert manager.is_interactive_table is True
        assert manager.object_type == "INTERACTIVE_TABLE"

    @pytest.mark.asyncio
    async def test_falls_back_to_standard_table_for_zero_copy(self):
        # Arrange - not an interactive table, but SHOW TABLES finds it
        pool = AsyncMock()
        pool.execute_query.side_effect = [
            [],  # SHOW INTERACTIVE TABLES
            [("ORDERS",)],  # SHOW TABLES
        ]
        manager = _manager(pool)

        # Act
        exists = await manager.table_exists()

        # Assert
        assert exists is True
        assert manager.is_interactive_table is False
        assert manager.object_type == "TABLE"

    @pytest.mark.asyncio
    async def test_interactive_lookup_failure_falls_back(self):
        # Arrange - account without interactive tables enabled
        pool = AsyncMock()
        pool.execute_query.side_effect = [
            RuntimeError("unsupported: SHOW INTERACTIVE TABLES"),
            [("ORDERS",)],
        ]
        manager = _manager(pool)

        # Act
        exists = await manager.table_exists()

        # Assert
        assert exists is True
        assert manager.is_interactive_table is False

    @pytest.mark.asyncio
    async def test_missing_object_returns_false(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.return_value = []
        manager = _manager(pool)

        # Act
        exists = await manager.table_exists()

        # Assert
        assert exists is False


class TestInteractiveTableManagerStats:
    """Stats must report interactive status and clustering key."""

    @pytest.mark.asyncio
    async def test_stats_include_clustering_key_and_flag(self):
        # Arrange
        pool = AsyncMock()
        interactive_row: list[Any] = [None] * 5
        interactive_row[4] = "(O_ORDERKEY, O_ORDERDATE)"
        pool.execute_query.side_effect = [
            [(1500,)],  # parent COUNT(*) fallback
            [tuple(interactive_row)],  # SHOW INTERACTIVE TABLES
        ]
        manager = _manager(pool)

        # Act
        stats = await manager.get_table_stats()

        # Assert
        assert stats["is_interactive_table"] is True
        assert stats["clustering_key"] == "O_ORDERKEY, O_ORDERDATE"

    @pytest.mark.asyncio
    async def test_stats_flag_false_for_zero_copy(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.side_effect = [
            [(1500,)],  # parent COUNT(*) fallback
            [],  # SHOW INTERACTIVE TABLES - not an interactive table
        ]
        manager = _manager(pool)

        # Act
        stats = await manager.get_table_stats()

        # Assert
        assert stats["is_interactive_table"] is False


class TestWarehouseAttachment:
    """Attachment must distinguish 'not attached' from 'could not determine'."""

    @pytest.mark.asyncio
    async def test_returns_true_when_attached(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.return_value = [_show_warehouses_row(tables="DB.SCH.ORDERS")]
        manager = _manager(pool)

        # Act
        result = await manager.check_warehouse_attachment("IW_DEMO")

        # Assert
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_not_attached(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.return_value = [_show_warehouses_row(tables="DB.SCH.OTHER")]
        manager = _manager(pool)

        # Act
        result = await manager.check_warehouse_attachment("IW_DEMO")

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_none_when_warehouse_unknown(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.return_value = []
        manager = _manager(pool)

        # Act
        result = await manager.check_warehouse_attachment("IW_DEMO")

        # Assert - None means indeterminate, NOT "not attached"
        assert result is None


class TestCacheWarming:
    """Cache warming must converge, report latencies, and never hang."""

    @pytest.mark.asyncio
    async def test_converges_on_fast_probe(self):
        # Arrange - mock probes return immediately, so latency is well under 200ms
        pool = AsyncMock()
        pool.execute_query.return_value = [(1,)]
        manager = _manager(pool)

        # Act
        result = await manager.warm_cache("IW_DEMO", timeout_s=5)

        # Assert
        assert result["converged"] is True
        assert result["iterations"] == 1
        assert result["cold_latency_ms"] is not None
        assert result["warm_latency_ms"] is not None
        assert result["warehouse"] == "IW_DEMO"
        assert result["table"] == "DB.SCH.ORDERS"

    @pytest.mark.asyncio
    async def test_reports_error_when_probe_fails(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.side_effect = RuntimeError("table not found")
        manager = _manager(pool)

        # Act
        result = await manager.warm_cache("IW_DEMO", timeout_s=5)

        # Assert
        assert result["iterations"] == 0
        assert result["converged"] is False
        assert "table not found" in result["error"]

    @pytest.mark.asyncio
    async def test_does_not_switch_warehouse_context(self):
        # Arrange
        pool = AsyncMock()
        pool.execute_query.return_value = [(1,)]
        manager = _manager(pool)

        # Act
        await manager.warm_cache("IW_DEMO", timeout_s=5)

        # Assert - warming must not issue USE WAREHOUSE per iteration
        executed = [str(c.args[0]).upper() for c in pool.execute_query.await_args_list]
        assert not any("USE WAREHOUSE" in sql for sql in executed)


class TestCostRoutingByWarehouseType:
    """An interactive warehouse bills at Table 1(d) rates for any table type."""

    @pytest.mark.parametrize(
        "table_type,warehouse_type,expected",
        [
            ("STANDARD", "INTERACTIVE", "interactive"),
            ("INTERACTIVE", "INTERACTIVE", "interactive"),
            ("INTERACTIVE", None, "interactive"),
            ("STANDARD", "STANDARD", "warehouse"),
            ("STANDARD", None, "warehouse"),
            ("HYBRID", "STANDARD", "warehouse"),
            ("POSTGRES", "INTERACTIVE", "postgres"),
        ],
        ids=[
            "zero-copy",
            "interactive-both",
            "interactive-table-only",
            "standard-both",
            "standard-no-wh-type",
            "hybrid",
            "postgres-wins",
        ],
    )
    def test_category_precedence(
        self, table_type: str, warehouse_type: str | None, expected: str
    ):
        # Act / Assert
        assert get_table_type_category(table_type, warehouse_type) == expected

    def test_zero_copy_uses_interactive_rate(self):
        # Act
        result = calculate_estimated_cost(
            3600,
            "X-SMALL",
            table_type="STANDARD",
            warehouse_type="INTERACTIVE",
        )

        # Assert - Table 1(d) X-Small rate, not the standard 1 credit/hr
        assert result["credits_per_hour"] == 0.6
        assert result["credits_used"] == pytest.approx(0.6)

    def test_standard_warehouse_unchanged(self):
        # Act - no warehouse_type supplied, preserving prior behaviour
        result = calculate_estimated_cost(3600, "X-SMALL", table_type="STANDARD")

        # Assert
        assert result["credits_per_hour"] == 1
        assert result["credits_used"] == pytest.approx(1.0)

    @pytest.mark.parametrize(
        "size,expected_rate",
        [("X-Small", 0.6), ("Medium", 2.4), ("X-SMALL", 0.6), ("MEDIUM", 2.4)],
        ids=["xs-titlecase", "medium-titlecase", "xs-upper", "medium-upper"],
    )
    def test_live_show_warehouses_size_casing(self, size: str, expected_rate: float):
        # Arrange / Act - SHOW WAREHOUSES reports "X-Small"/"Medium" casing
        result = calculate_estimated_cost(
            3600, size, table_type="INTERACTIVE", warehouse_type="INTERACTIVE"
        )

        # Assert
        assert result["credits_per_hour"] == expected_rate

    def test_unknown_size_reports_unavailable_not_a_default(self):
        # Arrange - interactive warehouses ALWAYS report a definite size, so a
        # missing size means the lookup failed and must not be defaulted.
        # Act
        result = calculate_estimated_cost(
            3600, None, table_type="INTERACTIVE", warehouse_type="INTERACTIVE"
        )

        # Assert - no fabricated MEDIUM rate
        assert result["credits_per_hour"] == 0.0
        assert result["credits_used"] == 0.0
        assert result["calculation_method"] == "unavailable"
        assert result["provisioned_comparison"]["breakeven_standard_wh_hours"] is None

    def test_actual_credits_still_honoured_when_size_unknown(self):
        # Arrange - actual credits are authoritative even without a rate
        # Act
        result = calculate_estimated_cost(
            3600,
            None,
            actual_credits_used=7.5,
            table_type="INTERACTIVE",
            warehouse_type="INTERACTIVE",
        )

        # Assert
        assert result["credits_used"] == pytest.approx(7.5)
        assert result["calculation_method"] == "actual"


class TestInteractiveBreakeven:
    """Break-even hours is the comparable figure; 24h totals are the supporting detail."""

    def test_xsmall_breakeven(self):
        # Act
        result = calculate_interactive_breakeven("X-SMALL")

        # Assert - 0.6 x 24 = 14.4 credits/day vs standard 1 credit/hr
        assert result["iw_24h_credits"] == pytest.approx(14.4)
        assert result["standard_wh_24h_credits"] == pytest.approx(24.0)
        assert result["breakeven_standard_wh_hours"] == pytest.approx(14.4)
        assert result["rate_basis"] == CREDIT_RATE_BASIS

    def test_medium_breakeven(self):
        # Act
        result = calculate_interactive_breakeven("MEDIUM")

        # Assert - 2.4 x 24 = 57.6 credits/day; standard MEDIUM is 4 credits/hr
        assert result["iw_24h_credits"] == pytest.approx(57.6)
        assert result["breakeven_standard_wh_hours"] == pytest.approx(14.4)

    def test_comparison_against_larger_standard_warehouse(self):
        # Act - interactive X-Small versus a Medium standard warehouse
        result = calculate_interactive_breakeven("X-SMALL", "MEDIUM")

        # Assert - 14.4 credits / 4 credits per hour = 3.6 hours
        assert result["breakeven_standard_wh_hours"] == pytest.approx(3.6)
        assert result["comparison_warehouse_size"] == "MEDIUM"

    def test_unknown_size_returns_nulls_not_fabricated_values(self):
        # Act
        result = calculate_interactive_breakeven("ADAPTIVE")

        # Assert - adaptive bills per query, so no provisioned figure exists
        assert result["iw_24h_credits"] is None
        assert result["standard_wh_24h_credits"] is None
        assert result["breakeven_standard_wh_hours"] is None
        assert result["rate_basis"] == CREDIT_RATE_BASIS

    def test_missing_size_returns_nulls(self):
        # Act
        result = calculate_interactive_breakeven(None)

        # Assert
        assert result["breakeven_standard_wh_hours"] is None
        assert result["interactive_warehouse_size"] == "UNKNOWN"

    def test_dollar_figures_scale_with_credit_price(self):
        # Act
        result = calculate_interactive_breakeven("X-SMALL", dollars_per_credit=3.00)

        # Assert
        assert result["iw_24h_cost_usd"] == pytest.approx(43.2)
        assert result["standard_wh_24h_cost_usd"] == pytest.approx(72.0)
        # Break-even is a ratio of credits, so it is price-independent
        assert result["breakeven_standard_wh_hours"] == pytest.approx(14.4)

    def test_interactive_run_includes_provisioned_comparison(self):
        # Act
        result = calculate_estimated_cost(
            300, "X-SMALL", table_type="STANDARD", warehouse_type="INTERACTIVE"
        )

        # Assert
        comparison = result["provisioned_comparison"]
        assert comparison["breakeven_standard_wh_hours"] == pytest.approx(14.4)
        assert "no uptime assumption" in comparison["assumption"]
