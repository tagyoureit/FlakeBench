"""
Results Helpers Package

Helper functions for test results routes that can be imported to reduce
the size of the main test_results.py file.

Usage:
    from backend.api.routes.results_helpers import (
        get_prefix,
        error_reason,
        normalize_error_message,
        compute_aggregated_find_max,
    )
"""

from .helpers import (
    LATENCY_AGGREGATION_METHOD,
    aggregate_parent_enrichment_stats,
    aggregate_parent_enrichment_status,
    compute_aggregated_find_max,
    error_reason,
    fetch_run_status,
    get_prefix,
    normalize_error_message,
    to_float_or_none,
)

__all__ = [
    "LATENCY_AGGREGATION_METHOD",
    "get_prefix",
    "error_reason",
    "normalize_error_message",
    "to_float_or_none",
    "fetch_run_status",
    "aggregate_parent_enrichment_status",
    "aggregate_parent_enrichment_stats",
    "compute_aggregated_find_max",
]
