-- =============================================================================
-- Unistore Benchmark - Statistical Analysis Stored Procedure
-- =============================================================================
-- Provides statistical analysis functions for Cortex Agent including:
-- - Rolling statistics (median, percentiles, confidence bands)
-- - Trend analysis (linear regression, direction detection)
-- - Mann-Whitney U test for significance testing
-- - Delta calculations vs baseline
--
-- Database: FLAKEBENCH
-- Schema: TEST_RESULTS
--
-- Created: 2026-02-12
-- Part of: Phase 7 - Cortex Agent for Analysis & Investigation
-- =============================================================================

USE DATABASE FLAKEBENCH;
USE SCHEMA TEST_RESULTS;

-- =============================================================================
-- CALCULATE_ROLLING_STATISTICS: Baseline statistics for a template
-- =============================================================================
-- Calculates rolling statistics from recent baseline tests for comparison.
-- Returns median, P10, P90 confidence bands, and trend information.
-- =============================================================================

CREATE OR REPLACE PROCEDURE CALCULATE_ROLLING_STATISTICS(
    p_test_id VARCHAR,
    p_use_count INTEGER DEFAULT 5,
    p_days_back INTEGER DEFAULT 30
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Calculate rolling statistics from baseline candidates for comparison. Returns median, confidence bands (P10-P90), and trend analysis.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_test_id VARCHAR := p_test_id;
    v_use_count INTEGER := COALESCE(p_use_count, 5);
    v_days_back INTEGER := COALESCE(p_days_back, 30);
    v_template_id VARCHAR;
    v_load_mode VARCHAR;
    v_table_type VARCHAR;
BEGIN
    -- Get the template_id, load_mode, and table_type for the current test
    SELECT 
        TEST_CONFIG:template_id::VARCHAR,
        COALESCE(
            TEST_CONFIG:template_config:load_mode::VARCHAR,
            TEST_CONFIG:scenario:load_mode::VARCHAR,
            'CONCURRENCY'
        ),
        TABLE_TYPE
    INTO v_template_id, v_load_mode, v_table_type
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = :v_test_id;
    
    IF (v_template_id IS NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'test_id', :v_test_id,
            'available', FALSE,
            'error', 'Test not found or no template_id'
        );
    END IF;
    
    -- Calculate rolling statistics from baseline candidates
    SELECT OBJECT_CONSTRUCT(
        'test_id', :v_test_id,
        'available', IFF(candidate_count > 0, TRUE, FALSE),
        'template_id', :v_template_id,
        'load_mode', :v_load_mode,
        'table_type', :v_table_type,
        'candidate_count', candidate_count,
        'used_count', used_count,
        'rolling_median', OBJECT_CONSTRUCT(
            'qps', ROUND(median_qps, 2),
            'p50_latency_ms', ROUND(median_p50, 2),
            'p95_latency_ms', ROUND(median_p95, 2),
            'p99_latency_ms', ROUND(median_p99, 2),
            'error_rate_pct', ROUND(median_error_rate, 4)
        ),
        'confidence_band', OBJECT_CONSTRUCT(
            'qps_p10', ROUND(qps_p10, 2),
            'qps_p90', ROUND(qps_p90, 2),
            'p95_p10', ROUND(p95_p10, 2),
            'p95_p90', ROUND(p95_p90, 2)
        ),
        'coefficient_of_variation', OBJECT_CONSTRUCT(
            'qps_cv', ROUND(qps_cv, 4),
            'p95_cv', ROUND(p95_cv, 4),
            'stability', CASE 
                WHEN qps_cv < 0.15 THEN 'STABLE'
                WHEN qps_cv < 0.30 THEN 'MODERATE'
                ELSE 'HIGH_VARIANCE'
            END
        ),
        'date_range', OBJECT_CONSTRUCT(
            'oldest', oldest_date,
            'newest', newest_date
        ),
        'baseline_tests', baseline_test_ids
    ) INTO result
    FROM (
        SELECT
            COUNT(*) AS candidate_count,
            LEAST(COUNT(*), :v_use_count) AS used_count,
            -- Medians
            MEDIAN(QPS) AS median_qps,
            MEDIAN(P50_LATENCY_MS) AS median_p50,
            MEDIAN(P95_LATENCY_MS) AS median_p95,
            MEDIAN(P99_LATENCY_MS) AS median_p99,
            MEDIAN(ERROR_RATE * 100) AS median_error_rate,
            -- Confidence bands (P10-P90)
            PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY QPS) AS qps_p10,
            PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY QPS) AS qps_p90,
            PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY P95_LATENCY_MS) AS p95_p10,
            PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY P95_LATENCY_MS) AS p95_p90,
            -- Coefficient of variation (stddev/mean)
            STDDEV(QPS) / NULLIF(AVG(QPS), 0) AS qps_cv,
            STDDEV(P95_LATENCY_MS) / NULLIF(AVG(P95_LATENCY_MS), 0) AS p95_cv,
            -- Date range
            MIN(START_TIME) AS oldest_date,
            MAX(START_TIME) AS newest_date,
            -- Test IDs for reference
            ARRAY_AGG(TEST_ID) WITHIN GROUP (ORDER BY START_TIME DESC) AS baseline_test_ids
        FROM (
            SELECT *
            FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
            WHERE TEST_CONFIG:template_id::VARCHAR = :v_template_id
              AND COALESCE(TEST_CONFIG:template_config:load_mode::VARCHAR, 
                           TEST_CONFIG:scenario:load_mode::VARCHAR, 'CONCURRENCY') = :v_load_mode
              AND TABLE_TYPE = :v_table_type
              AND STATUS = 'COMPLETED'
              AND TEST_ID != :v_test_id
              AND (RUN_ID IS NULL OR RUN_ID = TEST_ID)  -- Parent runs only
              AND START_TIME >= DATEADD('day', -:v_days_back, CURRENT_TIMESTAMP())
            ORDER BY START_TIME DESC
            LIMIT :v_use_count
        )
    );
    
    RETURN COALESCE(result, OBJECT_CONSTRUCT(
        'test_id', :v_test_id,
        'available', FALSE,
        'candidate_count', 0,
        'message', 'No baseline candidates found'
    ));
END;
$$;

-- =============================================================================
-- CALCULATE_TREND_ANALYSIS: Linear regression trend for a metric
-- =============================================================================
-- Performs linear regression on historical test data to detect trends.
-- Returns slope, R², and direction (IMPROVING/REGRESSING/STABLE).
-- =============================================================================

CREATE OR REPLACE PROCEDURE CALCULATE_TREND_ANALYSIS(
    p_template_id VARCHAR,
    p_metric VARCHAR DEFAULT 'QPS',
    p_limit INTEGER DEFAULT 10
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Calculate linear trend for a metric across recent tests. Returns slope, R², direction.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_template_id VARCHAR := p_template_id;
    v_metric VARCHAR := UPPER(COALESCE(p_metric, 'QPS'));
    v_limit INTEGER := COALESCE(p_limit, 10);
BEGIN
    -- Calculate linear regression using Snowflake's built-in REGR functions
    SELECT OBJECT_CONSTRUCT(
        'template_id', :v_template_id,
        'metric', :v_metric,
        'sample_size', n,
        'slope', ROUND(slope, 6),
        'intercept', ROUND(intercept, 4),
        'r_squared', ROUND(r_squared, 4),
        'direction', CASE
            WHEN n < 3 THEN 'INSUFFICIENT_DATA'
            WHEN r_squared < 0.3 THEN 'STABLE'
            WHEN ABS(slope_pct) < 2 THEN 'STABLE'
            WHEN slope > 0 AND :v_metric IN ('QPS', 'TOTAL_OPERATIONS') THEN 'IMPROVING'
            WHEN slope < 0 AND :v_metric IN ('QPS', 'TOTAL_OPERATIONS') THEN 'REGRESSING'
            WHEN slope > 0 AND :v_metric LIKE '%LATENCY%' THEN 'REGRESSING'
            WHEN slope < 0 AND :v_metric LIKE '%LATENCY%' THEN 'IMPROVING'
            ELSE 'STABLE'
        END,
        'interpretation', CASE
            WHEN n < 3 THEN 'Need at least 3 data points for trend analysis'
            WHEN r_squared < 0.3 THEN 'No clear trend detected (R² < 0.3)'
            WHEN ABS(slope_pct) < 2 THEN 'Trend is within noise threshold (<2% per run)'
            WHEN r_squared >= 0.7 THEN 'Strong trend detected (R² >= 0.7)'
            ELSE 'Moderate trend detected'
        END
    ) INTO result
    FROM (
        SELECT
            n,
            slope,
            y_mean - slope * x_mean AS intercept,
            CASE WHEN ss_tot > 0 THEN GREATEST(0, 1 - ss_res / ss_tot) ELSE 0 END AS r_squared,
            CASE WHEN y_mean != 0 THEN ABS(slope / y_mean * 100) ELSE 0 END AS slope_pct
        FROM (
            SELECT
                COUNT(*) AS n,
                AVG(x) AS x_mean,
                AVG(y) AS y_mean,
                -- Use REGR_SLOPE for linear regression
                REGR_SLOPE(y, x) AS slope,
                -- SS_tot = sum of (y - y_mean)^2
                REGR_SYY(y, x) AS ss_tot,
                -- SS_res = SS_tot * (1 - R^2)
                REGR_SYY(y, x) * (1 - POWER(COALESCE(REGR_R2(y, x), 0), 1)) AS ss_res
            FROM (
                SELECT
                    ROW_NUMBER() OVER (ORDER BY START_TIME ASC) - 1 AS x,
                    CASE :v_metric
                        WHEN 'QPS' THEN QPS
                        WHEN 'P50_LATENCY_MS' THEN P50_LATENCY_MS
                        WHEN 'P95_LATENCY_MS' THEN P95_LATENCY_MS
                        WHEN 'P99_LATENCY_MS' THEN P99_LATENCY_MS
                        WHEN 'ERROR_RATE' THEN ERROR_RATE * 100
                        WHEN 'TOTAL_OPERATIONS' THEN TOTAL_OPERATIONS
                        ELSE QPS
                    END AS y,
                    TEST_ID
                FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
                WHERE TEST_CONFIG:template_id::VARCHAR = :v_template_id
                  AND STATUS = 'COMPLETED'
                  AND (RUN_ID IS NULL OR RUN_ID = TEST_ID)
                ORDER BY START_TIME DESC
                LIMIT :v_limit
            )
        )
    );
    
    RETURN COALESCE(result, OBJECT_CONSTRUCT(
        'template_id', :v_template_id,
        'metric', :v_metric,
        'sample_size', 0,
        'direction', 'INSUFFICIENT_DATA',
        'error', 'No data found for template'
    ));
END;
$$;

-- =============================================================================
-- MANN_WHITNEY_U_TEST: Non-parametric significance test
-- =============================================================================
-- Performs Mann-Whitney U test to determine if two groups of measurements
-- are significantly different. Used for A/B test comparisons.
-- =============================================================================

CREATE OR REPLACE PROCEDURE MANN_WHITNEY_U_TEST(
    p_test_id_a VARCHAR,
    p_test_id_b VARCHAR,
    p_metric VARCHAR DEFAULT 'APP_ELAPSED_MS'
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Mann-Whitney U test for statistical significance between two tests. Returns U statistic, z-score, and p-value approximation.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_test_id_a VARCHAR := p_test_id_a;
    v_test_id_b VARCHAR := p_test_id_b;
    v_metric VARCHAR := UPPER(COALESCE(p_metric, 'APP_ELAPSED_MS'));
BEGIN
    -- Mann-Whitney U test implementation
    -- U = n1*n2 + (n1*(n1+1))/2 - R1
    -- where R1 is the sum of ranks for group 1
    
    SELECT OBJECT_CONSTRUCT(
        'test_a', :v_test_id_a,
        'test_b', :v_test_id_b,
        'metric', :v_metric,
        'n_a', n_a,
        'n_b', n_b,
        'mean_a', ROUND(mean_a, 4),
        'mean_b', ROUND(mean_b, 4),
        'median_a', ROUND(median_a, 4),
        'median_b', ROUND(median_b, 4),
        'u_statistic', ROUND(u_stat, 2),
        'z_score', ROUND(z_score, 4),
        'p_value_approx', ROUND(p_value, 6),
        'is_significant', IFF(p_value < 0.05, TRUE, FALSE),
        'significance_level', CASE
            WHEN p_value < 0.001 THEN 'HIGHLY_SIGNIFICANT'
            WHEN p_value < 0.01 THEN 'VERY_SIGNIFICANT'
            WHEN p_value < 0.05 THEN 'SIGNIFICANT'
            WHEN p_value < 0.10 THEN 'MARGINALLY_SIGNIFICANT'
            ELSE 'NOT_SIGNIFICANT'
        END,
        'interpretation', CASE
            WHEN n_a < 10 OR n_b < 10 THEN 'Sample sizes too small for reliable significance testing'
            WHEN p_value < 0.001 THEN 'Very strong evidence of difference between groups'
            WHEN p_value < 0.01 THEN 'Strong evidence of difference between groups'
            WHEN p_value < 0.05 THEN 'Moderate evidence of difference between groups'
            WHEN p_value < 0.10 THEN 'Weak evidence of difference - may be noise'
            ELSE 'No significant difference detected between groups'
        END,
        'effect_size', OBJECT_CONSTRUCT(
            'difference_pct', ROUND(IFF(mean_b != 0, (mean_a - mean_b) / mean_b * 100, NULL), 2),
            'direction', CASE 
                WHEN mean_a > mean_b THEN 'A_HIGHER'
                WHEN mean_a < mean_b THEN 'B_HIGHER'
                ELSE 'EQUAL'
            END
        )
    ) INTO result
    FROM (
        SELECT
            n_a,
            n_b,
            mean_a,
            mean_b,
            median_a,
            median_b,
            -- U statistic (smaller of U_a and U_b)
            LEAST(u_a, n_a * n_b - u_a) AS u_stat,
            -- Z-score approximation for large samples
            -- z = (U - μ_U) / σ_U where μ_U = n1*n2/2 and σ_U = sqrt(n1*n2*(n1+n2+1)/12)
            (LEAST(u_a, n_a * n_b - u_a) - (n_a * n_b / 2.0)) / 
                NULLIF(SQRT(n_a * n_b * (n_a + n_b + 1) / 12.0), 0) AS z_score,
            -- P-value approximation using normal distribution
            -- p ≈ 2 * (1 - Φ(|z|)) where Φ is standard normal CDF
            -- Using approximation: Φ(z) ≈ 1 / (1 + exp(-1.702 * z))
            2 * (1 - (1 / (1 + EXP(-1.702 * ABS(
                (LEAST(u_a, n_a * n_b - u_a) - (n_a * n_b / 2.0)) / 
                NULLIF(SQRT(n_a * n_b * (n_a + n_b + 1) / 12.0), 0)
            ))))) AS p_value
        FROM (
            SELECT
                SUM(CASE WHEN test_group = 'A' THEN 1 ELSE 0 END) AS n_a,
                SUM(CASE WHEN test_group = 'B' THEN 1 ELSE 0 END) AS n_b,
                AVG(CASE WHEN test_group = 'A' THEN metric_value END) AS mean_a,
                AVG(CASE WHEN test_group = 'B' THEN metric_value END) AS mean_b,
                MEDIAN(CASE WHEN test_group = 'A' THEN metric_value END) AS median_a,
                MEDIAN(CASE WHEN test_group = 'B' THEN metric_value END) AS median_b,
                -- U_a = sum of ranks for A - n_a*(n_a+1)/2
                SUM(CASE WHEN test_group = 'A' THEN rank_val ELSE 0 END) - 
                    (SUM(CASE WHEN test_group = 'A' THEN 1 ELSE 0 END) * 
                     (SUM(CASE WHEN test_group = 'A' THEN 1 ELSE 0 END) + 1) / 2.0) AS u_a
            FROM (
                SELECT
                    test_group,
                    metric_value,
                    RANK() OVER (ORDER BY metric_value) AS rank_val
                FROM (
                    SELECT 
                        'A' AS test_group,
                        CASE :v_metric
                            WHEN 'APP_ELAPSED_MS' THEN APP_ELAPSED_MS
                            WHEN 'DURATION_MS' THEN DURATION_MS
                            WHEN 'SF_EXECUTION_MS' THEN SF_EXECUTION_MS
                            ELSE APP_ELAPSED_MS
                        END AS metric_value
                    FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS
                    WHERE TEST_ID = :v_test_id_a
                      AND COALESCE(WARMUP, FALSE) = FALSE
                      AND SUCCESS = TRUE
                    
                    UNION ALL
                    
                    SELECT 
                        'B' AS test_group,
                        CASE :v_metric
                            WHEN 'APP_ELAPSED_MS' THEN APP_ELAPSED_MS
                            WHEN 'DURATION_MS' THEN DURATION_MS
                            WHEN 'SF_EXECUTION_MS' THEN SF_EXECUTION_MS
                            ELSE APP_ELAPSED_MS
                        END AS metric_value
                    FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS
                    WHERE TEST_ID = :v_test_id_b
                      AND COALESCE(WARMUP, FALSE) = FALSE
                      AND SUCCESS = TRUE
                )
                WHERE metric_value IS NOT NULL
            )
        )
    );
    
    IF (result IS NULL OR result:n_a IS NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'test_a', :v_test_id_a,
            'test_b', :v_test_id_b,
            'error', 'Insufficient query execution data for statistical test',
            'is_significant', NULL
        );
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- COMPARE_TESTS_STATISTICAL: Comprehensive statistical comparison
-- =============================================================================
-- Combines multiple statistical tests for a comprehensive comparison
-- between two tests or between a test and its baseline.
-- =============================================================================

CREATE OR REPLACE PROCEDURE COMPARE_TESTS_STATISTICAL(
    p_test_id_a VARCHAR,
    p_test_id_b VARCHAR DEFAULT NULL
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Comprehensive statistical comparison between two tests. If test_b is NULL, compares against rolling baseline.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_test_id_a VARCHAR := p_test_id_a;
    v_test_id_b VARCHAR := p_test_id_b;
BEGIN
    -- Get test A details and optionally test B or baseline
    SELECT OBJECT_CONSTRUCT(
        'test_a', OBJECT_CONSTRUCT(
            'test_id', a.TEST_ID,
            'test_name', a.TEST_NAME,
            'table_type', a.TABLE_TYPE,
            'warehouse_size', a.WAREHOUSE_SIZE,
            'qps', ROUND(a.QPS, 2),
            'p50_latency_ms', ROUND(a.P50_LATENCY_MS, 2),
            'p95_latency_ms', ROUND(a.P95_LATENCY_MS, 2),
            'p99_latency_ms', ROUND(a.P99_LATENCY_MS, 2),
            'error_rate_pct', ROUND(a.ERROR_RATE * 100, 4),
            'total_operations', a.TOTAL_OPERATIONS
        ),
        'test_b', CASE WHEN b.TEST_ID IS NOT NULL THEN OBJECT_CONSTRUCT(
            'test_id', b.TEST_ID,
            'test_name', b.TEST_NAME,
            'table_type', b.TABLE_TYPE,
            'warehouse_size', b.WAREHOUSE_SIZE,
            'qps', ROUND(b.QPS, 2),
            'p50_latency_ms', ROUND(b.P50_LATENCY_MS, 2),
            'p95_latency_ms', ROUND(b.P95_LATENCY_MS, 2),
            'p99_latency_ms', ROUND(b.P99_LATENCY_MS, 2),
            'error_rate_pct', ROUND(b.ERROR_RATE * 100, 4),
            'total_operations', b.TOTAL_OPERATIONS
        ) ELSE NULL END,
        'comparison_type', IFF(b.TEST_ID IS NOT NULL, 'DIRECT', 'BASELINE'),
        'deltas', OBJECT_CONSTRUCT(
            'qps_delta_pct', ROUND(IFF(COALESCE(b.QPS, 0) != 0, 
                (a.QPS - b.QPS) / b.QPS * 100, NULL), 2),
            'p50_delta_pct', ROUND(IFF(COALESCE(b.P50_LATENCY_MS, 0) != 0, 
                (a.P50_LATENCY_MS - b.P50_LATENCY_MS) / b.P50_LATENCY_MS * 100, NULL), 2),
            'p95_delta_pct', ROUND(IFF(COALESCE(b.P95_LATENCY_MS, 0) != 0, 
                (a.P95_LATENCY_MS - b.P95_LATENCY_MS) / b.P95_LATENCY_MS * 100, NULL), 2),
            'p99_delta_pct', ROUND(IFF(COALESCE(b.P99_LATENCY_MS, 0) != 0, 
                (a.P99_LATENCY_MS - b.P99_LATENCY_MS) / b.P99_LATENCY_MS * 100, NULL), 2),
            'error_rate_delta', ROUND((a.ERROR_RATE - COALESCE(b.ERROR_RATE, 0)) * 100, 4)
        ),
        'verdict', OBJECT_CONSTRUCT(
            'overall', CASE
                -- QPS improved >10% and latency same or better = IMPROVED
                WHEN COALESCE(b.QPS, 0) != 0 
                     AND (a.QPS - b.QPS) / b.QPS > 0.10 
                     AND (a.P95_LATENCY_MS <= b.P95_LATENCY_MS * 1.05 OR b.P95_LATENCY_MS IS NULL)
                THEN 'IMPROVED'
                -- QPS dropped >10% or latency increased >20% = REGRESSED
                WHEN COALESCE(b.QPS, 0) != 0 
                     AND (a.QPS - b.QPS) / b.QPS < -0.10
                THEN 'REGRESSED'
                WHEN COALESCE(b.P95_LATENCY_MS, 0) != 0 
                     AND (a.P95_LATENCY_MS - b.P95_LATENCY_MS) / b.P95_LATENCY_MS > 0.20
                THEN 'REGRESSED'
                -- Error rate increased significantly = REGRESSED
                WHEN a.ERROR_RATE > 0.01 AND a.ERROR_RATE > COALESCE(b.ERROR_RATE, 0) * 2
                THEN 'REGRESSED'
                -- Within ±10% = STABLE
                WHEN COALESCE(b.QPS, 0) != 0 
                     AND ABS((a.QPS - b.QPS) / b.QPS) <= 0.10
                THEN 'STABLE'
                ELSE 'INCONCLUSIVE'
            END,
            'qps_verdict', CASE
                WHEN COALESCE(b.QPS, 0) = 0 THEN 'NO_BASELINE'
                WHEN (a.QPS - b.QPS) / b.QPS > 0.10 THEN 'IMPROVED'
                WHEN (a.QPS - b.QPS) / b.QPS < -0.10 THEN 'REGRESSED'
                ELSE 'STABLE'
            END,
            'latency_verdict', CASE
                WHEN COALESCE(b.P95_LATENCY_MS, 0) = 0 THEN 'NO_BASELINE'
                WHEN (a.P95_LATENCY_MS - b.P95_LATENCY_MS) / b.P95_LATENCY_MS < -0.10 THEN 'IMPROVED'
                WHEN (a.P95_LATENCY_MS - b.P95_LATENCY_MS) / b.P95_LATENCY_MS > 0.20 THEN 'REGRESSED'
                ELSE 'STABLE'
            END
        ),
        'analysis_timestamp', CURRENT_TIMESTAMP()
    ) INTO result
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS a
    LEFT JOIN FLAKEBENCH.TEST_RESULTS.TEST_RESULTS b 
        ON b.TEST_ID = :v_test_id_b
    WHERE a.TEST_ID = :v_test_id_a;
    
    IF (result IS NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'error', 'Test A not found',
            'test_id_a', :v_test_id_a
        );
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- STATISTICAL_ANALYSIS: Main entry point for Cortex Agent
-- =============================================================================
-- Comprehensive statistical analysis combining:
-- - Rolling baseline statistics
-- - Trend analysis
-- - Delta calculations
-- - Verdicts and recommendations
-- =============================================================================

CREATE OR REPLACE PROCEDURE STATISTICAL_ANALYSIS(
    p_test_id VARCHAR,
    p_compare_to_test_id VARCHAR DEFAULT NULL,
    p_include_mann_whitney BOOLEAN DEFAULT FALSE
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Main statistical analysis entry point for Cortex Agent. Combines rolling stats, trends, deltas, and optional significance testing.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    rolling_stats VARIANT;
    trend_qps VARIANT;
    trend_p95 VARIANT;
    comparison VARIANT;
    mann_whitney VARIANT;
    v_test_id VARCHAR := p_test_id;
    v_compare_id VARCHAR := p_compare_to_test_id;
    v_template_id VARCHAR;
BEGIN
    -- Get template_id for trend analysis
    SELECT TEST_CONFIG:template_id::VARCHAR INTO v_template_id
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = :v_test_id;
    
    -- Get rolling statistics
    CALL CALCULATE_ROLLING_STATISTICS(:v_test_id);
    rolling_stats := (SELECT CALCULATE_ROLLING_STATISTICS FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
    
    -- Get QPS trend
    CALL CALCULATE_TREND_ANALYSIS(:v_template_id, 'QPS', 10);
    trend_qps := (SELECT CALCULATE_TREND_ANALYSIS FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
    
    -- Get P95 latency trend
    CALL CALCULATE_TREND_ANALYSIS(:v_template_id, 'P95_LATENCY_MS', 10);
    trend_p95 := (SELECT CALCULATE_TREND_ANALYSIS FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
    
    -- Get comparison (direct or vs baseline)
    IF (v_compare_id IS NOT NULL) THEN
        CALL COMPARE_TESTS_STATISTICAL(:v_test_id, :v_compare_id);
        comparison := (SELECT COMPARE_TESTS_STATISTICAL FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
        
        -- Optional Mann-Whitney test
        IF (p_include_mann_whitney = TRUE) THEN
            CALL MANN_WHITNEY_U_TEST(:v_test_id, :v_compare_id, 'APP_ELAPSED_MS');
            mann_whitney := (SELECT MANN_WHITNEY_U_TEST FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
        END IF;
    ELSE
        CALL COMPARE_TESTS_STATISTICAL(:v_test_id, NULL);
        comparison := (SELECT COMPARE_TESTS_STATISTICAL FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
    END IF;
    
    -- Combine all results
    RETURN OBJECT_CONSTRUCT(
        'test_id', :v_test_id,
        'template_id', :v_template_id,
        'rolling_statistics', rolling_stats,
        'trends', OBJECT_CONSTRUCT(
            'qps', trend_qps,
            'p95_latency', trend_p95
        ),
        'comparison', comparison,
        'mann_whitney', mann_whitney,
        'analysis_timestamp', CURRENT_TIMESTAMP()
    );
END;
$$;

-- =============================================================================
-- COST_CALCULATOR: Credit and cost analysis for tests (ARRAY version)
-- =============================================================================
-- NOTE: This version uses ARRAY parameter which is NOT supported by Cortex Agent
-- generic tools. Use COST_CALCULATOR_V2 for agent integration.
-- =============================================================================

CREATE OR REPLACE PROCEDURE COST_CALCULATOR(
    p_test_ids ARRAY,
    p_comparison_type VARCHAR DEFAULT 'absolute'
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Calculate cost metrics for tests including credit consumption, $/query, and cost comparisons.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_test_ids ARRAY := p_test_ids;
    v_comparison_type VARCHAR := LOWER(COALESCE(p_comparison_type, 'absolute'));
    v_credit_cost_usd NUMBER := 3.00;  -- $3 per credit (varies by contract)
BEGIN
    SELECT OBJECT_CONSTRUCT(
        'tests', ARRAY_AGG(OBJECT_CONSTRUCT(
            'test_id', TEST_ID,
            'test_name', TEST_NAME,
            'warehouse_size', WAREHOUSE_SIZE,
            'duration_seconds', ROUND(DURATION_SECONDS, 2),
            'qps', ROUND(QPS, 2),
            'total_operations', TOTAL_OPERATIONS,
            'credits_per_hour', credits_per_hour,
            'credits_used', ROUND(credits_used, 4),
            'cost_usd', ROUND(cost_usd, 4),
            'cost_per_query_usd', ROUND(cost_usd / NULLIF(TOTAL_OPERATIONS, 0), 8),
            'cost_per_1k_queries_usd', ROUND(cost_usd / NULLIF(TOTAL_OPERATIONS, 0) * 1000, 4),
            'queries_per_credit', ROUND(TOTAL_OPERATIONS / NULLIF(credits_used, 0), 2)
        )) WITHIN GROUP (ORDER BY cost_usd / NULLIF(TOTAL_OPERATIONS, 0) ASC),
        'summary', OBJECT_CONSTRUCT(
            'total_credits', ROUND(SUM(credits_used), 4),
            'total_cost_usd', ROUND(SUM(cost_usd), 2),
            'total_queries', SUM(TOTAL_OPERATIONS),
            'avg_cost_per_query_usd', ROUND(SUM(cost_usd) / NULLIF(SUM(TOTAL_OPERATIONS), 0), 6),
            'avg_cost_per_1k_queries_usd', ROUND(SUM(cost_usd) / NULLIF(SUM(TOTAL_OPERATIONS), 0) * 1000, 4)
        ),
        'comparison_type', :v_comparison_type,
        'credit_rate_usd', :v_credit_cost_usd,
        'analysis_timestamp', CURRENT_TIMESTAMP()
    ) INTO result
    FROM (
        SELECT
            TEST_ID,
            TEST_NAME,
            WAREHOUSE_SIZE,
            DURATION_SECONDS,
            QPS,
            TOTAL_OPERATIONS,
            -- Standard credit rates by warehouse size (Enterprise)
            CASE WAREHOUSE_SIZE
                WHEN 'X-SMALL' THEN 1 WHEN 'XSMALL' THEN 1
                WHEN 'SMALL' THEN 2 WHEN 'MEDIUM' THEN 4 WHEN 'LARGE' THEN 8
                WHEN 'X-LARGE' THEN 16 WHEN 'XLARGE' THEN 16
                WHEN '2X-LARGE' THEN 32 WHEN '2XLARGE' THEN 32
                WHEN '3X-LARGE' THEN 64 WHEN '3XLARGE' THEN 64
                WHEN '4X-LARGE' THEN 128 WHEN '4XLARGE' THEN 128
                ELSE 4
            END AS credits_per_hour,
            -- Credits used = duration in hours * credits per hour
            (DURATION_SECONDS / 3600.0) * 
            CASE WAREHOUSE_SIZE
                WHEN 'X-SMALL' THEN 1 WHEN 'XSMALL' THEN 1
                WHEN 'SMALL' THEN 2 WHEN 'MEDIUM' THEN 4 WHEN 'LARGE' THEN 8
                WHEN 'X-LARGE' THEN 16 WHEN 'XLARGE' THEN 16
                WHEN '2X-LARGE' THEN 32 WHEN '2XLARGE' THEN 32
                WHEN '3X-LARGE' THEN 64 WHEN '3XLARGE' THEN 64
                WHEN '4X-LARGE' THEN 128 WHEN '4XLARGE' THEN 128
                ELSE 4
            END AS credits_used,
            -- Cost in USD = credits * cost per credit
            (DURATION_SECONDS / 3600.0) * 
            CASE WAREHOUSE_SIZE
                WHEN 'X-SMALL' THEN 1 WHEN 'XSMALL' THEN 1
                WHEN 'SMALL' THEN 2 WHEN 'MEDIUM' THEN 4 WHEN 'LARGE' THEN 8
                WHEN 'X-LARGE' THEN 16 WHEN 'XLARGE' THEN 16
                WHEN '2X-LARGE' THEN 32 WHEN '2XLARGE' THEN 32
                WHEN '3X-LARGE' THEN 64 WHEN '3XLARGE' THEN 64
                WHEN '4X-LARGE' THEN 128 WHEN '4XLARGE' THEN 128
                ELSE 4
            END * :v_credit_cost_usd AS cost_usd
        FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
        WHERE TEST_ID IN (SELECT VALUE::VARCHAR FROM TABLE(FLATTEN(INPUT => :v_test_ids)))
          AND STATUS = 'COMPLETED'
    );
    
    IF (result IS NULL OR result:tests IS NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'error', 'No completed tests found',
            'test_ids', :v_test_ids
        );
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- COST_CALCULATOR_V2: Credit and cost analysis (VARCHAR version for Cortex Agent)
-- =============================================================================
-- This version accepts comma-separated test IDs as VARCHAR, which IS supported
-- by Cortex Agent generic tools. Use this for agent integration.
-- =============================================================================

CREATE OR REPLACE PROCEDURE COST_CALCULATOR_V2(
    p_test_ids VARCHAR,  -- Comma-separated test IDs (e.g., 'id1,id2,id3')
    p_comparison_type VARCHAR DEFAULT 'absolute'
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Calculate cost metrics for tests. Pass test IDs as comma-separated string.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_test_ids VARCHAR := p_test_ids;
    v_comparison_type VARCHAR := LOWER(COALESCE(p_comparison_type, 'absolute'));
    v_credit_cost_usd NUMBER := 3.00;
BEGIN
    SELECT OBJECT_CONSTRUCT(
        'tests', ARRAY_AGG(OBJECT_CONSTRUCT(
            'test_id', TEST_ID,
            'test_name', TEST_NAME,
            'warehouse_size', WAREHOUSE_SIZE,
            'duration_seconds', ROUND(DURATION_SECONDS, 2),
            'qps', ROUND(QPS, 2),
            'total_operations', TOTAL_OPERATIONS,
            'credits_per_hour', credits_per_hour,
            'credits_used', ROUND(credits_used, 4),
            'cost_usd', ROUND(cost_usd, 4),
            'cost_per_query_usd', ROUND(cost_usd / NULLIF(TOTAL_OPERATIONS, 0), 8),
            'cost_per_1k_queries_usd', ROUND(cost_usd / NULLIF(TOTAL_OPERATIONS, 0) * 1000, 4),
            'queries_per_credit', ROUND(TOTAL_OPERATIONS / NULLIF(credits_used, 0), 2)
        )) WITHIN GROUP (ORDER BY cost_usd / NULLIF(TOTAL_OPERATIONS, 0) ASC),
        'summary', OBJECT_CONSTRUCT(
            'total_credits', ROUND(SUM(credits_used), 4),
            'total_cost_usd', ROUND(SUM(cost_usd), 2),
            'total_queries', SUM(TOTAL_OPERATIONS),
            'avg_cost_per_query_usd', ROUND(SUM(cost_usd) / NULLIF(SUM(TOTAL_OPERATIONS), 0), 6),
            'avg_cost_per_1k_queries_usd', ROUND(SUM(cost_usd) / NULLIF(SUM(TOTAL_OPERATIONS), 0) * 1000, 4)
        ),
        'comparison_type', :v_comparison_type,
        'credit_rate_usd', :v_credit_cost_usd,
        'analysis_timestamp', CURRENT_TIMESTAMP()
    ) INTO result
    FROM (
        SELECT
            TEST_ID,
            TEST_NAME,
            WAREHOUSE_SIZE,
            DURATION_SECONDS,
            QPS,
            TOTAL_OPERATIONS,
            CASE WAREHOUSE_SIZE
                WHEN 'X-SMALL' THEN 1 WHEN 'XSMALL' THEN 1
                WHEN 'SMALL' THEN 2 WHEN 'MEDIUM' THEN 4 WHEN 'LARGE' THEN 8
                WHEN 'X-LARGE' THEN 16 WHEN 'XLARGE' THEN 16
                WHEN '2X-LARGE' THEN 32 WHEN '2XLARGE' THEN 32
                WHEN '3X-LARGE' THEN 64 WHEN '3XLARGE' THEN 64
                WHEN '4X-LARGE' THEN 128 WHEN '4XLARGE' THEN 128
                ELSE 4
            END AS credits_per_hour,
            (DURATION_SECONDS / 3600.0) * 
            CASE WAREHOUSE_SIZE
                WHEN 'X-SMALL' THEN 1 WHEN 'XSMALL' THEN 1
                WHEN 'SMALL' THEN 2 WHEN 'MEDIUM' THEN 4 WHEN 'LARGE' THEN 8
                WHEN 'X-LARGE' THEN 16 WHEN 'XLARGE' THEN 16
                WHEN '2X-LARGE' THEN 32 WHEN '2XLARGE' THEN 32
                WHEN '3X-LARGE' THEN 64 WHEN '3XLARGE' THEN 64
                WHEN '4X-LARGE' THEN 128 WHEN '4XLARGE' THEN 128
                ELSE 4
            END AS credits_used,
            (DURATION_SECONDS / 3600.0) * 
            CASE WAREHOUSE_SIZE
                WHEN 'X-SMALL' THEN 1 WHEN 'XSMALL' THEN 1
                WHEN 'SMALL' THEN 2 WHEN 'MEDIUM' THEN 4 WHEN 'LARGE' THEN 8
                WHEN 'X-LARGE' THEN 16 WHEN 'XLARGE' THEN 16
                WHEN '2X-LARGE' THEN 32 WHEN '2XLARGE' THEN 32
                WHEN '3X-LARGE' THEN 64 WHEN '3XLARGE' THEN 64
                WHEN '4X-LARGE' THEN 128 WHEN '4XLARGE' THEN 128
                ELSE 4
            END * :v_credit_cost_usd AS cost_usd
        FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
        WHERE TEST_ID IN (SELECT TRIM(VALUE) FROM TABLE(SPLIT_TO_TABLE(:v_test_ids, ',')))
          AND STATUS = 'COMPLETED'
    );
    
    IF (result IS NULL OR result:tests IS NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'error', 'No completed tests found',
            'test_ids', :v_test_ids
        );
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- Validation: Show created procedures
-- =============================================================================
SHOW PROCEDURES LIKE 'CALCULATE_%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;
SHOW PROCEDURES LIKE 'MANN_%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;
SHOW PROCEDURES LIKE 'COMPARE_%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;
SHOW PROCEDURES LIKE 'STATISTICAL_%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;
SHOW PROCEDURES LIKE 'COST_%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;
