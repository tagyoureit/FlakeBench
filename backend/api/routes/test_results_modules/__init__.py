"""
Test Results Package

This package contains the API routes for test results,
split into logical modules for better maintainability.

Modules:
- utils: Helper functions (cost calculation, error normalization)
- queries: Database fetch functions
- ai_analysis: AI prompt building (to be added)

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
]
