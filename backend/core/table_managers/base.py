"""
Base Table Manager

Abstract interface for table management across different table types.
"""

from abc import ABC, abstractmethod
from typing import Any
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
        # Tracks whether the target is a TABLE or VIEW (set during schema validation).
        # "TABLE" / "VIEW" / None
        self.object_type: str | None = None
        self._stats: dict[str, Any] = {}

    @abstractmethod
    async def get_table_stats(self) -> dict[str, Any]:
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
        Complete table setup.

        Returns:
            bool: True if successful
        """
        try:
            logger.info(f"Setting up table: {self.table_name}")

            exists = await self.table_exists()
            if not exists:
                logger.error(
                    "Table creation is disabled. Missing table/view: %s",
                    self.get_full_table_name(),
                )
                return False

            logger.info("Using existing table/view: %s", self.get_full_table_name())

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
        Teardown is a no-op.

        Table creation is disabled, so we never drop/modify customer objects.

        Returns:
            bool: True if successful
        """
        return True

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

    @property
    def stats(self) -> dict[str, Any]:
        """Get current table statistics."""
        return self._stats
