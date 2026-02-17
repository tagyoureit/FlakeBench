"""
Tests for /ai/generate-sql and /ai/validate-sql endpoints in templates.py (Item 6).

Covers:
- Generate SQL success (mocked AI_COMPLETE)
- Generate SQL no columns → 404
- Validate SQL success (mocked EXPLAIN)
- Validate SQL syntax error (mocked EXPLAIN failure)
- Validate SQL Postgres rejected → 400
- Request model validation (alias handling)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.api.routes.templates_modules.models import (
    AiGenerateSqlRequest,
    AiGenerateSqlResponse,
    AiValidateSqlRequest,
    AiValidateSqlResponse,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _mock_sf_pool(*, execute_results=None, execute_side_effect=None):
    """Build a mock Snowflake pool."""
    pool = AsyncMock()
    if execute_side_effect:
        pool.execute_query = AsyncMock(side_effect=execute_side_effect)
    elif execute_results is not None:
        pool.execute_query = AsyncMock(return_value=execute_results)
    else:
        pool.execute_query = AsyncMock(return_value=[])
    return pool


class TestAiGenerateSqlSuccess:
    """POST /ai/generate-sql with valid input and mocked AI."""

    @pytest.mark.asyncio
    async def test_returns_generated_sql(self, client: TestClient) -> None:
        # Mock column metadata query
        col_rows = [
            ("ID", "NUMBER", "NO"),
            ("NAME", "VARCHAR", "YES"),
            ("AMOUNT", "FLOAT", "YES"),
        ]
        ai_response = json.dumps(
            {
                "sql": "SELECT NAME, SUM(AMOUNT) FROM MYDB.PUBLIC.SALES GROUP BY NAME",
                "label": "Sales by Name",
                "operation_type": "READ",
                "explanation": "Aggregate sales amount grouped by name",
                "placeholders": [],
            }
        )

        call_count = 0

        async def _side_effect(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Column metadata query
                return col_rows
            else:
                # AI_COMPLETE call
                return [[ai_response]]

        pool = AsyncMock()
        pool.execute_query = AsyncMock(side_effect=_side_effect)

        with patch(
            "backend.api.routes.templates.snowflake_pool.get_default_pool",
            return_value=pool,
        ):
            response = client.post(
                "/api/templates/ai/generate-sql",
                json={
                    "database": "MYDB",
                    "schema": "PUBLIC",
                    "table_name": "SALES",
                    "table_type": "standard",
                    "intent": "aggregate sales by name",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert "sql" in data
        assert data["label"] == "Sales by Name"
        assert data["operation_type"] == "READ"

    @pytest.mark.asyncio
    async def test_no_columns_returns_404(self, client: TestClient) -> None:
        pool = AsyncMock()
        # Column query returns empty
        pool.execute_query = AsyncMock(return_value=[])

        with patch(
            "backend.api.routes.templates.snowflake_pool.get_default_pool",
            return_value=pool,
        ):
            response = client.post(
                "/api/templates/ai/generate-sql",
                json={
                    "database": "MYDB",
                    "schema": "PUBLIC",
                    "table_name": "EMPTY_TABLE",
                    "table_type": "standard",
                    "intent": "select all",
                },
            )

        assert response.status_code == 404
        assert "No columns" in response.json()["detail"]


class TestAiValidateSqlSuccess:
    """POST /ai/validate-sql with valid SQL (EXPLAIN succeeds)."""

    @pytest.mark.asyncio
    async def test_valid_sql(self, client: TestClient) -> None:
        pool = AsyncMock()
        # USE DATABASE, USE SCHEMA, and EXPLAIN all succeed
        pool.execute_query = AsyncMock(return_value=[])

        with patch(
            "backend.api.routes.templates.snowflake_pool.get_default_pool",
            return_value=pool,
        ):
            response = client.post(
                "/api/templates/ai/validate-sql",
                json={
                    "sql": "SELECT * FROM T1",
                    "database": "MYDB",
                    "schema": "PUBLIC",
                    "table_type": "standard",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is True
        assert data["error"] is None


class TestAiValidateSqlSyntaxError:
    """POST /ai/validate-sql when EXPLAIN fails."""

    @pytest.mark.asyncio
    async def test_syntax_error_returns_invalid(self, client: TestClient) -> None:
        call_count = 0

        async def _side_effect(query, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if "EXPLAIN" in query:
                raise Exception("SQL compilation error: syntax error near 'SELCT'")
            return []

        pool = AsyncMock()
        pool.execute_query = AsyncMock(side_effect=_side_effect)

        with patch(
            "backend.api.routes.templates.snowflake_pool.get_default_pool",
            return_value=pool,
        ):
            response = client.post(
                "/api/templates/ai/validate-sql",
                json={
                    "sql": "SELCT * FROM T1",
                    "database": "MYDB",
                    "schema": "PUBLIC",
                    "table_type": "standard",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["error"] is not None
        assert "syntax error" in data["error"].lower()


class TestAiValidateSqlPostgresRejected:
    """POST /ai/validate-sql with Postgres table type → 400."""

    @pytest.mark.asyncio
    async def test_postgres_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/templates/ai/validate-sql",
            json={
                "sql": "SELECT 1",
                "database": "MYDB",
                "schema": "PUBLIC",
                "table_type": "postgres",
            },
        )
        assert response.status_code == 400
        assert "Postgres" in response.json()["detail"]


class TestRequestModelValidation:
    """Test Pydantic model schema alias handling."""

    def test_ai_generate_sql_request_schema_alias(self) -> None:
        """schema field should accept both 'schema' and 'schema_name'."""
        # Using alias
        req = AiGenerateSqlRequest(
            database="DB",
            **{"schema": "SCH"},
            table_name="T",
            intent="test",
        )
        assert req.schema_name == "SCH"

    def test_ai_generate_sql_request_by_field_name(self) -> None:
        """populate_by_name=True allows schema_name directly."""
        req = AiGenerateSqlRequest(
            database="DB",
            schema_name="SCH",
            table_name="T",
            intent="test",
        )
        assert req.schema_name == "SCH"

    def test_ai_validate_sql_request_schema_alias(self) -> None:
        req = AiValidateSqlRequest(
            sql="SELECT 1",
            database="DB",
            **{"schema": "SCH"},
        )
        assert req.schema_name == "SCH"

    def test_ai_generate_sql_response_defaults(self) -> None:
        resp = AiGenerateSqlResponse(
            sql="SELECT 1",
            label="test",
        )
        assert resp.operation_type == "READ"
        assert resp.placeholders == []
        assert resp.explanation == ""
        assert resp.warnings == []

    def test_ai_validate_sql_response_valid(self) -> None:
        resp = AiValidateSqlResponse(valid=True)
        assert resp.error is None
        assert resp.warnings == []
