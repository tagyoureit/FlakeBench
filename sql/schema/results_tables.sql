-- =============================================================================
-- Unistore Benchmark - Results Storage Schema
-- =============================================================================
-- This schema stores test results, metrics, and configurations for 
-- Snowflake/Postgres performance benchmarking.
--
-- Database: UNISTORE_BENCHMARK
-- Schema: TEST_RESULTS
-- =============================================================================

-- Create database if it doesn't exist
CREATE DATABASE IF NOT EXISTS UNISTORE_BENCHMARK;

-- Create schema for test results
CREATE SCHEMA IF NOT EXISTS UNISTORE_BENCHMARK.TEST_RESULTS;

USE SCHEMA UNISTORE_BENCHMARK.TEST_RESULTS;

-- =============================================================================
-- TEST_RESULTS: Store individual test execution results
-- =============================================================================
CREATE TABLE IF NOT EXISTS TEST_RESULTS (
    -- Identification
    test_id VARCHAR(36) PRIMARY KEY,
    run_id VARCHAR(36),
    test_name VARCHAR(500) NOT NULL,
    scenario_name VARCHAR(500) NOT NULL,
    
    -- Test configuration summary
    table_name VARCHAR(500) NOT NULL,
    table_type VARCHAR(50) NOT NULL,
    warehouse VARCHAR(500),
    warehouse_size VARCHAR(50),
    
    -- Execution metadata
    status VARCHAR(50) NOT NULL,
    start_time TIMESTAMP_NTZ NOT NULL,
    end_time TIMESTAMP_NTZ,
    duration_seconds FLOAT,
    
    -- Workload summary
    concurrent_connections INTEGER NOT NULL,
    total_operations INTEGER DEFAULT 0,
    read_operations INTEGER DEFAULT 0,
    write_operations INTEGER DEFAULT 0,
    failed_operations INTEGER DEFAULT 0,
    
    -- Performance metrics (operations/second)
    operations_per_second FLOAT DEFAULT 0.0,
    reads_per_second FLOAT DEFAULT 0.0,
    writes_per_second FLOAT DEFAULT 0.0,
    
    -- Latency metrics (milliseconds)
    avg_latency_ms FLOAT DEFAULT 0.0,
    p50_latency_ms FLOAT DEFAULT 0.0,
    p90_latency_ms FLOAT DEFAULT 0.0,
    p95_latency_ms FLOAT DEFAULT 0.0,
    p99_latency_ms FLOAT DEFAULT 0.0,
    max_latency_ms FLOAT DEFAULT 0.0,
    min_latency_ms FLOAT DEFAULT 0.0,
    
    -- Throughput metrics
    bytes_read BIGINT DEFAULT 0,
    bytes_written BIGINT DEFAULT 0,
    rows_read BIGINT DEFAULT 0,
    rows_written BIGINT DEFAULT 0,
    
    -- Resource utilization
    warehouse_credits_used FLOAT,
    avg_cpu_percent FLOAT,
    avg_memory_mb FLOAT,
    
    -- Errors and issues
    error_count INTEGER DEFAULT 0,
    error_rate FLOAT DEFAULT 0.0,
    errors VARIANT,
    
    -- Detailed data (JSON/VARIANT)
    query_executions VARIANT,
    metrics_snapshots VARIANT,
    test_config VARIANT,
    custom_metrics VARIANT,
    
    -- Tags and metadata
    tags VARIANT,
    notes TEXT,
    
    -- Audit fields
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- =============================================================================
-- METRICS_SNAPSHOTS: Time-series metrics data
-- =============================================================================
CREATE TABLE IF NOT EXISTS METRICS_SNAPSHOTS (
    snapshot_id VARCHAR(36) PRIMARY KEY,
    test_id VARCHAR(36) NOT NULL,
    
    -- Timing
    timestamp TIMESTAMP_NTZ NOT NULL,
    elapsed_seconds FLOAT NOT NULL,
    
    -- Core metrics
    total_operations INTEGER NOT NULL,
    operations_per_second FLOAT NOT NULL,
    
    -- Latency metrics (milliseconds)
    p50_latency_ms FLOAT NOT NULL,
    p95_latency_ms FLOAT NOT NULL,
    p99_latency_ms FLOAT NOT NULL,
    avg_latency_ms FLOAT NOT NULL,
    
    -- Operation breakdown
    read_count INTEGER DEFAULT 0,
    write_count INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    
    -- Throughput
    bytes_per_second FLOAT DEFAULT 0.0,
    rows_per_second FLOAT DEFAULT 0.0,
    
    -- Connection pool
    active_connections INTEGER DEFAULT 0,
    
    -- Additional metrics (JSON)
    custom_metrics VARIANT,
    
    -- Audit
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- Foreign keys
    FOREIGN KEY (test_id) REFERENCES TEST_RESULTS(test_id)
);

-- =============================================================================
-- QUERY_EXECUTIONS: Detailed query execution history
-- =============================================================================
CREATE TABLE IF NOT EXISTS QUERY_EXECUTIONS (
    execution_id VARCHAR(36) PRIMARY KEY,
    test_id VARCHAR(36) NOT NULL,
    query_id VARCHAR(500) NOT NULL,
    
    -- Query details
    query_text TEXT NOT NULL,
    start_time TIMESTAMP_NTZ NOT NULL,
    end_time TIMESTAMP_NTZ NOT NULL,
    duration_ms FLOAT NOT NULL,
    
    -- Results
    rows_affected INTEGER,
    bytes_scanned BIGINT,
    warehouse VARCHAR(500),
    success BOOLEAN NOT NULL,
    error TEXT,
    
    -- Metadata
    connection_id INTEGER,
    custom_metadata VARIANT,
    
    -- Audit
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- Foreign keys
    FOREIGN KEY (test_id) REFERENCES TEST_RESULTS(test_id)
);

-- =============================================================================
-- Note: Indexes removed - Snowflake Standard Tables use automatic clustering
-- instead of traditional indexes. For better query performance, consider:
--   - Using clustering keys on frequently filtered columns
--   - Converting to Hybrid Tables if transactional semantics needed
--   - Using search optimization service for point lookups
-- =============================================================================

-- =============================================================================
-- Views for common queries
-- =============================================================================

-- Latest test results summary
CREATE OR REPLACE VIEW V_LATEST_TEST_RESULTS AS
SELECT 
    test_id,
    test_name,
    scenario_name,
    table_name,
    table_type,
    status,
    start_time,
    duration_seconds,
    operations_per_second,
    p95_latency_ms,
    error_rate,
    created_at
FROM TEST_RESULTS
WHERE start_time >= DATEADD(day, -7, CURRENT_TIMESTAMP())
ORDER BY start_time DESC;

-- Metrics snapshots aggregated by minute
CREATE OR REPLACE VIEW V_METRICS_BY_MINUTE AS
SELECT 
    test_id,
    DATE_TRUNC('minute', timestamp) AS minute,
    AVG(operations_per_second) AS avg_ops_per_sec,
    MAX(operations_per_second) AS max_ops_per_sec,
    AVG(p95_latency_ms) AS avg_p95_latency_ms,
    MAX(p95_latency_ms) AS max_p95_latency_ms,
    SUM(error_count) AS total_errors
FROM METRICS_SNAPSHOTS
GROUP BY test_id, DATE_TRUNC('minute', timestamp)
ORDER BY test_id, minute;

-- =============================================================================
-- Complete
-- =============================================================================

SELECT 'Schema setup complete' AS status;
