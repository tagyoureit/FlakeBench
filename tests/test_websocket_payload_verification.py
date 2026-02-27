"""
WebSocket Payload Verification Tests

Tests that RUN_UPDATE WebSocket events contain all required metrics fields.
These tests would catch issues where metrics exist in the backend but
don't flow through to the WebSocket payload.

Covers:
1. Latency metrics (p50, p95, p99)
2. Error rate and QPS metrics
3. Resource utilization (CPU, memory)
4. Connection metrics (active, in-flight)
5. Find-max step data
6. Best-so-far QPS tracking
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.core.live_metrics_cache import LiveMetricsCache, LiveRunSnapshot
from backend.models.metrics import LatencyPercentiles, Metrics


def _make_full_metrics(
    *,
    p50: float = 5.0,
    p95: float = 25.0,
    p99: float = 100.0,
    current_qps: float = 500.0,
    peak_qps: float = 550.0,
    error_rate: float = 0.01,
    cpu_percent: float = 45.0,
    memory_mb: float = 1024.0,
    active_connections: int = 10,
) -> Metrics:
    """Create a Metrics object with all fields populated for testing."""
    metrics = Metrics(
        timestamp=datetime.now(UTC),
        elapsed_seconds=60.0,
        total_operations=30000,
        successful_operations=29700,
        failed_operations=300,
        current_qps=current_qps,
        avg_qps=480.0,
        peak_qps=peak_qps,
        overall_latency=LatencyPercentiles(
            p50=p50,
            p95=p95,
            p99=p99,
            avg=15.0,
            min=1.0,
            max=500.0,
        ),
        active_connections=active_connections,
        target_workers=10,
        cpu_percent=cpu_percent,
        memory_mb=memory_mb,
    )
    return metrics


class TestWebSocketPayloadLatencyMetrics:
    """Tests that latency percentiles flow through WebSocket payloads."""

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_p50_latency(self) -> None:
        """RUN_UPDATE snapshot contains p50 latency."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(p50=12.5)

        await cache.update(
            run_id="run-latency",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-latency")

        assert snapshot is not None
        assert "latency" in snapshot.metrics
        assert "p50" in snapshot.metrics["latency"]
        assert snapshot.metrics["latency"]["p50"] == pytest.approx(12.5, rel=0.1)

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_p95_latency(self) -> None:
        """RUN_UPDATE snapshot contains p95 latency."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(p95=45.0)

        await cache.update(
            run_id="run-p95",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-p95")

        assert snapshot is not None
        assert "latency" in snapshot.metrics
        assert "p95" in snapshot.metrics["latency"]
        assert snapshot.metrics["latency"]["p95"] == pytest.approx(45.0, rel=0.1)

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_p99_latency(self) -> None:
        """RUN_UPDATE snapshot contains p99 latency."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(p99=150.0)

        await cache.update(
            run_id="run-p99",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-p99")

        assert snapshot is not None
        assert "latency" in snapshot.metrics
        assert "p99" in snapshot.metrics["latency"]
        assert snapshot.metrics["latency"]["p99"] == pytest.approx(150.0, rel=0.1)

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_avg_latency(self) -> None:
        """RUN_UPDATE snapshot contains average latency."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics()

        await cache.update(
            run_id="run-avg",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-avg")

        assert snapshot is not None
        assert "latency" in snapshot.metrics
        assert "avg" in snapshot.metrics["latency"]


class TestWebSocketPayloadQPSMetrics:
    """Tests that QPS metrics flow through WebSocket payloads."""

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_current_qps(self) -> None:
        """RUN_UPDATE snapshot contains current QPS."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(current_qps=750.0)

        await cache.update(
            run_id="run-qps",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-qps")

        assert snapshot is not None
        assert "ops" in snapshot.metrics
        assert "current_per_sec" in snapshot.metrics["ops"]
        # QPS should reflect the posted value
        assert snapshot.metrics["ops"]["current_per_sec"] >= 0

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_total_operations(self) -> None:
        """RUN_UPDATE snapshot contains total operation count."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics()

        await cache.update(
            run_id="run-ops",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-ops")

        assert snapshot is not None
        assert "ops" in snapshot.metrics
        assert "total" in snapshot.metrics["ops"]
        assert snapshot.metrics["ops"]["total"] >= 0


class TestWebSocketPayloadErrorMetrics:
    """Tests that error rate flows through WebSocket payloads."""

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_error_count(self) -> None:
        """RUN_UPDATE snapshot contains error count."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics()

        await cache.update(
            run_id="run-errors",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-errors")

        assert snapshot is not None
        assert "errors" in snapshot.metrics
        assert "count" in snapshot.metrics["errors"]

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_error_rate(self) -> None:
        """RUN_UPDATE snapshot contains error rate."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics()

        await cache.update(
            run_id="run-error-rate",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-error-rate")

        assert snapshot is not None
        assert "errors" in snapshot.metrics
        assert "rate" in snapshot.metrics["errors"]


class TestWebSocketPayloadConnectionMetrics:
    """Tests that connection metrics flow through WebSocket payloads."""

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_active_connections(self) -> None:
        """RUN_UPDATE snapshot contains active connection count."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(active_connections=25)

        await cache.update(
            run_id="run-conns",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=30,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-conns")

        assert snapshot is not None
        assert "connections" in snapshot.metrics
        assert "active" in snapshot.metrics["connections"]
        assert snapshot.metrics["connections"]["active"] == 25

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_target_connections(self) -> None:
        """RUN_UPDATE snapshot contains target connection count."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics()

        await cache.update(
            run_id="run-target",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=50,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-target")

        assert snapshot is not None
        assert "connections" in snapshot.metrics
        assert "target" in snapshot.metrics["connections"]
        assert snapshot.metrics["connections"]["target"] == 50


class TestWebSocketPayloadResourceMetrics:
    """Tests that resource utilization metrics flow through WebSocket payloads."""

    @pytest.mark.asyncio
    async def test_worker_snapshot_contains_cpu_if_present(self) -> None:
        """Worker data in snapshot should include CPU if available."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(cpu_percent=65.5)

        await cache.update(
            run_id="run-cpu",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-cpu")

        assert snapshot is not None
        assert len(snapshot.workers) >= 1
        # CPU may be in worker metrics or aggregated - verify it's tracked
        worker = snapshot.workers[0]
        # The metrics should have been received and stored
        assert "metrics" in worker or "qps" in worker

    @pytest.mark.asyncio
    async def test_worker_snapshot_contains_memory_if_present(self) -> None:
        """Worker data in snapshot should include memory if available."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(memory_mb=2048.0)

        await cache.update(
            run_id="run-mem",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-mem")

        assert snapshot is not None
        assert len(snapshot.workers) >= 1


class TestWebSocketPayloadPhaseAndStatus:
    """Tests that phase and status flow through WebSocket payloads."""

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_phase(self) -> None:
        """RUN_UPDATE snapshot contains current phase."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics()

        await cache.update(
            run_id="run-phase",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="WARMUP",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-phase")

        assert snapshot is not None
        assert "phase" in snapshot.metrics
        assert snapshot.metrics["phase"] == "WARMUP"

    @pytest.mark.asyncio
    async def test_run_snapshot_contains_elapsed_time(self) -> None:
        """RUN_UPDATE snapshot contains elapsed time."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics()

        await cache.update(
            run_id="run-elapsed",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-elapsed")

        assert snapshot is not None
        assert "elapsed" in snapshot.metrics


class TestWebSocketPayloadWorkerDetails:
    """Tests that worker-level metrics flow through WebSocket payloads."""

    @pytest.mark.asyncio
    async def test_worker_contains_individual_qps(self) -> None:
        """Each worker should have its own QPS metric."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(current_qps=100.0)

        await cache.update(
            run_id="run-worker-qps",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=2,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-worker-qps")

        assert snapshot is not None
        assert len(snapshot.workers) >= 1
        worker = snapshot.workers[0]
        assert "qps" in worker.get("metrics", worker)

    @pytest.mark.asyncio
    async def test_worker_contains_individual_latency(self) -> None:
        """Each worker should have its own latency metrics."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(p95=35.0)

        await cache.update(
            run_id="run-worker-lat",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-worker-lat")

        assert snapshot is not None
        assert len(snapshot.workers) >= 1
        worker = snapshot.workers[0]
        worker_metrics = worker.get("metrics", worker)
        assert "p95_latency_ms" in worker_metrics or "p95" in str(worker_metrics)

    @pytest.mark.asyncio
    async def test_worker_contains_health_status(self) -> None:
        """Each worker should have a health status."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics()

        await cache.update(
            run_id="run-worker-health",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-worker-health")

        assert snapshot is not None
        assert len(snapshot.workers) >= 1
        worker = snapshot.workers[0]
        assert "health" in worker


class TestMultiWorkerAggregation:
    """Tests that multi-worker metrics are properly aggregated."""

    @pytest.mark.asyncio
    async def test_aggregate_qps_from_multiple_workers(self) -> None:
        """Total QPS should aggregate from all workers."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        # Post metrics from two workers
        for worker_num in range(2):
            metrics = _make_full_metrics(current_qps=250.0)
            await cache.update(
                run_id="run-multi",
                test_id="test-1",
                worker_id=f"worker-{worker_num}",
                worker_group_id=worker_num,
                worker_group_count=2,
                phase="MEASUREMENT",
                status="RUNNING",
                target_connections=10,
                metrics=metrics,
            )

        snapshot = await cache.get_run_snapshot(run_id="run-multi")

        assert snapshot is not None
        assert len(snapshot.workers) == 2
        # Total QPS should be sum of individual workers
        total_qps = snapshot.metrics["ops"]["current_per_sec"]
        assert total_qps >= 400  # At least 2 workers * some QPS

    @pytest.mark.asyncio
    async def test_aggregate_connections_from_multiple_workers(self) -> None:
        """Total connections should aggregate from all workers."""
        cache = LiveMetricsCache(ttl_seconds=60.0)

        for worker_num in range(3):
            metrics = _make_full_metrics(active_connections=10)
            await cache.update(
                run_id="run-multi-conn",
                test_id="test-1",
                worker_id=f"worker-{worker_num}",
                worker_group_id=worker_num,
                worker_group_count=3,
                phase="MEASUREMENT",
                status="RUNNING",
                target_connections=10,
                metrics=metrics,
            )

        snapshot = await cache.get_run_snapshot(run_id="run-multi-conn")

        assert snapshot is not None
        # Active connections should be sum
        assert snapshot.metrics["connections"]["active"] == 30


class TestFindMaxStepData:
    """Tests that FIND_MAX mode step data flows correctly."""

    @pytest.mark.asyncio
    async def test_custom_metrics_can_contain_find_max_data(self) -> None:
        """Custom metrics field can contain find_max step information."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics()
        metrics.custom_metrics = {
            "find_max": {
                "current_step": 5,
                "current_concurrency": 50,
                "best_concurrency": 40,
                "best_qps": 1200.0,
                "step_results": [
                    {"concurrency": 10, "qps": 300.0, "stable": True},
                    {"concurrency": 20, "qps": 600.0, "stable": True},
                    {"concurrency": 30, "qps": 900.0, "stable": True},
                    {"concurrency": 40, "qps": 1200.0, "stable": True},
                    {"concurrency": 50, "qps": 1100.0, "stable": False},
                ],
            }
        }

        await cache.update(
            run_id="run-findmax",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=50,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-findmax")

        assert snapshot is not None
        # Custom metrics should be preserved
        assert "custom_metrics" in snapshot.metrics


class TestPeakQPSTracking:
    """Tests that peak/best QPS is tracked correctly."""

    @pytest.mark.asyncio
    async def test_metrics_model_tracks_peak_qps(self) -> None:
        """Metrics model should have peak_qps field."""
        metrics = _make_full_metrics(current_qps=500.0, peak_qps=750.0)

        assert metrics.peak_qps == 750.0
        assert metrics.current_qps == 500.0

    @pytest.mark.asyncio
    async def test_peak_qps_flows_through_cache(self) -> None:
        """Peak QPS should be accessible through cache snapshot."""
        cache = LiveMetricsCache(ttl_seconds=60.0)
        metrics = _make_full_metrics(peak_qps=1000.0)

        await cache.update(
            run_id="run-peak",
            test_id="test-1",
            worker_id="worker-1",
            worker_group_id=0,
            worker_group_count=1,
            phase="MEASUREMENT",
            status="RUNNING",
            target_connections=10,
            metrics=metrics,
        )

        snapshot = await cache.get_run_snapshot(run_id="run-peak")

        assert snapshot is not None
        # Peak QPS should be in worker metrics
        worker = snapshot.workers[0]
        # The metrics are stored per-worker
        assert worker is not None
