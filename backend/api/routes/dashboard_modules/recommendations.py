"""
Dashboard Recommendations - Scoring engine for workload-based recommendations.
"""

from typing import Optional
from .models import Recommendation


# =============================================================================
# Constants
# =============================================================================

# Workload type definitions with their priorities
WORKLOAD_PROFILES = {
    "OLTP_READ_HEAVY": {
        "name": "Read-Heavy OLTP",
        "description": "Online transaction processing with high read throughput",
        "priorities": {
            "avg_qps": 0.35,
            "avg_p95_ms": 0.30,  # Lower is better
            "avg_error_rate": 0.20,
            "cost_efficiency": 0.15,
        },
        "lower_is_better": ["avg_p95_ms", "avg_error_rate", "cost_efficiency"],
    },
    "OLTP_WRITE_HEAVY": {
        "name": "Write-Heavy OLTP",
        "description": "Transaction processing with frequent writes",
        "priorities": {
            "avg_qps": 0.30,
            "avg_p95_ms": 0.35,  # Latency more important for writes
            "avg_error_rate": 0.20,
            "cost_efficiency": 0.15,
        },
        "lower_is_better": ["avg_p95_ms", "avg_error_rate", "cost_efficiency"],
    },
    "ANALYTICS": {
        "name": "Analytical Queries",
        "description": "Complex queries with aggregations, less sensitive to latency",
        "priorities": {
            "avg_qps": 0.40,
            "avg_p95_ms": 0.20,  # Less important
            "avg_error_rate": 0.15,
            "cost_efficiency": 0.25,  # Cost matters more
        },
        "lower_is_better": ["avg_p95_ms", "avg_error_rate", "cost_efficiency"],
    },
    "REAL_TIME": {
        "name": "Real-Time Operations",
        "description": "Low-latency requirements, sub-second responses",
        "priorities": {
            "avg_qps": 0.20,
            "avg_p95_ms": 0.45,  # Latency is king
            "avg_error_rate": 0.25,
            "cost_efficiency": 0.10,
        },
        "lower_is_better": ["avg_p95_ms", "avg_error_rate", "cost_efficiency"],
    },
    "HYBRID": {
        "name": "Mixed Workloads",
        "description": "Balanced read/write with moderate latency requirements",
        "priorities": {
            "avg_qps": 0.30,
            "avg_p95_ms": 0.30,
            "avg_error_rate": 0.20,
            "cost_efficiency": 0.20,
        },
        "lower_is_better": ["avg_p95_ms", "avg_error_rate", "cost_efficiency"],
    },
}


# =============================================================================
# Scoring Functions
# =============================================================================

def normalize_metric(value: float, all_values: list[float], lower_is_better: bool = False) -> float:
    """
    Normalize a metric value to 0-1 scale.
    
    Args:
        value: The value to normalize
        all_values: All values for this metric across table types
        lower_is_better: If True, lower values get higher scores
        
    Returns:
        Normalized score between 0 and 1
    """
    if not all_values:
        return 0.0
    
    min_val = min(all_values)
    max_val = max(all_values)
    
    if max_val == min_val:
        return 1.0  # All values equal
    
    # Normalize to 0-1
    normalized = (value - min_val) / (max_val - min_val)
    
    # Invert if lower is better
    if lower_is_better:
        normalized = 1.0 - normalized
    
    return normalized


def calculate_weighted_score(
    metrics: dict[str, Optional[float]],
    weights: dict[str, float],
    all_metrics: list[dict[str, Optional[float]]],
    lower_is_better: list[str]
) -> float:
    """
    Calculate weighted score for a table type.
    
    Args:
        metrics: Metrics for this table type
        weights: Weight for each metric
        all_metrics: Metrics for all table types (for normalization)
        lower_is_better: List of metrics where lower is better
        
    Returns:
        Weighted score between 0 and 1
    """
    total_score = 0.0
    total_weight = 0.0
    
    for metric_name, weight in weights.items():
        value = metrics.get(metric_name)
        if value is None:
            continue
        
        # Get all values for this metric
        all_values = [
            m.get(metric_name) for m in all_metrics 
            if m.get(metric_name) is not None
        ]
        
        if not all_values:
            continue
        
        # Normalize and weight
        is_lower_better = metric_name in lower_is_better
        normalized = normalize_metric(value, all_values, is_lower_better)
        
        total_score += normalized * weight
        total_weight += weight
    
    return total_score / total_weight if total_weight > 0 else 0.0


def generate_recommendation(
    workload_type: str,
    table_type_metrics: list[dict],
    credit_cost_usd: float = 3.0
) -> Optional[Recommendation]:
    """
    Generate a recommendation for a specific workload type.
    
    Args:
        workload_type: Key from WORKLOAD_PROFILES
        table_type_metrics: List of dicts with table_type and metrics
        credit_cost_usd: Cost per credit in USD
        
    Returns:
        Recommendation object or None if unable to generate
    """
    profile = WORKLOAD_PROFILES.get(workload_type)
    if not profile:
        return None
    
    if not table_type_metrics:
        return None
    
    # Calculate cost efficiency metric for each table type
    for m in table_type_metrics:
        credits_per_1k = m.get("credits_per_1k_ops")
        if credits_per_1k is not None and credits_per_1k > 0:
            m["cost_efficiency"] = credits_per_1k  # Lower is better
        else:
            m["cost_efficiency"] = None
    
    # Score each table type
    scores = []
    for metrics in table_type_metrics:
        score = calculate_weighted_score(
            metrics,
            profile["priorities"],
            table_type_metrics,
            profile["lower_is_better"]
        )
        scores.append({
            "table_type": metrics["table_type"],
            "score": score,
            "metrics": {
                k: metrics.get(k) 
                for k in profile["priorities"].keys()
            }
        })
    
    # Sort by score descending
    scores.sort(key=lambda x: x["score"], reverse=True)
    
    if not scores:
        return None
    
    winner = scores[0]
    runner_up = scores[1] if len(scores) > 1 else None
    
    # Generate rationale
    rationale = _generate_rationale(winner, profile, table_type_metrics)
    runner_up_rationale = None
    if runner_up:
        runner_up_rationale = _generate_runner_up_rationale(
            runner_up, winner, profile
        )
    
    return Recommendation(
        workload_type=profile["name"],
        recommended_table_type=winner["table_type"],
        confidence=winner["score"],
        rationale=rationale,
        metrics_summary=winner["metrics"],
        runner_up=runner_up["table_type"] if runner_up else None,
        runner_up_rationale=runner_up_rationale
    )


def _generate_rationale(
    winner: dict,
    profile: dict,
    all_metrics: list[dict]
) -> str:
    """Generate explanation for why this table type was recommended."""
    
    table_type = winner["table_type"]
    metrics = winner["metrics"]
    
    strengths = []
    
    # Check QPS
    qps = metrics.get("avg_qps")
    if qps is not None:
        all_qps = [m.get("avg_qps") for m in all_metrics if m.get("avg_qps")]
        if all_qps and qps == max(all_qps):
            strengths.append(f"highest throughput ({qps:.0f} QPS)")
        elif all_qps and qps >= sorted(all_qps, reverse=True)[1] if len(all_qps) > 1 else 0:
            strengths.append(f"excellent throughput ({qps:.0f} QPS)")
    
    # Check latency
    p95 = metrics.get("avg_p95_ms")
    if p95 is not None:
        all_p95 = [m.get("avg_p95_ms") for m in all_metrics if m.get("avg_p95_ms")]
        if all_p95 and p95 == min(all_p95):
            strengths.append(f"lowest latency ({p95:.0f}ms P95)")
        elif all_p95 and p95 <= sorted(all_p95)[1] if len(all_p95) > 1 else float('inf'):
            strengths.append(f"low latency ({p95:.0f}ms P95)")
    
    # Check error rate
    error_rate = metrics.get("avg_error_rate")
    if error_rate is not None and error_rate < 0.01:
        strengths.append("high reliability (<1% errors)")
    
    # Check cost
    cost = metrics.get("cost_efficiency")
    if cost is not None:
        all_costs = [m.get("cost_efficiency") for m in all_metrics if m.get("cost_efficiency")]
        if all_costs and cost == min(all_costs):
            strengths.append("most cost-efficient")
    
    if not strengths:
        strengths.append(f"balanced performance (score: {winner['score']:.0%})")
    
    return f"{table_type} is recommended for {profile['name'].lower()} workloads due to " + \
           ", ".join(strengths) + "."


def _generate_runner_up_rationale(
    runner_up: dict,
    winner: dict,
    profile: dict
) -> str:
    """Generate explanation for the runner-up choice."""
    
    score_diff = winner["score"] - runner_up["score"]
    
    if score_diff < 0.05:
        return f"{runner_up['table_type']} is a close alternative " \
               f"(only {score_diff:.0%} behind). Consider if specific " \
               f"features favor one over the other."
    elif score_diff < 0.15:
        return f"{runner_up['table_type']} is a viable alternative " \
               f"if {winner['table_type']} doesn't meet your requirements."
    else:
        return f"{runner_up['table_type']} scores lower but may be suitable " \
               f"for simpler use cases."


def generate_all_recommendations(
    table_type_metrics: list[dict],
    credit_cost_usd: float = 3.0
) -> list[Recommendation]:
    """
    Generate recommendations for all workload types.
    
    Args:
        table_type_metrics: List of dicts with table_type and metrics
        credit_cost_usd: Cost per credit in USD
        
    Returns:
        List of Recommendation objects
    """
    recommendations = []
    
    for workload_type in WORKLOAD_PROFILES.keys():
        rec = generate_recommendation(
            workload_type, 
            table_type_metrics, 
            credit_cost_usd
        )
        if rec:
            recommendations.append(rec)
    
    return recommendations


def get_workload_profile_names() -> dict[str, str]:
    """Get mapping of workload type keys to display names."""
    return {
        key: profile["name"] 
        for key, profile in WORKLOAD_PROFILES.items()
    }
