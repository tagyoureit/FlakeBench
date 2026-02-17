"""
Tests for methodology metadata fields on TestResult (Item 8).

Covers:
- run_temperature, trial_index, realism_profile fields exist with correct defaults
- Serialization round-trip via model_dump() / model_validate()
- Schema DDL contains the three new columns
"""

from __future__ import annotations

from datetime import datetime, timezone


from backend.models.test_result import TestResult, TestStatus


def _minimal_result(**overrides) -> TestResult:
    """Build a TestResult with only required fields + overrides."""
    defaults = {
        "test_name": "meta-test",
        "scenario_name": "meta-scenario",
        "table_name": "T1",
        "table_type": "standard",
        "status": TestStatus.COMPLETED,
        "start_time": datetime.now(tz=timezone.utc),
        "concurrent_connections": 4,
    }
    defaults.update(overrides)
    return TestResult(**defaults)


class TestMethodologyDefaults:
    """Verify default values for methodology metadata."""

    def test_run_temperature_defaults_none(self) -> None:
        result = _minimal_result()
        assert result.run_temperature is None

    def test_trial_index_defaults_none(self) -> None:
        result = _minimal_result()
        assert result.trial_index is None

    def test_realism_profile_defaults_none(self) -> None:
        result = _minimal_result()
        assert result.realism_profile is None


class TestMethodologyExplicitValues:
    """Verify fields accept explicit values."""

    def test_run_temperature_accepts_float(self) -> None:
        result = _minimal_result(run_temperature=0.5)
        assert result.run_temperature == 0.5

    def test_run_temperature_cold(self) -> None:
        result = _minimal_result(run_temperature=0.0)
        assert result.run_temperature == 0.0

    def test_run_temperature_warm(self) -> None:
        result = _minimal_result(run_temperature=1.0)
        assert result.run_temperature == 1.0

    def test_trial_index_accepts_int(self) -> None:
        result = _minimal_result(trial_index=3)
        assert result.trial_index == 3

    def test_realism_profile_accepts_string(self) -> None:
        result = _minimal_result(realism_profile="COLD_START")
        assert result.realism_profile == "COLD_START"

    def test_realism_profile_baseline(self) -> None:
        result = _minimal_result(realism_profile="BASELINE")
        assert result.realism_profile == "BASELINE"


class TestMethodologySerialization:
    """Verify methodology fields survive serialization round-trip."""

    def test_round_trip_with_values(self) -> None:
        original = _minimal_result(
            run_temperature=0.75,
            trial_index=2,
            realism_profile="WARM_CACHE",
        )
        dumped = original.model_dump()
        restored = TestResult.model_validate(dumped)

        assert restored.run_temperature == 0.75
        assert restored.trial_index == 2
        assert restored.realism_profile == "WARM_CACHE"

    def test_round_trip_with_none(self) -> None:
        original = _minimal_result()
        dumped = original.model_dump()
        restored = TestResult.model_validate(dumped)

        assert restored.run_temperature is None
        assert restored.trial_index is None
        assert restored.realism_profile is None

    def test_model_dump_contains_keys(self) -> None:
        result = _minimal_result(run_temperature=0.5)
        dumped = result.model_dump()
        assert "run_temperature" in dumped
        assert "trial_index" in dumped
        assert "realism_profile" in dumped


class TestMethodologySchemaSQL:
    """Verify DDL schema file contains methodology columns."""

    def test_schema_has_run_temperature_column(self) -> None:
        with open("sql/schema/results_tables.sql") as f:
            ddl = f.read()
        assert "run_temperature" in ddl.lower()

    def test_schema_has_trial_index_column(self) -> None:
        with open("sql/schema/results_tables.sql") as f:
            ddl = f.read()
        assert "trial_index" in ddl.lower()

    def test_schema_has_realism_profile_column(self) -> None:
        with open("sql/schema/results_tables.sql") as f:
            ddl = f.read()
        assert "realism_profile" in ddl.lower()
