"""
Warehouse management mixin for test execution.

Handles warehouse state checks, resume/suspend operations.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class WarehouseManagerMixin:
    """Mixin providing warehouse management functionality."""

    # These attributes are expected from TestExecutor
    scenario: Any
    _did_resume_warehouse: bool
    _benchmark_warehouse_name: Optional[str]

    def _requires_interactive_warehouse(self) -> bool:
        """Check if any table requires an Interactive warehouse (HYBRID or INTERACTIVE type)."""
        for table_config in self.scenario.table_configs:
            table_type = str(getattr(table_config, "table_type", "")).upper()
            if table_type in ("HYBRID", "INTERACTIVE"):
                return True
        return False

    async def _check_warehouse_state(self, pool: Any, warehouse_name: str) -> str | None:
        """
        Check the current state of a warehouse.

        Returns:
            State string ('STARTED', 'SUSPENDED', 'RESUMING', etc.) or None if not found.
        """
        try:
            results = await pool.execute_query(f"SHOW WAREHOUSES LIKE '{warehouse_name}'")
            if results:
                for row in results:
                    if len(row) >= 4 and str(row[0]).upper() == warehouse_name.upper():
                        return str(row[3]).upper()
            return None
        except Exception as e:
            logger.warning(f"Failed to check warehouse state for {warehouse_name}: {e}")
            return None

    async def _resume_warehouse(self, pool: Any, warehouse_name: str) -> bool:
        """Resume a suspended warehouse. Returns True if successful."""
        try:
            await pool.execute_query(f"ALTER WAREHOUSE {warehouse_name} RESUME")
            logger.info(f"✅ Resumed suspended warehouse: {warehouse_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to resume warehouse {warehouse_name}: {e}")
            return False

    async def _suspend_warehouse(self, pool: Any, warehouse_name: str) -> bool:
        """Suspend a warehouse. Returns True if successful."""
        try:
            await pool.execute_query(f"ALTER WAREHOUSE {warehouse_name} SUSPEND")
            logger.info(f"✅ Suspended warehouse: {warehouse_name}")
            return True
        except Exception as e:
            logger.warning(f"Failed to suspend warehouse {warehouse_name}: {e}")
            return False
