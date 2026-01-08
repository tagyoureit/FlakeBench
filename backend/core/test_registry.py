"""
Test Registry

Runs template-based tests in-process and provides:
- lifecycle management (start/stop)
- live metrics pubsub for WebSocket streaming
- persistence hooks to Snowflake results tables
"""

from __future__ import annotations

import asyncio
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Optional

from backend.config import settings
from backend.connectors.snowflake_pool import SnowflakeConnectionPool
from backend.connectors import snowflake_pool
from backend.core.results_store import (
    insert_metrics_snapshot,
    insert_query_executions,
    insert_test_logs,
    insert_test_start,
    enrich_query_executions_from_query_history,
    update_test_overhead_percentiles,
    update_test_result_final,
)
from backend.core.test_log_stream import CURRENT_TEST_ID, TestLogQueueHandler
from backend.core.test_executor import TestExecutor
from backend.models.test_config import (
    TableConfig,
    TableType,
    TestScenario,
    WorkloadType,
)
from backend.models.test_result import TestStatus

logger = logging.getLogger(__name__)


def _default_columns() -> dict[str, str]:
    # Minimal schema aligned with the app's query patterns.
    return {
        "id": "NUMBER",
        "data": "VARCHAR(255)",
        "timestamp": "TIMESTAMP_NTZ",
    }


def _parse_csv(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _workload_type(value: Any) -> WorkloadType:
    if not value:
        return WorkloadType.MIXED
    raw = str(value).strip().lower()
    mapping = {
        "read_only": "read_only",
        "write_only": "write_only",
        "read_heavy": "read_heavy",
        "write_heavy": "write_heavy",
        "mixed": "mixed",
        "custom": "custom",
    }
    return WorkloadType(mapping.get(raw, "mixed"))


def _table_type(value: Any) -> TableType:
    if not value:
        return TableType.STANDARD
    raw = str(value).strip().lower()
    return TableType(raw)


@dataclass
class RunningTest:
    test_id: str
    template_id: str
    template_name: str
    template_config: dict[str, Any]
    scenario: TestScenario
    executor: TestExecutor
    task: Optional[asyncio.Task]
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    status: str = "PREPARED"
    last_payload: Optional[dict[str, Any]] = None
    subscribers: set[asyncio.Queue] = field(default_factory=set)
    snowflake_pool: Optional[SnowflakeConnectionPool] = None
    log_buffer: deque[dict[str, Any]] = field(
        default_factory=lambda: deque(maxlen=1000)
    )


class TestRegistry:
    def __init__(self) -> None:
        self._tests: dict[str, RunningTest] = {}
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task] = set()

    def _track_task(self, task: asyncio.Task) -> None:
        self._background_tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            self._background_tasks.discard(task)
            # Always retrieve exceptions so asyncio doesn't emit
            # "Task exception was never retrieved" warnings.
            try:
                exc = t.exception()
            except asyncio.CancelledError:
                return
            except Exception:
                return
            if exc is not None:
                logger.debug("Background task failed: %s", exc, exc_info=exc)

        task.add_done_callback(_done)

    async def shutdown(self, *, timeout_seconds: float = 5.0) -> None:
        """
        Best-effort shutdown for dev reloads and graceful termination.

        Cancels in-flight benchmark tasks (and any tracked background tasks) so
        uvicorn --reload doesn't hang on "waiting for background tasks".
        """

        async with self._lock:
            running_tests = list(self._tests.values())
            bg = list(self._background_tasks)

        # Cancel in-flight test runner tasks first.
        for t in running_tests:
            try:
                if t.task is not None:
                    t.task.cancel()
            except Exception:
                pass

        # Cancel tracked background tasks (metrics persistence / pubsub).
        for task in bg:
            try:
                task.cancel()
            except Exception:
                pass

        async def _await_all() -> None:
            runner_tasks = [t.task for t in running_tests if t.task is not None]
            await asyncio.gather(
                *runner_tasks,
                *bg,
                return_exceptions=True,
            )

        try:
            await asyncio.wait_for(_await_all(), timeout=timeout_seconds)
        except TimeoutError:
            logger.warning(
                "Registry shutdown timed out after %.1fs; forcing continuation",
                timeout_seconds,
            )

        # Close any per-test pools (best effort).
        for t in running_tests:
            pool = t.snowflake_pool
            if pool is None:
                continue
            try:
                await pool.close_all()
            except Exception:
                pass

        async with self._lock:
            self._tests.clear()
            self._background_tasks.clear()

    async def get(self, test_id: str) -> Optional[RunningTest]:
        async with self._lock:
            return self._tests.get(test_id)

    async def subscribe(self, test_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=50)
        async with self._lock:
            test = self._tests.get(test_id)
            if test is None:
                raise KeyError(test_id)
            test.subscribers.add(q)
            if test.last_payload is not None:
                try:
                    q.put_nowait(test.last_payload)
                except Exception:
                    pass
            if test.log_buffer:
                # Prime a newly connected dashboard with recent logs so a reload doesn't
                # lose context mid-run.
                try:
                    q.put_nowait(
                        {
                            "kind": "log_batch",
                            "test_id": test_id,
                            "logs": list(test.log_buffer)[-200:],
                        }
                    )
                except Exception:
                    pass
        return q

    async def unsubscribe(self, test_id: str, q: asyncio.Queue) -> None:
        async with self._lock:
            test = self._tests.get(test_id)
            if test is not None:
                test.subscribers.discard(q)

    async def _publish(self, test_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            test = self._tests.get(test_id)
            if test is None:
                return
            test.last_payload = payload
            subscribers = list(test.subscribers)

        for q in subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop if a client can't keep up.
                continue

    async def _publish_log(self, test_id: str, payload: dict[str, Any]) -> None:
        """
        Publish a log payload to subscribers without overwriting last metrics payload.
        """
        async with self._lock:
            test = self._tests.get(test_id)
            if test is None:
                return
            try:
                test.log_buffer.append(payload)
            except Exception:
                pass
            subscribers = list(test.subscribers)

        for q in subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                continue

    async def _drain_test_logs(
        self, *, test_id: str, q: asyncio.Queue, flush_batch_size: int = 200
    ) -> None:
        """
        Drain log events from a queue, stream them to dashboards, and persist to Snowflake.
        """
        pending_rows: list[dict[str, Any]] = []
        try:
            while True:
                event = await q.get()
                if event is None:
                    break

                try:
                    await self._publish_log(test_id, event)
                except Exception:
                    pass

                pending_rows.append(
                    {
                        "log_id": event.get("log_id"),
                        "test_id": event.get("test_id") or test_id,
                        "seq": event.get("seq"),
                        "timestamp": event.get("timestamp"),
                        "level": event.get("level"),
                        "logger": event.get("logger"),
                        "message": event.get("message"),
                        "exception": event.get("exception"),
                    }
                )

                if len(pending_rows) >= flush_batch_size:
                    try:
                        await insert_test_logs(rows=pending_rows)
                    except Exception as e:
                        logger.debug(
                            "Failed to persist TEST_LOGS for %s: %s", test_id, e
                        )
                    finally:
                        pending_rows.clear()
        finally:
            if pending_rows:
                try:
                    await insert_test_logs(rows=pending_rows)
                except Exception as e:
                    logger.debug(
                        "Failed to persist final TEST_LOGS for %s: %s", test_id, e
                    )

    async def start_from_template(
        self, template_id: str, *, auto_start: bool = True
    ) -> RunningTest:
        template = await self._load_template(template_id)
        template_name = template["template_name"]
        template_config = template["config"]

        scenario = self._scenario_from_template_config(template_name, template_config)
        executor = TestExecutor(scenario)
        # Attach template context for optional AI/pool-based workload adjustments.
        executor._template_id = template_id  # type: ignore[attr-defined]
        executor._template_config = template_config  # type: ignore[attr-defined]

        # Build a dedicated Snowflake pool for this test so warehouse selection doesn't
        # affect other operations.
        warehouse = self._warehouse_from_config(template_config)
        table_type = _table_type(template_config.get("table_type") or "STANDARD")
        is_postgres = table_type in (
            TableType.POSTGRES,
            TableType.SNOWFLAKE_POSTGRES,
            TableType.CRUNCHYDATA,
        )
        if (
            not is_postgres
            and warehouse
            and str(warehouse).upper() == str(settings.SNOWFLAKE_WAREHOUSE).upper()
        ):
            raise ValueError(
                "Template execution warehouse must not match results warehouse (SNOWFLAKE_WAREHOUSE)."
            )
        per_test_pool: SnowflakeConnectionPool | None = None
        if not is_postgres:
            # Template-controlled result cache behavior (Snowflake session parameter).
            # Default to TRUE for backwards compatibility with existing templates.
            raw_use_cached = (
                template_config.get("use_cached_result")
                if isinstance(template_config, dict)
                else None
            )
            if raw_use_cached is None:
                use_cached_result = True
            elif isinstance(raw_use_cached, bool):
                use_cached_result = raw_use_cached
            elif isinstance(raw_use_cached, (int, float)):
                use_cached_result = bool(raw_use_cached)
            elif isinstance(raw_use_cached, str):
                use_cached_result = raw_use_cached.strip().lower() not in {
                    "0",
                    "false",
                    "no",
                    "off",
                }
            else:
                use_cached_result = True

            concurrency = int(scenario.concurrent_connections)
            max_workers = max(1, concurrency)
            max_allowed = int(settings.SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS)
            if max_workers > max_allowed:
                raise ValueError(
                    f"Requested concurrency ({concurrency}) exceeds this node's configured "
                    f"SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS ({max_allowed}). "
                    "For thousands of simulated users, run multiple benchmark workers (multi-process/multi-node) "
                    "or increase SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS."
                )

            bench_executor = ThreadPoolExecutor(
                max_workers=max_workers,
                thread_name_prefix="sf-bench",
            )
            per_test_pool = SnowflakeConnectionPool(
                account=settings.SNOWFLAKE_ACCOUNT,
                user=settings.SNOWFLAKE_USER,
                password=settings.SNOWFLAKE_PASSWORD,
                warehouse=warehouse,
                database=settings.SNOWFLAKE_DATABASE,
                schema=settings.SNOWFLAKE_SCHEMA,
                role=settings.SNOWFLAKE_ROLE,
                # To avoid app-side queueing, match max connections to requested concurrency.
                pool_size=concurrency,
                max_overflow=0,
                timeout=settings.SNOWFLAKE_POOL_TIMEOUT,
                recycle=settings.SNOWFLAKE_POOL_RECYCLE,
                executor=bench_executor,
                owns_executor=True,
                max_parallel_creates=settings.SNOWFLAKE_POOL_MAX_PARALLEL_CREATES,
                connect_login_timeout=settings.SNOWFLAKE_BENCHMARK_CONNECT_LOGIN_TIMEOUT,
                connect_network_timeout=settings.SNOWFLAKE_BENCHMARK_CONNECT_NETWORK_TIMEOUT,
                connect_socket_timeout=settings.SNOWFLAKE_BENCHMARK_CONNECT_SOCKET_TIMEOUT,
                session_parameters={
                    # Prefer explicit TRUE/FALSE strings to match Snowflake's session parameter
                    # convention and avoid driver-specific bool serialization edge cases.
                    "USE_CACHED_RESULT": "TRUE" if use_cached_result else "FALSE",
                },
            )

            # Monkey-patch managers' pool in executor.setup (after they’re created) by
            # setting a private attribute that setup() will use.
            executor._snowflake_pool_override = per_test_pool  # type: ignore[attr-defined]

        test_id = str(executor.test_id)

        async def _runner() -> None:
            await self._run_and_persist(
                test_id=test_id,
                template_id=template_id,
                template_name=template_name,
                template_config=template_config,
                scenario=scenario,
                executor=executor,
                warehouse=warehouse,
                warehouse_size=str(template_config.get("warehouse_size") or ""),
            )

        task: Optional[asyncio.Task] = None
        status_str = "PREPARED"
        if auto_start:
            task = asyncio.create_task(_runner())
            self._track_task(task)
            status_str = "RUNNING"

        running = RunningTest(
            test_id=test_id,
            template_id=template_id,
            template_name=template_name,
            template_config=template_config,
            scenario=scenario,
            executor=executor,
            task=task,
            snowflake_pool=per_test_pool,
            status=status_str,
        )

        async with self._lock:
            self._tests[test_id] = running

        return running

    async def start_prepared(self, test_id: str) -> RunningTest:
        async with self._lock:
            t = self._tests.get(test_id)
            if t is None:
                raise KeyError(test_id)
            if t.task is not None and not t.task.done():
                return t
            # Only allow starting once; if previously completed, reject.
            if str(t.status).upper() not in {"PREPARED", "READY"}:
                raise ValueError(f"Test is not startable (status={t.status})")

            template_id = t.template_id
            template_name = t.template_name
            template_config = t.template_config
            scenario = t.scenario
            executor = t.executor
            warehouse = self._warehouse_from_config(template_config)

        async def _runner() -> None:
            await self._run_and_persist(
                test_id=test_id,
                template_id=template_id,
                template_name=template_name,
                template_config=template_config,
                scenario=scenario,
                executor=executor,
                warehouse=warehouse,
                warehouse_size=str(template_config.get("warehouse_size") or ""),
            )

        task = asyncio.create_task(_runner())
        self._track_task(task)
        async with self._lock:
            t2 = self._tests.get(test_id)
            if t2 is not None:
                t2.task = task
                t2.status = "RUNNING"
        latest = await self.get(test_id)
        if latest is None:
            raise KeyError(test_id)
        return latest

    async def stop(self, test_id: str) -> RunningTest:
        """
        Stop a running test by cancelling its runner task (best effort).
        """
        async with self._lock:
            t = self._tests.get(test_id)
            if t is None:
                raise KeyError(test_id)
            if t.task is None:
                raise ValueError("Test is not running")
            if t.task.done():
                return t
            t.status = "CANCELLING"
            try:
                t.task.cancel()
            except Exception:
                pass
            return t

    async def _run_and_persist(
        self,
        *,
        test_id: str,
        template_id: str,
        template_name: str,
        template_config: dict[str, Any],
        scenario: TestScenario,
        executor: TestExecutor,
        warehouse: Optional[str],
        warehouse_size: Optional[str],
    ) -> None:
        # Attach per-test log capture early so setup/validation errors are visible in the UI.
        log_q: asyncio.Queue = asyncio.Queue(maxsize=2000)
        log_handler: TestLogQueueHandler | None = None
        log_task: asyncio.Task | None = None
        token = CURRENT_TEST_ID.set(test_id)
        root_logger = logging.getLogger()
        log_handler = TestLogQueueHandler(test_id=test_id, queue=log_q)
        root_logger.addHandler(log_handler)
        log_task = asyncio.create_task(self._drain_test_logs(test_id=test_id, q=log_q))
        self._track_task(log_task)

        logs_cleaned = False

        async def _cleanup_logs() -> None:
            nonlocal logs_cleaned
            if logs_cleaned:
                return
            logs_cleaned = True

            try:
                root_logger.removeHandler(log_handler)
            except Exception:
                pass
            try:
                CURRENT_TEST_ID.reset(token)
            except Exception:
                pass
            try:
                # Signal drain task to flush+stop.
                log_q.put_nowait(None)
            except Exception:
                pass
            try:
                await asyncio.wait_for(log_task, timeout=2.0)
            except Exception:
                # Best-effort; don't block shutdown.
                pass

        # Persist start row
        table_cfg = scenario.table_configs[0]
        try:
            await insert_test_start(
                test_id=test_id,
                test_name=f"{template_name}",
                scenario=scenario,
                table_name=table_cfg.name,
                table_type=str(table_cfg.table_type).upper(),
                warehouse=warehouse,
                warehouse_size=warehouse_size or None,
                template_id=template_id,
                template_name=template_name,
                template_config=template_config,
            )
        except Exception:
            await _cleanup_logs()
            raise

        # Mark template usage
        try:
            pool = snowflake_pool.get_default_pool()
            await pool.execute_query(
                f"""
                UPDATE {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.TEST_TEMPLATES
                SET USAGE_COUNT = USAGE_COUNT + 1, LAST_USED_AT = ?
                WHERE TEMPLATE_ID = ?
                """,
                params=[datetime.now(UTC).isoformat(), template_id],
            )
        except Exception as e:
            logger.debug("Failed to increment template usage: %s", e)

        # Stream metrics
        warmup_seconds = int(getattr(scenario, "warmup_seconds", 0) or 0)
        run_seconds = int(getattr(scenario, "duration_seconds", 0) or 0)
        total_expected_seconds = warmup_seconds + run_seconds
        last_payload: dict[str, Any] | None = None

        def _with_phase(
            base_payload: dict[str, Any] | None,
            *,
            phase: str,
            now: datetime | None = None,
        ) -> dict[str, Any]:
            ts = now or datetime.now()
            start = executor.start_time
            elapsed_total = (ts - start).total_seconds() if start else 0.0
            phase_upper = str(phase).upper()
            if total_expected_seconds > 0 and phase_upper not in {
                "PROCESSING",
                "COMPLETED",
            }:
                elapsed_display = min(elapsed_total, float(total_expected_seconds))
            else:
                # During PROCESSING (and the terminal COMPLETED payload), keep counting
                # past the expected end time so UI can show e.g. 95/90.
                elapsed_display = elapsed_total

            payload = dict(base_payload or {})
            payload["timestamp"] = ts.isoformat()
            payload["phase"] = phase
            status_raw = executor.status
            status_val = getattr(status_raw, "value", status_raw)
            payload["status"] = str(status_val).upper()
            payload["timing"] = {
                "warmup_seconds": warmup_seconds,
                "run_seconds": run_seconds,
                "total_expected_seconds": total_expected_seconds,
                "elapsed_total_seconds": float(elapsed_total),
                "elapsed_display_seconds": float(elapsed_display),
            }
            return payload

        def on_metrics(metrics):
            nonlocal last_payload
            payload = metrics.to_websocket_payload()
            # UI wants wall-clock progress across warmup + run (no reset). The
            # metrics object itself resets after warmup to keep measurement-window
            # rates/latency clean, so we add a separate elapsed_total.
            phase = "RUNNING"
            if (
                warmup_seconds > 0
                and getattr(executor, "_measurement_start_time", None) is None
            ):
                phase = "WARMUP"

            payload = _with_phase(payload, phase=phase, now=metrics.timestamp)
            last_payload = payload
            self._track_task(asyncio.create_task(self._publish(test_id, payload)))
            self._track_task(
                asyncio.create_task(
                    insert_metrics_snapshot(test_id=test_id, metrics=metrics)
                )
            )

        executor.set_metrics_callback(on_metrics)

        # Execute
        persisted_query_executions = False
        try:
            ok = await executor.setup()
            if not ok:
                executor.status = TestStatus.FAILED
                result = await executor._build_result()
                await update_test_result_final(test_id=test_id, result=result)
                return

            result = await executor.execute()

            # Execution window is finished; post-processing (Snowflake writes,
            # query-history enrichment, overhead percentiles) can take time.
            await self._publish(
                test_id,
                _with_phase(last_payload, phase="PROCESSING"),
            )

            # Persist per-operation query executions.
            #
            # - If collect_query_history is enabled: persist all operations (warmup + measured).
            # - Otherwise: persist warmup operations only (small volume, useful for troubleshooting).
            try:
                records = executor.get_query_execution_records()
                if records:
                    persist_all = bool(
                        getattr(scenario, "collect_query_history", False)
                    )
                    selected = (
                        records if persist_all else [r for r in records if r.warmup]
                    )
                    if selected:
                        rows = [
                            {
                                "execution_id": r.execution_id,
                                "query_id": r.query_id,
                                "query_text": r.query_text,
                                "start_time": r.start_time.isoformat(),
                                "end_time": r.end_time.isoformat(),
                                "duration_ms": r.duration_ms,
                                "rows_affected": r.rows_affected,
                                "bytes_scanned": r.bytes_scanned,
                                "warehouse": r.warehouse,
                                "success": r.success,
                                "error": r.error,
                                "connection_id": r.connection_id,
                                "custom_metadata": r.custom_metadata,
                                "query_kind": r.query_kind,
                                "worker_id": r.worker_id,
                                "warmup": r.warmup,
                                "app_elapsed_ms": r.app_elapsed_ms,
                            }
                            for r in selected
                        ]
                        await insert_query_executions(test_id=test_id, rows=rows)
                        persisted_query_executions = True
            except Exception as e:
                # Best-effort: do not fail the run if persistence fails.
                logger.warning(
                    "Failed to persist QUERY_EXECUTIONS for %s (check schema migrations): %s",
                    test_id,
                    e,
                )

            # Enrich persisted QUERY_EXECUTIONS with Snowflake timings from QUERY_HISTORY.
            try:
                if getattr(scenario, "collect_query_history", False):
                    await enrich_query_executions_from_query_history(test_id=test_id)
                    await update_test_overhead_percentiles(test_id=test_id)
            except Exception as e:
                logger.debug("Failed to enrich QUERY_EXECUTIONS for %s: %s", test_id, e)

            await update_test_result_final(test_id=test_id, result=result)
        except asyncio.CancelledError:
            # Test was stopped. Record a partial final result as CANCELLED.
            executor.status = TestStatus.CANCELLED
            executor.end_time = datetime.now()
            try:
                result = await executor._build_result()
                await update_test_result_final(test_id=test_id, result=result)
            except Exception:
                pass
            raise
        except Exception as e:
            logger.exception("Test %s crashed: %s", test_id, e)
        finally:
            await _cleanup_logs()

            # Best-effort persistence of QUERY_EXECUTIONS even for CANCELLED/crashed runs.
            # (Previously CANCELLED runs would have zero rows, which is confusing.)
            if not persisted_query_executions:
                try:
                    records = executor.get_query_execution_records()
                    if records:
                        persist_all = bool(
                            getattr(scenario, "collect_query_history", False)
                        )
                        selected = (
                            records if persist_all else [r for r in records if r.warmup]
                        )
                        if selected:
                            rows = [
                                {
                                    "execution_id": r.execution_id,
                                    "query_id": r.query_id,
                                    "query_text": r.query_text,
                                    "start_time": r.start_time.isoformat(),
                                    "end_time": r.end_time.isoformat(),
                                    "duration_ms": r.duration_ms,
                                    "rows_affected": r.rows_affected,
                                    "bytes_scanned": r.bytes_scanned,
                                    "warehouse": r.warehouse,
                                    "success": r.success,
                                    "error": r.error,
                                    "connection_id": r.connection_id,
                                    "custom_metadata": r.custom_metadata,
                                    "query_kind": r.query_kind,
                                    "worker_id": r.worker_id,
                                    "warmup": r.warmup,
                                    "app_elapsed_ms": r.app_elapsed_ms,
                                }
                                for r in selected
                            ]
                            await insert_query_executions(test_id=test_id, rows=rows)
                except Exception as e:
                    logger.debug(
                        "Failed to persist QUERY_EXECUTIONS in finally for %s: %s",
                        test_id,
                        e,
                    )

            # Close per-test pool if present
            pool = getattr(executor, "_snowflake_pool_override", None)
            if pool is not None:
                try:
                    await pool.close_all()
                except Exception:
                    pass

            async with self._lock:
                t = self._tests.get(test_id)
                if t is not None:
                    status_raw = executor.status
                    status_val = getattr(status_raw, "value", status_raw)
                    t.status = str(status_val).upper()

            # Final UI signal: processing is done and the run reached a terminal state.
            await self._publish(
                test_id,
                _with_phase(last_payload, phase="COMPLETED"),
            )

    async def _load_template(self, template_id: str) -> dict[str, Any]:
        pool = snowflake_pool.get_default_pool()
        query = f"""
        SELECT TEMPLATE_ID, TEMPLATE_NAME, CONFIG
        FROM {settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}.TEST_TEMPLATES
        WHERE TEMPLATE_ID = ?
        """
        rows = await pool.execute_query(query, params=[template_id])
        if not rows:
            raise KeyError(template_id)
        _, name, config = rows[0]
        if isinstance(config, str):
            config = json.loads(config)
        return {"template_id": template_id, "template_name": name, "config": config}

    def _warehouse_from_config(self, cfg: dict[str, Any]) -> Optional[str]:
        table_type = _table_type(cfg.get("table_type") or "STANDARD")
        if table_type in (
            TableType.POSTGRES,
            TableType.SNOWFLAKE_POSTGRES,
            TableType.CRUNCHYDATA,
        ):
            return None

        mode = str(cfg.get("warehouse_mode") or "EXISTING").upper()
        if mode == "EXISTING":
            return cfg.get("warehouse_name") or settings.SNOWFLAKE_WAREHOUSE
        # CREATE_NEW not implemented yet; default to configured warehouse for safety.
        return settings.SNOWFLAKE_WAREHOUSE

    def _scenario_from_template_config(
        self, template_name: str, cfg: dict[str, Any]
    ) -> TestScenario:
        table_name = str(cfg.get("table_name") or "benchmark_table")
        db = str(cfg.get("database") or settings.SNOWFLAKE_DATABASE)
        schema = str(cfg.get("schema") or settings.SNOWFLAKE_SCHEMA)

        table_type = _table_type(cfg.get("table_type") or "STANDARD")
        clustering = _parse_csv(cfg.get("clustering_keys"))
        primary_key = _parse_csv(cfg.get("primary_key"))

        indexes_cfg = []
        for idx in cfg.get("indexes", []) if cfg.get("add_indexes") else []:
            indexes_cfg.append(
                {
                    "name": None,
                    "columns": _parse_csv(idx.get("columns")),
                    "include": _parse_csv(idx.get("include")),
                }
            )

        columns = cfg.get("columns") or _default_columns()

        table_config = TableConfig(
            name=table_name,
            table_type=table_type,
            database=db,
            schema_name=schema,
            columns=columns,
            clustering_keys=clustering or None,
            primary_key=primary_key or None,
            indexes=indexes_cfg or None,
            initial_row_count=int(cfg.get("initial_row_count") or 0),
        )

        workload_type = _workload_type(cfg.get("workload_type"))
        custom_queries: list[dict[str, Any]] | None = None
        if workload_type == WorkloadType.CUSTOM:
            # Templates persist the canonical 4-query workload as explicit CUSTOM weights + SQL.
            def _pct(key: str) -> int:
                return int(cfg.get(key) or 0)

            def _sql(key: str) -> str:
                return str(cfg.get(key) or "").strip()

            pct_fields = (
                "custom_point_lookup_pct",
                "custom_range_scan_pct",
                "custom_insert_pct",
                "custom_update_pct",
            )
            total = sum(_pct(k) for k in pct_fields)
            if total != 100:
                raise ValueError(
                    f"Template CUSTOM percentages must sum to 100 (currently {total})."
                )

            items = [
                (
                    "POINT_LOOKUP",
                    "custom_point_lookup_pct",
                    "custom_point_lookup_query",
                ),
                ("RANGE_SCAN", "custom_range_scan_pct", "custom_range_scan_query"),
                ("INSERT", "custom_insert_pct", "custom_insert_query"),
                ("UPDATE", "custom_update_pct", "custom_update_query"),
            ]
            custom_queries = []
            for kind, pct_k, sql_k in items:
                pct = _pct(pct_k)
                sql = _sql(sql_k)
                if pct <= 0:
                    continue
                if not sql:
                    raise ValueError(f"{sql_k} is required when {pct_k} > 0")
                custom_queries.append(
                    {"query_kind": kind, "weight_pct": pct, "sql": sql}
                )

        scenario = TestScenario(
            name=template_name,
            description=str(cfg.get("description") or ""),
            duration_seconds=int(cfg.get("duration") or settings.DEFAULT_TEST_DURATION),
            warmup_seconds=int(cfg.get("warmup") or 0),
            concurrent_connections=int(
                cfg.get("concurrent_connections") or settings.DEFAULT_CONCURRENCY
            ),
            think_time_ms=int(cfg.get("think_time") or 0),
            workload_type=workload_type,
            custom_queries=custom_queries,
            table_configs=[table_config],
        )

        # Collect per-operation query history for template runs so we can:
        # - compute per-query-type latencies
        # - enrich from Snowflake QUERY_HISTORY post-run
        # Warmup operations are also captured (flagged) for troubleshooting.
        scenario.collect_query_history = True

        return scenario


registry = TestRegistry()
