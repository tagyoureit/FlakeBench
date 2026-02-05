"""
Worker management for test executor.

NOTE: All workloads now use CUSTOM execution path exclusively.
Legacy workload types (READ_ONLY, WRITE_ONLY, MIXED, etc.) are no longer
supported at runtime. Templates are normalized to CUSTOM with explicit
query percentages during save.
"""

import asyncio
import logging

from typing import TYPE_CHECKING, Any, Optional

logger = logging.getLogger(__name__)


class WorkersMixin:
    """Mixin providing worker management functionality for TestExecutor."""

    if TYPE_CHECKING:

        async def _execute_custom(
            self, worker_id: int, warmup: bool = False
        ) -> None: ...

    # These attributes are defined in the main TestExecutor class
    scenario: Any
    _stop_event: asyncio.Event
    _metrics_epoch: int
    _measurement_active: bool
    workers: list[asyncio.Task]

    async def _worker(self, worker_id: int) -> None:
        """
        Worker task that executes operations until stopped.

        All workloads use CUSTOM execution which handles query mix
        (POINT_LOOKUP, RANGE_SCAN, INSERT, UPDATE) via weighted selection.

        Args:
            worker_id: Unique identifier for this worker
        """
        logger.debug("Worker %d started", worker_id)

        while not self._stop_event.is_set():
            try:
                await self._execute_custom(worker_id)

                # Think time between operations
                if self.scenario.think_time_ms > 0:
                    await asyncio.sleep(self.scenario.think_time_ms / 1000.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Worker %d operation error: %s", worker_id, e)

        logger.debug("Worker %d stopped", worker_id)

    async def _controlled_worker(
        self,
        worker_id: int,
        *,
        warmup: bool = False,
        stop_signal: Optional[asyncio.Event] = None,
    ) -> None:
        """
        Worker task for QPS/FIND_MAX modes with external stop signal.

        All workloads use CUSTOM execution which handles query mix
        (POINT_LOOKUP, RANGE_SCAN, INSERT, UPDATE) via weighted selection.

        Args:
            worker_id: Unique identifier for this worker
            warmup: Whether this worker is in warmup phase
            stop_signal: Optional event to signal this specific worker to stop
        """
        logger.debug("Controlled worker %d started (warmup=%s)", worker_id, warmup)

        while not self._stop_event.is_set():
            # Check worker-specific stop signal
            if stop_signal is not None and stop_signal.is_set():
                break

            try:
                # Determine if this operation counts as measurement
                # Post-warmup operations from workers spawned during warmup should
                # still count as measurement once the measurement window begins
                is_warmup_op = warmup and not self._measurement_active

                await self._execute_custom(worker_id, warmup=is_warmup_op)

                # Think time between operations
                if self.scenario.think_time_ms > 0:
                    await asyncio.sleep(self.scenario.think_time_ms / 1000.0)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug("Controlled worker %d operation error: %s", worker_id, e)

        logger.debug("Controlled worker %d stopped", worker_id)

    async def _warmup(self) -> None:
        """
        Execute warmup phase before measurement.

        Spawns workers that run for warmup_seconds, then stops them.
        Metrics from warmup are not counted in final results.
        """
        warmup_seconds = self.scenario.warmup_seconds
        if warmup_seconds <= 0:
            return

        logger.info("Starting warmup phase (%ds)...", warmup_seconds)

        # Spawn warmup workers
        warmup_workers: list[asyncio.Task] = []
        for worker_id in range(self.scenario.total_threads):
            task = asyncio.create_task(self._controlled_worker(worker_id, warmup=True))
            warmup_workers.append(task)

        # Run for warmup duration
        await asyncio.sleep(warmup_seconds)

        # Stop warmup workers by setting stop event temporarily
        # We use a different approach: cancel the warmup tasks
        for task in warmup_workers:
            task.cancel()

        # Wait for all warmup tasks to finish
        await asyncio.gather(*warmup_workers, return_exceptions=True)

        logger.info("Warmup phase complete")

    async def _transition_to_measurement_phase(self) -> None:
        """
        Transition from warmup to measurement phase.

        Updates query tags for Snowflake to distinguish warmup vs measurement queries.
        """
        # This is called after warmup completes to update any session state
        # that distinguishes warmup from measurement queries
        logger.debug("Transitioning to measurement phase")

        # Update benchmark query tag if configured
        if hasattr(self, "_benchmark_query_tag") and self._benchmark_query_tag:
            # The query tag is already set per-pool; this is a no-op for now
            # Future: could update session variable to indicate phase
            pass
