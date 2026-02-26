-- =============================================================================
-- Unistore Benchmark - Semantic View for Cortex Agent
-- =============================================================================
-- This semantic view provides a governed, queryable interface for benchmark
-- analytics data, enabling natural language queries via Cortex Agent.
--
-- Database: FLAKEBENCH
-- Schema: TEST_RESULTS
--
-- Updated: 2026-02-12
-- Changes: Added VQRs, improved table_type documentation, added filters
-- =============================================================================

USE DATABASE FLAKEBENCH;
USE SCHEMA TEST_RESULTS;

-- =============================================================================
-- BENCHMARK_ANALYTICS: Semantic View for Benchmark Analysis
-- =============================================================================
-- This semantic view exposes test results, worker metrics, and query executions
-- with logical naming, synonyms, and AI-friendly descriptions.
--
-- TABLE_TYPE VALUES (Database Systems):
--   POSTGRES           = PostgreSQL database
--   HYBRID             = Snowflake Unistore/Hybrid tables (row-level locking)
--   STANDARD           = Snowflake standard tables (analytics-optimized)
--   ICEBERG            = Snowflake Iceberg tables
--   INTERACTIVE        = Snowflake Interactive tables (low-latency)
--
-- IMPORTANT: "interactive" means table_type = 'INTERACTIVE', NOT 'HYBRID'
-- =============================================================================

CREATE OR REPLACE SEMANTIC VIEW BENCHMARK_ANALYTICS

  -- -------------------------------------------------------------------------
  -- TABLES: Define logical tables with primary keys and synonyms
  -- -------------------------------------------------------------------------
  TABLES (
    -- Main test results table
    FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS 
      PRIMARY KEY (EXECUTION_ID) 
      WITH SYNONYMS = ('queries', 'operations', 'query log'),

    STEP_HISTORY AS FLAKEBENCH.TEST_RESULTS.CONTROLLER_STEP_HISTORY 
      PRIMARY KEY (STEP_ID) 
      WITH SYNONYMS = ('find max steps', 'scaling steps'),

    FLAKEBENCH.TEST_RESULTS.TEST_RESULTS 
      PRIMARY KEY (TEST_ID) 
      WITH SYNONYMS = ('tests', 'benchmarks', 'test runs', 'benchmark results'),

    WORKER_METRICS AS FLAKEBENCH.TEST_RESULTS.WORKER_METRICS_SNAPSHOTS 
      PRIMARY KEY (SNAPSHOT_ID) 
      WITH SYNONYMS = ('worker snapshots', 'time series', 'metrics over time')
  )

  -- -------------------------------------------------------------------------
  -- RELATIONSHIPS: Define foreign key relationships between tables
  -- -------------------------------------------------------------------------
  RELATIONSHIPS (
    QUERY_TO_TEST AS QUERY_EXECUTIONS(TEST_ID) REFERENCES TEST_RESULTS(TEST_ID),
    WORKER_TO_TEST AS WORKER_METRICS(TEST_ID) REFERENCES TEST_RESULTS(TEST_ID)
  )

  -- -------------------------------------------------------------------------
  -- FACTS: Numeric measures at row level (before aggregation)
  -- -------------------------------------------------------------------------
  FACTS (
    -- Query Execution derived facts
    QUERY_EXECUTIONS.IS_FAILED_QUERY AS CASE WHEN success = FALSE THEN 1 ELSE 0 END 
      WITH SYNONYMS = ('failed flag', 'error flag') 
      COMMENT = '1 if query failed, 0 if successful. Use for counting/summing failures.',

    QUERY_EXECUTIONS.SUCCESS_INDICATOR AS CASE WHEN success = TRUE THEN 1 ELSE 0 END 
      WITH SYNONYMS = ('success flag', 'passed flag') 
      COMMENT = '1 if query succeeded, 0 if failed. Use for counting/summing successes.',

    -- Test Results Facts
    TEST_RESULTS.AVG_LATENCY_MS AS avg_latency_ms 
      WITH SYNONYMS = ('average latency', 'mean latency') 
      COMMENT = 'Average latency in ms',

    TEST_RESULTS.CONCURRENT_CONNECTIONS AS concurrent_connections 
      WITH SYNONYMS = ('concurrency', 'workers', 'threads', 'connections') 
      COMMENT = 'Number of concurrent worker threads',

    TEST_RESULTS.DURATION_SECONDS AS duration_seconds 
      WITH SYNONYMS = ('duration', 'runtime') 
      COMMENT = 'Test duration in seconds',

    TEST_RESULTS.ERROR_RATE AS error_rate 
      WITH SYNONYMS = ('error percentage', 'failure rate') 
      COMMENT = 'Percentage of failed operations (0-100)',

    TEST_RESULTS.FAILED_OPERATIONS AS failed_operations 
      WITH SYNONYMS = ('failures', 'errors') 
      COMMENT = 'Failed query count',

    TEST_RESULTS.MAX_LATENCY_MS AS max_latency_ms 
      WITH SYNONYMS = ('max latency', 'peak latency') 
      COMMENT = 'Maximum latency observed',

    TEST_RESULTS.P50_LATENCY_MS AS p50_latency_ms 
      WITH SYNONYMS = ('p50', 'median latency', 'median') 
      COMMENT = 'Median latency in ms - typical user experience',

    TEST_RESULTS.P95_LATENCY_MS AS p95_latency_ms 
      WITH SYNONYMS = ('p95', '95th percentile') 
      COMMENT = '95th percentile latency in ms',

    TEST_RESULTS.P99_LATENCY_MS AS p99_latency_ms 
      WITH SYNONYMS = ('p99', '99th percentile', 'tail latency') 
      COMMENT = '99th percentile latency for SLOs',

    TEST_RESULTS.QPS AS qps 
      WITH SYNONYMS = ('throughput', 'queries per second', 'ops per second') 
      COMMENT = 'Queries per second throughput',

    TEST_RESULTS.READ_OPERATIONS AS read_operations 
      WITH SYNONYMS = ('reads', 'selects') 
      COMMENT = 'Number of read operations',

    TEST_RESULTS.TOTAL_OPERATIONS AS total_operations 
      WITH SYNONYMS = ('total ops', 'query count') 
      COMMENT = 'Total queries executed',

    TEST_RESULTS.WAREHOUSE_CREDITS_USED AS warehouse_credits_used 
      WITH SYNONYMS = ('credits', 'cost') 
      COMMENT = 'Snowflake credits used (NULL for PostgreSQL)',

    TEST_RESULTS.WRITE_OPERATIONS AS write_operations 
      WITH SYNONYMS = ('writes', 'inserts', 'updates') 
      COMMENT = 'Number of write operations'
  )

  -- -------------------------------------------------------------------------
  -- DIMENSIONS: Categorical and temporal attributes for filtering/grouping
  -- -------------------------------------------------------------------------
  DIMENSIONS (
    -- Query Execution Dimensions
    QUERY_EXECUTIONS.QUERY_KIND AS query_kind 
      WITH SYNONYMS = ('operation type', 'query type') 
      COMMENT = 'Operation type: POINT_LOOKUP, RANGE_SCAN, INSERT, UPDATE, DELETE',

    QUERY_EXECUTIONS.SUCCESS AS success 
      COMMENT = 'Whether query succeeded (true/false)',

    QUERY_EXECUTIONS.WARMUP AS warmup 
      COMMENT = 'True if warmup phase query (exclude for metrics)',

    -- Step History Dimensions
    STEP_HISTORY.OUTCOME AS outcome 
      WITH SYNONYMS = ('step outcome') 
      COMMENT = 'Step outcome: STABLE, DEGRADED, ERROR_THRESHOLD',

    STEP_HISTORY.STEP_NUMBER AS step_number 
      COMMENT = 'Step number in FIND_MAX progression',

    -- Test Results Dimensions
    TEST_RESULTS.END_TIME AS end_time 
      WITH SYNONYMS = ('ended', 'finish time') 
      COMMENT = 'Test end timestamp',

    TEST_RESULTS.RUN_ID AS run_id 
      COMMENT = 'Run identifier for grouping tests',

    TEST_RESULTS.SCENARIO_NAME AS scenario_name 
      WITH SYNONYMS = ('scenario', 'workload') 
      COMMENT = 'Test scenario or workload pattern',

    TEST_RESULTS.START_TIME AS start_time 
      WITH SYNONYMS = ('started', 'begin time') 
      COMMENT = 'Test start timestamp',

    TEST_RESULTS.STATUS AS status 
      WITH SYNONYMS = ('test status', 'result') 
      COMMENT = 'Test status: COMPLETED, FAILED, CANCELLED, RUNNING',

    TEST_RESULTS.TABLE_NAME AS table_name 
      WITH SYNONYMS = ('target table') 
      COMMENT = 'Database table being benchmarked',

    TEST_RESULTS.TABLE_TYPE AS table_type 
      WITH SYNONYMS = ('database type', 'storage type', 'db type', 'database', 'database system', 'table type') 
      COMMENT = 'DATABASE SYSTEM: POSTGRES=PostgreSQL, HYBRID=Snowflake Unistore/Hybrid tables, STANDARD=Snowflake standard tables, ICEBERG=Snowflake Iceberg tables, INTERACTIVE=Snowflake Interactive tables. Use to compare database performance.',

    TEST_RESULTS.TEST_ID AS test_id 
      COMMENT = 'Unique test identifier (UUID)',

    TEST_RESULTS.TEST_NAME AS test_name 
      WITH SYNONYMS = ('name', 'benchmark name') 
      COMMENT = 'Human-readable test name',

    TEST_RESULTS.WAREHOUSE AS warehouse 
      WITH SYNONYMS = ('warehouse name', 'compute', 'instance') 
      COMMENT = 'Snowflake warehouse or PostgreSQL instance name',

    TEST_RESULTS.WAREHOUSE_SIZE AS warehouse_size 
      WITH SYNONYMS = ('size', 'compute size', 'instance size') 
      COMMENT = 'Compute size: XSMALL/SMALL/MEDIUM/LARGE/XLARGE',

    -- Worker Metrics Dimensions
    WORKER_METRICS.PHASE AS phase 
      WITH SYNONYMS = ('test phase') 
      COMMENT = 'Test phase: WARMUP, MEASUREMENT, COOLDOWN',

    WORKER_METRICS.WORKER_ID AS worker_id 
      COMMENT = 'Worker thread identifier'
  )

  -- -------------------------------------------------------------------------
  -- METRICS: Pre-defined aggregations
  -- -------------------------------------------------------------------------
  METRICS (
    -- Query Execution Metrics
    QUERY_EXECUTIONS.ERROR_COUNT AS SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) 
      WITH SYNONYMS = ('total errors', 'failure count') 
      COMMENT = 'Count of failed query executions',

    QUERY_EXECUTIONS.FAILED_QUERY_COUNT AS COUNT(CASE WHEN success = FALSE THEN 1 END) 
      WITH SYNONYMS = ('failed queries', 'error query count') 
      COMMENT = 'Number of queries that failed',

    QUERY_EXECUTIONS.SUCCESSFUL_QUERY_COUNT AS COUNT(CASE WHEN success = TRUE THEN 1 END) 
      WITH SYNONYMS = ('successful queries', 'passed queries') 
      COMMENT = 'Number of queries that succeeded',

    QUERY_EXECUTIONS.TOTAL_QUERY_COUNT AS COUNT(*) 
      WITH SYNONYMS = ('query count', 'execution count') 
      COMMENT = 'Total number of query executions',

    QUERY_EXECUTIONS.QUERY_ERROR_RATE AS 100.0 * SUM(CASE WHEN success = FALSE THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0) 
      WITH SYNONYMS = ('query failure rate') 
      COMMENT = 'Percentage of queries that failed',

    -- Test Results Metrics
    TEST_RESULTS.AVG_P50 AS AVG(p50_latency_ms) 
      COMMENT = 'Average median latency',

    TEST_RESULTS.AVG_P95 AS AVG(p95_latency_ms) 
      WITH SYNONYMS = ('average p95') 
      COMMENT = 'Average P95 latency',

    TEST_RESULTS.AVG_P99 AS AVG(p99_latency_ms) 
      WITH SYNONYMS = ('average p99') 
      COMMENT = 'Average P99 latency',

    TEST_RESULTS.AVG_QPS AS AVG(qps) 
      WITH SYNONYMS = ('average throughput', 'mean qps') 
      COMMENT = 'Average QPS across tests',

    TEST_RESULTS.MAX_QPS AS MAX(qps) 
      WITH SYNONYMS = ('peak throughput', 'best qps') 
      COMMENT = 'Maximum QPS achieved',

    TEST_RESULTS.MIN_QPS AS MIN(qps) 
      WITH SYNONYMS = ('lowest throughput') 
      COMMENT = 'Minimum QPS observed',

    TEST_RESULTS.TEST_COUNT AS COUNT(DISTINCT test_id) 
      WITH SYNONYMS = ('number of tests', 'total tests') 
      COMMENT = 'Count of distinct tests',

    TEST_RESULTS.TOTAL_ERRORS AS SUM(failed_operations) 
      COMMENT = 'Total failed operations',

    TEST_RESULTS.TOTAL_OPS AS SUM(total_operations) 
      COMMENT = 'Sum of all operations',

    TEST_RESULTS.AVG_ERROR_RATE AS AVG(error_rate) 
      WITH SYNONYMS = ('average error rate', 'mean error rate') 
      COMMENT = 'Average error rate across tests (percentage)'
  )

  COMMENT = 'Benchmark analytics for comparing Snowflake (HYBRID, STANDARD, ICEBERG, INTERACTIVE) vs PostgreSQL performance. Filter by table_type dimension for database comparisons.'

  -- -------------------------------------------------------------------------
  -- AI_SQL_GENERATION: Instructions for Cortex Analyst
  -- -------------------------------------------------------------------------
  AI_SQL_GENERATION 'DATABASE COMPARISON: table_type identifies the database system:
- POSTGRES = PostgreSQL database
- HYBRID = Snowflake Unistore/Hybrid tables
- STANDARD = Snowflake standard tables
- ICEBERG = Snowflake Iceberg tables
- INTERACTIVE = Snowflake Interactive tables

IMPORTANT: ''interactive'' means table_type = ''INTERACTIVE'', NOT ''HYBRID''

COMMON PATTERNS:
- PostgreSQL tests: WHERE table_type = ''POSTGRES''
- Interactive table tests: WHERE table_type = ''INTERACTIVE''
- Snowflake tests: WHERE table_type != ''POSTGRES''
- Compare all: GROUP BY table_type
- Completed only: WHERE status = ''COMPLETED''

METRICS: Higher qps = better throughput. Lower p50/p95/p99 = better latency. Lower error_rate = more reliable.'

  -- -------------------------------------------------------------------------
  -- EXTENSION: Filters and Verified Queries (VQRs)
  -- -------------------------------------------------------------------------
  WITH EXTENSION (CA = '{
    "tables": [
      {
        "name": "QUERY_EXECUTIONS",
        "dimensions": [
          {"name": "QUERY_KIND"},
          {"name": "SUCCESS"},
          {"name": "WARMUP"}
        ],
        "facts": [
          {"name": "is_failed_query"},
          {"name": "success_indicator"}
        ],
        "metrics": [
          {"name": "error_count"},
          {"name": "failed_query_count"},
          {"name": "successful_query_count"},
          {"name": "total_query_count"},
          {"name": "query_error_rate"}
        ],
        "filters": [
          {
            "name": "exclude_warmup_queries",
            "synonyms": ["no warmup", "measurement only queries"],
            "description": "Filter to exclude warmup phase queries for accurate metrics",
            "expr": "warmup = FALSE"
          },
          {
            "name": "read_operations_only",
            "synonyms": ["reads only", "selects only"],
            "description": "Filter to only show read operations (POINT_LOOKUP and RANGE_SCAN)",
            "expr": "query_kind IN (''POINT_LOOKUP'', ''RANGE_SCAN'')"
          },
          {
            "name": "write_operations_only",
            "synonyms": ["writes only", "mutations only"],
            "description": "Filter to only show write operations (INSERT, UPDATE, DELETE)",
            "expr": "query_kind IN (''INSERT'', ''UPDATE'', ''DELETE'')"
          },
          {
            "name": "successful_queries_only",
            "synonyms": ["success only", "no errors"],
            "description": "Filter to only show successful query executions",
            "expr": "success = TRUE"
          },
          {
            "name": "failed_queries_only",
            "synonyms": ["errors only", "failures only"],
            "description": "Filter to only show failed query executions",
            "expr": "success = FALSE"
          },
          {
            "name": "write_operations_insert_update",
            "synonyms": ["inserts and updates only"],
            "description": "Filter to only show INSERT and UPDATE operations (excludes DELETE)",
            "expr": "query_kind IN (''INSERT'', ''UPDATE'')"
          }
        ]
      },
      {
        "name": "STEP_HISTORY",
        "dimensions": [
          {"name": "OUTCOME"},
          {"name": "STEP_NUMBER"}
        ]
      },
      {
        "name": "TEST_RESULTS",
        "dimensions": [
          {"name": "END_TIME"},
          {"name": "RUN_ID"},
          {"name": "SCENARIO_NAME"},
          {"name": "START_TIME"},
          {"name": "STATUS"},
          {"name": "TABLE_NAME"},
          {"name": "TABLE_TYPE"},
          {"name": "TEST_ID"},
          {"name": "TEST_NAME"},
          {"name": "WAREHOUSE"},
          {"name": "WAREHOUSE_SIZE"}
        ],
        "facts": [
          {"name": "AVG_LATENCY_MS"},
          {"name": "CONCURRENT_CONNECTIONS"},
          {"name": "DURATION_SECONDS"},
          {"name": "ERROR_RATE"},
          {"name": "FAILED_OPERATIONS"},
          {"name": "MAX_LATENCY_MS"},
          {"name": "P50_LATENCY_MS"},
          {"name": "P95_LATENCY_MS"},
          {"name": "P99_LATENCY_MS"},
          {"name": "QPS"},
          {"name": "READ_OPERATIONS"},
          {"name": "TOTAL_OPERATIONS"},
          {"name": "WAREHOUSE_CREDITS_USED"},
          {"name": "WRITE_OPERATIONS"}
        ],
        "metrics": [
          {"name": "AVG_P50"},
          {"name": "AVG_P95"},
          {"name": "AVG_P99"},
          {"name": "AVG_QPS"},
          {"name": "MAX_QPS"},
          {"name": "MIN_QPS"},
          {"name": "TEST_COUNT"},
          {"name": "TOTAL_ERRORS"},
          {"name": "TOTAL_OPS"},
          {"name": "avg_error_rate"}
        ],
        "filters": [
          {
            "name": "completed_tests_only",
            "description": "Filter to only show completed benchmark tests",
            "expr": "status = ''COMPLETED''"
          },
          {
            "name": "postgresql_tests_only",
            "synonyms": ["postgres only", "postgresql filter"],
            "description": "Filter to only show PostgreSQL database tests",
            "expr": "table_type = ''POSTGRES''"
          },
          {
            "name": "snowflake_hybrid_tests_only",
            "synonyms": ["hybrid only", "unistore only"],
            "description": "Filter to only show Snowflake Unistore/Hybrid table tests",
            "expr": "table_type = ''HYBRID''"
          },
          {
            "name": "snowflake_standard_tests_only",
            "synonyms": ["standard only"],
            "description": "Filter to only show Snowflake standard table tests",
            "expr": "table_type = ''STANDARD''"
          },
          {
            "name": "failed_tests_only",
            "synonyms": ["failures only", "failed benchmarks"],
            "description": "Filter to only show failed benchmark tests",
            "expr": "status = ''FAILED''"
          },
          {
            "name": "interactive_tests_only",
            "synonyms": ["interactive only", "interactive tables"],
            "description": "Filter to only show Snowflake Interactive table tests",
            "expr": "table_type = ''INTERACTIVE''"
          },
          {
            "name": "postgres_tests_only",
            "synonyms": ["postgres only"],
            "description": "Filter to only show Postgres tests",
            "expr": "table_type = ''POSTGRES''"
          }
        ]
      },
      {
        "name": "WORKER_METRICS",
        "dimensions": [
          {"name": "PHASE"},
          {"name": "WORKER_ID"}
        ],
        "filters": [
          {
            "name": "measurement_phase_only",
            "synonyms": ["measurement only", "exclude warmup"],
            "description": "Filter to only show measurement phase metrics (excludes warmup and cooldown)",
            "expr": "phase = ''MEASUREMENT''"
          }
        ]
      }
    ],
    "relationships": [
      {"name": "QUERY_TO_TEST"},
      {"name": "WORKER_TO_TEST"}
    ],
    "verified_queries": [
      {
        "name": "Compare PostgreSQL vs Snowflake Performance",
        "sql": "SELECT TABLE_TYPE AS database_type, COUNT(DISTINCT TEST_ID) AS test_count, ROUND(AVG(QPS), 1) AS avg_qps, ROUND(AVG(P50_LATENCY_MS), 2) AS avg_p50_ms, ROUND(AVG(P95_LATENCY_MS), 2) AS avg_p95_ms, ROUND(AVG(P99_LATENCY_MS), 2) AS avg_p99_ms, ROUND(AVG(ERROR_RATE), 2) AS avg_error_rate FROM TEST_RESULTS WHERE STATUS = ''COMPLETED'' GROUP BY TABLE_TYPE ORDER BY avg_qps DESC",
        "question": "Compare PostgreSQL vs Snowflake performance"
      },
      {
        "name": "List Recent Tests",
        "sql": "SELECT TEST_ID, TEST_NAME, TABLE_TYPE AS database_type, WAREHOUSE_SIZE, STATUS, QPS, P50_LATENCY_MS, P95_LATENCY_MS, ERROR_RATE, START_TIME FROM TEST_RESULTS ORDER BY START_TIME DESC LIMIT 20",
        "question": "Show recent benchmark tests"
      },
      {
        "name": "Performance by Warehouse Size",
        "sql": "SELECT WAREHOUSE_SIZE, TABLE_TYPE AS database_type, COUNT(DISTINCT TEST_ID) AS test_count, ROUND(AVG(QPS), 1) AS avg_qps, ROUND(AVG(P50_LATENCY_MS), 2) AS avg_p50_ms, ROUND(AVG(P95_LATENCY_MS), 2) AS avg_p95_ms FROM TEST_RESULTS WHERE STATUS = ''COMPLETED'' GROUP BY WAREHOUSE_SIZE, TABLE_TYPE ORDER BY WAREHOUSE_SIZE, avg_qps DESC",
        "question": "Compare performance by warehouse size"
      },
      {
        "name": "PostgreSQL Tests Only",
        "sql": "SELECT TEST_ID, TEST_NAME, WAREHOUSE_SIZE, QPS, P50_LATENCY_MS AS p50_ms, P95_LATENCY_MS AS p95_ms, P99_LATENCY_MS AS p99_ms, ERROR_RATE, TOTAL_OPERATIONS, START_TIME FROM TEST_RESULTS WHERE TABLE_TYPE = ''POSTGRES'' AND STATUS = ''COMPLETED'' ORDER BY START_TIME DESC",
        "question": "Show PostgreSQL test results"
      },
      {
        "name": "Snowflake Hybrid Table Tests",
        "sql": "SELECT TEST_ID, TEST_NAME, WAREHOUSE_SIZE, QPS, P50_LATENCY_MS AS p50_ms, P95_LATENCY_MS AS p95_ms, P99_LATENCY_MS AS p99_ms, ERROR_RATE, TOTAL_OPERATIONS, START_TIME FROM TEST_RESULTS WHERE TABLE_TYPE = ''HYBRID'' AND STATUS = ''COMPLETED'' ORDER BY START_TIME DESC",
        "question": "Show Snowflake Unistore hybrid table test results"
      },
      {
        "name": "Best Performing Tests by QPS",
        "sql": "SELECT TEST_ID, TEST_NAME, TABLE_TYPE AS database_type, WAREHOUSE_SIZE, QPS AS queries_per_second, P50_LATENCY_MS, P95_LATENCY_MS, ERROR_RATE FROM TEST_RESULTS WHERE STATUS = ''COMPLETED'' ORDER BY QPS DESC LIMIT 10",
        "question": "Which tests had the best throughput?"
      },
      {
        "name": "Lowest Latency Tests",
        "sql": "SELECT TEST_ID, TEST_NAME, TABLE_TYPE AS database_type, WAREHOUSE_SIZE, P50_LATENCY_MS, P95_LATENCY_MS, P99_LATENCY_MS, QPS FROM TEST_RESULTS WHERE STATUS = ''COMPLETED'' ORDER BY P50_LATENCY_MS ASC LIMIT 10",
        "question": "Which tests had the lowest latency?"
      },
      {
        "name": "Test Performance Summary",
        "sql": "SELECT TEST_ID, TEST_NAME, TABLE_TYPE AS database_type, WAREHOUSE_SIZE, STATUS, QPS, P50_LATENCY_MS, P95_LATENCY_MS, P99_LATENCY_MS, ERROR_RATE, TOTAL_OPERATIONS, READ_OPERATIONS, WRITE_OPERATIONS, FAILED_OPERATIONS, DURATION_SECONDS, START_TIME, END_TIME FROM TEST_RESULTS WHERE TEST_ID = :test_id",
        "question": "What is the overall performance summary and operational status for a specific benchmark run?"
      },
      {
        "name": "Operation Type Breakdown",
        "sql": "SELECT QUERY_KIND AS operation_type, COUNT(*) AS total_queries, SUM(CASE WHEN SUCCESS = TRUE THEN 1 ELSE 0 END) AS successful, SUM(CASE WHEN SUCCESS = FALSE THEN 1 ELSE 0 END) AS failed, ROUND(100.0 * SUM(CASE WHEN SUCCESS = FALSE THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) AS error_rate_pct FROM QUERY_EXECUTIONS WHERE TEST_ID = :test_id AND WARMUP = FALSE GROUP BY QUERY_KIND ORDER BY total_queries DESC",
        "question": "What is the breakdown of operation types and their error counts for this benchmark run?"
      },
      {
        "name": "Test Execution Metrics",
        "sql": "SELECT t.TEST_ID, t.TEST_NAME, t.TABLE_TYPE AS database_type, t.QPS, t.P50_LATENCY_MS, t.P95_LATENCY_MS, t.P99_LATENCY_MS, t.AVG_LATENCY_MS, t.MAX_LATENCY_MS, t.ERROR_RATE, t.TOTAL_OPERATIONS, t.CONCURRENT_CONNECTIONS, t.DURATION_SECONDS FROM TEST_RESULTS AS t WHERE t.TEST_ID = :test_id",
        "question": "What are the detailed execution metrics and timing information for a specific benchmark test?"
      },
      {
        "name": "Failed Tests in Run",
        "sql": "SELECT TEST_ID, TEST_NAME, TABLE_TYPE AS database_type, WAREHOUSE_SIZE, STATUS, ERROR_RATE, START_TIME FROM TEST_RESULTS WHERE STATUS = ''FAILED'' ORDER BY START_TIME DESC",
        "question": "Which benchmark tests failed during the specific benchmark run?"
      },
      {
        "name": "Warmup vs Test Phase Queries",
        "sql": "SELECT CASE WHEN WARMUP = TRUE THEN ''Warmup'' ELSE ''Measurement'' END AS phase, COUNT(*) AS query_count, SUM(CASE WHEN SUCCESS = TRUE THEN 1 ELSE 0 END) AS successful, SUM(CASE WHEN SUCCESS = FALSE THEN 1 ELSE 0 END) AS failed FROM QUERY_EXECUTIONS WHERE TEST_ID = :test_id GROUP BY WARMUP",
        "question": "How many queries were executed during warmup versus actual testing phases for this benchmark test?"
      },
      {
        "name": "Successful Operations by Type",
        "sql": "SELECT QUERY_KIND AS operation_type, COUNT(*) AS successful_count FROM QUERY_EXECUTIONS WHERE TEST_ID = :test_id AND WARMUP = FALSE AND SUCCESS = TRUE GROUP BY QUERY_KIND ORDER BY successful_count DESC",
        "question": "How many successful operations of specific types were completed in a particular test run?"
      },
      {
        "name": "Multiple Tests Comparison",
        "sql": "SELECT t.TEST_ID, t.TEST_NAME, t.TABLE_TYPE AS database_type, t.TOTAL_OPERATIONS, t.FAILED_OPERATIONS, t.QPS, t.ERROR_RATE FROM TEST_RESULTS AS t WHERE t.STATUS = ''COMPLETED'' ORDER BY t.START_TIME DESC LIMIT 10",
        "question": "What are the execution volumes and failure counts for multiple benchmark tests?"
      },
      {
        "name": "Recent PostgreSQL Tests",
        "sql": "SELECT TEST_ID, TEST_NAME, WAREHOUSE_SIZE, QPS, P50_LATENCY_MS, P95_LATENCY_MS, ERROR_RATE, STATUS, START_TIME FROM TEST_RESULTS WHERE TABLE_TYPE = ''POSTGRES'' ORDER BY START_TIME DESC LIMIT 10",
        "question": "What are my recent postgres tests?"
      },
      {
        "name": "Analyze Latest PostgreSQL Test",
        "sql": "SELECT TEST_ID, TEST_NAME, TABLE_TYPE, WAREHOUSE_SIZE, STATUS, QPS, P50_LATENCY_MS, P95_LATENCY_MS, P99_LATENCY_MS, AVG_LATENCY_MS, ERROR_RATE, TOTAL_OPERATIONS, READ_OPERATIONS, WRITE_OPERATIONS, FAILED_OPERATIONS, DURATION_SECONDS, CONCURRENT_CONNECTIONS, START_TIME, END_TIME FROM TEST_RESULTS WHERE TABLE_TYPE = ''POSTGRES'' ORDER BY START_TIME DESC LIMIT 1",
        "question": "Analyze my latest postgres test"
      },
      {
        "name": "Benchmark Scope and Coverage",
        "sql": "SELECT COUNT(DISTINCT TEST_ID) AS total_tests, COUNT(DISTINCT TABLE_TYPE) AS database_types_tested, COUNT(DISTINCT WAREHOUSE_SIZE) AS warehouse_sizes_tested, SUM(TOTAL_OPERATIONS) AS total_operations, SUM(READ_OPERATIONS) AS total_reads, SUM(WRITE_OPERATIONS) AS total_writes, SUM(FAILED_OPERATIONS) AS total_failures FROM TEST_RESULTS WHERE STATUS = ''COMPLETED''",
        "question": "What is the scope and coverage of the benchmark run in terms of total operations executed, operation types tested, and number of individual tests performed?"
      },
      {
        "name": "Tests with Query Failures",
        "sql": "SELECT TEST_ID, TEST_NAME, TABLE_TYPE AS database_type, WAREHOUSE_SIZE, FAILED_OPERATIONS, ERROR_RATE, TOTAL_OPERATIONS, STATUS FROM TEST_RESULTS WHERE FAILED_OPERATIONS > 0 OR ERROR_RATE > 0 ORDER BY ERROR_RATE DESC, FAILED_OPERATIONS DESC",
        "question": "Which benchmark tests experienced query failures during this specific benchmark run?"
      },
      {
        "name": "Benchmark Test Count",
        "sql": "SELECT TABLE_TYPE AS database_type, WAREHOUSE_SIZE, STATUS, COUNT(*) AS test_count FROM TEST_RESULTS GROUP BY TABLE_TYPE, WAREHOUSE_SIZE, STATUS ORDER BY TABLE_TYPE, WAREHOUSE_SIZE, STATUS",
        "question": "How many benchmark tests match the search criteria across all database systems and configurations?"
      },
      {
        "name": "Operations and Failures per Test",
        "sql": "SELECT TEST_ID, TEST_NAME, TABLE_TYPE AS database_type, TOTAL_OPERATIONS, FAILED_OPERATIONS, ERROR_RATE, QPS FROM TEST_RESULTS WHERE STATUS = ''COMPLETED'' ORDER BY START_TIME DESC",
        "question": "What is the total number of operations and failure count for each benchmark test run?"
      },
      {
        "name": "Latest Interactive Table Test",
        "sql": "SELECT TEST_ID, TEST_NAME, TABLE_TYPE, WAREHOUSE_SIZE, STATUS, QPS, P50_LATENCY_MS, P95_LATENCY_MS, P99_LATENCY_MS, AVG_LATENCY_MS, ERROR_RATE, TOTAL_OPERATIONS, READ_OPERATIONS, WRITE_OPERATIONS, FAILED_OPERATIONS, DURATION_SECONDS, CONCURRENT_CONNECTIONS, START_TIME, END_TIME FROM TEST_RESULTS WHERE TABLE_TYPE = ''INTERACTIVE'' ORDER BY START_TIME DESC LIMIT 1",
        "question": "Tell me about my latest interactive table test"
      },
      {
        "name": "Recent Interactive Table Tests",
        "sql": "SELECT TEST_ID, TEST_NAME, WAREHOUSE_SIZE, QPS, P50_LATENCY_MS, P95_LATENCY_MS, ERROR_RATE, STATUS, START_TIME FROM TEST_RESULTS WHERE TABLE_TYPE = ''INTERACTIVE'' ORDER BY START_TIME DESC LIMIT 10",
        "question": "What are my recent interactive table tests?"
      },
      {
        "name": "Compare Interactive vs Hybrid Tables",
        "sql": "SELECT TABLE_TYPE AS database_type, COUNT(DISTINCT TEST_ID) AS test_count, ROUND(AVG(QPS), 1) AS avg_qps, ROUND(AVG(P50_LATENCY_MS), 2) AS avg_p50_ms, ROUND(AVG(P95_LATENCY_MS), 2) AS avg_p95_ms, ROUND(AVG(P99_LATENCY_MS), 2) AS avg_p99_ms FROM TEST_RESULTS WHERE TABLE_TYPE IN (''INTERACTIVE'', ''HYBRID'') AND STATUS = ''COMPLETED'' GROUP BY TABLE_TYPE ORDER BY avg_qps DESC",
        "question": "Compare Interactive tables vs Hybrid tables performance"
      },
      {
        "name": "All Database Types Summary",
        "sql": "SELECT TABLE_TYPE AS database_type, COUNT(DISTINCT TEST_ID) AS test_count, ROUND(AVG(QPS), 1) AS avg_qps, ROUND(MIN(P50_LATENCY_MS), 2) AS best_p50_ms, ROUND(AVG(P50_LATENCY_MS), 2) AS avg_p50_ms, ROUND(AVG(P95_LATENCY_MS), 2) AS avg_p95_ms, ROUND(AVG(ERROR_RATE), 4) AS avg_error_rate FROM TEST_RESULTS WHERE STATUS = ''COMPLETED'' GROUP BY TABLE_TYPE ORDER BY avg_qps DESC",
        "question": "Give me a summary of all database types tested"
      }
    ]
  }');

-- =============================================================================
-- Post-Creation Validation
-- =============================================================================
-- Run these commands to verify the semantic view was created correctly

-- Show the semantic view
SHOW SEMANTIC VIEWS LIKE 'BENCHMARK_ANALYTICS';

-- Show dimensions
SHOW SEMANTIC DIMENSIONS IN SEMANTIC VIEW BENCHMARK_ANALYTICS;

-- Show metrics  
SHOW SEMANTIC METRICS IN SEMANTIC VIEW BENCHMARK_ANALYTICS;

-- Show facts
SHOW SEMANTIC FACTS IN SEMANTIC VIEW BENCHMARK_ANALYTICS;

-- Get the DDL
SELECT GET_DDL('SEMANTIC_VIEW', 'FLAKEBENCH.TEST_RESULTS.BENCHMARK_ANALYTI   