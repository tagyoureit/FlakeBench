"""
Tests for throughput and OLAP aggregate fields on TestResult (Items 3 + 5).

Covers:
- GENERIC_SQL throughput fields (rows_per_sec, bytes_scanned_per_sec)
- OLAP aggregate fields (total_operations, total_rows_processed, total_bytes_scanned, olap_metrics)
- Default values
- Schema DDL contains all new columns
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.models.test_result import TestResult, TestStatus


def _minimal_result(**overrides) -> TestResult:
    """Build a TestResult with only required fields + overrides."""
    defaults = {
        "test_name": "throughput-test",
        "scenario_name": "throughput-scenario",
        "table_name": "T1",
        "table_type": "standard",
        "status": TestStatus.COMPLETED,
        "start_time": datetime.now(tz=timezone.utc),
        "concurrent_connections": 4,
    }
    defaults.update(overrides)
    return TestResult(**defaults)


class TestThroughputFields:
    """Verify GENERIC_SQL throughput fields."""

    def test_rows_per_sec_defaults_none(self) -> None:
        result = _minimal_result()
        assert result.generic_sql_rows_per_sec is None

    def test_bytes_scanned_per_sec_defaults_none(self) -> None:
        result = _minimal_result()
        assert result.generic_sql_bytes_scanned_per_sec is None

    def test_rows_per_sec_accepts_float(self) -> None:
        result = _minimal_result(generic_sql_rows_per_sec=1500.5)
        assert result.generic_sql_rows_per_sec == 1500.5

    def test_bytes_scanned_per_sec_accepts_float(self) -> None:
        result = _minimal_result(generic_sql_bytes_scanned_per_sec=1024000.0)
        assert result.generic_sql_bytes_scanned_per_sec == 1024000.0


class TestOLAPAggregateFields:
    """Verify OLAP aggregate fields."""

    def test_olap_total_operations_defaults_zero(self) -> None:
        result = _minimal_result()
        assert result.olap_total_operations == 0

    def test_olap_total_rows_processed_defaults_zero(self) -> None:
        result = _minimal_result()
        assert result.olap_total_rows_processed == 0

    def test_olap_total_bytes_scanned_defaults_zero(self) -> None:
        result = _minimal_result()
        assert result.olap_total_bytes_scanned == 0

    def test_olap_metrics_defaults_none(self) -> None:
        result = _minimal_result()
        assert result.olap_metrics is None

    def test_olap_total_operations_accepts_int(self) -> None:
        result = _minimal_result(olap_total_operations=42)
        assert result.olap_total_operations == 42

    def test_olap_total_rows_processed_accepts_int(self) -> None:
        result = _minimal_result(olap_total_rows_processed=100000)
        assert result.olap_total_rows_processed == 100000

    def test_olap_total_bytes_scanned_accepts_int(self) -> None:
        result = _minimal_result(olap_total_bytes_scanned=5_000_000)
        assert result.olap_total_bytes_scanned == 5_000_000

    def test_olap_metrics_accepts_dict(self) -> None:
        payload = {"by_kind": {"agg": {"p95_ms": 12.5}}}
        result = _minimal_result(olap_metrics=payload)
        assert result.olap_metrics == payload


class TestThroughputOLAPSerialization:
    """Verify throughput and OLAP fields survive round-trip."""

    def test_round_trip_throughput(self) -> None:
        original = _minimal_result(
            generic_sql_rows_per_sec=500.0,
            generic_sql_bytes_scanned_per_sec=1024.0,
        )
        dumped = original.model_dump()
        restored = TestResult.model_validate(dumped)
        assert restored.generic_sql_rows_per_sec == 500.0
        assert restored.generic_sql_bytes_scanned_per_sec == 1024.0

    def test_round_trip_olap(self) -> None:
        payload = {"subkind": "windowed"}
        original = _minimal_result(
            olap_total_operations=10,
            olap_total_rows_processed=5000,
            olap_total_bytes_scanned=2_000_000,
            olap_metrics=payload,
        )
        dumped = original.model_dump()
        restored = TestResult.model_validate(dumped)
        assert restored.olap_total_operations == 10
        assert restored.olap_total_rows_processed == 5000
        assert restored.olap_total_bytes_scanned == 2_000_000
        assert restored.olap_metrics == payload


class TestThroughputOLAPSchemaSQL:
    """Verify DDL schema file contains throughput and OLAP columns."""

    @pytest.fixture()
    def ddl(self) -> str:
        with open("sql/schema/results_tables.sql") as f:
            return f.read().lower()

    @pytest.mark.parametrize(
        "column",
        [
            "generic_sql_rows_per_sec",
            "generic_sql_bytes_scanned_per_sec",
            "olap_total_operations",
            "olap_total_rows_processed",
            "olap_total_bytes_scanned",
            "olap_metrics",
        ],
        ids=[
            "rows_per_sec",
            "bytes_scanned_per_sec",
            "olap_total_ops",
            "olap_total_rows",
            "olap_total_bytes",
            "olap_metrics",
        ],
    )
    def test_schema_has_column(self, ddl: str, column: str) -> None:
        assert column in ddl, f"Column {column} not found in results_tables.sql"
