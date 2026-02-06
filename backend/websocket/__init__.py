"""
WebSocket handlers package for real-time test metrics streaming.

This package provides:
- Helpers: Utility functions for datetime coercion, dict parsing
- Queries: Database queries for run status, enrichment, logs
- Metrics: Metrics aggregation for multi-worker tests
- Streaming: Main WebSocket streaming logic

All symbols are re-exported for backward compatibility.
"""

# Helper utilities
from .helpers import (
    _coerce_datetime,
    _parse_variant_dict,
    _to_int,
    _to_float,
    _sum_dicts,
    _avg_dicts,
    _health_from,
)

# Database queries
from .queries import (
    get_parent_test_status,
    fetch_run_status,
    fetch_run_test_ids,
    fetch_warehouse_context,
    fetch_parent_enrichment_status,
    fetch_enrichment_progress,
    fetch_logs_since_seq,
    fetch_logs_for_tests,
)

# Metrics aggregation
from .metrics import (
    build_aggregate_metrics,
    build_run_snapshot,
    aggregate_multi_worker_metrics,
)

# Streaming
from .streaming import stream_run_metrics

__all__ = [
    # Helpers
    "_coerce_datetime",
    "_parse_variant_dict",
    "_to_int",
    "_to_float",
    "_sum_dicts",
    "_avg_dicts",
    "_health_from",
    # Queries
    "get_parent_test_status",
    "fetch_run_status",
    "fetch_run_test_ids",
    "fetch_warehouse_context",
    "fetch_parent_enrichment_status",
    "fetch_enrichment_progress",
    "fetch_logs_since_seq",
    "fetch_logs_for_tests",
    # Metrics
    "build_aggregate_metrics",
    "build_run_snapshot",
    "aggregate_multi_worker_metrics",
    # Streaming
    "stream_run_metrics",
]
