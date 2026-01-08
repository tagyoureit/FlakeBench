"""
Hybrid Table Manager

Manages Snowflake hybrid tables with primary keys and indexes.
"""

import logging
from typing import Dict, Any
import random
from datetime import datetime, timedelta

from backend.core.table_managers.base import TableManager
from backend.models.test_config import TableConfig
from backend.connectors import snowflake_pool

logger = logging.getLogger(__name__)


class HybridTableManager(TableManager):
    """
    Manages Snowflake hybrid tables.

    Features:
    - Primary keys (required)
    - Secondary indexes
    - Foreign key constraints
    - Row-level operations
    """

    def __init__(self, config: TableConfig):
        """Initialize hybrid table manager."""
        super().__init__(config)
        self.pool = snowflake_pool.get_default_pool()

        # Validate config
        if not config.primary_key:
            raise ValueError("Hybrid tables require a primary key")
        self.primary_key = config.primary_key

    async def create_table(self) -> bool:
        """Create hybrid table with primary key and indexes."""
        try:
            full_name = self.get_full_table_name()
            columns = self.get_column_definitions()

            # Build CREATE HYBRID TABLE statement
            create_sql = f"CREATE HYBRID TABLE {full_name} (\n"
            create_sql += ",\n".join(f"  {col}" for col in columns)

            # Add primary key constraint
            pk_cols = ", ".join(self.primary_key)
            create_sql += f",\n  PRIMARY KEY ({pk_cols})"

            # Add foreign key constraints if specified
            if self.config.foreign_keys:
                for fk in self.config.foreign_keys:
                    fk_name = fk.get("name", "fk")
                    fk_cols = ", ".join(fk["columns"])
                    ref_table = fk["ref_table"]
                    ref_cols = ", ".join(fk["ref_columns"])
                    create_sql += f",\n  CONSTRAINT {fk_name} FOREIGN KEY ({fk_cols}) REFERENCES {ref_table}({ref_cols})"

            create_sql += "\n)"

            logger.info(f"Creating hybrid table: {full_name}")
            logger.debug(f"SQL: {create_sql}")

            await self.pool.execute_query(create_sql)

            # Create secondary indexes
            if self.config.indexes:
                await self._create_indexes(full_name)

            logger.info(f"✅ Hybrid table created: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create hybrid table: {e}")
            return False

    async def _create_indexes(self, table_name: str):
        """Create secondary indexes on hybrid table."""
        indexes = self.config.indexes or []
        for idx in indexes:
            try:
                idx_name = idx.get("name", f"idx_{len(indexes)}")
                idx_cols = ", ".join(idx["columns"])

                # Check if this is a composite index with INCLUDE
                include_cols = idx.get("include", [])

                index_sql = f"CREATE INDEX {idx_name} ON {table_name} ({idx_cols})"

                # Add INCLUDE columns for covering indexes
                if include_cols:
                    include_str = ", ".join(include_cols)
                    index_sql += f" INCLUDE ({include_str})"

                logger.info(f"Creating index: {idx_name}")
                await self.pool.execute_query(index_sql)

            except Exception as e:
                logger.error(f"Failed to create index {idx_name}: {e}")

    async def drop_table(self) -> bool:
        """Drop hybrid table."""
        try:
            full_name = self.get_full_table_name()
            drop_sql = f"DROP TABLE IF EXISTS {full_name}"

            logger.info(f"Dropping hybrid table: {full_name}")
            await self.pool.execute_query(drop_sql)

            logger.info(f"✅ Hybrid table dropped: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to drop hybrid table: {e}")
            return False

    async def truncate_table(self) -> bool:
        """Truncate hybrid table."""
        try:
            full_name = self.get_full_table_name()
            truncate_sql = f"TRUNCATE TABLE {full_name}"

            logger.info(f"Truncating hybrid table: {full_name}")
            await self.pool.execute_query(truncate_sql)

            logger.info(f"✅ Hybrid table truncated: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to truncate hybrid table: {e}")
            return False

    async def populate_data(self, row_count: int) -> bool:
        """
        Populate hybrid table with test data.

        Uses INSERT INTO with generated data. For hybrid tables,
        we ensure primary key uniqueness.
        """
        try:
            full_name = self.get_full_table_name()

            # For hybrid tables, use smaller batches for better performance
            batch_size = 500
            total_batches = (row_count + batch_size - 1) // batch_size

            logger.info(
                f"Populating {full_name} with {row_count} rows in {total_batches} batches"
            )

            for batch_num in range(total_batches):
                start_id = batch_num * batch_size
                end_id = min(start_id + batch_size, row_count)
                batch_count = end_id - start_id

                # Generate INSERT statement
                insert_sql = self._generate_insert_statement(
                    full_name, start_id, batch_count
                )

                await self.pool.execute_query(insert_sql)

                if (batch_num + 1) % 10 == 0 or batch_num == total_batches - 1:
                    logger.info(f"  Progress: {end_id}/{row_count} rows inserted")

            logger.info(f"✅ Data population complete: {row_count} rows")
            return True

        except Exception as e:
            logger.error(f"Failed to populate data: {e}")
            return False

    def _generate_insert_statement(
        self, table_name: str, start_id: int, count: int
    ) -> str:
        """
        Generate INSERT statement with sample data.

        Ensures primary key uniqueness for hybrid tables.
        """
        columns = list(self.config.columns.keys())
        col_types = self.config.columns
        pk_cols = set(self.primary_key)

        # Build INSERT
        insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)})\nVALUES\n"

        rows = []
        for i in range(count):
            row_id = start_id + i
            values = []

            for col in columns:
                col_type = col_types[col].upper()

                # Ensure PK columns are unique
                if col in pk_cols:
                    values.append(str(row_id))
                else:
                    values.append(self._generate_value(col, col_type, row_id))

            rows.append(f"({', '.join(values)})")

        insert_sql += ",\n".join(rows)
        return insert_sql

    def _generate_value(self, col_name: str, col_type: str, row_id: int) -> str:
        """Generate a sample value for a column."""
        col_name_lower = col_name.lower()

        # Date/time columns
        if "DATE" in col_type or "TIMESTAMP" in col_type:
            days_ago = row_id % 365
            date = datetime.now() - timedelta(days=days_ago)
            return f"'{date.strftime('%Y-%m-%d')}'"

        # Number columns
        if "NUMBER" in col_type or "INT" in col_type or "DECIMAL" in col_type:
            return str(random.randint(1, 10000))

        # String columns
        if "VARCHAR" in col_type or "STRING" in col_type or "TEXT" in col_type:
            if "customer" in col_name_lower:
                return f"'CUSTOMER_{row_id % 1000}'"
            elif "region" in col_name_lower:
                regions = ["NORTH", "SOUTH", "EAST", "WEST", "CENTRAL"]
                return f"'{regions[row_id % len(regions)]}'"
            elif "status" in col_name_lower:
                statuses = ["ACTIVE", "PENDING", "COMPLETED", "CANCELLED"]
                return f"'{statuses[row_id % len(statuses)]}'"
            else:
                return f"'VALUE_{row_id}'"

        # Boolean columns
        if "BOOLEAN" in col_type:
            return "TRUE" if row_id % 2 == 0 else "FALSE"

        # Default
        return f"'VALUE_{row_id}'"

    async def get_table_stats(self) -> Dict[str, Any]:
        """Get hybrid table statistics."""
        try:
            full_name = self.get_full_table_name()

            # Get row count
            count_sql = f"SELECT COUNT(*) FROM {full_name}"
            result = await self.pool.execute_query(count_sql)
            row_count = result[0][0] if result else 0

            # Get table info
            parts = full_name.split(".")
            stats = {
                "row_count": row_count,
                "primary_key": ", ".join(self.primary_key),
                "index_count": len(self.config.indexes) if self.config.indexes else 0,
            }

            # Try to get additional info from INFORMATION_SCHEMA
            if len(parts) == 3:
                db, schema, table = parts
                info_sql = f"""
                SELECT 
                    ROW_COUNT,
                    BYTES
                FROM {db}.INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = '{schema}'
                  AND TABLE_NAME = '{table}'
                """
                result = await self.pool.execute_query(info_sql)

                if result:
                    stats["table_row_count"] = result[0][0]
                    stats["bytes"] = result[0][1]

            return stats

        except Exception as e:
            logger.error(f"Failed to get table stats: {e}")
            return {"error": str(e)}

    async def table_exists(self) -> bool:
        """Check if hybrid table exists."""
        try:
            check_sql = f"SHOW TABLES LIKE '{self.table_name}'"

            if self.database and self.schema_name:
                check_sql += f" IN {self.database}.{self.schema_name}"

            result = await self.pool.execute_query(check_sql)
            return len(result) > 0

        except Exception as e:
            logger.debug(f"Error checking table existence: {e}")
            return False

    async def validate_schema(self) -> bool:
        """Validate hybrid table schema."""
        try:
            full_name = self.get_full_table_name()
            desc_sql = f"DESCRIBE TABLE {full_name}"

            result = await self.pool.execute_query(desc_sql)

            if not result:
                return False

            # Check that all configured columns exist
            actual_columns = {row[0].lower(): row[1].upper() for row in result}

            for col_name in self.config.columns.keys():
                if col_name.lower() not in actual_columns:
                    logger.error(f"Column {col_name} not found in table")
                    return False

            # Verify primary key columns exist
            for pk_col in self.primary_key:
                if pk_col.lower() not in actual_columns:
                    logger.error(f"Primary key column {pk_col} not found")
                    return False

            logger.info(f"✅ Schema validation passed: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Schema validation failed: {e}")
            return False
