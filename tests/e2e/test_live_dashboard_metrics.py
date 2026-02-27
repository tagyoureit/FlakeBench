"""
E2E Tests: Live Dashboard Metrics Verification

Tests that live metrics displayed on the dashboard show correct non-zero values.

This test suite validates all dashboard metrics that were previously showing
zeros despite the test running:
- Latency metrics (p50, p95, p99, avg)
- In-flight queries
- Error rate
- Find Max state (current step, best QPS)
- Target SLOs
- Latency distribution chart data
- Concurrent queries
- Postgres running queries (pg_bench)
- Resources (CPU, memory)

Run with: E2E_TEST=1 uv run pytest tests/e2e/test_live_dashboard_metrics.py -v
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Any

import httpx
import pytest

try:
    import websockets
except ImportError:
    websockets = None

if TYPE_CHECKING:
    pass

pytestmark = [pytest.mark.e2e, pytest.mark.websocket, pytest.mark.asyncio]

if websockets is None:
    pytest.skip("websockets package required", allow_module_level=True)


class TestLiveMetricsNonZero:
    """Test that live metrics have non-zero values when workers are active."""

    async def test_latency_metrics_non_zero(
        self,
        live_server: str,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: A run with workers posting metrics including latency data
        WHEN: WebSocket client receives RUN_UPDATE events
        THEN: Latency metrics (p50, p95, p99) should be non-zero

        This test validates the critical bug where dashboard showed 0ms for all
        latency metrics even though workers were reporting valid latency data.
        """
        response = await live_client.post(
            "/api/runs/",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = response.json()["run_id"]

        await live_client.post(f"/api/runs/{run_id}/start")

        ws_url = live_server.replace("http://", "ws://") + f"/ws/test/{run_id}"

        async with websockets.connect(ws_url) as ws:
            for i in range(5):
                metrics_payload = {
                    "run_id": run_id,
                    "test_id": run_id,
                    "worker_id": f"e2e-worker-latency-{i:03d}",
                    "worker_group_id": i,
                    "worker_group_count": 5,
                    "phase": "MEASUREMENT",
                    "status": "RUNNING",
                    "target_connections": 10,
                    "metrics": {
                        "timestamp": "2024-12-01T12:00:00Z",
                        "elapsed_seconds": 30.0 + i,
                        "total_operations": 1000 * (i + 1),
                        "successful_operations": 1000 * (i + 1) - 5,
                        "failed_operations": 5,
                        "current_qps": 100.0 + i * 10,
                        "avg_qps": 100.0,
                        "read_metrics": {"count": 800 * (i + 1)},
                        "write_metrics": {"count": 200 * (i + 1)},
                        "overall_latency": {
                            "p50": 5.5,
                            "p75": 8.2,
                            "p90": 12.1,
                            "p95": 15.8,
                            "p99": 25.3,
                            "p999": 50.7,
                            "min": 1.2,
                            "max": 100.5,
                            "avg": 6.8,
                        },
                        "active_connections": 10,
                        "target_workers": 10,
                    },
                }
                await live_client.post(
                    f"/api/runs/{run_id}/metrics/live",
                    json=metrics_payload,
                )

            latency_found = None
            start = time.time()
            while time.time() - start < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1)
                    event = json.loads(msg)
                    if event.get("event") == "RUN_UPDATE":
                        data = event.get("data", {})
                        latency = data.get("latency")
                        if latency and isinstance(latency, dict):
                            if latency.get("p50", 0) > 0:
                                latency_found = latency
                                break
                except asyncio.TimeoutError:
                    continue

        assert latency_found is not None, (
            "No RUN_UPDATE with non-zero latency received. "
            "Bug: Dashboard shows 0ms for P50/P95/P99 latency."
        )
        assert latency_found.get("p50", 0) > 0, (
            f"P50 latency should be > 0, got {latency_found.get('p50')}. "
            "Bug: Workers posting latency but dashboard shows 0."
        )
        assert latency_found.get("p95", 0) > 0, (
            f"P95 latency should be > 0, got {latency_found.get('p95')}. "
            "Bug: Workers posting latency but dashboard shows 0."
        )
        assert latency_found.get("p99", 0) > 0, (
            f"P99 latency should be > 0, got {latency_found.get('p99')}. "
            "Bug: Workers posting latency but dashboard shows 0."
        )

    async def test_in_flight_queries_non_zero(
        self,
        live_server: str,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: A run with workers reporting active connections
        WHEN: WebSocket client receives RUN_UPDATE events
        THEN: In-flight/active connections should be non-zero

        This test validates the bug where in-flight queries showed 0
        even though workers were actively processing queries.
        """
        response = await live_client.post(
            "/api/runs/",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")

        ws_url = live_server.replace("http://", "ws://") + f"/ws/test/{run_id}"

        async with websockets.connect(ws_url) as ws:
            for i in range(3):
                metrics_payload = {
                    "run_id": run_id,
                    "test_id": run_id,
                    "worker_id": f"e2e-worker-inflight-{i:03d}",
                    "worker_group_id": i,
                    "worker_group_count": 3,
                    "phase": "MEASUREMENT",
                    "status": "RUNNING",
                    "target_connections": 50,
                    "metrics": {
                        "timestamp": "2024-12-01T12:00:00Z",
                        "elapsed_seconds": 30.0,
                        "total_operations": 1000,
                        "successful_operations": 995,
                        "failed_operations": 5,
                        "current_qps": 100.0,
                        "avg_qps": 100.0,
                        "read_metrics": {"count": 800},
                        "write_metrics": {"count": 200},
                        "overall_latency": {
                            "p50": 5.0,
                            "p75": 8.0,
                            "p90": 12.0,
                            "p95": 15.0,
                            "p99": 25.0,
                            "p999": 50.0,
                            "min": 1.0,
                            "max": 100.0,
                            "avg": 6.0,
                        },
                        "active_connections": 45,
                        "target_workers": 50,
                    },
                }
                await live_client.post(
                    f"/api/runs/{run_id}/metrics/live",
                    json=metrics_payload,
                )

            connections_found = None
            start = time.time()
            while time.time() - start < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1)
                    event = json.loads(msg)
                    if event.get("event") == "RUN_UPDATE":
                        data = event.get("data", {})
                        connections = data.get("connections")
                        if connections and isinstance(connections, dict):
                            if connections.get("active", 0) > 0:
                                connections_found = connections
                                break
                except asyncio.TimeoutError:
                    continue

        assert connections_found is not None, (
            "No RUN_UPDATE with non-zero active connections received. "
            "Bug: Dashboard shows 0 in-flight queries."
        )
        assert connections_found.get("active", 0) > 0, (
            f"Active connections should be > 0, got {connections_found.get('active')}. "
            "Bug: Workers reporting 45 active but dashboard shows 0."
        )
        assert connections_found.get("target", 0) > 0, (
            f"Target connections should be > 0, got {connections_found.get('target')}. "
        )

    async def test_error_metrics_present(
        self,
        live_server: str,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: A run with workers reporting errors
        WHEN: WebSocket client receives RUN_UPDATE events
        THEN: Error count and rate should reflect reported errors
        """
        response = await live_client.post(
            "/api/runs/",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")

        ws_url = live_server.replace("http://", "ws://") + f"/ws/test/{run_id}"

        async with websockets.connect(ws_url) as ws:
            metrics_payload = {
                "run_id": run_id,
                "test_id": run_id,
                "worker_id": "e2e-worker-errors-001",
                "worker_group_id": 0,
                "worker_group_count": 1,
                "phase": "MEASUREMENT",
                "status": "RUNNING",
                "target_connections": 10,
                "metrics": {
                    "timestamp": "2024-12-01T12:00:00Z",
                    "elapsed_seconds": 30.0,
                    "total_operations": 1000,
                    "successful_operations": 950,
                    "failed_operations": 50,
                    "current_qps": 100.0,
                    "avg_qps": 100.0,
                    "read_metrics": {"count": 800},
                    "write_metrics": {"count": 200},
                    "overall_latency": {
                        "p50": 5.0,
                        "p75": 8.0,
                        "p90": 12.0,
                        "p95": 15.0,
                        "p99": 25.0,
                        "p999": 50.0,
                        "min": 1.0,
                        "max": 100.0,
                        "avg": 6.0,
                    },
                    "active_connections": 10,
                    "target_workers": 10,
                },
            }
            await live_client.post(
                f"/api/runs/{run_id}/metrics/live",
                json=metrics_payload,
            )

            errors_found = None
            start = time.time()
            while time.time() - start < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1)
                    event = json.loads(msg)
                    if event.get("event") == "RUN_UPDATE":
                        data = event.get("data", {})
                        errors = data.get("errors")
                        if errors and isinstance(errors, dict):
                            if errors.get("count", 0) > 0:
                                errors_found = errors
                                break
                except asyncio.TimeoutError:
                    continue

        assert errors_found is not None, (
            "No RUN_UPDATE with error data received. "
            "Bug: Dashboard shows no error metrics."
        )
        assert errors_found.get("count", 0) > 0, (
            f"Error count should be > 0, got {errors_found.get('count')}. "
            "Bug: Worker reported 50 errors but dashboard shows 0."
        )

    async def test_custom_metrics_postgres_bench(
        self,
        live_server: str,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: A run with workers reporting Postgres-specific metrics (pg_bench)
        WHEN: WebSocket client receives RUN_UPDATE events
        THEN: Custom metrics including pg_bench should be present

        This validates postgres running queries and other pg-specific metrics.
        """
        response = await live_client.post(
            "/api/runs/",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")

        ws_url = live_server.replace("http://", "ws://") + f"/ws/test/{run_id}"

        async with websockets.connect(ws_url) as ws:
            metrics_payload = {
                "run_id": run_id,
                "test_id": run_id,
                "worker_id": "e2e-worker-pg-001",
                "worker_group_id": 0,
                "worker_group_count": 1,
                "phase": "MEASUREMENT",
                "status": "RUNNING",
                "target_connections": 10,
                "metrics": {
                    "timestamp": "2024-12-01T12:00:00Z",
                    "elapsed_seconds": 30.0,
                    "total_operations": 1000,
                    "successful_operations": 995,
                    "failed_operations": 5,
                    "current_qps": 100.0,
                    "avg_qps": 100.0,
                    "read_metrics": {"count": 800},
                    "write_metrics": {"count": 200},
                    "overall_latency": {
                        "p50": 5.0,
                        "p75": 8.0,
                        "p90": 12.0,
                        "p95": 15.0,
                        "p99": 25.0,
                        "p999": 50.0,
                        "min": 1.0,
                        "max": 100.0,
                        "avg": 6.0,
                    },
                    "active_connections": 10,
                    "target_workers": 10,
                    "custom_metrics": {
                        "pg_bench": {
                            "running_queries": 8,
                            "idle_in_transaction": 2,
                            "active_connections": 10,
                        },
                        "resources": {
                            "host_cpu_percent": 45.5,
                            "host_memory_percent": 62.3,
                            "cgroup_cpu_percent": 35.2,
                            "cgroup_memory_percent": 58.1,
                        },
                    },
                },
            }
            await live_client.post(
                f"/api/runs/{run_id}/metrics/live",
                json=metrics_payload,
            )

            custom_metrics_found = None
            start = time.time()
            while time.time() - start < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1)
                    event = json.loads(msg)
                    if event.get("event") == "RUN_UPDATE":
                        data = event.get("data", {})
                        custom = data.get("custom_metrics")
                        if custom and isinstance(custom, dict):
                            if custom.get("pg_bench"):
                                custom_metrics_found = custom
                                break
                except asyncio.TimeoutError:
                    continue

        assert custom_metrics_found is not None, (
            "No RUN_UPDATE with pg_bench custom metrics received. "
            "Bug: Postgres running queries not shown on dashboard."
        )
        pg_bench = custom_metrics_found.get("pg_bench", {})
        assert pg_bench.get("running_queries", 0) > 0, (
            f"pg_bench.running_queries should be > 0, got {pg_bench.get('running_queries')}. "
        )

    async def test_resources_cpu_memory(
        self,
        live_server: str,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: A run with workers reporting CPU/memory resources
        WHEN: WebSocket client receives RUN_UPDATE events
        THEN: Resource metrics should be present and non-zero
        """
        response = await live_client.post(
            "/api/runs/",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")

        ws_url = live_server.replace("http://", "ws://") + f"/ws/test/{run_id}"

        async with websockets.connect(ws_url) as ws:
            metrics_payload = {
                "run_id": run_id,
                "test_id": run_id,
                "worker_id": "e2e-worker-resources-001",
                "worker_group_id": 0,
                "worker_group_count": 1,
                "phase": "MEASUREMENT",
                "status": "RUNNING",
                "target_connections": 10,
                "metrics": {
                    "timestamp": "2024-12-01T12:00:00Z",
                    "elapsed_seconds": 30.0,
                    "total_operations": 1000,
                    "successful_operations": 995,
                    "failed_operations": 5,
                    "current_qps": 100.0,
                    "avg_qps": 100.0,
                    "read_metrics": {"count": 800},
                    "write_metrics": {"count": 200},
                    "overall_latency": {
                        "p50": 5.0,
                        "p75": 8.0,
                        "p90": 12.0,
                        "p95": 15.0,
                        "p99": 25.0,
                        "p999": 50.0,
                        "min": 1.0,
                        "max": 100.0,
                        "avg": 6.0,
                    },
                    "active_connections": 10,
                    "target_workers": 10,
                    "custom_metrics": {
                        "resources": {
                            "host_cpu_percent": 45.5,
                            "host_memory_percent": 62.3,
                            "cgroup_cpu_percent": 35.2,
                            "cgroup_memory_percent": 58.1,
                        },
                    },
                },
            }
            await live_client.post(
                f"/api/runs/{run_id}/metrics/live",
                json=metrics_payload,
            )

            resources_found = None
            start = time.time()
            while time.time() - start < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1)
                    event = json.loads(msg)
                    if event.get("event") == "RUN_UPDATE":
                        data = event.get("data", {})
                        custom = data.get("custom_metrics", {})
                        resources = custom.get("resources")
                        if resources and isinstance(resources, dict):
                            if resources.get("host_cpu_percent", 0) > 0:
                                resources_found = resources
                                break
                except asyncio.TimeoutError:
                    continue

        assert resources_found is not None, (
            "No RUN_UPDATE with resource metrics received. "
            "Bug: CPU/memory not shown on dashboard."
        )
        assert resources_found.get("host_cpu_percent", 0) > 0, (
            f"host_cpu_percent should be > 0, got {resources_found.get('host_cpu_percent')}. "
        )

    async def test_find_max_state_present(
        self,
        live_server: str,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: A run with Find Max controller reporting state
        WHEN: WebSocket client receives RUN_UPDATE events
        THEN: find_max state should be present with step info

        This validates the Find Max step numbers that were showing N/A.
        """
        response = await live_client.post(
            "/api/runs/",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")

        ws_url = live_server.replace("http://", "ws://") + f"/ws/test/{run_id}"

        async with websockets.connect(ws_url) as ws:
            metrics_payload = {
                "run_id": run_id,
                "test_id": run_id,
                "worker_id": "e2e-worker-findmax-001",
                "worker_group_id": 0,
                "worker_group_count": 1,
                "phase": "MEASUREMENT",
                "status": "RUNNING",
                "target_connections": 10,
                "metrics": {
                    "timestamp": "2024-12-01T12:00:00Z",
                    "elapsed_seconds": 30.0,
                    "total_operations": 1000,
                    "successful_operations": 995,
                    "failed_operations": 5,
                    "current_qps": 500.0,
                    "avg_qps": 480.0,
                    "read_metrics": {"count": 800},
                    "write_metrics": {"count": 200},
                    "overall_latency": {
                        "p50": 5.0,
                        "p75": 8.0,
                        "p90": 12.0,
                        "p95": 15.0,
                        "p99": 25.0,
                        "p999": 50.0,
                        "min": 1.0,
                        "max": 100.0,
                        "avg": 6.0,
                    },
                    "active_connections": 10,
                    "target_workers": 10,
                    "custom_metrics": {
                        "find_max_controller": {
                            "current_step": 3,
                            "target_workers": 50,
                            "best_qps": 450.0,
                            "best_step": 2,
                            "step_end_at_epoch_ms": 1704067200000,
                            "step_history": [
                                {"step": 1, "qps": 200, "workers": 10},
                                {"step": 2, "qps": 450, "workers": 30},
                                {"step": 3, "qps": 500, "workers": 50},
                            ],
                        },
                    },
                },
            }
            await live_client.post(
                f"/api/runs/{run_id}/metrics/live",
                json=metrics_payload,
            )

            find_max_found = None
            start = time.time()
            while time.time() - start < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1)
                    event = json.loads(msg)
                    if event.get("event") == "RUN_UPDATE":
                        data = event.get("data", {})
                        find_max = data.get("find_max")
                        if find_max and isinstance(find_max, dict):
                            if find_max.get("current_step") is not None:
                                find_max_found = find_max
                                break
                        custom = data.get("custom_metrics", {})
                        fmc = custom.get("find_max_controller")
                        if fmc and isinstance(fmc, dict):
                            if fmc.get("current_step") is not None:
                                find_max_found = fmc
                                break
                except asyncio.TimeoutError:
                    continue

        assert find_max_found is not None, (
            "No RUN_UPDATE with find_max state received. "
            "Bug: Find Max step numbers show N/A on dashboard."
        )
        assert find_max_found.get("current_step") is not None, (
            f"find_max.current_step should be present, got {find_max_found.get('current_step')}. "
        )


class TestWebSocketPayloadStructure:
    """Validate the structure of WebSocket payloads matches frontend expectations."""

    async def test_run_update_has_all_required_fields(
        self,
        live_server: str,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: A running test with metrics
        WHEN: WebSocket streams RUN_UPDATE
        THEN: Payload structure should match frontend expectations

        This ensures the WebSocket payload has all fields the dashboard expects.
        """
        response = await live_client.post(
            "/api/runs/",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")

        ws_url = live_server.replace("http://", "ws://") + f"/ws/test/{run_id}"

        async with websockets.connect(ws_url) as ws:
            metrics_payload = {
                "run_id": run_id,
                "test_id": run_id,
                "worker_id": "e2e-worker-structure-001",
                "worker_group_id": 0,
                "worker_group_count": 1,
                "phase": "MEASUREMENT",
                "status": "RUNNING",
                "target_connections": 10,
                "metrics": {
                    "timestamp": "2024-12-01T12:00:00Z",
                    "elapsed_seconds": 30.0,
                    "total_operations": 1000,
                    "successful_operations": 995,
                    "failed_operations": 5,
                    "current_qps": 100.0,
                    "avg_qps": 100.0,
                    "read_metrics": {"count": 800},
                    "write_metrics": {"count": 200},
                    "overall_latency": {
                        "p50": 5.5,
                        "p75": 8.2,
                        "p90": 12.1,
                        "p95": 15.8,
                        "p99": 25.3,
                        "p999": 50.7,
                        "min": 1.2,
                        "max": 100.5,
                        "avg": 6.8,
                    },
                    "active_connections": 10,
                    "target_workers": 10,
                },
            }
            await live_client.post(
                f"/api/runs/{run_id}/metrics/live",
                json=metrics_payload,
            )

            run_update = None
            start = time.time()
            while time.time() - start < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1)
                    event = json.loads(msg)
                    if event.get("event") == "RUN_UPDATE":
                        data = event.get("data", {})
                        if data.get("latency"):
                            run_update = data
                            break
                except asyncio.TimeoutError:
                    continue

        assert run_update is not None, "No RUN_UPDATE with complete data received"

        assert "status" in run_update, "Missing 'status' field"
        assert "phase" in run_update, "Missing 'phase' field"

        assert "ops" in run_update, "Missing 'ops' field"
        ops = run_update["ops"]
        assert "total" in ops, "Missing 'ops.total'"
        assert "current_per_sec" in ops, "Missing 'ops.current_per_sec' (QPS)"

        assert "latency" in run_update, "Missing 'latency' field"
        latency = run_update["latency"]
        assert "p50" in latency, "Missing 'latency.p50'"
        assert "p95" in latency, "Missing 'latency.p95'"
        assert "p99" in latency, "Missing 'latency.p99'"
        assert "avg" in latency, "Missing 'latency.avg'"

        assert "errors" in run_update, "Missing 'errors' field"
        errors = run_update["errors"]
        assert "count" in errors, "Missing 'errors.count'"
        assert "rate" in errors, "Missing 'errors.rate'"

        assert "connections" in run_update, "Missing 'connections' field"
        connections = run_update["connections"]
        assert "active" in connections, "Missing 'connections.active'"
        assert "target" in connections, "Missing 'connections.target'"

    async def test_latency_values_match_posted_metrics(
        self,
        live_server: str,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: Workers posting specific latency values
        WHEN: WebSocket streams the aggregated metrics
        THEN: Latency values should be close to what workers reported

        This is a regression test for the bug where latency was always 0.
        """
        response = await live_client.post(
            "/api/runs/",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")

        ws_url = live_server.replace("http://", "ws://") + f"/ws/test/{run_id}"

        posted_p50 = 12.34
        posted_p95 = 45.67
        posted_p99 = 89.01

        async with websockets.connect(ws_url) as ws:
            metrics_payload = {
                "run_id": run_id,
                "test_id": run_id,
                "worker_id": "e2e-worker-match-001",
                "worker_group_id": 0,
                "worker_group_count": 1,
                "phase": "MEASUREMENT",
                "status": "RUNNING",
                "target_connections": 10,
                "metrics": {
                    "timestamp": "2024-12-01T12:00:00Z",
                    "elapsed_seconds": 30.0,
                    "total_operations": 1000,
                    "successful_operations": 995,
                    "failed_operations": 5,
                    "current_qps": 100.0,
                    "avg_qps": 100.0,
                    "read_metrics": {"count": 800},
                    "write_metrics": {"count": 200},
                    "overall_latency": {
                        "p50": posted_p50,
                        "p75": 30.0,
                        "p90": 40.0,
                        "p95": posted_p95,
                        "p99": posted_p99,
                        "p999": 100.0,
                        "min": 1.0,
                        "max": 150.0,
                        "avg": 20.0,
                    },
                    "active_connections": 10,
                    "target_workers": 10,
                },
            }
            await live_client.post(
                f"/api/runs/{run_id}/metrics/live",
                json=metrics_payload,
            )

            received_latency = None
            start = time.time()
            while time.time() - start < 10:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=1)
                    event = json.loads(msg)
                    if event.get("event") == "RUN_UPDATE":
                        data = event.get("data", {})
                        latency = data.get("latency")
                        if latency and latency.get("p50", 0) > 0:
                            received_latency = latency
                            break
                except asyncio.TimeoutError:
                    continue

        assert received_latency is not None, (
            "No RUN_UPDATE with non-zero latency received"
        )

        tolerance = 1.0
        assert abs(received_latency["p50"] - posted_p50) < tolerance, (
            f"P50 mismatch: posted {posted_p50}, received {received_latency['p50']}"
        )
        assert abs(received_latency["p95"] - posted_p95) < tolerance, (
            f"P95 mismatch: posted {posted_p95}, received {received_latency['p95']}"
        )
        assert abs(received_latency["p99"] - posted_p99) < tolerance, (
            f"P99 mismatch: posted {posted_p99}, received {received_latency['p99']}"
        )
