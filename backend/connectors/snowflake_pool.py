"""
Snowflake Connection Pool Manager

Manages connection pooling for Snowflake with health checks, retry logic,
and support for multiple warehouse connections.
"""

import logging
from typing import Dict, Optional, Any, List, cast
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime
from concurrent.futures import Executor, ThreadPoolExecutor

import snowflake.connector
from snowflake.connector import SnowflakeConnection
from snowflake.connector.errors import (
    OperationalError,
)

from backend.config import settings

logger = logging.getLogger(__name__)


class SnowflakeConnectionPool:
    """
    Connection pool for Snowflake with health monitoring and retry logic.
    """

    def __init__(
        self,
        account: str,
        user: str,
        password: Optional[str] = None,
        warehouse: Optional[str] = None,
        database: Optional[str] = None,
        schema: Optional[str] = None,
        role: Optional[str] = None,
        pool_size: int = 5,
        max_overflow: int = 10,
        timeout: int = 30,
        recycle: int = 3600,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        *,
        executor: Executor | None = None,
        owns_executor: bool = False,
        max_parallel_creates: int = 8,
        connect_login_timeout: int | None = None,
        connect_network_timeout: int | None = None,
        connect_socket_timeout: int | None = None,
        session_parameters: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize Snowflake connection pool.

        Args:
            account: Snowflake account identifier
            user: Username
            password: Password (or use private key)
            warehouse: Default warehouse
            database: Default database
            schema: Default schema
            role: Default role
            pool_size: Base pool size
            max_overflow: Max additional connections
            timeout: Connection timeout in seconds
            recycle: Recycle connections after N seconds
            max_retries: Max retry attempts for transient failures
            retry_delay: Delay between retries in seconds
        """
        self.account = account
        self.user = user
        self.password = password
        self.warehouse = warehouse
        self.database = database
        self.schema = schema
        self.role = role

        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.timeout = timeout
        self.recycle = recycle
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Connection pool (list of available connections)
        self._pool: List[SnowflakeConnection] = []
        self._in_use: Dict[int, SnowflakeConnection] = {}
        self._connection_times: Dict[int, datetime] = {}
        # Number of connection creations currently in flight. We must count these
        # towards max connections to avoid a connection "stampede" under high
        # concurrency where many tasks simultaneously decide to create a new
        # connection before any have been checked out.
        self._pending_creates: int = 0
        # Tracks the last time we ran a lightweight health check against a connection.
        # This avoids spamming `SELECT 1` on every checkout/return, which can dominate
        # benchmarks and pollute Snowsight query history.
        self._last_health_check: Dict[int, datetime] = {}
        self._lock = asyncio.Lock()
        self._initialized = False
        self._executor: Executor | None = executor
        self._owns_executor: bool = bool(owns_executor)
        # Limit how many blocking connect() calls we issue concurrently.
        self._max_parallel_creates: int = max(1, int(max_parallel_creates))
        self._create_semaphore = asyncio.Semaphore(self._max_parallel_creates)
        self._connect_login_timeout = (
            int(connect_login_timeout)
            if connect_login_timeout is not None
            else settings.SNOWFLAKE_CONNECT_LOGIN_TIMEOUT
        )
        self._connect_network_timeout = (
            int(connect_network_timeout)
            if connect_network_timeout is not None
            else settings.SNOWFLAKE_CONNECT_NETWORK_TIMEOUT
        )
        self._connect_socket_timeout = (
            int(connect_socket_timeout)
            if connect_socket_timeout is not None
            else settings.SNOWFLAKE_CONNECT_SOCKET_TIMEOUT
        )
        self._session_parameters: Dict[str, Any] = dict(session_parameters or {})
        # Minimum interval between health checks per connection.
        # (We still recycle connections via `self.recycle`.)
        self._health_check_interval_seconds: float = 30.0

        logger.info(
            f"Initialized Snowflake pool: {user}@{account}, "
            f"pool_size={pool_size}, max_overflow={max_overflow}"
        )

    def _run_in_executor(self, func, *args):
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(self._executor, func, *args)

    def max_connections(self) -> int:
        return int(self.pool_size) + int(self.max_overflow)

    async def initialize(self):
        """Initialize the connection pool by creating base connections."""
        if self._initialized:
            return

        async with self._lock:
            if self._initialized:
                return

            logger.info("Creating initial Snowflake connections...")

            # Create initial pool connections with bounded parallelism.
            connections: list[SnowflakeConnection | BaseException] = []
            remaining = int(self.pool_size)
            while remaining > 0:
                batch_n = min(remaining, self._max_parallel_creates)
                tasks = [self._create_connection() for _ in range(batch_n)]
                connections.extend(await asyncio.gather(*tasks, return_exceptions=True))
                remaining -= batch_n

            for conn in connections:
                if isinstance(conn, BaseException):
                    logger.error(f"Failed to create initial connection: {conn}")
                else:
                    self._pool.append(conn)
                    self._connection_times[id(conn)] = datetime.now()
                    self._last_health_check[id(conn)] = datetime.now()

            self._initialized = True
            logger.info(
                f"Connection pool initialized with {len(self._pool)} connections"
            )

    def _get_connection_params(self) -> Dict[str, Any]:
        """Get connection parameters for snowflake.connector."""
        session_params: Dict[str, Any] = {"QUERY_TAG": "unistore_benchmark"}
        session_params.update(self._session_parameters)
        params = {
            "account": self.account,
            "user": self.user,
            # We use `?` placeholders throughout the codebase. Snowflake's Python connector
            # defaults to `pyformat`, which can raise `TypeError: not all arguments converted
            # during string formatting` when passing params with `?` placeholders.
            # Setting qmark ensures consistent server-side binding for `?`.
            "paramstyle": "qmark",
            # Fail fast on degraded connectivity so reload/shutdown doesn't hang waiting for
            # threadpool connect() calls to finish.
            "login_timeout": self._connect_login_timeout,
            "network_timeout": self._connect_network_timeout,
            "socket_timeout": self._connect_socket_timeout,
            "session_parameters": {
                **session_params,
            },
        }

        if self.password:
            params["password"] = self.password
        # TODO: Add private key authentication support

        if self.warehouse:
            params["warehouse"] = self.warehouse
        if self.database:
            params["database"] = self.database
        if self.schema:
            params["schema"] = self.schema
        if self.role:
            params["role"] = self.role

        return params

    async def _create_connection(self) -> SnowflakeConnection:
        """
        Create a new Snowflake connection with retry logic.

        Returns:
            SnowflakeConnection: New connection

        Raises:
            SnowflakeError: If connection fails after retries
        """
        params = self._get_connection_params()

        async with self._create_semaphore:
            for attempt in range(self.max_retries):
                try:
                    conn = cast(
                        SnowflakeConnection,
                        await self._run_in_executor(
                            lambda: snowflake.connector.connect(**params)
                        ),
                    )

                    logger.debug(f"Created new Snowflake connection: {id(conn)}")
                    return conn

                except OperationalError as e:
                    if attempt < self.max_retries - 1:
                        logger.warning(
                            f"Connection attempt {attempt + 1} failed, retrying: {e}"
                        )
                        await asyncio.sleep(self.retry_delay * (attempt + 1))
                    else:
                        logger.error(
                            f"Failed to create connection after {self.max_retries} attempts"
                        )
                        raise
                except Exception as e:
                    logger.error(f"Unexpected error creating connection: {e}")
                    raise

        raise RuntimeError("Failed to create Snowflake connection")

    async def _is_connection_valid(self, conn: SnowflakeConnection) -> bool:
        """
        Check if a connection is still valid.

        Args:
            conn: Connection to check

        Returns:
            bool: True if connection is valid
        """
        try:
            # Check if connection is closed
            if conn.is_closed():
                return False

            # Check connection age for recycling
            conn_id = id(conn)
            if conn_id in self._connection_times:
                age = (datetime.now() - self._connection_times[conn_id]).total_seconds()
                if age > self.recycle:
                    logger.debug(f"Connection {conn_id} expired (age: {age}s)")
                    return False

            # Run a lightweight query occasionally to verify the connection is still usable.
            # This must not run on every checkout/return; doing so can serialize high
            # concurrency workloads and overwhelm query history with `SELECT 1`.
            last = self._last_health_check.get(conn_id)
            if (
                last is None
                or (datetime.now() - last).total_seconds()
                >= self._health_check_interval_seconds
            ):
                cursor = await self._run_in_executor(conn.cursor)
                try:
                    await self._run_in_executor(cursor.execute, "SELECT 1")
                finally:
                    await self._run_in_executor(cursor.close)
                self._last_health_check[conn_id] = datetime.now()

            return True

        except Exception as e:
            logger.debug(f"Connection validation failed: {e}")
            return False

    @asynccontextmanager
    async def get_connection(self):
        """
        Get a connection from the pool (async context manager).

        Usage:
            async with pool.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")

        Yields:
            SnowflakeConnection: Connection from pool
        """
        if not self._initialized:
            await self.initialize()

        conn = None

        try:
            # Acquire a connection without holding the pool lock across network I/O.
            #
            # Holding the lock while awaiting `_is_connection_valid()` (which can hit
            # Snowflake) serializes checkouts under concurrency and can make a "10
            # concurrent workers" run look like far fewer in Snowsight.
            while conn is None:
                candidate: Optional[SnowflakeConnection] = None
                need_create = False
                reserved_create = False

                async with self._lock:
                    if self._pool:
                        candidate = self._pool.pop()
                    else:
                        total_connections = (
                            len(self._pool) + len(self._in_use) + self._pending_creates
                        )
                        if total_connections < self.max_connections():
                            need_create = True
                            self._pending_creates += 1
                            reserved_create = True
                        else:
                            raise Exception(
                                f"Connection pool exhausted "
                                f"(max: {self.max_connections()})"
                            )

                if need_create:
                    try:
                        candidate = await self._create_connection()
                        now = datetime.now()
                        self._connection_times[id(candidate)] = now
                        self._last_health_check[id(candidate)] = now
                    except Exception:
                        async with self._lock:
                            self._pending_creates = max(0, self._pending_creates - 1)
                        raise

                if candidate is None:
                    continue

                if await self._is_connection_valid(candidate):
                    conn = candidate
                    break

                # Close invalid connection (best effort) and try again.
                try:
                    candidate.close()
                except Exception:
                    pass
                cid = id(candidate)
                self._connection_times.pop(cid, None)
                self._last_health_check.pop(cid, None)
                if reserved_create:
                    async with self._lock:
                        self._pending_creates = max(0, self._pending_creates - 1)

            async with self._lock:
                if reserved_create:
                    self._pending_creates = max(0, self._pending_creates - 1)
                self._in_use[id(conn)] = conn

            yield conn

        finally:
            # Return connection to pool
            if conn is not None:
                async with self._lock:
                    conn_id = id(conn)
                    if conn_id in self._in_use:
                        del self._in_use[conn_id]

                    # Always return to the pool; the next checkout will validate.
                    # (Do NOT validate here; that can double health-check traffic.)
                    self._pool.append(conn)

    async def execute_query(
        self,
        query: str,
        params: Optional[object] = None,
        warehouse: Optional[str] = None,
    ) -> List[tuple]:
        """
        Execute a query and return results.

        Args:
            query: SQL query to execute
            params: Query parameters (for binding)
            warehouse: Optional warehouse override

        Returns:
            List of result tuples
        """
        async with self.get_connection() as conn:
            # Switch warehouse if specified
            if warehouse and warehouse != self.warehouse:
                cursor = await self._run_in_executor(conn.cursor)
                await self._run_in_executor(
                    cursor.execute, f"USE WAREHOUSE {warehouse}"
                )
                await self._run_in_executor(cursor.close)

            # Execute query
            cursor = await self._run_in_executor(conn.cursor)

            try:
                if params is None:
                    await self._run_in_executor(cursor.execute, query)
                else:
                    # Snowflake connector supports both:
                    # - qmark params: Sequence[Any] for `?` placeholders
                    # - pyformat params: Mapping for `%(name)s` placeholders
                    await self._run_in_executor(cursor.execute, query, params)

                results = await self._run_in_executor(cursor.fetchall)
                return results

            finally:
                await self._run_in_executor(cursor.close)

    async def execute_query_with_info(
        self,
        query: str,
        params: Optional[object] = None,
        warehouse: Optional[str] = None,
        *,
        fetch: bool = True,
    ) -> tuple[List[tuple], dict[str, Any]]:
        """
        Execute a query and return results + execution info.

        This is primarily used for per-query logging/enrichment workflows.

        Returns:
            (results, info) where info includes:
              - query_id: Snowflake QUERY_ID (cursor.sfqid) when available
              - rowcount: cursor.rowcount (may be -1 depending on statement)
        """
        async with self.get_connection() as conn:
            if warehouse and warehouse != self.warehouse:
                cursor = await self._run_in_executor(conn.cursor)
                await self._run_in_executor(
                    cursor.execute, f"USE WAREHOUSE {warehouse}"
                )
                await self._run_in_executor(cursor.close)

            cursor = await self._run_in_executor(conn.cursor)
            try:
                if params is None:
                    await self._run_in_executor(cursor.execute, query)
                else:
                    await self._run_in_executor(cursor.execute, query, params)

                query_id = getattr(cursor, "sfqid", None)
                rowcount = getattr(cursor, "rowcount", None)
                results: List[tuple] = []
                if fetch:
                    results = await self._run_in_executor(cursor.fetchall)

                return results, {"query_id": query_id, "rowcount": rowcount}
            finally:
                await self._run_in_executor(cursor.close)

    async def get_pool_stats(self) -> Dict[str, Any]:
        """
        Get connection pool statistics.

        Returns:
            Dict with pool statistics
        """
        async with self._lock:
            return {
                "pool_size": self.pool_size,
                "max_overflow": self.max_overflow,
                "available": len(self._pool),
                "in_use": len(self._in_use),
                "total": len(self._pool) + len(self._in_use),
                "initialized": self._initialized,
            }

    async def close_all(self):
        """Close all connections in the pool."""
        async with self._lock:
            logger.info("Closing all Snowflake connections...")

            # Close connections in pool
            for conn in self._pool:
                try:
                    conn.close()
                except Exception:
                    pass

            # Close in-use connections
            for conn in self._in_use.values():
                try:
                    conn.close()
                except Exception:
                    pass

            self._pool.clear()
            self._in_use.clear()
            self._connection_times.clear()
            self._last_health_check.clear()
            self._initialized = False

            logger.info("All connections closed")

        # Shut down any owned executor outside the lock (best effort).
        if self._owns_executor and self._executor is not None:
            try:
                self._executor.shutdown(wait=False)  # type: ignore[attr-defined]
            except Exception:
                pass
            self._executor = None
            self._owns_executor = False


# Global connection pool instance
_default_pool: Optional[SnowflakeConnectionPool] = None
_default_executor: Executor | None = None


def get_default_pool() -> SnowflakeConnectionPool:
    """
    Get or create the default Snowflake connection pool.

    Returns:
        SnowflakeConnectionPool: Default pool instance
    """
    global _default_pool

    if _default_pool is None:
        global _default_executor
        if _default_executor is None:
            _default_executor = ThreadPoolExecutor(
                max_workers=max(
                    1, int(settings.SNOWFLAKE_RESULTS_EXECUTOR_MAX_WORKERS)
                ),
                thread_name_prefix="sf-results",
            )
        _default_pool = SnowflakeConnectionPool(
            account=settings.SNOWFLAKE_ACCOUNT,
            user=settings.SNOWFLAKE_USER,
            password=settings.SNOWFLAKE_PASSWORD,
            warehouse=settings.SNOWFLAKE_WAREHOUSE,
            database=settings.SNOWFLAKE_DATABASE,
            schema=settings.SNOWFLAKE_SCHEMA,
            role=settings.SNOWFLAKE_ROLE,
            pool_size=settings.SNOWFLAKE_POOL_SIZE,
            max_overflow=settings.SNOWFLAKE_MAX_OVERFLOW,
            timeout=settings.SNOWFLAKE_POOL_TIMEOUT,
            recycle=settings.SNOWFLAKE_POOL_RECYCLE,
            executor=_default_executor,
            owns_executor=False,
            max_parallel_creates=settings.SNOWFLAKE_POOL_MAX_PARALLEL_CREATES,
        )

    return _default_pool


async def close_default_pool():
    """Close the default connection pool."""
    global _default_pool
    if _default_pool is not None:
        await _default_pool.close_all()
        _default_pool = None
    global _default_executor
    if _default_executor is not None:
        try:
            _default_executor.shutdown(wait=False)  # type: ignore[attr-defined]
        except Exception:
            pass
        _default_executor = None
