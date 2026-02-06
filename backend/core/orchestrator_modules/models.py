"""
Data models for orchestrator.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from backend.core.postgres_stats import (
        PgCapabilities,
        PgStatDelta,
        PgStatSnapshot,
    )


@dataclass
class RunContext:
    """Context for an active run managed by the orchestrator."""

    run_id: str
    worker_group_count: int
    template_id: str
    scenario_config: dict[str, Any]
    poll_task: asyncio.Task | None = None
    worker_procs: list[asyncio.subprocess.Process] = field(default_factory=list)
    worker_stream_tasks: list[asyncio.Task] = field(default_factory=list)
    started_at: datetime | None = None
    stopping: bool = False
    log_queue: asyncio.Queue | None = None
    log_handler: "logging.Handler | None" = None
    log_drain_task: asyncio.Task | None = None
    did_resume_warehouse: bool = False
    # PostgreSQL statistics for enrichment (3-point capture)
    pg_capabilities: "PgCapabilities | None" = None
    pg_snapshot_before_warmup: "PgStatSnapshot | None" = None
    pg_snapshot_after_warmup: "PgStatSnapshot | None" = None
    pg_snapshot_after_measurement: "PgStatSnapshot | None" = None
    pg_delta_warmup: "PgStatDelta | None" = None  # warmup phase only
    pg_delta_measurement: "PgStatDelta | None" = None  # measurement phase only
    pg_delta_total: "PgStatDelta | None" = None  # warmup + measurement


# Import logging at runtime to avoid circular imports
import logging
