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
        # Specific reason the last setup() call failed (None if setup succeeded or
        # has not run). Surfaced to the UI so "setup failed" is actionable.
        self.setup_error: str | None = None
        # Underlying error from the last table_exists() lookup, if the lookup
        # itself failed rather than genuinely finding nothing. Set by subclasses
        # via _record_exists_error() so setup() can distinguish "absent" from
        # "could not check".
        self._exists_error: str | None = None

    def _record_exists_error(self, exc: Exception) -> None:
        """
        Record that a table_exists() lookup failed rather than returned empty.

        Args:
            exc: Exception raised while checking for the object
        """
        self._exists_error = str(exc)
        logger.debug("Error checking object existence: %s", exc)

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
        self.setup_error = None
        self._exists_error = None
        full_name = self.get_full_table_name()

        try:
            logger.info(f"Setting up table: {self.table_name}")

            exists = await self.table_exists()
            if not exists:
                if self._exists_error:
                    # The lookup itself failed — do not claim the object is absent.
                    self.setup_error = self._classify_setup_exception(
                        RuntimeError(self._exists_error)
                    )
                else:
                    self.setup_error = (
                        f"{full_name} does not exist (or the current role cannot see "
                        "it). FlakeBench never creates tables — check the name in your "
                        "test configuration, or create the object first."
                    )
                logger.error(self.setup_error)
                return False

            logger.info("Using existing table/view: %s", full_name)

            if not await self.validate_schema():
                self.setup_error = (
                    f"{full_name} exists but its schema does not match the test "
                    "configuration (missing or mistyped columns). See the log for the "
                    "column-level detail."
                )
                logger.error(self.setup_error)
                return False

            self._stats = await self.get_table_stats()
            logger.info(f"Table setup complete: {self.table_name}, stats={self._stats}")

            return True

        except Exception as e:
            self.setup_error = self._classify_setup_exception(e)
            logger.error(f"Error setting up table {self.table_name}: {e}")
            return False

    def _classify_setup_exception(self, exc: Exception) -> str:
        """
        Turn a raw driver exception into an actionable setup error message.

        Snowflake collapses "missing object" and "no privilege" into a single
        "does not exist or not authorized" error, so both are reported together.

        Args:
            exc: Exception raised during setup

        Returns:
            str: Human-readable failure reason
        """
        full_name = self.get_full_table_name()
        text = str(exc).lower()

        if "not authorized" in text or "insufficient privileges" in text:
            return (
                f"{full_name} does not exist or the current role is not authorized "
                f"to access it. Verify the name and grants. ({exc})"
            )
        if "does not exist" in text or "invalid identifier" in text:
            return f"{full_name} could not be resolved: {exc}"
        if "suspended" in text or "no active warehouse" in text:
            return (
                f"No usable warehouse while setting up {full_name}: {exc}"
            )
        return f"Could not set up {full_name}: {exc}"

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
