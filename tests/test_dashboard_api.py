"""
Unit tests for /api/dashboard/* endpoints.

Tests dashboard data retrieval with mocked database.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


class TestGetTableTypes:
    """Tests for GET /api/dashboard/table-types/summary."""

    def test_get_table_types_empty_data(self, client: TestClient) -> None:
        """Returns empty response when no data."""
        with patch("backend.api.routes.dashboard.snowflake_pool") as mock_pool:
            mock_pool.get_default_pool.return_value.execute_query = AsyncMock(
                return_value=[]
            )

            response = client.get("/api/dashboard/table-types/summary")

            assert response.status_code == 200
            data = response.json()
            assert data["kpi_cards"] == []
            assert data["totals"]["total_tests"] == 0

    def test_get_table_types_returns_kpi_cards(self, client: TestClient) -> None:
        """Returns KPI cards for each table type."""
        mock_row = (
            "HYBRID",  # TABLE_TYPE
            100,  # TEST_COUNT
            10,  # UNIQUE_TEMPLATES
            1500.0,  # AVG_QPS
            500.0,  # MIN_QPS
            3000.0,  # MAX_QPS
            1400.0,  # MEDIAN_QPS
            200.0,  # STDDEV_QPS
            5.0,  # AVG_P50_MS
            4.5,  # MEDIAN_P50_MS
            15.0,  # AVG_P95_MS
            10.0,  # MIN_P95_MS
            25.0,  # MAX_P95_MS
            14.0,  # MEDIAN_P95_MS
            30.0,  # AVG_P99_MS
            28.0,  # MEDIAN_P99_MS
            0.001,  # AVG_ERROR_RATE
            0.005,  # MAX_ERROR_RATE
            50.0,  # TOTAL_CREDITS
            0.5,  # AVG_CREDITS_PER_TEST
            0.03,  # CREDITS_PER_1K_OPS
            1000000,  # TOTAL_OPERATIONS
            datetime(2024, 1, 1),  # EARLIEST_TEST
            datetime(2024, 12, 1),  # LATEST_TEST
        )

        with patch("backend.api.routes.dashboard.snowflake_pool") as mock_pool:
            mock_pool.get_default_pool.return_value.execute_query = AsyncMock(
                return_value=[mock_row]
            )

            response = client.get("/api/dashboard/table-types/summary")

            assert response.status_code == 200
            data = response.json()
            assert len(data["kpi_cards"]) == 1
            assert data["kpi_cards"][0]["table_type"] == "HYBRID"
            assert data["kpi_cards"][0]["test_count"] == 100
            assert data["kpi_cards"][0]["avg_qps"] == 1500.0


class TestGetTemplates:
    """Tests for GET /api/dashboard/templates."""

    def test_get_templates_returns_list(self, client: TestClient) -> None:
        """Returns list of templates."""
        mock_row = (
            "template-001",  # TEMPLATE_ID
            "Load Test Template",  # TEMPLATE_NAME
            "HYBRID",  # TABLE_TYPE
            "X-SMALL",  # WAREHOUSE_SIZE
            "STEADY",  # LOAD_MODE
            50,  # TOTAL_RUNS
            datetime(2024, 12, 1),  # LAST_RUN
            1200.0,  # AVG_QPS
            12.0,  # AVG_P95_MS
            "stable",  # STABILITY_BADGE
            0.025,  # CREDITS_PER_1K_OPS
        )

        with patch("backend.api.routes.dashboard.snowflake_pool") as mock_pool:
            # First call returns templates, second call returns count
            mock_pool.get_default_pool.return_value.execute_query = AsyncMock(
                side_effect=[[mock_row], [(1,)]]
            )

            response = client.get("/api/dashboard/templates")

            assert response.status_code == 200
            data = response.json()
            assert len(data["templates"]) == 1
            assert data["templates"][0]["template_id"] == "template-001"
            assert data["total_count"] == 1


class TestGetDailyCosts:
    """Tests for GET /api/dashboard/costs/daily."""

    def test_get_daily_costs_returns_data(self, client: TestClient) -> None:
        """Returns daily cost rollup data."""
        # API expects: RUN_DATE, TABLE_TYPE, WAREHOUSE_SIZE, TEST_COUNT,
        #              TOTAL_CREDITS, TOTAL_OPERATIONS, CREDITS_PER_1K_OPS, AVG_QPS
        mock_rows = [
            (
                datetime(2024, 12, 1).date(),  # RUN_DATE
                "STANDARD",  # TABLE_TYPE
                "MEDIUM",  # WAREHOUSE_SIZE
                5,  # TEST_COUNT
                10.5,  # TOTAL_CREDITS
                100000,  # TOTAL_OPERATIONS
                0.105,  # CREDITS_PER_1K_OPS
                500.0,  # AVG_QPS
            ),
            (
                datetime(2024, 12, 2).date(),  # RUN_DATE
                "HYBRID",  # TABLE_TYPE
                "MEDIUM",  # WAREHOUSE_SIZE
                8,  # TEST_COUNT
                15.0,  # TOTAL_CREDITS
                150000,  # TOTAL_OPERATIONS
                0.1,  # CREDITS_PER_1K_OPS
                600.0,  # AVG_QPS
            ),
        ]

        with patch("backend.api.routes.dashboard.snowflake_pool") as mock_pool:
            mock_pool.get_default_pool.return_value.execute_query = AsyncMock(
                return_value=mock_rows
            )

            response = client.get("/api/dashboard/costs/daily")

            assert response.status_code == 200
            data = response.json()
            assert "data" in data
            assert "totals" in data


class TestGetChartData:
    """Tests for GET /api/dashboard/table-types/chart/{chart_type}."""

    def test_get_chart_qps(self, client: TestClient) -> None:
        """Returns QPS comparison chart data."""
        mock_row = (
            "STANDARD",  # TABLE_TYPE
            50,  # TEST_COUNT
            5,  # UNIQUE_TEMPLATES
            1000.0,  # AVG_QPS
            500.0, 1500.0, 950.0, 150.0,  # QPS stats
            5.0, 4.5,  # P50 stats
            15.0, 10.0, 20.0, 14.0,  # P95 stats
            30.0, 28.0,  # P99 stats
            0.001, 0.005,  # Error rates
            25.0, 0.5, 0.025,  # Credits
            500000,  # Total ops
            datetime(2024, 1, 1),
            datetime(2024, 12, 1),
        )

        with patch("backend.api.routes.dashboard.snowflake_pool") as mock_pool:
            mock_pool.get_default_pool.return_value.execute_query = AsyncMock(
                return_value=[mock_row]
            )

            response = client.get("/api/dashboard/table-types/chart/qps")

            assert response.status_code == 200
            data = response.json()
            assert "labels" in data
            assert "datasets" in data

    def test_get_chart_invalid_type(self, client: TestClient) -> None:
        """Returns 400 for invalid chart type."""
        mock_row = (
            "STANDARD", 50, 5, 1000.0, 500.0, 1500.0, 950.0, 150.0,
            5.0, 4.5, 15.0, 10.0, 20.0, 14.0, 30.0, 28.0,
            0.001, 0.005, 25.0, 0.5, 0.025, 500000,
            datetime(2024, 1, 1), datetime(2024, 12, 1),
        )

        with patch("backend.api.routes.dashboard.snowflake_pool") as mock_pool:
            mock_pool.get_default_pool.return_value.execute_query = AsyncMock(
                return_value=[mock_row]
            )

            response = client.get("/api/dashboard/table-types/chart/invalid_type")

            assert response.status_code == 400
            assert "unknown chart type" in response.json()["detail"].lower()
