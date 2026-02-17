"""
Dashboard Aggregations - Query builders for dynamic tables.

These queries use the full-fidelity schema from sql/schema/dashboard_tables.sql.
Deploy the SQL schema to get all columns available.
"""

from typing import Optional
from datetime import date


# =============================================================================
# SQL Queries for Dynamic Tables
# =============================================================================

def get_table_type_summary_query() -> str:
    """Query to fetch table type summary from dynamic table.
    
    Uses full schema from DT_TABLE_TYPE_SUMMARY with all latency percentile stats.
    """
    return """
    SELECT
        TABLE_TYPE,
        TEST_COUNT,
        UNIQUE_TEMPLATES,
        AVG_QPS,
        MIN_QPS,
        MAX_QPS,
        MEDIAN_QPS,
        P95_QPS,
        STDDEV_QPS,
        AVG_P50_MS,
        MIN_P50_MS,
        MAX_P50_MS,
        MEDIAN_P50_MS,
        AVG_P95_MS,
        MIN_P95_MS,
        MAX_P95_MS,
        MEDIAN_P95_MS,
        AVG_P99_MS,
        MIN_P99_MS,
        MAX_P99_MS,
        MEDIAN_P99_MS,
        AVG_ERROR_RATE,
        MAX_ERROR_RATE,
        TOTAL_FAILED_OPS,
        TOTAL_CREDITS,
        AVG_CREDITS_PER_TEST,
        CREDITS_PER_1K_OPS,
        TOTAL_OPERATIONS,
        TOTAL_READ_OPS,
        TOTAL_WRITE_OPS,
        EARLIEST_TEST,
        LATEST_TEST,
        REFRESHED_AT
    FROM DT_TABLE_TYPE_SUMMARY
    ORDER BY TEST_COUNT DESC
    """


def get_template_list_query(
    table_type: Optional[str] = None,
    sort_by: str = "last_run",
    limit: int = 50,
    offset: int = 0
) -> tuple[str, list]:
    """Query to fetch template list from dynamic table."""
    
    where_clause = ""
    params = []
    
    if table_type:
        where_clause = "WHERE TABLE_TYPE = ?"
        params.append(table_type)
    
    sort_columns = {
        "last_run": "LAST_RUN DESC",
        "total_runs": "TOTAL_RUNS DESC",
        "avg_qps": "AVG_QPS DESC NULLS LAST",
        "avg_p95_ms": "AVG_P95_MS ASC NULLS LAST",
        "template_name": "TEMPLATE_NAME ASC",
    }
    order_by = sort_columns.get(sort_by, "LAST_RUN DESC")
    
    params.extend([limit, offset])
    
    query = f"""
    SELECT
        TEMPLATE_ID,
        TEMPLATE_NAME,
        TABLE_TYPE,
        WAREHOUSE_SIZE,
        LOAD_MODE,
        TOTAL_RUNS,
        LAST_RUN,
        AVG_QPS,
        AVG_P95_MS,
        STABILITY_BADGE,
        CREDITS_PER_1K_OPS
    FROM DT_TEMPLATE_STATISTICS
    {where_clause}
    ORDER BY {order_by}
    LIMIT ? OFFSET ?
    """
    
    return query, params


def get_template_statistics_query(template_id: str) -> tuple[str, dict]:
    """Query to fetch detailed template statistics.
    
    Uses full schema from DT_TEMPLATE_STATISTICS with all latency percentile stats.
    """
    
    query = """
    SELECT
        TEMPLATE_ID,
        TEMPLATE_NAME,
        TABLE_TYPE,
        WAREHOUSE_SIZE,
        LOAD_MODE,
        TOTAL_RUNS,
        RECENT_RUNS,
        
        -- QPS stats
        AVG_QPS,
        STDDEV_QPS,
        MIN_QPS,
        MAX_QPS,
        MEDIAN_QPS,
        
        -- p50 stats (full)
        AVG_P50_MS,
        STDDEV_P50_MS,
        MIN_P50_MS,
        MAX_P50_MS,
        MEDIAN_P50_MS,
        
        -- p95 stats (full)
        AVG_P95_MS,
        STDDEV_P95_MS,
        MIN_P95_MS,
        MAX_P95_MS,
        MEDIAN_P95_MS,
        
        -- p99 stats (full)
        AVG_P99_MS,
        STDDEV_P99_MS,
        MIN_P99_MS,
        MAX_P99_MS,
        
        -- Error stats
        AVG_ERROR_RATE,
        MAX_ERROR_RATE,
        
        -- Cost stats
        TOTAL_CREDITS,
        AVG_CREDITS_PER_RUN,
        CREDITS_PER_1K_OPS,
        
        -- Recent stats
        RECENT_AVG_QPS,
        RECENT_AVG_P95_MS,
        
        -- Time range
        FIRST_RUN,
        LAST_RUN,
        
        -- Stability metrics
        CV_QPS,
        CV_P95,
        QPS_TREND_PCT,
        STABILITY_BADGE
        
    FROM DT_TEMPLATE_STATISTICS
    WHERE TEMPLATE_ID = %(template_id)s
    """
    
    return query, {"template_id": template_id}


def get_template_runs_query(
    template_id: str,
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "start_time",
    sort_order: str = "desc"
) -> tuple[str, dict]:
    """Query to fetch all runs for a template.
    
    Uses V_TEMPLATE_RUNS view which includes estimated_credits and credits_per_1k_ops.
    """
    
    # Validate sort order
    order = "DESC" if sort_order.lower() == "desc" else "ASC"
    
    # Map sort field to column
    sort_columns = {
        "start_time": f"START_TIME {order}",
        "qps": f"QPS {order} NULLS LAST",
        "p95": f"P95_LATENCY_MS {order} NULLS LAST",
        "error_rate": f"ERROR_RATE {order}",
    }
    order_by = sort_columns.get(sort_by, f"START_TIME {order}")
    
    query = f"""
    SELECT
        TEST_ID,
        START_TIME,
        DURATION_SECONDS,
        CONCURRENT_CONNECTIONS,
        QPS,
        P50_LATENCY_MS,
        P95_LATENCY_MS,
        P99_LATENCY_MS,
        ERROR_RATE,
        ESTIMATED_CREDITS,
        CREDITS_PER_1K_OPS,
        LOAD_MODE,
        RECENCY_RANK
    FROM V_TEMPLATE_RUNS
    WHERE TEMPLATE_ID = %(template_id)s
    ORDER BY {order_by}
    LIMIT %(limit)s OFFSET %(offset)s
    """
    
    return query, {"template_id": template_id, "limit": limit, "offset": offset}


def get_template_runs_count_query(template_id: str) -> tuple[str, dict]:
    """Query to count total runs for a template."""
    
    query = """
    SELECT COUNT(*) AS total_count
    FROM V_TEMPLATE_RUNS
    WHERE TEMPLATE_ID = %(template_id)s
    """
    
    return query, {"template_id": template_id}


def get_template_distribution_query(
    template_id: str,
    metric: str = "P95_LATENCY_MS"
) -> tuple[str, dict]:
    """Query to fetch metric values for histogram distribution."""
    
    # Validate metric column
    valid_metrics = {
        "p50_latency_ms": "P50_LATENCY_MS",
        "p95_latency_ms": "P95_LATENCY_MS",
        "p99_latency_ms": "P99_LATENCY_MS",
        "qps": "QPS",
        "error_rate": "ERROR_RATE",
    }
    column = valid_metrics.get(metric.lower(), "P95_LATENCY_MS")
    
    query = f"""
    SELECT {column} AS value
    FROM V_TEMPLATE_RUNS
    WHERE TEMPLATE_ID = %(template_id)s
      AND {column} IS NOT NULL
    ORDER BY START_TIME
    """
    
    return query, {"template_id": template_id}


def get_template_scatter_query(
    template_id: str,
    x_metric: str = "duration_seconds",
    y_metric: str = "qps"
) -> tuple[str, dict]:
    """Query to fetch scatter plot data.
    
    Uses V_TEMPLATE_RUNS which has estimated_credits and credits_per_1k_ops.
    """
    
    # Validate and map metrics
    metric_columns = {
        "duration_seconds": "DURATION_SECONDS",
        "duration": "DURATION_SECONDS",
        "qps": "QPS",
        "p50": "P50_LATENCY_MS",
        "p50_latency_ms": "P50_LATENCY_MS",
        "p95": "P95_LATENCY_MS",
        "p95_latency_ms": "P95_LATENCY_MS",
        "p99": "P99_LATENCY_MS",
        "p99_latency_ms": "P99_LATENCY_MS",
        "concurrency": "CONCURRENT_CONNECTIONS",
        "concurrent_connections": "CONCURRENT_CONNECTIONS",
        "error_rate": "ERROR_RATE",
        "credits": "ESTIMATED_CREDITS",
        "estimated_credits": "ESTIMATED_CREDITS",
        "cost": "CREDITS_PER_1K_OPS",
        "credits_per_1k_ops": "CREDITS_PER_1K_OPS",
    }
    
    x_col = metric_columns.get(x_metric.lower(), "DURATION_SECONDS")
    y_col = metric_columns.get(y_metric.lower(), "QPS")
    
    query = f"""
    SELECT
        TEST_ID,
        START_TIME,
        {x_col} AS x_value,
        {y_col} AS y_value
    FROM V_TEMPLATE_RUNS
    WHERE TEMPLATE_ID = %(template_id)s
      AND {x_col} IS NOT NULL
      AND {y_col} IS NOT NULL
    ORDER BY START_TIME
    """
    
    return query, {"template_id": template_id}


def get_daily_cost_query(
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    table_type: Optional[str] = None
) -> tuple[str, dict]:
    """Query to fetch daily cost rollup."""
    
    conditions = []
    params = {}
    
    if start_date:
        conditions.append("RUN_DATE >= %(start_date)s")
        params["start_date"] = start_date
    
    if end_date:
        conditions.append("RUN_DATE <= %(end_date)s")
        params["end_date"] = end_date
    
    if table_type:
        conditions.append("TABLE_TYPE = %(table_type)s")
        params["table_type"] = table_type
    
    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)
    
    query = f"""
    SELECT
        RUN_DATE,
        TABLE_TYPE,
        WAREHOUSE_SIZE,
        TEST_COUNT,
        TOTAL_CREDITS,
        AVG_CREDITS_PER_TEST,
        TOTAL_OPERATIONS,
        CREDITS_PER_1K_OPS,
        AVG_QPS,
        AVG_P95_MS,
        TOTAL_TEST_DURATION_SECONDS
    FROM DT_DAILY_COST_ROLLUP
    {where_clause}
    ORDER BY RUN_DATE DESC, TABLE_TYPE
    """
    
    return query, params


def get_template_time_series_query(template_id: str) -> tuple[str, dict]:
    """Query to fetch time series data for trend analysis.
    
    Uses V_TEMPLATE_RUNS which has credits_per_1k_ops pre-calculated.
    """
    
    query = """
    SELECT
        DATE_TRUNC('DAY', START_TIME)::DATE AS run_date,
        AVG(QPS) AS avg_qps,
        AVG(P95_LATENCY_MS) AS avg_p95_ms,
        AVG(CREDITS_PER_1K_OPS) AS avg_credits_per_1k_ops,
        COUNT(*) AS test_count
    FROM V_TEMPLATE_RUNS
    WHERE TEMPLATE_ID = %(template_id)s
    GROUP BY DATE_TRUNC('DAY', START_TIME)::DATE
    ORDER BY run_date
    """
    
    return query, {"template_id": template_id}
