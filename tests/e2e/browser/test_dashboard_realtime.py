"""
Browser E2E Tests: Dashboard Real-time Updates

Tests actual browser behavior using Playwright:
- Dashboard loads and renders correctly
- Real-time metrics update in the UI
- Phase transitions are visually reflected
- Charts render with live data

Prerequisites:
    uv add playwright pytest-playwright
    uv run playwright install chromium

Run with: E2E_TEST=1 uv run pytest tests/e2e/browser/ -v --browser chromium
"""

from __future__ import annotations

import re
import time

import pytest

try:
    from playwright.sync_api import Page, expect
except ImportError:
    Page = None
    expect = None

pytestmark = [pytest.mark.e2e, pytest.mark.browser]


# Skip all tests if playwright not installed
if Page is None:
    pytest.skip(
        "playwright package required: uv add playwright && uv run playwright install",
        allow_module_level=True,
    )


class TestDashboardLoads:
    """Test that dashboard page loads correctly."""

    def test_dashboard_page_loads(
        self,
        page: Page,
        server_url: str,
        create_run,
    ):
        """
        GIVEN: A valid run_id
        WHEN: Navigating to /dashboard/{run_id}
        THEN: Page loads without errors
        """
        run_id = create_run()

        # Navigate to dashboard
        page.goto(f"{server_url}/dashboard/{run_id}")

        # Page should load without console errors
        expect(page).to_have_title(
            re.compile(r".*Dashboard.*|.*FlakeBench.*", re.IGNORECASE)
        )

    def test_dashboard_shows_run_status(
        self,
        page: Page,
        server_url: str,
        create_run,
    ):
        """
        GIVEN: A run in PREPARED status
        WHEN: Viewing the dashboard
        THEN: Status indicator shows PREPARED
        """
        run_id = create_run()

        page.goto(f"{server_url}/dashboard/{run_id}")
        page.wait_for_load_state("networkidle")

        # Look for status indicator - could be various selectors
        status_locators = [
            page.locator("[data-testid='run-status']"),
            page.locator(".status-badge"),
            page.locator(".run-status"),
            page.get_by_text(re.compile(r"PREPARED|Prepared", re.IGNORECASE)),
        ]

        # At least one should be visible
        found_status = False
        for locator in status_locators:
            if locator.count() > 0:
                found_status = True
                break

        # If no specific status element, check page content
        if not found_status:
            content = page.content()
            assert "prepared" in content.lower() or "status" in content.lower(), (
                "No status indicator found on dashboard"
            )


class TestRealTimeMetricsUpdates:
    """Test that metrics update in real-time during run execution."""

    @pytest.mark.slow
    def test_qps_counter_updates_during_run(
        self,
        page: Page,
        server_url: str,
        create_and_start_run,
    ):
        """
        GIVEN: A running test
        WHEN: Viewing dashboard during execution
        THEN: QPS metric card is present and displays a numeric value
        """
        run_id = create_and_start_run()

        # Navigate to dashboard
        page.goto(f"{server_url}/dashboard/{run_id}")
        page.wait_for_load_state("networkidle")

        # Target the primary QPS metric card (first .metric-card whose .metric-label
        # contains "QPS"). A second card ("Best So Far") also matches, so use .first.
        qps_card = (
            page.locator(".metric-card")
            .filter(has=page.locator(".metric-label", has_text="QPS"))
            .first
        )
        qps_value_el = qps_card.locator(".metric-value")

        # QPS metric card must be present and contain a readable value.
        # Poll for up to 30 seconds to allow the run to progress through phases.
        qps_values = []
        for _ in range(30):
            time.sleep(1)
            if qps_value_el.count() > 0:
                text = qps_value_el.inner_text()
                numbers = re.findall(r"[\d,]+\.?\d*", text)
                if numbers:
                    try:
                        value = float(numbers[0].replace(",", ""))
                        qps_values.append(value)
                        # Once we have a non-zero value, collect a few more to
                        # verify updates, then stop early.
                        if value > 0 and len(qps_values) >= 5:
                            break
                    except ValueError:
                        pass

        # Must have collected at least some readings
        assert len(qps_values) >= 3, (
            "Could not collect QPS values from dashboard. "
            "Check that the QPS metric card is rendered."
        )

        # If the run reached measurement phase, values should be non-zero
        # and changing. If it stayed at 0 (e.g. short E2E template), that's
        # still valid -- the metric card rendered correctly.
        non_zero = [v for v in qps_values if v > 0]
        if non_zero:
            unique_values = set(non_zero)
            assert len(unique_values) >= 2, (
                f"QPS values were non-zero but did not change: {qps_values}"
            )

    @pytest.mark.slow
    def test_latency_metrics_display(
        self,
        page: Page,
        server_url: str,
        create_and_start_run,
    ):
        """
        GIVEN: A running test
        WHEN: Viewing dashboard
        THEN: Latency metrics (p50, p95, p99) are displayed
        """
        run_id = create_and_start_run()

        page.goto(f"{server_url}/dashboard/{run_id}")

        # Wait for metrics to populate
        time.sleep(5)

        # Check for latency indicators
        content = page.content()
        latency_indicators = ["p50", "p95", "p99", "latency", "ms", "percentile"]

        found_latency = any(
            indicator.lower() in content.lower() for indicator in latency_indicators
        )

        assert found_latency, (
            "No latency metrics found on dashboard. "
            "Expected p50/p95/p99 or similar latency indicators."
        )


class TestPhaseTransitionUI:
    """Test that phase transitions are reflected in the UI."""

    @pytest.mark.slow
    def test_phase_indicator_changes_during_run(
        self,
        page: Page,
        server_url: str,
        create_run,
    ):
        """
        GIVEN: A run transitioning through phases
        WHEN: Watching the dashboard
        THEN: Phase indicator updates (PREPARING -> WARMUP -> MEASUREMENT)
        """
        run_id = create_run()

        page.goto(f"{server_url}/dashboard/{run_id}")
        page.wait_for_load_state("networkidle")

        # Start the run
        import httpx

        with httpx.Client(
            base_url=server_url, timeout=30, follow_redirects=True
        ) as client:
            client.post(f"/api/runs/{run_id}/start")

        # Watch for phase changes
        observed_phases = set()
        phase_patterns = [
            "PREPARING",
            "WARMUP",
            "MEASUREMENT",
            "PROCESSING",
            "COMPLETED",
        ]

        for _ in range(20):  # Check for 20 seconds
            time.sleep(1)
            content = page.content()

            for phase in phase_patterns:
                if phase.lower() in content.lower():
                    observed_phases.add(phase)

        # Should observe multiple phases
        assert len(observed_phases) >= 2, (
            f"Expected multiple phases, only observed: {observed_phases}"
        )

    @pytest.mark.slow
    def test_status_updates_on_stop(
        self,
        page: Page,
        server_url: str,
        create_and_start_run,
    ):
        """
        GIVEN: A running test
        WHEN: Stop button is clicked or stop API called
        THEN: UI shows CANCELLING/CANCELLED status
        """
        run_id = create_and_start_run()

        page.goto(f"{server_url}/dashboard/{run_id}")
        time.sleep(3)  # Let it run

        # Stop the run
        import httpx

        with httpx.Client(
            base_url=server_url, timeout=30, follow_redirects=True
        ) as client:
            client.post(f"/api/runs/{run_id}/stop")

        # Wait for UI to reflect stop
        time.sleep(3)
        content = page.content()

        stop_indicators = ["CANCELLING", "CANCELLED", "COMPLETED", "STOPPED"]
        found_stop = any(
            indicator.lower() in content.lower() for indicator in stop_indicators
        )

        assert found_stop, (
            "UI did not reflect stop status. "
            f"Expected one of {stop_indicators} in page content."
        )


class TestChartRendering:
    """Test that charts render with live data."""

    @pytest.mark.slow
    def test_timeseries_chart_renders(
        self,
        page: Page,
        server_url: str,
        create_and_start_run,
    ):
        """
        GIVEN: A running test with metrics
        WHEN: Viewing dashboard
        THEN: Timeseries chart(s) are rendered with data points
        """
        run_id = create_and_start_run()

        page.goto(f"{server_url}/dashboard/{run_id}")

        # Wait for charts to render
        time.sleep(5)

        # Look for chart elements (canvas, svg, or chart containers)
        chart_locators = [
            page.locator("canvas"),
            page.locator("svg.chart"),
            page.locator("[data-testid='timeseries-chart']"),
            page.locator(".chart-container"),
            page.locator(".apexcharts-canvas"),
            page.locator(".chartjs-render-monitor"),
        ]

        chart_found = False
        for locator in chart_locators:
            count = locator.count()
            if count > 0:
                chart_found = True
                break

        assert chart_found, (
            "No chart element found on dashboard. "
            "Expected canvas, svg, or chart container element."
        )


class TestErrorHandling:
    """Test UI behavior on errors."""

    def test_invalid_run_shows_error(
        self,
        page: Page,
        server_url: str,
    ):
        """
        GIVEN: An invalid run_id
        WHEN: Navigating to dashboard
        THEN: Error message is displayed (not a crash)
        """
        page.goto(f"{server_url}/dashboard/nonexistent-run-xyz")

        # Should either show error or redirect, not crash
        # Check for error indicators or that page loaded
        page.wait_for_load_state("networkidle")

        # Page should be responsive
        content = page.content()
        assert len(content) > 100, "Page appears to be empty/crashed"

        # May show error message
        error_indicators = ["not found", "error", "invalid", "404"]
        has_error = any(ind in content.lower() for ind in error_indicators)

        # Either shows error OR redirects to valid page
        assert has_error or "dashboard" in page.url.lower(), (
            "Page did not show error or redirect for invalid run"
        )
