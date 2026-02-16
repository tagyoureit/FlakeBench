"""
Dashboard Modules - Package initialization.
"""

from .models import (
    # Table Type Models
    TableTypeKPI,
    ComparisonRow,
    ComparisonTable,
    DashboardTotals,
    Recommendation,
    TableTypeSummaryResponse,
    RecommendationsResponse,
    
    # Template Models
    MetricStats,
    CostStats,
    StabilityMetrics,
    OutlierInfo,
    TemplateSummary,
    TemplateStatisticsResponse,
    TemplateListResponse,
    
    # Distribution Models
    DistributionResponse,
    
    # Scatter Models
    ScatterPoint,
    TrendLine,
    ScatterResponse,
    
    # Trend Models
    TrendAnalysis,
    TimeSeriesPoint,
    TrendResponse,
    
    # Run Models
    TemplateRun,
    TemplateRunsResponse,
    
    # Cost Models
    DailyCostEntry,
    CostTotals,
    DailyCostResponse,
    
    # Chart Models
    ChartDataset,
    ChartDataResponse,
)

__all__ = [
    # Table Type Models
    "TableTypeKPI",
    "ComparisonRow",
    "ComparisonTable",
    "DashboardTotals",
    "Recommendation",
    "TableTypeSummaryResponse",
    "RecommendationsResponse",
    
    # Template Models
    "MetricStats",
    "CostStats",
    "StabilityMetrics",
    "OutlierInfo",
    "TemplateSummary",
    "TemplateStatisticsResponse",
    "TemplateListResponse",
    
    # Distribution Models
    "DistributionResponse",
    
    # Scatter Models
    "ScatterPoint",
    "TrendLine",
    "ScatterResponse",
    
    # Trend Models
    "TrendAnalysis",
    "TimeSeriesPoint",
    "TrendResponse",
    
    # Run Models
    "TemplateRun",
    "TemplateRunsResponse",
    
    # Cost Models
    "DailyCostEntry",
    "CostTotals",
    "DailyCostResponse",
    
    # Chart Models
    "ChartDataset",
    "ChartDataResponse",
]
