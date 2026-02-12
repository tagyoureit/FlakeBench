"""
Test Results Package

This package contains the API routes for test results,
split into logical modules for better maintainability.

Modules:
- utils: Helper functions (cost calculation, error normalization)
- queries: Database fetch functions
- statistics: Pure Python statistical utilities
- comparison_scoring: Similarity scoring and classification
- comparison: Core comparison service
- comparison_prompts: AI prompt generation for comparisons

The main router is imported from the parent module for
backward compatibility.
"""

from .utils import (
    get_prefix,
    build_cost_fields,
    error_reason,
    normalize_error_message,
    to_float_or_none,
    compute_latency_spread,
    compute_aggregated_find_max,
    LATENCY_AGGREGATION_METHOD,
)
from .queries import (
    fetch_run_status,
    aggregate_parent_enrichment_status,
    aggregate_parent_enrichment_stats,
    fetch_warehouse_metrics,
    fetch_postgres_stats,
    fetch_pg_enrichment,
    fetch_cluster_breakdown,
)
from .statistics import (
    percentile,
    calculate_kl_divergence,
    weighted_median,
    calculate_coefficient_of_variation,
    calculate_simple_trend,
)
from .comparison_scoring import (
    REGRESSION_THRESHOLDS,
    CONFIDENCE_BANDS,
    WAREHOUSE_SIZE_ORDER,
    SCORING_WEIGHTS,
    classify_change,
    get_confidence_level,
    check_hard_gates,
    warehouse_size_match_score,
    calculate_similarity_score,
    calculate_similarity_score_concurrency,
    calculate_similarity_score_qps,
    calculate_similarity_score_find_max,
    format_exclusion_reason,
)
from .comparison import (
    extract_test_features,
    derive_find_max_best_stable,
    fetch_baseline_candidates,
    fetch_current_test,
    fetch_step_history,
    calculate_rolling_statistics,
    calculate_deltas,
    determine_verdict,
    build_compare_context,
)
from .comparison_prompts import (
    generate_comparison_prompt,
    generate_find_max_comparison_prompt,
    generate_regression_investigation_prompt,
    generate_comparison_summary,
)

__all__ = [
    # Utils
    "get_prefix",
    "build_cost_fields",
    "error_reason",
    "normalize_error_message",
    "to_float_or_none",
    "compute_latency_spread",
    "compute_aggregated_find_max",
    "LATENCY_AGGREGATION_METHOD",
    # Queries
    "fetch_run_status",
    "aggregate_parent_enrichment_status",
    "aggregate_parent_enrichment_stats",
    "fetch_warehouse_metrics",
    "fetch_postgres_stats",
    "fetch_pg_enrichment",
    "fetch_cluster_breakdown",
    # Statistics
    "percentile",
    "calculate_kl_divergence",
    "weighted_median",
    "calculate_coefficient_of_variation",
    "calculate_simple_trend",
    # Comparison Scoring
    "REGRESSION_THRESHOLDS",
    "CONFIDENCE_BANDS",
    "WAREHOUSE_SIZE_ORDER",
    "SCORING_WEIGHTS",
    "classify_change",
    "get_confidence_level",
    "check_hard_gates",
    "warehouse_size_match_score",
    "calculate_similarity_score",
    "calculate_similarity_score_concurrency",
    "calculate_similarity_score_qps",
    "calculate_similarity_score_find_max",
    "format_exclusion_reason",
    # Comparison Service
    "extract_test_features",
    "derive_find_max_best_stable",
    "fetch_baseline_candidates",
    "fetch_current_test",
    "fetch_step_history",
    "calculate_rolling_statistics",
    "calculate_deltas",
    "determine_verdict",
    "build_compare_context",
    # Comparison Prompts
    "generate_comparison_prompt",
    "generate_find_max_comparison_prompt",
    "generate_regression_investigation_prompt",
    "generate_comparison_summary",
]
