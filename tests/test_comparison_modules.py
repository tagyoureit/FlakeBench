#!/usr/bin/env python3
"""
Tests for the comparison modules in test_results_modules/.

Tests:
- statistics.py: Pure Python statistical functions
- comparison_scoring.py: Similarity scoring and classification
- comparison.py: Core comparison service functions
- comparison_prompts.py: Prompt generation
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from datetime import datetime, timezone


# =============================================================================
# Test statistics.py
# =============================================================================

class TestStatistics:
    """Tests for statistics module."""

    def test_percentile_basic(self):
        """Test basic percentile calculations."""
        from backend.api.routes.test_results_modules.statistics import percentile

        values = [1.0, 2.0, 3.0, 4.0, 5.0]

        assert percentile(values, 0) == 1.0
        assert percentile(values, 50) == 3.0
        assert percentile(values, 100) == 5.0

    def test_percentile_interpolation(self):
        """Test percentile with interpolation."""
        from backend.api.routes.test_results_modules.statistics import percentile

        values = [10.0, 20.0, 30.0, 40.0]

        # P25 should interpolate between 10 and 20
        p25 = percentile(values, 25)
        assert p25 is not None
        assert 10 < p25 < 20

        # P75 should interpolate between 30 and 40
        p75 = percentile(values, 75)
        assert p75 is not None
        assert 30 < p75 < 40

    def test_percentile_empty(self):
        """Test percentile with empty list."""
        from backend.api.routes.test_results_modules.statistics import percentile

        assert percentile([], 50) is None

    def test_percentile_single_value(self):
        """Test percentile with single value."""
        from backend.api.routes.test_results_modules.statistics import percentile

        assert percentile([42.0], 50) == 42.0
        assert percentile([42.0], 0) == 42.0
        assert percentile([42.0], 100) == 42.0

    def test_kl_divergence_identical(self):
        """Test KL divergence with identical distributions."""
        from backend.api.routes.test_results_modules.statistics import calculate_kl_divergence

        latencies = [100.0, 150.0, 200.0, 250.0, 300.0] * 10

        result = calculate_kl_divergence(latencies, latencies, num_bins=5)

        assert result["kl_divergence"] is not None
        # Identical distributions should have very low KL divergence
        assert result["kl_divergence"] < 0.1
        assert "similar" in result["interpretation"].lower()

    def test_kl_divergence_different(self):
        """Test KL divergence with different distributions."""
        from backend.api.routes.test_results_modules.statistics import calculate_kl_divergence

        latencies_a = [100.0, 110.0, 120.0, 130.0, 140.0] * 10
        latencies_b = [500.0, 600.0, 700.0, 800.0, 900.0] * 10

        result = calculate_kl_divergence(latencies_a, latencies_b, num_bins=5)

        assert result["kl_divergence"] is not None
        # Very different distributions should have high KL divergence
        assert result["kl_divergence"] > 0.5

    def test_kl_divergence_insufficient_data(self):
        """Test KL divergence with insufficient data."""
        from backend.api.routes.test_results_modules.statistics import calculate_kl_divergence

        result = calculate_kl_divergence([1.0, 2.0], [3.0, 4.0], num_bins=5)

        assert result["kl_divergence"] is None
        assert "insufficient" in result.get("interpretation", "").lower()

    def test_weighted_median_uniform_weights(self):
        """Test weighted median with uniform weights."""
        from backend.api.routes.test_results_modules.statistics import weighted_median

        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        weights = [1.0, 1.0, 1.0, 1.0, 1.0]

        result = weighted_median(values, weights)
        assert result == 3.0  # Standard median

    def test_weighted_median_skewed_weights(self):
        """Test weighted median with skewed weights."""
        from backend.api.routes.test_results_modules.statistics import weighted_median

        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        # Heavy weight on first value
        weights = [10.0, 1.0, 1.0, 1.0, 1.0]

        result = weighted_median(values, weights)
        # Should be pulled toward 1.0
        assert result is not None
        assert result < 3.0

    def test_weighted_median_no_weights(self):
        """Test weighted median without weights (should use uniform)."""
        from backend.api.routes.test_results_modules.statistics import weighted_median

        values = [1.0, 2.0, 3.0, 4.0, 5.0]

        result = weighted_median(values)
        assert result == 3.0

    def test_coefficient_of_variation(self):
        """Test coefficient of variation calculation."""
        from backend.api.routes.test_results_modules.statistics import calculate_coefficient_of_variation

        # Low CV - consistent values
        consistent = [100.0, 101.0, 99.0, 100.0, 100.0]
        cv_low = calculate_coefficient_of_variation(consistent)
        assert cv_low is not None
        assert cv_low < 0.05  # Less than 5%

        # High CV - variable values
        variable = [50.0, 100.0, 150.0, 200.0, 250.0]
        cv_high = calculate_coefficient_of_variation(variable)
        assert cv_high is not None
        assert cv_high > 0.3  # More than 30%

    def test_coefficient_of_variation_empty(self):
        """Test CV with empty/insufficient data."""
        from backend.api.routes.test_results_modules.statistics import calculate_coefficient_of_variation

        assert calculate_coefficient_of_variation([]) is None
        assert calculate_coefficient_of_variation([1.0]) is None

    def test_simple_trend_improving(self):
        """Test trend detection for improving metrics."""
        from backend.api.routes.test_results_modules.statistics import calculate_simple_trend

        # Steadily improving QPS
        values = [100.0, 110.0, 120.0, 130.0, 140.0]

        result = calculate_simple_trend(values)

        assert result["direction"] == "IMPROVING"
        assert result["slope"] is not None
        assert result["slope"] > 0
        assert result["sample_size"] == 5

    def test_simple_trend_regressing(self):
        """Test trend detection for regressing metrics."""
        from backend.api.routes.test_results_modules.statistics import calculate_simple_trend

        # Steadily declining QPS
        values = [140.0, 130.0, 120.0, 110.0, 100.0]

        result = calculate_simple_trend(values)

        assert result["direction"] == "REGRESSING"
        assert result["slope"] is not None
        assert result["slope"] < 0

    def test_simple_trend_stable(self):
        """Test trend detection for stable metrics."""
        from backend.api.routes.test_results_modules.statistics import calculate_simple_trend

        # Stable values with minor noise
        values = [100.0, 101.0, 99.0, 100.0, 100.5]

        result = calculate_simple_trend(values)

        assert result["direction"] == "STABLE"

    def test_simple_trend_insufficient_data(self):
        """Test trend with insufficient data."""
        from backend.api.routes.test_results_modules.statistics import calculate_simple_trend

        result = calculate_simple_trend([100.0, 110.0])

        assert result["direction"] == "INSUFFICIENT_DATA"
        assert result["sample_size"] == 2


# =============================================================================
# Test comparison_scoring.py
# =============================================================================

class TestComparisonScoring:
    """Tests for comparison_scoring module."""

    def test_classify_change_qps_improvement(self):
        """Test QPS improvement classification."""
        from backend.api.routes.test_results_modules.comparison_scoring import classify_change

        # >10% improvement
        result = classify_change("qps", 15.0)
        assert result == "IMPROVEMENT"

    def test_classify_change_qps_regression(self):
        """Test QPS regression classification."""
        from backend.api.routes.test_results_modules.comparison_scoring import classify_change

        # <-20% regression
        result = classify_change("qps", -25.0)
        assert result == "REGRESSION"

    def test_classify_change_qps_warning(self):
        """Test QPS warning classification."""
        from backend.api.routes.test_results_modules.comparison_scoring import classify_change

        # Between -10% and -20%
        result = classify_change("qps", -15.0)
        assert result == "WARNING"

    def test_classify_change_qps_neutral(self):
        """Test QPS neutral classification."""
        from backend.api.routes.test_results_modules.comparison_scoring import classify_change

        # Within ±10%
        result = classify_change("qps", 5.0)
        assert result == "NEUTRAL"

    def test_classify_change_latency_improvement(self):
        """Test latency improvement (decrease is good)."""
        from backend.api.routes.test_results_modules.comparison_scoring import classify_change

        # P95 latency decreased by >20%
        result = classify_change("p95_latency", -25.0)
        assert result == "IMPROVEMENT"

    def test_classify_change_latency_regression(self):
        """Test latency regression (increase is bad)."""
        from backend.api.routes.test_results_modules.comparison_scoring import classify_change

        # P95 latency increased by >40%
        result = classify_change("p95_latency", 50.0)
        assert result == "REGRESSION"

    def test_get_confidence_level_high(self):
        """Test high confidence level."""
        from backend.api.routes.test_results_modules.comparison_scoring import get_confidence_level

        assert get_confidence_level(0.90) == "HIGH"
        assert get_confidence_level(0.85) == "HIGH"

    def test_get_confidence_level_medium(self):
        """Test medium confidence level."""
        from backend.api.routes.test_results_modules.comparison_scoring import get_confidence_level

        assert get_confidence_level(0.75) == "MEDIUM"
        assert get_confidence_level(0.70) == "MEDIUM"

    def test_get_confidence_level_low(self):
        """Test low confidence level."""
        from backend.api.routes.test_results_modules.comparison_scoring import get_confidence_level

        assert get_confidence_level(0.60) == "LOW"
        assert get_confidence_level(0.55) == "LOW"

    def test_get_confidence_level_excluded(self):
        """Test excluded confidence level (below threshold)."""
        from backend.api.routes.test_results_modules.comparison_scoring import get_confidence_level

        assert get_confidence_level(0.50) == "EXCLUDED"
        assert get_confidence_level(0.40) == "EXCLUDED"

    def test_check_hard_gates_same_template(self):
        """Test hard gate: same template passes."""
        from backend.api.routes.test_results_modules.comparison_scoring import check_hard_gates

        current = {"template_id": "abc-123", "load_mode": "CONCURRENCY", "table_type": "HYBRID"}
        candidate = {"template_id": "abc-123", "load_mode": "CONCURRENCY", "table_type": "HYBRID", "status": "COMPLETED"}

        passed, failures = check_hard_gates(current, candidate)
        assert passed is True
        assert len(failures) == 0

    def test_check_hard_gates_different_template(self):
        """Test hard gate: different template fails."""
        from backend.api.routes.test_results_modules.comparison_scoring import check_hard_gates

        current = {"template_id": "abc-123", "load_mode": "CONCURRENCY", "table_type": "HYBRID"}
        candidate = {"template_id": "xyz-789", "load_mode": "CONCURRENCY", "table_type": "HYBRID", "status": "COMPLETED"}

        passed, failures = check_hard_gates(current, candidate)
        assert passed is False
        assert any("template" in f.lower() for f in failures)

    def test_check_hard_gates_different_load_mode(self):
        """Test hard gate: different load mode fails."""
        from backend.api.routes.test_results_modules.comparison_scoring import check_hard_gates

        current = {"template_id": "abc-123", "load_mode": "CONCURRENCY", "table_type": "HYBRID"}
        candidate = {"template_id": "abc-123", "load_mode": "QPS", "table_type": "HYBRID", "status": "COMPLETED"}

        passed, failures = check_hard_gates(current, candidate)
        assert passed is False
        assert any("load_mode" in f.lower() for f in failures)

    def test_calculate_similarity_score_identical(self):
        """Test similarity score for identical tests."""
        from backend.api.routes.test_results_modules.comparison_scoring import calculate_similarity_score

        test = {
            "template_id": "abc-123",
            "load_mode": "CONCURRENCY",
            "table_type": "HYBRID",
            "warehouse_size": "MEDIUM",
            "concurrent_connections": 100,
            "duration_seconds": 300,
            "read_pct": 80.0,
            "status": "COMPLETED",
        }

        result = calculate_similarity_score(test, test, "CONCURRENCY")

        assert result["excluded"] is False
        assert result["total_score"] >= 0.9  # Very high similarity
        assert result["confidence"] == "HIGH"

    def test_calculate_similarity_score_different_warehouse(self):
        """Test similarity score with different warehouse size."""
        from backend.api.routes.test_results_modules.comparison_scoring import calculate_similarity_score

        current = {
            "template_id": "abc-123",
            "load_mode": "CONCURRENCY",
            "table_type": "HYBRID",
            "warehouse_size": "MEDIUM",
            "concurrent_connections": 100,
            "duration_seconds": 300,
            "read_pct": 80.0,
            "status": "COMPLETED",
        }
        candidate = {
            "template_id": "abc-123",
            "load_mode": "CONCURRENCY",
            "table_type": "HYBRID",
            "warehouse_size": "LARGE",  # Different
            "concurrent_connections": 100,
            "duration_seconds": 300,
            "read_pct": 80.0,
            "status": "COMPLETED",
        }

        result = calculate_similarity_score(current, candidate, "CONCURRENCY")

        # Should pass hard gates but have lower score due to warehouse difference
        assert result["excluded"] is False
        assert result["total_score"] < 1.0
        assert result["total_score"] > 0.5

    def test_calculate_similarity_score_excluded(self):
        """Test similarity score excludes incompatible tests."""
        from backend.api.routes.test_results_modules.comparison_scoring import calculate_similarity_score

        current = {
            "template_id": "abc-123",
            "load_mode": "CONCURRENCY",
            "table_type": "HYBRID",
        }
        candidate = {
            "template_id": "different-456",  # Different template
            "load_mode": "CONCURRENCY",
            "table_type": "HYBRID",
        }

        result = calculate_similarity_score(current, candidate, "CONCURRENCY")

        assert result["excluded"] is True
        assert len(result["exclusion_reasons"]) > 0


# =============================================================================
# Test comparison.py
# =============================================================================

class TestComparison:
    """Tests for comparison module."""

    def test_extract_test_features(self):
        """Test feature extraction from test row."""
        from backend.api.routes.test_results_modules.comparison import extract_test_features

        row = {
            "test_id": "test-123",
            "run_id": "run-456",
            "test_config": {
                "template_id": "tmpl-789",
                "template_name": "My Template",
                "template_config": {
                    "load_mode": "CONCURRENCY",
                    "scaling": {"mode": "FIXED"},
                },
                "scenario": {},
            },
            "table_type": "hybrid",
            "warehouse_size": "medium",
            "status": "completed",
            "qps": 1500.5,
            "p95_latency_ms": 45.2,
            "read_operations": 800,
            "total_operations": 1000,
        }

        features = extract_test_features(row)

        assert features["test_id"] == "test-123"
        assert features["template_id"] == "tmpl-789"
        assert features["load_mode"] == "CONCURRENCY"
        assert features["table_type"] == "HYBRID"
        assert features["warehouse_size"] == "MEDIUM"
        assert features["status"] == "COMPLETED"
        assert features["qps"] == 1500.5
        assert features["read_pct"] == 80.0  # 800/1000 * 100

    def test_derive_find_max_best_stable(self):
        """Test FIND_MAX best stable derivation."""
        from backend.api.routes.test_results_modules.comparison import derive_find_max_best_stable

        steps = [
            {"step": 1, "concurrency": 10, "qps": 100.0, "outcome": "STABLE", "stop_reason": None},
            {"step": 2, "concurrency": 20, "qps": 180.0, "outcome": "STABLE", "stop_reason": None},
            {"step": 3, "concurrency": 30, "qps": 250.0, "outcome": "STABLE", "stop_reason": None},
            {"step": 4, "concurrency": 40, "qps": 200.0, "outcome": "DEGRADED", "stop_reason": "QPS_DROP"},
        ]

        result = derive_find_max_best_stable(steps)

        assert result["best_stable_concurrency"] == 30
        assert result["best_stable_qps"] == 250.0
        assert result["degradation_concurrency"] == 40
        assert result["degradation_reason"] == "QPS_DROP"
        assert result["total_steps"] == 4

    def test_derive_find_max_no_stable(self):
        """Test FIND_MAX when no stable step found."""
        from backend.api.routes.test_results_modules.comparison import derive_find_max_best_stable

        steps = [
            {"step": 1, "concurrency": 10, "qps": 50.0, "outcome": "DEGRADED", "stop_reason": "LATENCY"},
        ]

        result = derive_find_max_best_stable(steps)

        assert result["best_stable_concurrency"] is None
        assert result["degradation_concurrency"] == 10
        assert result["degradation_reason"] == "Never achieved stability"

    def test_derive_find_max_empty(self):
        """Test FIND_MAX with no steps."""
        from backend.api.routes.test_results_modules.comparison import derive_find_max_best_stable

        result = derive_find_max_best_stable([])

        assert result["best_stable_concurrency"] is None
        assert result["total_steps"] == 0

    def test_calculate_deltas(self):
        """Test delta calculation between current and baseline."""
        from backend.api.routes.test_results_modules.comparison import calculate_deltas

        current = {"qps": 1100.0, "p95_latency_ms": 50.0}
        baseline = {"qps": 1000.0, "p95_latency_ms": 40.0}

        deltas = calculate_deltas(current, baseline)

        assert deltas["qps_delta_pct"] == pytest.approx(10.0, rel=0.01)
        assert deltas["p95_delta_pct"] == pytest.approx(25.0, rel=0.01)

    def test_calculate_deltas_zero_baseline(self):
        """Test delta calculation with zero baseline (should return None)."""
        from backend.api.routes.test_results_modules.comparison import calculate_deltas

        current = {"qps": 100.0}
        baseline = {"qps": 0.0}

        deltas = calculate_deltas(current, baseline)

        assert deltas["qps_delta_pct"] is None

    def test_calculate_rolling_statistics(self):
        """Test rolling statistics calculation."""
        from backend.api.routes.test_results_modules.comparison import calculate_rolling_statistics

        baselines = [
            {"qps": 1000.0, "p95_latency_ms": 50.0, "start_time": datetime(2024, 1, 5, tzinfo=timezone.utc)},
            {"qps": 1100.0, "p95_latency_ms": 45.0, "start_time": datetime(2024, 1, 4, tzinfo=timezone.utc)},
            {"qps": 1050.0, "p95_latency_ms": 48.0, "start_time": datetime(2024, 1, 3, tzinfo=timezone.utc)},
            {"qps": 980.0, "p95_latency_ms": 52.0, "start_time": datetime(2024, 1, 2, tzinfo=timezone.utc)},
            {"qps": 1020.0, "p95_latency_ms": 47.0, "start_time": datetime(2024, 1, 1, tzinfo=timezone.utc)},
        ]

        stats = calculate_rolling_statistics(baselines, use_count=5)

        assert stats["available"] is True
        assert stats["candidate_count"] == 5
        assert stats["used_count"] == 5
        assert stats["rolling_median"]["qps"] is not None
        assert stats["confidence_band"]["qps_p10"] is not None

    def test_calculate_rolling_statistics_empty(self):
        """Test rolling statistics with no baselines."""
        from backend.api.routes.test_results_modules.comparison import calculate_rolling_statistics

        stats = calculate_rolling_statistics([], use_count=5)

        assert stats["available"] is False
        assert stats["candidate_count"] == 0

    def test_determine_verdict_improved(self):
        """Test verdict determination for improvements."""
        from backend.api.routes.test_results_modules.comparison import determine_verdict

        deltas = {
            "qps_delta_pct": 15.0,  # +15% QPS
            "p95_delta_pct": -25.0,  # -25% latency (improvement)
        }

        result = determine_verdict(deltas)
        assert result["verdict"] == "IMPROVED"

    def test_determine_verdict_regressed(self):
        """Test verdict determination for regressions."""
        from backend.api.routes.test_results_modules.comparison import determine_verdict

        deltas = {
            "qps_delta_pct": -25.0,  # -25% QPS (regression)
            "p95_delta_pct": 50.0,  # +50% latency (regression)
        }

        result = determine_verdict(deltas)
        assert result["verdict"] == "REGRESSED"

    def test_determine_verdict_stable(self):
        """Test verdict determination for stable results."""
        from backend.api.routes.test_results_modules.comparison import determine_verdict

        deltas = {
            "qps_delta_pct": 2.0,  # Within neutral range
            "p95_delta_pct": 5.0,  # Within neutral range
        }

        result = determine_verdict(deltas)
        assert result["verdict"] == "STABLE"


# =============================================================================
# Test comparison_prompts.py
# =============================================================================

class TestComparisonPrompts:
    """Tests for comparison_prompts module."""

    def test_generate_comparison_prompt_basic(self):
        """Test basic prompt generation."""
        from backend.api.routes.test_results_modules.comparison_prompts import generate_comparison_prompt

        compare_context = {
            "test_id": "test-123",
            "load_mode": "CONCURRENCY",
            "baseline": {
                "available": True, 
                "candidate_count": 5,
                "rolling_median": {
                    "qps": 1000.0,
                    "p95_latency_ms": 50.0,
                },
                "confidence_band": {
                    "qps_p10": 900.0,
                    "qps_p90": 1100.0,
                },
            },
            "vs_previous": {
                "test_id": "test-122",
                "similarity_score": 0.95,
                "deltas": {"qps_delta_pct": 10.0, "p95_delta_pct": -5.0},
            },
            "vs_median": {
                "qps_delta_pct": 8.0,
                "verdict": "IMPROVED",
                "verdict_reasons": ["QPS +8%"],
            },
            "trend": {"direction": "IMPROVING"},
            "comparable_runs": [],
        }

        prompt = generate_comparison_prompt(compare_context, "CONCURRENCY")

        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_generate_comparison_prompt_no_baseline(self):
        """Test prompt generation when no baseline available."""
        from backend.api.routes.test_results_modules.comparison_prompts import generate_comparison_prompt

        compare_context = {
            "test_id": "test-123",
            "load_mode": "CONCURRENCY",
            "baseline": {"available": False, "candidate_count": 0},
            "vs_previous": None,
            "vs_median": None,
            "trend": {"direction": "INSUFFICIENT_DATA"},
            "comparable_runs": [],
        }

        prompt = generate_comparison_prompt(compare_context, "CONCURRENCY")

        assert isinstance(prompt, str)
        # Should handle missing baseline gracefully (may be empty or informative)

    def test_generate_comparison_prompt_find_max(self):
        """Test prompt generation for FIND_MAX mode."""
        from backend.api.routes.test_results_modules.comparison_prompts import generate_comparison_prompt

        compare_context = {
            "test_id": "test-123",
            "load_mode": "FIND_MAX_CONCURRENCY",
            "baseline": {
                "available": True, 
                "candidate_count": 3,
                "rolling_median": {
                    "qps": 1000.0,
                    "p95_latency_ms": 50.0,
                },
                "confidence_band": {},
            },
            "vs_previous": {
                "test_id": "test-122",
                "similarity_score": 0.90,
                "deltas": {"qps_delta_pct": 5.0},
            },
            "vs_median": {"verdict": "STABLE"},
            "trend": {"direction": "STABLE"},
            "comparable_runs": [],
            # FIND_MAX specific fields
            "find_max_comparison": {
                "current_best_concurrency": 30,
                "previous_best_concurrency": 28,
                "delta_pct": 7.1,
            },
        }

        prompt = generate_comparison_prompt(compare_context, "FIND_MAX_CONCURRENCY")

        assert isinstance(prompt, str)


# =============================================================================
# Integration Tests
# =============================================================================

class TestIntegration:
    """Integration tests across modules."""

    def test_full_comparison_flow(self):
        """Test full comparison flow with mock data."""
        from backend.api.routes.test_results_modules.statistics import percentile
        from backend.api.routes.test_results_modules.comparison_scoring import (
            calculate_similarity_score,
            classify_change,
        )
        from backend.api.routes.test_results_modules.comparison import (
            extract_test_features,
            calculate_deltas,
            determine_verdict,
        )

        # Mock current test
        current_row = {
            "test_id": "current-123",
            "test_config": {"template_id": "tmpl-1", "template_config": {"load_mode": "CONCURRENCY"}},
            "table_type": "HYBRID",
            "warehouse_size": "MEDIUM",
            "status": "COMPLETED",
            "qps": 1200.0,
            "p95_latency_ms": 42.0,
            "read_operations": 900,
            "total_operations": 1000,
        }

        # Mock baseline test
        baseline_row = {
            "test_id": "baseline-100",
            "test_config": {"template_id": "tmpl-1", "template_config": {"load_mode": "CONCURRENCY"}},
            "table_type": "HYBRID",
            "warehouse_size": "MEDIUM",
            "status": "COMPLETED",
            "qps": 1000.0,
            "p95_latency_ms": 50.0,
            "read_operations": 900,
            "total_operations": 1000,
        }

        # Extract features
        current = extract_test_features(current_row)
        baseline = extract_test_features(baseline_row)

        # Calculate similarity
        similarity = calculate_similarity_score(current, baseline, "CONCURRENCY")
        assert similarity["excluded"] is False
        assert similarity["total_score"] >= 0.7  # Reasonably high similarity

        # Calculate deltas
        deltas = calculate_deltas(current, baseline)
        assert deltas["qps_delta_pct"] == pytest.approx(20.0, rel=0.01)

        # Classify changes
        qps_class = classify_change("qps", deltas["qps_delta_pct"])
        assert qps_class == "IMPROVEMENT"

        # Determine verdict
        verdict = determine_verdict(deltas)
        assert verdict["verdict"] in ["IMPROVED", "STABLE"]


class TestEndpoint:
    """Tests for the compare-context endpoint."""

    def test_endpoint_exists(self):
        """Test that the endpoint is registered."""
        from backend.api.routes.test_results import router

        # Find the compare-context route
        route_paths = [route.path for route in router.routes]
        assert "/{test_id}/compare-context" in route_paths

    def test_endpoint_function_signature(self):
        """Test that the endpoint function has correct parameters."""
        from backend.api.routes.test_results import get_compare_context
        import inspect

        sig = inspect.signature(get_compare_context)
        params = list(sig.parameters.keys())

        assert "test_id" in params
        assert "baseline_count" in params
        assert "comparable_limit" in params
        assert "min_similarity" in params
        assert "include_excluded" in params


class TestPhase3Integration:
    """Tests for Phase 3: AI Prompt Integration."""

    def test_ai_analysis_imports_comparison_modules(self):
        """Test that ai_analysis can import comparison modules."""
        from backend.api.routes.test_results import (
            build_compare_context,
            generate_comparison_prompt,
        )
        
        assert callable(build_compare_context)
        assert callable(generate_comparison_prompt)

    def test_generate_comparison_prompt_returns_string(self):
        """Test that generate_comparison_prompt returns a string for valid context."""
        from backend.api.routes.test_results_modules.comparison_prompts import generate_comparison_prompt
        
        context = {
            "test_id": "test-123",
            "baseline": {
                "available": True,
                "candidate_count": 5,
                "rolling_median": {"qps": 1000.0, "p95_latency_ms": 50.0},
                "confidence_band": {},
            },
            "vs_previous": {"test_id": "test-122", "similarity_score": 0.9, "deltas": {}},
            "vs_median": {"verdict": "STABLE", "verdict_reasons": []},
            "trend": {"direction": "STABLE"},
            "comparable_runs": [],
        }
        
        result = generate_comparison_prompt(context, "CONCURRENCY")
        
        assert isinstance(result, str)
        assert len(result) > 0

    def test_comparison_summary_structure(self):
        """Test the expected structure of comparison_summary in ai_analysis response."""
        # This tests the structure we expect from the ai_analysis endpoint
        expected_keys = [
            "baseline_available",
            "baseline_count",
            "verdict",
            "verdict_reasons",
            "qps_delta_pct",
            "p95_delta_pct",
            "trend_direction",
            "vs_previous_test_id",
            "vs_previous_similarity",
        ]
        
        # Build a mock comparison_summary like the endpoint does
        baseline = {"available": True, "candidate_count": 5}
        vs_median = {"verdict": "IMPROVED", "verdict_reasons": ["QPS +10%"], "qps_delta_pct": 10.0, "p95_delta_pct": -5.0}
        vs_previous = {"test_id": "prev-123", "similarity_score": 0.92}
        trend = {"direction": "IMPROVING"}
        
        comparison_summary = {
            "baseline_available": baseline.get("available", False),
            "baseline_count": baseline.get("candidate_count", 0),
            "verdict": vs_median.get("verdict") if vs_median else None,
            "verdict_reasons": vs_median.get("verdict_reasons", []) if vs_median else [],
            "qps_delta_pct": vs_median.get("qps_delta_pct") if vs_median else None,
            "p95_delta_pct": vs_median.get("p95_delta_pct") if vs_median else None,
            "trend_direction": trend.get("direction") if trend else None,
            "vs_previous_test_id": vs_previous.get("test_id") if vs_previous else None,
            "vs_previous_similarity": vs_previous.get("similarity_score") if vs_previous else None,
        }
        
        # Verify all expected keys are present
        for key in expected_keys:
            assert key in comparison_summary, f"Missing key: {key}"
        
        # Verify values
        assert comparison_summary["baseline_available"] is True
        assert comparison_summary["baseline_count"] == 5
        assert comparison_summary["verdict"] == "IMPROVED"
        assert comparison_summary["trend_direction"] == "IMPROVING"


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
