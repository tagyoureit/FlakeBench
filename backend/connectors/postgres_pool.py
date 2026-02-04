"""
Postgres Connection Pool Manager

Manages async connection pooling for Postgres with health checks and retry logic.
"""

import logging
import time
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
        pool_name: str = "default",
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
            pool_name: Descriptive name for logging (e.g., "catalog", "benchmark")
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
        self.pool_name = pool_name

        self._pool: Optional[Pool] = None
        self._initialized = False

        logger.info(
            f"[{pool_name}] Postgres pool configured: {user}@{host}:{port}/{database}, "
            f"size={min_size}-{max_size}"
        )

    async def initialize(self):
        """Initialize the connection pool."""
        if self._initialized:
            return

        logger.info(f"[{self.pool_name}] Creating Postgres connection pool...")

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
                    f"[{self.pool_name}] Postgres pool ready "
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

    @staticmethod
    def _convert_placeholders(query: str) -> str:
        """
        Convert `?` placeholders to `$1, $2, ...` for asyncpg.

        Templates use Snowflake-style `?` placeholders; asyncpg requires numbered `$N`.
        """
        result = []
        idx = 0
        i = 0
        in_string = False
        string_char = None

        while i < len(query):
            ch = query[i]

            # Track string literals to avoid converting ? inside them
            if ch in ("'", '"') and (i == 0 or query[i - 1] != "\\"):
                if not in_string:
                    in_string = True
                    string_char = ch
                elif ch == string_char:
                    in_string = False
                    string_char = None

            if ch == "?" and not in_string:
                idx += 1
                result.append(f"${idx}")
            else:
                result.append(ch)
            i += 1

        return "".join(result)

    async def execute_query_with_info(
        self,
        query: str,
        params: Optional[List[Any]] = None,
        *,
        fetch: bool = True,
        timeout: Optional[float] = None,
    ) -> tuple[List[tuple], Dict[str, Any]]:
        """
        Execute a query and return results + execution info.

        Compatible with SnowflakeConnectionPool.execute_query_with_info for
        unified CUSTOM workload execution.

        Args:
            query: SQL query (may use `?` placeholders, will be converted)
            params: Query parameters as a list
            fetch: If True, fetch and return results
            timeout: Optional query timeout

        Returns:
            (results, info) where info includes:
              - query_id: None (Postgres doesn't have Snowflake-style query IDs)
              - rowcount: Number of rows affected (for DML) or returned (for SELECT)
        """
        # Convert ? placeholders to $1, $2, ... for asyncpg
        converted_query = self._convert_placeholders(query)

        async with self.get_connection() as conn:
            # Capture server-side execution time for App Overhead metrics
            start_time = time.perf_counter()

            if fetch:
                # SELECT-style query
                if params:
                    rows = await conn.fetch(converted_query, *params, timeout=timeout)
                else:
                    rows = await conn.fetch(converted_query, timeout=timeout)

                # Convert asyncpg.Record to tuples for consistency with Snowflake
                results = [tuple(row.values()) for row in rows]
                rowcount = len(results)
            else:
                # DML query (INSERT, UPDATE, DELETE)
                if params:
                    status = await conn.execute(
                        converted_query, *params, timeout=timeout
                    )
                else:
                    status = await conn.execute(converted_query, timeout=timeout)

                results = []
                # Parse rowcount from status string (e.g., "INSERT 0 1", "UPDATE 5")
                rowcount = None
                if status:
                    parts = str(status).split()
                    if len(parts) >= 2:
                        try:
                            # Last number is typically the row count
                            rowcount = int(parts[-1])
                        except ValueError:
                            pass

            # Calculate elapsed time in milliseconds
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0

            return results, {
                "query_id": None,  # Postgres doesn't have Snowflake-style query IDs
                "rowcount": rowcount,
                "total_elapsed_time_ms": elapsed_ms,  # Server-side timing for overhead calc
            }

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


# Global connection pool instances (legacy - for backward compatibility)
_default_pool: Optional[PostgresConnectionPool] = None
_snowflake_postgres_pool: Optional[PostgresConnectionPool] = None

# Dynamic pool cache: keyed by (pool_type, database)
_dynamic_pools: Dict[tuple[str, str], PostgresConnectionPool] = {}


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


def get_postgres_connection_params(pool_type: str = "default") -> dict[str, Any]:
    """
    Get connection parameters for Postgres (without database).

    Args:
        pool_type: "default" for standard Postgres, "snowflake_postgres" for Snowflake Postgres

    Returns:
        Dict with host, port, user, password (no database)
    """
    if pool_type == "snowflake_postgres":
        return {
            "host": settings.SNOWFLAKE_POSTGRES_HOST,
            "port": settings.SNOWFLAKE_POSTGRES_PORT,
            "user": settings.SNOWFLAKE_POSTGRES_USER,
            "password": settings.SNOWFLAKE_POSTGRES_PASSWORD,
        }
    return {
        "host": settings.POSTGRES_HOST,
        "port": settings.POSTGRES_PORT,
        "user": settings.POSTGRES_USER,
        "password": settings.POSTGRES_PASSWORD,
    }


def get_pool_for_database(
    database: str,
    pool_type: str = "default",
) -> PostgresConnectionPool:
    """
    Get or create a connection pool for a specific database.

    Pools are cached by (pool_type, database) key and created lazily.
    This enables dynamic database selection from templates without requiring
    POSTGRES_DATABASE to match.

    NOTE: This creates small pools (1-2 connections) intended for catalog/API
    operations like schema introspection. Benchmark workers should create their
    own properly-sized pools directly.

    Args:
        database: Database name to connect to
        pool_type: "default" for standard Postgres, "snowflake_postgres" for Snowflake Postgres

    Returns:
        PostgresConnectionPool: Pool for the specified database
    """
    global _dynamic_pools

    cache_key = (pool_type, database)
    if cache_key in _dynamic_pools:
        return _dynamic_pools[cache_key]

    params = get_postgres_connection_params(pool_type)
    pool = PostgresConnectionPool(
        host=params["host"],
        port=params["port"],
        database=database,
        user=params["user"],
        password=params["password"],
        min_size=1,  # Catalog pools only need 1-2 connections
        max_size=2,
        pool_name="catalog",
    )

    _dynamic_pools[cache_key] = pool
    return pool


async def fetch_from_database(
    database: str,
    query: str,
    *args,
    pool_type: str = "default",
    timeout: float = 30.0,
) -> List[asyncpg.Record]:
    """
    Execute a query against a specific database using an ad-hoc connection.

    This is used for catalog operations (listing databases, schemas, tables)
    where we need to connect to a user-selected database rather than the
    pre-configured pool database.

    Args:
        database: Database name to connect to
        query: SQL query to execute
        *args: Query parameters
        pool_type: "default" for standard Postgres, "snowflake_postgres" for Snowflake Postgres
        timeout: Query timeout in seconds

    Returns:
        List of records
    """
    params = get_postgres_connection_params(pool_type)
    conn = None
    try:
        conn = await asyncpg.connect(
            host=params["host"],
            port=params["port"],
            database=database,
            user=params["user"],
            password=params["password"],
            timeout=timeout,
        )
        return await conn.fetch(query, *args, timeout=timeout)
    finally:
        if conn:
            await conn.close()


async def close_all_pools():
    """Close all Postgres connection pools (legacy and dynamic)."""
    global _default_pool, _snowflake_postgres_pool, _dynamic_pools

    # Close legacy pools
    legacy_pools = [
        ("default", _default_pool),
        ("snowflake_postgres", _snowflake_postgres_pool),
    ]

    for name, pool in legacy_pools:
        if pool is not None:
            logger.info(f"Closing {name} pool...")
            await pool.close()

    _default_pool = None
    _snowflake_postgres_pool = None

    # Close dynamic pools
    for (pool_type, database), pool in list(_dynamic_pools.items()):
        logger.info(f"Closing dynamic pool {pool_type}/{database}...")
        await pool.close()

    _dynamic_pools = {}
