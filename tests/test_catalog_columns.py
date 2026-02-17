"""
Tests for the /columns endpoint in catalog.py (Item 4).

Covers:
- Snowflake success response (mocked) — returns column list
- Missing params → 400
- _validate_ident rejects SQL-injection-like identifiers
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.api.routes.catalog import _validate_ident


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestValidateIdent:
    """Unit tests for the _validate_ident helper."""

    def test_valid_uppercase(self) -> None:
        assert _validate_ident("MY_TABLE", label="table") == "MY_TABLE"

    def test_valid_with_numbers(self) -> None:
        assert _validate_ident("TABLE_123", label="table") == "TABLE_123"

    def test_lowercased_input_uppercased(self) -> None:
        assert _validate_ident("my_table", label="table") == "MY_TABLE"

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="Missing table"):
            _validate_ident("", label="table")

    def test_none_raises(self) -> None:
        with pytest.raises(ValueError, match="Missing table"):
            _validate_ident(None, label="table")

    def test_sql_injection_semicolon_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_ident("T1; DROP TABLE T2--", label="table")

    def test_sql_injection_quote_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_ident("T1' OR '1'='1", label="table")

    def test_dash_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_ident("MY-TABLE", label="table")

    def test_space_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_ident("MY TABLE", label="table")

    def test_dot_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid"):
            _validate_ident("DB.SCHEMA.TABLE", label="table")


class TestColumnsEndpointSnowflake:
    """Tests for GET /api/catalog/columns with Snowflake backend."""

    @pytest.mark.asyncio
    async def test_success_response(self, client: TestClient) -> None:
        mock_rows = [
            ("COL_A", "VARCHAR", 1, "YES"),
            ("COL_B", "NUMBER", 2, "NO"),
        ]
        mock_pool = AsyncMock()
        mock_pool.execute_query = AsyncMock(return_value=mock_rows)

        with patch(
            "backend.api.routes.catalog.snowflake_pool.get_default_pool",
            return_value=mock_pool,
        ):
            response = client.get(
                "/api/catalog/columns",
                params={
                    "table_type": "standard",
                    "database": "MYDB",
                    "schema": "PUBLIC",
                    "table": "USERS",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["name"] == "COL_A"
        assert data[0]["data_type"] == "VARCHAR"
        assert data[0]["ordinal_position"] == 1
        assert data[0]["is_nullable"] == "YES"
        assert data[1]["name"] == "COL_B"
        assert data[1]["data_type"] == "NUMBER"
        assert data[1]["ordinal_position"] == 2
        assert data[1]["is_nullable"] == "NO"

    @pytest.mark.asyncio
    async def test_invalid_database_returns_400(self, client: TestClient) -> None:
        response = client.get(
            "/api/catalog/columns",
            params={
                "table_type": "standard",
                "database": "BAD;DB",
                "schema": "PUBLIC",
                "table": "USERS",
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_schema_returns_400(self, client: TestClient) -> None:
        response = client.get(
            "/api/catalog/columns",
            params={
                "table_type": "standard",
                "database": "MYDB",
                "schema": "BAD SCHEMA",
                "table": "USERS",
            },
        )
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_table_returns_400(self, client: TestClient) -> None:
        response = client.get(
            "/api/catalog/columns",
            params={
                "table_type": "standard",
                "database": "MYDB",
                "schema": "PUBLIC",
                "table": "T' OR 1=1--",
            },
        )
        assert response.status_code == 400
