"""
Real-Time Update Tests

These tests verify the complete data flow from worker metrics to dashboard display.
They are designed to catch specific issues with real-time updates not appearing.

Key failure modes being tested:
1. Field name mismatches between backend and frontend
2. TTL cache expiry causing fallback to stale DB data
3. Phase filtering excluding valid worker metrics
4. Custom metrics (sf_bench, pg_bench, resources) not propagating
5. Latency percentiles not aggregating correctly
6. Connection counts (in-flight queries) not summing
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.live_metrics_cache import (
    LiveMetricsCache,
    LiveRunSnapshot,
    _aggregate_workers,
    WorkerLiveMetrics,
)
from backend.models.metrics import LatencyPercentiles, Metrics, OperationMetrics


# =============================================================================
# Test Fixtures
# =============================================================================


def make_worker_metrics(
    *,
    qps: float = 100.0,
    total_ops: int = 1000,
    p50: float = 10.0,
    p95: float = 50.0,
    p99: float = 100.0,
    avg: float = 25.0,
    reads: int = 800,
    writes: int = 200,
    errors: int = 0,
    active_connections: int = 10,
    target_workers: int = 10,
    elapsed_seconds: float = 60.0,
    custom_metrics: dict[str, Any] | None = None,
) -> Metrics:
    """Create realistic worker metrics for testing."""
    return Metrics(
        timestamp=datetime.now(UTC),
        elapsed_seconds=elapsed_seconds,
        total_operations=total_ops,
        successful_operations=total_ops - errors,
        failed_operations=errors,
        current_qps=qps,
        avg_qps=qps,
        read_metrics=OperationMetrics(count=reads),
        write_metrics=OperationMetrics(count=writes),
        overall_latency=LatencyPercentiles(p50=p50, p95=p95, p99=p99, avg=avg),
        active_connections=active_connections,
        target_workers=target_workers,
        custom_metrics=custom_metrics or {},
    )


def make_worker_snapshot(
    *,
    worker_id: str = "worker-1",
    test_id: str = "test-abc",
    worker_group_id: int = 0,
    worker_group_count: int = 1,
    phase: str | None = "RUNNING",
    status: str | None = "RUNNING",
    target_connections: int | None = 10,
    metrics: Metrics | None = None,
) -> WorkerLiveMetrics:
    """Create a WorkerLiveMetrics snapshot for aggregation testing."""
    return WorkerLiveMetrics(
        test_id=test_id,
        worker_id=worker_id,
        worker_group_id=worker_group_id,
        worker_group_count=worker_group_count,
        phase=phase,
        status=status,
        target_connections=target_connections,
        metrics=metrics or make_worker_metrics(),
        received_at=datetime.now(UTC),
    )


# =============================================================================
# Frontend Field Mapping Tests
# =============================================================================


class TestFrontendFieldMappings:
    """
    Test that cache output matches exact field names the frontend expects.
    
    Frontend (dashboard.js) expects these specific paths:
    - ops.current_per_sec → metrics.ops_per_sec
    - latency.p50 → metrics.p50_latency
    - latency.p95 → metrics.p95_latency
    - latency.p99 → metrics.p99_latency
    - errors.rate → metrics.error_rate
    - errors.count → metrics.total_errors
    - connections.active → metrics.in_flight
    - connections.target → metrics.target_workers
    """

    @pytest.mark.asyncio
    async def test_ops_field_structure(self) -> None:
        """Frontend expects ops.current_per_sec and ops.total."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=150.0, total_ops=5000),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        # Frontend expects these exact field names
        assert "ops" in snapshot.metrics
        assert "current_per_sec" in snapshot.metrics["ops"], "Frontend needs ops.current_per_sec"
        assert "total" in snapshot.metrics["ops"], "Frontend needs ops.total"

        # Verify values
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(150.0)
        assert snapshot.metrics["ops"]["total"] == 5000

    @pytest.mark.asyncio
    async def test_latency_field_structure(self) -> None:
        """Frontend expects latency.p50, latency.p95, latency.p99, latency.avg."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(p50=15.5, p95=45.2, p99=120.8, avg=25.0),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        # Frontend expects these exact field names
        assert "latency" in snapshot.metrics
        assert "p50" in snapshot.metrics["latency"], "Frontend needs latency.p50"
        assert "p95" in snapshot.metrics["latency"], "Frontend needs latency.p95"
        assert "p99" in snapshot.metrics["latency"], "Frontend needs latency.p99"
        assert "avg" in snapshot.metrics["latency"], "Frontend needs latency.avg"

        # Verify values (single worker = direct values)
        assert snapshot.metrics["latency"]["p50"] == pytest.approx(15.5)
        assert snapshot.metrics["latency"]["p95"] == pytest.approx(45.2)
        assert snapshot.metrics["latency"]["p99"] == pytest.approx(120.8)
        assert snapshot.metrics["latency"]["avg"] == pytest.approx(25.0)

    @pytest.mark.asyncio
    async def test_errors_field_structure(self) -> None:
        """Frontend expects errors.rate and errors.count."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(total_ops=1000, errors=50),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        # Frontend expects these exact field names
        assert "errors" in snapshot.metrics
        assert "rate" in snapshot.metrics["errors"], "Frontend needs errors.rate"
        assert "count" in snapshot.metrics["errors"], "Frontend needs errors.count"

        # Verify values
        assert snapshot.metrics["errors"]["count"] == 50
        assert snapshot.metrics["errors"]["rate"] == pytest.approx(0.05)  # 50/1000

    @pytest.mark.asyncio
    async def test_connections_field_structure(self) -> None:
        """Frontend expects connections.active (in-flight) and connections.target."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=100,
            metrics=make_worker_metrics(active_connections=75, target_workers=100),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        # Frontend expects these exact field names
        assert "connections" in snapshot.metrics
        assert "active" in snapshot.metrics["connections"], "Frontend needs connections.active for in-flight queries"
        assert "target" in snapshot.metrics["connections"], "Frontend needs connections.target"

        # Verify values
        assert snapshot.metrics["connections"]["active"] == 75
        assert snapshot.metrics["connections"]["target"] == 100


# =============================================================================
# Custom Metrics Tests (sf_bench, pg_bench, resources)
# =============================================================================


class TestCustomMetricsPropagation:
    """
    Test that custom_metrics (sf_bench, pg_bench, resources) propagate correctly.
    
    These power:
    - Snowflake running queries display
    - Postgres running queries display
    - CPU/memory resource displays
    """

    @pytest.mark.asyncio
    async def test_sf_bench_propagates(self) -> None:
        """Snowflake benchmark counters should propagate to dashboard."""
        sf_bench_data = {
            "running": 5,
            "queued": 2,
            "blocked": 1,
            "running_tagged": 3,
            "running_other": 2,
            "running_read": 4,
            "running_write": 1,
        }
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(custom_metrics={"sf_bench": sf_bench_data}),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        assert "custom_metrics" in snapshot.metrics
        assert "sf_bench" in snapshot.metrics["custom_metrics"], "sf_bench should propagate"

        sf_bench = snapshot.metrics["custom_metrics"]["sf_bench"]
        assert sf_bench["running"] == 5
        assert sf_bench["queued"] == 2
        assert sf_bench["blocked"] == 1

    @pytest.mark.asyncio
    async def test_pg_bench_propagates(self) -> None:
        """Postgres benchmark counters should propagate to dashboard."""
        pg_bench_data = {
            "running": 8,
            "queued": 3,
            "blocked": 0,
        }
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(custom_metrics={"pg_bench": pg_bench_data}),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        assert "custom_metrics" in snapshot.metrics
        assert "pg_bench" in snapshot.metrics["custom_metrics"], "pg_bench should propagate"

        pg_bench = snapshot.metrics["custom_metrics"]["pg_bench"]
        assert pg_bench["running"] == 8
        assert pg_bench["queued"] == 3

    @pytest.mark.asyncio
    async def test_resources_propagates(self) -> None:
        """CPU/memory resources should propagate to dashboard."""
        resources_data = {
            "cpu_percent": 75.5,
            "memory_mb": 2048,
            "memory_percent": 45.2,
        }
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(custom_metrics={"resources": resources_data}),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        assert "custom_metrics" in snapshot.metrics
        assert "resources" in snapshot.metrics["custom_metrics"], "resources should propagate"

        resources = snapshot.metrics["custom_metrics"]["resources"]
        assert resources["cpu_percent"] == pytest.approx(75.5)
        assert resources["memory_mb"] == pytest.approx(2048)

    @pytest.mark.asyncio
    async def test_sf_bench_sums_across_workers(self) -> None:
        """Multiple workers' sf_bench counters should be summed."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # Worker 1
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=2,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(
                custom_metrics={"sf_bench": {"running": 5, "queued": 2}}
            ),
        )

        # Worker 2
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-2",
            worker_group_id=1,
            worker_group_count=2,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(
                custom_metrics={"sf_bench": {"running": 3, "queued": 4}}
            ),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        sf_bench = snapshot.metrics["custom_metrics"]["sf_bench"]
        assert sf_bench["running"] == 8  # 5 + 3
        assert sf_bench["queued"] == 6  # 2 + 4


# =============================================================================
# Phase Filtering Tests
# =============================================================================


class TestPhaseFiltering:
    """
    Test that workers in valid phases are included in metrics.
    
    Workers should be included if:
    - phase is None/empty
    - phase is WARMUP, MEASUREMENT, or RUNNING
    - status is not DEAD
    """

    @pytest.mark.asyncio
    async def test_running_phase_included(self) -> None:
        """Workers in RUNNING phase should have metrics included."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=100.0),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_measurement_phase_included(self) -> None:
        """Workers in MEASUREMENT phase should have metrics included."""
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
            metrics=make_worker_metrics(qps=100.0),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_warmup_phase_included(self) -> None:
        """Workers in WARMUP phase should have metrics included."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="WARMUP",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=50.0),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_none_phase_included(self) -> None:
        """Workers with None/empty phase should have metrics included."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase=None,
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=100.0),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_dead_status_excluded(self) -> None:
        """Workers with DEAD status should have metrics excluded."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # Healthy worker
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=2,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=100.0),
        )

        # Dead worker (should be excluded)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-2",
            worker_group_id=1,
            worker_group_count=2,
            phase="RUNNING",
            status="DEAD",
            target_connections=10,
            metrics=make_worker_metrics(qps=500.0),  # High QPS should NOT be included
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        # Only worker-1's 100 QPS, not worker-2's 500
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_completed_phase_excluded(self) -> None:
        """Workers in COMPLETED phase should have metrics excluded."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # Running worker
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=2,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=100.0),
        )

        # Completed worker (should be excluded)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-2",
            worker_group_id=1,
            worker_group_count=2,
            phase="COMPLETED",
            status="COMPLETED",
            target_connections=10,
            metrics=make_worker_metrics(qps=200.0),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        # Only worker-1's 100 QPS
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(100.0)


# =============================================================================
# TTL and Cache Expiry Tests
# =============================================================================


class TestTTLBehavior:
    """
    Test cache TTL behavior that can cause real-time updates to stop.
    
    Default TTL is 5 seconds. Workers must post at least every 5s
    or their metrics are pruned and fallback to DB occurs.
    """

    @pytest.mark.asyncio
    async def test_fresh_metrics_available(self) -> None:
        """Metrics posted recently should be available."""
        cache = LiveMetricsCache(ttl_seconds=5.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=100.0),
        )

        # Immediately available
        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(100.0)

    @pytest.mark.asyncio
    async def test_ttl_expiry_returns_none(self) -> None:
        """Metrics older than TTL should cause get_run_snapshot to return None."""
        cache = LiveMetricsCache(ttl_seconds=1.0)  # Short TTL for testing
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=100.0),
        )

        # Available immediately
        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        # Wait for TTL to expire
        await asyncio.sleep(1.5)

        # Should now return None (causes DB fallback in streaming.py)
        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is None, "Stale metrics should cause None return (triggers DB fallback)"

    @pytest.mark.asyncio
    async def test_continuous_updates_keep_cache_fresh(self) -> None:
        """Continuous updates prevent TTL expiry."""
        cache = LiveMetricsCache(ttl_seconds=1.0)

        # Initial update
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=100.0),
        )

        # Simulate continuous updates every 0.5s (faster than TTL)
        for _ in range(5):
            await asyncio.sleep(0.5)
            await cache.update(
                run_id="run-123",
                test_id="test-abc",
                worker_id="worker-1",
                worker_group_id=0,
                worker_group_count=1,
                phase="RUNNING",
                status="RUNNING",
                target_connections=10,
                metrics=make_worker_metrics(qps=100.0),
            )

            # Should remain available
            snapshot = await cache.get_run_snapshot(run_id="run-123")
            assert snapshot is not None, "Continuous updates should keep cache fresh"


# =============================================================================
# Multi-Worker Aggregation Tests
# =============================================================================


class TestMultiWorkerAggregation:
    """
    Test that metrics from multiple workers aggregate correctly.
    
    - QPS: summed across workers
    - Operations: summed across workers
    - Latency p50: averaged
    - Latency p95/p99: max (slowest worker approximation)
    - Connections: summed
    - Error rate: total_errors / total_ops
    """

    @pytest.mark.asyncio
    async def test_qps_sums_across_workers(self) -> None:
        """QPS from all workers should be summed."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        for i, qps in enumerate([100.0, 150.0, 200.0]):
            await cache.update(
                run_id="run-123",
                test_id="test-abc",
                worker_id=f"worker-{i}",
                worker_group_id=i,
                worker_group_count=3,
                phase="RUNNING",
                status="RUNNING",
                target_connections=10,
                metrics=make_worker_metrics(qps=qps),
            )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(450.0)  # 100+150+200

    @pytest.mark.asyncio
    async def test_connections_sum_across_workers(self) -> None:
        """Active connections (in-flight queries) should sum across workers."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        for i, active in enumerate([25, 30, 45]):
            await cache.update(
                run_id="run-123",
                test_id="test-abc",
                worker_id=f"worker-{i}",
                worker_group_id=i,
                worker_group_count=3,
                phase="RUNNING",
                status="RUNNING",
                target_connections=50,
                metrics=make_worker_metrics(active_connections=active),
            )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["connections"]["active"] == 100  # 25+30+45
        assert snapshot.metrics["connections"]["target"] == 150  # 50*3

    @pytest.mark.asyncio
    async def test_latency_p95_uses_max(self) -> None:
        """P95 latency should use max across workers (slowest worker)."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        for i, p95 in enumerate([30.0, 80.0, 45.0]):
            await cache.update(
                run_id="run-123",
                test_id="test-abc",
                worker_id=f"worker-{i}",
                worker_group_id=i,
                worker_group_count=3,
                phase="RUNNING",
                status="RUNNING",
                target_connections=10,
                metrics=make_worker_metrics(p95=p95),
            )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["latency"]["p95"] == pytest.approx(80.0)  # max

    @pytest.mark.asyncio
    async def test_latency_p99_uses_max(self) -> None:
        """P99 latency should use max across workers (slowest worker)."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        for i, p99 in enumerate([100.0, 150.0, 120.0]):
            await cache.update(
                run_id="run-123",
                test_id="test-abc",
                worker_id=f"worker-{i}",
                worker_group_id=i,
                worker_group_count=3,
                phase="RUNNING",
                status="RUNNING",
                target_connections=10,
                metrics=make_worker_metrics(p99=p99),
            )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["latency"]["p99"] == pytest.approx(150.0)  # max

    @pytest.mark.asyncio
    async def test_latency_p50_uses_average(self) -> None:
        """P50 latency should use average across workers."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        for i, p50 in enumerate([10.0, 20.0, 30.0]):
            await cache.update(
                run_id="run-123",
                test_id="test-abc",
                worker_id=f"worker-{i}",
                worker_group_id=i,
                worker_group_count=3,
                phase="RUNNING",
                status="RUNNING",
                target_connections=10,
                metrics=make_worker_metrics(p50=p50),
            )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["latency"]["p50"] == pytest.approx(20.0)  # avg(10,20,30)

    @pytest.mark.asyncio
    async def test_error_rate_uses_total_ratio(self) -> None:
        """Error rate should be total_errors / total_ops across all workers."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # Worker 1: 1000 ops, 10 errors
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=2,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(total_ops=1000, errors=10),
        )

        # Worker 2: 2000 ops, 40 errors
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-2",
            worker_group_id=1,
            worker_group_count=2,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(total_ops=2000, errors=40),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None
        assert snapshot.metrics["errors"]["count"] == 50  # 10 + 40
        assert snapshot.metrics["errors"]["rate"] == pytest.approx(50 / 3000)  # 50/3000


# =============================================================================
# Find Max Controller Tests
# =============================================================================


class TestFindMaxController:
    """
    Test find_max_controller propagation for step-based benchmarks.
    """

    @pytest.mark.asyncio
    async def test_find_max_controller_propagates(self) -> None:
        """find_max_controller from workers should propagate."""
        find_max_data = {
            "current_step": 3,
            "target_workers": 50,
            "step_end_at_epoch_ms": 1700000000000,
            "best_qps": 1500.0,
            "best_workers": 40,
        }
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=50,
            metrics=make_worker_metrics(
                custom_metrics={"find_max_controller": find_max_data}
            ),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        assert "custom_metrics" in snapshot.metrics
        assert "find_max_controller" in snapshot.metrics["custom_metrics"]

        controller = snapshot.metrics["custom_metrics"]["find_max_controller"]
        assert controller["current_step"] == 3
        assert controller["target_workers"] == 50
        assert controller["best_qps"] == 1500.0


# =============================================================================
# Direct Aggregation Function Tests
# =============================================================================


class TestAggregateWorkersFunction:
    """
    Test the _aggregate_workers function directly for edge cases.
    """

    def test_empty_workers_returns_empty(self) -> None:
        """Empty worker list returns empty metrics and worker rows."""
        metrics, workers = _aggregate_workers([], now=datetime.now(UTC))
        assert metrics == {}
        assert workers == []

    def test_single_worker_passes_through(self) -> None:
        """Single worker metrics pass through directly."""
        worker = make_worker_snapshot(
            worker_id="worker-1",
            phase="RUNNING",
            status="RUNNING",
            metrics=make_worker_metrics(qps=100.0, p50=15.0, p95=50.0, p99=100.0),
        )

        metrics, workers = _aggregate_workers([worker], now=datetime.now(UTC))

        assert metrics["ops"]["current_per_sec"] == pytest.approx(100.0)
        assert metrics["latency"]["p50"] == pytest.approx(15.0)
        assert metrics["latency"]["p95"] == pytest.approx(50.0)
        assert metrics["latency"]["p99"] == pytest.approx(100.0)
        assert len(workers) == 1

    def test_multiple_workers_aggregate_correctly(self) -> None:
        """Multiple workers aggregate with correct operations."""
        workers = [
            make_worker_snapshot(
                worker_id="worker-1",
                worker_group_id=0,
                phase="RUNNING",
                status="RUNNING",
                metrics=make_worker_metrics(qps=100.0, p50=10.0, p95=40.0, p99=80.0, active_connections=20),
            ),
            make_worker_snapshot(
                worker_id="worker-2",
                worker_group_id=1,
                phase="RUNNING",
                status="RUNNING",
                metrics=make_worker_metrics(qps=200.0, p50=20.0, p95=60.0, p99=120.0, active_connections=30),
            ),
        ]

        metrics, worker_rows = _aggregate_workers(workers, now=datetime.now(UTC))

        # QPS summed
        assert metrics["ops"]["current_per_sec"] == pytest.approx(300.0)
        # p50 averaged
        assert metrics["latency"]["p50"] == pytest.approx(15.0)
        # p95/p99 max
        assert metrics["latency"]["p95"] == pytest.approx(60.0)
        assert metrics["latency"]["p99"] == pytest.approx(120.0)
        # Connections summed
        assert metrics["connections"]["active"] == 50


# =============================================================================
# End-to-End Payload Structure Test
# =============================================================================


class TestEndToEndPayloadStructure:
    """
    Verify the complete payload structure matches what frontend expects.
    """

    @pytest.mark.asyncio
    async def test_complete_payload_structure(self) -> None:
        """Test that all expected fields are present in the snapshot."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=100,
            metrics=make_worker_metrics(
                qps=250.0,
                total_ops=10000,
                p50=12.5,
                p95=45.0,
                p99=95.0,
                avg=20.0,
                reads=8000,
                writes=2000,
                errors=50,
                active_connections=85,
                target_workers=100,
                custom_metrics={
                    "sf_bench": {"running": 10, "queued": 5},
                    "pg_bench": {"running": 8, "queued": 2},
                    "resources": {"cpu_percent": 65.0, "memory_mb": 4096},
                    "app_ops_breakdown": {"point_lookup_count": 5000, "range_scan_count": 3000},
                },
            ),
        )

        snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert snapshot is not None

        # Top-level required fields
        assert "phase" in snapshot.metrics
        assert "elapsed" in snapshot.metrics
        assert "ops" in snapshot.metrics
        assert "operations" in snapshot.metrics
        assert "latency" in snapshot.metrics
        assert "errors" in snapshot.metrics
        assert "connections" in snapshot.metrics
        assert "custom_metrics" in snapshot.metrics

        # ops structure
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(250.0)
        assert snapshot.metrics["ops"]["total"] == 10000

        # operations structure
        assert snapshot.metrics["operations"]["reads"] == 8000
        assert snapshot.metrics["operations"]["writes"] == 2000

        # latency structure
        assert snapshot.metrics["latency"]["p50"] == pytest.approx(12.5)
        assert snapshot.metrics["latency"]["p95"] == pytest.approx(45.0)
        assert snapshot.metrics["latency"]["p99"] == pytest.approx(95.0)
        assert snapshot.metrics["latency"]["avg"] == pytest.approx(20.0)

        # errors structure
        assert snapshot.metrics["errors"]["count"] == 50
        assert snapshot.metrics["errors"]["rate"] == pytest.approx(0.005)

        # connections structure (in-flight queries)
        assert snapshot.metrics["connections"]["active"] == 85
        assert snapshot.metrics["connections"]["target"] == 100

        # custom_metrics structure
        assert snapshot.metrics["custom_metrics"]["sf_bench"]["running"] == 10
        assert snapshot.metrics["custom_metrics"]["pg_bench"]["running"] == 8
        assert snapshot.metrics["custom_metrics"]["resources"]["cpu_percent"] == pytest.approx(65.0)

        # workers list
        assert len(snapshot.workers) == 1
        assert snapshot.workers[0]["worker_id"] == "worker-1"

        # test_ids list
        assert "test-abc" in snapshot.test_ids
        assert "run-123" in snapshot.test_ids


# =============================================================================
# Streaming Layer Tests
# =============================================================================


class TestStreamingPayloadConstruction:
    """
    Test the WebSocket streaming payload construction.
    
    streaming.py spreads **metrics into the payload, so we need to verify
    that field names are correct.
    """

    @pytest.mark.asyncio
    async def test_payload_structure_from_cache(self) -> None:
        """Verify the final payload structure sent via WebSocket."""
        from backend.websocket.metrics import build_aggregate_metrics, build_run_snapshot

        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="run-123",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=100,
            metrics=make_worker_metrics(
                qps=200.0,
                total_ops=5000,
                p50=15.0,
                p95=55.0,
                p99=110.0,
                errors=25,
                active_connections=80,
            ),
        )

        live_snapshot = await cache.get_run_snapshot(run_id="run-123")
        assert live_snapshot is not None

        # Simulate streaming.py payload construction (lines 238-246)
        metrics = dict(live_snapshot.metrics)
        workers = list(live_snapshot.workers)
        
        metrics_phase = metrics.pop("phase", None)
        phase = metrics_phase or "RUNNING"
        status_upper = "RUNNING"

        ops = metrics.get("ops")
        latency = metrics.get("latency")
        errors = metrics.get("errors")
        connections = metrics.get("connections")
        operations = metrics.get("operations")

        aggregate_metrics = build_aggregate_metrics(
            ops=ops,
            latency=latency,
            errors=errors,
            connections=connections,
            operations=operations,
        )

        run_snapshot = build_run_snapshot(
            run_id="run-123",
            status=status_upper,
            phase=phase,
            elapsed_seconds=60.0,
            worker_count=len(workers),
            aggregate_metrics=aggregate_metrics,
            run_status=None,
        )

        payload = {
            "test_id": "run-123",
            "status": status_upper,
            "phase": phase,
            "timestamp": datetime.now(UTC).isoformat(),
            "run": run_snapshot,
            "workers": workers,
            **metrics,
        }

        # Verify top-level fields exist (what frontend parses)
        assert "ops" in payload, "Frontend expects 'ops' at top level"
        assert "latency" in payload, "Frontend expects 'latency' at top level"
        assert "errors" in payload, "Frontend expects 'errors' at top level"
        assert "connections" in payload, "Frontend expects 'connections' at top level"
        assert "custom_metrics" in payload, "Frontend expects 'custom_metrics' at top level"

        # Verify ops structure
        assert payload["ops"]["current_per_sec"] == pytest.approx(200.0)
        assert payload["ops"]["total"] == 5000

        # Verify latency structure
        assert payload["latency"]["p50"] == pytest.approx(15.0)
        assert payload["latency"]["p95"] == pytest.approx(55.0)
        assert payload["latency"]["p99"] == pytest.approx(110.0)

        # Verify errors structure
        assert payload["errors"]["count"] == 25
        assert payload["errors"]["rate"] == pytest.approx(0.005)

        # Verify connections structure (in-flight queries)
        assert payload["connections"]["active"] == 80
        assert payload["connections"]["target"] == 100

        # Verify run.aggregate_metrics (alternative source for frontend)
        assert payload["run"]["aggregate_metrics"]["qps"] == pytest.approx(200.0)
        assert payload["run"]["aggregate_metrics"]["p50_latency_ms"] == pytest.approx(15.0)
        assert payload["run"]["aggregate_metrics"]["p95_latency_ms"] == pytest.approx(55.0)
        assert payload["run"]["aggregate_metrics"]["active_connections"] == 80


# =============================================================================
# API Endpoint Tests
# =============================================================================


class TestWorkerMetricsEndpoint:
    """
    Test the /api/runs/{run_id}/metrics/live endpoint that workers POST to.
    """

    @pytest.mark.asyncio
    async def test_ingest_live_metrics_updates_cache(self) -> None:
        """Verify the API endpoint updates the cache correctly."""
        from backend.api.routes.runs import LiveMetricsUpdate
        from backend.core.live_metrics_cache import live_metrics_cache
        from backend.models.metrics import LatencyPercentiles, Metrics, OperationMetrics

        # Create a request payload matching what workers send
        metrics = Metrics(
            timestamp=datetime.now(UTC),
            elapsed_seconds=120.0,
            total_operations=10000,
            successful_operations=9950,
            failed_operations=50,
            current_qps=300.0,
            avg_qps=280.0,
            read_metrics=OperationMetrics(count=8000),
            write_metrics=OperationMetrics(count=2000),
            overall_latency=LatencyPercentiles(p50=20.0, p95=60.0, p99=150.0, avg=30.0),
            active_connections=90,
            target_workers=100,
            custom_metrics={
                "sf_bench": {"running": 15, "queued": 3},
                "resources": {"cpu_percent": 70.0},
            },
        )

        # Directly call cache update (simulating what ingest_live_metrics does)
        await live_metrics_cache.update(
            run_id="integration-test-run",
            test_id="integration-test-run",
            worker_id="integration-worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=100,
            metrics=metrics,
        )

        # Verify cache was updated
        snapshot = await live_metrics_cache.get_run_snapshot(run_id="integration-test-run")
        assert snapshot is not None, "Cache should have snapshot after update"

        # Verify metrics propagated correctly
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(300.0)
        assert snapshot.metrics["latency"]["p50"] == pytest.approx(20.0)
        assert snapshot.metrics["connections"]["active"] == 90
        assert snapshot.metrics["custom_metrics"]["sf_bench"]["running"] == 15


# =============================================================================
# Diagnostic Tests for Debugging Real-Time Issues
# =============================================================================


class TestDiagnosticHelpers:
    """
    Diagnostic tests that can help identify issues during real benchmarks.
    
    These tests verify specific behaviors that could cause real-time updates to fail.
    """

    @pytest.mark.asyncio
    async def test_cache_returns_none_when_no_workers(self) -> None:
        """Cache returns None when no workers have posted - triggers DB fallback."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        
        # No updates made
        snapshot = await cache.get_run_snapshot(run_id="empty-run")
        assert snapshot is None, "Empty cache should return None (triggers DB fallback)"

    @pytest.mark.asyncio
    async def test_run_id_matching_is_exact(self) -> None:
        """run_id must match exactly - case sensitive."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="Run-123",  # Mixed case
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(),
        )

        # Exact match works
        assert await cache.get_run_snapshot(run_id="Run-123") is not None

        # Different case fails
        assert await cache.get_run_snapshot(run_id="run-123") is None
        assert await cache.get_run_snapshot(run_id="RUN-123") is None

    @pytest.mark.asyncio
    async def test_whitespace_in_run_id_trimmed(self) -> None:
        """Whitespace in run_id is trimmed."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="  run-123  ",  # Extra whitespace
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(),
        )

        # Should be trimmed to "run-123"
        assert await cache.get_run_snapshot(run_id="run-123") is not None
        assert await cache.get_run_snapshot(run_id="  run-123  ") is not None

    @pytest.mark.asyncio
    async def test_all_workers_excluded_returns_empty_metrics(self) -> None:
        """If all workers are DEAD or wrong phase, aggregation returns empty."""
        workers = [
            make_worker_snapshot(
                worker_id="worker-1",
                phase="COMPLETED",  # Excluded
                status="COMPLETED",
                metrics=make_worker_metrics(qps=100.0),
            ),
            make_worker_snapshot(
                worker_id="worker-2",
                phase="RUNNING",
                status="DEAD",  # Excluded
                metrics=make_worker_metrics(qps=200.0),
            ),
        ]

        metrics, worker_rows = _aggregate_workers(workers, now=datetime.now(UTC))

        # No metrics should be included (all excluded)
        assert metrics["ops"]["current_per_sec"] == 0.0
        assert metrics["ops"]["total"] == 0
        # But worker rows still returned for display
        assert len(worker_rows) == 2

    @pytest.mark.asyncio
    async def test_metrics_zero_when_no_valid_workers(self) -> None:
        """When all workers excluded, metrics are zero but structure is valid."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        
        # Only add a DEAD worker
        await cache.update(
            run_id="dead-workers-run",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="DEAD",
            target_connections=10,
            metrics=make_worker_metrics(qps=100.0, total_ops=1000),
        )

        snapshot = await cache.get_run_snapshot(run_id="dead-workers-run")
        assert snapshot is not None  # Snapshot exists

        # Metrics are zero because worker is DEAD
        assert snapshot.metrics["ops"]["current_per_sec"] == 0.0
        assert snapshot.metrics["ops"]["total"] == 0

    @pytest.mark.asyncio
    async def test_custom_metrics_empty_when_not_provided(self) -> None:
        """custom_metrics fields are empty dicts when workers don't provide them."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        await cache.update(
            run_id="no-custom-metrics",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(custom_metrics={}),  # Empty custom metrics
        )

        snapshot = await cache.get_run_snapshot(run_id="no-custom-metrics")
        assert snapshot is not None

        # custom_metrics should exist but sub-dicts are empty
        assert "custom_metrics" in snapshot.metrics
        assert snapshot.metrics["custom_metrics"]["sf_bench"] == {}
        assert snapshot.metrics["custom_metrics"]["pg_bench"] == {}
        assert snapshot.metrics["custom_metrics"]["resources"] == {}


# =============================================================================
# Worker Posting Frequency Tests
# =============================================================================


class TestWorkerPostingBehavior:
    """
    Tests related to worker posting frequency and timing.
    
    Workers should post at least every 5 seconds (default TTL) to keep cache fresh.
    """

    @pytest.mark.asyncio
    async def test_rapid_updates_all_captured(self) -> None:
        """Multiple rapid updates from same worker should all be captured."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # Rapid updates simulating 1-second intervals
        for i in range(5):
            await cache.update(
                run_id="rapid-updates",
                test_id="test-abc",
                worker_id="worker-1",
                worker_group_id=0,
                worker_group_count=1,
                phase="RUNNING",
                status="RUNNING",
                target_connections=10,
                metrics=make_worker_metrics(qps=100.0 + i * 10),  # Increasing QPS
            )

        snapshot = await cache.get_run_snapshot(run_id="rapid-updates")
        assert snapshot is not None
        # Should have latest value (140.0)
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(140.0)

    @pytest.mark.asyncio
    async def test_worker_replacement_on_update(self) -> None:
        """Each worker update replaces the previous one (not accumulates)."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # First update
        await cache.update(
            run_id="replacement-test",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=100.0, total_ops=1000),
        )

        # Second update (replaces first)
        await cache.update(
            run_id="replacement-test",
            test_id="test-abc",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="RUNNING",
            status="RUNNING",
            target_connections=10,
            metrics=make_worker_metrics(qps=200.0, total_ops=2000),
        )

        snapshot = await cache.get_run_snapshot(run_id="replacement-test")
        assert snapshot is not None
        
        # Should have replaced values, not accumulated
        assert snapshot.metrics["ops"]["current_per_sec"] == pytest.approx(200.0)
        assert snapshot.metrics["ops"]["total"] == 2000
        # Only 1 worker entry
        assert len(snapshot.workers) == 1
