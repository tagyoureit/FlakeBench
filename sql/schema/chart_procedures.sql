-- =============================================================================
-- Unistore Benchmark - Chart Procedures for Cortex Agent
-- =============================================================================
-- These stored procedures return chart-ready JSON data for visualization.
-- They are designed to be called by the Cortex Agent as tools and match
-- the Python API endpoints for consistency.
--
-- Database: FLAKEBENCH
-- Schema: TEST_RESULTS
--
-- Updated: 2026-02-12
-- Changes: All SPs now match Python API functionality exactly
-- =============================================================================

USE DATABASE FLAKEBENCH;
USE SCHEMA TEST_RESULTS;

-- =============================================================================
-- LIST_RECENT_TESTS: List recent benchmark tests
-- =============================================================================
-- Returns recent tests with scaling config, load mode, and workload mix.
-- Only returns parent runs (RUN_ID = TEST_ID) or single tests.
-- =============================================================================

CREATE OR REPLACE PROCEDURE LIST_RECENT_TESTS(
    p_limit NUMBER DEFAULT 20
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'List recent tests matching Python /tests endpoint. Returns parent runs only with scaling, load mode, and workload mix.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_limit INTEGER;
BEGIN
    v_limit := LEAST(COALESCE(p_limit, 20), 50);
    
    SELECT OBJECT_CONSTRUCT(
        'results', results_arr,
        'total_pages', 1
    ) INTO result
    FROM (
        SELECT ARRAY_AGG(
            OBJECT_CONSTRUCT(
                'test_id', TEST_ID,
                'run_id', RUN_ID,
                'test_name', TEST_NAME,
                'table_type', TABLE_TYPE,
                'warehouse_size', WAREHOUSE_SIZE,
                'created_at', TO_VARCHAR(START_TIME, 'YYYY-MM-DD"T"HH24:MI:SS.FF3"Z"'),
                'ops_per_sec', QPS,
                'p95_latency', P95_LATENCY_MS,
                'p99_latency', P99_LATENCY_MS,
                'error_rate', ERROR_RATE * 100.0,
                'status', STATUS,
                'concurrent_connections', CONCURRENT_CONNECTIONS,
                'duration', DURATION_SECONDS,
                'failure_reason', FAILURE_REASON,
                'enrichment_status', ENRICHMENT_STATUS,
                -- Load mode fields
                'load_mode', COALESCE(TEST_CONFIG:template_config:load_mode::STRING, 'CONCURRENCY'),
                'target_qps', TEST_CONFIG:template_config:target_qps::NUMBER,
                'start_concurrency', TEST_CONFIG:template_config:start_concurrency::NUMBER,
                'concurrency_increment', TEST_CONFIG:template_config:concurrency_increment::NUMBER,
                -- Scaling config
                'scaling', TEST_CONFIG:template_config:scaling,
                -- Workload mix
                'custom_point_lookup_pct', TEST_CONFIG:template_config:custom_point_lookup_pct::NUMBER,
                'custom_range_scan_pct', TEST_CONFIG:template_config:custom_range_scan_pct::NUMBER,
                'custom_insert_pct', TEST_CONFIG:template_config:custom_insert_pct::NUMBER,
                'custom_update_pct', TEST_CONFIG:template_config:custom_update_pct::NUMBER
            )
        ) WITHIN GROUP (ORDER BY START_TIME DESC) AS results_arr
        FROM (
            SELECT * FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
            WHERE RUN_ID IS NULL OR RUN_ID = TEST_ID  -- Only parent runs or single tests
            ORDER BY START_TIME DESC
            LIMIT :v_limit
        )
    );
    
    IF (result IS NULL) THEN
        RETURN OBJECT_CONSTRUCT('results', ARRAY_CONSTRUCT(), 'total_pages', 1);
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- GET_TEST_SUMMARY: Comprehensive test summary
-- =============================================================================
-- Returns full test details including config, results, latencies by operation
-- type, parent run info, and enrichment status.
-- Matches Python /{test_id} endpoint output structure.
-- =============================================================================

CREATE OR REPLACE PROCEDURE GET_TEST_SUMMARY(
    p_test_id VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Get comprehensive test summary matching Python /{test_id} endpoint. Returns test config, results, latencies, parent run info, and enrichment status.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_test_id VARCHAR := p_test_id;
    v_run_id VARCHAR;
    v_is_parent BOOLEAN := FALSE;
BEGIN
    -- Check if parent run
    SELECT RUN_ID INTO v_run_id
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = :v_test_id;
    
    IF (v_run_id IS NOT NULL AND v_run_id = :v_test_id) THEN
        v_is_parent := TRUE;
    END IF;
    
    SELECT OBJECT_CONSTRUCT(
        'test_id', TEST_ID,
        'run_id', RUN_ID,
        'is_parent_run', IFF(RUN_ID = TEST_ID, TRUE, FALSE),
        'test_name', TEST_NAME,
        'scenario_name', SCENARIO_NAME,
        'table_name', TABLE_NAME,
        'table_type', TABLE_TYPE,
        'warehouse', WAREHOUSE,
        'warehouse_size', WAREHOUSE_SIZE,
        'status', STATUS,
        'start_time', START_TIME,
        'end_time', END_TIME,
        'duration_seconds', DURATION_SECONDS,
        'duration', DURATION_SECONDS,
        'concurrent_connections', CONCURRENT_CONNECTIONS,
        'query_tag', QUERY_TAG,
        'failure_reason', FAILURE_REASON,
        'enrichment_status', ENRICHMENT_STATUS,
        'enrichment_error', ENRICHMENT_ERROR,
        -- Load mode and scaling from config
        'load_mode', COALESCE(TEST_CONFIG:template_config:load_mode::STRING, 'CONCURRENCY'),
        'target_qps', TEST_CONFIG:template_config:target_qps::NUMBER,
        'start_concurrency', TEST_CONFIG:template_config:start_concurrency::NUMBER,
        'concurrency_increment', TEST_CONFIG:template_config:concurrency_increment::NUMBER,
        'scaling', TEST_CONFIG:template_config:scaling,
        -- Workload mix
        'custom_point_lookup_pct', TEST_CONFIG:template_config:custom_point_lookup_pct::NUMBER,
        'custom_range_scan_pct', TEST_CONFIG:template_config:custom_range_scan_pct::NUMBER,
        'custom_insert_pct', TEST_CONFIG:template_config:custom_insert_pct::NUMBER,
        'custom_update_pct', TEST_CONFIG:template_config:custom_update_pct::NUMBER,
        -- Operations summary
        'total_operations', TOTAL_OPERATIONS,
        'read_operations', READ_OPERATIONS,
        'write_operations', WRITE_OPERATIONS,
        'failed_operations', FAILED_OPERATIONS,
        'ops_per_sec', QPS,
        'reads_per_second', READS_PER_SECOND,
        'writes_per_second', WRITES_PER_SECOND,
        'error_rate', ERROR_RATE,
        -- Overall latency
        'avg_latency_ms', AVG_LATENCY_MS,
        'p50_latency', P50_LATENCY_MS,
        'p50_latency_ms', P50_LATENCY_MS,
        'p90_latency_ms', P90_LATENCY_MS,
        'p95_latency', P95_LATENCY_MS,
        'p95_latency_ms', P95_LATENCY_MS,
        'p99_latency', P99_LATENCY_MS,
        'p99_latency_ms', P99_LATENCY_MS,
        'min_latency_ms', MIN_LATENCY_MS,
        'max_latency_ms', MAX_LATENCY_MS,
        -- Read latencies
        'read_p50_latency_ms', READ_P50_LATENCY_MS,
        'read_p95_latency_ms', READ_P95_LATENCY_MS,
        'read_p99_latency_ms', READ_P99_LATENCY_MS,
        'read_min_latency_ms', READ_MIN_LATENCY_MS,
        'read_max_latency_ms', READ_MAX_LATENCY_MS,
        -- Write latencies
        'write_p50_latency_ms', WRITE_P50_LATENCY_MS,
        'write_p95_latency_ms', WRITE_P95_LATENCY_MS,
        'write_p99_latency_ms', WRITE_P99_LATENCY_MS,
        'write_min_latency_ms', WRITE_MIN_LATENCY_MS,
        'write_max_latency_ms', WRITE_MAX_LATENCY_MS,
        -- Point lookup latencies
        'point_lookup_p50_latency_ms', POINT_LOOKUP_P50_LATENCY_MS,
        'point_lookup_p95_latency_ms', POINT_LOOKUP_P95_LATENCY_MS,
        'point_lookup_p99_latency_ms', POINT_LOOKUP_P99_LATENCY_MS,
        'point_lookup_min_latency_ms', POINT_LOOKUP_MIN_LATENCY_MS,
        'point_lookup_max_latency_ms', POINT_LOOKUP_MAX_LATENCY_MS,
        -- Range scan latencies
        'range_scan_p50_latency_ms', RANGE_SCAN_P50_LATENCY_MS,
        'range_scan_p95_latency_ms', RANGE_SCAN_P95_LATENCY_MS,
        'range_scan_p99_latency_ms', RANGE_SCAN_P99_LATENCY_MS,
        'range_scan_min_latency_ms', RANGE_SCAN_MIN_LATENCY_MS,
        'range_scan_max_latency_ms', RANGE_SCAN_MAX_LATENCY_MS,
        -- Insert latencies
        'insert_p50_latency_ms', INSERT_P50_LATENCY_MS,
        'insert_p95_latency_ms', INSERT_P95_LATENCY_MS,
        'insert_p99_latency_ms', INSERT_P99_LATENCY_MS,
        'insert_min_latency_ms', INSERT_MIN_LATENCY_MS,
        'insert_max_latency_ms', INSERT_MAX_LATENCY_MS,
        -- Update latencies
        'update_p50_latency_ms', UPDATE_P50_LATENCY_MS,
        'update_p95_latency_ms', UPDATE_P95_LATENCY_MS,
        'update_p99_latency_ms', UPDATE_P99_LATENCY_MS,
        'update_min_latency_ms', UPDATE_MIN_LATENCY_MS,
        'update_max_latency_ms', UPDATE_MAX_LATENCY_MS,
        -- Find max result (if applicable)
        'find_max_result', FIND_MAX_RESULT,
        -- Latency spread (P95/P50 ratio)
        'latency_spread_ratio', IFF(P50_LATENCY_MS > 0, ROUND(P95_LATENCY_MS / P50_LATENCY_MS, 1), NULL),
        'latency_spread_warning', IFF(P50_LATENCY_MS > 0 AND P95_LATENCY_MS / P50_LATENCY_MS > 5.0, TRUE, FALSE),
        -- Multi-worker info
        'latency_aggregation_method', IFF(RUN_ID = TEST_ID, 'slowest_worker_approximation', NULL)
    ) INTO result
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = :v_test_id;
    
    IF (result IS NULL) THEN
        RETURN OBJECT_CONSTRUCT('error', 'Test not found', 'test_id', :v_test_id);
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- GET_LATENCY_BREAKDOWN: Detailed latency breakdown by operation type
-- =============================================================================
-- Returns read/write aggregates, duration_seconds, ops_per_second,
-- and per-query-type breakdown. Supports parent run aggregation.
-- Matches Python /{test_id}/latency-breakdown endpoint.
-- =============================================================================

CREATE OR REPLACE PROCEDURE GET_LATENCY_BREAKDOWN(
    p_test_id VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Get detailed latency breakdown matching Python API. Returns read/write aggregates, duration_seconds, ops_per_second, per_query_type breakdown, and parent run support.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_test_id VARCHAR := p_test_id;
    v_run_id VARCHAR;
    v_is_parent BOOLEAN := FALSE;
BEGIN
    -- Check if this is a parent run
    SELECT RUN_ID INTO v_run_id
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = :v_test_id;
    
    IF (v_run_id IS NOT NULL AND v_run_id = :v_test_id) THEN
        v_is_parent := TRUE;
    END IF;
    
    -- Use a single comprehensive query with dynamic test filtering
    IF (v_is_parent) THEN
        -- Parent run: aggregate from all child tests
        SELECT OBJECT_CONSTRUCT(
            'test_id', :v_test_id,
            'available', TRUE,
            'is_parent_run', TRUE,
            'duration_seconds', duration_seconds,
            'total_operations', total_operations,
            'ops_per_second', ROUND(IFF(duration_seconds > 0, total_operations / duration_seconds, 0), 2),
            'read_operations', read_ops,
            'write_operations', write_ops,
            'per_query_type', per_query_type
        ) INTO result
        FROM (
            SELECT
                MAX(duration_seconds) AS duration_seconds,
                SUM(CASE WHEN stat_type = 'RW' THEN query_count ELSE 0 END) AS total_operations,
                OBJECT_CONSTRUCT(
                    'count', MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN query_count END),
                    'p50_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN p50_ms END), 2),
                    'p95_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN p95_ms END), 2),
                    'p99_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN p99_ms END), 2),
                    'min_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN min_ms END), 2),
                    'max_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN max_ms END), 2),
                    'avg_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN avg_ms END), 2),
                    'ops_per_second', ROUND(IFF(MAX(duration_seconds) > 0,
                        MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN query_count END) / MAX(duration_seconds), 0), 2)
                ) AS read_ops,
                OBJECT_CONSTRUCT(
                    'count', MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN query_count END),
                    'p50_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN p50_ms END), 2),
                    'p95_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN p95_ms END), 2),
                    'p99_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN p99_ms END), 2),
                    'min_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN min_ms END), 2),
                    'max_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN max_ms END), 2),
                    'avg_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN avg_ms END), 2),
                    'ops_per_second', ROUND(IFF(MAX(duration_seconds) > 0,
                        MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN query_count END) / MAX(duration_seconds), 0), 2)
                ) AS write_ops,
                ARRAY_AGG(
                    CASE WHEN stat_type = 'QK' THEN
                        OBJECT_CONSTRUCT(
                            'query_type', category,
                            'count', query_count,
                            'p50_ms', ROUND(p50_ms, 2),
                            'p95_ms', ROUND(p95_ms, 2),
                            'p99_ms', ROUND(p99_ms, 2),
                            'min_ms', ROUND(min_ms, 2),
                            'max_ms', ROUND(max_ms, 2),
                            'avg_ms', ROUND(avg_ms, 2)
                        )
                    END
                ) WITHIN GROUP (ORDER BY 
                    CASE category 
                        WHEN 'POINT_LOOKUP' THEN 1 
                        WHEN 'RANGE_SCAN' THEN 2 
                        WHEN 'INSERT' THEN 3 
                        WHEN 'UPDATE' THEN 4 
                        ELSE 5 
                    END
                ) AS per_query_type
            FROM (
                WITH raw_data AS (
                    SELECT
                        APP_ELAPSED_MS,
                        QUERY_KIND,
                        CASE
                            WHEN UPPER(REPLACE(QUERY_KIND, '_', ' ')) IN ('POINT LOOKUP', 'RANGE SCAN', 'SELECT', 'READ', 'POINT_LOOKUP', 'RANGE_SCAN') THEN 'READ'
                            WHEN UPPER(REPLACE(QUERY_KIND, '_', ' ')) IN ('INSERT', 'UPDATE', 'DELETE', 'WRITE') THEN 'WRITE'
                            ELSE 'OTHER'
                        END AS OPERATION_TYPE,
                        START_TIME
                    FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS
                    WHERE TEST_ID IN (SELECT TEST_ID FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS WHERE RUN_ID = :v_test_id)
                      AND COALESCE(WARMUP, FALSE) = FALSE
                      AND SUCCESS = TRUE
                      AND APP_ELAPSED_MS IS NOT NULL
                ),
                duration_info AS (
                    SELECT TIMESTAMPDIFF('SECOND', MIN(START_TIME), MAX(START_TIME)) AS duration_seconds
                    FROM raw_data
                ),
                rw_stats AS (
                    SELECT
                        'RW' AS stat_type,
                        OPERATION_TYPE AS category,
                        COUNT(*) AS query_count,
                        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p50_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p95_ms,
                        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p99_ms,
                        MIN(APP_ELAPSED_MS) AS min_ms,
                        MAX(APP_ELAPSED_MS) AS max_ms,
                        AVG(APP_ELAPSED_MS) AS avg_ms,
                        (SELECT duration_seconds FROM duration_info) AS duration_seconds
                    FROM raw_data
                    WHERE OPERATION_TYPE IN ('READ', 'WRITE')
                    GROUP BY OPERATION_TYPE
                ),
                qk_stats AS (
                    SELECT
                        'QK' AS stat_type,
                        QUERY_KIND AS category,
                        COUNT(*) AS query_count,
                        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p50_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p95_ms,
                        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p99_ms,
                        MIN(APP_ELAPSED_MS) AS min_ms,
                        MAX(APP_ELAPSED_MS) AS max_ms,
                        AVG(APP_ELAPSED_MS) AS avg_ms,
                        (SELECT duration_seconds FROM duration_info) AS duration_seconds
                    FROM raw_data
                    GROUP BY QUERY_KIND
                )
                SELECT * FROM rw_stats
                UNION ALL
                SELECT * FROM qk_stats
            )
        );
    ELSE
        -- Single test: query directly
        SELECT OBJECT_CONSTRUCT(
            'test_id', :v_test_id,
            'available', TRUE,
            'is_parent_run', FALSE,
            'duration_seconds', duration_seconds,
            'total_operations', total_operations,
            'ops_per_second', ROUND(IFF(duration_seconds > 0, total_operations / duration_seconds, 0), 2),
            'read_operations', read_ops,
            'write_operations', write_ops,
            'per_query_type', per_query_type
        ) INTO result
        FROM (
            SELECT
                MAX(duration_seconds) AS duration_seconds,
                SUM(CASE WHEN stat_type = 'RW' THEN query_count ELSE 0 END) AS total_operations,
                OBJECT_CONSTRUCT(
                    'count', MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN query_count END),
                    'p50_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN p50_ms END), 2),
                    'p95_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN p95_ms END), 2),
                    'p99_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN p99_ms END), 2),
                    'min_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN min_ms END), 2),
                    'max_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN max_ms END), 2),
                    'avg_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN avg_ms END), 2),
                    'ops_per_second', ROUND(IFF(MAX(duration_seconds) > 0,
                        MAX(CASE WHEN stat_type = 'RW' AND category = 'READ' THEN query_count END) / MAX(duration_seconds), 0), 2)
                ) AS read_ops,
                OBJECT_CONSTRUCT(
                    'count', MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN query_count END),
                    'p50_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN p50_ms END), 2),
                    'p95_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN p95_ms END), 2),
                    'p99_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN p99_ms END), 2),
                    'min_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN min_ms END), 2),
                    'max_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN max_ms END), 2),
                    'avg_ms', ROUND(MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN avg_ms END), 2),
                    'ops_per_second', ROUND(IFF(MAX(duration_seconds) > 0,
                        MAX(CASE WHEN stat_type = 'RW' AND category = 'WRITE' THEN query_count END) / MAX(duration_seconds), 0), 2)
                ) AS write_ops,
                ARRAY_AGG(
                    CASE WHEN stat_type = 'QK' THEN
                        OBJECT_CONSTRUCT(
                            'query_type', category,
                            'count', query_count,
                            'p50_ms', ROUND(p50_ms, 2),
                            'p95_ms', ROUND(p95_ms, 2),
                            'p99_ms', ROUND(p99_ms, 2),
                            'min_ms', ROUND(min_ms, 2),
                            'max_ms', ROUND(max_ms, 2),
                            'avg_ms', ROUND(avg_ms, 2)
                        )
                    END
                ) WITHIN GROUP (ORDER BY 
                    CASE category 
                        WHEN 'POINT_LOOKUP' THEN 1 
                        WHEN 'RANGE_SCAN' THEN 2 
                        WHEN 'INSERT' THEN 3 
                        WHEN 'UPDATE' THEN 4 
                        ELSE 5 
                    END
                ) AS per_query_type
            FROM (
                WITH raw_data AS (
                    SELECT
                        APP_ELAPSED_MS,
                        QUERY_KIND,
                        CASE
                            WHEN UPPER(REPLACE(QUERY_KIND, '_', ' ')) IN ('POINT LOOKUP', 'RANGE SCAN', 'SELECT', 'READ', 'POINT_LOOKUP', 'RANGE_SCAN') THEN 'READ'
                            WHEN UPPER(REPLACE(QUERY_KIND, '_', ' ')) IN ('INSERT', 'UPDATE', 'DELETE', 'WRITE') THEN 'WRITE'
                            ELSE 'OTHER'
                        END AS OPERATION_TYPE,
                        START_TIME
                    FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS
                    WHERE TEST_ID = :v_test_id
                      AND COALESCE(WARMUP, FALSE) = FALSE
                      AND SUCCESS = TRUE
                      AND APP_ELAPSED_MS IS NOT NULL
                ),
                duration_info AS (
                    SELECT TIMESTAMPDIFF('SECOND', MIN(START_TIME), MAX(START_TIME)) AS duration_seconds
                    FROM raw_data
                ),
                rw_stats AS (
                    SELECT
                        'RW' AS stat_type,
                        OPERATION_TYPE AS category,
                        COUNT(*) AS query_count,
                        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p50_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p95_ms,
                        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p99_ms,
                        MIN(APP_ELAPSED_MS) AS min_ms,
                        MAX(APP_ELAPSED_MS) AS max_ms,
                        AVG(APP_ELAPSED_MS) AS avg_ms,
                        (SELECT duration_seconds FROM duration_info) AS duration_seconds
                    FROM raw_data
                    WHERE OPERATION_TYPE IN ('READ', 'WRITE')
                    GROUP BY OPERATION_TYPE
                ),
                qk_stats AS (
                    SELECT
                        'QK' AS stat_type,
                        QUERY_KIND AS category,
                        COUNT(*) AS query_count,
                        PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p50_ms,
                        PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p95_ms,
                        PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p99_ms,
                        MIN(APP_ELAPSED_MS) AS min_ms,
                        MAX(APP_ELAPSED_MS) AS max_ms,
                        AVG(APP_ELAPSED_MS) AS avg_ms,
                        (SELECT duration_seconds FROM duration_info) AS duration_seconds
                    FROM raw_data
                    GROUP BY QUERY_KIND
                )
                SELECT * FROM rw_stats
                UNION ALL
                SELECT * FROM qk_stats
            )
        );
    END IF;
    
    IF (result IS NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'test_id', :v_test_id,
            'available', FALSE,
            'message', 'No query execution data available'
        );
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- GET_ERROR_TIMELINE: Error distribution over time
-- =============================================================================
-- Returns error counts per 5-second bucket with warmup detection and
-- per-operation-type breakdown. Supports parent run aggregation.
-- Matches Python /{test_id}/error-timeline endpoint.
-- =============================================================================

CREATE OR REPLACE PROCEDURE GET_ERROR_TIMELINE(
    p_test_id VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Get error counts bucketed by time for visualizing error trends. Returns per 5-second bucket breakdown with warmup detection and parent run support.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_test_id VARCHAR := p_test_id;
    v_run_id VARCHAR;
    v_is_parent BOOLEAN := FALSE;
BEGIN
    -- Check if this is a parent run
    SELECT RUN_ID INTO v_run_id
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = :v_test_id;
    
    IF (v_run_id IS NOT NULL AND v_run_id = :v_test_id) THEN
        v_is_parent := TRUE;
    END IF;
    
    IF (v_is_parent) THEN
        -- Parent run: aggregate from all child tests
        SELECT OBJECT_CONSTRUCT(
            'test_id', :v_test_id,
            'available', IFF(ARRAY_SIZE(points) > 0, TRUE, FALSE),
            'is_parent_run', TRUE,
            'bucket_size_seconds', 5,
            'total_queries', total_queries,
            'total_errors', total_errors,
            'overall_error_rate_pct', ROUND(IFF(total_queries > 0, total_errors * 100.0 / total_queries, 0), 2),
            'warmup_end_elapsed_seconds', warmup_end_bucket,
            'points', points
        ) INTO result
        FROM (
            SELECT
                SUM(bucket_total) AS total_queries,
                SUM(bucket_errors) AS total_errors,
                MIN(CASE WHEN is_warmup = 0 THEN bucket_seconds END) AS warmup_end_bucket,
                ARRAY_AGG(
                    OBJECT_CONSTRUCT(
                        'elapsed_seconds', bucket_seconds,
                        'total_queries', bucket_total,
                        'error_count', bucket_errors,
                        'error_rate_pct', ROUND(IFF(bucket_total > 0, bucket_errors * 100.0 / bucket_total, 0), 2),
                        'point_lookup_errors', pl_errors,
                        'range_scan_errors', rs_errors,
                        'insert_errors', ins_errors,
                        'update_errors', upd_errors,
                        'warmup', IFF(is_warmup = 1, TRUE, FALSE)
                    )
                ) WITHIN GROUP (ORDER BY bucket_seconds ASC) AS points
            FROM (
                WITH query_bounds AS (
                    SELECT
                        MIN(qe.START_TIME) AS FIRST_QUERY,
                        MAX(qe.START_TIME) AS LAST_QUERY,
                        MIN(CASE WHEN COALESCE(qe.WARMUP, FALSE) = FALSE THEN qe.START_TIME END) AS FIRST_MEASUREMENT
                    FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS qe
                    WHERE qe.TEST_ID IN (SELECT TEST_ID FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS WHERE RUN_ID = :v_test_id)
                )
                SELECT
                    FLOOR(DATEDIFF('second', qb.FIRST_QUERY, qe.START_TIME) / 5) * 5 AS bucket_seconds,
                    COUNT(*) AS bucket_total,
                    SUM(CASE WHEN qe.SUCCESS = FALSE THEN 1 ELSE 0 END) AS bucket_errors,
                    SUM(CASE WHEN qe.SUCCESS = FALSE AND qe.QUERY_KIND = 'POINT_LOOKUP' THEN 1 ELSE 0 END) AS pl_errors,
                    SUM(CASE WHEN qe.SUCCESS = FALSE AND qe.QUERY_KIND = 'RANGE_SCAN' THEN 1 ELSE 0 END) AS rs_errors,
                    SUM(CASE WHEN qe.SUCCESS = FALSE AND qe.QUERY_KIND = 'INSERT' THEN 1 ELSE 0 END) AS ins_errors,
                    SUM(CASE WHEN qe.SUCCESS = FALSE AND qe.QUERY_KIND = 'UPDATE' THEN 1 ELSE 0 END) AS upd_errors,
                    MAX(CASE WHEN qe.START_TIME < qb.FIRST_MEASUREMENT THEN 1 ELSE 0 END) AS is_warmup
                FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS qe
                CROSS JOIN query_bounds qb
                WHERE qe.TEST_ID IN (SELECT TEST_ID FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS WHERE RUN_ID = :v_test_id)
                GROUP BY FLOOR(DATEDIFF('second', qb.FIRST_QUERY, qe.START_TIME) / 5) * 5
            )
        );
    ELSE
        -- Single test: query directly
        SELECT OBJECT_CONSTRUCT(
            'test_id', :v_test_id,
            'available', IFF(ARRAY_SIZE(points) > 0, TRUE, FALSE),
            'is_parent_run', FALSE,
            'bucket_size_seconds', 5,
            'total_queries', total_queries,
            'total_errors', total_errors,
            'overall_error_rate_pct', ROUND(IFF(total_queries > 0, total_errors * 100.0 / total_queries, 0), 2),
            'warmup_end_elapsed_seconds', warmup_end_bucket,
            'points', points
        ) INTO result
        FROM (
            SELECT
                SUM(bucket_total) AS total_queries,
                SUM(bucket_errors) AS total_errors,
                MIN(CASE WHEN is_warmup = 0 THEN bucket_seconds END) AS warmup_end_bucket,
                ARRAY_AGG(
                    OBJECT_CONSTRUCT(
                        'elapsed_seconds', bucket_seconds,
                        'total_queries', bucket_total,
                        'error_count', bucket_errors,
                        'error_rate_pct', ROUND(IFF(bucket_total > 0, bucket_errors * 100.0 / bucket_total, 0), 2),
                        'point_lookup_errors', pl_errors,
                        'range_scan_errors', rs_errors,
                        'insert_errors', ins_errors,
                        'update_errors', upd_errors,
                        'warmup', IFF(is_warmup = 1, TRUE, FALSE)
                    )
                ) WITHIN GROUP (ORDER BY bucket_seconds ASC) AS points
            FROM (
                WITH query_bounds AS (
                    SELECT
                        MIN(qe.START_TIME) AS FIRST_QUERY,
                        MAX(qe.START_TIME) AS LAST_QUERY,
                        MIN(CASE WHEN COALESCE(qe.WARMUP, FALSE) = FALSE THEN qe.START_TIME END) AS FIRST_MEASUREMENT
                    FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS qe
                    WHERE qe.TEST_ID = :v_test_id
                )
                SELECT
                    FLOOR(DATEDIFF('second', qb.FIRST_QUERY, qe.START_TIME) / 5) * 5 AS bucket_seconds,
                    COUNT(*) AS bucket_total,
                    SUM(CASE WHEN qe.SUCCESS = FALSE THEN 1 ELSE 0 END) AS bucket_errors,
                    SUM(CASE WHEN qe.SUCCESS = FALSE AND qe.QUERY_KIND = 'POINT_LOOKUP' THEN 1 ELSE 0 END) AS pl_errors,
                    SUM(CASE WHEN qe.SUCCESS = FALSE AND qe.QUERY_KIND = 'RANGE_SCAN' THEN 1 ELSE 0 END) AS rs_errors,
                    SUM(CASE WHEN qe.SUCCESS = FALSE AND qe.QUERY_KIND = 'INSERT' THEN 1 ELSE 0 END) AS ins_errors,
                    SUM(CASE WHEN qe.SUCCESS = FALSE AND qe.QUERY_KIND = 'UPDATE' THEN 1 ELSE 0 END) AS upd_errors,
                    MAX(CASE WHEN qe.START_TIME < qb.FIRST_MEASUREMENT THEN 1 ELSE 0 END) AS is_warmup
                FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS qe
                CROSS JOIN query_bounds qb
                WHERE qe.TEST_ID = :v_test_id
                GROUP BY FLOOR(DATEDIFF('second', qb.FIRST_QUERY, qe.START_TIME) / 5) * 5
            )
        );
    END IF;
    
    IF (result IS NULL OR result:points IS NULL OR ARRAY_SIZE(result:points) = 0) THEN
        RETURN OBJECT_CONSTRUCT(
            'test_id', :v_test_id,
            'available', FALSE,
            'message', 'No query execution data available',
            'points', ARRAY_CONSTRUCT()
        );
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- GET_METRICS_TIMESERIES: Time-series metrics for dashboard charts
-- =============================================================================
-- Returns aggregated time-series data for QPS, latency, and connections.
-- Supports warmup detection and multi-worker aggregation.
-- Matches Python /{test_id}/metrics endpoint.
-- =============================================================================

CREATE OR REPLACE PROCEDURE GET_METRICS_TIMESERIES(
    p_test_id VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Get time-series metrics for a test. Matches Python /metrics endpoint with snapshots array, parent run support, warmup detection.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    v_test_id VARCHAR := p_test_id;
    v_run_id VARCHAR;
    v_is_parent BOOLEAN := FALSE;
BEGIN
    -- Get run_id and check if parent run
    SELECT RUN_ID INTO v_run_id
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = :v_test_id
    LIMIT 1;
    
    IF (v_run_id IS NULL) THEN
        RETURN OBJECT_CONSTRUCT('error', 'Test not found', 'test_id', :v_test_id);
    END IF;
    
    IF (v_run_id = :v_test_id) THEN
        v_is_parent := TRUE;
    END IF;
    
    -- Build metrics timeseries matching Python API structure
    SELECT OBJECT_CONSTRUCT(
        'test_id', :v_test_id,
        'count', ARRAY_SIZE(snapshots),
        'latency_aggregation_method', 'slowest_worker_approximation',
        'warmup_end_elapsed_seconds', warmup_end_elapsed,
        'smoothing_applied', IFF(worker_count > 1, TRUE, FALSE),
        'snapshots', snapshots
    ) INTO result
    FROM (
        SELECT
            MIN(CASE WHEN phase = 'MEASUREMENT' THEN elapsed_seconds END) AS warmup_end_elapsed,
            MAX(worker_count) AS worker_count,
            ARRAY_AGG(
                OBJECT_CONSTRUCT(
                    'timestamp', timestamp,
                    'elapsed_seconds', elapsed_seconds,
                    'ops_per_sec', qps,
                    'p50_latency', p50_latency_ms,
                    'p95_latency', p95_latency_ms,
                    'p99_latency', p99_latency_ms,
                    'active_connections', active_connections,
                    'target_workers', target_connections,
                    'warmup', IFF(phase = 'WARMUP', TRUE, FALSE),
                    'sf_running', COALESCE(sf_running, 0),
                    'sf_running_read', COALESCE(sf_running_read, 0),
                    'sf_running_write', COALESCE(sf_running_write, 0),
                    'sf_queued', COALESCE(sf_queued, 0),
                    'sf_blocked', COALESCE(sf_blocked, 0),
                    'app_point_lookup_ops_sec', COALESCE(app_pl_ops, 0),
                    'app_range_scan_ops_sec', COALESCE(app_rs_ops, 0),
                    'app_insert_ops_sec', COALESCE(app_ins_ops, 0),
                    'app_update_ops_sec', COALESCE(app_upd_ops, 0),
                    'resources_cpu_percent', COALESCE(cpu_pct, 0),
                    'resources_memory_mb', COALESCE(mem_mb, 0)
                )
            ) WITHIN GROUP (ORDER BY elapsed_seconds ASC) AS snapshots
        FROM (
            -- Aggregate by second bucket for multi-worker runs
            SELECT
                MIN(TIMESTAMP) AS timestamp,
                ROUND(ELAPSED_SECONDS) AS elapsed_seconds,
                SUM(QPS) AS qps,
                AVG(P50_LATENCY_MS) AS p50_latency_ms,
                MAX(P95_LATENCY_MS) AS p95_latency_ms,
                MAX(P99_LATENCY_MS) AS p99_latency_ms,
                SUM(ACTIVE_CONNECTIONS) AS active_connections,
                SUM(TARGET_CONNECTIONS) AS target_connections,
                MAX(PHASE) AS phase,
                COUNT(DISTINCT WORKER_ID) AS worker_count,
                -- Parse custom metrics safely
                SUM(CUSTOM_METRICS:sf_bench:running::NUMBER) AS sf_running,
                SUM(CUSTOM_METRICS:sf_bench:running_read::NUMBER) AS sf_running_read,
                SUM(CUSTOM_METRICS:sf_bench:running_write::NUMBER) AS sf_running_write,
                SUM(CUSTOM_METRICS:warehouse:queued::NUMBER) AS sf_queued,
                SUM(CUSTOM_METRICS:sf_bench:blocked::NUMBER) AS sf_blocked,
                -- Compute breakdown ops from total QPS and counts
                SUM(
                    IFF(CUSTOM_METRICS:app_ops_breakdown:total_count::NUMBER > 0,
                        QPS * CUSTOM_METRICS:app_ops_breakdown:point_lookup_count::NUMBER / CUSTOM_METRICS:app_ops_breakdown:total_count::NUMBER, 
                        0)
                ) AS app_pl_ops,
                SUM(
                    IFF(CUSTOM_METRICS:app_ops_breakdown:total_count::NUMBER > 0,
                        QPS * CUSTOM_METRICS:app_ops_breakdown:range_scan_count::NUMBER / CUSTOM_METRICS:app_ops_breakdown:total_count::NUMBER, 
                        0)
                ) AS app_rs_ops,
                SUM(
                    IFF(CUSTOM_METRICS:app_ops_breakdown:total_count::NUMBER > 0,
                        QPS * CUSTOM_METRICS:app_ops_breakdown:insert_count::NUMBER / CUSTOM_METRICS:app_ops_breakdown:total_count::NUMBER, 
                        0)
                ) AS app_ins_ops,
                SUM(
                    IFF(CUSTOM_METRICS:app_ops_breakdown:total_count::NUMBER > 0,
                        QPS * CUSTOM_METRICS:app_ops_breakdown:update_count::NUMBER / CUSTOM_METRICS:app_ops_breakdown:total_count::NUMBER, 
                        0)
                ) AS app_upd_ops,
                AVG(CUSTOM_METRICS:resources:cpu_percent::NUMBER) AS cpu_pct,
                AVG(CUSTOM_METRICS:resources:memory_mb::NUMBER) AS mem_mb
            FROM FLAKEBENCH.TEST_RESULTS.WORKER_METRICS_SNAPSHOTS
            WHERE RUN_ID = :v_run_id
              AND PHASE IN ('WARMUP', 'MEASUREMENT', 'RUNNING')
            GROUP BY ROUND(ELAPSED_SECONDS)
        )
    );
    
    IF (result IS NULL OR result:snapshots IS NULL OR ARRAY_SIZE(result:snapshots) = 0) THEN
        RETURN OBJECT_CONSTRUCT(
            'test_id', :v_test_id,
            'count', 0,
            'latency_aggregation_method', NULL,
            'warmup_end_elapsed_seconds', NULL,
            'smoothing_applied', FALSE,
            'snapshots', ARRAY_CONSTRUCT()
        );
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- GET_STEP_HISTORY: FIND_MAX step progression
-- =============================================================================
-- Returns step-by-step data for FIND_MAX_CONCURRENCY tests.
-- =============================================================================

CREATE OR REPLACE PROCEDURE GET_STEP_HISTORY(
    p_test_id VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Get FIND_MAX step history. Returns JSON with step-by-step progression data.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    run_id_val VARCHAR;
BEGIN
    -- Get the run_id for this test
    SELECT RUN_ID INTO run_id_val
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = p_test_id
    LIMIT 1;
    
    IF (run_id_val IS NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'error', 'Test not found',
            'test_id', p_test_id
        );
    END IF;
    
    SELECT OBJECT_CONSTRUCT(
        'test_id', p_test_id,
        'run_id', run_id_val,
        'metadata', OBJECT_CONSTRUCT(
            'total_steps', COUNT(*),
            'best_step', MAX(CASE WHEN OUTCOME = 'STABLE' THEN STEP_NUMBER END),
            'final_outcome', MAX_BY(OUTCOME, STEP_NUMBER),
            'final_reason', MAX_BY(STOP_REASON, STEP_NUMBER)
        ),
        'steps', ARRAY_AGG(
            OBJECT_CONSTRUCT(
                'step_number', STEP_NUMBER,
                'target_workers', TARGET_WORKERS,
                'qps', ROUND(QPS, 1),
                'p50_latency_ms', ROUND(P50_LATENCY_MS, 1),
                'p95_latency_ms', ROUND(P95_LATENCY_MS, 1),
                'p99_latency_ms', ROUND(P99_LATENCY_MS, 1),
                'error_count', ERROR_COUNT,
                'error_rate', ROUND(ERROR_RATE, 2),
                'qps_vs_prior_pct', ROUND(QPS_VS_PRIOR_PCT, 1),
                'p95_vs_baseline_pct', ROUND(P95_VS_BASELINE_PCT, 1),
                'queue_detected', QUEUE_DETECTED,
                'outcome', OUTCOME,
                'stop_reason', STOP_REASON,
                'duration_seconds', ROUND(STEP_DURATION_SECONDS, 1)
            ) ORDER BY STEP_NUMBER
        )
    ) INTO result
    FROM FLAKEBENCH.TEST_RESULTS.CONTROLLER_STEP_HISTORY
    WHERE RUN_ID = run_id_val
      AND STEP_TYPE = 'FIND_MAX';
    
    IF (result IS NULL OR result:steps IS NULL OR ARRAY_SIZE(result:steps) = 0) THEN
        -- Try to get from find_max_result in TEST_RESULTS
        SELECT OBJECT_CONSTRUCT(
            'test_id', p_test_id,
            'run_id', run_id_val,
            'source', 'TEST_RESULTS.find_max_result',
            'find_max_result', FIND_MAX_RESULT
        ) INTO result
        FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
        WHERE TEST_ID = p_test_id
          AND FIND_MAX_RESULT IS NOT NULL;
    END IF;
    
    IF (result IS NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'test_id', p_test_id,
            'error', 'No step history found. This test may not be a FIND_MAX_CONCURRENCY test.',
            'steps', ARRAY_CONSTRUCT()
        );
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- GET_WAREHOUSE_TIMESERIES: Multi-cluster warehouse metrics over time
-- =============================================================================
-- Returns warehouse scaling metrics (cluster counts, queue times) over time.
-- Useful for understanding MCW behavior during tests.
-- =============================================================================

CREATE OR REPLACE PROCEDURE GET_WAREHOUSE_TIMESERIES(
    p_test_id VARCHAR,
    p_bucket_seconds INTEGER DEFAULT 1
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Get warehouse scaling metrics over time. Returns JSON with cluster counts and queue metrics.'
EXECUTE AS OWNER
AS
$$
DECLARE
    result VARIANT;
    run_id_val VARCHAR;
    bucket_size INTEGER;
BEGIN
    bucket_size := GREATEST(COALESCE(p_bucket_seconds, 1), 1);
    
    -- Get the run_id for this test
    SELECT RUN_ID INTO run_id_val
    FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = p_test_id
    LIMIT 1;
    
    IF (run_id_val IS NULL) THEN
        RETURN OBJECT_CONSTRUCT(
            'error', 'Test not found',
            'test_id', p_test_id
        );
    END IF;
    
    -- Check if we have warehouse poll data
    SELECT OBJECT_CONSTRUCT(
        'test_id', p_test_id,
        'run_id', run_id_val,
        'bucket_seconds', bucket_size,
        'source', 'WAREHOUSE_POLL_SNAPSHOTS',
        'data', COALESCE(ARRAY_AGG(
            OBJECT_CONSTRUCT(
                'elapsed_seconds', ELAPSED_SECONDS,
                'started_clusters', STARTED_CLUSTERS,
                'running', RUNNING,
                'queued', QUEUED,
                'min_cluster_count', MIN_CLUSTER_COUNT,
                'max_cluster_count', MAX_CLUSTER_COUNT,
                'scaling_policy', SCALING_POLICY
            ) ORDER BY ELAPSED_SECONDS
        ), ARRAY_CONSTRUCT())
    ) INTO result
    FROM FLAKEBENCH.TEST_RESULTS.WAREHOUSE_POLL_SNAPSHOTS
    WHERE RUN_ID = run_id_val;
    
    -- If no warehouse poll data, try to derive from query executions
    IF (result:data = ARRAY_CONSTRUCT() OR ARRAY_SIZE(result:data) = 0) THEN
        SELECT OBJECT_CONSTRUCT(
            'test_id', p_test_id,
            'bucket_seconds', bucket_size,
            'source', 'QUERY_EXECUTIONS',
            'data', ARRAY_AGG(
                OBJECT_CONSTRUCT(
                    'time_bucket', time_bucket,
                    'active_clusters', active_clusters,
                    'cluster_ids', cluster_ids,
                    'queries_started', queries_started,
                    'avg_queue_overload_ms', avg_queue_overload,
                    'max_queue_overload_ms', max_queue_overload,
                    'queries_queued', queries_queued
                ) ORDER BY time_bucket
            )
        ) INTO result
        FROM (
            SELECT
                FLOOR(TIMESTAMPDIFF('SECOND', 
                    (SELECT MIN(START_TIME) FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS WHERE TEST_ID = p_test_id), 
                    START_TIME
                ) / :bucket_size) * :bucket_size AS time_bucket,
                COUNT(DISTINCT SF_CLUSTER_NUMBER) AS active_clusters,
                ARRAY_AGG(DISTINCT SF_CLUSTER_NUMBER) AS cluster_ids,
                COUNT(*) AS queries_started,
                ROUND(AVG(SF_QUEUED_OVERLOAD_MS), 2) AS avg_queue_overload,
                MAX(SF_QUEUED_OVERLOAD_MS) AS max_queue_overload,
                SUM(CASE WHEN SF_QUEUED_OVERLOAD_MS > 0 THEN 1 ELSE 0 END) AS queries_queued
            FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS
            WHERE TEST_ID = p_test_id
              AND WARMUP = FALSE
            GROUP BY FLOOR(TIMESTAMPDIFF('SECOND', 
                (SELECT MIN(START_TIME) FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS WHERE TEST_ID = p_test_id), 
                START_TIME
            ) / :bucket_size)
        );
    END IF;
    
    RETURN result;
END;
$$;

-- =============================================================================
-- ANALYZE_BENCHMARK: Comprehensive benchmark analysis
-- =============================================================================
-- Returns a comprehensive analysis of a benchmark test including:
-- - Test summary
-- - Latency breakdown
-- - Error analysis
-- - Throughput analysis
-- =============================================================================

CREATE OR REPLACE PROCEDURE ANALYZE_BENCHMARK(
    p_test_id VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
COMMENT = 'Get comprehensive benchmark analysis combining summary, latency, errors, and throughput.'
EXECUTE AS OWNER
AS
$$
DECLARE
    test_summary VARIANT;
    latency_breakdown VARIANT;
    error_summary VARIANT;
BEGIN
    -- Get test summary
    CALL GET_TEST_SUMMARY(:p_test_id);
    test_summary := (SELECT GET_TEST_SUMMARY FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
    
    -- Get latency breakdown
    CALL GET_LATENCY_BREAKDOWN(:p_test_id);
    latency_breakdown := (SELECT GET_LATENCY_BREAKDOWN FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())));
    
    RETURN OBJECT_CONSTRUCT(
        'test_id', p_test_id,
        'summary', test_summary,
        'latency_breakdown', latency_breakdown,
        'analysis_timestamp', CURRENT_TIMESTAMP()
    );
END;
$$;

-- =============================================================================
-- Validation: Show created procedures
-- =============================================================================
SHOW PROCEDURES LIKE 'GET_%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;
SHOW PROCEDURES LIKE 'LIST_%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;
SHOW PROCEDURES LIKE 'ANALYZE_%' IN SCHEMA FLAKEBENCH.TEST_RESULTS;
