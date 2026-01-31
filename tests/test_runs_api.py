"""
Tests for the /api/runs endpoints (Section 2.8 - Controller API Contract).

These tests use stubs/mocks to verify:
- API routing and response structure
- Error handling (404, 400, 503, 500)
- Integration between routes and OrchestratorService
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


@pytest.fixture
def client() -> TestClient:
    """FastAPI test client."""
    return TestClient(app)


class TestCreateRun:
    """Tests for POST /api/runs endpoint."""

    @pytest.mark.asyncio
    async def test_create_run_success(self, client: TestClient) -> None:
        """Create run returns 201 with run_id and PREPARED status."""
        # Arrange
        mock_template = {
            "template_id": "tmpl-123",
            "template_name": "test-template",
            "config": {"workload": {"duration_seconds": 60}},
        }
        mock_scenario = {"name": "test-scenario"}

        with (
            patch(
                "backend.api.routes.runs.registry._load_template",
                new_callable=AsyncMock,
                return_value=mock_template,
            ),
            patch(
                "backend.api.routes.runs.registry._scenario_from_template_config",
                return_value=mock_scenario,
            ),
            patch(
                "backend.api.routes.runs.orchestrator.create_run",
                new_callable=AsyncMock,
                return_value="run-abc123",
            ),
        ):
            # Act
            response = client.post("/api/runs", json={"template_id": "tmpl-123"})

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["run_id"] == "run-abc123"
        assert data["status"] == "PREPARED"
        assert data["dashboard_url"] == "/dashboard/run-abc123"

    @pytest.mark.asyncio
    async def test_create_run_template_not_found(self, client: TestClient) -> None:
        """Create run returns 404 when template doesn't exist."""
        # Arrange
        with patch(
            "backend.api.routes.runs.registry._load_template",
            new_callable=AsyncMock,
            side_effect=KeyError("Template not found"),
        ):
            # Act
            response = client.post(
                "/api/runs", json={"template_id": "nonexistent-template"}
            )

        # Assert
        assert response.status_code == 404
        assert "Template not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_run_invalid_config(self, client: TestClient) -> None:
        """Create run returns 400 for invalid configuration."""
        # Arrange
        mock_template = {
            "template_id": "tmpl-bad",
            "template_name": "bad-template",
            "config": {},
        }

        with (
            patch(
                "backend.api.routes.runs.registry._load_template",
                new_callable=AsyncMock,
                return_value=mock_template,
            ),
            patch(
                "backend.api.routes.runs.registry._scenario_from_template_config",
                side_effect=ValueError("Invalid workload configuration"),
            ),
        ):
            # Act
            response = client.post("/api/runs", json={"template_id": "tmpl-bad"})

        # Assert
        assert response.status_code == 400
        assert "Invalid workload configuration" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_run_snowflake_connectivity_error(
        self, client: TestClient
    ) -> None:
        """Create run returns 503 for Snowflake connectivity issues."""
        # Arrange
        mock_template = {
            "template_id": "tmpl-123",
            "template_name": "test-template",
            "config": {},
        }
        mock_scenario = {"name": "test-scenario"}

        with (
            patch(
                "backend.api.routes.runs.registry._load_template",
                new_callable=AsyncMock,
                return_value=mock_template,
            ),
            patch(
                "backend.api.routes.runs.registry._scenario_from_template_config",
                return_value=mock_scenario,
            ),
            patch(
                "backend.api.routes.runs.orchestrator.create_run",
                new_callable=AsyncMock,
                side_effect=Exception("IP/token is not allowed to access Snowflake"),
            ),
        ):
            # Act
            response = client.post("/api/runs", json={"template_id": "tmpl-123"})

        # Assert
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["code"] == "SNOWFLAKE_IP_NOT_ALLOWED"

    @pytest.mark.asyncio
    async def test_create_run_internal_error(self, client: TestClient) -> None:
        """Create run returns 500 for unexpected errors."""
        # Arrange
        mock_template = {
            "template_id": "tmpl-123",
            "template_name": "test-template",
            "config": {},
        }
        mock_scenario = {"name": "test-scenario"}

        with (
            patch(
                "backend.api.routes.runs.registry._load_template",
                new_callable=AsyncMock,
                return_value=mock_template,
            ),
            patch(
                "backend.api.routes.runs.registry._scenario_from_template_config",
                return_value=mock_scenario,
            ),
            patch(
                "backend.api.routes.runs.orchestrator.create_run",
                new_callable=AsyncMock,
                side_effect=Exception("Unexpected database error"),
            ),
        ):
            # Act
            response = client.post("/api/runs", json={"template_id": "tmpl-123"})

        # Assert
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail["code"] == "INTERNAL_ERROR"
        assert detail["operation"] == "create run"


class TestStartRun:
    """Tests for POST /api/runs/{run_id}/start endpoint."""

    @pytest.mark.asyncio
    async def test_start_run_success(self, client: TestClient) -> None:
        """Start run returns 202 with RUNNING status."""
        # Arrange
        with (
            patch(
                "backend.api.routes.runs.orchestrator.start_run",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.runs.orchestrator.get_run_status",
                new_callable=AsyncMock,
                return_value={"status": "RUNNING"},
            ),
        ):
            # Act
            response = client.post("/api/runs/run-123/start")

        # Assert
        assert response.status_code == 202
        data = response.json()
        assert data["run_id"] == "run-123"
        assert data["status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_start_run_not_found(self, client: TestClient) -> None:
        """Start run returns 404 when run doesn't exist."""
        # Arrange
        with patch(
            "backend.api.routes.runs.orchestrator.start_run",
            new_callable=AsyncMock,
            side_effect=ValueError("Run not found"),
        ):
            # Act
            response = client.post("/api/runs/nonexistent-run/start")

        # Assert
        assert response.status_code == 404
        assert "Run not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_start_run_returns_status_from_db(self, client: TestClient) -> None:
        """Start run returns actual status from RUN_STATUS table."""
        # Arrange - run might transition to WARMUP phase quickly
        with (
            patch(
                "backend.api.routes.runs.orchestrator.start_run",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.runs.orchestrator.get_run_status",
                new_callable=AsyncMock,
                return_value={"status": "running"},  # lowercase from DB
            ),
        ):
            # Act
            response = client.post("/api/runs/run-456/start")

        # Assert
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "RUNNING"  # uppercased

    @pytest.mark.asyncio
    async def test_start_run_fallback_when_status_none(
        self, client: TestClient
    ) -> None:
        """Start run returns RUNNING when get_run_status returns None."""
        # Arrange
        with (
            patch(
                "backend.api.routes.runs.orchestrator.start_run",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.runs.orchestrator.get_run_status",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            # Act
            response = client.post("/api/runs/run-789/start")

        # Assert
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_start_run_snowflake_error(self, client: TestClient) -> None:
        """Start run returns 503 for Snowflake connectivity issues."""
        # Arrange
        with patch(
            "backend.api.routes.runs.orchestrator.start_run",
            new_callable=AsyncMock,
            side_effect=Exception("Failed to connect to DB (08001)"),
        ):
            # Act
            response = client.post("/api/runs/run-123/start")

        # Assert
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["code"] == "SNOWFLAKE_CONNECTION_FAILED"


class TestStopRun:
    """Tests for POST /api/runs/{run_id}/stop endpoint."""

    @pytest.mark.asyncio
    async def test_stop_run_success(self, client: TestClient) -> None:
        """Stop run returns 202 with CANCELLING status."""
        # Arrange
        with (
            patch(
                "backend.api.routes.runs.orchestrator.stop_run",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.runs.orchestrator.get_run_status",
                new_callable=AsyncMock,
                return_value={"status": "CANCELLING"},
            ),
        ):
            # Act
            response = client.post("/api/runs/run-123/stop")

        # Assert
        assert response.status_code == 202
        data = response.json()
        assert data["run_id"] == "run-123"
        assert data["status"] == "CANCELLING"

    @pytest.mark.asyncio
    async def test_stop_run_not_found(self, client: TestClient) -> None:
        """Stop run returns 404 when run doesn't exist."""
        # Arrange
        with patch(
            "backend.api.routes.runs.orchestrator.stop_run",
            new_callable=AsyncMock,
            side_effect=ValueError("Run not found"),
        ):
            # Act
            response = client.post("/api/runs/nonexistent-run/stop")

        # Assert
        assert response.status_code == 404
        assert "Run not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_stop_run_already_cancelled(self, client: TestClient) -> None:
        """Stop run returns current status when run is already cancelled."""
        # Arrange
        with (
            patch(
                "backend.api.routes.runs.orchestrator.stop_run",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.runs.orchestrator.get_run_status",
                new_callable=AsyncMock,
                return_value={"status": "CANCELLED"},
            ),
        ):
            # Act
            response = client.post("/api/runs/run-done/stop")

        # Assert
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "CANCELLED"

    @pytest.mark.asyncio
    async def test_stop_run_fallback_when_status_none(self, client: TestClient) -> None:
        """Stop run returns CANCELLING when get_run_status returns None."""
        # Arrange
        with (
            patch(
                "backend.api.routes.runs.orchestrator.stop_run",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.runs.orchestrator.get_run_status",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            # Act
            response = client.post("/api/runs/run-xyz/stop")

        # Assert
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "CANCELLING"

    @pytest.mark.asyncio
    async def test_stop_run_internal_error(self, client: TestClient) -> None:
        """Stop run returns 500 for unexpected errors."""
        # Arrange
        with patch(
            "backend.api.routes.runs.orchestrator.stop_run",
            new_callable=AsyncMock,
            side_effect=Exception("Database timeout"),
        ):
            # Act
            response = client.post("/api/runs/run-123/stop")

        # Assert
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail["code"] == "INTERNAL_ERROR"
        assert detail["operation"] == "stop run"


class TestRequestValidation:
    """Tests for request body validation."""

    def test_create_run_missing_template_id(self, client: TestClient) -> None:
        """Create run returns 422 for missing template_id."""
        # Act
        response = client.post("/api/runs", json={})

        # Assert
        assert response.status_code == 422

    def test_create_run_invalid_json(self, client: TestClient) -> None:
        """Create run returns 422 for invalid JSON."""
        # Act
        response = client.post(
            "/api/runs",
            content="not valid json",
            headers={"Content-Type": "application/json"},
        )

        # Assert
        assert response.status_code == 422


class TestAutoscaleEndpoints:
    """Tests for the legacy autoscale endpoints that now delegate to OrchestratorService.

    These endpoints maintain API compatibility with the UI while routing through
    the orchestrator for proper RUN_STATUS management.
    """

    @pytest.mark.asyncio
    async def test_run_from_template_autoscale_success(
        self, client: TestClient
    ) -> None:
        """Autoscale endpoint creates run via orchestrator and returns 201."""
        # Arrange
        mock_template = {
            "template_id": "tmpl-auto-123",
            "template_name": "autoscale-template",
            "config": {
                "scaling": {"mode": "AUTO"},
                "workload": {"duration_seconds": 60},
            },
        }
        mock_scenario = {"name": "test-scenario"}

        with (
            patch(
                "backend.api.routes.test_results.registry._load_template",
                new_callable=AsyncMock,
                return_value=mock_template,
            ),
            patch(
                "backend.api.routes.test_results.registry._scenario_from_template_config",
                return_value=mock_scenario,
            ),
            patch(
                "backend.api.routes.test_results.orchestrator.create_run",
                new_callable=AsyncMock,
                return_value="run-auto-abc",
            ),
        ):
            # Act
            response = client.post("/api/tests/from-template/tmpl-auto-123/autoscale")

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["test_id"] == "run-auto-abc"
        assert data["dashboard_url"] == "/dashboard/run-auto-abc"

    @pytest.mark.asyncio
    async def test_run_from_template_autoscale_fixed_mode_rejected(
        self, client: TestClient
    ) -> None:
        """Autoscale endpoint returns 400 for FIXED scaling mode."""
        # Arrange
        mock_template = {
            "template_id": "tmpl-fixed",
            "template_name": "fixed-template",
            "config": {
                "scaling": {"mode": "FIXED"},
                "workload": {"duration_seconds": 60},
            },
        }

        with patch(
            "backend.api.routes.test_results.registry._load_template",
            new_callable=AsyncMock,
            return_value=mock_template,
        ):
            # Act
            response = client.post("/api/tests/from-template/tmpl-fixed/autoscale")

        # Assert
        assert response.status_code == 400
        assert "FIXED scaling mode" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_run_from_template_autoscale_template_not_found(
        self, client: TestClient
    ) -> None:
        """Autoscale endpoint returns 404 when template doesn't exist."""
        # Arrange
        with patch(
            "backend.api.routes.test_results.registry._load_template",
            new_callable=AsyncMock,
            side_effect=KeyError("Template not found"),
        ):
            # Act
            response = client.post("/api/tests/from-template/nonexistent/autoscale")

        # Assert
        assert response.status_code == 404
        assert "Template not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_run_from_template_autoscale_bounded_mode_allowed(
        self, client: TestClient
    ) -> None:
        """Autoscale endpoint accepts BOUNDED scaling mode."""
        # Arrange
        mock_template = {
            "template_id": "tmpl-bounded",
            "template_name": "bounded-template",
            "config": {
                "scaling": {"mode": "BOUNDED"},
                "workload": {"duration_seconds": 60},
            },
        }
        mock_scenario = {"name": "test-scenario"}

        with (
            patch(
                "backend.api.routes.test_results.registry._load_template",
                new_callable=AsyncMock,
                return_value=mock_template,
            ),
            patch(
                "backend.api.routes.test_results.registry._scenario_from_template_config",
                return_value=mock_scenario,
            ),
            patch(
                "backend.api.routes.test_results.orchestrator.create_run",
                new_callable=AsyncMock,
                return_value="run-bounded-xyz",
            ),
        ):
            # Act
            response = client.post("/api/tests/from-template/tmpl-bounded/autoscale")

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["test_id"] == "run-bounded-xyz"

    @pytest.mark.asyncio
    async def test_start_autoscale_success(self, client: TestClient) -> None:
        """Start autoscale endpoint starts run via orchestrator and returns 202."""
        # Arrange
        with (
            patch(
                "backend.api.routes.test_results.orchestrator.start_run",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.test_results.orchestrator.get_run_status",
                new_callable=AsyncMock,
                return_value={"status": "RUNNING"},
            ),
        ):
            # Act
            response = client.post("/api/tests/test-123/start-autoscale")

        # Assert
        assert response.status_code == 202
        data = response.json()
        assert data["test_id"] == "test-123"
        assert data["status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_start_autoscale_run_not_found(self, client: TestClient) -> None:
        """Start autoscale endpoint returns 404 when run doesn't exist."""
        # Arrange
        with patch(
            "backend.api.routes.test_results.orchestrator.start_run",
            new_callable=AsyncMock,
            side_effect=ValueError("Run not found"),
        ):
            # Act
            response = client.post("/api/tests/nonexistent/start-autoscale")

        # Assert
        assert response.status_code == 404
        assert "Run not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_start_autoscale_returns_status_from_db(
        self, client: TestClient
    ) -> None:
        """Start autoscale returns actual status from RUN_STATUS table."""
        # Arrange
        with (
            patch(
                "backend.api.routes.test_results.orchestrator.start_run",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.test_results.orchestrator.get_run_status",
                new_callable=AsyncMock,
                return_value={"status": "running"},  # lowercase from DB
            ),
        ):
            # Act
            response = client.post("/api/tests/test-456/start-autoscale")

        # Assert
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "RUNNING"  # uppercased

    @pytest.mark.asyncio
    async def test_start_autoscale_fallback_when_status_none(
        self, client: TestClient
    ) -> None:
        """Start autoscale returns RUNNING when get_run_status returns None."""
        # Arrange
        with (
            patch(
                "backend.api.routes.test_results.orchestrator.start_run",
                new_callable=AsyncMock,
            ),
            patch(
                "backend.api.routes.test_results.orchestrator.get_run_status",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            # Act
            response = client.post("/api/tests/test-789/start-autoscale")

        # Assert
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_start_autoscale_internal_error(self, client: TestClient) -> None:
        """Start autoscale returns 500 for unexpected errors."""
        # Arrange
        with patch(
            "backend.api.routes.test_results.orchestrator.start_run",
            new_callable=AsyncMock,
            side_effect=Exception("Unexpected error"),
        ):
            # Act
            response = client.post("/api/tests/test-err/start-autoscale")

        # Assert
        assert response.status_code == 500
        detail = response.json()["detail"]
        assert detail["code"] == "INTERNAL_ERROR"
        assert detail["operation"] == "start run"
