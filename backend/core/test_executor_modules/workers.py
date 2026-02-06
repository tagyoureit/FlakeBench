"""
Worker management for test execution.

Handles worker lifecycle, warmup, and phase transitions.
"""

import asyncio
import logging
from datetime import datetime, UTC
from typing import Any, Optional

logger = logging.getLogger(__name__)


class WorkerMixin:
    """Mixin providing worker management functionality."""

    # Expected attributes from TestExecutor
    scenario: Any
    _stop_event: asyncio.Event
    _metrics_lock: asyncio.Lock
    _metrics_epoch: int
    _measurement_active: bool
    metrics: Any
    _benchmark_query_tag: str | None
    _benchmark_query_tag_running: str | None

    async def _warmup(self):
        """Execute warmup period."""
        warmup_workers = [
            asyncio.create_task(self._worker(i, warmup=True))
            for i in range(min(5, self.scenario.total_threads))
        ]
        try:
            await asyncio.sleep(self.scenario.warmup_seconds)
        finally:
            self._stop_event.set()
            for t in warmup_workers:
                try:
                    t.cancel()
                except Exception:
                    pass
            await asyncio.gather(*warmup_workers, return_exceptions=True)
            self._stop_event.clear()

    async def _transition_to_measurement_phase(self) -> None:
        """
        Transition from warmup to measurement phase.

        Updates the Snowflake QUERY_TAG from :phase=WARMUP to :phase=RUNNING.
        """
        running_tag = getattr(self, "_benchmark_query_tag_running", None)
        if not running_tag:
            return

        self._benchmark_query_tag = str(running_tag)

        pool = getattr(self, "_snowflake_pool_override", None)
        if pool is None:
            logger.warning(
                "No pool available for QUERY_TAG update during phase transition"
            )
            return
        if not hasattr(pool, "update_query_tag"):
            logger.warning(
                "Pool does not support update_query_tag method; QUERY_TAG not updated"
            )
            return
        try:
            updated = await pool.update_query_tag(str(running_tag))
            if updated == 0:
                logger.warning(
                    "QUERY_TAG update returned 0 connections; pool may have no active connections"
                )
            else:
                logger.info(
                    "Transitioned to measurement phase: QUERY_TAG updated on %d connections",
                    int(updated),
                )
        except Exception as e:
            logger.warning("Failed to update QUERY_TAG on pool connections: %s", str(e))

    async def _controlled_worker(
        self,
        *,
        worker_id: int,
        warmup: bool,
        stop_signal: asyncio.Event,
    ) -> None:
        """
        Worker loop with a per-worker stop signal (used for QPS mode scale-down).

        Unlike `_worker`, this never applies per-worker rate limiting. QPS mode
        controls offered load via the number of active workers.
        """
        operations_executed = 0
        target_ops = self.scenario.operations_per_connection
        effective_warmup = bool(warmup)

        try:
            while not self._stop_event.is_set():
                if stop_signal.is_set():
                    break

                if target_ops and operations_executed >= target_ops:
                    break

                effective_warmup = bool(warmup) and not bool(self._measurement_active)
                await self._execute_operation(worker_id, effective_warmup)
                operations_executed += 1

                if stop_signal.is_set():
                    break

                if self.scenario.think_time_ms > 0:
                    await asyncio.sleep(self.scenario.think_time_ms / 1000.0)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not effective_warmup:
                logger.error("Worker %s error: %s", worker_id, e)
                async with self._metrics_lock:
                    self.metrics.failed_operations += 1

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
                if target_ops and operations_executed >= target_ops:
                    break

                await self._execute_operation(worker_id, warmup)
                operations_executed += 1

                if self.scenario.think_time_ms > 0:
                    await asyncio.sleep(self.scenario.think_time_ms / 1000.0)

                if self.scenario.target_qps:
                    await asyncio.sleep(1.0 / self.scenario.target_qps)

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if not warmup:
                logger.error(f"Worker {worker_id} error: {e}")
                async with self._metrics_lock:
                    self.metrics.failed_operations += 1

    async def _execute_operation(self, worker_id: int, warmup: bool = False):
        """
        Execute a single operation.

        NOTE: All workloads now use CUSTOM execution path exclusively.
        """
        await self._execute_custom(worker_id, warmup)
