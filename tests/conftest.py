"""
Global pytest configuration and fixtures for FlakeBench tests.

This module provides:
- Real Snowflake database fixtures (E2E_TEST schema)
- FastAPI test client fixtures
- WebSocket test fixtures
- Test data seeding utilities

E2E tests use FLAKEBENCH.E2E_TEST schema (isolated from production).
Run `sql/schema/e2e_test_schema.sql` to set up the test schema.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncGenerator, Generator
from unittest.mock import patch

import httpx
import pytest
import pytest_asyncio
import snowflake.connector
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from snowflake.connector import SnowflakeConnection


# =============================================================================
# Environment Configuration
# =============================================================================

# E2E tests use a dedicated schema to avoid polluting production data
E2E_TEST_SCHEMA = "E2E_TEST"
E2E_TEST_DATABASE = os.getenv("E2E_TEST_DATABASE", "FLAKEBENCH")


def is_e2e_test() -> bool:
    """Check if we're running E2E tests (vs unit tests)."""
    return os.getenv("E2E_TEST", "").lower() in ("1", "true", "yes")


# =============================================================================
# Snowflake Connection Fixtures (Real Database)
# =============================================================================


@pytest.fixture(scope="session")
def snowflake_connection_params() -> dict:
    """
    Get Snowflake connection parameters from environment.
    
    Required environment variables:
    - SNOWFLAKE_ACCOUNT
    - SNOWFLAKE_USER
    - SNOWFLAKE_PASSWORD
    - SNOWFLAKE_WAREHOUSE
    - SNOWFLAKE_ROLE
    """
    from backend.config import settings
    
    return {
        "account": settings.SNOWFLAKE_ACCOUNT,
        "user": settings.SNOWFLAKE_USER,
        "password": settings.SNOWFLAKE_PASSWORD,
        "warehouse": settings.SNOWFLAKE_WAREHOUSE,
        "role": settings.SNOWFLAKE_ROLE,
        "database": E2E_TEST_DATABASE,
        "schema": E2E_TEST_SCHEMA,
    }


@pytest.fixture(scope="session")
def snowflake_conn(snowflake_connection_params: dict) -> Generator[SnowflakeConnection, None, None]:
    """
    Session-scoped Snowflake connection for E2E tests.
    
    Uses the E2E_TEST schema to isolate test data from production.
    """
    if not is_e2e_test():
        pytest.skip("E2E tests require E2E_TEST=1 environment variable")
    
    conn = snowflake.connector.connect(**snowflake_connection_params)
    
    # Verify we're connected to the test schema
    cursor = conn.cursor()
    cursor.execute(f"USE DATABASE {E2E_TEST_DATABASE}")
    cursor.execute(f"USE SCHEMA {E2E_TEST_SCHEMA}")
    cursor.close()
    
    yield conn
    
    conn.close()


@pytest.fixture
def db_cursor(snowflake_conn: SnowflakeConnection):
    """
    Per-test database cursor with automatic cleanup.
    """
    cursor = snowflake_conn.cursor()
    yield cursor
    cursor.close()


@pytest.fixture
def clean_test_data(snowflake_conn: SnowflakeConnection):
    """
    Clean up test data before and after each test.
    
    Calls the E2E_CLEANUP() stored procedure to reset state.
    """
    cursor = snowflake_conn.cursor()
    
    # Clean before test
    cursor.execute("CALL E2E_CLEANUP()")
    
    yield
    
    # Clean after test
    cursor.execute("CALL E2E_CLEANUP()")
    cursor.close()


# =============================================================================
# Test Data Factories
# =============================================================================


@pytest.fixture
def test_run_id() -> str:
    """Generate a unique run ID for each test."""
    return f"e2e-run-{uuid.uuid4().hex[:12]}"


@pytest.fixture
def create_test_run(snowflake_conn: SnowflakeConnection):
    """
    Factory fixture to create test runs in RUN_STATUS table.
    
    Usage:
        run_id = create_test_run(status="PREPARED", phase="PREPARING")
    """
    created_run_ids: list[str] = []
    
    def _create_run(
        run_id: str | None = None,
        status: str = "PREPARED",
        phase: str = "PREPARING",
        test_name: str = "E2E Test Run",
        total_workers: int = 1,
    ) -> str:
        if run_id is None:
            run_id = f"e2e-run-{uuid.uuid4().hex[:12]}"
        
        cursor = snowflake_conn.cursor()
        cursor.execute(
            """
            INSERT INTO RUN_STATUS (
                run_id, test_id, test_name, status, phase,
                total_workers_expected, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
            )
            """,
            (run_id, run_id, test_name, status, phase, total_workers),
        )
        cursor.close()
        
        created_run_ids.append(run_id)
        return run_id
    
    yield _create_run
    
    # Cleanup created runs
    if created_run_ids:
        cursor = snowflake_conn.cursor()
        for rid in created_run_ids:
            cursor.execute("DELETE FROM WORKER_HEARTBEATS WHERE run_id = %s", (rid,))
            cursor.execute("DELETE FROM RUN_CONTROL_EVENTS WHERE run_id = %s", (rid,))
            cursor.execute("DELETE FROM RUN_STATUS WHERE run_id = %s", (rid,))
        cursor.close()


@pytest.fixture
def create_control_event(snowflake_conn: SnowflakeConnection):
    """
    Factory fixture to create control events in RUN_CONTROL_EVENTS table.
    
    Usage:
        event_id = create_control_event(run_id, "START", {"scope": "ALL"})
    """
    import json
    
    def _create_event(
        run_id: str,
        event_type: str,
        event_data: dict,
        sequence_id: int = 1,
    ) -> str:
        event_id = f"evt-{uuid.uuid4().hex[:12]}"
        
        cursor = snowflake_conn.cursor()
        cursor.execute(
            """
            INSERT INTO RUN_CONTROL_EVENTS (
                event_id, run_id, event_type, event_data, sequence_id, created_at
            ) VALUES (
                %s, %s, %s, PARSE_JSON(%s), %s, CURRENT_TIMESTAMP()
            )
            """,
            (event_id, run_id, event_type, json.dumps(event_data), sequence_id),
        )
        cursor.close()
        
        return event_id
    
    return _create_event


# =============================================================================
# FastAPI Test Client Fixtures
# =============================================================================


@pytest.fixture
def client() -> TestClient:
    """
    Synchronous FastAPI test client for unit tests.
    
    Uses mocked dependencies by default.
    """
    from backend.main import app
    return TestClient(app)


@pytest.fixture
def e2e_client(snowflake_conn: SnowflakeConnection) -> TestClient:
    """
    E2E test client that uses real Snowflake connections.
    
    Patches the settings to use E2E_TEST schema.
    """
    if not is_e2e_test():
        pytest.skip("E2E tests require E2E_TEST=1 environment variable")
    
    from backend.main import app
    
    with patch("backend.config.settings.RESULTS_SCHEMA", E2E_TEST_SCHEMA):
        yield TestClient(app)


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Async HTTP client for testing against a running server.
    
    Use this for integration tests that need the full async stack.
    """
    from backend.main import app
    
    async with httpx.AsyncClient(app=app, base_url="http://test", follow_redirects=True) as client:
        yield client


# =============================================================================
# WebSocket Test Fixtures
# =============================================================================


@pytest.fixture
def websocket_url() -> str:
    """Base WebSocket URL for tests."""
    return "ws://test/ws/test"


@asynccontextmanager
async def connect_websocket(run_id: str, base_url: str = "ws://localhost:8000"):
    """
    Async context manager for WebSocket connections in tests.
    
    Usage:
        async with connect_websocket("run-123") as ws:
            message = await ws.recv()
    """
    import websockets
    
    url = f"{base_url}/ws/test/{run_id}"
    async with websockets.connect(url) as websocket:
        yield websocket


# =============================================================================
# Event Loop Configuration
# =============================================================================


@pytest.fixture(scope="session")
def event_loop():
    """
    Session-scoped event loop for async tests.
    
    Required for session-scoped async fixtures.
    """
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Test Markers
# =============================================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "e2e: marks tests as end-to-end tests requiring real database (deselect with '-m \"not e2e\"')",
    )
    config.addinivalue_line(
        "markers",
        "websocket: marks tests that test WebSocket functionality",
    )
    config.addinivalue_line(
        "markers",
        "browser: marks tests that use Playwright browser automation",
    )
    config.addinivalue_line(
        "markers",
        "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    )


# =============================================================================
# Skip Conditions
# =============================================================================


def pytest_collection_modifyitems(config, items):
    """
    Automatically skip E2E tests unless E2E_TEST=1 is set.
    """
    skip_e2e = pytest.mark.skip(reason="E2E tests require E2E_TEST=1")
    
    for item in items:
        if "e2e" in item.keywords and not is_e2e_test():
            item.add_marker(skip_e2e)
