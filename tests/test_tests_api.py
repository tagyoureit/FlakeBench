"""
Unit tests for /api/tests/* endpoints.

Tests test management API endpoints.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestGetTestStatus:
    """Tests for GET /api/test/{test_id}."""

    def test_get_test_status_success(self, client: TestClient) -> None:
        """Returns test status successfully."""
        response = client.get("/api/test/test-123")

        assert response.status_code == 200
        data = response.json()
        assert data["test_id"] == "test-123"
        assert "status" in data

    def test_get_test_status_returns_expected_fields(self, client: TestClient) -> None:
        """Response contains expected fields."""
        response = client.get("/api/test/test-456")

        assert response.status_code == 200
        data = response.json()
        # Current implementation returns mock data
        assert "test_id" in data
        assert "status" in data
        assert "duration" in data
        assert "elapsed" in data


class TestStopTest:
    """Tests for POST /api/test/{test_id}/stop."""

    def test_stop_test_success(self, client: TestClient) -> None:
        """Successfully stops a test."""
        response = client.post("/api/test/test-123/stop")

        assert response.status_code == 200
        data = response.json()
        assert data["test_id"] == "test-123"
        assert data["status"] == "stopped"


class TestPauseTest:
    """Tests for POST /api/test/{test_id}/pause."""

    def test_pause_test_success(self, client: TestClient) -> None:
        """Successfully pauses a test."""
        response = client.post("/api/test/test-123/pause")

        assert response.status_code == 200
        data = response.json()
        assert data["test_id"] == "test-123"
        assert data["status"] == "paused"


class TestStartTest:
    """Tests for POST /api/test/start."""

    def test_start_test_returns_test_id(self, client: TestClient) -> None:
        """Starting a test returns a test ID."""
        response = client.post(
            "/api/test/start",
            json={
                "duration": 300,
                "concurrent_connections": 10,
                "workload_type": "CUSTOM",
                "table_type": "STANDARD",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "test_id" in data
        assert data["status"] in ("running", "created")
        assert "started_at" in data


class TestCreateTest:
    """Tests for POST /api/test/create."""

    def test_create_test_returns_test_id(self, client: TestClient) -> None:
        """Creating a test returns a test ID."""
        response = client.post(
            "/api/test/create",
            json={
                "template_id": "test-template",
                "duration": 600,
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "test_id" in data
        assert data["status"] in ("running", "created")
