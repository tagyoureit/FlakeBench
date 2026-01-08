"""
Tests for MetricsCollector.

These are async unit tests (pytest-asyncio) validating metrics aggregation,
percentile calculation, snapshots, reset, and summary stats.
"""

import asyncio
import random

import pytest

from backend.core.metrics_collector import (
    MetricsCollector,
    OperationResult,
    OperationType,
)

pytestmark = pytest.mark.asyncio


async def test_collector_creation() -> None:
    collector = MetricsCollector(
        window_size=1000,
        snapshot_interval_seconds=1.0,
    )
    collector.start()

    assert collector.metrics.total_operations == 0
    assert collector.metrics.successful_operations == 0
    assert len(collector.snapshots) == 0


async def test_operation_recording() -> None:
    collector = MetricsCollector()
    collector.start()

    # Successful read
    await collector.record_operation(
        OperationResult(
            operation_type=OperationType.READ,
            success=True,
            latency_ms=15.5,
            rows_affected=100,
            bytes_transferred=10240,
        )
    )

    # Successful write
    await collector.record_operation(
        OperationResult(
            operation_type=OperationType.WRITE,
            success=True,
            latency_ms=25.3,
            rows_affected=10,
            bytes_transferred=2048,
        )
    )

    # Failed read
    await collector.record_operation(
        OperationResult(
            operation_type=OperationType.READ,
            success=False,
            latency_ms=50.0,
        )
    )

    metrics = await collector.get_metrics()
    assert metrics.total_operations == 3
    assert metrics.successful_operations == 2
    assert metrics.failed_operations == 1
    assert metrics.read_metrics.count == 2
    assert metrics.write_metrics.count == 1
    assert metrics.rows_read == 100
    assert metrics.rows_written == 10


async def test_percentile_calculation() -> None:
    collector = MetricsCollector()
    collector.start()

    latencies = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    for lat in latencies:
        await collector.record_operation(
            OperationResult(
                operation_type=OperationType.READ,
                success=True,
                latency_ms=float(lat),
            )
        )

    metrics = await collector.calculate_metrics()
    percentiles = metrics.overall_latency

    assert percentiles.min == 10.0
    assert percentiles.max == 100.0
    assert percentiles.avg == 55.0
    assert 45 <= percentiles.p50 <= 60  # median-ish


async def test_throughput_calculation() -> None:
    collector = MetricsCollector()
    collector.start()

    for _ in range(100):
        await collector.record_operation(
            OperationResult(
                operation_type=OperationType.READ,
                success=True,
                latency_ms=random.uniform(10, 50),
                rows_affected=100,
                bytes_transferred=10240,
            )
        )

    await asyncio.sleep(0.05)
    metrics = await collector.calculate_metrics()

    assert metrics.total_operations == 100
    assert metrics.elapsed_seconds > 0
    assert metrics.avg_ops_per_second > 0
    assert metrics.rows_per_second > 0
    assert metrics.bytes_per_second > 0


async def test_snapshot_creation() -> None:
    collector = MetricsCollector()
    collector.start()

    for _ in range(50):
        await collector.record_operation(
            OperationResult(
                operation_type=OperationType.READ,
                success=True,
                latency_ms=random.uniform(10, 50),
            )
        )

    snapshot = await collector.create_snapshot()
    assert len(collector.snapshots) == 1
    assert collector.snapshots[0] == snapshot

    for _ in range(5):
        await collector.record_operation(
            OperationResult(
                operation_type=OperationType.WRITE,
                success=True,
                latency_ms=random.uniform(20, 60),
            )
        )
        await collector.create_snapshot()

    recent = collector.get_snapshots(limit=3)
    assert len(recent) == 3


async def test_metrics_reset() -> None:
    collector = MetricsCollector()
    collector.start()

    for _ in range(20):
        await collector.record_operation(
            OperationResult(
                operation_type=OperationType.READ,
                success=True,
                latency_ms=random.uniform(10, 50),
            )
        )

    metrics_before = await collector.get_metrics()
    assert metrics_before.total_operations == 20

    await collector.reset()

    metrics_after = await collector.get_metrics()
    assert metrics_after.total_operations == 0
    assert metrics_after.successful_operations == 0
    assert len(collector.snapshots) == 0


async def test_summary_stats() -> None:
    collector = MetricsCollector()
    collector.start()

    for _ in range(80):
        await collector.record_operation(
            OperationResult(
                operation_type=OperationType.READ,
                success=True,
                latency_ms=random.uniform(10, 50),
            )
        )

    for _ in range(20):
        await collector.record_operation(
            OperationResult(
                operation_type=OperationType.WRITE,
                success=True,
                latency_ms=random.uniform(20, 60),
            )
        )

    for _ in range(5):
        await collector.record_operation(
            OperationResult(
                operation_type=OperationType.READ,
                success=False,
                latency_ms=100.0,
            )
        )

    await asyncio.sleep(0.05)
    await collector.calculate_metrics()

    summary = collector.get_summary()

    assert summary["total_operations"] == 105
    assert summary["successful_operations"] == 100
    assert summary["failed_operations"] == 5
    assert summary["read_operations"] == 85
    assert summary["write_operations"] == 20
