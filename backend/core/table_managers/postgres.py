"""
Postgres Table Manager

Manages Postgres tables (standalone Postgres, Snowflake-Postgres, CrunchyData).
"""

import logging
from typing import Dict, Any
import random
from datetime import datetime, timedelta

from backend.core.table_managers.base import TableManager
from backend.models.test_config import TableConfig, TableType
from backend.connectors import postgres_pool

logger = logging.getLogger(__name__)


class PostgresTableManager(TableManager):
    """
    Manages Postgres tables.

    Supports:
    - Standalone Postgres
    - Snowflake via Postgres protocol
    - CrunchyData

    Features:
    - B-tree, Hash, GIN, GiST indexes
    - Primary and foreign keys
    - Check constraints
    """

    def __init__(self, config: TableConfig):
        """Initialize Postgres table manager."""
        super().__init__(config)

        # Select appropriate pool based on table type
        if config.table_type == TableType.SNOWFLAKE_POSTGRES:
            self.pool = postgres_pool.get_snowflake_postgres_pool()
        elif config.table_type == TableType.CRUNCHYDATA:
            self.pool = postgres_pool.get_crunchydata_pool()
        else:  # TableType.POSTGRES
            self.pool = postgres_pool.get_default_pool()

    async def create_table(self) -> bool:
        """Create Postgres table with indexes and constraints."""
        try:
            full_name = self.get_full_table_name()
            columns = self.get_column_definitions()

            # Convert Snowflake types to Postgres types
            pg_columns = [self._convert_to_postgres_type(col) for col in columns]

            # Build CREATE TABLE statement
            create_sql = f"CREATE TABLE {full_name} (\n"
            create_sql += ",\n".join(f"  {col}" for col in pg_columns)

            # Add primary key if specified
            if self.config.primary_key:
                pk_cols = ", ".join(self.config.primary_key)
                create_sql += f",\n  PRIMARY KEY ({pk_cols})"

            # Add foreign keys if specified
            if self.config.foreign_keys:
                for fk in self.config.foreign_keys:
                    fk_name = fk.get("name", "fk")
                    fk_cols = ", ".join(fk["columns"])
                    ref_table = fk["ref_table"]
                    ref_cols = ", ".join(fk["ref_columns"])
                    create_sql += f",\n  CONSTRAINT {fk_name} FOREIGN KEY ({fk_cols}) REFERENCES {ref_table}({ref_cols})"

            create_sql += "\n)"

            logger.info(f"Creating Postgres table: {full_name}")
            logger.debug(f"SQL: {create_sql}")

            await self.pool.execute_query(create_sql)

            # Create indexes
            if self.config.postgres_indexes:
                await self._create_indexes(full_name)

            logger.info(f"✅ Postgres table created: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to create Postgres table: {e}")
            return False

    def _convert_to_postgres_type(self, col_def: str) -> str:
        """
        Convert Snowflake column type to Postgres type.

        Args:
            col_def: Column definition (e.g., "id NUMBER")

        Returns:
            Postgres column definition
        """
        parts = col_def.split()
        if len(parts) < 2:
            return col_def

        col_name = parts[0]
        col_type = " ".join(parts[1:]).upper()

        # Type mapping
        type_map = {
            "NUMBER": "NUMERIC",
            "VARCHAR": "VARCHAR",
            "STRING": "TEXT",
            "TEXT": "TEXT",
            "DATE": "DATE",
            "TIMESTAMP": "TIMESTAMP",
            "BOOLEAN": "BOOLEAN",
            "BINARY": "BYTEA",
            "VARIANT": "JSONB",
            "OBJECT": "JSONB",
            "ARRAY": "JSONB",
        }

        # Handle DECIMAL(p,s)
        if "DECIMAL" in col_type:
            pg_type = col_type.replace("DECIMAL", "NUMERIC")
        else:
            # Find matching type
            pg_type = col_type
            for sf_type, pg_type_mapped in type_map.items():
                if sf_type in col_type:
                    pg_type = col_type.replace(sf_type, pg_type_mapped)
                    break

        return f"{col_name} {pg_type}"

    async def _create_indexes(self, table_name: str):
        """Create indexes on Postgres table."""
        indexes = self.config.postgres_indexes or []
        for idx in indexes:
            try:
                idx_name = idx.get("name", f"idx_{len(indexes)}")
                idx_cols = ", ".join(idx["columns"])
                idx_type = idx.get("type", "btree").lower()

                index_sql = f"CREATE INDEX {idx_name} ON {table_name} USING {idx_type} ({idx_cols})"

                logger.info(f"Creating index: {idx_name} ({idx_type})")
                await self.pool.execute_query(index_sql)

            except Exception as e:
                logger.error(f"Failed to create index {idx_name}: {e}")

    async def drop_table(self) -> bool:
        """Drop Postgres table."""
        try:
            full_name = self.get_full_table_name()
            drop_sql = f"DROP TABLE IF EXISTS {full_name} CASCADE"

            logger.info(f"Dropping Postgres table: {full_name}")
            await self.pool.execute_query(drop_sql)

            logger.info(f"✅ Postgres table dropped: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to drop Postgres table: {e}")
            return False

    async def truncate_table(self) -> bool:
        """Truncate Postgres table."""
        try:
            full_name = self.get_full_table_name()
            truncate_sql = f"TRUNCATE TABLE {full_name} CASCADE"

            logger.info(f"Truncating Postgres table: {full_name}")
            await self.pool.execute_query(truncate_sql)

            logger.info(f"✅ Postgres table truncated: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to truncate Postgres table: {e}")
            return False

    async def populate_data(self, row_count: int) -> bool:
        """
        Populate Postgres table with test data.

        Uses INSERT INTO with batch inserts for performance.
        """
        try:
            full_name = self.get_full_table_name()

            # Use smaller batches for Postgres
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
        """Generate INSERT statement with sample data for Postgres."""
        columns = list(self.config.columns.keys())
        col_types = self.config.columns
        pk_cols = set(self.config.primary_key) if self.config.primary_key else set()

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
        """Generate a sample value for a Postgres column."""
        col_name_lower = col_name.lower()

        # Date/time columns
        if "DATE" in col_type or "TIMESTAMP" in col_type:
            days_ago = row_id % 365
            date = datetime.now() - timedelta(days=days_ago)
            return f"'{date.strftime('%Y-%m-%d')}'"

        # Number columns
        if (
            "NUMBER" in col_type
            or "INT" in col_type
            or "DECIMAL" in col_type
            or "NUMERIC" in col_type
        ):
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

        # JSON columns
        if "JSONB" in col_type or "JSON" in col_type:
            return f'\'{{"id": {row_id}, "value": "data_{row_id}"}}\''

        # Default
        return f"'VALUE_{row_id}'"

    async def get_table_stats(self) -> Dict[str, Any]:
        """Get Postgres table statistics."""
        try:
            full_name = self.get_full_table_name()

            # Get row count
            count_sql = f"SELECT COUNT(*) FROM {full_name}"
            row_count = await self.pool.fetch_val(count_sql)

            # Get table size
            size_sql = f"SELECT pg_total_relation_size('{full_name}')"
            try:
                size_bytes = await self.pool.fetch_val(size_sql)
            except Exception:
                size_bytes = None

            stats = {
                "row_count": row_count,
            }

            if size_bytes:
                stats["bytes"] = size_bytes
                stats["size_mb"] = round(size_bytes / (1024 * 1024), 2)

            if self.config.primary_key:
                stats["primary_key"] = ", ".join(self.config.primary_key)

            return stats

        except Exception as e:
            logger.error(f"Failed to get table stats: {e}")
            return {"error": str(e)}

    async def table_exists(self) -> bool:
        """Check if Postgres table exists."""
        try:
            check_sql = """
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = $1
            )
            """

            exists = await self.pool.fetch_val(check_sql, self.table_name.lower())
            return exists

        except Exception as e:
            logger.debug(f"Error checking table existence: {e}")
            return False

    async def validate_schema(self) -> bool:
        """Validate Postgres table schema."""
        try:
            full_name = self.get_full_table_name()

            # Get table columns
            desc_sql = """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = $1
            ORDER BY ordinal_position
            """

            result = await self.pool.fetch_all(desc_sql, self.table_name.lower())

            if not result:
                return False

            # Check that all configured columns exist
            actual_columns = {row["column_name"].lower() for row in result}

            for col_name in self.config.columns.keys():
                if col_name.lower() not in actual_columns:
                    logger.error(f"Column {col_name} not found in table")
                    return False

            logger.info(f"✅ Schema validation passed: {full_name}")
            return True

        except Exception as e:
            logger.error(f"Schema validation failed: {e}")
            return False
