"""
Base Table Manager

Abstract interface for table management across different table types.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List
import logging

from backend.models.test_config import TableConfig

logger = logging.getLogger(__name__)


class TableManager(ABC):
    """
    Abstract base class for managing tables in different database systems.

    Each table type (Standard, Hybrid, Interactive, Postgres) implements
    this interface to provide consistent table lifecycle management.
    """

    def __init__(self, config: TableConfig):
        """
        Initialize table manager with configuration.

        Args:
            config: Table configuration
        """
        self.config = config
        self.table_name = config.name
        self.database = config.database
        self.schema_name = config.schema_name
        self._created = False
        self._stats: Dict[str, Any] = {}

    @abstractmethod
    async def create_table(self) -> bool:
        """
        Create the table with specified configuration.

        Returns:
            bool: True if successful
        """
        pass

    @abstractmethod
    async def drop_table(self) -> bool:
        """
        Drop the table if it exists.

        Returns:
            bool: True if successful
        """
        pass

    @abstractmethod
    async def truncate_table(self) -> bool:
        """
        Truncate the table (remove all data).

        Returns:
            bool: True if successful
        """
        pass

    @abstractmethod
    async def populate_data(self, row_count: int) -> bool:
        """
        Populate table with initial test data.

        Args:
            row_count: Number of rows to insert

        Returns:
            bool: True if successful
        """
        pass

    @abstractmethod
    async def get_table_stats(self) -> Dict[str, Any]:
        """
        Get table statistics (row count, size, etc.).

        Returns:
            Dict with table statistics
        """
        pass

    @abstractmethod
    async def table_exists(self) -> bool:
        """
        Check if table exists.

        Returns:
            bool: True if table exists
        """
        pass

    @abstractmethod
    async def validate_schema(self) -> bool:
        """
        Validate that table schema matches configuration.

        Returns:
            bool: True if schema is valid
        """
        pass

    async def setup(self) -> bool:
        """
        Complete table setup (create + populate).

        Returns:
            bool: True if successful
        """
        try:
            logger.info(f"Setting up table: {self.table_name}")

            # Create if missing (non-destructive default).
            # If the table already exists, we validate and reuse it.
            exists = await self.table_exists()
            if not exists:
                if not await self.create_table():
                    logger.error(f"Failed to create table: {self.table_name}")
                    return False
                self._created = True
            else:
                logger.info(
                    f"Table {self.table_name} already exists, reusing (no drop)."
                )
                self._created = False

            # Populate data if needed
            if not exists and self.config.initial_row_count > 0:
                logger.info(
                    f"Populating {self.table_name} with "
                    f"{self.config.initial_row_count} rows"
                )
                if not await self.populate_data(self.config.initial_row_count):
                    logger.error(f"Failed to populate table: {self.table_name}")
                    return False

            # Validate
            if not await self.validate_schema():
                logger.error(f"Schema validation failed: {self.table_name}")
                return False

            # Get stats
            self._stats = await self.get_table_stats()
            logger.info(f"Table setup complete: {self.table_name}, stats={self._stats}")

            return True

        except Exception as e:
            logger.error(f"Error setting up table {self.table_name}: {e}")
            return False

    async def teardown(self) -> bool:
        """
        Clean up table (drop).

        Returns:
            bool: True if successful
        """
        try:
            if self._created:
                logger.info(f"Tearing down table: {self.table_name}")
                await self.drop_table()
                self._created = False
            return True
        except Exception as e:
            logger.error(f"Error tearing down table {self.table_name}: {e}")
            return False

    def get_full_table_name(self) -> str:
        """
        Get fully qualified table name.

        Returns:
            str: database.schema.table or just table
        """
        parts = []
        if self.database:
            parts.append(self.database)
        if self.schema_name:
            parts.append(self.schema_name)
        parts.append(self.table_name)
        return ".".join(parts)

    def get_column_definitions(self) -> List[str]:
        """
        Get column definitions as SQL strings.

        Returns:
            List of "column_name type" strings
        """
        return [
            f"{col_name} {col_type}"
            for col_name, col_type in self.config.columns.items()
        ]

    @property
    def is_created(self) -> bool:
        """Check if table has been created."""
        return self._created

    @property
    def stats(self) -> Dict[str, Any]:
        """Get current table statistics."""
        return self._stats
