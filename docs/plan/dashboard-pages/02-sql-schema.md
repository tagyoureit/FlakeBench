# Dashboard Pages - SQL Schema

**Parent:** [00-overview.md](00-overview.md)

---

## 1. Dynamic Tables Overview

We need three dynamic tables to pre-aggregate data for dashboard performance:

| Dynamic Table | Purpose | Refresh Trigger |
|---------------|---------|-----------------|
| `DT_TABLE_TYPE_SUMMARY` | Aggregate metrics per table type | Downstream of `TEST_RESULTS` |
| `DT_TEMPLATE_STATISTICS` | Rolling stats per template | Downstream of `TEST_RESULTS` |
| `DT_DAILY_COST_ROLLUP` | Daily cost tracking | Downstream of `TEST_RESULTS` |

**Refresh Strategy:** All use `DOWNSTREAM` mode, meaning they refresh automatically when `TEST_RESULTS` receives new data. No scheduled refresh needed.

**Target Lag:** 1 minute (acceptable for dashboard use case)

---

## 2. Dynamic Table: DT_TABLE_TYPE_SUMMARY

### Purpose
Provides aggregate performance metrics for each table type, enabling the "which table type is best?" comparison view.

### SQL Definition

```sql
-- =============================================================================
-- DT_TABLE_TYPE_SUMMARY: Aggregate metrics per table type for dashboard
-- =============================================================================
-- Refresh: Downstream of TEST_RESULTS (auto-refresh when new tests complete)
-- Target Lag: 1 minute
-- =============================================================================

CREATE OR ALTER DYNAMIC TABLE FLAKEBENCH.TEST_RESULTS.DT_TABLE_TYPE_SUMMARY
    TARGET_LAG = '1 minute'
    WAREHOUSE = FLAKEBENCH_WH
AS
SELECT
    -- Grouping
    TABLE_TYPE,
    
    -- Test counts
    COUNT(*) AS test_count,
    COUNT(DISTINCT TEST_CONFIG:template_id::VARCHAR) AS unique_templates,
    
    -- Throughput metrics
    AVG(QPS) AS avg_qps,
    MIN(QPS) AS min_qps,
    MAX(QPS) AS max_qps,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY QPS) AS median_qps,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY QPS) AS p95_qps,
    STDDEV(QPS) AS stddev_qps,
    
    -- Latency metrics (p50)
    AVG(P50_LATENCY_MS) AS avg_p50_ms,
    MIN(P50_LATENCY_MS) AS min_p50_ms,
    MAX(P50_LATENCY_MS) AS max_p50_ms,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY P50_LATENCY_MS) AS median_p50_ms,
    
    -- Latency metrics (p95)
    AVG(P95_LATENCY_MS) AS avg_p95_ms,
    MIN(P95_LATENCY_MS) AS min_p95_ms,
    MAX(P95_LATENCY_MS) AS max_p95_ms,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY P95_LATENCY_MS) AS median_p95_ms,
    
    -- Latency metrics (p99)
    AVG(P99_LATENCY_MS) AS avg_p99_ms,
    MIN(P99_LATENCY_MS) AS min_p99_ms,
    MAX(P99_LATENCY_MS) AS max_p99_ms,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY P99_LATENCY_MS) AS median_p99_ms,
    
    -- Error metrics
    AVG(ERROR_RATE) AS avg_error_rate,
    MAX(ERROR_RATE) AS max_error_rate,
    SUM(FAILED_OPERATIONS) AS total_failed_ops,
    
    -- Cost metrics
    SUM(WAREHOUSE_CREDITS_USED) AS total_credits,
    AVG(WAREHOUSE_CREDITS_USED) AS avg_credits_per_test,
    
    -- Cost efficiency (credits per 1K operations)
    CASE 
        WHEN SUM(TOTAL_OPERATIONS) > 0 
        THEN (SUM(WAREHOUSE_CREDITS_USED) / SUM(TOTAL_OPERATIONS)) * 1000
        ELSE NULL 
    END AS credits_per_1k_ops,
    
    -- Operations breakdown
    SUM(TOTAL_OPERATIONS) AS total_operations,
    SUM(READ_OPERATIONS) AS total_read_ops,
    SUM(WRITE_OPERATIONS) AS total_write_ops,
    
    -- Time range
    MIN(START_TIME) AS earliest_test,
    MAX(START_TIME) AS latest_test,
    
    -- Last refresh timestamp
    CURRENT_TIMESTAMP() AS refreshed_at

FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
WHERE 
    STATUS = 'COMPLETED'
    AND TABLE_TYPE IS NOT NULL
    AND QPS > 0  -- Exclude failed/incomplete tests
GROUP BY TABLE_TYPE;

-- Add comment
COMMENT ON DYNAMIC TABLE FLAKEBENCH.TEST_RESULTS.DT_TABLE_TYPE_SUMMARY IS 
'Aggregate performance metrics by table type for dashboard comparison view. Refreshes automatically when TEST_RESULTS changes.';
```

### Expected Output Shape

| TABLE_TYPE | test_count | avg_qps | avg_p95_ms | credits_per_1k_ops | ... |
|------------|------------|---------|------------|-------------------|-----|
| STANDARD | 127 | 1200.5 | 48.2 | 0.033 | ... |
| HYBRID | 89 | 2145.3 | 34.2 | 0.023 | ... |
| INTERACTIVE | 34 | 890.1 | 52.1 | 0.067 | ... |
| DYNAMIC | 45 | NULL | 45.0 | 0.010 | ... |
| POSTGRES | 23 | 650.2 | 67.3 | 0.028 | ... |

---

## 3. Dynamic Table: DT_TEMPLATE_STATISTICS

### Purpose
Provides rolling statistics for each template, enabling trend analysis and stability assessment.

### SQL Definition

```sql
-- =============================================================================
-- DT_TEMPLATE_STATISTICS: Rolling stats per template for analysis page
-- =============================================================================
-- Refresh: Downstream of TEST_RESULTS
-- Target Lag: 1 minute
-- =============================================================================

CREATE OR ALTER DYNAMIC TABLE FLAKEBENCH.TEST_RESULTS.DT_TEMPLATE_STATISTICS
    TARGET_LAG = '1 minute'
    WAREHOUSE = FLAKEBENCH_WH
AS
WITH template_tests AS (
    SELECT
        TEST_CONFIG:template_id::VARCHAR AS template_id,
        TEST_CONFIG:scenario:name::VARCHAR AS template_name,
        TABLE_TYPE,
        WAREHOUSE_SIZE,
        TEST_CONFIG:scenario:load_mode::VARCHAR AS load_mode,
        
        -- Core metrics
        QPS,
        P50_LATENCY_MS,
        P95_LATENCY_MS,
        P99_LATENCY_MS,
        ERROR_RATE,
        DURATION_SECONDS,
        CONCURRENT_CONNECTIONS,
        TOTAL_OPERATIONS,
        
        -- Cost
        WAREHOUSE_CREDITS_USED,
        
        -- Timestamps
        START_TIME,
        
        -- For trend calculation (row number by time)
        ROW_NUMBER() OVER (
            PARTITION BY TEST_CONFIG:template_id::VARCHAR 
            ORDER BY START_TIME DESC
        ) AS recency_rank
        
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE 
        STATUS = 'COMPLETED'
        AND TEST_CONFIG:template_id IS NOT NULL
        AND QPS > 0
),

-- Calculate stats per template
template_aggregates AS (
    SELECT
        template_id,
        MAX(template_name) AS template_name,
        MAX(TABLE_TYPE) AS table_type,
        MAX(WAREHOUSE_SIZE) AS warehouse_size,
        MAX(load_mode) AS load_mode,
        
        -- Counts
        COUNT(*) AS total_runs,
        COUNT(CASE WHEN recency_rank <= 10 THEN 1 END) AS recent_runs,
        
        -- QPS stats
        AVG(QPS) AS avg_qps,
        STDDEV(QPS) AS stddev_qps,
        MIN(QPS) AS min_qps,
        MAX(QPS) AS max_qps,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY QPS) AS median_qps,
        
        -- Latency stats (p95)
        AVG(P95_LATENCY_MS) AS avg_p95_ms,
        STDDEV(P95_LATENCY_MS) AS stddev_p95_ms,
        MIN(P95_LATENCY_MS) AS min_p95_ms,
        MAX(P95_LATENCY_MS) AS max_p95_ms,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY P95_LATENCY_MS) AS median_p95_ms,
        
        -- Latency stats (p99)
        AVG(P99_LATENCY_MS) AS avg_p99_ms,
        MIN(P99_LATENCY_MS) AS min_p99_ms,
        MAX(P99_LATENCY_MS) AS max_p99_ms,
        
        -- Error stats
        AVG(ERROR_RATE) AS avg_error_rate,
        MAX(ERROR_RATE) AS max_error_rate,
        
        -- Cost stats
        SUM(WAREHOUSE_CREDITS_USED) AS total_credits,
        AVG(WAREHOUSE_CREDITS_USED) AS avg_credits_per_run,
        
        -- Cost efficiency
        CASE 
            WHEN SUM(TOTAL_OPERATIONS) > 0 
            THEN (SUM(WAREHOUSE_CREDITS_USED) / SUM(TOTAL_OPERATIONS)) * 1000
            ELSE NULL 
        END AS credits_per_1k_ops,
        
        -- Last 10 runs stats (for recent trend)
        AVG(CASE WHEN recency_rank <= 10 THEN QPS END) AS recent_avg_qps,
        AVG(CASE WHEN recency_rank <= 10 THEN P95_LATENCY_MS END) AS recent_avg_p95_ms,
        
        -- Time range
        MIN(START_TIME) AS first_run,
        MAX(START_TIME) AS last_run,
        
        -- Refresh timestamp
        CURRENT_TIMESTAMP() AS refreshed_at
        
    FROM template_tests
    GROUP BY template_id
)

SELECT
    *,
    
    -- Coefficient of Variation (stability indicator)
    CASE WHEN avg_qps > 0 THEN stddev_qps / avg_qps ELSE NULL END AS cv_qps,
    CASE WHEN avg_p95_ms > 0 THEN stddev_p95_ms / avg_p95_ms ELSE NULL END AS cv_p95,
    
    -- Trend indicator (recent vs all-time)
    CASE 
        WHEN avg_qps > 0 AND recent_avg_qps IS NOT NULL 
        THEN ((recent_avg_qps - avg_qps) / avg_qps) * 100
        ELSE NULL 
    END AS qps_trend_pct,
    
    -- Stability badge (based on CV)
    CASE
        WHEN cv_qps IS NULL THEN 'unknown'
        WHEN cv_qps < 0.10 THEN 'very_stable'
        WHEN cv_qps < 0.15 THEN 'stable'
        WHEN cv_qps < 0.25 THEN 'moderate'
        ELSE 'volatile'
    END AS stability_badge

FROM template_aggregates
WHERE total_runs >= 2;  -- Need at least 2 runs for meaningful stats

COMMENT ON DYNAMIC TABLE FLAKEBENCH.TEST_RESULTS.DT_TEMPLATE_STATISTICS IS 
'Rolling statistics per template for trend analysis and stability assessment. Refreshes automatically when TEST_RESULTS changes.';
```

### Expected Output Shape

| template_id | template_name | total_runs | avg_qps | cv_qps | stability_badge | ... |
|-------------|---------------|------------|---------|--------|-----------------|-----|
| afd4d1b6... | oltp_point_lookup | 47 | 2145.3 | 0.082 | stable | ... |
| b7c2e8f1... | range_scan_100k | 32 | 450.2 | 0.156 | moderate | ... |

---

## 4. Dynamic Table: DT_DAILY_COST_ROLLUP

### Purpose
Tracks daily cost consumption by table type and warehouse size for budget analysis.

### SQL Definition

```sql
-- =============================================================================
-- DT_DAILY_COST_ROLLUP: Daily cost tracking for budget analysis
-- =============================================================================
-- Refresh: Downstream of TEST_RESULTS
-- Target Lag: 1 minute
-- =============================================================================

CREATE OR ALTER DYNAMIC TABLE FLAKEBENCH.TEST_RESULTS.DT_DAILY_COST_ROLLUP
    TARGET_LAG = '1 minute'
    WAREHOUSE = FLAKEBENCH_WH
AS
SELECT
    DATE_TRUNC('DAY', START_TIME)::DATE AS run_date,
    TABLE_TYPE,
    WAREHOUSE_SIZE,
    
    -- Test counts
    COUNT(*) AS test_count,
    
    -- Credit consumption
    SUM(WAREHOUSE_CREDITS_USED) AS total_credits,
    AVG(WAREHOUSE_CREDITS_USED) AS avg_credits_per_test,
    
    -- Operations
    SUM(TOTAL_OPERATIONS) AS total_operations,
    
    -- Cost efficiency
    CASE 
        WHEN SUM(TOTAL_OPERATIONS) > 0 
        THEN (SUM(WAREHOUSE_CREDITS_USED) / SUM(TOTAL_OPERATIONS)) * 1000
        ELSE NULL 
    END AS credits_per_1k_ops,
    
    -- Performance summary
    AVG(QPS) AS avg_qps,
    AVG(P95_LATENCY_MS) AS avg_p95_ms,
    
    -- Duration
    SUM(DURATION_SECONDS) AS total_test_duration_seconds,
    
    -- Refresh timestamp
    CURRENT_TIMESTAMP() AS refreshed_at

FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
WHERE 
    STATUS = 'COMPLETED'
    AND START_TIME IS NOT NULL
GROUP BY 
    DATE_TRUNC('DAY', START_TIME)::DATE,
    TABLE_TYPE,
    WAREHOUSE_SIZE;

COMMENT ON DYNAMIC TABLE FLAKEBENCH.TEST_RESULTS.DT_DAILY_COST_ROLLUP IS 
'Daily cost rollup by table type and warehouse size for budget tracking. Refreshes automatically when TEST_RESULTS changes.';
```

---

## 5. Supporting View: V_TEMPLATE_RUNS

### Purpose
Lists all runs for a specific template with enriched fields for the template analysis page.

```sql
-- =============================================================================
-- V_TEMPLATE_RUNS: Detailed run list for template analysis
-- =============================================================================

CREATE OR REPLACE VIEW FLAKEBENCH.TEST_RESULTS.V_TEMPLATE_RUNS AS
SELECT
    TEST_ID,
    RUN_ID,
    TEST_CONFIG:template_id::VARCHAR AS template_id,
    TEST_NAME,
    TABLE_TYPE,
    WAREHOUSE_SIZE,
    STATUS,
    START_TIME,
    DURATION_SECONDS,
    CONCURRENT_CONNECTIONS,
    
    -- Performance
    QPS,
    P50_LATENCY_MS,
    P95_LATENCY_MS,
    P99_LATENCY_MS,
    ERROR_RATE,
    
    -- Operations
    TOTAL_OPERATIONS,
    READ_OPERATIONS,
    WRITE_OPERATIONS,
    FAILED_OPERATIONS,
    
    -- Cost
    WAREHOUSE_CREDITS_USED,
    CASE 
        WHEN TOTAL_OPERATIONS > 0 
        THEN (WAREHOUSE_CREDITS_USED / TOTAL_OPERATIONS) * 1000
        ELSE NULL 
    END AS credits_per_1k_ops,
    
    -- Load mode details
    TEST_CONFIG:scenario:load_mode::VARCHAR AS load_mode,
    TEST_CONFIG:template_config:scaling:mode::VARCHAR AS scale_mode,
    
    -- For outlier detection (will be enriched by API)
    ROW_NUMBER() OVER (
        PARTITION BY TEST_CONFIG:template_id::VARCHAR 
        ORDER BY START_TIME DESC
    ) AS recency_rank

FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
WHERE 
    STATUS = 'COMPLETED'
    AND TEST_CONFIG:template_id IS NOT NULL;

COMMENT ON VIEW FLAKEBENCH.TEST_RESULTS.V_TEMPLATE_RUNS IS 
'Detailed run list per template for analysis page. Use with template_id filter.';
```

---

## 6. Histogram Data Query

For latency distribution histograms, we query `QUERY_EXECUTIONS` (not pre-aggregated):

```sql
-- Query to get latency distribution for a template
-- Called on-demand from API, not pre-materialized

SELECT
    WIDTH_BUCKET(APP_ELAPSED_MS, 0, 200, 20) AS bucket,  -- 20 buckets from 0-200ms
    MIN(APP_ELAPSED_MS) AS bucket_min,
    MAX(APP_ELAPSED_MS) AS bucket_max,
    COUNT(*) AS count
FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS qe
JOIN FLAKEBENCH.TEST_RESULTS.TEST_RESULTS tr 
    ON qe.TEST_ID = tr.TEST_ID
WHERE 
    tr.TEST_CONFIG:template_id::VARCHAR = :template_id
    AND qe.WARMUP = FALSE  -- Exclude warmup
    AND qe.SUCCESS = TRUE  -- Only successful queries
GROUP BY bucket
ORDER BY bucket;
```

---

## 7. Migration Script

```sql
-- =============================================================================
-- Migration: Create Dashboard Dynamic Tables
-- Run this script to set up the dashboard infrastructure
-- =============================================================================

USE DATABASE FLAKEBENCH;
USE SCHEMA TEST_RESULTS;

-- Step 1: Create DT_TABLE_TYPE_SUMMARY
-- [Include full DDL from Section 2]

-- Step 2: Create DT_TEMPLATE_STATISTICS  
-- [Include full DDL from Section 3]

-- Step 3: Create DT_DAILY_COST_ROLLUP
-- [Include full DDL from Section 4]

-- Step 4: Create V_TEMPLATE_RUNS view
-- [Include full DDL from Section 5]

-- Step 5: Verify creation
SHOW DYNAMIC TABLES LIKE 'DT_%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;
SHOW VIEWS LIKE 'V_TEMPLATE%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;

-- Step 6: Initial refresh (optional - will auto-refresh on next TEST_RESULTS insert)
ALTER DYNAMIC TABLE DT_TABLE_TYPE_SUMMARY REFRESH;
ALTER DYNAMIC TABLE DT_TEMPLATE_STATISTICS REFRESH;
ALTER DYNAMIC TABLE DT_DAILY_COST_ROLLUP REFRESH;

-- Step 7: Verify data
SELECT * FROM DT_TABLE_TYPE_SUMMARY;
SELECT COUNT(*) AS template_count FROM DT_TEMPLATE_STATISTICS;
SELECT COUNT(*) AS day_count FROM DT_DAILY_COST_ROLLUP;
```

---

## 8. Cost Considerations

| Dynamic Table | Estimated Size | Refresh Frequency | Credit Impact |
|---------------|----------------|-------------------|---------------|
| DT_TABLE_TYPE_SUMMARY | ~5 rows | Per TEST_RESULTS insert | Minimal |
| DT_TEMPLATE_STATISTICS | ~50 rows | Per TEST_RESULTS insert | Minimal |
| DT_DAILY_COST_ROLLUP | ~500 rows | Per TEST_RESULTS insert | Minimal |

**Total estimated refresh cost:** < 0.01 credits per test run

The dynamic tables are small (< 1000 rows each) and refresh incrementally, so the credit cost is negligible compared to the query performance benefit.

---

**Next:** [03-api-endpoints.md](03-api-endpoints.md) - FastAPI endpoint specifications
