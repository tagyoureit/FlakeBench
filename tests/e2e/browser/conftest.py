"""
Shared fixtures for browser E2E tests.

Provides reusable fixtures for creating runs, navigating to dashboards,
waiting for Alpine.js initialization, and capturing screenshots on failure.

Prerequisites:
    uv add playwright pytest-playwright httpx
    uv run playwright install chromium

Run with: E2E_TEST=1 uv run pytest tests/e2e/browser/ -v --browser chromium
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import httpx
import pytest

if TYPE_CHECKING:
    from playwright.sync_api import Page

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

E2E_SERVER_URL = os.getenv("E2E_SERVER_URL", "http://127.0.0.1:8765")
E2E_TEMPLATE_ID = os.getenv("E2E_TEMPLATE_ID", "e2e-test-template-001")

TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED", "STOPPED"})

# ---------------------------------------------------------------------------
# server_url fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def server_url() -> str:
    """Base URL for the E2E test server."""
    return E2E_SERVER_URL


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def _http_client(base_url: str) -> httpx.Client:
    return httpx.Client(base_url=base_url, timeout=30, follow_redirects=True)


# ---------------------------------------------------------------------------
# create_run fixture  (factory)
# ---------------------------------------------------------------------------


@pytest.fixture
def create_run(server_url: str):
    """
    Factory fixture: POST /api/runs and return run_id.

    Usage::

        run_id = create_run()
        run_id = create_run(template_id="custom-template")
    """

    def _create(template_id: str = E2E_TEMPLATE_ID) -> str:
        with _http_client(server_url) as client:
            resp = client.post("/api/runs", json={"template_id": template_id})
            resp.raise_for_status()
            return resp.json()["run_id"]

    return _create


# ---------------------------------------------------------------------------
# create_and_start_run fixture  (factory)
# ---------------------------------------------------------------------------


@pytest.fixture
def create_and_start_run(server_url: str):
    """
    Factory fixture: create + start a run, return run_id.

    Usage::

        run_id = create_and_start_run()
    """

    def _create_and_start(template_id: str = E2E_TEMPLATE_ID) -> str:
        with _http_client(server_url) as client:
            resp = client.post("/api/runs", json={"template_id": template_id})
            resp.raise_for_status()
            run_id = resp.json()["run_id"]
            client.post(f"/api/runs/{run_id}/start").raise_for_status()
            return run_id

    return _create_and_start


# ---------------------------------------------------------------------------
# wait_for_run_completion fixture  (factory)
# ---------------------------------------------------------------------------


@pytest.fixture
def wait_for_run_completion(server_url: str):
    """
    Poll ``GET /api/tests/{run_id}`` until the run reaches a terminal status.

    Returns the final status string.
    """

    def _wait(run_id: str, timeout: float = 120) -> str:
        deadline = time.monotonic() + timeout
        with _http_client(server_url) as client:
            while time.monotonic() < deadline:
                resp = client.get(f"/api/tests/{run_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    status = (data.get("status") or "").upper()
                    if status in TERMINAL_STATUSES:
                        return status
                time.sleep(2)
        raise TimeoutError(
            f"Run {run_id} did not reach a terminal status within {timeout}s"
        )

    return _wait


# ---------------------------------------------------------------------------
# Alpine.js readiness helper
# ---------------------------------------------------------------------------


def wait_for_alpine(page: "Page", timeout: float = 15_000) -> None:
    """
    Wait until Alpine.js has initialised on the page.

    Checks for ``Alpine`` global and at least one ``__x`` component.
    Falls back to ``networkidle`` after *timeout* ms.
    """
    try:
        page.wait_for_function(
            """() => {
                if (typeof Alpine === 'undefined') return false;
                const root = document.querySelector('[x-data]');
                return root && root.__x !== undefined;
            }""",
            timeout=timeout,
        )
    except Exception:
        # Fallback – Alpine may use a different init mechanism
        page.wait_for_load_state("networkidle")


# ---------------------------------------------------------------------------
# live_dashboard_page fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def live_dashboard_page(page: "Page", server_url: str, create_and_start_run):
    """
    Navigate to ``/dashboard/{run_id}`` for a freshly started run.

    Waits for Alpine.js to initialise before yielding the (page, run_id) tuple.
    """
    run_id = create_and_start_run()
    page.goto(f"{server_url}/dashboard/{run_id}")
    wait_for_alpine(page)
    return page, run_id


# ---------------------------------------------------------------------------
# history_dashboard_page fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def history_dashboard_page(
    page: "Page",
    server_url: str,
    create_and_start_run,
    wait_for_run_completion,
):
    """
    Create a run, wait for it to complete, navigate to the history dashboard.

    Returns (page, run_id).
    """
    run_id = create_and_start_run()
    wait_for_run_completion(run_id, timeout=120)
    page.goto(f"{server_url}/dashboard/history/{run_id}")
    wait_for_alpine(page)
    return page, run_id


# ---------------------------------------------------------------------------
# Screenshot-on-failure hook
# ---------------------------------------------------------------------------


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Store test result so the screenshot fixture can check for failure."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)


@pytest.fixture(autouse=True)
def _capture_screenshot_on_failure(page: "Page", request):
    """Capture a full-page screenshot when a test fails."""
    yield

    rep = getattr(request.node, "rep_call", None)
    if rep is not None and rep.failed:
        screenshot_dir = "test-results/screenshots"
        os.makedirs(screenshot_dir, exist_ok=True)
        safe_name = request.node.name.replace("/", "_").replace(":", "_")
        path = f"{screenshot_dir}/{safe_name}.png"
        try:
            page.screenshot(path=path, full_page=True)
        except Exception:
            pass  # page may already be closed
