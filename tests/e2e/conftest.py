"""
E2E Test Fixtures - Real infrastructure configuration.

This module extends the global conftest.py with E2E-specific fixtures:
- Live server management
- Database state assertions
- WebSocket event collectors
- Timing utilities
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, AsyncGenerator, Generator

import httpx
import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from snowflake.connector import SnowflakeConnection


# =============================================================================
# Live Server Fixtures
# =============================================================================

E2E_SERVER_PORT = int(os.getenv("E2E_SERVER_PORT", "8765"))
E2E_SERVER_HOST = os.getenv("E2E_SERVER_HOST", "127.0.0.1")
E2E_BASE_URL = f"http://{E2E_SERVER_HOST}:{E2E_SERVER_PORT}"
E2E_WS_URL = f"ws://{E2E_SERVER_HOST}:{E2E_SERVER_PORT}"


@pytest.fixture(scope="session")
def live_server_url() -> str:
    """Base URL for the live test server."""
    return E2E_BASE_URL


@pytest.fixture(scope="session")
def live_ws_url() -> str:
    """WebSocket URL for the live test server."""
    return E2E_WS_URL


@pytest.fixture(scope="module")
def live_server() -> Generator[str, None, None]:
    """
    Start a live server for E2E tests.
    
    Launches uvicorn in a subprocess and waits for it to be ready.
    Server is killed after the test module completes.
    
    Yields the base URL of the running server.
    """
    import signal
    
    env = os.environ.copy()
    env["E2E_TEST"] = "1"
    env["RESULTS_SCHEMA"] = "E2E_TEST"
    
    # Start server
    process = subprocess.Popen(
        [
            "uv", "run", "uvicorn",
            "backend.main:app",
            "--host", E2E_SERVER_HOST,
            "--port", str(E2E_SERVER_PORT),
            "--log-level", "warning",
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    
    # Wait for server to be ready
    max_wait = 30
    start_time = time.time()
    server_ready = False
    
    while time.time() - start_time < max_wait:
        try:
            response = httpx.get(f"{E2E_BASE_URL}/health", timeout=1)
            if response.status_code == 200:
                server_ready = True
                break
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        time.sleep(0.5)
    
    if not server_ready:
        process.kill()
        stdout, stderr = process.communicate()
        raise RuntimeError(
            f"Server failed to start within {max_wait}s.\n"
            f"stdout: {stdout.decode()}\n"
            f"stderr: {stderr.decode()}"
        )
    
    yield E2E_BASE_URL
    
    # Cleanup
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


# =============================================================================
# HTTP Client Fixtures
# =============================================================================


@pytest_asyncio.fixture
async def live_client(live_server: str) -> AsyncGenerator[httpx.AsyncClient, None]:
    """
    Async HTTP client connected to the live test server.
    """
    async with httpx.AsyncClient(base_url=live_server, timeout=300, follow_redirects=True) as client:
        yield client


# =============================================================================
# Database State Assertions
# =============================================================================


@dataclass
class RunState:
    """Snapshot of a run's state from the database."""
    run_id: str
    status: str
    phase: str
    total_ops: int = 0
    error_count: int = 0
    current_qps: float = 0.0
    workers_registered: int = 0
    workers_active: int = 0


@pytest.fixture
def get_run_state(snowflake_conn: "SnowflakeConnection"):
    """
    Factory fixture to query run state from RUN_STATUS table.
    
    Usage:
        state = get_run_state(run_id)
        assert state.status == "RUNNING"
        assert state.phase == "MEASUREMENT"
    """
    def _get_state(run_id: str) -> RunState | None:
        cursor = snowflake_conn.cursor()
        cursor.execute(
            """
            SELECT run_id, status, phase, total_ops, error_count, 
                   current_qps, workers_registered, workers_active
            FROM RUN_STATUS
            WHERE run_id = %s
            """,
            (run_id,),
        )
        row = cursor.fetchone()
        cursor.close()
        
        if row is None:
            return None
        
        return RunState(
            run_id=row[0],
            status=row[1],
            phase=row[2],
            total_ops=row[3] or 0,
            error_count=row[4] or 0,
            current_qps=row[5] or 0.0,
            workers_registered=row[6] or 0,
            workers_active=row[7] or 0,
        )
    
    return _get_state


@pytest.fixture
def get_control_events(snowflake_conn: "SnowflakeConnection"):
    """
    Factory fixture to query control events for a run.
    
    Usage:
        events = get_control_events(run_id)
        assert len(events) == 2
        assert events[0]["event_type"] == "START"
    """
    def _get_events(run_id: str) -> list[dict]:
        cursor = snowflake_conn.cursor()
        cursor.execute(
            """
            SELECT event_id, event_type, event_data, sequence_id, created_at
            FROM RUN_CONTROL_EVENTS
            WHERE run_id = %s
            ORDER BY sequence_id ASC
            """,
            (run_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
        
        return [
            {
                "event_id": row[0],
                "event_type": row[1],
                "event_data": json.loads(row[2]) if isinstance(row[2], str) else row[2],
                "sequence_id": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]
    
    return _get_events


# =============================================================================
# WebSocket Event Collector
# =============================================================================


@dataclass
class WebSocketEventCollector:
    """
    Collects WebSocket events for assertion.
    
    Usage:
        collector = WebSocketEventCollector()
        async with collector.connect(run_id):
            await asyncio.sleep(5)
        
        assert collector.has_event("RUN_UPDATE")
        updates = collector.get_events("RUN_UPDATE")
    """
    events: list[dict] = field(default_factory=list)
    _task: asyncio.Task | None = None
    _stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    
    def has_event(self, event_type: str) -> bool:
        """Check if any event of the given type was received."""
        return any(e.get("event") == event_type for e in self.events)
    
    def get_events(self, event_type: str) -> list[dict]:
        """Get all events of the given type."""
        return [e for e in self.events if e.get("event") == event_type]
    
    def count_events(self, event_type: str) -> int:
        """Count events of the given type."""
        return len(self.get_events(event_type))
    
    async def connect(self, run_id: str, base_url: str = E2E_WS_URL):
        """
        Connect to WebSocket and start collecting events.
        
        Returns an async context manager.
        """
        import websockets
        
        url = f"{base_url}/ws/test/{run_id}"
        
        async def _collect():
            try:
                async with websockets.connect(url) as ws:
                    while not self._stop_event.is_set():
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                            event = json.loads(msg)
                            self.events.append(event)
                        except asyncio.TimeoutError:
                            continue
            except Exception:
                pass
        
        self._task = asyncio.create_task(_collect())
        return self
    
    async def stop(self):
        """Stop collecting events."""
        self._stop_event.set()
        if self._task:
            await asyncio.wait_for(self._task, timeout=2)
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.stop()


@pytest.fixture
def ws_collector() -> WebSocketEventCollector:
    """Fresh WebSocket event collector for each test."""
    return WebSocketEventCollector()


# =============================================================================
# Timing Utilities
# =============================================================================


@pytest.fixture
def wait_for_status(get_run_state):
    """
    Wait for a run to reach a specific status.
    
    Usage:
        await wait_for_status(run_id, "RUNNING", timeout=10)
    """
    async def _wait(run_id: str, expected_status: str, timeout: float = 30) -> RunState:
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            state = get_run_state(run_id)
            if state and state.status == expected_status:
                return state
            await asyncio.sleep(0.5)
        
        current_state = get_run_state(run_id)
        raise TimeoutError(
            f"Run {run_id} did not reach status '{expected_status}' within {timeout}s. "
            f"Current state: {current_state}"
        )
    
    return _wait


@pytest.fixture
def wait_for_phase(get_run_state):
    """
    Wait for a run to reach a specific phase.
    
    Usage:
        await wait_for_phase(run_id, "MEASUREMENT", timeout=10)
    """
    async def _wait(run_id: str, expected_phase: str, timeout: float = 30) -> RunState:
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            state = get_run_state(run_id)
            if state and state.phase == expected_phase:
                return state
            await asyncio.sleep(0.5)
        
        current_state = get_run_state(run_id)
        raise TimeoutError(
            f"Run {run_id} did not reach phase '{expected_phase}' within {timeout}s. "
            f"Current state: {current_state}"
        )
    
    return _wait
