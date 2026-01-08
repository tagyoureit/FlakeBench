"""
Postgres Connection Pool Manager

Manages async connection pooling for Postgres with health checks and retry logic.
"""

import logging
from typing import Optional, Any, Dict, List
from contextlib import asynccontextmanager
import asyncio

import asyncpg
from asyncpg import Pool
from asyncpg.exceptions import (
    TooManyConnectionsError,
    CannotConnectNowError,
)

from backend.config import settings

logger = logging.getLogger(__name__)


class PostgresConnectionPool:
    """
    Async connection pool for Postgres with health monitoring and retry logic.
    """

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
        min_size: int = 5,
        max_size: int = 20,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        command_timeout: float = 60.0,
    ):
        """
        Initialize Postgres connection pool.

        Args:
            host: Database host
            port: Database port
            database: Database name
            user: Username
            password: Password
            min_size: Minimum pool size
            max_size: Maximum pool size
            max_retries: Max retry attempts for transient failures
            retry_delay: Delay between retries in seconds
            command_timeout: Command timeout in seconds
        """
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.min_size = min_size
        self.max_size = max_size
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.command_timeout = command_timeout

        self._pool: Optional[Pool] = None
        self._initialized = False

        logger.info(
            f"Initialized Postgres pool: {user}@{host}:{port}/{database}, "
            f"min_size={min_size}, max_size={max_size}"
        )

    async def initialize(self):
        """Initialize the connection pool."""
        if self._initialized:
            return

        logger.info("Creating Postgres connection pool...")

        for attempt in range(self.max_retries):
            try:
                self._pool = await asyncpg.create_pool(
                    host=self.host,
                    port=self.port,
                    database=self.database,
                    user=self.user,
                    password=self.password,
                    min_size=self.min_size,
                    max_size=self.max_size,
                    command_timeout=self.command_timeout,
                )

                self._initialized = True
                logger.info(
                    f"Postgres pool created successfully "
                    f"(size: {self.min_size}-{self.max_size})"
                )
                return

            except (CannotConnectNowError, TooManyConnectionsError) as e:
                if attempt < self.max_retries - 1:
                    logger.warning(
                        f"Pool creation attempt {attempt + 1} failed, retrying: {e}"
                    )
                    await asyncio.sleep(self.retry_delay * (attempt + 1))
                else:
                    logger.error(
                        f"Failed to create pool after {self.max_retries} attempts"
                    )
                    raise
            except Exception as e:
                logger.error(f"Unexpected error creating pool: {e}")
                raise

    @asynccontextmanager
    async def get_connection(self):
        """
        Get a connection from the pool (async context manager).

        Usage:
            async with pool.get_connection() as conn:
                result = await conn.fetch("SELECT 1")

        Yields:
            Connection: Connection from pool
        """
        if not self._initialized:
            await self.initialize()

        if self._pool is None:
            raise Exception("Pool not initialized")

        async with self._pool.acquire() as conn:
            yield conn

    async def execute_query(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None,
    ) -> str:
        """
        Execute a query that doesn't return results (INSERT, UPDATE, DELETE, etc.).

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Optional query timeout

        Returns:
            Status string (e.g., "INSERT 0 1")
        """
        async with self.get_connection() as conn:
            return await conn.execute(query, *args, timeout=timeout)

    async def fetch_all(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None,
    ) -> List[asyncpg.Record]:
        """
        Fetch all rows from a query.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Optional query timeout

        Returns:
            List of records
        """
        async with self.get_connection() as conn:
            return await conn.fetch(query, *args, timeout=timeout)

    async def fetch_one(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None,
    ) -> Optional[asyncpg.Record]:
        """
        Fetch a single row from a query.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Optional query timeout

        Returns:
            Single record or None
        """
        async with self.get_connection() as conn:
            return await conn.fetchrow(query, *args, timeout=timeout)

    async def fetch_val(
        self,
        query: str,
        *args,
        timeout: Optional[float] = None,
    ) -> Any:
        """
        Fetch a single value from a query.

        Args:
            query: SQL query to execute
            *args: Query parameters
            timeout: Optional query timeout

        Returns:
            Single value
        """
        async with self.get_connection() as conn:
            return await conn.fetchval(query, *args, timeout=timeout)

    async def execute_many(
        self,
        query: str,
        args_list: List[tuple],
        timeout: Optional[float] = None,
    ):
        """
        Execute a query multiple times with different parameters.

        Args:
            query: SQL query to execute
            args_list: List of parameter tuples
            timeout: Optional query timeout
        """
        async with self.get_connection() as conn:
            await conn.executemany(query, args_list, timeout=timeout)

    async def is_healthy(self) -> bool:
        """
        Check if the connection pool is healthy.

        Returns:
            bool: True if pool is healthy
        """
        if not self._initialized or self._pool is None:
            return False

        try:
            result = await self.fetch_val("SELECT 1")
            return result == 1
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False

    async def get_pool_stats(self) -> Dict[str, Any]:
        """
        Get connection pool statistics.

        Returns:
            Dict with pool statistics
        """
        if not self._initialized or self._pool is None:
            return {
                "initialized": False,
                "size": 0,
                "free": 0,
            }

        return {
            "initialized": True,
            "min_size": self.min_size,
            "max_size": self.max_size,
            "size": self._pool.get_size(),
            "free": self._pool.get_idle_size(),
            "in_use": self._pool.get_size() - self._pool.get_idle_size(),
        }

    async def close(self):
        """Close the connection pool."""
        if self._pool is not None:
            logger.info("Closing Postgres connection pool...")
            await self._pool.close()
            self._pool = None
            self._initialized = False
            logger.info("Postgres pool closed")


# Global connection pool instances
_default_pool: Optional[PostgresConnectionPool] = None
_snowflake_postgres_pool: Optional[PostgresConnectionPool] = None
_crunchydata_pool: Optional[PostgresConnectionPool] = None


def get_default_pool() -> PostgresConnectionPool:
    """
    Get or create the default Postgres connection pool.

    Returns:
        PostgresConnectionPool: Default pool instance
    """
    global _default_pool

    if _default_pool is None:
        _default_pool = PostgresConnectionPool(
            host=settings.POSTGRES_HOST,
            port=settings.POSTGRES_PORT,
            database=settings.POSTGRES_DATABASE,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            min_size=settings.POSTGRES_POOL_MIN_SIZE,
            max_size=settings.POSTGRES_POOL_MAX_SIZE,
        )

    return _default_pool


def get_snowflake_postgres_pool() -> PostgresConnectionPool:
    """
    Get or create connection pool for Snowflake via Postgres protocol.

    Returns:
        PostgresConnectionPool: Snowflake Postgres pool
    """
    global _snowflake_postgres_pool

    if _snowflake_postgres_pool is None:
        if not settings.SNOWFLAKE_POSTGRES_HOST:
            raise ValueError("SNOWFLAKE_POSTGRES_HOST not configured")

        _snowflake_postgres_pool = PostgresConnectionPool(
            host=settings.SNOWFLAKE_POSTGRES_HOST,
            port=settings.SNOWFLAKE_POSTGRES_PORT,
            database=settings.SNOWFLAKE_POSTGRES_DATABASE,
            user=settings.SNOWFLAKE_POSTGRES_USER,
            password=settings.SNOWFLAKE_POSTGRES_PASSWORD,
            min_size=settings.POSTGRES_POOL_MIN_SIZE,
            max_size=settings.POSTGRES_POOL_MAX_SIZE,
        )

    return _snowflake_postgres_pool


def get_crunchydata_pool() -> PostgresConnectionPool:
    """
    Get or create connection pool for CrunchyData.

    Returns:
        PostgresConnectionPool: CrunchyData pool
    """
    global _crunchydata_pool

    if _crunchydata_pool is None:
        if not settings.CRUNCHYDATA_HOST:
            raise ValueError("CRUNCHYDATA_HOST not configured")

        _crunchydata_pool = PostgresConnectionPool(
            host=settings.CRUNCHYDATA_HOST,
            port=settings.CRUNCHYDATA_PORT,
            database=settings.CRUNCHYDATA_DATABASE,
            user=settings.CRUNCHYDATA_USER,
            password=settings.CRUNCHYDATA_PASSWORD,
            min_size=settings.POSTGRES_POOL_MIN_SIZE,
            max_size=settings.POSTGRES_POOL_MAX_SIZE,
        )

    return _crunchydata_pool


async def close_all_pools():
    """Close all Postgres connection pools."""
    global _default_pool, _snowflake_postgres_pool, _crunchydata_pool

    pools = [
        ("default", _default_pool),
        ("snowflake_postgres", _snowflake_postgres_pool),
        ("crunchydata", _crunchydata_pool),
    ]

    for name, pool in pools:
        if pool is not None:
            logger.info(f"Closing {name} pool...")
            await pool.close()

    _default_pool = None
    _snowflake_postgres_pool = None
    _crunchydata_pool = None
