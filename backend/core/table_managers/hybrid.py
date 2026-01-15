"""
Hybrid Table Manager (Existing Objects Only)

Benchmarks existing Snowflake hybrid tables and views.

Table creation is intentionally not supported by this app.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.core.table_managers.base import TableManager
from backend.connectors import snowflake_pool

logger = logging.getLogger(__name__)


class HybridTableManager(TableManager):
    """
    Manages existing Snowflake hybrid tables/views.

    The existing object schema is treated as authoritative and is introspected at setup time.
    """

    def __init__(self, config):
        super().__init__(config)
        self.pool = snowflake_pool.get_default_pool()

    async def get_table_stats(self) -> dict[str, Any]:
        """
        Get basic table/view statistics.

        For hybrid tables, we use INFORMATION_SCHEMA.TABLES row estimate instead of
        SELECT COUNT(*) because COUNT(*) on large hybrid tables is extremely slow
        (no micro-partition metadata optimization like standard tables).
        """
        full_name = self.get_full_table_name()
        stats: dict[str, Any] = {}

        if self.object_type:
            stats["object_type"] = self.object_type

        # For hybrid tables, prefer INFORMATION_SCHEMA estimate (fast) over COUNT(*) (slow).
        # COUNT(*) on a 150M row hybrid table can take 1-2 minutes vs ~1 second for metadata.
        if (self.object_type or "").upper() == "TABLE":
            try:
                parts = full_name.split(".")
                if len(parts) == 3:
                    db, schema, table = parts
                    info = await self.pool.execute_query(
                        f"""
                        SELECT ROW_COUNT, BYTES
                        FROM {db}.INFORMATION_SCHEMA.TABLES
                        WHERE TABLE_SCHEMA = '{schema}'
                          AND TABLE_NAME = '{table}'
                        """
                    )
                    if info and info[0][0] is not None:
                        stats["row_count"] = int(info[0][0])
                        stats["table_row_count"] = info[0][0]
                        stats["bytes"] = info[0][1]
                        stats["row_count_source"] = "INFORMATION_SCHEMA"
                        return stats
            except Exception as e:
                logger.debug("INFORMATION_SCHEMA lookup failed: %s", e)

        # Fallback to COUNT(*) only if INFORMATION_SCHEMA failed or for views.
        # Note: This is slow for large hybrid tables but needed for views.
        try:
            rows = await self.pool.execute_query(f"SELECT COUNT(*) FROM {full_name}")
            stats["row_count"] = (
                int(rows[0][0]) if rows and rows[0] and rows[0][0] else 0
            )
            stats["row_count_source"] = "COUNT"
        except Exception as e:
            stats["row_count"] = None
            stats["row_count_error"] = str(e)

        return stats

    async def table_exists(self) -> bool:
        """Check if the selected object exists as a table or view."""
        try:
            check_tables = f"SHOW TABLES LIKE '{self.table_name}'"
            if self.database and self.schema_name:
                check_tables += f" IN {self.database}.{self.schema_name}"

            tables = await self.pool.execute_query(check_tables)
            if tables:
                self.object_type = "TABLE"
                return True

            check_views = f"SHOW VIEWS LIKE '{self.table_name}'"
            if self.database and self.schema_name:
                check_views += f" IN {self.database}.{self.schema_name}"

            views = await self.pool.execute_query(check_views)
            if views:
                self.object_type = "VIEW"
                return True

            return False
        except Exception as e:
            logger.debug("Error checking object existence: %s", e)
            return False

    async def validate_schema(self) -> bool:
        """Introspect the existing table/view schema and hydrate `config.columns`."""
        full_name = self.get_full_table_name()

        try:
            rows: list[tuple] = []
            try:
                rows = await self.pool.execute_query(f"DESCRIBE TABLE {full_name}")
                self.object_type = self.object_type or "TABLE"
            except Exception:
                rows = await self.pool.execute_query(f"DESCRIBE VIEW {full_name}")
                self.object_type = "VIEW"

            if not rows:
                return False

            columns: dict[str, str] = {}
            for row in rows:
                if not row:
                    continue
                col_name = str(row[0]).strip().upper()
                col_type = str(row[1]).strip().upper() if len(row) > 1 else ""
                if col_name:
                    columns[col_name] = col_type

            if not columns:
                return False

            self.config.columns = columns
            logger.info("✅ Schema validation passed: %s", full_name)
            return True
        except Exception as e:
            logger.error("Schema validation failed: %s", e)
            return False
