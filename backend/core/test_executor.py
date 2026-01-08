"""
Test Executor

Orchestrates performance test execution with concurrent workload generation.
"""

import asyncio
import json
import logging
import re
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any, Callable, List, Optional, cast
from uuid import uuid4
import time
from backend.models import (
    TestScenario,
    TestResult,
    TestStatus,
    WorkloadType,
    Metrics,
)
from backend.config import settings
from backend.core.table_managers import create_table_manager, TableManager
from backend.core.table_profiler import TableProfile, profile_snowflake_table

logger = logging.getLogger(__name__)


@dataclass
class _TableRuntimeState:
    profile: Optional[TableProfile] = None
    next_insert_id: Optional[int] = None
    insert_id_seq: Optional[Iterator[int]] = None


@dataclass
class _QueryExecutionRecord:
    execution_id: str
    test_id: str
    query_id: str
    query_text: str
    start_time: datetime
    end_time: datetime
    duration_ms: float
    success: bool
    error: Optional[str]
    warehouse: Optional[str]
    rows_affected: Optional[int]
    bytes_scanned: Optional[int]
    connection_id: Optional[int]
    custom_metadata: dict[str, Any]
    query_kind: str
    worker_id: int
    warmup: bool
    app_elapsed_ms: float


class TestExecutor:
    """
    Orchestrates performance test execution.

    Manages:
    - Test lifecycle (setup, execute, teardown)
    - Concurrent worker pool
    - Workload generation
    - Real-time metrics collection
    """

    def __init__(self, scenario: TestScenario):
        """
        Initialize test executor.

        Args:
            scenario: Test scenario configuration
        """
        self.scenario = scenario
        self.test_id = uuid4()

        # State
        self.status = TestStatus.PENDING
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self._measurement_start_time: Optional[datetime] = None

        # Table managers
        self.table_managers: List[TableManager] = []
        self._table_state: dict[str, _TableRuntimeState] = {}

        # Workers
        self.workers: List[asyncio.Task] = []
        self._stop_event = asyncio.Event()

        # Metrics
        self.metrics = Metrics()
        self._metrics_lock = asyncio.Lock()
        self._latencies_ms: deque[float] = deque(maxlen=10000)
        self._last_snapshot_time: Optional[datetime] = None
        self._last_snapshot_ops: int = 0

        # Query type counters (for debugging)
        self._point_lookup_count: int = 0
        self._range_scan_count: int = 0
        self._insert_count: int = 0
        self._update_count: int = 0

        # CUSTOM workload execution state (authoritative template mix).
        # - schedule: smooth weighted round-robin sequence of query kinds
        # - per-worker index: ensures stable offsets across workers without randomness
        self._custom_schedule: list[str] = []
        self._custom_sql_by_kind: dict[str, str] = {}
        self._custom_weights: dict[str, int] = {}
        self._custom_pos_by_worker: dict[int, int] = {}

        # Per-operation capture for QUERY_EXECUTIONS (optionally persisted).
        self._query_execution_records: deque[_QueryExecutionRecord] = deque(
            maxlen=200_000
        )

        # Latency samples by kind (non-warmup only, for summary columns).
        self._lat_by_kind_ms: dict[str, list[float]] = {
            "POINT_LOOKUP": [],
            "RANGE_SCAN": [],
            "INSERT": [],
            "UPDATE": [],
        }
        self._lat_read_ms: list[float] = []
        self._lat_write_ms: list[float] = []

        # Results
        self.test_result: Optional[TestResult] = None

        # Callbacks
        self.metrics_callback: Optional[Callable[[Metrics], None]] = None

        logger.info(f"TestExecutor initialized: {scenario.name}")
        if self.scenario.workload_type == WorkloadType.CUSTOM:
            self._init_custom_workload()

    @staticmethod
    def _build_smooth_weighted_schedule(weights: dict[str, int]) -> list[str]:
        """
        Build a smooth weighted round-robin schedule.

        This yields a stable interleaving that converges to the exact target weights
        over one full cycle (e.g., 100 slots for percentage weights).
        """
        total = int(sum(weights.values()))
        if total <= 0:
            return []
        current: dict[str, int] = {k: 0 for k in weights}
        schedule: list[str] = []
        for _ in range(total):
            for k, w in weights.items():
                current[k] += int(w)
            # Use __getitem__ (not .get) so the key function is guaranteed to return int.
            k_max = max(current, key=current.__getitem__)
            schedule.append(k_max)
            current[k_max] -= total
        return schedule

    def _init_custom_workload(self) -> None:
        """Parse scenario.custom_queries into an execution schedule and SQL map."""
        raw = self.scenario.custom_queries or []
        weights: dict[str, int] = {}
        sql_by_kind: dict[str, str] = {}

        allowed = {"POINT_LOOKUP", "RANGE_SCAN", "INSERT", "UPDATE"}
        for entry in raw:
            if not isinstance(entry, dict):
                raise ValueError("custom_queries entries must be JSON objects")
            kind_raw = entry.get("query_kind") or entry.get("kind") or ""
            kind = str(kind_raw).strip().upper()
            if kind not in allowed:
                raise ValueError(f"Unsupported custom query_kind: {kind_raw!r}")

            pct_raw = entry.get("weight_pct", entry.get("pct", entry.get("weight", 0)))
            try:
                pct = int(pct_raw)
            except Exception as e:
                raise ValueError(f"Invalid weight_pct for {kind}: {pct_raw!r}") from e
            if pct <= 0:
                continue

            sql_raw = entry.get("sql", entry.get("query", entry.get("query_text", "")))
            sql = str(sql_raw or "").strip()
            if not sql:
                raise ValueError(f"Missing SQL for custom query kind {kind}")

            weights[kind] = pct
            sql_by_kind[kind] = sql

        total = sum(weights.values())
        if total != 100:
            raise ValueError(
                f"Custom workload weights must sum to 100 (currently {total})."
            )

        self._custom_weights = dict(weights)
        self._custom_sql_by_kind = dict(sql_by_kind)
        self._custom_schedule = self._build_smooth_weighted_schedule(weights)
        self._custom_pos_by_worker.clear()

    def _custom_next_kind(self, worker_id: int) -> str:
        if not self._custom_schedule:
            self._init_custom_workload()
        if not self._custom_schedule:
            raise ValueError("CUSTOM workload has no scheduled queries")
        n = len(self._custom_schedule)
        pos = self._custom_pos_by_worker.get(worker_id, worker_id % n)
        kind = self._custom_schedule[pos]
        self._custom_pos_by_worker[worker_id] = (pos + 1) % n
        return kind

    async def setup(self) -> bool:
        """
        Setup test environment.

        - Create table managers
        - Setup tables
        - Initialize connection pools

        Returns:
            bool: True if setup successful
        """
        try:
            logger.info(f"Setting up test: {self.scenario.name}")

            # Create table managers
            for table_config in self.scenario.table_configs:
                manager = create_table_manager(table_config)
                self.table_managers.append(manager)

            # Optional: per-test Snowflake pool override (used for template-selected warehouses).
            pool_override = getattr(self, "_snowflake_pool_override", None)
            if pool_override is not None:
                for manager in self.table_managers:
                    if hasattr(manager, "pool") and hasattr(
                        manager.pool, "execute_query"
                    ):
                        cast(Any, manager).pool = pool_override

            # Setup tables in parallel
            setup_tasks = [manager.setup() for manager in self.table_managers]
            results = await asyncio.gather(*setup_tasks, return_exceptions=True)

            # Check for failures
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(
                        f"Failed to setup table {self.table_managers[i].table_name}: {result}"
                    )
                    return False
                elif not result:
                    logger.error(
                        f"Failed to setup table {self.table_managers[i].table_name}"
                    )
                    return False

            logger.info(
                f"✅ Test setup complete: {len(self.table_managers)} tables ready"
            )

            # Snowflake-first: lightweight profiling for adaptive reads/range scans
            await self._profile_tables()
            return True

        except Exception as e:
            logger.error(f"Error during test setup: {e}")
            return False

    async def _profile_tables(self) -> None:
        """
        Profile tables so query generation can adapt to unknown schemas.

        Snowflake-first: if the table manager's pool supports `execute_query`,
        we treat it as Snowflake and run DESCRIBE + MIN/MAX aggregates.
        """
        for manager in self.table_managers:
            full_name = manager.get_full_table_name()
            self._table_state.setdefault(full_name, _TableRuntimeState())

            pool = getattr(manager, "pool", None)
            if pool is None or not hasattr(pool, "execute_query"):
                continue

            try:
                profile = await profile_snowflake_table(pool, full_name)
                state = self._table_state[full_name]
                state.profile = profile
                if profile.id_max is not None:
                    state.next_insert_id = profile.id_max + 1
                    state.insert_id_seq = count(int(profile.id_max) + 1)
                elif state.insert_id_seq is None:
                    state.insert_id_seq = count(1)

                # Warn if profiling succeeded but critical fields are missing
                if profile.id_column and (
                    profile.id_min is None or profile.id_max is None
                ):
                    logger.warning(
                        f"Table {full_name} has ID column '{profile.id_column}' but min/max are not set. "
                        f"Point lookup queries will fall back to range scans."
                    )
            except Exception as e:
                logger.warning(
                    "Table profiling failed for %s: %s - Point lookups will not be available",
                    full_name,
                    e,
                )

        # Load persisted value pools (if present) after table managers and profiling.
        await self._load_value_pools()

    async def _load_value_pools(self) -> None:
        """
        Load template-associated value pools (if any) into memory.

        Pools are persisted during template preparation and must never be generated
        at runtime (no AI calls in the hot path).
        """
        tpl_cfg = getattr(self, "_template_config", None)
        tpl_id = getattr(self, "_template_id", None)
        if not isinstance(tpl_cfg, dict) or not tpl_id:
            self._value_pools = {}
            return

        ai_cfg = tpl_cfg.get("ai_workload")
        if not isinstance(ai_cfg, dict):
            self._value_pools = {}
            return

        pool_id = ai_cfg.get("pool_id")
        if not pool_id:
            self._value_pools = {}
            return

        try:
            from backend.connectors import snowflake_pool

            pool = snowflake_pool.get_default_pool()
            rows = await pool.execute_query(
                f"""
                SELECT POOL_KIND, COLUMN_NAME, VALUE
                FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.TEMPLATE_VALUE_POOLS
                WHERE TEMPLATE_ID = ?
                  AND POOL_ID = ?
                ORDER BY POOL_KIND, COLUMN_NAME, SEQ
                """,
                params=[str(tpl_id), str(pool_id)],
            )

            def _normalize_variant(v: Any) -> Any:
                # Snowflake VARIANT values may come back as:
                # - Python native (int/float/dict/list/datetime/date)
                # - JSON-ish strings (e.g. '"1996-06-03"' including quotes)
                # Normalize to something safe to bind as a query parameter.
                if isinstance(v, str):
                    s = v.strip()
                    if not s:
                        return v
                    try_json = (
                        s[0] in '{["'
                        or s in {"null", "true", "false"}
                        or s[0].isdigit()
                        or s[0] == "-"
                    )
                    if try_json:
                        try:
                            return json.loads(s)
                        except Exception:
                            return v
                if isinstance(v, dict):
                    out: dict[str, Any] = {}
                    for k2, v2 in v.items():
                        out[str(k2).strip().upper()] = _normalize_variant(v2)
                    return out
                if isinstance(v, list):
                    return [_normalize_variant(x) for x in v]
                return v

            pools: dict[str, dict[str | None, list[Any]]] = {}
            for kind, col_name, value in rows:
                k = str(kind or "").upper()
                col = str(col_name).upper() if col_name is not None else None
                pools.setdefault(k, {}).setdefault(col, []).append(
                    _normalize_variant(value)
                )

            self._value_pools = pools
            self._ai_workload = ai_cfg
        except Exception as e:
            logger.debug("Failed to load TEMPLATE_VALUE_POOLS: %s", e)
            self._value_pools = {}

    def _select_list_sql(self) -> str:
        """
        Projection list for SELECT queries.

        If the template includes ai_workload.projection_columns, we use it to
        avoid SELECT * on wide customer tables.
        """
        tpl_cfg = getattr(self, "_template_config", None)
        if not isinstance(tpl_cfg, dict):
            return "*"
        ai_cfg = tpl_cfg.get("ai_workload")
        if not isinstance(ai_cfg, dict):
            return "*"
        cols = ai_cfg.get("projection_columns")
        if not isinstance(cols, list):
            return "*"

        out: list[str] = []
        for c in cols:
            s = str(c or "").strip().upper()
            if not s:
                continue
            out.append(f'"{s}"')
        # De-dupe and cap to keep SQL reasonable.
        seen: set[str] = set()
        deduped: list[str] = []
        for c in out:
            if c in seen:
                continue
            seen.add(c)
            deduped.append(c)
        if not deduped:
            return "*"
        return ", ".join(deduped[:50])

    def _pool_values(self, kind: str, column: Optional[str] = None) -> list[Any]:
        pools = getattr(self, "_value_pools", {}) or {}
        kind_u = (kind or "").upper()
        col_u = column.upper() if column else None
        return list(pools.get(kind_u, {}).get(col_u, []))

    def _next_from_pool(
        self, worker_id: int, kind: str, column: Optional[str] = None
    ) -> Any:
        values = self._pool_values(kind, column)
        if not values:
            return None
        # Each worker has its own cyclic walk.
        #
        # IMPORTANT: use a stride based on requested concurrency so that workers
        # traverse largely disjoint subsets early in a run. The previous
        # (n + worker_id) scheme caused heavy overlap across workers and
        # produced massive Snowflake result-cache hit rates (artificially low
        # P95 latencies).
        if not hasattr(self, "_worker_pool_seq"):
            self._worker_pool_seq = {}
        key = (int(worker_id), (kind or "").upper(), (column or "").upper())
        n = int(getattr(self, "_worker_pool_seq", {}).get(key, 0))
        getattr(self, "_worker_pool_seq")[key] = n + 1
        stride = int(getattr(self.scenario, "concurrent_connections", 1) or 1)
        stride = max(1, stride)
        idx = (n * stride + int(worker_id)) % len(values)
        return values[idx]

    async def execute(self) -> TestResult:
        """
        Execute performance test.

        - Spawn concurrent workers
        - Generate workloads
        - Collect metrics
        - Return results

        Returns:
            TestResult: Test execution results
        """
        metrics_task: Optional[asyncio.Task] = None
        try:
            logger.info(f"🚀 Executing test: {self.scenario.name}")
            logger.info(
                f"📋 Workload: {self.scenario.workload_type}, Duration: {self.scenario.duration_seconds}s, Workers: {self.scenario.concurrent_connections}"
            )

            self.status = TestStatus.RUNNING
            self.start_time = datetime.now()
            self.metrics.timestamp = self.start_time

            # Start metrics collector immediately (including warmup) so the UI
            # receives steady updates and the websocket doesn't go idle.
            metrics_task = asyncio.create_task(self._collect_metrics())

            # Warmup period
            if self.scenario.warmup_seconds > 0:
                logger.info(f"Warming up for {self.scenario.warmup_seconds}s...")
                await self._warmup()

            # Reset metrics after warmup
            self.metrics = Metrics()
            self.metrics.timestamp = datetime.now()
            # From this point forward we consider the measurement window started.
            self._measurement_start_time = datetime.now()
            # Reset snapshot state so current ops/sec doesn't get skewed by warmup counters.
            self._last_snapshot_time = None
            self._last_snapshot_ops = 0
            self._latencies_ms.clear()

            # Spawn workers
            logger.info(f"Spawning {self.scenario.concurrent_connections} workers...")
            self.workers = [
                asyncio.create_task(self._worker(worker_id))
                for worker_id in range(self.scenario.concurrent_connections)
            ]

            # Run for duration
            await asyncio.sleep(self.scenario.duration_seconds)

            # Stop workers
            logger.info("Stopping workers...")
            self._stop_event.set()

            # Wait for workers to finish
            await asyncio.gather(*self.workers, return_exceptions=True)

            # Stop metrics collector
            metrics_task.cancel()
            try:
                await metrics_task
            except asyncio.CancelledError:
                pass

            # Finalize
            self.end_time = datetime.now()
            self.status = TestStatus.COMPLETED

            # Build result
            self.test_result = await self._build_result()

            logger.info(
                f"✅ Test complete: {self.test_result.total_operations} ops, {self.test_result.operations_per_second:.2f} ops/sec"
            )
            logger.info(
                f"📊 Query distribution - Reads: {self._point_lookup_count} point lookups, {self._range_scan_count} range scans | Writes: {self._insert_count} inserts, {self._update_count} updates"
            )

            return self.test_result

        except asyncio.CancelledError:
            # Ensure worker tasks don't leak on cancellation (important for dev reload/shutdown).
            self._stop_event.set()
            for t in self.workers:
                try:
                    t.cancel()
                except Exception:
                    pass
            await asyncio.gather(*self.workers, return_exceptions=True)

            if metrics_task is not None:
                metrics_task.cancel()
                try:
                    await metrics_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            raise

        except Exception as e:
            logger.error(f"Error during test execution: {e}")
            self.status = TestStatus.FAILED
            self.end_time = datetime.now()

            # Build partial result
            self.test_result = await self._build_result()
            return self.test_result

    async def teardown(self) -> bool:
        """
        Teardown test environment.

        - Drop tables
        - Clean up resources

        Returns:
            bool: True if teardown successful
        """
        try:
            logger.info(f"Tearing down test: {self.scenario.name}")

            # Teardown tables in parallel
            teardown_tasks = [manager.teardown() for manager in self.table_managers]
            await asyncio.gather(*teardown_tasks, return_exceptions=True)

            logger.info("✅ Test teardown complete")
            return True

        except Exception as e:
            logger.error(f"Error during test teardown: {e}")
            return False

    async def _warmup(self):
        """Execute warmup period."""
        warmup_workers = [
            asyncio.create_task(self._worker(i, warmup=True))
            for i in range(min(5, self.scenario.concurrent_connections))
        ]
        try:
            await asyncio.sleep(self.scenario.warmup_seconds)
        finally:
            # Always stop warmup workers, even if the task is cancelled.
            self._stop_event.set()
            for t in warmup_workers:
                try:
                    t.cancel()
                except Exception:
                    pass
            await asyncio.gather(*warmup_workers, return_exceptions=True)
            self._stop_event.clear()

    async def _worker(self, worker_id: int, warmup: bool = False):
        """
        Worker task that executes operations.

        Args:
            worker_id: Worker identifier
            warmup: If True, this is a warmup run
        """
        operations_executed = 0
        target_ops = self.scenario.operations_per_connection

        try:
            while not self._stop_event.is_set():
                # Check if we've hit operation limit
                if target_ops and operations_executed >= target_ops:
                    break

                # Execute operation based on workload type
                await self._execute_operation(worker_id, warmup)
                operations_executed += 1

                # Think time
                if self.scenario.think_time_ms > 0:
                    await asyncio.sleep(self.scenario.think_time_ms / 1000.0)

                # Rate limiting
                if self.scenario.target_ops_per_second:
                    # Simple rate limiting (can be improved)
                    await asyncio.sleep(1.0 / self.scenario.target_ops_per_second)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not warmup:
                logger.error(f"Worker {worker_id} error: {e}")
                async with self._metrics_lock:
                    self.metrics.failed_operations += 1

    async def _execute_operation(self, worker_id: int, warmup: bool = False):
        """
        Execute a single operation based on workload type.

        Args:
            worker_id: Worker identifier
            warmup: If True, don't record metrics
        """
        workload = self.scenario.workload_type

        # Determine operation type
        if workload == WorkloadType.READ_ONLY:
            await self._execute_read(worker_id, warmup)
        elif workload == WorkloadType.WRITE_ONLY:
            await self._execute_write(worker_id, warmup)
        elif workload == WorkloadType.READ_HEAVY:
            # 80% reads, 20% writes
            import random

            if random.random() < 0.8:
                await self._execute_read(worker_id, warmup)
            else:
                await self._execute_write(worker_id, warmup)
        elif workload == WorkloadType.WRITE_HEAVY:
            # 20% reads, 80% writes
            import random

            if random.random() < 0.2:
                await self._execute_read(worker_id, warmup)
            else:
                await self._execute_write(worker_id, warmup)
        elif workload == WorkloadType.MIXED:
            # 50/50 reads/writes
            import random

            if random.random() < 0.5:
                await self._execute_read(worker_id, warmup)
            else:
                await self._execute_write(worker_id, warmup)
        elif workload == WorkloadType.CUSTOM:
            await self._execute_custom(worker_id, warmup)

    async def _execute_read(self, worker_id: int, warmup: bool = False):
        """Execute read operation."""
        start_wall = datetime.now(UTC)
        start_perf = time.perf_counter()

        query: str = ""
        params: Optional[list] = None
        query_kind = "RANGE_SCAN"

        try:
            # Select random table
            import random

            manager = random.choice(self.table_managers)
            full_name = manager.get_full_table_name()

            batch_size = self.scenario.read_batch_size
            state = self._table_state.get(full_name, _TableRuntimeState())
            profile = state.profile

            # Choose read shape:
            # - Point lookup (by ID) when possible
            # - Otherwise range scan (time-based if possible, else id-based)
            point_lookup_ratio = (
                self.scenario.point_lookup_ratio
                if hasattr(self.scenario, "point_lookup_ratio")
                else 0.5
            )
            do_point_lookup = random.random() < point_lookup_ratio
            used_point_lookup = False

            if (
                profile
                and profile.id_column
                and do_point_lookup
                and (
                    bool(self._pool_values("KEY", profile.id_column))
                    or (
                        profile.id_min is not None
                        and profile.id_max is not None
                        and profile.id_max >= profile.id_min
                    )
                )
            ):
                pooled = self._next_from_pool(worker_id, "KEY", profile.id_column)
                if pooled is None:
                    row_id = random.randint(profile.id_min, profile.id_max)  # type: ignore[arg-type]
                else:
                    row_id = pooled
                select_list = self._select_list_sql()
                query = f'SELECT {select_list} FROM {full_name} WHERE "{profile.id_column}" = ?'
                params = [row_id]
                used_point_lookup = True
                query_kind = "POINT_LOOKUP"
            else:
                query, params = self._build_range_scan(
                    full_name, profile, batch_size, worker_id=worker_id
                )

            # Get appropriate pool
            if hasattr(manager, "pool"):
                if hasattr(manager.pool, "execute_query"):
                    # Snowflake
                    result, info = await manager.pool.execute_query_with_info(
                        query, params=params, fetch=True
                    )
                    sf_query_id = str(info.get("query_id") or "")
                    sf_rowcount = info.get("rowcount")
                else:
                    # Postgres
                    result = await manager.pool.fetch_all(query)
                    sf_query_id = f"LOCAL_{uuid4()}"
                    sf_rowcount = None

                end_wall = datetime.now(UTC)
                app_elapsed_ms = (time.perf_counter() - start_perf) * 1000.0

                # Update metrics
                duration_ms = app_elapsed_ms

                # Always update the real-time counters used by the websocket + METRICS_SNAPSHOTS,
                # including during warmup. We still reset metrics after warmup so the final
                # summary remains measurement-window only.
                async with self._metrics_lock:
                    self.metrics.total_operations += 1
                    self.metrics.successful_operations += 1
                    self.metrics.read_metrics.count += 1
                    self.metrics.read_metrics.success_count += 1
                    self.metrics.read_metrics.total_duration_ms += duration_ms
                    self.metrics.rows_read += len(result)
                    self._latencies_ms.append(duration_ms)

                # Summary-only breakdowns exclude warmup.
                if not warmup:
                    if used_point_lookup:
                        self._point_lookup_count += 1
                    else:
                        self._range_scan_count += 1

                    self._lat_read_ms.append(duration_ms)
                    self._lat_by_kind_ms[query_kind].append(duration_ms)

                # Capture per-operation record if enabled for this scenario.
                #
                # Even when full query history capture is disabled, we still capture warmup
                # operations so they can be persisted for troubleshooting / visibility.
                if warmup or getattr(self.scenario, "collect_query_history", False):
                    pool_obj = getattr(manager, "pool", None)
                    pool_warehouse = (
                        str(getattr(pool_obj, "warehouse", "")).strip() or None
                    )
                    self._query_execution_records.append(
                        _QueryExecutionRecord(
                            execution_id=str(uuid4()),
                            test_id=str(self.test_id),
                            query_id=sf_query_id or f"LOCAL_{uuid4()}",
                            query_text=query,
                            start_time=start_wall,
                            end_time=end_wall,
                            duration_ms=app_elapsed_ms,
                            success=True,
                            error=None,
                            warehouse=pool_warehouse,
                            rows_affected=int(sf_rowcount)
                            if sf_rowcount is not None
                            else len(result),
                            bytes_scanned=None,
                            connection_id=None,
                            custom_metadata={"rows_returned": len(result)},
                            query_kind=query_kind,
                            worker_id=worker_id,
                            warmup=warmup,
                            app_elapsed_ms=app_elapsed_ms,
                        )
                    )

        except Exception as e:
            end_wall = datetime.now(UTC)
            app_elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
            if not warmup:
                logger.warning(f"Read operation failed: {e}")

            # Track failures during warmup too (metrics are reset after warmup).
            async with self._metrics_lock:
                self.metrics.total_operations += 1
                self.metrics.failed_operations += 1
                self.metrics.read_metrics.count += 1
                self.metrics.read_metrics.error_count += 1

            if warmup or getattr(self.scenario, "collect_query_history", False):
                self._query_execution_records.append(
                    _QueryExecutionRecord(
                        execution_id=str(uuid4()),
                        test_id=str(self.test_id),
                        query_id=f"LOCAL_{uuid4()}",
                        query_text=query or "READ_FAILED",
                        start_time=start_wall,
                        end_time=end_wall,
                        duration_ms=app_elapsed_ms,
                        success=False,
                        error=str(e),
                        warehouse=None,
                        rows_affected=None,
                        bytes_scanned=None,
                        connection_id=None,
                        custom_metadata={"params_count": len(params or [])},
                        query_kind=query_kind,
                        worker_id=worker_id,
                        warmup=warmup,
                        app_elapsed_ms=app_elapsed_ms,
                    )
                )

    def _build_range_scan(
        self,
        full_name: str,
        profile: Optional[TableProfile],
        batch_size: int,
        range_width: int = 100,
        *,
        worker_id: int = 0,
    ) -> tuple[str, Optional[list]]:
        import random

        if profile and profile.time_column and profile.time_max is not None:
            # Prefer a persisted pool of cutoffs (reduces identical range scans under concurrency).
            pooled = self._next_from_pool(worker_id, "RANGE", profile.time_column)
            if pooled is not None:
                cutoff = pooled
            elif profile.time_min is not None and profile.time_min < profile.time_max:
                # Pick a cutoff inside [min,max] so it should match some data.
                #
                # Randomize the choice (vs a constant midpoint) to avoid accidentally
                # generating identical range scans when RANGE pools are absent.
                span = profile.time_max - profile.time_min
                cutoff = profile.time_min + (span * random.random())
            else:
                cutoff = profile.time_max - timedelta(days=7)

            select_list = self._select_list_sql()
            query = (
                f'SELECT {select_list} FROM {full_name} WHERE "{profile.time_column}" >= ? '
                f'ORDER BY "{profile.time_column}" DESC LIMIT {batch_size}'
            )
            return query, [cutoff]

        if (
            profile
            and profile.id_column
            and profile.id_min is not None
            and profile.id_max is not None
        ):
            start_id = profile.id_min
            if profile.id_max > profile.id_min + range_width:
                start_id = random.randint(profile.id_min, profile.id_max - range_width)
            end_id = start_id + range_width

            select_list = self._select_list_sql()
            query = (
                f'SELECT {select_list} FROM {full_name} WHERE "{profile.id_column}" BETWEEN ? AND ? '
                f'ORDER BY "{profile.id_column}" LIMIT {batch_size}'
            )
            return query, [start_id, end_id]

        select_list = self._select_list_sql()
        return f"SELECT {select_list} FROM {full_name} LIMIT {batch_size}", None

    async def _execute_write(self, worker_id: int, warmup: bool = False):
        """Execute write operation."""
        start_wall = datetime.now(UTC)
        start_perf = time.perf_counter()

        query: str = ""
        params: Optional[list] = None
        query_kind = "INSERT"
        rows_written = 0

        try:
            # Select random table
            import random

            manager = random.choice(self.table_managers)
            full_name = manager.get_full_table_name()
            state = self._table_state.get(full_name, _TableRuntimeState())
            profile = state.profile

            # Decide between insert/update. If update_ratio isn't set, default to 30% updates.
            update_ratio = (
                self.scenario.update_ratio if self.scenario.update_ratio > 0 else 0.3
            )
            do_update = (
                profile is not None
                and profile.id_column is not None
                and (
                    bool(self._pool_values("KEY", profile.id_column))
                    or (
                        profile.id_min is not None
                        and profile.id_max is not None
                        and profile.id_max >= profile.id_min
                    )
                )
                and random.random() < update_ratio
            )

            if do_update:
                # `do_update` guarantees profile is present and has id bounds.
                query, params = self._build_update(full_name, manager, profile)  # type: ignore[arg-type]
                rows_written = 1
                query_kind = "UPDATE"
                if not warmup:
                    self._update_count += 1
            else:
                query, params = self._build_insert(full_name, manager, state)
                rows_written = self.scenario.write_batch_size
                query_kind = "INSERT"
                if not warmup:
                    self._insert_count += 1

            # Execute write
            if hasattr(manager, "pool"):
                if hasattr(manager.pool, "execute_query"):
                    # Snowflake
                    _, info = await manager.pool.execute_query_with_info(
                        query, params=params, fetch=False
                    )
                    sf_query_id = str(info.get("query_id") or "")
                    sf_rowcount = info.get("rowcount")
                else:
                    # Postgres
                    await manager.pool.execute_query(query)
                    sf_query_id = f"LOCAL_{uuid4()}"
                    sf_rowcount = None

                end_wall = datetime.now(UTC)
                app_elapsed_ms = (time.perf_counter() - start_perf) * 1000.0

                # Update metrics
                duration_ms = app_elapsed_ms

                # Always update the real-time counters used by the websocket + METRICS_SNAPSHOTS,
                # including during warmup. We still reset metrics after warmup so the final
                # summary remains measurement-window only.
                async with self._metrics_lock:
                    self.metrics.total_operations += 1
                    self.metrics.successful_operations += 1
                    self.metrics.write_metrics.count += 1
                    self.metrics.write_metrics.success_count += 1
                    self.metrics.write_metrics.total_duration_ms += duration_ms
                    self.metrics.rows_written += rows_written
                    self._latencies_ms.append(duration_ms)

                # Summary-only breakdowns exclude warmup.
                if not warmup:
                    self._lat_write_ms.append(duration_ms)
                    self._lat_by_kind_ms[query_kind].append(duration_ms)

                if warmup or getattr(self.scenario, "collect_query_history", False):
                    pool_obj = getattr(manager, "pool", None)
                    pool_warehouse = (
                        str(getattr(pool_obj, "warehouse", "")).strip() or None
                    )
                    self._query_execution_records.append(
                        _QueryExecutionRecord(
                            execution_id=str(uuid4()),
                            test_id=str(self.test_id),
                            query_id=sf_query_id or f"LOCAL_{uuid4()}",
                            query_text=query,
                            start_time=start_wall,
                            end_time=end_wall,
                            duration_ms=app_elapsed_ms,
                            success=True,
                            error=None,
                            warehouse=pool_warehouse,
                            rows_affected=int(sf_rowcount)
                            if sf_rowcount is not None
                            else rows_written,
                            bytes_scanned=None,
                            connection_id=None,
                            custom_metadata={"rows_written": rows_written},
                            query_kind=query_kind,
                            worker_id=worker_id,
                            warmup=warmup,
                            app_elapsed_ms=app_elapsed_ms,
                        )
                    )

        except Exception as e:
            end_wall = datetime.now(UTC)
            app_elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
            if not warmup:
                logger.debug(f"Write operation failed: {e}")

            # Track failures during warmup too (metrics are reset after warmup).
            async with self._metrics_lock:
                self.metrics.total_operations += 1
                self.metrics.failed_operations += 1
                self.metrics.write_metrics.count += 1
                self.metrics.write_metrics.error_count += 1

            if warmup or getattr(self.scenario, "collect_query_history", False):
                self._query_execution_records.append(
                    _QueryExecutionRecord(
                        execution_id=str(uuid4()),
                        test_id=str(self.test_id),
                        query_id=f"LOCAL_{uuid4()}",
                        query_text=query or "WRITE_FAILED",
                        start_time=start_wall,
                        end_time=end_wall,
                        duration_ms=app_elapsed_ms,
                        success=False,
                        error=str(e),
                        warehouse=None,
                        rows_affected=None,
                        bytes_scanned=None,
                        connection_id=None,
                        custom_metadata={"params_count": len(params or [])},
                        query_kind=query_kind,
                        worker_id=worker_id,
                        warmup=warmup,
                        app_elapsed_ms=app_elapsed_ms,
                    )
                )

    def get_query_execution_records(self) -> list[_QueryExecutionRecord]:
        """Get captured per-operation records (including warmup if enabled)."""
        return list(self._query_execution_records)

    def _build_insert(
        self, full_name: str, manager: TableManager, state: _TableRuntimeState
    ) -> tuple[str, Optional[list]]:
        import random

        columns = list(manager.config.columns.keys())
        batch_size = self.scenario.write_batch_size
        id_col = state.profile.id_column if state.profile else None
        row_pool: list[Any] = self._pool_values("ROW", None)
        use_params = hasattr(getattr(manager, "pool", None), "execute_query_with_info")

        # If template specifies explicit insert columns, honor them (and keep ROW pool aligned).
        tpl_cfg = getattr(self, "_template_config", None)
        if isinstance(tpl_cfg, dict):
            ai_cfg = tpl_cfg.get("ai_workload")
            if isinstance(ai_cfg, dict) and isinstance(
                ai_cfg.get("insert_columns"), list
            ):
                desired = [
                    str(c).upper()
                    for c in ai_cfg.get("insert_columns")
                    if str(c).strip()
                ]
                available = {str(c).upper() for c in manager.config.columns.keys()}
                chosen = [c for c in desired if c in available]
                if chosen:
                    columns = chosen
                    # Ensure key column is inserted if required.
                    if (
                        id_col
                        and id_col.upper() in available
                        and id_col.upper() not in columns
                    ):
                        columns = [id_col.upper(), *columns]

        if not use_params:
            # Legacy literal SQL path (used by non-Snowflake pools)
            values_list: list[str] = []
            for _ in range(batch_size):
                row_values: list[str] = []
                for col in columns:
                    col_upper = col.upper()
                    col_type = manager.config.columns[col].upper()

                    if (
                        id_col
                        and col_upper == id_col
                        and any(t in col_type for t in ("NUMBER", "INT", "DECIMAL"))
                    ):
                        if state.next_insert_id is None:
                            state.next_insert_id = 1
                        row_values.append(str(state.next_insert_id))
                        state.next_insert_id += 1
                        continue

                    if "TIMESTAMP" in col_type:
                        row_values.append("CURRENT_TIMESTAMP")
                    elif "DATE" in col_type:
                        row_values.append("CURRENT_DATE")
                    elif (
                        "NUMBER" in col_type
                        or "INT" in col_type
                        or "DECIMAL" in col_type
                    ):
                        row_values.append(str(random.randint(1, 1_000_000)))
                    elif (
                        "VARCHAR" in col_type
                        or "TEXT" in col_type
                        or "STRING" in col_type
                    ):
                        # Keep literals short; this path is primarily for debugging/non-Snowflake pools.
                        row_values.append(f"'T{random.randint(0, 9)}'")
                    else:
                        row_values.append("NULL")

                values_list.append(f"({', '.join(row_values)})")

            return (
                f"INSERT INTO {full_name} ({', '.join(columns)}) VALUES {', '.join(values_list)}",
                None,
            )

        # Parameterized Snowflake insert using pooled rows when available.
        placeholders: list[str] = []
        params: list[Any] = []
        for i in range(batch_size):
            sample_row = row_pool[(i % len(row_pool))] if row_pool else {}
            row_ph: list[str] = []
            for col in columns:
                col_upper = col.upper()
                col_type = manager.config.columns[col].upper()

                if id_col and col_upper == id_col:
                    # Prefer monotonic unique IDs for numeric keys; otherwise use UUID.
                    if any(t in col_type for t in ("NUMBER", "INT", "DECIMAL")):
                        seq = state.insert_id_seq or count(1)
                        state.insert_id_seq = seq
                        params.append(next(seq))
                    else:
                        params.append(str(uuid4()))
                    row_ph.append("?")
                    continue

                if isinstance(sample_row, dict) and col_upper in sample_row:
                    params.append(sample_row.get(col_upper))
                    row_ph.append("?")
                    continue

                if "TIMESTAMP" in col_type:
                    params.append(datetime.now(UTC))
                elif "DATE" in col_type:
                    params.append(datetime.now(UTC).date())
                elif "NUMBER" in col_type or "INT" in col_type or "DECIMAL" in col_type:
                    params.append(random.randint(1, 1000000))
                elif (
                    "VARCHAR" in col_type or "TEXT" in col_type or "STRING" in col_type
                ):
                    params.append(f"TEST_{random.randint(1, 1000000)}")
                else:
                    params.append(None)
                row_ph.append("?")

            placeholders.append(f"({', '.join(row_ph)})")

        cols_sql = ", ".join(f'"{c.upper()}"' for c in columns)
        query = f"INSERT INTO {full_name} ({cols_sql}) VALUES {', '.join(placeholders)}"
        return query, params

    def _build_update(
        self, full_name: str, manager: TableManager, profile: TableProfile
    ) -> tuple[str, list]:
        import random

        # Prefer pooled keys if available.
        pooled = self._next_from_pool(0, "KEY", profile.id_column)
        if pooled is not None:
            target_id = pooled
        elif profile.id_min is not None and profile.id_max is not None:
            target_id = random.randint(profile.id_min, profile.id_max)
        else:
            raise ValueError("Cannot build update without key pool or id_min/id_max")

        # If template specifies update columns, honor that first.
        tpl_cfg = getattr(self, "_template_config", None)
        update_cols = []
        if isinstance(tpl_cfg, dict):
            ai_cfg = tpl_cfg.get("ai_workload")
            if isinstance(ai_cfg, dict) and isinstance(
                ai_cfg.get("update_columns"), list
            ):
                update_cols = [
                    str(c).upper()
                    for c in ai_cfg.get("update_columns")
                    if str(c).strip()
                ]

        candidates = update_cols or [c.upper() for c in manager.config.columns.keys()]
        for col_upper in candidates:
            if col_upper == profile.id_column:
                continue
            col_type_raw = manager.config.columns.get(
                col_upper
            ) or manager.config.columns.get(col_upper.lower())
            col_type = str(col_type_raw or "").upper()

            if "TIMESTAMP" in col_type or "DATE" in col_type:
                query = f'UPDATE {full_name} SET "{col_upper}" = CURRENT_TIMESTAMP WHERE "{profile.id_column}" = ?'
                return query, [target_id]

            if "VARCHAR" in col_type or "TEXT" in col_type or "STRING" in col_type:
                query = f'UPDATE {full_name} SET "{col_upper}" = ? WHERE "{profile.id_column}" = ?'
                return query, [f"TEST_{random.randint(1, 1000000)}", target_id]

            if "NUMBER" in col_type or "INT" in col_type or "DECIMAL" in col_type:
                query = f'UPDATE {full_name} SET "{col_upper}" = ? WHERE "{profile.id_column}" = ?'
                return query, [random.randint(1, 1000000), target_id]

        query = f'UPDATE {full_name} SET "{profile.id_column}" = "{profile.id_column}" WHERE "{profile.id_column}" = ?'
        return query, [target_id]

    async def _execute_custom(self, worker_id: int, warmup: bool = False):
        """
        Execute a CUSTOM operation.

        CUSTOM workloads are authoritative for templates:
        - Deterministic selection according to stored weights (exact over a full cycle)
        - SQL comes from template config (scenario.custom_queries), with `{table}` substituted
        - Params are generated for the canonical 4-query workload (POINT_LOOKUP/RANGE_SCAN/INSERT/UPDATE)
        """
        start_wall = datetime.now(UTC)
        start_perf = time.perf_counter()

        query_kind = self._custom_next_kind(worker_id)
        is_read = query_kind in {"POINT_LOOKUP", "RANGE_SCAN"}

        # Select random table (templates typically include 1 table; keep generic).
        import random

        manager = random.choice(self.table_managers)
        full_name = manager.get_full_table_name()
        state = self._table_state.get(full_name, _TableRuntimeState())
        profile = state.profile

        sql_tpl = self._custom_sql_by_kind.get(query_kind)
        if not sql_tpl:
            raise ValueError(f"No SQL found for custom query kind {query_kind}")
        query = sql_tpl.replace("{table}", full_name)

        params: Optional[list[Any]] = None
        rows_written_expected = 0

        def _choose_id() -> Any:
            if profile and profile.id_column:
                pooled = self._next_from_pool(worker_id, "KEY", profile.id_column)
                if pooled is not None:
                    return pooled
                if (
                    profile.id_min is not None
                    and profile.id_max is not None
                    and profile.id_max >= profile.id_min
                ):
                    return random.randint(profile.id_min, profile.id_max)
            raise ValueError("Cannot choose key value (missing KEY pool and id bounds)")

        # Template-provided workload metadata (populated by UI adjustment + persisted on save).
        tpl_cfg = getattr(self, "_template_config", None)
        ai_cfg = None
        if isinstance(tpl_cfg, dict):
            ai_cfg = tpl_cfg.get("ai_workload")

        insert_cols: list[str] = []
        update_cols: list[str] = []
        if isinstance(ai_cfg, dict):
            if isinstance(ai_cfg.get("insert_columns"), list):
                insert_cols = [
                    str(c).upper()
                    for c in ai_cfg.get("insert_columns")
                    if str(c).strip()
                ]
            if isinstance(ai_cfg.get("update_columns"), list):
                update_cols = [
                    str(c).upper()
                    for c in ai_cfg.get("update_columns")
                    if str(c).strip()
                ]

        def _count_placeholders(sql: str) -> int:
            return int(sql.count("?"))

        def _col_type(col_upper: str) -> str:
            raw = manager.config.columns.get(col_upper) or manager.config.columns.get(
                col_upper.lower()
            )
            return str(raw or "").upper()

        def _new_value_for(col_upper: str) -> Any:
            typ = _col_type(col_upper)
            if "TIMESTAMP" in typ:
                return datetime.now(UTC)
            if "DATE" in typ:
                return datetime.now(UTC).date()
            if "NUMBER" in typ or "INT" in typ or "DECIMAL" in typ:
                import random

                m = re.search(r"\((\d+)\s*,\s*(\d+)\)", typ)
                if m:
                    scale = int(m.group(2))
                    if scale > 0:
                        # Keep values small-ish but valid for the declared scale.
                        return round(random.random() * 1000.0, scale)
                return random.randint(1, 1_000_000)
            # Strings
            import random

            max_len: int | None = None
            m = re.search(r"(VARCHAR|CHAR|CHARACTER)\s*\(\s*(\d+)\s*\)", typ)
            if m:
                try:
                    max_len = int(m.group(2))
                except Exception:
                    max_len = None
            if max_len is not None and max_len <= 0:
                max_len = None
            if max_len == 1:
                return random.choice(list("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
            base = f"TEST_{random.randint(1, 1_000_000)}"
            return base[:max_len] if max_len else base

        def _split_top_level_csv(s: str) -> list[str]:
            out: list[str] = []
            cur: list[str] = []
            depth = 0
            in_sq = False
            for ch in s:
                if in_sq:
                    cur.append(ch)
                    if ch == "'":
                        in_sq = False
                    continue
                if ch == "'":
                    in_sq = True
                    cur.append(ch)
                    continue
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth = max(0, depth - 1)
                if ch == "," and depth == 0:
                    token = "".join(cur).strip()
                    if token:
                        out.append(token)
                    cur = []
                    continue
                cur.append(ch)
            tail = "".join(cur).strip()
            if tail:
                out.append(tail)
            return out

        def _clean_ident(tok: str) -> str:
            t = str(tok or "").strip()
            # Strip double quotes used for identifiers.
            if len(t) >= 2 and t[0] == '"' and t[-1] == '"':
                t = t[1:-1]
            return t.strip().upper()

        def _insert_placeholder_columns(sql: str) -> list[str]:
            # Returns a list of column names in the same order as `?` placeholders.
            m = re.search(
                r"(?is)\binsert\s+into\s+.+?\(\s*(?P<cols>.*?)\s*\)\s*values\s*\(\s*(?P<vals>.*?)\s*\)",
                sql,
            )
            if not m:
                return []
            cols_raw = m.group("cols")
            vals_raw = m.group("vals")
            cols = [_clean_ident(c) for c in _split_top_level_csv(cols_raw)]
            vals = _split_top_level_csv(vals_raw)
            if not cols or not vals or len(cols) != len(vals):
                return []
            out: list[str] = []
            for col, val_expr in zip(cols, vals):
                n = str(val_expr).count("?")
                if n <= 0:
                    continue
                out.extend([col] * n)
            return out

        if query_kind == "POINT_LOOKUP":
            target_id = _choose_id()
            params = [target_id]
            if not warmup:
                self._point_lookup_count += 1
        elif query_kind == "RANGE_SCAN":
            ph = _count_placeholders(query)
            if ph == 1:
                # Time-based cutoff preferred; bind from RANGE pool if available, else fallback.
                if profile and profile.time_column:
                    pooled = self._next_from_pool(
                        worker_id, "RANGE", profile.time_column
                    )
                    if pooled is not None:
                        params = [pooled]
                    elif profile.time_max is not None:
                        params = [profile.time_max - timedelta(days=7)]
                    else:
                        raise ValueError(
                            "Cannot choose range cutoff (missing RANGE pool and time bounds)"
                        )
                else:
                    raise ValueError(
                        "Range scan SQL expects 1 param but no time column detected"
                    )
            else:
                # Default: id-based BETWEEN form expects 2 params; bind (start,start).
                start_id = _choose_id()
                params = [start_id, start_id]
            if not warmup:
                self._range_scan_count += 1
        elif query_kind == "INSERT":
            ph = _count_placeholders(query)
            if ph <= 0:
                raise ValueError("INSERT SQL must use placeholders")

            cols_from_sql = _insert_placeholder_columns(query)
            if cols_from_sql and len(cols_from_sql) == ph:
                cols = cols_from_sql
            else:
                # Fallback: use insert_columns ordering if provided; else manager columns.
                cols = insert_cols or [
                    str(c).upper() for c in manager.config.columns.keys()
                ]
                cols = cols[:ph]
            sample_row = self._next_from_pool(worker_id, "ROW", None) or {}

            params = []
            for c in cols:
                if (
                    profile
                    and profile.id_column
                    and c == str(profile.id_column).upper()
                ):
                    # Unique key values
                    col_type = _col_type(c)
                    if any(t in col_type for t in ("NUMBER", "INT", "DECIMAL")):
                        seq = state.insert_id_seq or count(1)
                        state.insert_id_seq = seq
                        params.append(next(seq))
                    else:
                        params.append(str(uuid4()))
                    continue
                if isinstance(sample_row, dict) and c in sample_row:
                    params.append(sample_row.get(c))
                    continue
                params.append(_new_value_for(c))
            rows_written_expected = 1
            if not warmup:
                self._insert_count += 1
        elif query_kind == "UPDATE":
            target_id = _choose_id()
            ph = _count_placeholders(query)
            if ph == 1:
                # Degenerate form: WHERE key = ? only
                params = [target_id]
            else:
                col = update_cols[0] if update_cols else None
                new_val = _new_value_for(col) if col else f"TEST_{uuid4()}"
                params = [new_val, target_id]
            rows_written_expected = 1
            if not warmup:
                self._update_count += 1
        else:
            raise ValueError(f"Unsupported custom query kind {query_kind}")

        try:
            if not hasattr(manager, "pool") or not hasattr(
                manager.pool, "execute_query"
            ):
                raise ValueError(
                    "CUSTOM workloads currently require Snowflake execution"
                )

            # Snowflake execution via execute_query_with_info
            if is_read:
                result, info = await manager.pool.execute_query_with_info(
                    query, params=params, fetch=True
                )
                rows_read = len(result or [])
                sf_query_id = str(info.get("query_id") or "")
                sf_rowcount = info.get("rowcount")
            else:
                _, info = await manager.pool.execute_query_with_info(
                    query, params=params, fetch=False
                )
                rows_read = 0
                sf_query_id = str(info.get("query_id") or "")
                sf_rowcount = info.get("rowcount")

            end_wall = datetime.now(UTC)
            app_elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
            duration_ms = app_elapsed_ms

            async with self._metrics_lock:
                self.metrics.total_operations += 1
                self.metrics.successful_operations += 1
                self._latencies_ms.append(duration_ms)

                if is_read:
                    self.metrics.read_metrics.count += 1
                    self.metrics.read_metrics.success_count += 1
                    self.metrics.read_metrics.total_duration_ms += duration_ms
                    self.metrics.rows_read += int(rows_read)
                else:
                    rows_written = (
                        int(sf_rowcount)
                        if sf_rowcount is not None
                        else int(rows_written_expected)
                    )
                    self.metrics.write_metrics.count += 1
                    self.metrics.write_metrics.success_count += 1
                    self.metrics.write_metrics.total_duration_ms += duration_ms
                    self.metrics.rows_written += rows_written

            if not warmup:
                if is_read:
                    self._lat_read_ms.append(duration_ms)
                else:
                    self._lat_write_ms.append(duration_ms)
                self._lat_by_kind_ms[query_kind].append(duration_ms)

            if warmup or getattr(self.scenario, "collect_query_history", False):
                pool_obj = getattr(manager, "pool", None)
                pool_warehouse = str(getattr(pool_obj, "warehouse", "")).strip() or None
                self._query_execution_records.append(
                    _QueryExecutionRecord(
                        execution_id=str(uuid4()),
                        test_id=str(self.test_id),
                        query_id=sf_query_id or f"LOCAL_{uuid4()}",
                        query_text=query,
                        start_time=start_wall,
                        end_time=end_wall,
                        duration_ms=app_elapsed_ms,
                        success=True,
                        error=None,
                        warehouse=pool_warehouse,
                        rows_affected=(
                            int(sf_rowcount)
                            if sf_rowcount is not None
                            else (
                                int(rows_read)
                                if is_read
                                else int(rows_written_expected)
                            )
                        ),
                        bytes_scanned=None,
                        connection_id=None,
                        custom_metadata={
                            "params_count": len(params or []),
                            "rows_returned": int(rows_read),
                        }
                        if is_read
                        else {"params_count": len(params or [])},
                        query_kind=query_kind,
                        worker_id=worker_id,
                        warmup=warmup,
                        app_elapsed_ms=app_elapsed_ms,
                    )
                )

        except Exception as e:
            end_wall = datetime.now(UTC)
            app_elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
            if not warmup:
                logger.warning("Custom operation failed (%s): %s", query_kind, e)

            async with self._metrics_lock:
                self.metrics.total_operations += 1
                self.metrics.failed_operations += 1
                if is_read:
                    self.metrics.read_metrics.count += 1
                    self.metrics.read_metrics.error_count += 1
                else:
                    self.metrics.write_metrics.count += 1
                    self.metrics.write_metrics.error_count += 1

            if warmup or getattr(self.scenario, "collect_query_history", False):
                self._query_execution_records.append(
                    _QueryExecutionRecord(
                        execution_id=str(uuid4()),
                        test_id=str(self.test_id),
                        query_id=f"LOCAL_{uuid4()}",
                        query_text=query,
                        start_time=start_wall,
                        end_time=end_wall,
                        duration_ms=app_elapsed_ms,
                        success=False,
                        error=str(e),
                        warehouse=None,
                        rows_affected=None,
                        bytes_scanned=None,
                        connection_id=None,
                        custom_metadata={"params_count": len(params or [])},
                        query_kind=query_kind,
                        worker_id=worker_id,
                        warmup=warmup,
                        app_elapsed_ms=app_elapsed_ms,
                    )
                )

    async def _collect_metrics(self):
        """Collect metrics at regular intervals."""
        interval = self.scenario.metrics_interval_seconds

        try:
            while True:
                await asyncio.sleep(interval)

                now = datetime.now()
                self.metrics.timestamp = now

                # Update elapsed time
                base = self._measurement_start_time or self.start_time
                if base:
                    self.metrics.elapsed_seconds = (now - base).total_seconds()

                async with self._metrics_lock:
                    # Calculate average ops/sec
                    if self.metrics.elapsed_seconds > 0:
                        self.metrics.avg_ops_per_second = (
                            self.metrics.total_operations / self.metrics.elapsed_seconds
                        )

                    # Calculate current ops/sec (since last snapshot)
                    if self._last_snapshot_time is not None:
                        dt = (now - self._last_snapshot_time).total_seconds()
                        if dt > 0:
                            ops_delta = (
                                self.metrics.total_operations - self._last_snapshot_ops
                            )
                            self.metrics.current_ops_per_second = ops_delta / dt
                            if (
                                self.metrics.current_ops_per_second
                                > self.metrics.peak_ops_per_second
                            ):
                                self.metrics.peak_ops_per_second = (
                                    self.metrics.current_ops_per_second
                                )
                    self._last_snapshot_time = now
                    self._last_snapshot_ops = self.metrics.total_operations

                    # Latency percentiles over a rolling window
                    if self._latencies_ms:
                        latencies = sorted(self._latencies_ms)

                        def pct(p: float) -> float:
                            if not latencies:
                                return 0.0
                            k = int(round((p / 100.0) * (len(latencies) - 1)))
                            k = max(0, min(k, len(latencies) - 1))
                            return float(latencies[k])

                        self.metrics.overall_latency.p50 = pct(50)
                        self.metrics.overall_latency.p90 = pct(90)
                        self.metrics.overall_latency.p95 = pct(95)
                        self.metrics.overall_latency.p99 = pct(99)
                        self.metrics.overall_latency.min = float(latencies[0])
                        self.metrics.overall_latency.max = float(latencies[-1])
                        self.metrics.overall_latency.avg = float(
                            sum(latencies) / len(latencies)
                        )

                # Invoke callback if set
                if self.metrics_callback:
                    try:
                        self.metrics_callback(self.metrics)
                    except Exception as e:
                        logger.error(f"Metrics callback error: {e}")

        except asyncio.CancelledError:
            pass

    async def _build_result(self) -> TestResult:
        """Build test result from metrics."""
        duration = 0.0
        if self.start_time and self.end_time:
            duration = (self.end_time - self.start_time).total_seconds()

        def _pct(values: list[float], p: float) -> float:
            if not values:
                return 0.0
            xs = sorted(values)
            if len(xs) == 1:
                return float(xs[0])
            k = int(round((p / 100.0) * (len(xs) - 1)))
            k = max(0, min(k, len(xs) - 1))
            return float(xs[k])

        def _min(values: list[float]) -> float:
            return float(min(values)) if values else 0.0

        def _max(values: list[float]) -> float:
            return float(max(values)) if values else 0.0

        def _avg(values: list[float]) -> float:
            return float(sum(values) / len(values)) if values else 0.0

        overall_lat = list(self._latencies_ms)
        overall_p50 = _pct(overall_lat, 50)
        overall_p90 = _pct(overall_lat, 90)
        overall_p95 = _pct(overall_lat, 95)
        overall_p99 = _pct(overall_lat, 99)
        overall_min = _min(overall_lat)
        overall_max = _max(overall_lat)
        overall_avg = _avg(overall_lat)

        read_p50 = _pct(self._lat_read_ms, 50)
        read_p95 = _pct(self._lat_read_ms, 95)
        read_p99 = _pct(self._lat_read_ms, 99)
        read_min = _min(self._lat_read_ms)
        read_max = _max(self._lat_read_ms)

        write_p50 = _pct(self._lat_write_ms, 50)
        write_p95 = _pct(self._lat_write_ms, 95)
        write_p99 = _pct(self._lat_write_ms, 99)
        write_min = _min(self._lat_write_ms)
        write_max = _max(self._lat_write_ms)

        pl = self._lat_by_kind_ms.get("POINT_LOOKUP", [])
        rs = self._lat_by_kind_ms.get("RANGE_SCAN", [])
        ins = self._lat_by_kind_ms.get("INSERT", [])
        upd = self._lat_by_kind_ms.get("UPDATE", [])

        # Get first table info
        table_config = (
            self.scenario.table_configs[0] if self.scenario.table_configs else None
        )

        result = TestResult(
            test_id=self.test_id,
            test_name=f"test_{self.scenario.name}",
            scenario_name=self.scenario.name,
            table_name=table_config.name if table_config else "unknown",
            table_type=table_config.table_type if table_config else "unknown",
            status=self.status,
            start_time=self.start_time or datetime.now(),
            end_time=self.end_time,
            duration_seconds=duration,
            concurrent_connections=self.scenario.concurrent_connections,
            total_operations=self.metrics.total_operations,
            read_operations=self.metrics.read_metrics.count,
            write_operations=self.metrics.write_metrics.count,
            failed_operations=self.metrics.failed_operations,
            operations_per_second=self.metrics.avg_ops_per_second,
            reads_per_second=self.metrics.read_metrics.count / duration
            if duration > 0
            else 0,
            writes_per_second=self.metrics.write_metrics.count / duration
            if duration > 0
            else 0,
            rows_read=self.metrics.rows_read,
            rows_written=self.metrics.rows_written,
            avg_latency_ms=overall_avg,
            p50_latency_ms=overall_p50,
            p90_latency_ms=overall_p90,
            p95_latency_ms=overall_p95,
            p99_latency_ms=overall_p99,
            min_latency_ms=overall_min,
            max_latency_ms=overall_max,
            read_p50_latency_ms=read_p50,
            read_p95_latency_ms=read_p95,
            read_p99_latency_ms=read_p99,
            read_min_latency_ms=read_min,
            read_max_latency_ms=read_max,
            write_p50_latency_ms=write_p50,
            write_p95_latency_ms=write_p95,
            write_p99_latency_ms=write_p99,
            write_min_latency_ms=write_min,
            write_max_latency_ms=write_max,
            point_lookup_p50_latency_ms=_pct(pl, 50),
            point_lookup_p95_latency_ms=_pct(pl, 95),
            point_lookup_p99_latency_ms=_pct(pl, 99),
            point_lookup_min_latency_ms=_min(pl),
            point_lookup_max_latency_ms=_max(pl),
            range_scan_p50_latency_ms=_pct(rs, 50),
            range_scan_p95_latency_ms=_pct(rs, 95),
            range_scan_p99_latency_ms=_pct(rs, 99),
            range_scan_min_latency_ms=_min(rs),
            range_scan_max_latency_ms=_max(rs),
            insert_p50_latency_ms=_pct(ins, 50),
            insert_p95_latency_ms=_pct(ins, 95),
            insert_p99_latency_ms=_pct(ins, 99),
            insert_min_latency_ms=_min(ins),
            insert_max_latency_ms=_max(ins),
            update_p50_latency_ms=_pct(upd, 50),
            update_p95_latency_ms=_pct(upd, 95),
            update_p99_latency_ms=_pct(upd, 99),
            update_min_latency_ms=_min(upd),
            update_max_latency_ms=_max(upd),
        )

        return result

    def set_metrics_callback(self, callback: Callable[[Metrics], None]):
        """
        Set callback for real-time metrics updates.

        Args:
            callback: Function to call with metrics updates
        """
        self.metrics_callback = callback
