-- Debug: investigate one benchmark run by TEST_ID
-- Test: http://localhost:8000/dashboard/03f3d3b9-167c-42f4-85f1-019da106d4fd

USE DATABASE UNISTORE_BENCHMARK;
USE SCHEMA TEST_RESULTS;

SET TEST_ID = '03f3d3b9-167c-42f4-85f1-019da106d4fd';

-- -----------------------------------------------------------------------------
-- 1) Test summary row
-- -----------------------------------------------------------------------------
SELECT
  TEST_ID,
  TEST_NAME,
  SCENARIO_NAME,
  TABLE_NAME,
  TABLE_TYPE,
  WAREHOUSE,
  WAREHOUSE_SIZE,
  STATUS,
  START_TIME,
  END_TIME,
  DURATION_SECONDS,
  CONCURRENT_CONNECTIONS,
  TOTAL_OPERATIONS,
  OPERATIONS_PER_SECOND,
  P95_LATENCY_MS,
  RANGE_SCAN_P95_LATENCY_MS,
  POINT_LOOKUP_P95_LATENCY_MS,
  INSERT_P95_LATENCY_MS,
  UPDATE_P95_LATENCY_MS,
  APP_OVERHEAD_P95_MS
FROM TEST_RESULTS
WHERE TEST_ID = $TEST_ID;

-- -----------------------------------------------------------------------------
-- 2) Extract stored template config + scenario (authoritative settings used)
-- -----------------------------------------------------------------------------
WITH tr AS (
  SELECT TEST_CONFIG AS CFG
  FROM TEST_RESULTS
  WHERE TEST_ID = $TEST_ID
)
SELECT
  CFG:template_id::STRING AS TEMPLATE_ID,
  CFG:template_name::STRING AS TEMPLATE_NAME,
  CFG:template_config:table_type::STRING AS TEMPLATE_TABLE_TYPE,
  CFG:template_config:warehouse_name::STRING AS TEMPLATE_WAREHOUSE,
  CFG:template_config:database::STRING AS TEMPLATE_DB,
  CFG:template_config:schema::STRING AS TEMPLATE_SCHEMA,
  CFG:template_config:table_name::STRING AS TEMPLATE_TABLE,
  CFG:template_config:ai_workload:pool_id::STRING AS AI_POOL_ID,
  CFG:template_config:ai_workload:range_mode::STRING AS AI_RANGE_MODE,
  CFG:template_config:custom_point_lookup_query::STRING AS CUSTOM_POINT_LOOKUP_QUERY,
  CFG:template_config:custom_range_scan_query::STRING AS CUSTOM_RANGE_SCAN_QUERY,
  CFG:template_config:custom_insert_query::STRING AS CUSTOM_INSERT_QUERY,
  CFG:template_config:custom_update_query::STRING AS CUSTOM_UPDATE_QUERY,
  CFG:scenario AS SCENARIO
FROM tr;

-- -----------------------------------------------------------------------------
-- 3) Query execution breakdown by kind (measurement only)
-- -----------------------------------------------------------------------------
SELECT
  QUERY_KIND,
  COUNT(*) AS N,
  COUNT_IF(NOT SUCCESS) AS ERRORS,
  ROUND(100.0 * COUNT_IF(NOT SUCCESS) / NULLIF(COUNT(*), 0), 2) AS ERROR_PCT,
  ROUND(AVG(DURATION_MS), 2) AS AVG_APP_MS,
  ROUND(APPROX_PERCENTILE(DURATION_MS, 0.50), 2) AS P50_APP_MS,
  ROUND(APPROX_PERCENTILE(DURATION_MS, 0.95), 2) AS P95_APP_MS,
  ROUND(MAX(DURATION_MS), 2) AS MAX_APP_MS,
  MAX(TRY_TO_NUMBER(TO_VARCHAR(CUSTOM_METADATA:rows_returned))) AS MAX_ROWS_RETURNED,
  ROUND(AVG(TRY_TO_NUMBER(TO_VARCHAR(CUSTOM_METADATA:rows_returned))), 2) AS AVG_ROWS_RETURNED
FROM QUERY_EXECUTIONS
WHERE TEST_ID = $TEST_ID
  AND COALESCE(WARMUP, FALSE) = FALSE
GROUP BY QUERY_KIND
ORDER BY N DESC;

-- -----------------------------------------------------------------------------
-- 4) Slowest queries (what actually caused the run to overrun)
-- -----------------------------------------------------------------------------
SELECT
  QUERY_KIND,
  SUCCESS,
  ROUND(DURATION_MS, 2) AS APP_MS,
  ROUND(SF_TOTAL_ELAPSED_MS, 2) AS SF_TOTAL_MS,
  ROUND(SF_EXECUTION_MS, 2) AS SF_EXEC_MS,
  ROUND(SF_QUEUED_OVERLOAD_MS, 2) AS SF_Q_OVERLOAD_MS,
  ROUND(SF_QUEUED_PROVISIONING_MS, 2) AS SF_Q_PROVISION_MS,
  ROUND(SF_TX_BLOCKED_MS, 2) AS SF_TX_BLOCKED_MS,
  SF_BYTES_SCANNED,
  SF_ROWS_PRODUCED,
  QUERY_ID,
  START_TIME,
  END_TIME,
  LEFT(QUERY_TEXT, 250) AS QUERY_TEXT_250,
  CUSTOM_METADATA
FROM QUERY_EXECUTIONS
WHERE TEST_ID = $TEST_ID
  AND COALESCE(WARMUP, FALSE) = FALSE
ORDER BY DURATION_MS DESC
LIMIT 25;

-- -----------------------------------------------------------------------------
-- 5) If AI pools exist, confirm they were loaded (skipping expensive runtime profiling)
-- -----------------------------------------------------------------------------
WITH tr AS (
  SELECT
    TEST_CONFIG:template_id::STRING AS TEMPLATE_ID,
    TEST_CONFIG:template_config:ai_workload:pool_id::STRING AS POOL_ID
  FROM TEST_RESULTS
  WHERE TEST_ID = $TEST_ID
)
SELECT
  tr.TEMPLATE_ID,
  tr.POOL_ID,
  COUNT(*) AS VALUE_POOL_ROWS
FROM tr
LEFT JOIN TEMPLATE_VALUE_POOLS p
  ON p.TEMPLATE_ID = tr.TEMPLATE_ID
  AND p.POOL_ID = tr.POOL_ID
GROUP BY tr.TEMPLATE_ID, tr.POOL_ID;

-- -----------------------------------------------------------------------------
-- 6) Table metadata sanity check (row estimates vs expensive COUNT(*))
-- -----------------------------------------------------------------------------
-- Information schema row estimates (fast, but can be null/0 depending on object type).
SELECT
  TABLE_CATALOG,
  TABLE_SCHEMA,
  TABLE_NAME,
  TABLE_TYPE,
  ROW_COUNT,
  BYTES,
  CLUSTERING_KEY
FROM UNISTORE_BENCHMARK.INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'PUBLIC'
  AND TABLE_NAME = 'TPCH_SF100_ORDERS_HYBRID';

-- SHOW TABLES metadata (often reports rows/bytes even when INFORMATION_SCHEMA is sparse).
SHOW TABLES LIKE 'TPCH_SF100_ORDERS_HYBRID' IN SCHEMA UNISTORE_BENCHMARK.PUBLIC;
SELECT * FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

-- -----------------------------------------------------------------------------
-- 7) Query history for this test_id (includes setup + pool health checks)
-- -----------------------------------------------------------------------------
SET QUERY_TAG = 'unistore_benchmark:test_id=' || $TEST_ID;

SELECT
  QUERY_ID,
  QUERY_TEXT,
  START_TIME,
  END_TIME,
  ROUND(TOTAL_ELAPSED_TIME / 1000.0, 3) AS TOTAL_S,
  ROUND(EXECUTION_TIME / 1000.0, 3) AS EXEC_S,
  ROUND(QUEUED_OVERLOAD_TIME / 1000.0, 3) AS QUEUED_OVERLOAD_S,
  ROUND(QUEUED_PROVISIONING_TIME / 1000.0, 3) AS QUEUED_PROVISIONING_S,
  ROUND(TRANSACTION_BLOCKED_TIME / 1000.0, 3) AS TX_BLOCKED_S
FROM TABLE(
  INFORMATION_SCHEMA.QUERY_HISTORY(
    END_TIME_RANGE_START => DATEADD('hour', -8, CURRENT_TIMESTAMP()),
    END_TIME_RANGE_END => CURRENT_TIMESTAMP(),
    RESULT_LIMIT => 200
  )
)
WHERE QUERY_TAG = $QUERY_TAG
ORDER BY START_TIME;

-- -----------------------------------------------------------------------------
-- 8) Value pool ranges (validate RANGE pool is sane for time cutoffs)
-- -----------------------------------------------------------------------------
WITH tr AS (
  SELECT
    TEST_CONFIG:template_id::STRING AS TEMPLATE_ID,
    TEST_CONFIG:template_config:ai_workload:pool_id::STRING AS POOL_ID
  FROM TEST_RESULTS
  WHERE TEST_ID = $TEST_ID
)
SELECT
  p.POOL_KIND,
  p.COLUMN_NAME,
  COUNT(*) AS N,
  MIN(TRY_TO_DATE(TO_VARCHAR(p.VALUE))) AS MIN_DATE,
  MAX(TRY_TO_DATE(TO_VARCHAR(p.VALUE))) AS MAX_DATE
FROM tr
JOIN TEMPLATE_VALUE_POOLS p
  ON p.TEMPLATE_ID = tr.TEMPLATE_ID
  AND p.POOL_ID = tr.POOL_ID
WHERE p.POOL_KIND = 'RANGE'
GROUP BY p.POOL_KIND, p.COLUMN_NAME
ORDER BY N DESC;


