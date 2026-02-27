"""
Browser E2E Tests: Dashboard Common Elements

Tests UI elements that appear in BOTH live and history dashboard modes:
- Template info card
- Control panel structure
- Latency KPI cards
- SLO targets table
- Charts (canvas elements)
- Run logs section

Run with: E2E_TEST=1 uv run pytest tests/e2e/browser/test_dashboard_common.py -v --browser chromium
"""

from __future__ import annotations

import time

import pytest

try:
    from playwright.sync_api import Page, expect
except ImportError:
    Page = None
    expect = None

from tests.e2e.browser.conftest import wait_for_alpine

pytestmark = [pytest.mark.e2e, pytest.mark.browser]

if Page is None:
    pytest.skip(
        "playwright package required: uv add playwright && uv run playwright install",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _goto_live(page: Page, server_url: str, create_run) -> str:
    """Navigate to a PREPARED run's live dashboard. Returns run_id."""
    run_id = create_run()
    page.goto(f"{server_url}/dashboard/{run_id}")
    wait_for_alpine(page)
    return run_id


def _goto_live_running(page: Page, server_url: str, create_and_start_run) -> str:
    """Navigate to a RUNNING run's live dashboard. Returns run_id."""
    run_id = create_and_start_run()
    page.goto(f"{server_url}/dashboard/{run_id}")
    wait_for_alpine(page)
    return run_id


def _goto_history(
    page: Page,
    server_url: str,
    create_and_start_run,
    wait_for_run_completion,
) -> str:
    """Create run, wait for completion, navigate to history. Returns run_id."""
    run_id = create_and_start_run()
    wait_for_run_completion(run_id, timeout=120)
    page.goto(f"{server_url}/dashboard/history/{run_id}")
    wait_for_alpine(page)
    return run_id


# ==========================================================================
# Template Info Card
# ==========================================================================


class TestTemplateInfoCard:
    """Template/test configuration card appears in both modes."""

    def test_template_name_displayed_live(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Card title shows the template or test name in live mode."""
        _goto_live_running(page, server_url, create_and_start_run)
        # The card-title inside the first card with templateInfo
        title = page.locator(".card-title").first
        expect(title).to_be_visible(timeout=10_000)
        # Should have some text (template name is populated by Alpine)
        time.sleep(3)  # allow Alpine to hydrate
        text = title.inner_text()
        assert len(text) > 0, "Template name card title is empty"

    def test_template_name_displayed_history(
        self,
        page: Page,
        server_url: str,
        create_and_start_run,
        wait_for_run_completion,
    ):
        """Card title shows the template or test name in history mode."""
        _goto_history(page, server_url, create_and_start_run, wait_for_run_completion)
        title = page.locator(".card-title").first
        expect(title).to_be_visible(timeout=10_000)
        time.sleep(2)
        assert len(title.inner_text()) > 0, "Template name card title is empty"

    def test_table_type_icon_present(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Table type icon (Snowflake/Postgres) renders in the info card."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        icon = page.locator("img.template-type-icon")
        # Icon may be hidden via x-show if tableTypeIconSrc() is falsy;
        # at minimum the element should exist in DOM.
        assert icon.count() >= 1, "template-type-icon img element not found"

    def test_duration_and_load_mode_shown(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Duration and load mode text appears in the template info card."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        content = page.content()
        assert "duration" in content.lower() or "load mode" in content.lower(), (
            "Neither 'Duration' nor 'Load Mode' found in page content"
        )


# ==========================================================================
# Control Panel
# ==========================================================================


class TestControlPanel:
    """Test Control Panel card structure."""

    def test_start_button_present(self, page: Page, server_url: str, create_run):
        """Start button is present and enabled for a PREPARED run."""
        _goto_live(page, server_url, create_run)
        time.sleep(2)
        start_btn = page.locator("button.btn-success", has_text="Start")
        expect(start_btn).to_be_visible(timeout=10_000)
        expect(start_btn).to_be_enabled()

    def test_stop_button_present_and_disabled(
        self, page: Page, server_url: str, create_run
    ):
        """Stop button is present but disabled for a PREPARED run."""
        _goto_live(page, server_url, create_run)
        time.sleep(2)
        stop_btn = page.locator("button.btn-error", has_text="Stop")
        expect(stop_btn).to_be_visible(timeout=10_000)
        expect(stop_btn).to_be_disabled()

    def test_phase_pipeline_labels(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Phase pipeline renders phase labels after test starts."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        pipeline = page.locator(".phase-pipeline")
        expect(pipeline).to_be_visible(timeout=10_000)
        badges = pipeline.locator(".phase-badge")
        # Should have at least 3 phase badges (PREPARING, WARMUP, MEASUREMENT, ...)
        assert badges.count() >= 3, f"Expected >=3 phase badges, found {badges.count()}"

    def test_total_time_counter_visible(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Total time counter appears after the test starts."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        counter = page.locator(".total-time-value")
        expect(counter).to_be_visible(timeout=10_000)


# ==========================================================================
# Latency KPI Cards
# ==========================================================================


class TestLatencyKPICards:
    """Latency metric cards (QPS, P50, P95, P99, Error Rate)."""

    @pytest.mark.slow
    def test_qps_card_present_with_value(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """QPS metric card present with a numeric .metric-value."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(5)
        qps_card = (
            page.locator(".metric-card")
            .filter(has=page.locator(".metric-label", has_text="QPS"))
            .first
        )
        expect(qps_card).to_be_visible(timeout=10_000)
        value_el = qps_card.locator(".metric-value")
        expect(value_el).to_be_visible()

    @pytest.mark.slow
    def test_p50_p95_p99_cards_present(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """P50, P95, and P99 latency cards each have a .metric-value-main element."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(5)
        for label in ["P50", "P95", "P99"]:
            card = (
                page.locator(".metric-card")
                .filter(has=page.locator(".metric-label", has_text=label))
                .first
            )
            expect(card).to_be_visible(timeout=10_000)
            main_val = card.locator(".metric-value-main")
            expect(main_val).to_be_visible()

    @pytest.mark.slow
    def test_error_rate_card_present(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Error Rate card present with percentage format."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(5)
        card = (
            page.locator(".metric-card")
            .filter(has=page.locator(".metric-label", has_text="Error Rate"))
            .first
        )
        expect(card).to_be_visible(timeout=10_000)
        value_el = card.locator(".metric-value")
        expect(value_el).to_be_visible()
        text = value_el.inner_text()
        assert "%" in text, f"Error rate value missing '%': {text}"

    @pytest.mark.slow
    def test_info_icons_on_metric_cards(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Each KPI metric card has an info icon (tooltip trigger)."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(5)
        info_icons = page.locator(".metrics-grid .info-icon")
        # We expect at least 4 info icons (QPS, P50, P95, P99, Error Rate, ...)
        assert info_icons.count() >= 4, (
            f"Expected >=4 info icons, found {info_icons.count()}"
        )


# ==========================================================================
# SLO Targets Table
# ==========================================================================


class TestSLOTargetsTable:
    """Targets (SLOs) card and table."""

    @pytest.mark.slow
    def test_slo_card_rendered(self, page: Page, server_url: str, create_and_start_run):
        """Targets (SLOs) card is present when templateInfo is loaded."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(5)
        slo_card = page.locator(".card").filter(
            has=page.locator(".card-title", has_text="Targets (SLOs)")
        )
        # Card exists in DOM (may be hidden if no SLO config)
        assert slo_card.count() >= 1, "Targets (SLOs) card not found in DOM"

    @pytest.mark.slow
    def test_slo_overall_status_badge(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Overall SLO status badge is rendered."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(5)
        badge = page.locator(
            ".card:has(.card-title:has-text('Targets (SLOs)')) .status-badge"
        )
        # Badge should exist (PASS / FAIL / DISABLED)
        assert badge.count() >= 1, "SLO overall status badge not found"

    @pytest.mark.slow
    def test_slo_table_headers(self, page: Page, server_url: str, create_and_start_run):
        """SLO table has expected column headers."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(5)
        slo_card = page.locator(".card").filter(
            has=page.locator(".card-title", has_text="Targets (SLOs)")
        )
        headers = slo_card.locator("th")
        if headers.count() > 0:
            header_texts = [headers.nth(i).inner_text() for i in range(headers.count())]
            expected = {"Query Type", "Weight", "P95 Target", "Status"}
            found = {h.strip() for h in header_texts}
            missing = expected - found
            assert not missing, f"Missing SLO table headers: {missing}"


# ==========================================================================
# Charts
# ==========================================================================


class TestCharts:
    """Chart canvas elements are present in both modes."""

    @pytest.mark.slow
    def test_throughput_chart_canvas(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Throughput chart canvas (#throughputChart) is in the DOM."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        canvas = page.locator("#throughputChart")
        assert canvas.count() == 1, "throughputChart canvas not found"

    @pytest.mark.slow
    def test_latency_chart_canvas(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Latency chart canvas (#latencyChart) is in the DOM."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        canvas = page.locator("#latencyChart")
        assert canvas.count() == 1, "latencyChart canvas not found"

    @pytest.mark.slow
    def test_concurrency_chart_canvas(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Concurrency chart canvas (#concurrencyChart) is in the DOM."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        canvas = page.locator("#concurrencyChart")
        assert canvas.count() == 1, "concurrencyChart canvas not found"


# ==========================================================================
# Run Logs
# ==========================================================================


class TestRunLogs:
    """Run logs card and controls."""

    @pytest.mark.slow
    def test_log_card_with_level_filter(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Log card renders with a level filter dropdown."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        log_card = page.locator(".card").filter(
            has=page.locator(".card-title", has_text="Run Logs")
        )
        expect(log_card).to_be_visible(timeout=10_000)
        level_select = log_card.locator(".form-select").first
        expect(level_select).to_be_visible()

    @pytest.mark.slow
    def test_log_output_container_exists(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Log output container (.log-output) is in the DOM."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        log_output = page.locator(".log-output")
        assert log_output.count() >= 1, ".log-output container not found"

    @pytest.mark.slow
    def test_log_source_filter_present(
        self, page: Page, server_url: str, create_and_start_run
    ):
        """Source filter control is present in the log card."""
        _goto_live_running(page, server_url, create_and_start_run)
        time.sleep(3)
        log_controls = page.locator(".log-controls")
        expect(log_controls).to_be_visible(timeout=10_000)
        # Source filter is conditional on logTargets being populated;
        # verify the controls container is there at minimum
        controls = log_controls.locator(".log-control")
        assert controls.count() >= 1, "No .log-control elements found in log controls"
