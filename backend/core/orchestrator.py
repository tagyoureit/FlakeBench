from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, Optional

from backend.config import settings
from backend.connectors import snowflake_pool
from backend.models.test_config import TestScenario

logger = logging.getLogger(__name__)

class OrchestratorService:
    """
    Central control plane for benchmark runs.
    Replaces the in-memory TestRegistry with a Snowflake-backed state machine.
    """

    def __init__(self) -> None:
        self._pool = snowflake_pool.get_default_pool()
        self._background_tasks: set[asyncio.Task] = set()

    async def create_run(
        self, 
        template_id: str, 
        template_config: dict[str, Any],
        scenario: TestScenario
    ) -> str:
        """
        Creates a new parent run in PREPARED state.
        Writes to RUN_STATUS table.
        
        Args:
            template_id: The source template ID
            template_config: The full resolved configuration
            scenario: The parsed scenario model
            
        Returns:
            str: The newly created RUN_ID (UUID)
        """
        import uuid
        run_id = str(uuid.uuid4())
        
        # TODO: Insert into RUN_STATUS via SQL
        # INSERT INTO RUN_STATUS (run_id, status, phase, ...)
        logger.info(f"Created run {run_id} for template {template_id}")
        return run_id

    async def start_run(self, run_id: str) -> None:
        """
        Transitions run to RUNNING and spawns workers.
        """
        # 1. Update RUN_STATUS to RUNNING
        # 2. Spawn workers (Local subprocess or SPCS)
        logger.info(f"Starting run {run_id}")
        pass

    async def stop_run(self, run_id: str) -> None:
        """
        Signals the run to stop.
        """
        # 1. Insert STOP event into RUN_CONTROL_EVENTS
        # 2. Update RUN_STATUS to STOPPING
        logger.info(f"Stopping run {run_id}")
        pass

    async def _poll_loop(self) -> None:
        """
        Background loop to:
        1. Aggregate metrics from NODE_METRICS_SNAPSHOTS
        2. Check WORKER_HEARTBEATS for dead nodes
        3. Manage phase transitions (WARMUP -> MEASUREMENT -> COMPLETED)
        """
        while True:
            try:
                # TODO: Implement polling logic
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Orchestrator poll error: {e}")
                await asyncio.sleep(5.0)

# Global singleton instance
orchestrator = OrchestratorService()
