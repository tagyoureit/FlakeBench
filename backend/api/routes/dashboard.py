"""
Dashboard API Routes - Endpoints for dashboard pages.

Table Type Comparison:
- GET /api/dashboard/table-types/summary - KPI cards and comparison table
- GET /api/dashboard/table-types/recommendations - Workload recommendations
- GET /api/dashboard/table-types/chart/{chart_type} - Chart data

Template Analysis:
- GET /api/dashboard/templates - Template list
- GET /api/dashboard/templates/{template_id} - Template statistics
- GET /api/dashboard/templates/{template_id}/runs - Historical runs
- GET /api/dashboard/templates/{template_id}/distribution - Histogram data
- GET /api/dashboard/templates/{template_id}/scatter - Scatter plot data

Cost Analysis:
- GET /api/dashboard/costs/daily - Daily cost rollup
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status

from backend.config import settings
from backend.connectors import snowflake_pool

from .dashboard_modules.models import (
    TableTypeKPI,
    ComparisonRow,
    ComparisonTable,
    DashboardTotals,
    TableTypeSummaryResponse,
    RecommendationsResponse,
    TemplateSummary,
    TemplateListResponse,
    TemplateStatisticsResponse,
    MetricStats,
    CostStats,
    StabilityMetrics,
    OutlierInfo,
    TemplateRun,
    TemplateRunsResponse,
    DistributionResponse,
    ScatterPoint,
    ScatterResponse,
    DailyCostEntry,
    CostTotals,
    DailyCostResponse,
    ChartDataResponse,
)
from .dashboard_modules.aggregations import (
    get_table_type_summary_query,
    get_template_list_query,
    get_template_statistics_query,
    get_template_runs_query,
    get_template_runs_count_query,
    get_template_distribution_query,
    get_template_scatter_query,
    get_daily_cost_query,
)
from .dashboard_modules.recommendations import generate_all_recommendations
from .dashboard_modules.badges import assign_table_type_badges
from .dashboard_modules.chart_builders import (
    build_qps_comparison_chart,
    build_latency_comparison_chart,
    build_cost_comparison_chart,
    build_test_count_chart,
    build_histogram_chart,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Cost constants
CREDIT_COST_USD = getattr(settings, 'COST_DOLLARS_PER_CREDIT', 3.0)


def _prefix() -> str:
    """Get the database.schema prefix for queries."""
    return f"{settings.RESULTS_DATABASE}.{settings.RESULTS_SCHEMA}"


# =============================================================================
# Table Type Comparison Endpoints
# =============================================================================

@router.get("/table-types/summary", response_model=TableTypeSummaryResponse)
async def get_table_type_summary() -> TableTypeSummaryResponse:
    """
    Get aggregated KPI data for all table types.
    
    Returns KPI cards, comparison table, and totals for the dashboard.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _prefix()
    
    # Fetch from dynamic table
    query = f"""
    SELECT
        TABLE_TYPE,
        TEST_COUNT,
        UNIQUE_TEMPLATES,
        AVG_QPS,
        MIN_QPS,
        MAX_QPS,
        MEDIAN_QPS,
        STDDEV_QPS,
        AVG_P50_MS,
        MEDIAN_P50_MS,
        AVG_P95_MS,
        MIN_P95_MS,
        MAX_P95_MS,
        MEDIAN_P95_MS,
        AVG_P99_MS,
        MEDIAN_P99_MS,
        AVG_ERROR_RATE,
        MAX_ERROR_RATE,
        TOTAL_CREDITS,
        AVG_CREDITS_PER_TEST,
        CREDITS_PER_1K_OPS,
        TOTAL_OPERATIONS,
        EARLIEST_TEST,
        LATEST_TEST
    FROM {prefix}.DT_TABLE_TYPE_SUMMARY
    ORDER BY TEST_COUNT DESC
    """
    
    rows = await pool.execute_query(query)
    
    if not rows:
        # Return empty response if no data
        return TableTypeSummaryResponse(
            generated_at=datetime.now(),
            kpi_cards=[],
            comparison_table=ComparisonTable(columns=[], rows=[]),
            totals=DashboardTotals(
                total_tests=0,
                total_templates=0,
                total_operations=0,
                total_credits=0.0,
                total_cost_usd=0.0
            )
        )
    
    # Build KPI cards
    kpi_cards = []
    for row in rows:
        (
            table_type, test_count, unique_templates,
            avg_qps, min_qps, max_qps, median_qps, stddev_qps,
            avg_p50_ms, median_p50_ms,
            avg_p95_ms, min_p95_ms, max_p95_ms, median_p95_ms,
            avg_p99_ms, median_p99_ms,
            avg_error_rate, max_error_rate,
            total_credits, avg_credits_per_test, credits_per_1k_ops,
            total_operations,
            earliest_test, latest_test
        ) = row
        
        # Calculate USD costs
        estimated_cost_usd = float(total_credits or 0) * CREDIT_COST_USD if total_credits else None
        cost_per_1k_ops_usd = float(credits_per_1k_ops or 0) * CREDIT_COST_USD if credits_per_1k_ops else None
        
        kpi = TableTypeKPI(
            table_type=str(table_type),
            test_count=int(test_count or 0),
            unique_templates=int(unique_templates or 0),
            avg_qps=float(avg_qps) if avg_qps else None,
            min_qps=float(min_qps) if min_qps else None,
            max_qps=float(max_qps) if max_qps else None,
            median_qps=float(median_qps) if median_qps else None,
            stddev_qps=float(stddev_qps) if stddev_qps else None,
            avg_p50_ms=float(avg_p50_ms) if avg_p50_ms else None,
            avg_p95_ms=float(avg_p95_ms) if avg_p95_ms else None,
            avg_p99_ms=float(avg_p99_ms) if avg_p99_ms else None,
            median_p95_ms=float(median_p95_ms) if median_p95_ms else None,
            avg_error_rate=float(avg_error_rate) if avg_error_rate is not None else None,
            max_error_rate=float(max_error_rate) if max_error_rate is not None else None,
            total_credits=float(total_credits) if total_credits else None,
            avg_credits_per_test=float(avg_credits_per_test) if avg_credits_per_test else None,
            credits_per_1k_ops=float(credits_per_1k_ops) if credits_per_1k_ops else None,
            estimated_cost_usd=estimated_cost_usd,
            cost_per_1k_ops_usd=cost_per_1k_ops_usd,
            total_operations=int(total_operations) if total_operations else None,
            earliest_test=earliest_test,
            latest_test=latest_test,
        )
        kpi_cards.append(kpi)
    
    # Assign badges
    kpi_cards = assign_table_type_badges(kpi_cards)
    
    # Build comparison table
    comparison_table = _build_comparison_table(kpi_cards)
    
    # Calculate totals
    totals = DashboardTotals(
        total_tests=sum(k.test_count for k in kpi_cards),
        total_templates=sum(k.unique_templates for k in kpi_cards),
        total_operations=sum(k.total_operations or 0 for k in kpi_cards),
        total_credits=sum(k.total_credits or 0 for k in kpi_cards),
        total_cost_usd=sum((k.total_credits or 0) * CREDIT_COST_USD for k in kpi_cards)
    )
    
    return TableTypeSummaryResponse(
        generated_at=datetime.now(),
        kpi_cards=kpi_cards,
        comparison_table=comparison_table,
        totals=totals
    )


def _build_comparison_table(kpi_cards: list[TableTypeKPI]) -> ComparisonTable:
    """Build comparison table from KPI cards."""
    
    if not kpi_cards:
        return ComparisonTable(columns=[], rows=[])
    
    table_types = [k.table_type for k in kpi_cards]
    columns = ["Metric"] + table_types
    
    # Define metrics to compare
    metrics = [
        ("avg_qps", "Avg QPS", False, "number"),
        ("avg_p95_ms", "Avg P95 (ms)", True, "latency"),
        ("avg_p99_ms", "Avg P99 (ms)", True, "latency"),
        ("avg_error_rate", "Avg Error Rate", True, "percent"),
        ("cost_per_1k_ops_usd", "Cost per 1K Ops ($)", True, "cost"),
        ("test_count", "Test Count", False, "number"),
    ]
    
    rows = []
    for metric_key, metric_label, lower_is_better, format_type in metrics:
        values = {}
        for kpi in kpi_cards:
            val = getattr(kpi, metric_key, None)
            values[kpi.table_type] = val
        
        # Find winner
        valid_values = [(tt, v) for tt, v in values.items() if v is not None]
        winner = None
        if valid_values:
            if lower_is_better:
                winner = min(valid_values, key=lambda x: x[1])[0]
            else:
                winner = max(valid_values, key=lambda x: x[1])[0]
        
        rows.append(ComparisonRow(
            metric=metric_key,
            metric_label=metric_label,
            values=values,
            winner=winner,
            lower_is_better=lower_is_better,
            format_type=format_type
        ))
    
    return ComparisonTable(columns=columns, rows=rows)


@router.get("/table-types/recommendations", response_model=RecommendationsResponse)
async def get_recommendations() -> RecommendationsResponse:
    """
    Get workload-based recommendations for table types.
    
    Analyzes performance data and recommends the best table type
    for different workload patterns (OLTP, Analytics, Real-time, etc.)
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _prefix()
    
    # Fetch summary data
    query = f"""
    SELECT
        TABLE_TYPE,
        AVG_QPS,
        AVG_P95_MS,
        AVG_ERROR_RATE,
        CREDITS_PER_1K_OPS
    FROM {prefix}.DT_TABLE_TYPE_SUMMARY
    """
    
    rows = await pool.execute_query(query)
    
    if not rows:
        return RecommendationsResponse(recommendations=[])
    
    # Build metrics list for recommendation engine
    table_type_metrics = []
    for row in rows:
        table_type, avg_qps, avg_p95_ms, avg_error_rate, credits_per_1k_ops = row
        table_type_metrics.append({
            "table_type": str(table_type),
            "avg_qps": float(avg_qps) if avg_qps else 0,
            "avg_p95_ms": float(avg_p95_ms) if avg_p95_ms else 0,
            "avg_error_rate": float(avg_error_rate) if avg_error_rate is not None else 0,
            "credits_per_1k_ops": float(credits_per_1k_ops) if credits_per_1k_ops else None,
        })
    
    # Generate recommendations
    recommendations = generate_all_recommendations(table_type_metrics, CREDIT_COST_USD)
    
    return RecommendationsResponse(recommendations=recommendations)


@router.get("/table-types/chart/{chart_type}", response_model=ChartDataResponse)
async def get_table_type_chart(
    chart_type: str
) -> ChartDataResponse:
    """
    Get Chart.js formatted data for table type comparisons.
    
    Supported chart types: qps, latency, cost, test_count
    """
    # Fetch KPI data
    summary = await get_table_type_summary()
    kpi_cards = summary.kpi_cards
    
    if chart_type == "qps":
        return build_qps_comparison_chart(kpi_cards)
    elif chart_type == "latency":
        return build_latency_comparison_chart(kpi_cards)
    elif chart_type == "cost":
        return build_cost_comparison_chart(kpi_cards)
    elif chart_type == "test_count":
        return build_test_count_chart(kpi_cards)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown chart type: {chart_type}. Supported: qps, latency, cost, test_count"
        )


@router.get("/table-types/scatter/{metric}")
async def get_table_type_scatter(
    metric: str,
    limit: int = Query(500, ge=1, le=2000, description="Maximum points per table type")
) -> dict:
    """
    Get scatter plot data for individual tests grouped by table type.
    
    Supported metrics: qps, p95_latency
    Returns individual test data points for scatter visualization with jitter.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _prefix()
    
    metric_col = {
        "qps": "QPS",
        "p95_latency": "P95_LATENCY_MS",
        "p50_latency": "P50_LATENCY_MS",
        "p99_latency": "P99_LATENCY_MS",
    }.get(metric.lower(), "QPS")
    
    query = f"""
    SELECT 
        TABLE_TYPE,
        TEST_ID,
        {metric_col} as METRIC_VALUE,
        START_TIME
    FROM {prefix}.V_TEMPLATE_RUNS
    WHERE {metric_col} IS NOT NULL
    ORDER BY TABLE_TYPE, START_TIME DESC
    """
    
    rows = await pool.execute_query(query)
    
    datasets = {}
    table_type_colors = {
        'STANDARD': {'bg': 'rgba(59, 130, 246, 0.6)', 'border': 'rgb(59, 130, 246)'},
        'HYBRID': {'bg': 'rgba(16, 185, 129, 0.6)', 'border': 'rgb(16, 185, 129)'},
        'INTERACTIVE': {'bg': 'rgba(249, 115, 22, 0.6)', 'border': 'rgb(249, 115, 22)'},
        'DYNAMIC': {'bg': 'rgba(139, 92, 246, 0.6)', 'border': 'rgb(139, 92, 246)'},
        'POSTGRES': {'bg': 'rgba(236, 72, 153, 0.6)', 'border': 'rgb(236, 72, 153)'},
    }
    default_color = {'bg': 'rgba(107, 114, 128, 0.6)', 'border': 'rgb(107, 114, 128)'}
    
    for row in rows:
        table_type, test_id, metric_value, start_time = row
        tt = str(table_type).upper()
        
        if tt not in datasets:
            datasets[tt] = {
                'label': tt,
                'data': [],
                'backgroundColor': table_type_colors.get(tt, default_color)['bg'],
                'borderColor': table_type_colors.get(tt, default_color)['border'],
            }
        
        if len(datasets[tt]['data']) < limit:
            datasets[tt]['data'].append({
                'y': float(metric_value) if metric_value else 0,
                'test_id': str(test_id),
                'start_time': str(start_time) if start_time else None,
            })
    
    return {
        'metric': metric,
        'datasets': list(datasets.values()),
        'table_types': list(datasets.keys()),
    }


# =============================================================================
# Template Analysis Endpoints
# =============================================================================

@router.get("/templates", response_model=TemplateListResponse)
async def get_template_list(
    table_type: Optional[str] = Query(None, description="Filter by table type"),
    sort_by: str = Query("last_run", description="Sort field: last_run, total_runs, avg_qps, avg_p95_ms"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> TemplateListResponse:
    """
    Get list of templates with summary statistics.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _prefix()
    
    query, params = get_template_list_query(table_type, sort_by, limit, offset)
    query = query.replace("DT_TEMPLATE_STATISTICS", f"{prefix}.DT_TEMPLATE_STATISTICS")
    
    rows = await pool.execute_query(query, params=params)
    
    templates = []
    for row in rows:
        (
            template_id, template_name, tt, warehouse_size, load_mode,
            total_runs, last_run, avg_qps, avg_p95_ms, stability_badge,
            credits_per_1k_ops
        ) = row
        
        templates.append(TemplateSummary(
            template_id=str(template_id),
            template_name=str(template_name) if template_name else str(template_id),
            table_type=str(tt) if tt else "UNKNOWN",
            warehouse_size=str(warehouse_size) if warehouse_size else None,
            load_mode=str(load_mode) if load_mode else None,
            total_runs=int(total_runs or 0),
            last_run=last_run,
            avg_qps=float(avg_qps) if avg_qps else None,
            avg_p95_ms=float(avg_p95_ms) if avg_p95_ms else None,
            stability_badge=str(stability_badge) if stability_badge else "unknown",
            cost_per_1k_ops_usd=float(credits_per_1k_ops) * CREDIT_COST_USD if credits_per_1k_ops else None
        ))
    
    # Get total count
    count_query = f"""
    SELECT COUNT(*) FROM {prefix}.DT_TEMPLATE_STATISTICS
    {"WHERE TABLE_TYPE = ?" if table_type else ""}
    """
    count_params = [table_type] if table_type else []
    count_rows = await pool.execute_query(count_query, params=count_params)
    total_count = int(count_rows[0][0]) if count_rows else 0
    
    return TemplateListResponse(templates=templates, total_count=total_count)


@router.get("/templates/{template_id}", response_model=TemplateStatisticsResponse)
async def get_template_statistics(template_id: str) -> TemplateStatisticsResponse:
    """
    Get detailed statistics for a specific template.
    
    Uses full schema from DT_TEMPLATE_STATISTICS with all latency percentile stats.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _prefix()
    
    # Only select columns that actually exist in DT_TEMPLATE_STATISTICS
    query = f"""
    SELECT
        TEMPLATE_ID, TEMPLATE_NAME, TABLE_TYPE, WAREHOUSE_SIZE, LOAD_MODE,
        TOTAL_RUNS, RECENT_RUNS,
        AVG_QPS, STDDEV_QPS, MIN_QPS, MAX_QPS, MEDIAN_QPS,
        AVG_P50_MS, STDDEV_P50_MS,
        AVG_P95_MS, STDDEV_P95_MS, MIN_P95_MS, MAX_P95_MS,
        AVG_P99_MS,
        AVG_ERROR_RATE, MAX_ERROR_RATE,
        TOTAL_CREDITS, AVG_CREDITS_PER_RUN, CREDITS_PER_1K_OPS,
        RECENT_AVG_QPS, RECENT_AVG_P95_MS,
        FIRST_RUN, LAST_RUN,
        CV_QPS, CV_P95, QPS_TREND_PCT, STABILITY_BADGE
    FROM {prefix}.DT_TEMPLATE_STATISTICS
    WHERE TEMPLATE_ID = ?
    """
    
    rows = await pool.execute_query(query, params=[template_id])
    
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template not found: {template_id}"
        )
    
    row = rows[0]
    # Unpack row - order must match SELECT columns above
    (
        tid, tname, tt, wh_size, load_mode,
        total_runs, recent_runs,
        avg_qps, stddev_qps, min_qps, max_qps, median_qps,
        avg_p50, stddev_p50,
        avg_p95, stddev_p95, min_p95, max_p95,
        avg_p99,
        avg_error, max_error,
        total_credits, avg_credits, credits_per_1k,
        recent_qps, recent_p95,
        first_run, last_run,
        cv_qps, cv_p95, qps_trend_pct, stability_badge
    ) = row
    
    # Build response
    def _safe_float(v):
        return float(v) if v is not None else None
    
    qps_stats = MetricStats(
        avg=_safe_float(avg_qps),
        min=_safe_float(min_qps),
        max=_safe_float(max_qps),
        median=_safe_float(median_qps),
        stddev=_safe_float(stddev_qps),
        cv=_safe_float(cv_qps)
    )
    
    p50_stats = MetricStats(
        avg=_safe_float(avg_p50),
        stddev=_safe_float(stddev_p50)
    )
    
    p95_stats = MetricStats(
        avg=_safe_float(avg_p95),
        min=_safe_float(min_p95),
        max=_safe_float(max_p95),
        stddev=_safe_float(stddev_p95),
        cv=_safe_float(cv_p95)
    )
    
    p99_stats = MetricStats(
        avg=_safe_float(avg_p99)
    )
    
    error_stats = MetricStats(
        avg=_safe_float(avg_error),
        max=_safe_float(max_error)
    )
    
    # Calculate USD costs
    total_cost_usd = float(total_credits or 0) * CREDIT_COST_USD
    avg_cost_usd = float(avg_credits or 0) * CREDIT_COST_USD
    cost_per_1k_usd = float(credits_per_1k or 0) * CREDIT_COST_USD if credits_per_1k else None
    
    cost_stats = CostStats(
        total_credits=float(total_credits or 0),
        avg_credits_per_run=float(avg_credits or 0),
        credits_per_1k_ops=_safe_float(credits_per_1k),
        total_cost_usd=total_cost_usd,
        avg_cost_per_run_usd=avg_cost_usd,
        cost_per_1k_ops_usd=cost_per_1k_usd
    )
    
    # Determine trend direction
    trend_direction = None
    if qps_trend_pct is not None:
        if qps_trend_pct > 5:
            trend_direction = "improving"
        elif qps_trend_pct < -5:
            trend_direction = "degrading"
        else:
            trend_direction = "stable"
    
    stability = StabilityMetrics(
        cv_qps=_safe_float(cv_qps),
        cv_p95=_safe_float(cv_p95),
        badge=str(stability_badge) if stability_badge else "unknown",
        trend_direction=trend_direction,
        trend_pct=_safe_float(qps_trend_pct)
    )
    
    return TemplateStatisticsResponse(
        template_id=str(tid),
        template_name=str(tname) if tname else str(tid),
        table_type=str(tt) if tt else "UNKNOWN",
        warehouse_size=str(wh_size) if wh_size else None,
        load_mode=str(load_mode) if load_mode else None,
        total_runs=int(total_runs or 0),
        recent_runs=int(recent_runs or 0),
        qps_stats=qps_stats,
        p50_stats=p50_stats,
        p95_stats=p95_stats,
        p99_stats=p99_stats,
        error_stats=error_stats,
        cost_stats=cost_stats,
        stability=stability,
        outliers=[],  # Would need separate query to detect
        badges=[]  # Will be assigned by badge logic
    )


@router.get("/templates/{template_id}/runs", response_model=TemplateRunsResponse)
async def get_template_runs(
    template_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("start_time"),
    sort_order: str = Query("desc"),
) -> TemplateRunsResponse:
    """
    Get historical runs for a template.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _prefix()
    
    # Get runs
    order = "DESC" if sort_order.lower() == "desc" else "ASC"
    sort_cols = {
        "start_time": f"START_TIME {order}",
        "qps": f"QPS {order} NULLS LAST",
        "p95": f"P95_LATENCY_MS {order} NULLS LAST",
    }
    order_by = sort_cols.get(sort_by, f"START_TIME {order}")
    
    query = f"""
    SELECT
        TEST_ID, START_TIME, DURATION_SECONDS, CONCURRENT_CONNECTIONS,
        QPS, P50_LATENCY_MS, P95_LATENCY_MS, P99_LATENCY_MS,
        ERROR_RATE, ESTIMATED_CREDITS, TOTAL_OPERATIONS
    FROM {prefix}.V_TEMPLATE_RUNS
    WHERE TEMPLATE_ID = ?
    ORDER BY {order_by}
    LIMIT ? OFFSET ?
    """
    
    rows = await pool.execute_query(query, params=[template_id, limit, offset])
    
    runs = []
    for row in rows:
        (
            test_id, start_time, duration, concurrency,
            qps, p50, p95, p99,
            error_rate, credits, total_ops
        ) = row
        
        # Calculate credits per 1k ops if we have both values
        credits_per_1k = None
        if credits and total_ops and total_ops > 0:
            credits_per_1k = (float(credits) / float(total_ops)) * 1000
        
        runs.append(TemplateRun(
            test_id=str(test_id),
            start_time=start_time,
            duration_seconds=float(duration) if duration else None,
            concurrent_connections=int(concurrency) if concurrency else None,
            qps=float(qps) if qps else None,
            p50_ms=float(p50) if p50 else None,
            p95_ms=float(p95) if p95 else None,
            p99_ms=float(p99) if p99 else None,
            error_rate=float(error_rate) if error_rate is not None else 0,
            credits_used=float(credits) if credits else None,
            cost_per_1k_ops_usd=credits_per_1k * CREDIT_COST_USD if credits_per_1k else None
        ))
    
    # Get total count
    count_query = f"SELECT COUNT(*) FROM {prefix}.V_TEMPLATE_RUNS WHERE TEMPLATE_ID = ?"
    count_rows = await pool.execute_query(count_query, params=[template_id])
    total_count = int(count_rows[0][0]) if count_rows else 0
    
    return TemplateRunsResponse(
        template_id=template_id,
        runs=runs,
        total_count=total_count,
        page=offset // limit + 1,
        page_size=limit
    )


@router.get("/templates/{template_id}/distribution", response_model=DistributionResponse)
async def get_template_distribution(
    template_id: str,
    metric: str = Query("p95_latency_ms", description="Metric: qps, p50_latency_ms, p95_latency_ms, p99_latency_ms")
) -> DistributionResponse:
    """
    Get histogram distribution data for a template metric.
    """
    import numpy as np
    
    pool = snowflake_pool.get_default_pool()
    prefix = _prefix()
    
    # Map metric to column
    metric_cols = {
        "qps": "QPS",
        "p50_latency_ms": "P50_LATENCY_MS",
        "p95_latency_ms": "P95_LATENCY_MS",
        "p99_latency_ms": "P99_LATENCY_MS",
        "error_rate": "ERROR_RATE",
    }
    column = metric_cols.get(metric.lower(), "P95_LATENCY_MS")
    
    query = f"""
    SELECT {column}
    FROM {prefix}.V_TEMPLATE_RUNS
    WHERE TEMPLATE_ID = ? AND {column} IS NOT NULL
    """
    
    rows = await pool.execute_query(query, params=[template_id])
    
    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No data found for template: {template_id}"
        )
    
    values = [float(row[0]) for row in rows if row[0] is not None]
    
    if not values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No valid values for metric: {metric}"
        )
    
    # Calculate histogram
    arr = np.array(values)
    counts, bin_edges = np.histogram(arr, bins='auto')
    
    return DistributionResponse(
        template_id=template_id,
        metric=metric,
        bins=bin_edges.tolist(),
        counts=counts.tolist(),
        mean=float(np.mean(arr)),
        std_dev=float(np.std(arr)),
        min_val=float(np.min(arr)),
        max_val=float(np.max(arr)),
        distribution_type="unknown"  # Would need proper analysis
    )


@router.get("/templates/{template_id}/scatter", response_model=ScatterResponse)
async def get_template_scatter(
    template_id: str,
    x_metric: str = Query("duration_seconds", description="X-axis metric"),
    y_metric: str = Query("qps", description="Y-axis metric"),
) -> ScatterResponse:
    """
    Get scatter plot data for two metrics.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _prefix()
    
    # Map metrics
    metric_cols = {
        "duration_seconds": "DURATION_SECONDS",
        "duration": "DURATION_SECONDS",
        "qps": "QPS",
        "p50": "P50_LATENCY_MS",
        "p95": "P95_LATENCY_MS",
        "p99": "P99_LATENCY_MS",
        "error_rate": "ERROR_RATE",
        "credits": "ESTIMATED_CREDITS",
        "estimated_credits": "ESTIMATED_CREDITS",
        "total_ops": "TOTAL_OPERATIONS",
        "total_operations": "TOTAL_OPERATIONS",
    }
    
    x_col = metric_cols.get(x_metric.lower(), "DURATION_SECONDS")
    y_col = metric_cols.get(y_metric.lower(), "QPS")
    
    query = f"""
    SELECT TEST_ID, START_TIME, {x_col}, {y_col}
    FROM {prefix}.V_TEMPLATE_RUNS
    WHERE TEMPLATE_ID = ? AND {x_col} IS NOT NULL AND {y_col} IS NOT NULL
    ORDER BY START_TIME
    """
    
    rows = await pool.execute_query(query, params=[template_id])
    
    points = []
    for row in rows:
        test_id, start_time, x_val, y_val = row
        if x_val is not None and y_val is not None:
            points.append(ScatterPoint(
                x=float(x_val),
                y=float(y_val),
                test_id=str(test_id),
                label=str(start_time.date()) if start_time else str(test_id)
            ))
    
    # Calculate correlation
    correlation = None
    if len(points) >= 2:
        import numpy as np
        import math
        x_vals = [p.x for p in points]
        y_vals = [p.y for p in points]
        try:
            with np.errstate(divide='ignore', invalid='ignore'):
                corr_val = float(np.corrcoef(x_vals, y_vals)[0, 1])
            if not math.isnan(corr_val) and not math.isinf(corr_val):
                correlation = corr_val
        except Exception:
            pass
    
    return ScatterResponse(
        template_id=template_id,
        x_metric=x_metric,
        y_metric=y_metric,
        x_label=x_metric.replace("_", " ").title(),
        y_label=y_metric.replace("_", " ").title(),
        data=points,
        correlation=correlation
    )


# =============================================================================
# Cost Analysis Endpoints
# =============================================================================

@router.get("/costs/daily", response_model=DailyCostResponse)
async def get_daily_costs(
    start_date: Optional[date] = Query(None),
    end_date: Optional[date] = Query(None),
    table_type: Optional[str] = Query(None),
) -> DailyCostResponse:
    """
    Get daily cost rollup data.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _prefix()
    
    conditions = []
    params = []
    
    if start_date:
        conditions.append("RUN_DATE >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("RUN_DATE <= ?")
        params.append(end_date)
    if table_type:
        conditions.append("TABLE_TYPE = ?")
        params.append(table_type)
    
    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)
    
    query = f"""
    SELECT
        RUN_DATE, TABLE_TYPE, WAREHOUSE_SIZE,
        TEST_COUNT, TOTAL_CREDITS, TOTAL_OPERATIONS,
        CREDITS_PER_1K_OPS, AVG_QPS
    FROM {prefix}.DT_DAILY_COST_ROLLUP
    {where_clause}
    ORDER BY RUN_DATE DESC, TABLE_TYPE
    """
    
    rows = await pool.execute_query(query, params=params)
    
    data = []
    total_credits = 0.0
    total_tests = 0
    total_ops = 0
    
    for row in rows:
        (
            run_date, tt, wh_size,
            test_count, credits, operations,
            credits_per_1k, avg_qps
        ) = row
        
        credits_val = float(credits or 0)
        total_credits += credits_val
        total_tests += int(test_count or 0)
        total_ops += int(operations or 0)
        
        data.append(DailyCostEntry(
            run_date=run_date,
            table_type=str(tt) if tt else "UNKNOWN",
            warehouse_size=str(wh_size) if wh_size else None,
            test_count=int(test_count or 0),
            total_credits=credits_val,
            total_cost_usd=credits_val * CREDIT_COST_USD,
            total_operations=int(operations or 0),
            credits_per_1k_ops=float(credits_per_1k) if credits_per_1k else None,
            avg_qps=float(avg_qps) if avg_qps else None
        ))
    
    totals = CostTotals(
        total_credits=total_credits,
        total_cost_usd=total_credits * CREDIT_COST_USD,
        total_tests=total_tests,
        total_operations=total_ops,
        avg_credits_per_1k_ops=(total_credits / total_ops * 1000) if total_ops > 0 else None
    )
    
    return DailyCostResponse(data=data, totals=totals)
