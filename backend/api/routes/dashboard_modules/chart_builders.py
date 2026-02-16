"""
Dashboard Chart Builders - Format data for Chart.js.
"""

from typing import Optional
from .models import (
    ChartDataset,
    ChartDataResponse,
    TableTypeKPI,
    DailyCostEntry,
)


# =============================================================================
# Color Palettes
# =============================================================================

# Color palette for table types (consistent across charts)
TABLE_TYPE_COLORS = {
    "STANDARD": {"bg": "rgba(59, 130, 246, 0.7)", "border": "rgb(59, 130, 246)"},      # Blue
    "HYBRID": {"bg": "rgba(16, 185, 129, 0.7)", "border": "rgb(16, 185, 129)"},        # Green
    "INTERACTIVE": {"bg": "rgba(249, 115, 22, 0.7)", "border": "rgb(249, 115, 22)"},   # Orange
    "DYNAMIC": {"bg": "rgba(139, 92, 246, 0.7)", "border": "rgb(139, 92, 246)"},       # Purple
    "POSTGRES": {"bg": "rgba(236, 72, 153, 0.7)", "border": "rgb(236, 72, 153)"},      # Pink
}

# Default color for unknown types
DEFAULT_COLOR = {"bg": "rgba(107, 114, 128, 0.7)", "border": "rgb(107, 114, 128)"}


def get_table_type_color(table_type: str) -> dict:
    """Get color for a table type."""
    return TABLE_TYPE_COLORS.get(table_type.upper(), DEFAULT_COLOR)


# =============================================================================
# Bar Chart Builders
# =============================================================================

def build_qps_comparison_chart(kpi_cards: list[TableTypeKPI]) -> ChartDataResponse:
    """Build bar chart comparing QPS across table types."""
    
    labels = [k.table_type for k in kpi_cards]
    values = [k.avg_qps if k.avg_qps else 0 for k in kpi_cards]
    colors = [get_table_type_color(k.table_type)["bg"] for k in kpi_cards]
    borders = [get_table_type_color(k.table_type)["border"] for k in kpi_cards]
    
    return ChartDataResponse(
        chart_type="bar",
        labels=labels,
        datasets=[
            ChartDataset(
                label="Average QPS",
                data=values,
                backgroundColor=colors,
                borderColor=borders,
                borderWidth=2,
            )
        ]
    )


def build_latency_comparison_chart(kpi_cards: list[TableTypeKPI]) -> ChartDataResponse:
    """Build bar chart comparing P95 latency across table types."""
    
    labels = [k.table_type for k in kpi_cards]
    values = [k.avg_p95_ms if k.avg_p95_ms else 0 for k in kpi_cards]
    colors = [get_table_type_color(k.table_type)["bg"] for k in kpi_cards]
    borders = [get_table_type_color(k.table_type)["border"] for k in kpi_cards]
    
    return ChartDataResponse(
        chart_type="bar",
        labels=labels,
        datasets=[
            ChartDataset(
                label="Average P95 Latency (ms)",
                data=values,
                backgroundColor=colors,
                borderColor=borders,
                borderWidth=2,
            )
        ]
    )


def build_cost_comparison_chart(kpi_cards: list[TableTypeKPI]) -> ChartDataResponse:
    """Build bar chart comparing cost per 1K ops across table types."""
    
    labels = [k.table_type for k in kpi_cards]
    values = [k.cost_per_1k_ops_usd if k.cost_per_1k_ops_usd else 0 for k in kpi_cards]
    colors = [get_table_type_color(k.table_type)["bg"] for k in kpi_cards]
    borders = [get_table_type_color(k.table_type)["border"] for k in kpi_cards]
    
    return ChartDataResponse(
        chart_type="bar",
        labels=labels,
        datasets=[
            ChartDataset(
                label="Cost per 1K Operations (USD)",
                data=values,
                backgroundColor=colors,
                borderColor=borders,
                borderWidth=2,
            )
        ]
    )


def build_test_count_chart(kpi_cards: list[TableTypeKPI]) -> ChartDataResponse:
    """Build bar chart showing test counts per table type."""
    
    labels = [k.table_type for k in kpi_cards]
    values = [float(k.test_count) for k in kpi_cards]
    colors = [get_table_type_color(k.table_type)["bg"] for k in kpi_cards]
    borders = [get_table_type_color(k.table_type)["border"] for k in kpi_cards]
    
    return ChartDataResponse(
        chart_type="bar",
        labels=labels,
        datasets=[
            ChartDataset(
                label="Test Count",
                data=values,
                backgroundColor=colors,
                borderColor=borders,
                borderWidth=2,
            )
        ]
    )


# =============================================================================
# Line Chart Builders
# =============================================================================

def build_daily_cost_trend_chart(
    daily_costs: list[DailyCostEntry],
    group_by_table_type: bool = True
) -> ChartDataResponse:
    """Build line chart showing daily cost trend."""
    
    if not daily_costs:
        return ChartDataResponse(chart_type="line", labels=[], datasets=[])
    
    # Get unique dates (sorted)
    dates = sorted(set(str(d.run_date) for d in daily_costs))
    
    if group_by_table_type:
        # Group by table type
        table_types = sorted(set(d.table_type for d in daily_costs if d.table_type))
        
        datasets = []
        for tt in table_types:
            # Get costs for this table type by date
            tt_costs = {str(d.run_date): d.total_cost_usd for d in daily_costs if d.table_type == tt}
            values = [tt_costs.get(date) for date in dates]
            
            color = get_table_type_color(tt)
            datasets.append(ChartDataset(
                label=tt,
                data=values,
                backgroundColor=color["bg"],
                borderColor=color["border"],
                borderWidth=2,
            ))
        
        return ChartDataResponse(
            chart_type="line",
            labels=dates,
            datasets=datasets
        )
    else:
        # Aggregate total by date
        date_totals = {}
        for d in daily_costs:
            date_str = str(d.run_date)
            date_totals[date_str] = date_totals.get(date_str, 0) + d.total_cost_usd
        
        values = [date_totals.get(date) for date in dates]
        
        return ChartDataResponse(
            chart_type="line",
            labels=dates,
            datasets=[
                ChartDataset(
                    label="Total Cost (USD)",
                    data=values,
                    backgroundColor="rgba(59, 130, 246, 0.2)",
                    borderColor="rgb(59, 130, 246)",
                    borderWidth=2,
                )
            ]
        )


def build_qps_trend_chart(time_series: list[dict]) -> ChartDataResponse:
    """Build line chart showing QPS trend over time."""
    
    if not time_series:
        return ChartDataResponse(chart_type="line", labels=[], datasets=[])
    
    labels = [str(ts.get("date", "")) for ts in time_series]
    qps_values = [ts.get("avg_qps") for ts in time_series]
    p95_values = [ts.get("avg_p95_ms") for ts in time_series]
    
    datasets = [
        ChartDataset(
            label="QPS",
            data=qps_values,
            backgroundColor="rgba(59, 130, 246, 0.2)",
            borderColor="rgb(59, 130, 246)",
            borderWidth=2,
        )
    ]
    
    # Add P95 on secondary axis if present
    if any(v is not None for v in p95_values):
        datasets.append(ChartDataset(
            label="P95 (ms)",
            data=p95_values,
            backgroundColor="rgba(249, 115, 22, 0.2)",
            borderColor="rgb(249, 115, 22)",
            borderWidth=2,
        ))
    
    return ChartDataResponse(
        chart_type="line",
        labels=labels,
        datasets=datasets
    )


# =============================================================================
# Histogram Builder
# =============================================================================

def build_histogram_chart(
    bins: list[float],
    counts: list[int],
    metric_label: str = "Value"
) -> ChartDataResponse:
    """Build histogram chart from bin edges and counts."""
    
    # Create bin labels (e.g., "0-10", "10-20")
    labels = []
    for i in range(len(counts)):
        if i < len(bins) - 1:
            labels.append(f"{bins[i]:.0f}-{bins[i+1]:.0f}")
        else:
            labels.append(f">{bins[i]:.0f}")
    
    return ChartDataResponse(
        chart_type="bar",
        labels=labels,
        datasets=[
            ChartDataset(
                label=f"Count ({metric_label})",
                data=[float(c) for c in counts],
                backgroundColor="rgba(59, 130, 246, 0.7)",
                borderColor="rgb(59, 130, 246)",
                borderWidth=1,
            )
        ]
    )


# =============================================================================
# Box Plot Builder
# =============================================================================

def build_box_plot_data(
    template_id: str,
    stats: dict
) -> dict:
    """
    Build box plot data for Chart.js box plot plugin.
    
    Note: Requires Chart.js box plot plugin (chartjs-chart-box-and-violin-plot)
    
    Returns dict with:
        - min, q1, median, q3, max values
        - outliers
    """
    return {
        "min": stats.get("min"),
        "q1": stats.get("p25"),  # Would need to calculate from raw data
        "median": stats.get("median"),
        "q3": stats.get("p75"),  # Would need to calculate from raw data
        "max": stats.get("max"),
        "mean": stats.get("avg"),
        "outliers": [],  # Would need to calculate from raw data
    }


# =============================================================================
# Scatter Plot Builder
# =============================================================================

def build_scatter_chart_data(
    points: list[dict],
    x_label: str = "X",
    y_label: str = "Y",
    trend_line: Optional[dict] = None
) -> dict:
    """
    Build scatter plot data for Chart.js.
    
    Args:
        points: List of dicts with x, y values
        x_label: Label for x-axis
        y_label: Label for y-axis
        trend_line: Optional dict with slope and intercept
        
    Returns:
        Dict suitable for Chart.js scatter chart
    """
    scatter_data = {
        "type": "scatter",
        "datasets": [
            {
                "label": f"{y_label} vs {x_label}",
                "data": [{"x": p.get("x"), "y": p.get("y")} for p in points if p.get("x") is not None],
                "backgroundColor": "rgba(59, 130, 246, 0.7)",
                "borderColor": "rgb(59, 130, 246)",
                "pointRadius": 6,
                "pointHoverRadius": 8,
            }
        ],
        "options": {
            "scales": {
                "x": {"title": {"display": True, "text": x_label}},
                "y": {"title": {"display": True, "text": y_label}},
            }
        }
    }
    
    # Add trend line if provided
    if trend_line and trend_line.get("slope") is not None:
        slope = trend_line["slope"]
        intercept = trend_line["intercept"]
        
        # Calculate line endpoints
        x_values = [p.get("x") for p in points if p.get("x") is not None]
        if x_values:
            x_min, x_max = min(x_values), max(x_values)
            y_min = slope * x_min + intercept
            y_max = slope * x_max + intercept
            
            scatter_data["datasets"].append({
                "label": f"Trend (R²={trend_line.get('r_squared', 0):.2f})",
                "data": [{"x": x_min, "y": y_min}, {"x": x_max, "y": y_max}],
                "type": "line",
                "borderColor": "rgba(249, 115, 22, 0.8)",
                "borderWidth": 2,
                "pointRadius": 0,
                "fill": False,
            })
    
    return scatter_data
