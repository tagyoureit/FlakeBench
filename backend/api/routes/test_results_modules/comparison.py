"""
Core comparison service for test baseline comparison.

Orchestrates:
- Fetching baseline candidates from database
- Calculating rolling statistics
- Building the compare context for AI analysis
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.config import settings

from .statistics import (
    percentile,
    weighted_median,
    calculate_simple_trend,
)
from .comparison_scoring import (
    calculate_similarity_score,
    classify_change,
    get_confidence_level,
    check_hard_gates,
)
from .fingerprint import compute_sql_fingerprint

logger = logging.getLogger(__name__)


def get_prefix() -> str:
    """Get the database.schema prefix for results tables."""
    return f"{settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}"


# =============================================================================
# DATA EXTRACTION HELPERS
# =============================================================================

# Per-kind latency columns fetched alongside aggregate metrics.
# Order matters — positional mapping starts at index 18 (after TEST_NAME).
_PER_KIND_COLUMNS = [
    "POINT_LOOKUP_P50_LATENCY_MS",
    "POINT_LOOKUP_P95_LATENCY_MS",
    "POINT_LOOKUP_P99_LATENCY_MS",
    "RANGE_SCAN_P50_LATENCY_MS",
    "RANGE_SCAN_P95_LATENCY_MS",
    "RANGE_SCAN_P99_LATENCY_MS",
    "INSERT_P50_LATENCY_MS",
    "INSERT_P95_LATENCY_MS",
    "INSERT_P99_LATENCY_MS",
    "UPDATE_P50_LATENCY_MS",
    "UPDATE_P95_LATENCY_MS",
    "UPDATE_P99_LATENCY_MS",
    "GENERIC_SQL_P50_LATENCY_MS",
    "GENERIC_SQL_P95_LATENCY_MS",
    "GENERIC_SQL_P99_LATENCY_MS",
]

_PER_KIND_SELECT = ",\n        ".join(_PER_KIND_COLUMNS)


def _row_to_dict(row: tuple) -> dict[str, Any]:
    """Convert a positional result row to a named dict.

    Assumes the standard SELECT order used by fetch_current_test,
    fetch_baseline_candidates, and fetch_comparable_candidates.
    """
    d = {
        "test_id": row[0],
        "run_id": row[1],
        "test_config": row[2] if isinstance(row[2], dict) else {},
        "table_type": row[3],
        "warehouse_size": row[4],
        "status": row[5],
        "duration_seconds": row[6],
        "concurrent_connections": row[7],
        "qps": row[8],
        "p50_latency_ms": row[9],
        "p95_latency_ms": row[10],
        "p99_latency_ms": row[11],
        "error_rate": row[12],
        "read_operations": row[13],
        "total_operations": row[14],
        "start_time": row[15],
        "find_max_result": row[16] if len(row) > 16 else None,
        "test_name": row[17] if len(row) > 17 else None,
    }
    # Map per-kind columns starting at index 18
    for i, col in enumerate(_PER_KIND_COLUMNS):
        idx = 18 + i
        d[col.lower()] = row[idx] if len(row) > idx else None
    return d


def _enrich_row_dict(row_dict: dict[str, Any]) -> dict[str, Any]:
    """Apply common post-processing to a row dict (name override, FIND_MAX parsing)."""
    if row_dict["test_name"]:
        row_dict["test_config"]["template_name"] = row_dict["test_name"]

    find_max_result = row_dict.get("find_max_result")
    if find_max_result and isinstance(find_max_result, dict):
        step_history = find_max_result.get("step_history", [])
        fm_derived = derive_find_max_best_stable(step_history)
        row_dict.update(fm_derived)

    return row_dict

def extract_test_features(row: dict[str, Any]) -> dict[str, Any]:
    """
    Extract comparison-relevant features from a test result row.

    Normalizes field names and extracts nested config values.

    Args:
        row: Raw test result row (dict with database column names).

    Returns:
        Dictionary with normalized feature names for scoring.
    """
    test_config = row.get("test_config") or {}
    template_config = test_config.get("template_config") or {}
    scenario = test_config.get("scenario") or {}
    scaling_config = template_config.get("scaling") or {}

    # Extract load_mode with fallback
    load_mode = (
        template_config.get("load_mode")
        or scenario.get("load_mode")
        or ""
    ).upper()

    # Extract read percentage from workload mix
    read_ops = row.get("read_operations", 0) or 0
    total_ops = row.get("total_operations", 1) or 1
    read_pct = (read_ops / total_ops * 100) if total_ops > 0 else 0

    # Extract SQL fingerprint (if available)
    sql_text = template_config.get("sql_template") or template_config.get("query_template")
    fingerprint = compute_sql_fingerprint(sql_text) if sql_text else None

    # Fallback template name if missing
    template_name = test_config.get("template_name", "")
    if not template_name and test_config.get("template_id"):
        template_name = f"Template {test_config.get('template_id')[:8]}"

    return {
        "test_id": row.get("test_id"),
        "run_id": row.get("run_id"),
        "template_id": test_config.get("template_id"),
        "template_name": template_name,
        "load_mode": load_mode,
        "table_type": (row.get("table_type") or "").upper(),
        "target_type": template_config.get("target_type"),
        "sql_fingerprint": fingerprint,
        "status": (row.get("status") or "").upper(),
        "warehouse_size": (row.get("warehouse_size") or "").upper(),
        "scale_mode": scaling_config.get("mode"),
        "concurrent_connections": row.get("concurrent_connections"),
        "target_qps": scenario.get("target_qps"),
        "duration_seconds": row.get("duration_seconds"),
        "use_cached_result": template_config.get("use_cached_result"),
        "read_pct": read_pct,
        # Performance metrics
        "qps": row.get("qps"),
        "p50_latency_ms": row.get("p50_latency_ms"),
        "p95_latency_ms": row.get("p95_latency_ms"),
        "p99_latency_ms": row.get("p99_latency_ms"),
        "error_rate": row.get("error_rate"),
        # FIND_MAX specific (may be None)
        "best_stable_concurrency": row.get("best_stable_concurrency"),
        "best_stable_qps": row.get("best_stable_qps"),
        "degradation_concurrency": row.get("degradation_concurrency"),
        "degradation_reason": row.get("degradation_reason"),
        "total_steps": row.get("total_steps"),
        # Quality metrics
        "steady_state_quality": row.get("steady_state_quality"),
        # Per-kind latency metrics
        "point_lookup_p50_latency_ms": row.get("point_lookup_p50_latency_ms"),
        "point_lookup_p95_latency_ms": row.get("point_lookup_p95_latency_ms"),
        "point_lookup_p99_latency_ms": row.get("point_lookup_p99_latency_ms"),
        "range_scan_p50_latency_ms": row.get("range_scan_p50_latency_ms"),
        "range_scan_p95_latency_ms": row.get("range_scan_p95_latency_ms"),
        "range_scan_p99_latency_ms": row.get("range_scan_p99_latency_ms"),
        "insert_p50_latency_ms": row.get("insert_p50_latency_ms"),
        "insert_p95_latency_ms": row.get("insert_p95_latency_ms"),
        "insert_p99_latency_ms": row.get("insert_p99_latency_ms"),
        "update_p50_latency_ms": row.get("update_p50_latency_ms"),
        "update_p95_latency_ms": row.get("update_p95_latency_ms"),
        "update_p99_latency_ms": row.get("update_p99_latency_ms"),
        "generic_sql_p50_latency_ms": row.get("generic_sql_p50_latency_ms"),
        "generic_sql_p95_latency_ms": row.get("generic_sql_p95_latency_ms"),
        "generic_sql_p99_latency_ms": row.get("generic_sql_p99_latency_ms"),
        # Timestamps
        "start_time": row.get("start_time"),
        "test_date": row.get("start_time"),
    }


def derive_find_max_best_stable(steps: list[dict]) -> dict[str, Any]:
    """
    Derive best stable concurrency from FIND_MAX step history.

    Args:
        steps: List of step dictionaries with keys:
            - step: int
            - concurrency: int
            - qps: float
            - outcome: str (STABLE/DEGRADED)
            - stop_reason: str

    Returns:
        Dictionary with:
            - best_stable_concurrency: int or None
            - best_stable_qps: float or None
            - degradation_concurrency: int or None
            - degradation_reason: str or None
            - total_steps: int
    """
    if not steps:
        return {
            "best_stable_concurrency": None,
            "best_stable_qps": None,
            "degradation_concurrency": None,
            "degradation_reason": None,
            "total_steps": 0,
        }

    stable_steps = [s for s in steps if s.get("outcome") == "STABLE"]
    degraded_steps = [s for s in steps if s.get("outcome") == "DEGRADED"]

    if not stable_steps:
        # Never achieved stability
        first_deg = degraded_steps[0] if degraded_steps else steps[0]
        return {
            "best_stable_concurrency": None,
            "best_stable_qps": None,
            "degradation_concurrency": first_deg.get("concurrency"),
            "degradation_reason": "Never achieved stability",
            "total_steps": len(steps),
        }

    # Best stable = highest concurrency that was stable
    best = max(stable_steps, key=lambda s: s.get("concurrency", 0))

    # Degradation = first degradation after best stable
    best_step_num = best.get("step", 0)
    later_degraded = [
        s for s in degraded_steps
        if s.get("step", 0) > best_step_num
    ]
    degradation = later_degraded[0] if later_degraded else None

    return {
        "best_stable_concurrency": best.get("concurrency"),
        "best_stable_qps": best.get("qps"),
        "degradation_concurrency": degradation.get("concurrency") if degradation else None,
        "degradation_reason": degradation.get("stop_reason") if degradation else None,
        "total_steps": len(steps),
    }


# =============================================================================
# DATABASE QUERY FUNCTIONS
# =============================================================================

async def fetch_baseline_candidates(
    pool: Any,
    test_id: str,
    limit: int = 10,
    days_back: int = 30,
) -> list[dict[str, Any]]:
    """
    Fetch baseline candidate tests for comparison.

    Queries tests with:
    - Same template_id
    - Same load_mode
    - Same table_type
    - Status = COMPLETED
    - Parent rollup only (not child workers)
    - Within the last N days

    Args:
        pool: Database connection pool.
        test_id: Current test ID to find baselines for.
        limit: Maximum number of candidates to return.
        days_back: How many days back to look for baselines.

    Returns:
        List of test result dictionaries with extracted features.
    """
    prefix = get_prefix()

    query = f"""
    WITH current_test AS (
        SELECT
            TEST_ID,
            TEST_CONFIG:template_id::STRING AS template_id,
            COALESCE(
                TEST_CONFIG:template_config:load_mode::STRING,
                TEST_CONFIG:scenario:load_mode::STRING
            ) AS load_mode,
            TABLE_TYPE
        FROM {prefix}.TEST_RESULTS
        WHERE TEST_ID = ?
    )
    SELECT
        t.TEST_ID,
        t.RUN_ID,
        t.TEST_CONFIG,
        t.TABLE_TYPE,
        t.WAREHOUSE_SIZE,
        t.STATUS,
        t.DURATION_SECONDS,
        t.CONCURRENT_CONNECTIONS,
        t.QPS,
        t.P50_LATENCY_MS,
        t.P95_LATENCY_MS,
        t.P99_LATENCY_MS,
        t.ERROR_RATE,
        t.READ_OPERATIONS,
        t.TOTAL_OPERATIONS,
        t.START_TIME,
        t.FIND_MAX_RESULT,
        t.TEST_NAME,
        t.POINT_LOOKUP_P50_LATENCY_MS,
        t.POINT_LOOKUP_P95_LATENCY_MS,
        t.POINT_LOOKUP_P99_LATENCY_MS,
        t.RANGE_SCAN_P50_LATENCY_MS,
        t.RANGE_SCAN_P95_LATENCY_MS,
        t.RANGE_SCAN_P99_LATENCY_MS,
        t.INSERT_P50_LATENCY_MS,
        t.INSERT_P95_LATENCY_MS,
        t.INSERT_P99_LATENCY_MS,
        t.UPDATE_P50_LATENCY_MS,
        t.UPDATE_P95_LATENCY_MS,
        t.UPDATE_P99_LATENCY_MS,
        t.GENERIC_SQL_P50_LATENCY_MS,
        t.GENERIC_SQL_P95_LATENCY_MS,
        t.GENERIC_SQL_P99_LATENCY_MS,
        ROW_NUMBER() OVER (ORDER BY t.START_TIME DESC) AS recency_rank
    FROM {prefix}.TEST_RESULTS t
    JOIN current_test c ON
        t.TEST_CONFIG:template_id::STRING = c.template_id
        AND COALESCE(
            t.TEST_CONFIG:template_config:load_mode::STRING,
            t.TEST_CONFIG:scenario:load_mode::STRING
        ) = c.load_mode
        AND t.TABLE_TYPE = c.TABLE_TYPE
    WHERE t.TEST_ID != c.TEST_ID
      AND t.STATUS = 'COMPLETED'
      AND (t.RUN_ID IS NULL OR t.TEST_ID = t.RUN_ID)
      AND t.START_TIME >= DATEADD(day, -{days_back}, CURRENT_TIMESTAMP())
    ORDER BY t.START_TIME DESC
    LIMIT ?
    """

    rows = await pool.execute_query(query, params=[test_id, limit])

    if not rows:
        return []

    results = []
    for row in rows:
        row_dict = _row_to_dict(row)
        # recency_rank is the last column (after per-kind columns)
        row_dict["recency_rank"] = row[-1] if len(row) > len(_PER_KIND_COLUMNS) + 18 else None
        row_dict = _enrich_row_dict(row_dict)
        results.append(extract_test_features(row_dict))

    return results


async def fetch_comparable_candidates(
    pool: Any,
    current_test: dict[str, Any],
    limit: int = 10,
    days_back: int = 90,
) -> list[dict[str, Any]]:
    """
    Fetch comparable candidates across different templates.

    Searches for tests that:
    - Have the same Table Type
    - Have the same SQL Template or Query Tag
    - Are NOT the same template ID (cross-template search)
    - Are COMPLETED
    - Within the last N days

    Args:
        pool: Database connection pool.
        current_test: Current test dictionary (with extracted features).
        limit: Max candidates to return.
        days_back: Lookback window.

    Returns:
        List of comparable candidate dictionaries.
    """
    prefix = get_prefix()
    test_id = current_test["test_id"]
    table_type = current_test["table_type"]
    template_id = current_test.get("template_id")
    
    # Extract SQL template from the raw config (we need to re-fetch or pass it down)
    # For now, we'll assume exact match on SQL string if available
    # But current_test here is the extracted features dict, which might not have the raw SQL
    # We added sql_fingerprint but that's a hash. We need the raw SQL string for the query.
    
    # To fix this properly, let's fetch the SQL template from the DB for the current test if needed,
    # or better, just pass the query parameters we want to match on.
    
    # Since we can't easily get the raw SQL string here without re-fetching, 
    # let's assume we can match on query_tag or just fetch candidates by table_type 
    # and filter in Python using the fingerprint.
    
    # Broad search by table_type + status, then filter/rank in Python
    query = f"""
    SELECT
        TEST_ID,
        RUN_ID,
        TEST_CONFIG,
        TABLE_TYPE,
        WAREHOUSE_SIZE,
        STATUS,
        DURATION_SECONDS,
        CONCURRENT_CONNECTIONS,
        QPS,
        P50_LATENCY_MS,
        P95_LATENCY_MS,
        P99_LATENCY_MS,
        ERROR_RATE,
        READ_OPERATIONS,
        TOTAL_OPERATIONS,
        START_TIME,
        FIND_MAX_RESULT,
        TEST_NAME,
        {_PER_KIND_SELECT}
    FROM {prefix}.TEST_RESULTS
    WHERE TABLE_TYPE = ?
      AND TEST_ID != ?
      AND STATUS = 'COMPLETED'
      AND (RUN_ID IS NULL OR TEST_ID = RUN_ID)
      AND START_TIME >= DATEADD(day, -{days_back}, CURRENT_TIMESTAMP())
      -- Exclude same template to find "other" tests
      AND (TEST_CONFIG:template_id::STRING IS NULL OR TEST_CONFIG:template_id::STRING != ?)
    ORDER BY START_TIME DESC
    LIMIT 100
    """
    
    rows = await pool.execute_query(query, params=[table_type, test_id, template_id])
    
    if not rows:
        return []

    candidates = []
    current_fingerprint = current_test.get("sql_fingerprint")
    
    for row in rows:
        row_dict = _row_to_dict(row)
        
        # Override test_config name if column name exists
        if row_dict["test_name"]:
            row_dict["test_config"]["template_name"] = row_dict["test_name"]
        
        # Extract features (includes fingerprint calculation)
        candidate = extract_test_features(row_dict)
        
        # Filter: Must match SQL fingerprint if available
        if current_fingerprint and candidate.get("sql_fingerprint") != current_fingerprint:
            continue
            
        # Parse FIND_MAX if needed
        find_max_result = row_dict.get("find_max_result")
        if find_max_result and isinstance(find_max_result, dict):
            step_history = find_max_result.get("step_history", [])
            fm_derived = derive_find_max_best_stable(step_history)
            candidate.update(fm_derived)
            
        candidates.append(candidate)
        
    # Return top N (ranked by recency for now, scoring handles the rest)
    return candidates[:limit]


async def fetch_current_test(pool: Any, test_id: str) -> dict[str, Any] | None:
    """
    Fetch the current test for comparison context.

    Args:
        pool: Database connection pool.
        test_id: Test ID to fetch.

    Returns:
        Dictionary with extracted test features, or None if not found.
    """
    prefix = get_prefix()

    query = f"""
    SELECT
        TEST_ID,
        RUN_ID,
        TEST_CONFIG,
        TABLE_TYPE,
        WAREHOUSE_SIZE,
        STATUS,
        DURATION_SECONDS,
        CONCURRENT_CONNECTIONS,
        QPS,
        P50_LATENCY_MS,
        P95_LATENCY_MS,
        P99_LATENCY_MS,
        ERROR_RATE,
        READ_OPERATIONS,
        TOTAL_OPERATIONS,
        START_TIME,
        FIND_MAX_RESULT,
        TEST_NAME,
        {_PER_KIND_SELECT}
    FROM {prefix}.TEST_RESULTS
    WHERE TEST_ID = ?
    """

    rows = await pool.execute_query(query, params=[test_id])

    if not rows:
        return None

    row_dict = _enrich_row_dict(_row_to_dict(rows[0]))

    return extract_test_features(row_dict)


async def fetch_step_history(pool: Any, test_id: str) -> list[dict]:
    """
    Fetch CONTROLLER_STEP_HISTORY for FIND_MAX tests.

    Args:
        pool: Database connection pool.
        test_id: Test ID to fetch step history for.

    Returns:
        List of step dictionaries.
    """
    prefix = get_prefix()

    query = f"""
    SELECT
        STEP,
        CONCURRENCY,
        QPS,
        P95_LATENCY_MS,
        P99_LATENCY_MS,
        OUTCOME,
        STOP_REASON
    FROM {prefix}.CONTROLLER_STEP_HISTORY
    WHERE TEST_ID = ?
    ORDER BY STEP ASC
    """

    rows = await pool.execute_query(query, params=[test_id])

    if not rows:
        return []

    return [
        {
            "step": row[0],
            "concurrency": row[1],
            "qps": row[2],
            "p95_latency_ms": row[3],
            "p99_latency_ms": row[4],
            "outcome": row[5],
            "stop_reason": row[6],
        }
        for row in rows
    ]


# =============================================================================
# STATISTICS CALCULATION
# =============================================================================

def calculate_rolling_statistics(
    baselines: list[dict[str, Any]],
    use_count: int = 5,
) -> dict[str, Any]:
    """
    Calculate rolling statistics from baseline candidates.

    Uses the most recent N baselines to compute:
    - Median QPS, P95, P99
    - P10-P90 confidence bands
    - Recency-weighted statistics

    Args:
        baselines: List of baseline test features (sorted by recency).
        use_count: Number of most recent baselines to use.

    Returns:
        Dictionary with rolling statistics.
    """
    if not baselines:
        return {
            "available": False,
            "candidate_count": 0,
            "used_count": 0,
            "rolling_median": {},
            "confidence_band": {},
        }

    # Use most recent N baselines
    used = baselines[:use_count]
    n = len(used)

    # Extract metric arrays
    qps_values = sorted([b["qps"] for b in used if b.get("qps") is not None])
    p50_values = sorted([b["p50_latency_ms"] for b in used if b.get("p50_latency_ms") is not None])
    p95_values = sorted([b["p95_latency_ms"] for b in used if b.get("p95_latency_ms") is not None])
    p99_values = sorted([b["p99_latency_ms"] for b in used if b.get("p99_latency_ms") is not None])
    error_values = sorted([b["error_rate"] for b in used if b.get("error_rate") is not None])

    # Calculate medians
    rolling_median = {
        "qps": percentile(qps_values, 50),
        "p50_latency_ms": percentile(p50_values, 50),
        "p95_latency_ms": percentile(p95_values, 50),
        "p99_latency_ms": percentile(p99_values, 50),
        "error_rate_pct": percentile(error_values, 50),
    }

    # Per-kind P95 medians (only include kinds with data)
    _per_kind_p95_keys = [
        "point_lookup_p95_latency_ms",
        "range_scan_p95_latency_ms",
        "insert_p95_latency_ms",
        "update_p95_latency_ms",
        "generic_sql_p95_latency_ms",
    ]
    for key in _per_kind_p95_keys:
        vals = sorted([b[key] for b in used if b.get(key) is not None])
        if vals:
            rolling_median[key] = percentile(vals, 50)

    # Calculate confidence bands (P10-P90)
    confidence_band = {
        "qps_p10": percentile(qps_values, 10),
        "qps_p90": percentile(qps_values, 90),
        "p95_p10": percentile(p95_values, 10),
        "p95_p90": percentile(p95_values, 90),
    }

    # Calculate recency-weighted median
    weights = [0.8 ** i for i in range(n)]
    weighted_qps = weighted_median(
        [b["qps"] for b in used if b.get("qps") is not None],
        weights[:len([b for b in used if b.get("qps") is not None])],
    )

    # Get date range
    dates = [b["start_time"] for b in used if b.get("start_time")]
    oldest_date = min(dates) if dates else None
    newest_date = max(dates) if dates else None

    return {
        "available": True,
        "candidate_count": len(baselines),
        "used_count": n,
        "rolling_median": rolling_median,
        "confidence_band": confidence_band,
        "weighted_qps_median": weighted_qps,
        "oldest_date": oldest_date.isoformat() if oldest_date else None,
        "newest_date": newest_date.isoformat() if newest_date else None,
    }


def calculate_deltas(
    current: dict[str, Any],
    baseline: dict[str, Any],
) -> dict[str, Any]:
    """
    Calculate percentage deltas between current and baseline.

    Args:
        current: Current test features.
        baseline: Baseline test features (or rolling median).

    Returns:
        Dictionary with delta percentages for each metric.
    """
    def safe_delta_pct(curr_val: float | None, base_val: float | None) -> float | None:
        if curr_val is None or base_val is None or base_val == 0:
            return None
        return ((curr_val - base_val) / abs(base_val)) * 100

    return {
        "qps_delta_pct": safe_delta_pct(current.get("qps"), baseline.get("qps")),
        "p50_delta_pct": safe_delta_pct(
            current.get("p50_latency_ms"), baseline.get("p50_latency_ms")
        ),
        "p95_delta_pct": safe_delta_pct(
            current.get("p95_latency_ms"), baseline.get("p95_latency_ms")
        ),
        "p99_delta_pct": safe_delta_pct(
            current.get("p99_latency_ms"), baseline.get("p99_latency_ms")
        ),
        "error_rate_delta_pct": safe_delta_pct(
            current.get("error_rate"), baseline.get("error_rate")
        ),
        # Per-kind P95 deltas
        "point_lookup_p95_delta_pct": safe_delta_pct(
            current.get("point_lookup_p95_latency_ms"),
            baseline.get("point_lookup_p95_latency_ms"),
        ),
        "range_scan_p95_delta_pct": safe_delta_pct(
            current.get("range_scan_p95_latency_ms"),
            baseline.get("range_scan_p95_latency_ms"),
        ),
        "insert_p95_delta_pct": safe_delta_pct(
            current.get("insert_p95_latency_ms"),
            baseline.get("insert_p95_latency_ms"),
        ),
        "update_p95_delta_pct": safe_delta_pct(
            current.get("update_p95_latency_ms"),
            baseline.get("update_p95_latency_ms"),
        ),
        "generic_sql_p95_delta_pct": safe_delta_pct(
            current.get("generic_sql_p95_latency_ms"),
            baseline.get("generic_sql_p95_latency_ms"),
        ),
    }


def determine_verdict(deltas: dict[str, Any]) -> dict[str, Any]:
    """
    Determine overall verdict based on metric deltas.

    Uses classification thresholds to determine:
    - IMPROVED: Multiple metrics improved, none regressed
    - REGRESSED: Any metric regressed
    - STABLE: All metrics within neutral range
    - INCONCLUSIVE: Mixed signals

    Args:
        deltas: Dictionary of delta percentages.

    Returns:
        Dictionary with verdict and reasons.
    """
    classifications = {}
    reasons = []

    # Classify each metric
    qps_delta = deltas.get("qps_delta_pct")
    if qps_delta is not None:
        classifications["qps"] = classify_change("qps", qps_delta)
        if classifications["qps"] != "NEUTRAL":
            reasons.append(f"QPS {qps_delta:+.1f}% ({classifications['qps']})")

    p95_delta = deltas.get("p95_delta_pct")
    if p95_delta is not None:
        classifications["p95"] = classify_change("p95_latency", p95_delta)
        if classifications["p95"] != "NEUTRAL":
            reasons.append(f"P95 latency {p95_delta:+.1f}% ({classifications['p95']})")

    p99_delta = deltas.get("p99_delta_pct")
    if p99_delta is not None:
        classifications["p99"] = classify_change("p99_latency", p99_delta)
        if classifications["p99"] != "NEUTRAL":
            reasons.append(f"P99 latency {p99_delta:+.1f}% ({classifications['p99']})")

    # Per-kind P95 deltas (only classify if data exists)
    _per_kind_labels = {
        "point_lookup_p95_delta_pct": "Point Lookup P95",
        "range_scan_p95_delta_pct": "Range Scan P95",
        "insert_p95_delta_pct": "Insert P95",
        "update_p95_delta_pct": "Update P95",
        "generic_sql_p95_delta_pct": "Generic SQL P95",
    }
    for key, label in _per_kind_labels.items():
        delta = deltas.get(key)
        if delta is not None:
            cls = classify_change("p95_latency", delta)
            classifications[key] = cls
            if cls != "NEUTRAL":
                reasons.append(f"{label} {delta:+.1f}% ({cls})")

    # Determine overall verdict
    values = list(classifications.values())

    if not values:
        return {"verdict": "INCONCLUSIVE", "verdict_reasons": ["Insufficient data"]}

    if "REGRESSION" in values:
        return {"verdict": "REGRESSED", "verdict_reasons": reasons}

    if "WARNING" in values and "IMPROVEMENT" not in values:
        return {"verdict": "WARNING", "verdict_reasons": reasons}

    if all(v == "IMPROVEMENT" for v in values):
        return {"verdict": "IMPROVED", "verdict_reasons": reasons}

    if all(v == "NEUTRAL" for v in values):
        return {"verdict": "STABLE", "verdict_reasons": ["All metrics within normal range"]}

    if "IMPROVEMENT" in values and all(v in ("IMPROVEMENT", "NEUTRAL") for v in values):
        return {"verdict": "IMPROVED", "verdict_reasons": reasons}

    return {"verdict": "INCONCLUSIVE", "verdict_reasons": reasons}


# =============================================================================
# MAIN ORCHESTRATION
# =============================================================================

async def build_compare_context(
    pool: Any,
    test_id: str,
    baseline_count: int = 5,
    comparable_limit: int = 5,
    min_similarity: float = 0.55,
    include_excluded: bool = False,
) -> dict[str, Any]:
    """
    Build complete comparison context for AI analysis.

    Orchestrates:
    1. Fetching current test
    2. Fetching baseline candidates
    3. Calculating rolling statistics
    4. Calculating similarity scores
    5. Determining verdict

    Args:
        pool: Database connection pool.
        test_id: Current test ID.
        baseline_count: Number of baseline runs to use for statistics.
        comparable_limit: Max comparable candidates to return.
        min_similarity: Minimum similarity score to include.
        include_excluded: Whether to include excluded candidates.

    Returns:
        Complete compare context dictionary matching API spec (Section 11.1).
    """
    start_time = datetime.now(timezone.utc)

    # Fetch current test
    current = await fetch_current_test(pool, test_id)
    if not current:
        return {
            "test_id": test_id,
            "error": "Test not found",
            "baseline": {"available": False},
        }

    load_mode = current.get("load_mode", "")

    # Fetch baseline candidates (same template)
    candidates = await fetch_baseline_candidates(
        pool, test_id, limit=baseline_count + 5  # Fetch extra for exclusions
    )

    # Fetch comparable candidates (different template, similar SQL)
    cross_template_candidates = await fetch_comparable_candidates(
        pool, current, limit=comparable_limit
    )

    # Calculate rolling statistics (only from strict baselines)
    baseline_stats = calculate_rolling_statistics(candidates, use_count=baseline_count)

    # Build vs_previous comparison (most recent baseline)
    vs_previous = None
    if candidates:
        previous = candidates[0]
        prev_score = calculate_similarity_score(current, previous, load_mode)
        prev_deltas = calculate_deltas(current, previous)

        vs_previous = {
            "test_id": previous.get("test_id"),
            "test_date": (
                previous["start_time"].isoformat()
                if previous.get("start_time")
                else None
            ),
            "similarity_score": prev_score["total_score"],
            "confidence": prev_score["confidence"],
            "deltas": prev_deltas,
            "differences": [],  # TODO: Populate notable differences
        }

    # Build vs_median comparison
    vs_median = None
    if baseline_stats["available"]:
        rm = baseline_stats["rolling_median"]
        median_baseline = {
            "qps": rm.get("qps"),
            "p50_latency_ms": rm.get("p50_latency_ms"),
            "p95_latency_ms": rm.get("p95_latency_ms"),
            "p99_latency_ms": rm.get("p99_latency_ms"),
            "error_rate": rm.get("error_rate_pct"),
            # Per-kind medians (only present if baselines had data)
            "point_lookup_p95_latency_ms": rm.get("point_lookup_p95_latency_ms"),
            "range_scan_p95_latency_ms": rm.get("range_scan_p95_latency_ms"),
            "insert_p95_latency_ms": rm.get("insert_p95_latency_ms"),
            "update_p95_latency_ms": rm.get("update_p95_latency_ms"),
            "generic_sql_p95_latency_ms": rm.get("generic_sql_p95_latency_ms"),
        }
        median_deltas = calculate_deltas(current, median_baseline)
        verdict_result = determine_verdict(median_deltas)

        vs_median = {
            "qps_delta_pct": median_deltas.get("qps_delta_pct"),
            "p95_delta_pct": median_deltas.get("p95_delta_pct"),
            "generic_sql_p95_delta_pct": median_deltas.get("generic_sql_p95_delta_pct"),
            **verdict_result,
        }

    # Calculate trend
    if len(candidates) >= 3:
        qps_values = [c["qps"] for c in reversed(candidates) if c.get("qps")]
        trend = calculate_simple_trend(qps_values)
    else:
        trend = {
            "direction": "INSUFFICIENT_DATA",
            "slope": None,
            "r_squared": None,
            "sample_size": len(candidates),
        }

    # Score and rank comparable runs (strict baselines)
    comparable_runs = []
    exclusions = []

    def process_candidates(candidate_list, strict_mode=True):
        processed = []
        for candidate in candidate_list:
            # Use current load mode for scoring context
            score_result = calculate_similarity_score(current, candidate, load_mode)

            if score_result["excluded"]:
                if include_excluded:
                    exclusions.append({
                        "test_id": candidate.get("test_id"),
                        "score": score_result["total_score"],
                        "reasons": score_result.get("exclusion_reasons", []),
                        "source": "strict" if strict_mode else "cross_template"
                    })
                continue

            # Lower threshold for cross-template discovery? Or keep same?
            # Keeping same ensures quality.
            if score_result["total_score"] < min_similarity:
                if include_excluded:
                    exclusions.append({
                        "test_id": candidate.get("test_id"),
                        "score": score_result["total_score"],
                        "reasons": [f"Score below threshold: {score_result['total_score']:.2f} < {min_similarity}"],
                        "source": "strict" if strict_mode else "cross_template"
                    })
                continue

            processed.append({
                "test_id": candidate.get("test_id"),
                "test_date": (
                    candidate["start_time"].isoformat()
                    if candidate.get("start_time")
                    else None
                ),
                "test_name": candidate.get("template_name") or candidate.get("test_id") or "Unknown Test",
                "match_type": "BASELINE" if strict_mode else "SIMILAR",
                "similarity_score": score_result["total_score"],
                "confidence": score_result["confidence"],
                "score_breakdown": score_result["breakdown"],
                "match_reasons": (
                    ["Same template", "Same load mode", "Same table type"]
                    if strict_mode
                    else ["Same SQL fingerprint", "Different template", "Same table type"]
                ),
                "differences": [],
                "config": {
                    "table_type": candidate.get("table_type"),
                    "load_mode": candidate.get("load_mode"),
                    "warehouse_size": candidate.get("warehouse_size"),
                    "scale_mode": candidate.get("scale_mode"),
                    "duration_seconds": candidate.get("duration_seconds"),
                },
                "metrics": {
                    "qps": candidate.get("qps"),
                    "p95_latency_ms": candidate.get("p95_latency_ms"),
                    "error_rate_pct": candidate.get("error_rate"),
                    "point_lookup_p95_latency_ms": candidate.get("point_lookup_p95_latency_ms"),
                    "range_scan_p95_latency_ms": candidate.get("range_scan_p95_latency_ms"),
                    "insert_p95_latency_ms": candidate.get("insert_p95_latency_ms"),
                    "update_p95_latency_ms": candidate.get("update_p95_latency_ms"),
                    "generic_sql_p95_latency_ms": candidate.get("generic_sql_p95_latency_ms"),
                },
                "is_same_template": strict_mode
            })
        
        # Sort by similarity score
        processed.sort(key=lambda x: x["similarity_score"], reverse=True)
        return processed

    comparable_runs = process_candidates(candidates, strict_mode=True)[:comparable_limit]
    
    # Process cross-template candidates separately (and sort them!)
    similar_runs = process_candidates(cross_template_candidates, strict_mode=False)
    # Re-sort to be safe, though process_candidates does it
    similar_runs.sort(key=lambda x: x["similarity_score"], reverse=True)
    similar_runs = similar_runs[:comparable_limit]

    end_time = datetime.now(timezone.utc)
    computation_time_ms = int((end_time - start_time).total_seconds() * 1000)

    return {
        "test_id": test_id,
        "template_id": current.get("template_id"),
        "load_mode": load_mode,
        "baseline": baseline_stats,
        "vs_previous": vs_previous,
        "vs_median": vs_median,
        "trend": trend,
        "comparable_candidates": comparable_runs,  # Strict baselines (same template) - RENAMED to match JS
        "similar_candidates": similar_runs,        # Cross-template candidates
        "exclusions": exclusions if include_excluded else [],
        "metadata": {
            "computed_at": end_time.isoformat(),
            "computation_time_ms": computation_time_ms,
            "data_freshness": end_time.isoformat(),
        },
    }
