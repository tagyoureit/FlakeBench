"""
Worker management for test executor.
"""

import asyncio
import logging

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from backend.models import WorkloadType

logger = logging.getLogger(__name__)


class WorkersMixin:
    """Mixin providing worker management functionality for TestExecutor."""

    if TYPE_CHECKING:

        async def _execute_read(self, worker_id: int, warmup: bool = False) -> None: ...

        async def _execute_write(
            self, worker_id: int, warmup: bool = False
        ) -> None: ...

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

        Args:
            worker_id: Unique identifier for this worker
        """
        from backend.models import WorkloadType

        logger.debug("Worker %d started", worker_id)

        while not self._stop_event.is_set():
            try:
                workload_type = self.scenario.workload_type

                if workload_type == WorkloadType.READ_ONLY:
                    await self._execute_read(worker_id)
                elif workload_type == WorkloadType.WRITE_ONLY:
                    await self._execute_write(worker_id)
                elif workload_type == WorkloadType.CUSTOM:
                    await self._execute_custom(worker_id)
                elif workload_type in (
                    WorkloadType.READ_HEAVY,
                    WorkloadType.WRITE_HEAVY,
                    WorkloadType.MIXED,
                ):
                    await self._execute_mixed(worker_id, workload_type)
                else:
                    # Default to mixed workload
                    await self._execute_mixed(worker_id, WorkloadType.MIXED)

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

        Args:
            worker_id: Unique identifier for this worker
            warmup: Whether this worker is in warmup phase
            stop_signal: Optional event to signal this specific worker to stop
        """
        from backend.models import WorkloadType

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

                workload_type = self.scenario.workload_type

                if workload_type == WorkloadType.READ_ONLY:
                    await self._execute_read(worker_id, warmup=is_warmup_op)
                elif workload_type == WorkloadType.WRITE_ONLY:
                    await self._execute_write(worker_id, warmup=is_warmup_op)
                elif workload_type == WorkloadType.CUSTOM:
                    await self._execute_custom(worker_id, warmup=is_warmup_op)
                elif workload_type in (
                    WorkloadType.READ_HEAVY,
                    WorkloadType.WRITE_HEAVY,
                    WorkloadType.MIXED,
                ):
                    await self._execute_mixed(
                        worker_id, workload_type, warmup=is_warmup_op
                    )
                else:
                    await self._execute_mixed(
                        worker_id, WorkloadType.MIXED, warmup=is_warmup_op
                    )

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

    async def _execute_mixed(
        self,
        worker_id: int,
        workload_type: "WorkloadType",
        warmup: bool = False,
    ) -> None:
        """
        Execute a mixed workload operation based on workload type ratios.

        Args:
            worker_id: Worker identifier
            workload_type: Type of mixed workload
            warmup: Whether this is a warmup operation
        """
        import random
        from backend.models import WorkloadType

        # Determine read/write ratio based on workload type
        if workload_type == WorkloadType.READ_HEAVY:
            read_ratio = 0.8
        elif workload_type == WorkloadType.WRITE_HEAVY:
            read_ratio = 0.2
        else:  # MIXED
            read_ratio = 0.5

        if random.random() < read_ratio:
            await self._execute_read(worker_id, warmup=warmup)
        else:
            await self._execute_write(worker_id, warmup=warmup)

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
