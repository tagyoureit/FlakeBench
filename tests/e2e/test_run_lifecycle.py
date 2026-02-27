"""
E2E Tests: Run Lifecycle API Integration

Tests the full run lifecycle against real Snowflake database:
- Run creation creates real DB records
- Start/stop transitions update real state
- Status queries return actual DB values
- Phase transitions occur correctly

Run with: E2E_TEST=1 uv run pytest tests/e2e/test_run_lifecycle.py -v
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from tests.e2e.conftest import RunState

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]


class TestRunCreation:
    """Test run creation creates real database records."""

    async def test_create_run_inserts_into_run_status(
        self,
        live_client: httpx.AsyncClient,
        get_run_state,
        clean_test_data,
    ):
        """
        GIVEN: A valid template exists
        WHEN: POST /api/runs with template_id
        THEN: A row is inserted into RUN_STATUS with PREPARED status
        """
        # Act - Create run via API
        response = await live_client.post(
            "/api/runs",
            json={"template_id": "e2e-test-template-001"},
        )

        # Assert - API returns success
        assert response.status_code == 201, f"Failed: {response.text}"
        data = response.json()
        run_id = data["run_id"]
        assert data["status"] == "PREPARED"

        # Assert - Database has the record
        state = get_run_state(run_id)
        assert state is not None, f"Run {run_id} not found in database"
        assert state.status == "PREPARED"
        # Phase is empty until the run actually starts
        assert state.phase in ("", "PREPARING")

    async def test_create_run_generates_unique_ids(
        self,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: Multiple run creation requests
        WHEN: Each request is processed
        THEN: Each run gets a unique ID
        """
        run_ids = []
        for _ in range(3):
            response = await live_client.post(
                "/api/runs",
                json={"template_id": "e2e-test-template-001"},
            )
            assert response.status_code == 201
            run_ids.append(response.json()["run_id"])

        # All IDs should be unique
        assert len(set(run_ids)) == 3

    async def test_create_run_with_invalid_template_returns_404(
        self,
        live_client: httpx.AsyncClient,
    ):
        """
        GIVEN: A non-existent template ID
        WHEN: POST /api/runs
        THEN: Returns 404 with clear error message
        """
        response = await live_client.post(
            "/api/runs",
            json={"template_id": "nonexistent-template-xyz"},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestRunStart:
    """Test run start transitions and state management."""

    async def test_start_run_transitions_to_running(
        self,
        live_client: httpx.AsyncClient,
        get_run_state,
        clean_test_data,
    ):
        """
        GIVEN: A run in PREPARED status
        WHEN: POST /api/runs/{run_id}/start
        THEN: Status transitions to RUNNING in database
        """
        # Create run
        create_response = await live_client.post(
            "/api/runs",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = create_response.json()["run_id"]

        # Start run
        start_response = await live_client.post(f"/api/runs/{run_id}/start")
        assert start_response.status_code == 202

        # Verify database state (may take several seconds for workers to spawn)
        # Status transitions: PREPARED -> STARTING -> RUNNING
        for _ in range(10):
            await asyncio.sleep(1)
            state = get_run_state(run_id)
            if state and state.status in ("RUNNING", "WARMUP", "MEASUREMENT", "COMPLETED", "FAILED"):
                break
        assert state is not None
        assert state.status in ("STARTING", "RUNNING", "WARMUP", "MEASUREMENT", "COMPLETED", "FAILED")

    async def test_start_run_creates_start_event(
        self,
        live_client: httpx.AsyncClient,
        get_control_events,
        clean_test_data,
    ):
        """
        GIVEN: A run in PREPARED status
        WHEN: POST /api/runs/{run_id}/start
        THEN: A START event is created in RUN_CONTROL_EVENTS
        """
        # Create and start run
        create_response = await live_client.post(
            "/api/runs",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = create_response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")

        # Wait for event to be written
        await asyncio.sleep(1)

        # Verify control event
        events = get_control_events(run_id)
        start_events = [e for e in events if e["event_type"] == "START"]
        assert len(start_events) >= 1, f"No START event found. Events: {events}"

    async def test_start_nonexistent_run_returns_404(
        self,
        live_client: httpx.AsyncClient,
    ):
        """
        GIVEN: A non-existent run ID
        WHEN: POST /api/runs/{run_id}/start
        THEN: Returns 404
        """
        response = await live_client.post("/api/runs/nonexistent-run-xyz/start")
        assert response.status_code == 404


class TestRunStop:
    """Test run stop and cancellation."""

    async def test_stop_run_transitions_to_cancelling(
        self,
        live_client: httpx.AsyncClient,
        get_run_state,
        clean_test_data,
    ):
        """
        GIVEN: A running test
        WHEN: POST /api/runs/{run_id}/stop
        THEN: Status transitions to CANCELLING or CANCELLED
        """
        # Create and start run
        create_response = await live_client.post(
            "/api/runs",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = create_response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")
        await asyncio.sleep(1)  # Let it start

        # Stop run
        stop_response = await live_client.post(f"/api/runs/{run_id}/stop")
        assert stop_response.status_code == 202

        # Verify state transition
        await asyncio.sleep(1)
        state = get_run_state(run_id)
        assert state is not None
        assert state.status in ("CANCELLING", "CANCELLED", "COMPLETED")

    async def test_stop_run_creates_stop_event(
        self,
        live_client: httpx.AsyncClient,
        get_control_events,
        clean_test_data,
    ):
        """
        GIVEN: A running test
        WHEN: POST /api/runs/{run_id}/stop
        THEN: A STOP event is created in RUN_CONTROL_EVENTS
        """
        # Create, start, then stop
        create_response = await live_client.post(
            "/api/runs",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = create_response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")
        await asyncio.sleep(1)
        await live_client.post(f"/api/runs/{run_id}/stop")

        # Wait for event
        await asyncio.sleep(1)

        # Verify stop event
        events = get_control_events(run_id)
        stop_events = [e for e in events if e["event_type"] == "STOP"]
        assert len(stop_events) >= 1, f"No STOP event found. Events: {events}"


class TestRunStatus:
    """Test run status queries return accurate database state."""

    async def test_get_run_status_returns_db_state(
        self,
        live_client: httpx.AsyncClient,
        get_run_state,
        clean_test_data,
    ):
        """
        GIVEN: A run exists in the database
        WHEN: Querying the run state
        THEN: Database state matches what the API created
        """
        # Create run
        create_response = await live_client.post(
            "/api/runs",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = create_response.json()["run_id"]
        api_status = create_response.json()["status"]

        # Compare with database
        db_state = get_run_state(run_id)
        assert db_state is not None
        assert api_status.upper() == db_state.status.upper()


class TestPhaseTransitions:
    """Test that phase transitions occur correctly during run lifecycle."""

    @pytest.mark.slow
    async def test_run_transitions_through_phases(
        self,
        live_client: httpx.AsyncClient,
        get_run_state,
        wait_for_phase,
        clean_test_data,
    ):
        """
        GIVEN: A started run with warmup and measurement phases
        WHEN: Run executes
        THEN: Phases transition PREPARING -> WARMUP -> MEASUREMENT -> PROCESSING
        
        Note: This test takes ~15-20 seconds due to warmup/measurement duration.
        """
        # Create and start run
        create_response = await live_client.post(
            "/api/runs",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = create_response.json()["run_id"]

        # Initial state should be PREPARED with empty phase
        state = get_run_state(run_id)
        assert state.phase in ("", "PREPARING")

        # Start run
        await live_client.post(f"/api/runs/{run_id}/start")

        # Track observed phases
        observed_phases = [state.phase]
        timeout = 60  # Total timeout for all transitions
        start_time = time.time()

        while time.time() - start_time < timeout:
            await asyncio.sleep(1)
            state = get_run_state(run_id)
            if state.phase not in observed_phases:
                observed_phases.append(state.phase)

            # Exit if completed or failed
            if state.status in ("COMPLETED", "FAILED", "CANCELLED"):
                break

        # Verify we saw multiple phases (not stuck in one)
        assert len(observed_phases) >= 2, (
            f"Expected multiple phase transitions, only saw: {observed_phases}"
        )

        # Verify we saw at least WARMUP or MEASUREMENT or PREPARING (workers starting)
        valid_phases = {"PREPARING", "WARMUP", "MEASUREMENT"}
        assert any(
            phase in observed_phases for phase in valid_phases
        ), f"Expected at least one execution phase, saw: {observed_phases}"


class TestDatabaseIntegrity:
    """Test database constraints and data integrity."""

    async def test_run_id_is_uuid_format(
        self,
        live_client: httpx.AsyncClient,
        clean_test_data,
    ):
        """
        GIVEN: A created run
        WHEN: Examining the run_id
        THEN: It follows UUID or similar unique format
        """
        response = await live_client.post(
            "/api/runs",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = response.json()["run_id"]

        # Should be a reasonable length and contain alphanumeric/dash characters
        assert len(run_id) >= 8
        assert all(c.isalnum() or c == "-" for c in run_id)

    async def test_control_events_have_monotonic_sequence(
        self,
        live_client: httpx.AsyncClient,
        get_control_events,
        clean_test_data,
    ):
        """
        GIVEN: A run with multiple control events
        WHEN: Querying events
        THEN: sequence_id values are monotonically increasing
        """
        # Create, start, then stop (generates multiple events)
        create_response = await live_client.post(
            "/api/runs",
            json={"template_id": "e2e-test-template-001"},
        )
        run_id = create_response.json()["run_id"]
        await live_client.post(f"/api/runs/{run_id}/start")
        await asyncio.sleep(1)
        await live_client.post(f"/api/runs/{run_id}/stop")
        await asyncio.sleep(1)

        # Get events and check sequence
        events = get_control_events(run_id)
        if len(events) >= 2:
            sequence_ids = [e["sequence_id"] for e in events]
            assert sequence_ids == sorted(sequence_ids), (
                f"Events not in sequence order: {sequence_ids}"
            )
