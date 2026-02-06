"""
Utility functions for orchestrator.

Contains helper functions for worker management and process handling.
"""

from __future__ import annotations

import asyncio
import logging
import math
import shutil
import sys
from typing import Any

logger = logging.getLogger(__name__)


def uv_available() -> str | None:
    """Check if uv is available and return the path, or None if not found."""
    uv_bin = shutil.which("uv")
    return uv_bin


def build_worker_targets(
    total_target: int,
    worker_group_count: int,
    *,
    per_worker_cap: int | None = None,
    min_threads_per_worker: int | None = None,
    max_threads_per_worker: int | None = None,
    load_mode: str | None = None,
    target_qps_total: float | None = None,
) -> tuple[int, dict[str, dict[str, Any]]]:
    """
    Distribute total_target threads across workers using pack strategy.

    Algorithm (Pack Strategy):
    - Fill workers to max_threads_per_worker first
    - Last worker gets the remainder
    - Example: 100 threads, 7 workers, max 15 -> 6@15 + 1@10

    Args:
        total_target: Total threads to distribute.
        worker_group_count: Number of workers.
        per_worker_cap: Optional per-worker ceiling (clamps total if exceeded).
        min_threads_per_worker: Optional per-worker floor (clamps total if below).
        max_threads_per_worker: Optional per-worker ceiling (takes precedence over per_worker_cap).
        load_mode: Optional load mode (if "QPS", includes per-worker QPS target).
        target_qps_total: Optional total QPS target (distributed evenly in QPS mode).

    Returns:
        Tuple of (effective_total, targets_dict) where targets_dict is:
        {"worker-0": {"target_threads": N, "worker_group_id": 0, ...}, ...}
    """
    target_total = max(0, int(total_target))
    worker_count = max(1, int(worker_group_count))

    effective_cap = per_worker_cap
    if max_threads_per_worker is not None:
        effective_cap = (
            min(int(max_threads_per_worker), int(per_worker_cap))
            if per_worker_cap is not None
            else int(max_threads_per_worker)
        )
    if effective_cap is not None and int(effective_cap) > 0:
        max_total = int(effective_cap) * worker_count
        if target_total > max_total:
            logger.warning(
                "Target %d exceeds per-worker cap; clamping to %d",
                target_total,
                max_total,
            )
            target_total = max_total

    if min_threads_per_worker is not None and int(min_threads_per_worker) > 0:
        min_total = int(min_threads_per_worker) * worker_count
        if target_total < min_total:
            logger.warning(
                "Target %d below min_threads_per_worker floor; clamping to %d",
                target_total,
                min_total,
            )
            target_total = min_total

    per_worker_qps = None
    if load_mode == "QPS" and target_qps_total is not None:
        per_worker_qps = float(target_qps_total) / float(worker_count)

    targets: dict[str, dict[str, Any]] = {}

    # Pack strategy: fill workers to effective_cap, last worker gets remainder
    if effective_cap is not None and int(effective_cap) > 0:
        cap = int(effective_cap)
        remaining = target_total
        for idx in range(worker_count):
            # Fill to cap, or take what's left
            target = min(cap, remaining)
            remaining -= target
            entry: dict[str, Any] = {
                "target_threads": int(target),
                "worker_group_id": int(idx),
            }
            if per_worker_qps is not None:
                entry["target_qps"] = float(per_worker_qps)
            targets[f"worker-{idx}"] = entry
    else:
        # No cap - balance evenly (original behavior)
        base = target_total // worker_count
        remainder = target_total % worker_count
        for idx in range(worker_count):
            target = base + (1 if idx < remainder else 0)
            entry = {
                "target_threads": int(target),
                "worker_group_id": int(idx),
            }
            if per_worker_qps is not None:
                entry["target_qps"] = float(per_worker_qps)
            targets[f"worker-{idx}"] = entry

    return target_total, targets


async def stream_worker_output(
    proc: asyncio.subprocess.Process,
    worker_id: int,
    run_id: str,
) -> None:
    """Stream worker stdout/stderr to console in real-time.
    
    NOTE: We print directly instead of using logger.log() to avoid duplicate
    entries in TEST_LOGS - workers already persist their own logs via
    TestLogQueueHandler.
    """

    async def _stream_pipe(stream: asyncio.StreamReader | None) -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode().rstrip()
            if text:
                print(f"[worker-{worker_id}] {text}", file=sys.stderr)

    tasks = []
    if proc.stdout:
        tasks.append(_stream_pipe(proc.stdout))
    if proc.stderr:
        tasks.append(_stream_pipe(proc.stderr))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
