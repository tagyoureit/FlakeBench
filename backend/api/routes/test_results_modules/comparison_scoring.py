"""
Similarity scoring for test comparison.

Implements the scoring contract from the AI comparison plan:
- Hard gates (must pass ALL)
- Soft scoring by load mode (CONCURRENCY, QPS, FIND_MAX_CONCURRENCY)
- Confidence bands
- Exclusion reason codes
- Regression classification thresholds
"""

from __future__ import annotations

from typing import Any, Literal


# =============================================================================
# CONSTANTS - Regression Thresholds (Section 9.7)
# =============================================================================

REGRESSION_THRESHOLDS: dict[str, dict[str, float]] = {
    # QPS thresholds (all modes) - higher is better
    "qps": {
        "improvement": 10.0,    # > +10% = IMPROVEMENT
        "warning": -10.0,       # -10% to -20% = WARNING
        "regression": -20.0,    # < -20% = REGRESSION
    },
    # P50 latency - lower is better (inverted signs)
    "p50_latency": {
        "improvement": -15.0,   # < -15% = IMPROVEMENT
        "warning": 15.0,        # +15% to +30% = WARNING
        "regression": 30.0,     # > +30% = REGRESSION
    },
    # P95 latency - lower is better (inverted signs)
    "p95_latency": {
        "improvement": -20.0,   # < -20% = IMPROVEMENT
        "warning": 20.0,        # +20% to +40% = WARNING
        "regression": 40.0,     # > +40% = REGRESSION
    },
    # P99 latency - lower is better (inverted signs)
    "p99_latency": {
        "improvement": -25.0,   # < -25% = IMPROVEMENT
        "warning": 25.0,        # +25% to +50% = WARNING
        "regression": 50.0,     # > +50% = REGRESSION
    },
    # Error rate - thresholds are absolute, not percentage change
    "error_rate": {
        "improvement": 0.1,     # < 0.1% = IMPROVEMENT
        "warning": 1.0,         # 1-5% = WARNING
        "regression": 5.0,      # > 5% = REGRESSION
    },
    # FIND_MAX best concurrency - higher is better
    "find_max_best_concurrency": {
        "improvement": 15.0,    # > +15% = IMPROVEMENT
        "warning": -15.0,       # -15% to -25% = WARNING
        "regression": -25.0,    # < -25% = REGRESSION
    },
    # FIND_MAX best QPS - higher is better
    "find_max_best_qps": {
        "improvement": 10.0,    # > +10% = IMPROVEMENT
        "warning": -10.0,       # -10% to -20% = WARNING
        "regression": -20.0,    # < -20% = REGRESSION
    },
}

# Confidence bands based on similarity score (Section 9.5)
CONFIDENCE_BANDS = {
    "HIGH": {"min": 0.85, "color": "green"},
    "MEDIUM": {"min": 0.70, "color": "yellow"},
    "LOW": {"min": 0.55, "color": "orange"},
    "EXCLUDED": {"min": 0.0, "color": "gray"},
}

# Warehouse size ordering for adjacency scoring
WAREHOUSE_SIZE_ORDER = [
    "XSMALL", "SMALL", "MEDIUM", "LARGE", "XLARGE",
    "2XLARGE", "3XLARGE", "4XLARGE", "5XLARGE", "6XLARGE",
]

# Soft scoring weights by load mode (Sections 9.2-9.4)
SCORING_WEIGHTS = {
    "CONCURRENCY": {
        "scale_mode": 0.20,
        "concurrency": 0.25,
        "duration": 0.15,
        "warehouse": 0.20,
        "workload": 0.15,
        "cache": 0.05,
    },
    "QPS": {
        "target_qps": 0.30,
        "scale_mode": 0.15,
        "duration": 0.15,
        "warehouse": 0.20,
        "workload": 0.15,
        "cache": 0.05,
    },
    "FIND_MAX_CONCURRENCY": {
        "best_stable_concurrency": 0.35,
        "best_stable_qps": 0.25,
        "degradation_point": 0.15,
        "steps_to_degradation": 0.10,
        "qps_efficiency": 0.10,
        "degradation_reason": 0.05,
    },
}


# =============================================================================
# CLASSIFICATION FUNCTIONS
# =============================================================================

ClassificationResult = Literal["IMPROVEMENT", "NEUTRAL", "WARNING", "REGRESSION"]


def classify_change(metric: str, delta_pct: float) -> ClassificationResult:
    """
    Classify a performance change based on thresholds.

    Args:
        metric: The metric name (must be a key in REGRESSION_THRESHOLDS).
        delta_pct: The percentage change (positive = higher value).

    Returns:
        Classification: IMPROVEMENT, NEUTRAL, WARNING, or REGRESSION.

    Example:
        >>> classify_change("qps", 15.0)
        'IMPROVEMENT'
        >>> classify_change("qps", -25.0)
        'REGRESSION'
        >>> classify_change("p95_latency", 50.0)
        'REGRESSION'
    """
    if metric not in REGRESSION_THRESHOLDS:
        return "NEUTRAL"

    thresholds = REGRESSION_THRESHOLDS[metric]

    # For latency metrics, higher is worse (inverted logic)
    is_latency = "latency" in metric

    if is_latency:
        # For latency: negative delta = improvement
        if delta_pct < thresholds["improvement"]:
            return "IMPROVEMENT"
        elif delta_pct > thresholds["regression"]:
            return "REGRESSION"
        elif delta_pct > thresholds["warning"]:
            return "WARNING"
        else:
            return "NEUTRAL"
    else:
        # For throughput metrics: positive delta = improvement
        if delta_pct > thresholds["improvement"]:
            return "IMPROVEMENT"
        elif delta_pct < thresholds["regression"]:
            return "REGRESSION"
        elif delta_pct < thresholds["warning"]:
            return "WARNING"
        else:
            return "NEUTRAL"


def get_confidence_level(similarity_score: float) -> str:
    """
    Get confidence level based on similarity score.

    Args:
        similarity_score: Score from 0.0 to 1.0.

    Returns:
        Confidence level: HIGH, MEDIUM, LOW, or EXCLUDED.
    """
    if similarity_score >= CONFIDENCE_BANDS["HIGH"]["min"]:
        return "HIGH"
    elif similarity_score >= CONFIDENCE_BANDS["MEDIUM"]["min"]:
        return "MEDIUM"
    elif similarity_score >= CONFIDENCE_BANDS["LOW"]["min"]:
        return "LOW"
    else:
        return "EXCLUDED"


# =============================================================================
# HARD GATE FUNCTIONS (Section 9.1)
# =============================================================================

def check_hard_gates(
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> tuple[bool, list[str]]:
    """
    Check if a candidate passes all hard gates for comparison.

    Hard gates (must pass ALL):
    - Same template_id (Phase 1)
    - Same load_mode
    - Same table_type
    - Same target_type
    - Candidate status = COMPLETED
    - Parent rollup only (not child worker rows)
    - Quality gate (non-FIND_MAX: steady_state_quality >= 0.5)
    - FIND_MAX gate: best_stable_concurrency present

    Args:
        current: Current test data.
        candidate: Candidate baseline test data.

    Returns:
        Tuple of (passes_all_gates, list_of_failure_reasons).
    """
    failures: list[str] = []

    # Same template_id
    if current.get("template_id") != candidate.get("template_id"):
        failures.append("Different template_id")

    # Same load_mode
    if current.get("load_mode") != candidate.get("load_mode"):
        failures.append(
            f"Different load_mode: {current.get('load_mode')} vs {candidate.get('load_mode')}"
        )

    # Same table_type
    if current.get("table_type") != candidate.get("table_type"):
        failures.append(
            f"Different table_type: {current.get('table_type')} vs {candidate.get('table_type')}"
        )

    # Same target_type (if specified)
    curr_target = current.get("target_type")
    cand_target = candidate.get("target_type")
    if curr_target and cand_target and curr_target != cand_target:
        failures.append(f"Different target_type: {curr_target} vs {cand_target}")

    # Completed status
    if candidate.get("status", "").upper() != "COMPLETED":
        failures.append(f"Candidate status not COMPLETED: {candidate.get('status')}")

    # Parent rollup check
    candidate_test_id = candidate.get("test_id")
    candidate_run_id = candidate.get("run_id")
    if candidate_run_id and candidate_test_id != candidate_run_id:
        failures.append("Candidate is a child worker row, not parent rollup")

    # Quality gate for non-FIND_MAX modes
    load_mode = current.get("load_mode", "").upper()
    if load_mode != "FIND_MAX_CONCURRENCY":
        quality = candidate.get("steady_state_quality", 1.0)
        if quality is not None and quality < 0.5:
            failures.append(f"Candidate quality too low: {quality:.2f} < 0.5")
    else:
        # FIND_MAX: require best_stable_concurrency
        if not candidate.get("best_stable_concurrency"):
            failures.append("FIND_MAX candidate missing best_stable_concurrency")

    return (len(failures) == 0, failures)


# =============================================================================
# SOFT SCORING FUNCTIONS (Sections 9.2-9.4)
# =============================================================================

def _clamp(value: float, min_val: float = 0.0, max_val: float = 1.0) -> float:
    """Clamp value to range [min_val, max_val]."""
    return max(min_val, min(max_val, value))


def _numeric_similarity(a: float | None, b: float | None) -> float:
    """
    Calculate similarity between two numeric values.

    Formula: clamp(1 - abs(a-b) / max(max(a,b), 1), 0, 1)

    Returns 1.0 if values are equal, decreasing as they diverge.
    Returns 0.5 if one value is None.
    """
    if a is None or b is None:
        return 0.5  # Partial match if one is missing

    if a == b:
        return 1.0

    max_val = max(abs(a), abs(b), 1.0)
    diff = abs(a - b)

    return _clamp(1.0 - diff / max_val)


def warehouse_size_match_score(size_a: str | None, size_b: str | None) -> float:
    """
    Calculate warehouse size similarity score.

    Returns:
        1.0 if exact match
        0.5 if adjacent sizes (e.g., SMALL vs MEDIUM)
        0.0 if more than one step apart or either is None/unknown
    """
    if not size_a or not size_b:
        return 0.5  # Partial match if unknown

    size_a = size_a.upper()
    size_b = size_b.upper()

    if size_a == size_b:
        return 1.0

    try:
        idx_a = WAREHOUSE_SIZE_ORDER.index(size_a)
        idx_b = WAREHOUSE_SIZE_ORDER.index(size_b)
        distance = abs(idx_a - idx_b)

        if distance == 1:
            return 0.5
        else:
            return 0.0
    except ValueError:
        # Unknown size
        return 0.0


def _scale_mode_match_score(mode_a: str | None, mode_b: str | None) -> float:
    """
    Calculate scale mode similarity.

    Returns:
        1.0 if exact match
        0.5 if one is NULL
        0.0 otherwise
    """
    if mode_a is None and mode_b is None:
        return 1.0
    if mode_a is None or mode_b is None:
        return 0.5
    return 1.0 if mode_a.upper() == mode_b.upper() else 0.0


def _workload_mix_similarity(read_pct_a: float | None, read_pct_b: float | None) -> float:
    """
    Calculate workload mix similarity based on read percentage.

    Formula: 1 - abs(read_pct_a - read_pct_b) / 100
    """
    if read_pct_a is None or read_pct_b is None:
        return 0.5

    return 1.0 - abs(read_pct_a - read_pct_b) / 100.0


def _cache_mode_match_score(cache_a: bool | None, cache_b: bool | None) -> float:
    """Calculate cache mode match score."""
    if cache_a is None or cache_b is None:
        return 0.5
    return 1.0 if cache_a == cache_b else 0.0


def _degradation_reason_match_score(reason_a: str | None, reason_b: str | None) -> float:
    """
    Match degradation reasons by category.

    Categories:
    - THROUGHPUT: "QPS dropped"
    - LATENCY: "P95 latency increased", "P99 latency"
    - QUEUE: "Queue detected", "queued", "blocked"
    - ERROR: "Error rate exceeded"

    Returns:
        1.0 if same category
        0.5 if related categories
        0.0 otherwise
    """
    if not reason_a or not reason_b:
        return 0.5

    def categorize(reason: str) -> str:
        reason_lower = reason.lower()
        if "qps" in reason_lower and "drop" in reason_lower:
            return "THROUGHPUT"
        if "latency" in reason_lower:
            return "LATENCY"
        if "queue" in reason_lower or "blocked" in reason_lower:
            return "QUEUE"
        if "error" in reason_lower:
            return "ERROR"
        return "OTHER"

    cat_a = categorize(reason_a)
    cat_b = categorize(reason_b)

    if cat_a == cat_b:
        return 1.0

    # Related categories
    related_pairs = {
        ("THROUGHPUT", "QUEUE"),
        ("LATENCY", "QUEUE"),
    }
    if (cat_a, cat_b) in related_pairs or (cat_b, cat_a) in related_pairs:
        return 0.5

    return 0.0


def calculate_similarity_score_concurrency(
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Calculate similarity score for CONCURRENCY mode tests.

    Weights (Section 9.2):
    - Scale Mode Match: 0.20
    - Concurrency Similarity: 0.25
    - Duration Similarity: 0.15
    - Warehouse Size Match: 0.20
    - Workload Mix Similarity: 0.15
    - Cache Mode Match: 0.05

    Returns:
        Dictionary with total_score, breakdown, and confidence level.
    """
    weights = SCORING_WEIGHTS["CONCURRENCY"]

    scale_mode = _scale_mode_match_score(
        current.get("scale_mode"),
        candidate.get("scale_mode"),
    )
    concurrency = _numeric_similarity(
        current.get("concurrent_connections"),
        candidate.get("concurrent_connections"),
    )
    duration = _numeric_similarity(
        current.get("duration_seconds"),
        candidate.get("duration_seconds"),
    )
    warehouse = warehouse_size_match_score(
        current.get("warehouse_size"),
        candidate.get("warehouse_size"),
    )
    workload = _workload_mix_similarity(
        current.get("read_pct"),
        candidate.get("read_pct"),
    )
    cache = _cache_mode_match_score(
        current.get("use_cached_result"),
        candidate.get("use_cached_result"),
    )

    breakdown = {
        "scale_mode": round(scale_mode, 3),
        "concurrency": round(concurrency, 3),
        "duration": round(duration, 3),
        "warehouse": round(warehouse, 3),
        "workload": round(workload, 3),
        "cache": round(cache, 3),
    }

    total = (
        scale_mode * weights["scale_mode"]
        + concurrency * weights["concurrency"]
        + duration * weights["duration"]
        + warehouse * weights["warehouse"]
        + workload * weights["workload"]
        + cache * weights["cache"]
    )

    return {
        "total_score": round(total, 3),
        "breakdown": breakdown,
        "confidence": get_confidence_level(total),
    }


def calculate_similarity_score_qps(
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Calculate similarity score for QPS mode tests.

    Weights (Section 9.3):
    - Target QPS Similarity: 0.30
    - Scale Mode Match: 0.15
    - Duration Similarity: 0.15
    - Warehouse Size Match: 0.20
    - Workload Mix Similarity: 0.15
    - Cache Mode Match: 0.05

    Returns:
        Dictionary with total_score, breakdown, and confidence level.
    """
    weights = SCORING_WEIGHTS["QPS"]

    target_qps = _numeric_similarity(
        current.get("target_qps"),
        candidate.get("target_qps"),
    )
    scale_mode = _scale_mode_match_score(
        current.get("scale_mode"),
        candidate.get("scale_mode"),
    )
    duration = _numeric_similarity(
        current.get("duration_seconds"),
        candidate.get("duration_seconds"),
    )
    warehouse = warehouse_size_match_score(
        current.get("warehouse_size"),
        candidate.get("warehouse_size"),
    )
    workload = _workload_mix_similarity(
        current.get("read_pct"),
        candidate.get("read_pct"),
    )
    cache = _cache_mode_match_score(
        current.get("use_cached_result"),
        candidate.get("use_cached_result"),
    )

    breakdown = {
        "target_qps": round(target_qps, 3),
        "scale_mode": round(scale_mode, 3),
        "duration": round(duration, 3),
        "warehouse": round(warehouse, 3),
        "workload": round(workload, 3),
        "cache": round(cache, 3),
    }

    total = (
        target_qps * weights["target_qps"]
        + scale_mode * weights["scale_mode"]
        + duration * weights["duration"]
        + warehouse * weights["warehouse"]
        + workload * weights["workload"]
        + cache * weights["cache"]
    )

    return {
        "total_score": round(total, 3),
        "breakdown": breakdown,
        "confidence": get_confidence_level(total),
    }


def calculate_similarity_score_find_max(
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    """
    Calculate similarity score for FIND_MAX_CONCURRENCY mode tests.

    Weights (Section 9.4):
    - Best Stable Concurrency Similarity: 0.35
    - Best Stable QPS Similarity: 0.25
    - Degradation Point Similarity: 0.15
    - Steps to Degradation: 0.10
    - QPS Efficiency: 0.10
    - Degradation Reason Match: 0.05

    Returns:
        Dictionary with total_score, breakdown, and confidence level.
    """
    weights = SCORING_WEIGHTS["FIND_MAX_CONCURRENCY"]

    best_cc = _numeric_similarity(
        current.get("best_stable_concurrency"),
        candidate.get("best_stable_concurrency"),
    )
    best_qps = _numeric_similarity(
        current.get("best_stable_qps"),
        candidate.get("best_stable_qps"),
    )
    deg_point = _numeric_similarity(
        current.get("degradation_concurrency"),
        candidate.get("degradation_concurrency"),
    )
    steps = _numeric_similarity(
        current.get("total_steps"),
        candidate.get("total_steps"),
    )

    # QPS Efficiency = qps / concurrency
    curr_eff = None
    cand_eff = None
    if current.get("best_stable_qps") and current.get("best_stable_concurrency"):
        curr_eff = current["best_stable_qps"] / current["best_stable_concurrency"]
    if candidate.get("best_stable_qps") and candidate.get("best_stable_concurrency"):
        cand_eff = candidate["best_stable_qps"] / candidate["best_stable_concurrency"]

    efficiency = _numeric_similarity(curr_eff, cand_eff)

    deg_reason = _degradation_reason_match_score(
        current.get("degradation_reason"),
        candidate.get("degradation_reason"),
    )

    breakdown = {
        "best_stable_concurrency": round(best_cc, 3),
        "best_stable_qps": round(best_qps, 3),
        "degradation_point": round(deg_point, 3),
        "steps_to_degradation": round(steps, 3),
        "qps_efficiency": round(efficiency, 3),
        "degradation_reason": round(deg_reason, 3),
    }

    total = (
        best_cc * weights["best_stable_concurrency"]
        + best_qps * weights["best_stable_qps"]
        + deg_point * weights["degradation_point"]
        + steps * weights["steps_to_degradation"]
        + efficiency * weights["qps_efficiency"]
        + deg_reason * weights["degradation_reason"]
    )

    return {
        "total_score": round(total, 3),
        "breakdown": breakdown,
        "confidence": get_confidence_level(total),
    }


def calculate_similarity_score(
    current: dict[str, Any],
    candidate: dict[str, Any],
    load_mode: str,
) -> dict[str, Any]:
    """
    Calculate similarity score based on load mode.

    Dispatches to the appropriate mode-specific scoring function.

    Args:
        current: Current test data with extracted features.
        candidate: Candidate test data with extracted features.
        load_mode: Load mode (CONCURRENCY, QPS, FIND_MAX_CONCURRENCY).

    Returns:
        Dictionary with total_score, breakdown, confidence, and exclusion reasons.
    """
    mode = load_mode.upper()

    # First check hard gates
    passes, gate_failures = check_hard_gates(current, candidate)

    if not passes:
        return {
            "total_score": 0.0,
            "breakdown": {},
            "confidence": "EXCLUDED",
            "excluded": True,
            "exclusion_reasons": gate_failures,
        }

    # Calculate soft score based on mode
    if mode == "CONCURRENCY":
        result = calculate_similarity_score_concurrency(current, candidate)
    elif mode == "QPS":
        result = calculate_similarity_score_qps(current, candidate)
    elif mode == "FIND_MAX_CONCURRENCY":
        result = calculate_similarity_score_find_max(current, candidate)
    else:
        # Default to CONCURRENCY scoring for unknown modes
        result = calculate_similarity_score_concurrency(current, candidate)

    result["excluded"] = result["confidence"] == "EXCLUDED"
    result["exclusion_reasons"] = []

    return result


# =============================================================================
# EXCLUSION REASON FORMATTING (Section 9.6)
# =============================================================================

def format_exclusion_reason(
    code: str,
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> str:
    """
    Format exclusion reason with actual values.

    Codes:
    - WH_SIZE_DIFF: Warehouse size differs
    - DURATION_DIFF: Duration differs significantly
    - SCALE_MODE_DIFF: Different scale mode
    - CONCURRENCY_DIFF: Concurrency differs significantly
    - WORKLOAD_DIFF: Workload mix differs
    - LOW_QUALITY: Baseline test was unstable
    - CACHE_MODE_DIFF: Cache mode differs
    """
    if code == "WH_SIZE_DIFF":
        return (
            f"Warehouse size differs: {current.get('warehouse_size')} "
            f"vs {candidate.get('warehouse_size')}"
        )

    if code == "DURATION_DIFF":
        curr_dur = current.get("duration_seconds", 0)
        cand_dur = candidate.get("duration_seconds", 0)
        if cand_dur > 0:
            pct = abs(curr_dur - cand_dur) / cand_dur * 100
        else:
            pct = 100
        return f"Duration differs by {pct:.0f}% ({curr_dur}s vs {cand_dur}s)"

    if code == "SCALE_MODE_DIFF":
        return (
            f"Different scale mode: {current.get('scale_mode')} "
            f"vs {candidate.get('scale_mode')}"
        )

    if code == "CONCURRENCY_DIFF":
        curr_cc = current.get("concurrent_connections", 0)
        cand_cc = candidate.get("concurrent_connections", 0)
        if cand_cc > 0:
            pct = abs(curr_cc - cand_cc) / cand_cc * 100
        else:
            pct = 100
        return f"Concurrency differs by {pct:.0f}%"

    if code == "WORKLOAD_DIFF":
        return (
            f"Workload mix differs: {current.get('read_pct', 0):.0f}% "
            f"vs {candidate.get('read_pct', 0):.0f}% reads"
        )

    if code == "LOW_QUALITY":
        quality = candidate.get("steady_state_quality", 0)
        return f"Baseline test had unstable steady state (quality={quality:.2f})"

    if code == "CACHE_MODE_DIFF":
        return (
            f"Cache mode differs: {current.get('use_cached_result')} "
            f"vs {candidate.get('use_cached_result')}"
        )

    return f"Exclusion: {code}"
