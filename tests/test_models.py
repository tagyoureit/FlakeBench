#!/usr/bin/env python3
"""
Test script for Pydantic data models.

Validates model creation, validation, and serialization.
"""

import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.models import (
    TableType,
    TableConfig,
    WarehouseSize,
    ScalingPolicy,
    WarehouseConfig,
    WorkloadType,
    TestScenario,
    TestStatus,
    TestResult,
    TestRun,
    Metrics,
    MetricsSnapshot,
    LatencyPercentiles,
)


def test_table_config():
    """Test TableConfig model."""
    print("\n🔍 Testing TableConfig")
    print("=" * 60)

    try:
        # Standard table
        standard_table = TableConfig(
            name="test_standard",
            table_type=TableType.STANDARD,
            columns={
                "id": "NUMBER",
                "date": "DATE",
                "customer_id": "VARCHAR",
                "amount": "DECIMAL(10,2)",
            },
            initial_row_count=1000000,
        )
        print(f"✅ Standard table created: {standard_table.name}")

        # Hybrid table (existing table; primary key is not required by the app)
        hybrid_table = TableConfig(
            name="test_hybrid",
            table_type=TableType.HYBRID,
            columns={
                "id": "NUMBER",
                "customer_id": "VARCHAR",
                "date": "DATE",
                "amount": "DECIMAL(10,2)",
            },
            initial_row_count=100000,
        )
        print(f"✅ Hybrid table created: {hybrid_table.name}")

        # Interactive table (requires CLUSTER BY)
        interactive_table = TableConfig(
            name="test_interactive",
            table_type=TableType.INTERACTIVE,
            cluster_by=["date", "region"],
            columns={
                "id": "NUMBER",
                "date": "DATE",
                "region": "VARCHAR",
                "value": "DECIMAL",
            },
            cache_warming_enabled=True,
        )
        print(f"✅ Interactive table created: {interactive_table.name}")

        # Hybrid without PK should still validate (table creation is disabled)
        try:
            TableConfig(
                name="bad_hybrid",
                table_type=TableType.HYBRID,
                columns={"id": "NUMBER"},
            )
            print("✅ Hybrid config without PK validated (expected)")
        except ValueError as e:
            print(f"❌ Unexpected validation error: {e}")
            return False

        return True

    except Exception as e:
        print(f"❌ TableConfig test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_warehouse_config():
    """Test WarehouseConfig model."""
    print("\n🔍 Testing WarehouseConfig")
    print("=" * 60)

    try:
        # Single-cluster warehouse
        small_wh = WarehouseConfig(
            name="TEST_SMALL_WH",
            size=WarehouseSize.SMALL,
            auto_suspend_seconds=300,
            auto_resume=True,
        )
        print(f"✅ Single-cluster warehouse: {small_wh.name} ({small_wh.size})")

        # Multi-cluster warehouse
        large_wh = WarehouseConfig(
            name="TEST_LARGE_WH",
            size=WarehouseSize.LARGE,
            min_cluster_count=2,
            max_cluster_count=5,
            scaling_policy=ScalingPolicy.ECONOMY,
        )
        print(
            f"✅ Multi-cluster warehouse: {large_wh.name} ({large_wh.min_cluster_count}-{large_wh.max_cluster_count})"
        )

        # Test validation (max < min should fail)
        try:
            WarehouseConfig(
                name="BAD_WH",
                size=WarehouseSize.MEDIUM,
                min_cluster_count=5,
                max_cluster_count=2,
            )
            print("❌ Should have failed: max < min clusters")
            return False
        except ValueError as e:
            print(f"✅ Validation works: {e}")

        return True

    except Exception as e:
        print(f"❌ WarehouseConfig test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_test_scenario():
    """Test TestScenario model."""
    print("\n🔍 Testing TestScenario")
    print("=" * 60)

    try:
        # Read-heavy workload
        table = TableConfig(
            name="test_table",
            table_type=TableType.STANDARD,
            columns={"id": "NUMBER", "value": "VARCHAR"},
        )

        warehouse = WarehouseConfig(
            name="TEST_WH",
            size=WarehouseSize.MEDIUM,
        )

        scenario = TestScenario(
            name="read_heavy_test",
            description="80/20 read/write test",
            duration_seconds=120,
            warmup_seconds=10,
            concurrent_connections=50,
            workload_type=WorkloadType.READ_HEAVY,
            read_batch_size=100,
            write_batch_size=10,
            metrics_interval_seconds=1.0,
            table_configs=[table],
            warehouse_configs=[warehouse],
            tags={"test_type": "performance", "environment": "dev"},
        )
        print(f"✅ Test scenario created: {scenario.name}")
        print(f"   Duration: {scenario.duration_seconds}s")
        print(f"   Connections: {scenario.concurrent_connections}")
        print(f"   Workload: {scenario.workload_type}")

        # Custom query scenario
        custom_scenario = TestScenario(
            name="custom_queries",
            duration_seconds=60,
            concurrent_connections=10,
            workload_type=WorkloadType.CUSTOM,
            custom_queries=[
                {
                    "query_kind": "POINT_LOOKUP",
                    "weight_pct": 70,
                    "sql": "SELECT * FROM {table} WHERE id = ?",
                },
                {
                    "query_kind": "INSERT",
                    "weight_pct": 30,
                    "sql": "INSERT INTO {table} (id, value) VALUES (?, ?)",
                },
            ],
            table_configs=[table],
        )
        print(f"✅ Custom scenario created: {custom_scenario.name}")

        # Test validation (CUSTOM without queries should fail)
        try:
            TestScenario(
                name="bad_custom",
                duration_seconds=60,
                concurrent_connections=10,
                workload_type=WorkloadType.CUSTOM,
                table_configs=[table],
            )
            print("❌ Should have failed: CUSTOM without queries")
            return False
        except ValueError as e:
            print(f"✅ Validation works: {e}")

        return True

    except Exception as e:
        print(f"❌ TestScenario test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_test_result():
    """Test TestResult model."""
    print("\n🔍 Testing TestResult")
    print("=" * 60)

    try:
        result = TestResult(
            test_name="performance_test_1",
            scenario_name="read_heavy_test",
            table_name="test_standard",
            table_type="standard",
            warehouse="TEST_WH",
            warehouse_size="Medium",
            status=TestStatus.COMPLETED,
            start_time=datetime.now(),
            end_time=datetime.now(),
            duration_seconds=120.5,
            concurrent_connections=50,
            total_operations=12000,
            read_operations=9600,
            write_operations=2400,
            qps=99.6,
            avg_latency_ms=15.2,
            p95_latency_ms=45.3,
            p99_latency_ms=78.9,
            bytes_read=1024000,
            bytes_written=256000,
        )

        print(f"✅ Test result created: {result.test_name}")
        print(f"   Test ID: {result.test_id}")
        print(f"   Status: {result.status}")
        print(f"   Operations: {result.total_operations}")
        print(f"   QPS: {result.qps:.2f}")
        print(f"   P95 latency: {result.p95_latency_ms:.2f}ms")

        # Test JSON serialization
        json_data = result.model_dump_json()
        print(f"✅ JSON serialization works ({len(json_data)} bytes)")

        return True

    except Exception as e:
        print(f"❌ TestResult test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_test_run():
    """Test TestRun model."""
    print("\n🔍 Testing TestRun")
    print("=" * 60)

    try:
        run = TestRun(
            run_name="comparison_run_1",
            description="Compare standard vs hybrid tables",
            status=TestStatus.RUNNING,
            start_time=datetime.now(),
            snowflake_account="myaccount.us-east-1",
            client_version="0.1.0",
        )

        # Add test results
        result1 = TestResult(
            test_name="standard_table_test",
            scenario_name="read_heavy",
            table_name="test_standard",
            table_type="standard",
            status=TestStatus.COMPLETED,
            start_time=datetime.now(),
            concurrent_connections=50,
            qps=120.5,
        )

        result2 = TestResult(
            test_name="hybrid_table_test",
            scenario_name="read_heavy",
            table_name="test_hybrid",
            table_type="hybrid",
            status=TestStatus.COMPLETED,
            start_time=datetime.now(),
            concurrent_connections=50,
            qps=145.8,
        )

        run.add_test_result(result1)
        run.add_test_result(result2)
        run.calculate_summary()

        print(f"✅ Test run created: {run.run_name}")
        print(f"   Run ID: {run.run_id}")
        print(f"   Total tests: {run.total_tests}")
        print(f"   Successful: {run.successful_tests}")

        return True

    except Exception as e:
        print(f"❌ TestRun test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_metrics():
    """Test Metrics model."""
    print("\n🔍 Testing Metrics")
    print("=" * 60)

    try:
        metrics = Metrics(
            elapsed_seconds=30.5,
            total_operations=3050,
            successful_operations=3048,
            failed_operations=2,
            current_qps=102.3,
            avg_qps=100.0,
            peak_qps=125.6,
            active_connections=50,
            idle_connections=5,
        )

        # Set latency
        metrics.overall_latency = LatencyPercentiles(
            p50=12.5,
            p95=45.2,
            p99=78.9,
            avg=18.3,
            min=2.1,
            max=156.4,
        )

        print("✅ Metrics created")
        print(f"   Operations: {metrics.total_operations}")
        print(f"   QPS: {metrics.current_qps:.2f}")
        print(f"   P95 latency: {metrics.overall_latency.p95:.2f}ms")
        print(f"   Success rate: {metrics.success_rate:.4f}")

        # Test WebSocket payload
        payload = metrics.to_websocket_payload()
        print(f"✅ WebSocket payload created ({len(str(payload))} bytes)")

        # Test snapshot
        MetricsSnapshot.from_metrics(metrics)
        print("✅ Metrics snapshot created")

        return True

    except Exception as e:
        print(f"❌ Metrics test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def main():
    """Run all model tests."""
    print("=" * 60)
    print("🧪 Running Data Model Tests")
    print("=" * 60)

    tests = [
        ("TableConfig", test_table_config),
        ("WarehouseConfig", test_warehouse_config),
        ("TestScenario", test_test_scenario),
        ("TestResult", test_test_result),
        ("TestRun", test_test_run),
        ("Metrics", test_metrics),
    ]

    results = []
    for name, test_func in tests:
        result = test_func()
        results.append((name, result))

    print("\n" + "=" * 60)
    print("📊 Test Results Summary")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")

    print()
    print(f"Total: {passed}/{total} tests passed")

    if passed == total:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
