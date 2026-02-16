-- =============================================================================
-- Dashboard Dynamic Tables and Views
-- =============================================================================
-- Purpose: Pre-aggregated data for dashboard pages
-- - DT_TABLE_TYPE_SUMMARY: Aggregate metrics per table type
-- - DT_TEMPLATE_STATISTICS: Rolling stats per template
-- - DT_DAILY_COST_ROLLUP: Daily cost tracking
-- - V_TEMPLATE_RUNS: Detailed run list for template analysis
--
-- Refresh Strategy: All dynamic tables use DOWNSTREAM mode, refreshing
-- automatically when TEST_RESULTS receives new data.
-- =============================================================================

USE DATABASE UNISTORE_BENCHMARK;
USE SCHEMA TEST_RESULTS;

-- =============================================================================
-- DT_TABLE_TYPE_SUMMARY: Aggregate metrics per table type for dashboard
-- =============================================================================
-- Provides KPI cards and comparison table data
-- Refresh: Downstream of TEST_RESULTS (auto-refresh when new tests complete)
-- Target Lag: 1 minute
--
-- Credit Estimation: When WAREHOUSE_CREDITS_USED is NULL, we estimate credits
-- using duration × credits_per_hour based on table type and warehouse size:
-- - STANDARD/HYBRID: Standard warehouse rates (1-512 credits/hr by size)
-- - INTERACTIVE: 0.6x standard rates
-- - POSTGRES: Low rates (0.0356 cr/hr for STANDARD_M default)
-- =============================================================================

CREATE OR ALTER DYNAMIC TABLE DT_TABLE_TYPE_SUMMARY
    TARGET_LAG = '1 minute'
    WAREHOUSE = COMPUTE_WH
AS
WITH test_with_credits AS (
    SELECT
        *,
        COALESCE(
            WAREHOUSE_CREDITS_USED,
            -- Estimate credits if not provided
            CASE 
                -- POSTGRES uses Snowflake Postgres Compute rates (Table 1(i))
                -- Maps warehouse size names to Postgres instance families
                WHEN TABLE_TYPE = 'POSTGRES' THEN 
                    (DURATION_SECONDS / 3600.0) * 
                    CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                        WHEN 'XSMALL' THEN 0.0068    -- BURST_XS
                        WHEN 'X-SMALL' THEN 0.0068
                        WHEN 'SMALL' THEN 0.0136    -- BURST_S
                        WHEN 'MEDIUM' THEN 0.0356   -- STANDARD_M
                        WHEN 'LARGE' THEN 0.0712    -- STANDARD_L
                        WHEN 'XLARGE' THEN 0.1424   -- STANDARD_XL
                        WHEN 'X-LARGE' THEN 0.1424
                        WHEN '2XLARGE' THEN 0.2848  -- STANDARD_2X
                        WHEN '2X-LARGE' THEN 0.2848
                        WHEN '4XLARGE' THEN 0.5696  -- STANDARD_4XL
                        WHEN '4X-LARGE' THEN 0.5696
                        -- Named Postgres instance families
                        WHEN 'STANDARD_M' THEN 0.0356
                        WHEN 'STANDARD_L' THEN 0.0712
                        WHEN 'STANDARD_XL' THEN 0.1424
                        WHEN 'STANDARD_2X' THEN 0.2848
                        WHEN 'STANDARD_4XL' THEN 0.5696
                        WHEN 'STANDARD_8XL' THEN 1.1392
                        WHEN 'HIGHMEM_L' THEN 0.1024
                        WHEN 'HIGHMEM_XL' THEN 0.2048
                        WHEN 'HIGHMEM_2XL' THEN 0.4096
                        WHEN 'BURST_XS' THEN 0.0068
                        WHEN 'BURST_S' THEN 0.0136
                        WHEN 'BURST_M' THEN 0.0272
                        ELSE 0.0356  -- Default to STANDARD_M
                    END
                -- INTERACTIVE uses 60% of standard rates
                WHEN TABLE_TYPE = 'INTERACTIVE' THEN 
                    (DURATION_SECONDS / 3600.0) * 
                    CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                        WHEN 'XSMALL' THEN 0.6 WHEN 'X-SMALL' THEN 0.6
                        WHEN 'SMALL' THEN 1.2
                        WHEN 'MEDIUM' THEN 2.4
                        WHEN 'LARGE' THEN 4.8
                        WHEN 'XLARGE' THEN 9.6 WHEN 'X-LARGE' THEN 9.6
                        WHEN '2XLARGE' THEN 19.2 WHEN '2X-LARGE' THEN 19.2
                        ELSE 2.4  -- Default to MEDIUM
                    END
                -- STANDARD/HYBRID/others use standard warehouse rates
                ELSE 
                    (DURATION_SECONDS / 3600.0) * 
                    CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                        WHEN 'XSMALL' THEN 1 WHEN 'X-SMALL' THEN 1
                        WHEN 'SMALL' THEN 2
                        WHEN 'MEDIUM' THEN 4
                        WHEN 'LARGE' THEN 8
                        WHEN 'XLARGE' THEN 16 WHEN 'X-LARGE' THEN 16
                        WHEN '2XLARGE' THEN 32 WHEN '2X-LARGE' THEN 32
                        WHEN '3XLARGE' THEN 64 WHEN '3X-LARGE' THEN 64
                        WHEN '4XLARGE' THEN 128 WHEN '4X-LARGE' THEN 128
                        ELSE 4  -- Default to MEDIUM
                    END
            END
        ) AS estimated_credits
    FROM TEST_RESULTS
    WHERE 
        STATUS = 'COMPLETED'
        AND TABLE_TYPE IS NOT NULL
        AND QPS > 0
)
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
    
    -- Cost metrics (using estimated credits)
    SUM(estimated_credits) AS total_credits,
    AVG(estimated_credits) AS avg_credits_per_test,
    
    -- Cost efficiency (credits per 1K operations)
    CASE 
        WHEN SUM(TOTAL_OPERATIONS) > 0 
        THEN (SUM(estimated_credits) / SUM(TOTAL_OPERATIONS)) * 1000
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

FROM test_with_credits
GROUP BY TABLE_TYPE;

COMMENT ON DYNAMIC TABLE DT_TABLE_TYPE_SUMMARY IS 
'Aggregate performance metrics by table type for dashboard comparison view. Refreshes automatically when TEST_RESULTS changes.';


-- =============================================================================
-- DT_TEMPLATE_STATISTICS: Rolling stats per template for analysis page
-- =============================================================================
-- Provides template-level aggregates including stability metrics
-- Refresh: Downstream of TEST_RESULTS
-- Target Lag: 1 minute
--
-- Credit Estimation: Same logic as DT_TABLE_TYPE_SUMMARY
-- =============================================================================

CREATE OR ALTER DYNAMIC TABLE DT_TEMPLATE_STATISTICS
    TARGET_LAG = '1 minute'
    WAREHOUSE = COMPUTE_WH
AS
WITH template_tests AS (
    SELECT
        TEST_CONFIG:template_id::VARCHAR AS template_id,
        COALESCE(
            TEST_CONFIG:scenario:name::VARCHAR,
            TEST_CONFIG:template_config:name::VARCHAR,
            TEST_NAME
        ) AS template_name,
        TABLE_TYPE,
        WAREHOUSE_SIZE,
        COALESCE(
            TEST_CONFIG:scenario:load_mode::VARCHAR,
            TEST_CONFIG:template_config:load_mode::VARCHAR
        ) AS load_mode,
        
        -- Core metrics
        QPS,
        P50_LATENCY_MS,
        P95_LATENCY_MS,
        P99_LATENCY_MS,
        ERROR_RATE,
        DURATION_SECONDS,
        CONCURRENT_CONNECTIONS,
        TOTAL_OPERATIONS,
        
        -- Cost: estimate if not provided
        COALESCE(
            WAREHOUSE_CREDITS_USED,
            CASE 
                -- POSTGRES uses Snowflake Postgres Compute rates (Table 1(i))
                WHEN TABLE_TYPE = 'POSTGRES' THEN 
                    (DURATION_SECONDS / 3600.0) * 
                    CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                        WHEN 'XSMALL' THEN 0.0068 WHEN 'X-SMALL' THEN 0.0068
                        WHEN 'SMALL' THEN 0.0136
                        WHEN 'MEDIUM' THEN 0.0356
                        WHEN 'LARGE' THEN 0.0712
                        WHEN 'XLARGE' THEN 0.1424 WHEN 'X-LARGE' THEN 0.1424
                        WHEN '2XLARGE' THEN 0.2848 WHEN '2X-LARGE' THEN 0.2848
                        WHEN 'STANDARD_M' THEN 0.0356
                        WHEN 'STANDARD_L' THEN 0.0712
                        ELSE 0.0356
                    END
                WHEN TABLE_TYPE = 'INTERACTIVE' THEN 
                    (DURATION_SECONDS / 3600.0) * 
                    CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                        WHEN 'XSMALL' THEN 0.6 WHEN 'X-SMALL' THEN 0.6
                        WHEN 'SMALL' THEN 1.2
                        WHEN 'MEDIUM' THEN 2.4
                        WHEN 'LARGE' THEN 4.8
                        WHEN 'XLARGE' THEN 9.6 WHEN 'X-LARGE' THEN 9.6
                        ELSE 2.4
                    END
                ELSE 
                    (DURATION_SECONDS / 3600.0) * 
                    CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                        WHEN 'XSMALL' THEN 1 WHEN 'X-SMALL' THEN 1
                        WHEN 'SMALL' THEN 2
                        WHEN 'MEDIUM' THEN 4
                        WHEN 'LARGE' THEN 8
                        WHEN 'XLARGE' THEN 16 WHEN 'X-LARGE' THEN 16
                        WHEN '2XLARGE' THEN 32 WHEN '2X-LARGE' THEN 32
                        ELSE 4
                    END
            END
        ) AS estimated_credits,
        
        -- Timestamps
        START_TIME,
        
        -- For trend calculation (row number by time)
        ROW_NUMBER() OVER (
            PARTITION BY TEST_CONFIG:template_id::VARCHAR 
            ORDER BY START_TIME DESC
        ) AS recency_rank
        
    FROM TEST_RESULTS
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
        
        -- Latency stats (p50)
        AVG(P50_LATENCY_MS) AS avg_p50_ms,
        STDDEV(P50_LATENCY_MS) AS stddev_p50_ms,
        MIN(P50_LATENCY_MS) AS min_p50_ms,
        MAX(P50_LATENCY_MS) AS max_p50_ms,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY P50_LATENCY_MS) AS median_p50_ms,
        
        -- Latency stats (p95)
        AVG(P95_LATENCY_MS) AS avg_p95_ms,
        STDDEV(P95_LATENCY_MS) AS stddev_p95_ms,
        MIN(P95_LATENCY_MS) AS min_p95_ms,
        MAX(P95_LATENCY_MS) AS max_p95_ms,
        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY P95_LATENCY_MS) AS median_p95_ms,
        
        -- Latency stats (p99)
        AVG(P99_LATENCY_MS) AS avg_p99_ms,
        STDDEV(P99_LATENCY_MS) AS stddev_p99_ms,
        MIN(P99_LATENCY_MS) AS min_p99_ms,
        MAX(P99_LATENCY_MS) AS max_p99_ms,
        
        -- Error stats
        AVG(ERROR_RATE) AS avg_error_rate,
        MAX(ERROR_RATE) AS max_error_rate,
        
        -- Cost stats (using estimated credits)
        SUM(estimated_credits) AS total_credits,
        AVG(estimated_credits) AS avg_credits_per_run,
        
        -- Cost efficiency
        CASE 
            WHEN SUM(TOTAL_OPERATIONS) > 0 
            THEN (SUM(estimated_credits) / SUM(TOTAL_OPERATIONS)) * 1000
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
    template_id,
    template_name,
    table_type,
    warehouse_size,
    load_mode,
    total_runs,
    recent_runs,
    
    -- QPS stats
    avg_qps,
    stddev_qps,
    min_qps,
    max_qps,
    median_qps,
    
    -- p50 stats
    avg_p50_ms,
    stddev_p50_ms,
    min_p50_ms,
    max_p50_ms,
    median_p50_ms,
    
    -- p95 stats
    avg_p95_ms,
    stddev_p95_ms,
    min_p95_ms,
    max_p95_ms,
    median_p95_ms,
    
    -- p99 stats
    avg_p99_ms,
    stddev_p99_ms,
    min_p99_ms,
    max_p99_ms,
    
    -- Error stats
    avg_error_rate,
    max_error_rate,
    
    -- Cost stats
    total_credits,
    avg_credits_per_run,
    credits_per_1k_ops,
    
    -- Recent stats
    recent_avg_qps,
    recent_avg_p95_ms,
    
    -- Time range
    first_run,
    last_run,
    refreshed_at,
    
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
        WHEN avg_qps IS NULL OR stddev_qps IS NULL THEN 'unknown'
        WHEN (stddev_qps / NULLIF(avg_qps, 0)) < 0.10 THEN 'very_stable'
        WHEN (stddev_qps / NULLIF(avg_qps, 0)) < 0.15 THEN 'stable'
        WHEN (stddev_qps / NULLIF(avg_qps, 0)) < 0.25 THEN 'moderate'
        ELSE 'volatile'
    END AS stability_badge

FROM template_aggregates
WHERE total_runs >= 2;  -- Need at least 2 runs for meaningful stats

COMMENT ON DYNAMIC TABLE DT_TEMPLATE_STATISTICS IS 
'Rolling statistics per template for trend analysis and stability assessment. Refreshes automatically when TEST_RESULTS changes.';


-- =============================================================================
-- DT_DAILY_COST_ROLLUP: Daily cost tracking for budget analysis
-- =============================================================================
-- Tracks daily credit consumption by table type and warehouse size
-- Refresh: Downstream of TEST_RESULTS
-- Target Lag: 1 minute
--
-- Credit Estimation: Same logic as DT_TABLE_TYPE_SUMMARY
-- =============================================================================

CREATE OR ALTER DYNAMIC TABLE DT_DAILY_COST_ROLLUP
    TARGET_LAG = '1 minute'
    WAREHOUSE = COMPUTE_WH
AS
WITH test_with_credits AS (
    SELECT
        *,
        COALESCE(
            WAREHOUSE_CREDITS_USED,
            CASE 
                -- POSTGRES uses Snowflake Postgres Compute rates (Table 1(i))
                WHEN TABLE_TYPE = 'POSTGRES' THEN 
                    (DURATION_SECONDS / 3600.0) * 
                    CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                        WHEN 'XSMALL' THEN 0.0068 WHEN 'X-SMALL' THEN 0.0068
                        WHEN 'SMALL' THEN 0.0136
                        WHEN 'MEDIUM' THEN 0.0356
                        WHEN 'LARGE' THEN 0.0712
                        WHEN 'XLARGE' THEN 0.1424 WHEN 'X-LARGE' THEN 0.1424
                        WHEN '2XLARGE' THEN 0.2848 WHEN '2X-LARGE' THEN 0.2848
                        ELSE 0.0356
                    END
                WHEN TABLE_TYPE = 'INTERACTIVE' THEN 
                    (DURATION_SECONDS / 3600.0) * 
                    CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                        WHEN 'XSMALL' THEN 0.6 WHEN 'X-SMALL' THEN 0.6
                        WHEN 'SMALL' THEN 1.2
                        WHEN 'MEDIUM' THEN 2.4
                        WHEN 'LARGE' THEN 4.8
                        WHEN 'XLARGE' THEN 9.6 WHEN 'X-LARGE' THEN 9.6
                        ELSE 2.4
                    END
                ELSE 
                    (DURATION_SECONDS / 3600.0) * 
                    CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                        WHEN 'XSMALL' THEN 1 WHEN 'X-SMALL' THEN 1
                        WHEN 'SMALL' THEN 2
                        WHEN 'MEDIUM' THEN 4
                        WHEN 'LARGE' THEN 8
                        WHEN 'XLARGE' THEN 16 WHEN 'X-LARGE' THEN 16
                        WHEN '2XLARGE' THEN 32 WHEN '2X-LARGE' THEN 32
                        ELSE 4
                    END
            END
        ) AS estimated_credits
    FROM TEST_RESULTS
    WHERE 
        STATUS = 'COMPLETED'
        AND START_TIME IS NOT NULL
)
SELECT
    DATE_TRUNC('DAY', START_TIME)::DATE AS run_date,
    TABLE_TYPE,
    WAREHOUSE_SIZE,
    
    -- Test counts
    COUNT(*) AS test_count,
    
    -- Credit consumption (using estimated)
    SUM(estimated_credits) AS total_credits,
    AVG(estimated_credits) AS avg_credits_per_test,
    
    -- Operations
    SUM(TOTAL_OPERATIONS) AS total_operations,
    
    -- Cost efficiency
    CASE 
        WHEN SUM(TOTAL_OPERATIONS) > 0 
        THEN (SUM(estimated_credits) / SUM(TOTAL_OPERATIONS)) * 1000
        ELSE NULL 
    END AS credits_per_1k_ops,
    
    -- Performance summary
    AVG(QPS) AS avg_qps,
    AVG(P95_LATENCY_MS) AS avg_p95_ms,
    
    -- Duration
    SUM(DURATION_SECONDS) AS total_test_duration_seconds,
    
    -- Refresh timestamp
    CURRENT_TIMESTAMP() AS refreshed_at

FROM test_with_credits
GROUP BY 
    DATE_TRUNC('DAY', START_TIME)::DATE,
    TABLE_TYPE,
    WAREHOUSE_SIZE;

COMMENT ON DYNAMIC TABLE DT_DAILY_COST_ROLLUP IS 
'Daily cost rollup by table type and warehouse size for budget tracking. Refreshes automatically when TEST_RESULTS changes.';


-- =============================================================================
-- V_TEMPLATE_RUNS: Detailed run list for template analysis
-- =============================================================================
-- Lists all runs for a specific template with enriched fields
-- Use with WHERE template_id = ? filter
--
-- Credit Estimation: Same logic as dynamic tables
-- =============================================================================

CREATE OR REPLACE VIEW V_TEMPLATE_RUNS AS
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
    
    -- Cost (estimated if not provided)
    COALESCE(
        WAREHOUSE_CREDITS_USED,
        CASE 
            -- POSTGRES uses Snowflake Postgres Compute rates (Table 1(i))
            WHEN TABLE_TYPE = 'POSTGRES' THEN 
                (DURATION_SECONDS / 3600.0) * 
                CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                    WHEN 'XSMALL' THEN 0.0068 WHEN 'X-SMALL' THEN 0.0068
                    WHEN 'SMALL' THEN 0.0136
                    WHEN 'MEDIUM' THEN 0.0356
                    WHEN 'LARGE' THEN 0.0712
                    WHEN 'XLARGE' THEN 0.1424 WHEN 'X-LARGE' THEN 0.1424
                    ELSE 0.0356
                END
            WHEN TABLE_TYPE = 'INTERACTIVE' THEN 
                (DURATION_SECONDS / 3600.0) * 
                CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                    WHEN 'XSMALL' THEN 0.6 WHEN 'X-SMALL' THEN 0.6
                    WHEN 'SMALL' THEN 1.2
                    WHEN 'MEDIUM' THEN 2.4
                    WHEN 'LARGE' THEN 4.8
                    WHEN 'XLARGE' THEN 9.6 WHEN 'X-LARGE' THEN 9.6
                    ELSE 2.4
                END
            ELSE 
                (DURATION_SECONDS / 3600.0) * 
                CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                    WHEN 'XSMALL' THEN 1 WHEN 'X-SMALL' THEN 1
                    WHEN 'SMALL' THEN 2
                    WHEN 'MEDIUM' THEN 4
                    WHEN 'LARGE' THEN 8
                    WHEN 'XLARGE' THEN 16 WHEN 'X-LARGE' THEN 16
                    WHEN '2XLARGE' THEN 32 WHEN '2X-LARGE' THEN 32
                    ELSE 4
                END
        END
    ) AS estimated_credits,
    CASE 
        WHEN TOTAL_OPERATIONS > 0 THEN
            (COALESCE(
                WAREHOUSE_CREDITS_USED,
                CASE 
                    WHEN TABLE_TYPE = 'POSTGRES' THEN 
                        (DURATION_SECONDS / 3600.0) * 
                        CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                            WHEN 'MEDIUM' THEN 0.0356 ELSE 0.0356
                        END
                    WHEN TABLE_TYPE = 'INTERACTIVE' THEN 
                        (DURATION_SECONDS / 3600.0) * 
                        CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                            WHEN 'MEDIUM' THEN 2.4 ELSE 2.4
                        END
                    ELSE 
                        (DURATION_SECONDS / 3600.0) * 
                        CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))
                            WHEN 'MEDIUM' THEN 4 ELSE 4
                        END
                END
            ) / TOTAL_OPERATIONS) * 1000
        ELSE NULL 
    END AS credits_per_1k_ops,
    
    -- Load mode details
    COALESCE(
        TEST_CONFIG:scenario:load_mode::VARCHAR,
        TEST_CONFIG:template_config:load_mode::VARCHAR
    ) AS load_mode,
    TEST_CONFIG:template_config:scaling:mode::VARCHAR AS scale_mode,
    
    -- For outlier detection (will be enriched by API)
    ROW_NUMBER() OVER (
        PARTITION BY TEST_CONFIG:template_id::VARCHAR 
        ORDER BY START_TIME DESC
    ) AS recency_rank

FROM TEST_RESULTS
WHERE 
    STATUS = 'COMPLETED'
    AND TEST_CONFIG:template_id IS NOT NULL;

COMMENT ON VIEW V_TEMPLATE_RUNS IS 
'Detailed run list per template for analysis page. Use with template_id filter.';


-- =============================================================================
-- Verification Queries
-- =============================================================================
-- Run these after deployment to verify data

-- Verify DT_TABLE_TYPE_SUMMARY
-- SELECT table_type, test_count, avg_qps, credits_per_1k_ops 
-- FROM DT_TABLE_TYPE_SUMMARY
-- ORDER BY test_count DESC;

-- Verify DT_TEMPLATE_STATISTICS
-- SELECT template_id, template_name, table_type, total_runs, stability_badge
-- FROM DT_TEMPLATE_STATISTICS
-- ORDER BY total_runs DESC
-- LIMIT 20;

-- Verify DT_DAILY_COST_ROLLUP
-- SELECT run_date, table_type, test_count, total_credits
-- FROM DT_DAILY_COST_ROLLUP
-- ORDER BY run_date DESC
-- LIMIT 20;

-- Verify V_TEMPLATE_RUNS
-- SELECT COUNT(*) AS total_runs, COUNT(DISTINCT template_id) AS templates
-- FROM V_TEMPLATE_RUNS;
