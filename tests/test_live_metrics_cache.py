"""
Unit tests for LiveMetricsCache.

Tests the in-memory cache that powers dashboard updates.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from backend.core.live_metrics_cache import (
    LiveMetricsCache,
    WorkerLiveMetrics,
    _health_from,
)
from backend.models.metrics import LatencyPercentiles, Metrics, OperationMetrics


def _make_metrics(
    *,
    qps: float = 100.0,
    total_ops: int = 1000,
    p50: float = 10.0,
    p95: float = 50.0,
    p99: float = 100.0,
    reads: int = 800,
    writes: int = 200,
    errors: int = 0,
    active_connections: int = 10,
) -> Metrics:
    """Create a Metrics instance for testing."""
    return Metrics(
        timestamp=datetime.now(UTC),
        elapsed_seconds=60.0,
        total_operations=total_ops,
        successful_operations=total_ops - errors,
        failed_operations=errors,
        current_qps=qps,
        avg_qps=qps,
        read_metrics=OperationMetrics(count=reads),
        write_metrics=OperationMetrics(count=writes),
        overall_latency=LatencyPercentiles(p50=p50, p95=p95, p99=p99, avg=p50),
        active_connections=active_connections,
        target_workers=10,
    )


class TestLiveMetricsCacheUpdate:
    """Tests for LiveMetricsCache.update()."""

    @pytest.mark.asyncio
    async def test_update_creates_run_entry(self) -> None:
        """Basic update creates a run entry in the cache."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert len(snapshot.workers) == 1
        assert "test-abc" in snapshot.test_ids

    @pytest.mark.asyncio
    async def test_update_multiple_workers_same_run(self) -> None:
        """Multiple workers for the same run are tracked separately."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # First worker
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=2,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(qps=100.0, total_ops=500),
        )

        # Second worker
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-2",
            worker_group_id=1,
            worker_group_count=2,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(qps=150.0, total_ops=700),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert len(snapshot.workers) == 2

        # Verify aggregation sums QPS
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(250.0)
        assert snapshot.metrics["ops"]["total"] == 1200

    @pytest.mark.asyncio
    async def test_update_ignores_empty_run_id(self) -> None:
        """Empty run_id is ignored."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        await cache.update(
            run_id="",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(),
        )

        snapshot = await cache.get_run_snapshot(run_id="")
        assert snapshot is None


class TestLiveMetricsCacheGetSnapshot:
    """Tests for LiveMetricsCache.get_run_snapshot()."""

    @pytest.mark.asyncio
    async def test_get_run_snapshot_returns_none_for_unknown_run(self) -> None:
        """Unknown run_id returns None."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        snapshot = await cache.get_run_snapshot(run_id="nonexistent-run")
        assert snapshot is None

    @pytest.mark.asyncio
    async def test_get_run_snapshot_returns_none_for_empty_run_id(self) -> None:
        """Empty run_id returns None."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        snapshot = await cache.get_run_snapshot(run_id="")
        assert snapshot is None


class TestLiveMetricsCachePrune:
    """Tests for cache pruning behavior."""

    @pytest.mark.asyncio
    async def test_prune_removes_stale_workers(self) -> None:
        """Workers older than TTL are removed."""
        cache = LiveMetricsCache(ttl_seconds=1.0)

        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(),
        )

        # Verify worker exists
        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert len(snapshot.workers) == 1

        # Wait for TTL to expire
        await asyncio.sleep(1.5)

        # Worker should be pruned
        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is None  # Run removed because no workers left

    @pytest.mark.asyncio
    async def test_prune_removes_empty_runs(self) -> None:
        """Runs with no workers are removed after pruning."""
        # Note: TTL minimum is 1.0 second (enforced in LiveMetricsCache)
        cache = LiveMetricsCache(ttl_seconds=1.0)

        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(),
        )

        # Wait for all workers to expire (TTL is clamped to min 1.0s)
        await asyncio.sleep(1.5)

        # Trigger prune via get_run_snapshot
        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is None

        # Verify internal state is cleaned
        assert len(cache._runs) == 0


class TestHealthStatus:
    """Tests for worker health status calculation."""

    def test_health_status_healthy(self) -> None:
        """Age < 30s returns HEALTHY."""
        assert _health_from("RUNNING", 5.0) == "HEALTHY"
        assert _health_from("RUNNING", 29.9) == "HEALTHY"
        assert _health_from(None, 0.0) == "HEALTHY"

    def test_health_status_stale(self) -> None:
        """30s <= age < 60s returns STALE."""
        assert _health_from("RUNNING", 30.0) == "STALE"
        assert _health_from("RUNNING", 45.0) == "STALE"
        assert _health_from("RUNNING", 59.9) == "STALE"

    def test_health_status_dead(self) -> None:
        """Age >= 60s returns DEAD."""
        assert _health_from("RUNNING", 60.0) == "DEAD"
        assert _health_from("RUNNING", 120.0) == "DEAD"

    def test_health_status_dead_from_status(self) -> None:
        """Status DEAD always returns DEAD regardless of age."""
        assert _health_from("DEAD", 0.0) == "DEAD"
        assert _health_from("DEAD", 5.0) == "DEAD"

    def test_health_status_stale_when_age_none(self) -> None:
        """None age returns STALE (unless status is DEAD)."""
        assert _health_from("RUNNING", None) == "STALE"
        assert _health_from(None, None) == "STALE"


class TestAggregateMetrics:
    """Tests for metrics aggregation across workers."""

    @pytest.mark.asyncio
    async def test_aggregate_metrics_sums_correctly(self) -> None:
        """QPS and ops totals are summed across workers."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # Worker 1
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=3,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(qps=100.0, total_ops=1000, reads=800, writes=200),
        )

        # Worker 2
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-2",
            worker_group_id=1,
            worker_group_count=3,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(qps=150.0, total_ops=1500, reads=1200, writes=300),
        )

        # Worker 3
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-3",
            worker_group_id=2,
            worker_group_count=3,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(qps=200.0, total_ops=2000, reads=1600, writes=400),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        # QPS should be summed
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(450.0)

        # Total ops should be summed
        assert snapshot.metrics["ops"]["total"] == 4500

        # Reads/writes should be summed
        assert snapshot.metrics["operations"]["reads"] == 3600
        assert snapshot.metrics["operations"]["writes"] == 900

        # Connections should be summed
        assert snapshot.metrics["connections"]["active"] == 30  # 10 * 3 workers
        assert snapshot.metrics["connections"]["target"] == 30

    @pytest.mark.asyncio
    async def test_aggregate_excludes_dead_workers(self) -> None:
        """DEAD workers are excluded from metrics aggregation."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # Healthy worker
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=2,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=_make_metrics(qps=100.0, total_ops=1000),
        )

        # Dead worker
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-2",
            worker_group_id=1,
            worker_group_count=2,
            phase="MEASUREMENT",
            status="DEAD",
            target_connections=10,
            metrics=_make_metrics(qps=500.0, total_ops=5000),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        # Only healthy worker's metrics should be included
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(100.0)
        assert snapshot.metrics["ops"]["total"] == 1000
