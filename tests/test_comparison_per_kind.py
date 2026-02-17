"""
Tests for per-kind metrics in comparison_prompts.py (Item 2).

Covers:
- Rolling median per-kind P95 lines present when data available
- Rolling median per-kind omitted when keys are None
- Vs-previous per-kind delta lines
- Vs-median generic_sql delta with indicator
- Deep compare per-kind delta_pct calculation
"""

from __future__ import annotations

import pytest

from backend.api.routes.test_results_modules.comparison_prompts import (
    _generate_rolling_median_section,
    _generate_vs_previous_section,
    _generate_vs_median_section,
    generate_deep_compare_prompt,
    _calc_delta_pct,
)


class TestRollingMedianPerKind:
    """Rolling median section includes per-kind P95 lines when data is present."""

    def test_per_kind_p95_present(self) -> None:
        compare_context = {
            "baseline": {
                "used_count": 5,
                "rolling_median": {
                    "qps": 100.0,
                    "p95_latency_ms": 15.0,
                    "error_rate_pct": 0.5,
                    "point_lookup_p95_latency_ms": 2.5,
                    "range_scan_p95_latency_ms": 8.0,
                    "generic_sql_p95_latency_ms": 22.0,
                },
                "confidence_band": {},
            },
        }
        result = _generate_rolling_median_section(compare_context)
        assert "Point Lookup P95: 2.5ms" in result
        assert "Range Scan P95: 8.0ms" in result
        assert "Generic SQL P95: 22.0ms" in result

    def test_per_kind_p95_omitted_when_none(self) -> None:
        compare_context = {
            "baseline": {
                "used_count": 5,
                "rolling_median": {
                    "qps": 100.0,
                    "p95_latency_ms": 15.0,
                    "error_rate_pct": 0.5,
                    # No per-kind keys
                },
                "confidence_band": {},
            },
        }
        result = _generate_rolling_median_section(compare_context)
        assert "Per-Query-Kind" not in result

    def test_partial_per_kind_only_shows_available(self) -> None:
        compare_context = {
            "baseline": {
                "used_count": 3,
                "rolling_median": {
                    "qps": 50.0,
                    "p95_latency_ms": 10.0,
                    "error_rate_pct": 0.0,
                    "insert_p95_latency_ms": 5.0,
                    # Others are absent
                },
                "confidence_band": {},
            },
        }
        result = _generate_rolling_median_section(compare_context)
        assert "Insert P95: 5.0ms" in result
        assert "Point Lookup" not in result

    def test_per_kind_includes_header(self) -> None:
        compare_context = {
            "baseline": {
                "used_count": 5,
                "rolling_median": {
                    "qps": 100.0,
                    "p95_latency_ms": 15.0,
                    "error_rate_pct": 0.5,
                    "update_p95_latency_ms": 3.0,
                },
                "confidence_band": {},
            },
        }
        result = _generate_rolling_median_section(compare_context)
        assert "Per-Query-Kind Latency Medians:" in result


class TestVsPreviousPerKind:
    """Vs-previous section includes per-kind latency change lines."""

    def test_per_kind_deltas_present(self) -> None:
        vs_previous = {
            "test_date": "2025-01-15",
            "confidence": "HIGH",
            "deltas": {
                "qps_delta_pct": 5.0,
                "p95_delta_pct": -3.0,
                "point_lookup_p95_delta_pct": -2.5,
                "range_scan_p95_delta_pct": 10.0,
                "generic_sql_p95_delta_pct": -5.0,
            },
        }
        result = _generate_vs_previous_section(vs_previous)
        assert "Point Lookup P95 change: -2.5%" in result
        assert "Range Scan P95 change: +10.0%" in result
        assert "Generic SQL P95 change: -5.0%" in result

    def test_per_kind_omitted_when_absent(self) -> None:
        vs_previous = {
            "test_date": "2025-01-15",
            "confidence": "HIGH",
            "deltas": {
                "qps_delta_pct": 5.0,
                "p95_delta_pct": -3.0,
                # No per-kind deltas
            },
        }
        result = _generate_vs_previous_section(vs_previous)
        assert "Per-Kind" not in result

    def test_per_kind_partial(self) -> None:
        vs_previous = {
            "test_date": "2025-01-15",
            "confidence": "MEDIUM",
            "deltas": {
                "qps_delta_pct": 0.0,
                "p95_delta_pct": 0.0,
                "insert_p95_delta_pct": 12.5,
            },
        }
        result = _generate_vs_previous_section(vs_previous)
        assert "Insert P95 change: +12.5%" in result
        assert "Point Lookup" not in result


class TestVsMedianGenericSQL:
    """Vs-median section includes Generic SQL P95 delta with indicator."""

    def test_generic_sql_delta_with_indicator(self) -> None:
        vs_median = {
            "qps_delta_pct": 5.0,
            "p95_delta_pct": -3.0,
            "verdict": "STABLE",
            "verdict_reasons": [],
            "generic_sql_p95_delta_pct": 25.0,  # +25% latency => WARNING
        }
        result = _generate_vs_median_section(vs_median)
        assert "Generic SQL P95: +25.0%" in result
        # The classify_change for p95_latency +25% => WARNING
        assert "(WARNING)" in result

    def test_generic_sql_delta_improvement(self) -> None:
        vs_median = {
            "qps_delta_pct": 5.0,
            "p95_delta_pct": -3.0,
            "verdict": "STABLE",
            "verdict_reasons": [],
            "generic_sql_p95_delta_pct": -25.0,  # -25% latency => IMPROVEMENT
        }
        result = _generate_vs_median_section(vs_median)
        assert "Generic SQL P95: -25.0%" in result
        assert "(IMPROVED)" in result

    def test_no_generic_sql_delta_omitted(self) -> None:
        vs_median = {
            "qps_delta_pct": 5.0,
            "p95_delta_pct": -3.0,
            "verdict": "STABLE",
            "verdict_reasons": [],
            # No generic_sql_p95_delta_pct
        }
        result = _generate_vs_median_section(vs_median)
        assert "Generic SQL P95" not in result


class TestDeepComparePerKind:
    """generate_deep_compare_prompt computes per-kind delta_pct correctly."""

    def test_per_kind_deltas_in_result(self) -> None:
        test_a = {
            "qps": 100.0,
            "p50_latency_ms": 5.0,
            "p95_latency_ms": 15.0,
            "p99_latency_ms": 30.0,
            "point_lookup_p95_latency_ms": 2.0,
            "range_scan_p95_latency_ms": 10.0,
            "generic_sql_p95_latency_ms": 20.0,
        }
        test_b = {
            "qps": 80.0,
            "p50_latency_ms": 6.0,
            "p95_latency_ms": 18.0,
            "p99_latency_ms": 35.0,
            "point_lookup_p95_latency_ms": 2.5,
            "range_scan_p95_latency_ms": 8.0,
            "generic_sql_p95_latency_ms": 25.0,
        }
        _prompt, deltas = generate_deep_compare_prompt(test_a, test_b)

        # Per-kind delta keys follow pattern: X_p95_delta_pct
        assert "point_lookup_p95_delta_pct" in deltas
        assert "range_scan_p95_delta_pct" in deltas
        assert "generic_sql_p95_delta_pct" in deltas

        # point_lookup: (2.0 - 2.5) / 2.5 * 100 = -20.0%
        assert deltas["point_lookup_p95_delta_pct"] == pytest.approx(-20.0, abs=0.1)

        # range_scan: (10.0 - 8.0) / 8.0 * 100 = +25.0%
        assert deltas["range_scan_p95_delta_pct"] == pytest.approx(25.0, abs=0.1)

        # generic_sql: (20.0 - 25.0) / 25.0 * 100 = -20.0%
        assert deltas["generic_sql_p95_delta_pct"] == pytest.approx(-20.0, abs=0.1)

    def test_per_kind_delta_none_when_missing(self) -> None:
        test_a = {
            "qps": 100.0,
            "p50_latency_ms": 5.0,
            "p95_latency_ms": 15.0,
            "p99_latency_ms": 30.0,
        }
        test_b = {
            "qps": 80.0,
            "p50_latency_ms": 6.0,
            "p95_latency_ms": 18.0,
            "p99_latency_ms": 35.0,
        }
        _prompt, deltas = generate_deep_compare_prompt(test_a, test_b)
        # Keys should exist but be None
        assert deltas.get("point_lookup_p95_delta_pct") is None
        assert deltas.get("generic_sql_p95_delta_pct") is None


class TestCalcDeltaPct:
    """Unit tests for the _calc_delta_pct helper."""

    def test_positive_delta(self) -> None:
        assert _calc_delta_pct(110.0, 100.0) == pytest.approx(10.0)

    def test_negative_delta(self) -> None:
        assert _calc_delta_pct(80.0, 100.0) == pytest.approx(-20.0)

    def test_none_a(self) -> None:
        assert _calc_delta_pct(None, 100.0) is None

    def test_none_b(self) -> None:
        assert _calc_delta_pct(100.0, None) is None

    def test_zero_b(self) -> None:
        assert _calc_delta_pct(100.0, 0.0) is None
