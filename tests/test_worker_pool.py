"""
Unit tests for WorkerPool.

Tests dynamic worker scaling functionality.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.core.worker_pool import WorkerPool


class TestWorkerPoolSpawn:
    """Tests for WorkerPool.spawn_one()."""

    @pytest.mark.asyncio
    async def test_spawn_one_creates_worker(self) -> None:
        """spawn_one creates a worker and returns its ID."""
        workers_created: list[int] = []

        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            workers_created.append(worker_id)
            await stop_signal.wait()

        pool = WorkerPool(worker_factory=mock_worker, min_workers=0, max_workers=10)

        worker_id = await pool.spawn_one(warmup=False)
        # Yield to event loop so worker task starts running
        await asyncio.sleep(0)

        assert worker_id == 0
        assert len(workers_created) == 1
        assert pool.count == 1

        # Cleanup
        await pool.stop_all()

    @pytest.mark.asyncio
    async def test_spawn_increments_worker_id(self) -> None:
        """Each spawn increments the worker ID."""
        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()

        pool = WorkerPool(worker_factory=mock_worker, min_workers=0, max_workers=10)

        id1 = await pool.spawn_one(warmup=False)
        id2 = await pool.spawn_one(warmup=False)
        id3 = await pool.spawn_one(warmup=False)

        assert id1 == 0
        assert id2 == 1
        assert id3 == 2
        assert pool.count == 3

        await pool.stop_all()


class TestWorkerPoolScaleTo:
    """Tests for WorkerPool.scale_to()."""

    @pytest.mark.asyncio
    async def test_scale_to_increases_workers(self) -> None:
        """scale_to spawns workers when target > current count."""
        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()

        pool = WorkerPool(worker_factory=mock_worker, min_workers=0, max_workers=10)

        await pool.scale_to(5, warmup=False)

        assert pool.count == 5
        assert len(pool.running_worker_ids()) == 5

        await pool.stop_all()

    @pytest.mark.asyncio
    async def test_scale_to_decreases_workers(self) -> None:
        """scale_to signals workers to stop when target < current count."""
        stopped_workers: list[int] = []

        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()
            stopped_workers.append(worker_id)

        pool = WorkerPool(worker_factory=mock_worker, min_workers=0, max_workers=10)

        # Scale up first
        await pool.scale_to(5, warmup=False)
        assert pool.count == 5

        # Scale down
        await pool.scale_to(2, warmup=False)

        # Give workers time to stop
        await asyncio.sleep(0.1)

        # Should have 2 running (not signaled to stop)
        assert len(pool.running_worker_ids()) == 2

        await pool.stop_all()

    @pytest.mark.asyncio
    async def test_scale_to_respects_max_workers(self) -> None:
        """scale_to does not exceed max_workers."""
        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()

        pool = WorkerPool(worker_factory=mock_worker, min_workers=0, max_workers=5)

        await pool.scale_to(100, warmup=False)

        # Should be capped at max_workers
        assert pool.count == 5

        await pool.stop_all()

    @pytest.mark.asyncio
    async def test_scale_to_respects_min_workers(self) -> None:
        """scale_to does not go below min_workers."""
        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()

        pool = WorkerPool(worker_factory=mock_worker, min_workers=3, max_workers=10)

        await pool.scale_to(5, warmup=False)
        await pool.scale_to(1, warmup=False)

        # Should be floored at min_workers
        # Note: running_worker_ids excludes stop-signaled workers
        await asyncio.sleep(0.1)
        assert len(pool.running_worker_ids()) >= 3

        await pool.stop_all()

    @pytest.mark.asyncio
    async def test_scale_to_calls_prewarm_callback(self) -> None:
        """scale_to calls prewarm_callback when scaling up."""
        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()

        prewarm_called_with: list[int] = []

        async def prewarm_callback(target: int):
            prewarm_called_with.append(target)

        pool = WorkerPool(worker_factory=mock_worker, min_workers=0, max_workers=10)

        await pool.scale_to(5, warmup=False, prewarm_callback=prewarm_callback)

        assert 5 in prewarm_called_with

        await pool.stop_all()


class TestWorkerPoolStopAll:
    """Tests for WorkerPool.stop_all()."""

    @pytest.mark.asyncio
    async def test_stop_all_signals_all_workers(self) -> None:
        """stop_all signals all workers to stop."""
        stopped_count = 0

        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            nonlocal stopped_count
            await stop_signal.wait()
            stopped_count += 1

        pool = WorkerPool(worker_factory=mock_worker, min_workers=0, max_workers=10)

        await pool.scale_to(5, warmup=False)
        assert pool.count == 5

        await pool.stop_all(timeout_seconds=2.0)

        assert stopped_count == 5
        assert pool.count == 0

    @pytest.mark.asyncio
    async def test_stop_all_timeout_handling(self) -> None:
        """stop_all handles slow workers with timeout."""
        async def slow_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()
            await asyncio.sleep(10)  # Intentionally slow

        pool = WorkerPool(worker_factory=slow_worker, min_workers=0, max_workers=10)

        await pool.scale_to(2, warmup=False)

        # Should complete within timeout even if workers are slow
        await pool.stop_all(timeout_seconds=0.5)

        # Pool should be cleared even if workers didn't finish gracefully
        assert len(pool._worker_tasks) == 0


class TestWorkerPoolPrune:
    """Tests for WorkerPool.prune_completed()."""

    @pytest.mark.asyncio
    async def test_prune_completed_removes_done_tasks(self) -> None:
        """prune_completed removes workers that have finished."""
        async def quick_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            # Exit immediately without waiting for stop signal
            pass

        pool = WorkerPool(worker_factory=quick_worker, min_workers=0, max_workers=10)

        await pool.spawn_one(warmup=False)
        await pool.spawn_one(warmup=False)

        # Wait for workers to complete
        await asyncio.sleep(0.1)

        # Before prune, tasks are still in dict
        assert len(pool._worker_tasks) == 2

        pool.prune_completed()

        # After prune, completed tasks are removed
        assert len(pool._worker_tasks) == 0


class TestWorkerPoolRunningWorkerIds:
    """Tests for WorkerPool.running_worker_ids()."""

    @pytest.mark.asyncio
    async def test_running_worker_ids_excludes_stopped(self) -> None:
        """running_worker_ids excludes stop-signaled workers."""
        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()

        pool = WorkerPool(worker_factory=mock_worker, min_workers=0, max_workers=10)

        # Spawn 5 workers
        for _ in range(5):
            await pool.spawn_one(warmup=False)

        # All 5 should be running
        assert len(pool.running_worker_ids()) == 5

        # Signal 2 to stop (highest IDs)
        for wid in [4, 3]:
            entry = pool._worker_tasks.get(wid)
            if entry:
                _, stop_signal = entry
                stop_signal.set()

        # Only 3 should be "running" (not signaled)
        assert len(pool.running_worker_ids()) == 3
        assert 0 in pool.running_worker_ids()
        assert 1 in pool.running_worker_ids()
        assert 2 in pool.running_worker_ids()

        await pool.stop_all()


class TestWorkerPoolCallbackNotification:
    """Tests for worker change callback."""

    @pytest.mark.asyncio
    async def test_on_workers_changed_called_on_spawn(self) -> None:
        """on_workers_changed callback is called when worker spawns."""
        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()

        callback_count = 0

        def on_changed():
            nonlocal callback_count
            callback_count += 1

        pool = WorkerPool(
            worker_factory=mock_worker,
            min_workers=0,
            max_workers=10,
            on_workers_changed=on_changed,
        )

        await pool.spawn_one(warmup=False)

        assert callback_count >= 1

        await pool.stop_all()

    @pytest.mark.asyncio
    async def test_on_workers_changed_called_on_scale_down(self) -> None:
        """on_workers_changed callback is called when scaling down."""
        async def mock_worker(worker_id: int, warmup: bool, stop_signal: asyncio.Event):
            await stop_signal.wait()

        callback_count = 0

        def on_changed():
            nonlocal callback_count
            callback_count += 1

        pool = WorkerPool(
            worker_factory=mock_worker,
            min_workers=0,
            max_workers=10,
            on_workers_changed=on_changed,
        )

        await pool.scale_to(5, warmup=False)
        initial_count = callback_count

        await pool.scale_to(2, warmup=False)

        # Callback should have been called for scale down
        assert callback_count > initial_count

        await pool.stop_all()
