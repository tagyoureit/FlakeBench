"""
Dashboard API Models - Pydantic response models for dashboard endpoints.
"""

from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field


# =============================================================================
# Table Type Summary Models
# =============================================================================

class TableTypeKPI(BaseModel):
    """KPI card data for a single table type."""
    
    table_type: str
    test_count: int
    unique_templates: int
    
    # Performance metrics
    avg_qps: Optional[float] = None
    median_qps: Optional[float] = None
    min_qps: Optional[float] = None
    max_qps: Optional[float] = None
    stddev_qps: Optional[float] = None
    
    # Latency metrics
    avg_p50_ms: Optional[float] = None
    avg_p95_ms: Optional[float] = None
    avg_p99_ms: Optional[float] = None
    median_p95_ms: Optional[float] = None
    
    # Error metrics
    avg_error_rate: Optional[float] = None
    max_error_rate: Optional[float] = None
    
    # Cost metrics (raw from DB)
    total_credits: Optional[float] = None
    avg_credits_per_test: Optional[float] = None
    credits_per_1k_ops: Optional[float] = None
    
    # Cost metrics (USD - calculated)
    estimated_cost_usd: Optional[float] = None
    cost_per_1k_ops_usd: Optional[float] = None
    
    # Operations
    total_operations: Optional[int] = None
    
    # Time range
    earliest_test: Optional[datetime] = None
    latest_test: Optional[datetime] = None
    
    # Computed badges
    badges: list[str] = Field(default_factory=list)
    
    # Trend indicator
    trend_direction: Optional[str] = None  # "up", "down", "stable"


class ComparisonRow(BaseModel):
    """A single row in the comparison table."""
    
    metric: str
    metric_label: str
    values: dict[str, Optional[float]]  # {table_type: value}
    winner: Optional[str] = None
    lower_is_better: bool = False
    format_type: str = "number"  # "number", "latency", "percent", "cost"


class ComparisonTable(BaseModel):
    """Full comparison table data."""
    
    columns: list[str]  # ["Metric", "STANDARD", "HYBRID", ...]
    rows: list[ComparisonRow]


class DashboardTotals(BaseModel):
    """Aggregate totals across all table types."""
    
    total_tests: int
    total_templates: int
    total_operations: int
    total_credits: float
    total_cost_usd: float


class Recommendation(BaseModel):
    """Workload-based recommendation."""
    
    workload_type: str  # "OLTP", "Analytics", "Mixed"
    recommended_table_type: str
    confidence: float  # 0.0 - 1.0
    rationale: str
    metrics_summary: dict[str, Optional[float]]  # Values may be None
    runner_up: Optional[str] = None
    runner_up_rationale: Optional[str] = None


class TableTypeSummaryResponse(BaseModel):
    """Response for /api/dashboard/table-types/summary."""
    
    generated_at: datetime
    kpi_cards: list[TableTypeKPI]
    comparison_table: ComparisonTable
    totals: DashboardTotals


class RecommendationsResponse(BaseModel):
    """Response for /api/dashboard/table-types/recommendations."""
    
    recommendations: list[Recommendation]


# =============================================================================
# Template Statistics Models
# =============================================================================

class MetricStats(BaseModel):
    """Statistics for a single metric."""
    
    avg: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None
    median: Optional[float] = None
    stddev: Optional[float] = None
    cv: Optional[float] = None  # Coefficient of variation


class CostStats(BaseModel):
    """Cost-related statistics."""
    
    total_credits: float = 0
    avg_credits_per_run: float = 0
    credits_per_1k_ops: Optional[float] = None
    total_cost_usd: float = 0
    avg_cost_per_run_usd: float = 0
    cost_per_1k_ops_usd: Optional[float] = None
    qps_per_dollar: Optional[float] = None


class StabilityMetrics(BaseModel):
    """Stability and trend metrics."""
    
    cv_qps: Optional[float] = None
    cv_p95: Optional[float] = None
    badge: str = "unknown"  # "very_stable", "stable", "moderate", "volatile"
    trend_direction: Optional[str] = None  # "improving", "degrading", "stable"
    trend_pct: Optional[float] = None


class OutlierInfo(BaseModel):
    """Information about an outlier test run."""
    
    test_id: str
    date: datetime
    metric: str
    value: float
    reason: str  # e.g., "3.2σ above median"


class TemplateSummary(BaseModel):
    """Summary for a template in list view."""
    
    template_id: str
    template_name: str
    table_type: str
    warehouse_size: Optional[str] = None
    load_mode: Optional[str] = None
    total_runs: int
    last_run: Optional[datetime] = None
    avg_qps: Optional[float] = None
    avg_p95_ms: Optional[float] = None
    stability_badge: str = "unknown"
    cost_per_1k_ops_usd: Optional[float] = None


class TemplateStatisticsResponse(BaseModel):
    """Response for /api/dashboard/templates/{id}/statistics."""
    
    template_id: str
    template_name: str
    table_type: str
    warehouse_size: Optional[str] = None
    load_mode: Optional[str] = None
    
    # Counts
    total_runs: int
    recent_runs: int  # Last 10
    
    # Performance stats
    qps_stats: MetricStats
    p50_stats: MetricStats
    p95_stats: MetricStats
    p99_stats: MetricStats
    error_stats: MetricStats
    
    # Cost stats
    cost_stats: CostStats
    
    # Stability
    stability: StabilityMetrics
    
    # Outliers
    outliers: list[OutlierInfo] = Field(default_factory=list)
    
    # Badges
    badges: list[str] = Field(default_factory=list)


class TemplateListResponse(BaseModel):
    """Response for /api/dashboard/templates list."""
    
    templates: list[TemplateSummary]
    total_count: int


# =============================================================================
# Distribution Models (Histograms)
# =============================================================================

class DistributionResponse(BaseModel):
    """Response for /api/dashboard/templates/{id}/distribution."""
    
    template_id: str
    metric: str
    
    # Histogram data
    bins: list[float]  # Bin edges
    counts: list[int]  # Count per bin
    
    # Summary stats
    mean: float
    std_dev: float
    min_val: float
    max_val: float
    
    # Distribution shape
    distribution_type: str  # "normal", "skewed_right", "bimodal", etc.
    skewness: Optional[float] = None


# =============================================================================
# Scatter Plot Models
# =============================================================================

class ScatterPoint(BaseModel):
    """A single point in a scatter plot."""
    
    x: float
    y: float
    test_id: str
    label: str  # For tooltip


class TrendLine(BaseModel):
    """Trend line for scatter plot."""
    
    slope: float
    intercept: float
    r_squared: float


class ScatterResponse(BaseModel):
    """Response for /api/dashboard/templates/{id}/scatter."""
    
    template_id: str
    x_metric: str
    y_metric: str
    x_label: str
    y_label: str
    data: list[ScatterPoint]
    correlation: Optional[float] = None
    trend_line: Optional[TrendLine] = None


# =============================================================================
# Trend Models
# =============================================================================

class TrendAnalysis(BaseModel):
    """Trend analysis for a metric."""
    
    direction: str  # "improving", "degrading", "stable"
    slope: float
    r_squared: float
    confidence: float
    change_pct: float  # % change from first to last


class TimeSeriesPoint(BaseModel):
    """A single point in time series data."""
    
    date: date
    qps: Optional[float] = None
    p95_ms: Optional[float] = None
    cost_per_1k_ops: Optional[float] = None
    test_count: int = 0


class TrendResponse(BaseModel):
    """Response for /api/dashboard/templates/{id}/trend."""
    
    template_id: str
    qps_trend: TrendAnalysis
    p95_trend: TrendAnalysis
    cost_trend: Optional[TrendAnalysis] = None
    time_series: list[TimeSeriesPoint]


# =============================================================================
# Template Runs Models
# =============================================================================

class TemplateRun(BaseModel):
    """A single test run for a template."""
    
    test_id: str
    start_time: datetime
    duration_seconds: Optional[float] = None
    concurrent_connections: Optional[int] = None
    qps: Optional[float] = None
    p50_ms: Optional[float] = None
    p95_ms: Optional[float] = None
    p99_ms: Optional[float] = None
    error_rate: float = 0
    credits_used: Optional[float] = None
    cost_per_1k_ops_usd: Optional[float] = None
    
    # Outlier detection
    is_outlier: bool = False
    outlier_reason: Optional[str] = None


class TemplateRunsResponse(BaseModel):
    """Response for /api/dashboard/templates/{id}/runs."""
    
    template_id: str
    runs: list[TemplateRun]
    total_count: int
    page: int
    page_size: int


# =============================================================================
# Cost Models
# =============================================================================

class DailyCostEntry(BaseModel):
    """A single day's cost data."""
    
    run_date: date
    table_type: str
    warehouse_size: Optional[str] = None
    test_count: int
    total_credits: float
    total_cost_usd: float
    total_operations: int
    credits_per_1k_ops: Optional[float] = None
    avg_qps: Optional[float] = None


class CostTotals(BaseModel):
    """Aggregate cost totals."""
    
    total_credits: float
    total_cost_usd: float
    total_tests: int
    total_operations: int
    avg_credits_per_1k_ops: Optional[float] = None


class DailyCostResponse(BaseModel):
    """Response for /api/dashboard/costs/daily."""
    
    data: list[DailyCostEntry]
    totals: CostTotals


# =============================================================================
# Chart Data Models (for Chart.js)
# =============================================================================

class ChartDataset(BaseModel):
    """A dataset for Chart.js."""
    
    label: str
    data: list[Optional[float]]
    backgroundColor: str | list[str]
    borderColor: Optional[str] = None
    borderWidth: int = 1


class ChartDataResponse(BaseModel):
    """Response for chart endpoints."""
    
    chart_type: str
    labels: list[str]
    datasets: list[ChartDataset]
