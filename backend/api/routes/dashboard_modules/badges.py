"""
Dashboard Badges - Badge determination logic.
"""

from typing import Optional
from .models import TableTypeKPI, TemplateStatisticsResponse


# =============================================================================
# Badge Definitions
# =============================================================================

BADGE_DEFINITIONS = {
    # Performance badges
    "highest_qps": {
        "label": "🏆 Highest QPS",
        "description": "Best throughput among all table types",
        "category": "performance",
    },
    "lowest_latency": {
        "label": "⚡ Lowest Latency", 
        "description": "Best P95 latency among all table types",
        "category": "performance",
    },
    "most_consistent": {
        "label": "📊 Most Consistent",
        "description": "Lowest variance in performance",
        "category": "stability",
    },
    
    # Cost badges
    "most_cost_efficient": {
        "label": "💰 Most Cost Efficient",
        "description": "Lowest cost per 1K operations",
        "category": "cost",
    },
    "best_qps_per_dollar": {
        "label": "💵 Best QPS/$",
        "description": "Highest throughput per dollar",
        "category": "cost",
    },
    
    # Reliability badges
    "most_reliable": {
        "label": "✅ Most Reliable",
        "description": "Lowest error rate",
        "category": "reliability",
    },
    "zero_errors": {
        "label": "🛡️ Zero Errors",
        "description": "No errors recorded",
        "category": "reliability",
    },
    
    # Stability badges
    "very_stable": {
        "label": "🔒 Very Stable",
        "description": "CV < 10%, highly predictable",
        "category": "stability",
    },
    "stable": {
        "label": "📈 Stable",
        "description": "CV < 15%, predictable performance",
        "category": "stability",
    },
    "moderate": {
        "label": "📊 Moderate",
        "description": "CV < 25%, some variance",
        "category": "stability",
    },
    "volatile": {
        "label": "⚠️ Volatile",
        "description": "CV >= 25%, high variance",
        "category": "stability",
    },
    
    # Trend badges
    "improving": {
        "label": "📈 Improving",
        "description": "Performance trending upward",
        "category": "trend",
    },
    "degrading": {
        "label": "📉 Degrading",
        "description": "Performance trending downward",
        "category": "trend",
    },
    
    # Sample size badges
    "high_confidence": {
        "label": "🎯 High Confidence",
        "description": "50+ test runs",
        "category": "confidence",
    },
    "low_sample": {
        "label": "❓ Low Sample",
        "description": "Fewer than 10 test runs",
        "category": "confidence",
    },
}


# =============================================================================
# Badge Assignment Functions
# =============================================================================

def assign_table_type_badges(kpi_cards: list[TableTypeKPI]) -> list[TableTypeKPI]:
    """
    Assign comparative badges to table type KPI cards.
    
    Args:
        kpi_cards: List of TableTypeKPI objects
        
    Returns:
        Same list with badges populated
    """
    if not kpi_cards:
        return kpi_cards
    
    # Extract metrics for comparison
    qps_values = [(k.table_type, k.avg_qps) for k in kpi_cards if k.avg_qps]
    p95_values = [(k.table_type, k.avg_p95_ms) for k in kpi_cards if k.avg_p95_ms]
    error_values = [(k.table_type, k.avg_error_rate) for k in kpi_cards if k.avg_error_rate is not None]
    cost_values = [(k.table_type, k.credits_per_1k_ops) for k in kpi_cards if k.credits_per_1k_ops]
    stddev_values = [(k.table_type, k.stddev_qps / k.avg_qps if k.stddev_qps and k.avg_qps else None) 
                    for k in kpi_cards]
    stddev_values = [(t, v) for t, v in stddev_values if v is not None]
    
    # Find winners
    highest_qps = max(qps_values, key=lambda x: x[1])[0] if qps_values else None
    lowest_p95 = min(p95_values, key=lambda x: x[1])[0] if p95_values else None
    lowest_error = min(error_values, key=lambda x: x[1])[0] if error_values else None
    lowest_cost = min(cost_values, key=lambda x: x[1])[0] if cost_values else None
    most_consistent = min(stddev_values, key=lambda x: x[1])[0] if stddev_values else None
    
    # Assign badges
    for kpi in kpi_cards:
        badges = []
        
        # Performance badges
        if kpi.table_type == highest_qps:
            badges.append("highest_qps")
        if kpi.table_type == lowest_p95:
            badges.append("lowest_latency")
        if kpi.table_type == most_consistent:
            badges.append("most_consistent")
        
        # Cost badges
        if kpi.table_type == lowest_cost:
            badges.append("most_cost_efficient")
        
        # Reliability badges
        if kpi.table_type == lowest_error:
            badges.append("most_reliable")
        if kpi.avg_error_rate == 0:
            badges.append("zero_errors")
        
        # Confidence badges
        if kpi.test_count >= 50:
            badges.append("high_confidence")
        elif kpi.test_count < 10:
            badges.append("low_sample")
        
        kpi.badges = badges
    
    return kpi_cards


def assign_template_badges(
    stats: TemplateStatisticsResponse,
    all_templates: Optional[list[TemplateStatisticsResponse]] = None
) -> TemplateStatisticsResponse:
    """
    Assign badges to a template's statistics.
    
    Args:
        stats: Template statistics
        all_templates: Optional list of all templates for comparison
        
    Returns:
        Same stats object with badges populated
    """
    badges = []
    
    # Stability badges (from pre-calculated)
    stability_badge = stats.stability.badge
    if stability_badge in ["very_stable", "stable", "moderate", "volatile"]:
        badges.append(stability_badge)
    
    # Trend badges
    if stats.stability.trend_direction == "improving" and stats.stability.trend_pct and stats.stability.trend_pct > 5:
        badges.append("improving")
    elif stats.stability.trend_direction == "degrading" and stats.stability.trend_pct and stats.stability.trend_pct < -5:
        badges.append("degrading")
    
    # Confidence badges
    if stats.total_runs >= 50:
        badges.append("high_confidence")
    elif stats.total_runs < 10:
        badges.append("low_sample")
    
    # Error badges
    if stats.error_stats.avg == 0:
        badges.append("zero_errors")
    elif stats.error_stats.max and stats.error_stats.max < 0.01:
        badges.append("most_reliable")
    
    # Comparative badges (if we have all templates)
    if all_templates:
        same_type = [t for t in all_templates if t.table_type == stats.table_type]
        if same_type:
            # Best QPS in category
            qps_values = [(t.template_id, t.qps_stats.avg) for t in same_type if t.qps_stats.avg]
            if qps_values:
                best_qps = max(qps_values, key=lambda x: x[1])
                if stats.template_id == best_qps[0]:
                    badges.append("highest_qps")
            
            # Best latency in category
            p95_values = [(t.template_id, t.p95_stats.avg) for t in same_type if t.p95_stats.avg]
            if p95_values:
                best_p95 = min(p95_values, key=lambda x: x[1])
                if stats.template_id == best_p95[0]:
                    badges.append("lowest_latency")
    
    stats.badges = badges
    return stats


def get_badge_display(badge_key: str) -> dict:
    """
    Get display information for a badge.
    
    Args:
        badge_key: The badge identifier
        
    Returns:
        Dict with label, description, category
    """
    badge = BADGE_DEFINITIONS.get(badge_key, {})
    return {
        "key": badge_key,
        "label": badge.get("label", badge_key),
        "description": badge.get("description", ""),
        "category": badge.get("category", "other"),
    }


def get_all_badge_definitions() -> dict:
    """Get all badge definitions for UI reference."""
    return BADGE_DEFINITIONS
