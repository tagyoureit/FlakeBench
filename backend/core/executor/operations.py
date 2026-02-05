"""
Operation execution for test executor.

NOTE: All workloads now use CUSTOM execution path exclusively (_execute_custom).
Legacy methods (_execute_read, _execute_write, _build_insert) have been removed.
Templates are normalized to CUSTOM with explicit query percentages during save.
"""

import asyncio
import logging
import random
import re
import time
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import TYPE_CHECKING, Any, Optional, cast
from uuid import uuid4

from backend.core.executor.helpers import (
    annotate_query_for_sf_kind,
    classify_sql_error,
    is_postgres_pool,
    quote_column,
)
from backend.core.executor.types import QueryExecutionRecord, TableRuntimeState

if TYPE_CHECKING:
    from backend.core.table_managers import TableManager
    from backend.core.table_profiler import TableProfile

logger = logging.getLogger(__name__)


class OperationsMixin:
    """Mixin providing operation execution functionality for TestExecutor."""

    if TYPE_CHECKING:

        def _init_custom_workload(self) -> None: ...

    # These attributes are defined in the main TestExecutor class
    scenario: Any
    test_id: Any
    table_managers: list["TableManager"]
    _table_state: dict[str, TableRuntimeState]
    _metrics_lock: asyncio.Lock
    _metrics_epoch: int
    metrics: Any
    _latencies_ms: Any
    _find_max_step_collecting: bool
    _find_max_step_ops_by_kind: dict[str, int]
    _find_max_step_lat_by_kind_ms: dict[str, Any]
    _find_max_step_errors_by_kind: dict[str, int]
    _sql_error_categories: dict[str, int]
    _sql_error_sample_counts: dict[str, int]
    _lat_by_kind_ms: dict[str, list[float]]
    _lat_read_ms: list[float]
    _lat_write_ms: list[float]
    _latency_sf_execution_ms: Any
    _latency_network_overhead_ms: Any
    _point_lookup_count: int
    _range_scan_count: int
    _insert_count: int
    _update_count: int
    _custom_schedule: list[str]
    _custom_sql_by_kind: dict[str, str]
    _custom_weights: dict[str, int]
    _custom_pos_by_worker: dict[int, int]
    _query_execution_records: Any

    def _pool_values(self, kind: str, column: Optional[str] = None) -> list[Any]:
        """Get values from a value pool."""
        pools = getattr(self, "_value_pools", {}) or {}
        kind_u = (kind or "").upper()
        col_u = column.upper() if column else None
        return list(pools.get(kind_u, {}).get(col_u, []))

    def _next_from_pool(
        self, worker_id: int, kind: str, column: Optional[str] = None
    ) -> Any:
        """Get next value from a pool with worker-specific cycling."""
        values = self._pool_values(kind, column)
        if not values:
            return None

        if not hasattr(self, "_worker_pool_seq"):
            self._worker_pool_seq = {}

        key = (int(worker_id), (kind or "").upper(), (column or "").upper())
        n = int(getattr(self, "_worker_pool_seq", {}).get(key, 0))
        getattr(self, "_worker_pool_seq")[key] = n + 1

        local_concurrency = int(getattr(self.scenario, "total_threads", 1) or 1)
        local_concurrency = max(1, local_concurrency)
        group_id = int(getattr(self.scenario, "worker_group_id", 0) or 0)
        group_count = int(getattr(self.scenario, "worker_group_count", 1) or 1)
        group_count = max(1, group_count)
        if group_id < 0:
            group_id = 0
        if group_id >= group_count:
            group_id = group_count - 1

        global_stride = local_concurrency * group_count
        global_worker_id = (group_id * local_concurrency) + int(worker_id)
        idx = (n * global_stride + global_worker_id) % len(values)
        return values[idx]

    def _select_list_sql(self) -> str:
        """Get SELECT projection list from template config."""
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

    def _custom_next_kind(self, worker_id: int) -> str:
        """Get next query kind for CUSTOM workload."""
        if not self._custom_schedule:
            self._init_custom_workload()
        if not self._custom_schedule:
            raise ValueError("CUSTOM workload has no scheduled queries")
        n = len(self._custom_schedule)
        pos = self._custom_pos_by_worker.get(worker_id, worker_id % n)
        kind = self._custom_schedule[pos]
        self._custom_pos_by_worker[worker_id] = (pos + 1) % n
        return kind

    async def _append_query_execution_record(
        self, record: QueryExecutionRecord
    ) -> None:
        """Append a query execution record to storage."""
        self._query_execution_records.append(record)

    async def _execute_custom(self, worker_id: int, warmup: bool = False) -> None:
        """Execute a CUSTOM workload operation."""
        start_perf = time.perf_counter()
        epoch_at_start = int(self._metrics_epoch)

        query_kind = self._custom_next_kind(worker_id)
        is_read = query_kind in {"POINT_LOOKUP", "RANGE_SCAN"}

        manager = random.choice(self.table_managers)
        full_name = manager.get_full_table_name()
        self._table_state.setdefault(full_name, TableRuntimeState())
        state = self._table_state[full_name]
        profile = state.profile
        pool = cast(Any, getattr(manager, "pool", None))

        sql_tpl = self._custom_sql_by_kind.get(query_kind)
        if not sql_tpl:
            raise ValueError(f"No SQL found for custom query kind {query_kind}")

        query = sql_tpl.replace("{table}", full_name)
        params: Optional[list[Any]] = None
        rows_written_expected = 0

        # Build parameters based on query kind
        params = self._build_custom_params(
            query_kind, query, worker_id, manager, profile, state
        )
        if query_kind in ("INSERT", "UPDATE"):
            rows_written_expected = 1

        try:
            # Annotate query with UB_KIND marker for server-side stats tracking
            # (Snowflake QUERY_HISTORY and Postgres pg_stat_statements)
            query = annotate_query_for_sf_kind(query, query_kind)

            if is_read:
                result, info = await pool.execute_query_with_info(
                    query, params=params, fetch=True
                )
                rows_read = len(result or [])
                sf_rowcount = info.get("rowcount")
            else:
                _, info = await pool.execute_query_with_info(
                    query, params=params, fetch=False
                )
                rows_read = 0
                sf_rowcount = info.get("rowcount")

            sf_execution_ms = info.get("total_elapsed_time_ms")
            app_elapsed_ms = (time.perf_counter() - start_perf) * 1000.0

            counted = False
            async with self._metrics_lock:
                if int(self._metrics_epoch) == int(epoch_at_start):
                    counted = True
                    self.metrics.total_operations += 1
                    self.metrics.successful_operations += 1
                    self._latencies_ms.append(app_elapsed_ms)

                    if (
                        self._find_max_step_collecting
                        and query_kind in self._find_max_step_ops_by_kind
                    ):
                        self._find_max_step_ops_by_kind[query_kind] += 1
                        self._find_max_step_lat_by_kind_ms[query_kind].append(
                            app_elapsed_ms
                        )

                    if is_read:
                        self.metrics.read_metrics.count += 1
                        self.metrics.read_metrics.success_count += 1
                        self.metrics.read_metrics.total_duration_ms += app_elapsed_ms
                        self.metrics.rows_read += int(rows_read)
                    else:
                        rows_written = (
                            int(sf_rowcount)
                            if sf_rowcount is not None
                            else int(rows_written_expected)
                        )
                        self.metrics.write_metrics.count += 1
                        self.metrics.write_metrics.success_count += 1
                        self.metrics.write_metrics.total_duration_ms += app_elapsed_ms
                        self.metrics.rows_written += rows_written

                    # Latency breakdown (execution vs network overhead)
                    if sf_execution_ms is not None and sf_execution_ms >= 0:
                        self._latency_sf_execution_ms.append(sf_execution_ms)
                        network_overhead = max(0.0, app_elapsed_ms - sf_execution_ms)
                        self._latency_network_overhead_ms.append(network_overhead)

            if counted and not warmup:
                if is_read:
                    self._lat_read_ms.append(app_elapsed_ms)
                else:
                    self._lat_write_ms.append(app_elapsed_ms)
                self._lat_by_kind_ms[query_kind].append(app_elapsed_ms)

                if query_kind == "POINT_LOOKUP":
                    self._point_lookup_count += 1
                elif query_kind == "RANGE_SCAN":
                    self._range_scan_count += 1
                elif query_kind == "INSERT":
                    self._insert_count += 1
                elif query_kind == "UPDATE":
                    self._update_count += 1

        except Exception as e:
            app_elapsed_ms = (time.perf_counter() - start_perf) * 1000.0

            category = classify_sql_error(e)
            async with self._metrics_lock:
                if int(self._metrics_epoch) == int(epoch_at_start):
                    self.metrics.total_operations += 1
                    self.metrics.failed_operations += 1

                    if is_read:
                        self.metrics.read_metrics.count += 1
                        self.metrics.read_metrics.error_count += 1
                    else:
                        self.metrics.write_metrics.count += 1
                        self.metrics.write_metrics.error_count += 1

                    if (
                        self._find_max_step_collecting
                        and query_kind in self._find_max_step_ops_by_kind
                    ):
                        self._find_max_step_ops_by_kind[query_kind] += 1
                        self._find_max_step_errors_by_kind[query_kind] += 1

                    self._sql_error_categories[category] = (
                        self._sql_error_categories.get(category, 0) + 1
                    )

    def _build_custom_params(
        self,
        query_kind: str,
        query: str,
        worker_id: int,
        manager: "TableManager",
        profile: Optional["TableProfile"],
        state: TableRuntimeState,
    ) -> list[Any]:
        """Build parameters for a custom query."""

        def _choose_id() -> Any:
            if profile and profile.id_column:
                pooled = self._next_from_pool(worker_id, "KEY", profile.id_column)
                if pooled is not None:
                    return pooled
                if profile.id_min is not None and profile.id_max is not None:
                    return random.randint(profile.id_min, profile.id_max)
            raise ValueError("Cannot choose key value")

        def _count_placeholders(sql: str) -> int:
            q_count = sql.count("?")
            if q_count > 0:
                return q_count
            pg_matches = re.findall(r"\$\d+", sql)
            return len(pg_matches)

        def _new_value_for(col_upper: str) -> Any:
            col_type_raw = manager.config.columns.get(
                col_upper
            ) or manager.config.columns.get(col_upper.lower())
            typ = str(col_type_raw or "").upper()

            if "TIMESTAMP" in typ:
                return datetime.now(UTC)
            if "DATE" in typ:
                return datetime.now(UTC).date()
            if any(t in typ for t in ("NUMBER", "INT", "DECIMAL")):
                return random.randint(1, 1_000_000)
            return f"TEST_{random.randint(1, 1_000_000)}"

        if query_kind == "POINT_LOOKUP":
            return [_choose_id()]

        elif query_kind == "RANGE_SCAN":
            ph = _count_placeholders(query)
            if ph == 1:
                if profile and profile.time_column:
                    pooled = self._next_from_pool(
                        worker_id, "RANGE", profile.time_column
                    )
                    if pooled is not None:
                        return [pooled]
                    if profile.time_max is not None:
                        return [profile.time_max - timedelta(days=7)]
                raise ValueError("Range scan expects time column")
            else:
                start_id = _choose_id()
                return [start_id, start_id]

        elif query_kind == "INSERT":
            ph = _count_placeholders(query)
            if ph <= 0:
                raise ValueError("INSERT SQL must use placeholders")

            # Get insert columns from template config
            tpl_cfg = getattr(self, "_template_config", None)
            insert_cols: list[str] = []
            if isinstance(tpl_cfg, dict):
                ai_cfg = tpl_cfg.get("ai_workload")
                if isinstance(ai_cfg, dict) and isinstance(
                    ai_cfg.get("insert_columns"), list
                ):
                    insert_cols = [
                        str(c).upper()
                        for c in ai_cfg.get("insert_columns")
                        if str(c).strip()
                    ]

            cols = insert_cols or [
                str(c).upper() for c in manager.config.columns.keys()
            ]
            cols = cols[:ph]

            params = []
            for c in cols:
                c_upper = c.upper()
                if (
                    profile
                    and profile.id_column
                    and c_upper == str(profile.id_column).upper()
                ):
                    col_type_raw = manager.config.columns.get(
                        c_upper
                    ) or manager.config.columns.get(c_upper.lower())
                    col_type = str(col_type_raw or "").upper()
                    if any(t in col_type for t in ("NUMBER", "INT", "DECIMAL")):
                        # Use per-worker insert sequences to avoid PK conflicts
                        if state.insert_id_seqs is None:
                            state.insert_id_seqs = {}
                        if worker_id not in state.insert_id_seqs:
                            # Partition ID space by worker
                            # Estimate range based on test duration:
                            # - 1000 inserts/sec max (conservative)
                            # - 10x safety factor
                            # - Minimum 100K for short tests
                            tpl_cfg = getattr(self, "_template_config", None) or {}
                            duration = (tpl_cfg.get("warmup") or 30) + (
                                tpl_cfg.get("duration") or 120
                            )
                            range_size = max(duration * 1000 * 10, 100_000)
                            base = (profile.id_max or 0) + 1
                            start_id = base + (worker_id * range_size)
                            state.insert_id_seqs[worker_id] = count(start_id)
                        params.append(next(state.insert_id_seqs[worker_id]))
                    else:
                        params.append(str(uuid4()))
                    continue
                params.append(_new_value_for(c_upper))
            return params

        elif query_kind == "UPDATE":
            target_id = _choose_id()
            ph = _count_placeholders(query)
            if ph == 1:
                return [target_id]
            else:
                # Get update columns from template config
                tpl_cfg = getattr(self, "_template_config", None)
                update_cols: list[str] = []
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

                set_col = update_cols[0] if update_cols else None
                new_val = _new_value_for(set_col) if set_col else f"TEST_{uuid4()}"
                return [new_val, target_id]

        return []
