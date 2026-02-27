"""
Unit tests for /api/connections/* endpoints.

Tests connection CRUD operations with mocked connection_manager.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.models.connection import (
    ConnectionResponse,
    ConnectionTestResponse,
    ConnectionType,
)


@pytest.fixture
def mock_connection_response() -> ConnectionResponse:
    """Create a mock connection response."""
    return ConnectionResponse(
        connection_id="conn-123",
        connection_name="test-connection",
        connection_type=ConnectionType.SNOWFLAKE,
        account="test-account",
        is_default=False,
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        username="test-user",
        has_password=True,
        has_private_key=False,
    )


class TestListConnections:
    """Tests for GET /api/connections/."""

    def test_list_connections_empty(self, client: TestClient) -> None:
        """Returns empty list when no connections exist."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.list_connections = AsyncMock(return_value=[])

            response = client.get("/api/connections/")

            assert response.status_code == 200
            data = response.json()
            assert data["connections"] == []
            assert data["total"] == 0

    def test_list_connections_returns_all(
        self, client: TestClient, mock_connection_response: ConnectionResponse
    ) -> None:
        """Returns all connections."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.list_connections = AsyncMock(
                return_value=[mock_connection_response]
            )

            response = client.get("/api/connections/")

            assert response.status_code == 200
            data = response.json()
            assert len(data["connections"]) == 1
            assert data["total"] == 1
            assert data["connections"][0]["connection_name"] == "test-connection"

    def test_list_connections_with_type_filter(
        self, client: TestClient, mock_connection_response: ConnectionResponse
    ) -> None:
        """Filters connections by type."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.list_connections = AsyncMock(
                return_value=[mock_connection_response]
            )

            response = client.get("/api/connections/?connection_type=SNOWFLAKE")

            assert response.status_code == 200
            mock_cm.list_connections.assert_called_once()
            call_kwargs = mock_cm.list_connections.call_args.kwargs
            assert call_kwargs["connection_type"] == ConnectionType.SNOWFLAKE


class TestCreateConnection:
    """Tests for POST /api/connections/."""

    def test_create_connection_success(
        self, client: TestClient, mock_connection_response: ConnectionResponse
    ) -> None:
        """Successfully creates a connection."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.create_connection = AsyncMock(return_value=mock_connection_response)

            response = client.post(
                "/api/connections/",
                json={
                    "connection_name": "new-connection",
                    "connection_type": "SNOWFLAKE",
                    "account": "test-account",
                    "username": "user",
                    "password": "pass",
                },
            )

            assert response.status_code == 201
            data = response.json()
            assert data["connection_name"] == "test-connection"

    def test_create_connection_duplicate_name_fails(self, client: TestClient) -> None:
        """Returns 409 when connection name already exists."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.create_connection = AsyncMock(
                side_effect=Exception("unique constraint violation")
            )

            response = client.post(
                "/api/connections/",
                json={
                    "connection_name": "existing-connection",
                    "connection_type": "SNOWFLAKE",
                    "account": "test-account",
                },
            )

            assert response.status_code == 409
            assert "already exists" in response.json()["detail"]

    def test_create_connection_missing_account_fails(self, client: TestClient) -> None:
        """Returns 400 when Snowflake connection missing account."""
        response = client.post(
            "/api/connections/",
            json={
                "connection_name": "bad-connection",
                "connection_type": "SNOWFLAKE",
                # Missing required 'account' field
            },
        )

        assert response.status_code == 400


class TestGetConnection:
    """Tests for GET /api/connections/{connection_id}."""

    def test_get_connection_success(
        self, client: TestClient, mock_connection_response: ConnectionResponse
    ) -> None:
        """Returns connection by ID."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.get_connection = AsyncMock(return_value=mock_connection_response)

            response = client.get("/api/connections/conn-123")

            assert response.status_code == 200
            data = response.json()
            assert data["connection_id"] == "conn-123"
            assert data["connection_name"] == "test-connection"

    def test_get_connection_not_found(self, client: TestClient) -> None:
        """Returns 404 when connection not found."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.get_connection = AsyncMock(return_value=None)

            response = client.get("/api/connections/nonexistent")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()


class TestUpdateConnection:
    """Tests for PUT /api/connections/{connection_id}."""

    def test_update_connection_success(
        self, client: TestClient, mock_connection_response: ConnectionResponse
    ) -> None:
        """Successfully updates a connection."""
        updated = mock_connection_response.model_copy()
        updated.connection_name = "updated-name"

        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.update_connection = AsyncMock(return_value=updated)

            response = client.put(
                "/api/connections/conn-123",
                json={"connection_name": "updated-name"},
            )

            assert response.status_code == 200
            assert response.json()["connection_name"] == "updated-name"

    def test_update_connection_not_found(self, client: TestClient) -> None:
        """Returns 404 when connection not found."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.update_connection = AsyncMock(return_value=None)

            response = client.put(
                "/api/connections/nonexistent",
                json={"connection_name": "new-name"},
            )

            assert response.status_code == 404


class TestDeleteConnection:
    """Tests for DELETE /api/connections/{connection_id}."""

    def test_delete_connection_success(
        self, client: TestClient, mock_connection_response: ConnectionResponse
    ) -> None:
        """Successfully deletes a connection."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.get_connection = AsyncMock(return_value=mock_connection_response)
            mock_cm.delete_connection = AsyncMock(return_value=None)

            response = client.delete("/api/connections/conn-123")

            assert response.status_code == 204

    def test_delete_connection_not_found(self, client: TestClient) -> None:
        """Returns 404 when connection not found."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.get_connection = AsyncMock(return_value=None)

            response = client.delete("/api/connections/nonexistent")

            assert response.status_code == 404


class TestTestConnection:
    """Tests for POST /api/connections/{connection_id}/test."""

    def test_test_connection_success(
        self, client: TestClient, mock_connection_response: ConnectionResponse
    ) -> None:
        """Successfully tests a connection."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.get_connection = AsyncMock(return_value=mock_connection_response)
            mock_cm.test_connection = AsyncMock(
                return_value=ConnectionTestResponse(
                    success=True,
                    message="Connection successful",
                    latency_ms=45.2,
                    server_version="8.0.1",
                )
            )

            response = client.post("/api/connections/conn-123/test")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["latency_ms"] == 45.2

    def test_test_connection_invalid_credentials(
        self, client: TestClient, mock_connection_response: ConnectionResponse
    ) -> None:
        """Returns failure result when credentials are invalid."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.get_connection = AsyncMock(return_value=mock_connection_response)
            mock_cm.test_connection = AsyncMock(
                return_value=ConnectionTestResponse(
                    success=False,
                    message="Authentication failed: invalid credentials",
                    latency_ms=None,
                    server_version=None,
                )
            )

            response = client.post("/api/connections/conn-123/test")

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is False
            assert "failed" in data["message"].lower()

    def test_test_connection_not_found(self, client: TestClient) -> None:
        """Returns 404 when connection not found."""
        with patch("backend.api.routes.connections.connection_manager") as mock_cm:
            mock_cm.get_connection = AsyncMock(return_value=None)

            response = client.post("/api/connections/nonexistent/test")

            assert response.status_code == 404
