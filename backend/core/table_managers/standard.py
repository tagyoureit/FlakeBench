"""
Standard Table Manager

Manages Snowflake standard tables with clustering keys and time travel.
"""

import logging
from typing import Dict, Any
import random
from datetime import datetime, timedelta

from backend.core.table_managers.base import TableManager
from backend.models.test_config import TableConfig
from backend.connectors import snowflake_pool

logger = logging.getLogger(__name__)


class StandardTableManager(TableManager):
    """
    Manages Snowflake standard tables.

    Features:
    - Clustering keys
    - Data retention (time travel)
    - Standard Snowflake table optimizations
    """

    def __init__(self, config: TableConfig):
        """Initialize standard table manager."""
        super().__init__(config)
        self.pool = snowflake_pool.get_default_pool()

    async def create_table(self) -> bool:
        """Create standard table with clustering and retention settings."""
        try:
            full_name = self.get_full_table_name()
            columns = self.get_column_definitions()

            # Build CREATE TABLE statement
            create_sql = f"CREATE TABLE {full_name} (\n"
            create_sql += ",\n".join(f"  {col}" for col in columns)
            create_sql += "\n)"

            # Add clustering keys
            if self.config.clustering_keys:
                cluster_cols = ", ".join(self.config.clustering_keys)
                create_sql += f"\nCLUSTER BY ({cluster_cols})"

            # Add data retention
            if self.config.data_retention_days:
                create_sql += (
                    f"\nDATA_RETENTION_TIME_IN_DAYS = {self.config.data_retention_days}"
                )

            logger.info(f"Creating standard table: {full_name}")
            logger.debug(f"SQL: {create_sql}")

            await self.pool.execute_query(create_sql)

            logger.info(f"✅ Standard table created: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create standard table: {e}")
            return False

    async def drop_table(self) -> bool:
        """Drop standard table."""
        try:
            full_name = self.get_full_table_name()
            drop_sql = f"DROP TABLE IF EXISTS {full_name}"

            logger.info(f"Dropping table: {full_name}")
            await self.pool.execute_query(drop_sql)

            logger.info(f"✅ Table dropped: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to drop table: {e}")
            return False

    async def truncate_table(self) -> bool:
        """Truncate standard table."""
        try:
            full_name = self.get_full_table_name()
            truncate_sql = f"TRUNCATE TABLE {full_name}"

            logger.info(f"Truncating table: {full_name}")
            await self.pool.execute_query(truncate_sql)

            logger.info(f"✅ Table truncated: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to truncate table: {e}")
            return False

    async def populate_data(self, row_count: int) -> bool:
        """
        Populate standard table with test data.

        Uses INSERT INTO with generated data based on column types.
        """
        try:
            full_name = self.get_full_table_name()

            # Generate data in batches
            batch_size = 1000
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

        Args:
            table_name: Full table name
            start_id: Starting ID value
            count: Number of rows to generate

        Returns:
            INSERT statement
        """
        columns = list(self.config.columns.keys())
        col_types = self.config.columns

        # Build INSERT
        insert_sql = f"INSERT INTO {table_name} ({', '.join(columns)})\nVALUES\n"

        rows = []
        for i in range(count):
            row_id = start_id + i
            values = []

            for col in columns:
                col_type = col_types[col].upper()
                values.append(self._generate_value(col, col_type, row_id))

            rows.append(f"({', '.join(values)})")

        insert_sql += ",\n".join(rows)
        return insert_sql

    def _generate_value(self, col_name: str, col_type: str, row_id: int) -> str:
        """
        Generate a sample value for a column.

        Args:
            col_name: Column name
            col_type: Column type
            row_id: Current row ID

        Returns:
            SQL value string
        """
        col_name_lower = col_name.lower()

        # ID columns
        if "id" in col_name_lower:
            return str(row_id)

        # Date/time columns
        if "DATE" in col_type or "TIMESTAMP" in col_type:
            # Generate dates over past 365 days
            days_ago = row_id % 365
            date = datetime.now() - timedelta(days=days_ago)
            return f"'{date.strftime('%Y-%m-%d')}'"

        # Number columns
        if "NUMBER" in col_type or "INT" in col_type or "DECIMAL" in col_type:
            return str(random.randint(1, 10000))

        # String columns
        if "VARCHAR" in col_type or "STRING" in col_type or "TEXT" in col_type:
            # Generate sample strings
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
        """Get standard table statistics."""
        try:
            full_name = self.get_full_table_name()

            # Get row count
            count_sql = f"SELECT COUNT(*) FROM {full_name}"
            result = await self.pool.execute_query(count_sql)
            row_count = result[0][0] if result else 0

            # Get table info from INFORMATION_SCHEMA
            parts = full_name.split(".")
            if len(parts) == 3:
                db, schema, table = parts
                info_sql = f"""
                SELECT 
                    ROW_COUNT,
                    BYTES,
                    CLUSTERING_KEY
                FROM {db}.INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = '{schema}'
                  AND TABLE_NAME = '{table}'
                """
                result = await self.pool.execute_query(info_sql)

                if result:
                    return {
                        "row_count": row_count,
                        "table_row_count": result[0][0],
                        "bytes": result[0][1],
                        "clustering_key": result[0][2],
                    }

            return {
                "row_count": row_count,
            }

        except Exception as e:
            logger.error(f"Failed to get table stats: {e}")
            return {"error": str(e)}

    async def table_exists(self) -> bool:
        """Check if standard table exists."""
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
        """Validate standard table schema."""
        try:
            full_name = self.get_full_table_name()
            desc_sql = f"DESCRIBE TABLE {full_name}"

            result = await self.pool.execute_query(desc_sql)

            if not result:
                return False

            # Check that all configured columns exist
            actual_columns = {row[0].lower(): row[1].upper() for row in result}

            for col_name, col_type in self.config.columns.items():
                if col_name.lower() not in actual_columns:
                    logger.error(f"Column {col_name} not found in table")
                    return False

            logger.info(f"✅ Schema validation passed: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Schema validation failed: {e}")
            return False
