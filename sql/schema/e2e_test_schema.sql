-- =============================================================================
-- E2E Test Schema Setup - Isolated Test Environment
-- =============================================================================
-- Creates a dedicated test schema for E2E tests that can be safely reset
-- between test runs. Uses the same table structure as production but in
-- an isolated FLAKEBENCH_E2E_TEST schema.
--
-- Usage:
--   Run this script to set up the test environment
--   Tests use FLAKEBENCH.E2E_TEST schema instead of FLAKEBENCH.TEST_RESULTS
--
-- Cleanup:
--   DROP SCHEMA FLAKEBENCH.E2E_TEST CASCADE;
-- =============================================================================

USE DATABASE FLAKEBENCH;

-- Create isolated test schema
CREATE SCHEMA IF NOT EXISTS E2E_TEST;
USE SCHEMA E2E_TEST;

-- =============================================================================
-- RUN_STATUS: Authoritative state for a parent run (E2E Test Copy)
-- =============================================================================
CREATE HYBRID TABLE IF NOT EXISTS RUN_STATUS (
    run_id VARCHAR(36) NOT NULL,
    test_id VARCHAR(36) NOT NULL,
    
    -- Configuration Snapshot
    template_id VARCHAR(36),
    test_name VARCHAR(500),
    scenario_config VARIANT,
    
    -- Lifecycle State
    status VARCHAR(50) NOT NULL,
    phase VARCHAR(50) NOT NULL,
    
    -- Timing (Authoritative)
    start_time TIMESTAMP_NTZ,
    end_time TIMESTAMP_NTZ,
    warmup_start_time TIMESTAMP_NTZ,
    warmup_end_time TIMESTAMP_NTZ,
    
    -- Worker Orchestration
    total_workers_expected INTEGER DEFAULT 1,
    workers_registered INTEGER DEFAULT 0,
    workers_active INTEGER DEFAULT 0,
    workers_completed INTEGER DEFAULT 0,
    
    -- Aggregate Metrics
    total_ops INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    current_qps FLOAT DEFAULT 0.0,
    
    -- State tracking
    find_max_state VARIANT,
    worker_targets VARIANT,
    next_sequence_id INTEGER DEFAULT 1,
    cancellation_reason TEXT,
    qps_controller_state VARIANT,
    
    -- Audit
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    CONSTRAINT PK_RUN_STATUS PRIMARY KEY (run_id)
);

-- =============================================================================
-- RUN_CONTROL_EVENTS: Command channel for workers (E2E Test Copy)
-- =============================================================================
CREATE HYBRID TABLE IF NOT EXISTS RUN_CONTROL_EVENTS (
    event_id VARCHAR(36) NOT NULL,
    run_id VARCHAR(36) NOT NULL,
    
    event_type VARCHAR(50) NOT NULL,
    event_data VARIANT NOT NULL,
    
    sequence_id INTEGER NOT NULL,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    CONSTRAINT PK_RUN_CONTROL_EVENTS PRIMARY KEY (event_id),
    CONSTRAINT FK_RUN_CONTROL_EVENTS_RUN_ID FOREIGN KEY (run_id) 
        REFERENCES RUN_STATUS (run_id)
);

-- =============================================================================
-- WORKER_HEARTBEATS: Liveness tracking (E2E Test Copy)
-- =============================================================================
CREATE HYBRID TABLE IF NOT EXISTS WORKER_HEARTBEATS (
    run_id VARCHAR(36) NOT NULL,
    worker_id VARCHAR(100) NOT NULL,
    worker_group_id INTEGER NOT NULL,
    
    status VARCHAR(50) NOT NULL,
    phase VARCHAR(50),
    
    last_heartbeat TIMESTAMP_NTZ NOT NULL,
    heartbeat_count INTEGER DEFAULT 0,
    
    active_connections INTEGER DEFAULT 0,
    target_connections INTEGER DEFAULT 0,
    
    cpu_percent FLOAT,
    memory_percent FLOAT,
    
    queries_processed INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    CONSTRAINT PK_WORKER_HEARTBEATS PRIMARY KEY (run_id, worker_id),
    CONSTRAINT FK_WORKER_HEARTBEATS_RUN_ID FOREIGN KEY (run_id) 
        REFERENCES RUN_STATUS (run_id)
);

-- =============================================================================
-- TEST_TEMPLATES: Mirrors production table name for E2E tests
-- =============================================================================
CREATE TABLE IF NOT EXISTS TEST_TEMPLATES (
    template_id VARCHAR(36) NOT NULL,
    template_name VARCHAR(500) NOT NULL,
    config VARIANT NOT NULL,
    tags VARIANT,
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    CONSTRAINT PK_TEST_TEMPLATES PRIMARY KEY (template_id)
);

-- Insert a minimal test template for E2E tests
-- Config uses the flat structure expected by test_registry._scenario_from_template_config
-- All workloads are normalized to CUSTOM; weights must sum to 100.
MERGE INTO TEST_TEMPLATES AS target
USING (
    SELECT 
        'e2e-test-template-001' AS template_id,
        'E2E Test Template - Short Duration' AS template_name,
        PARSE_JSON($${
            "database": "FLAKEBENCH",
            "schema": "E2E_TEST",
            "table_name": "E2E_SAMPLE_DATA",
            "table_type": "STANDARD",
            "warehouse_name": "COMPUTE_WH",
            "warehouse_size": "XSMALL",
            "duration": 10,
            "warmup": 2,
            "concurrent_connections": 2,
            "start_concurrency": 2,
            "workload_type": "CUSTOM",
            "mix_preset": "MIXED",
            "load_mode": "CONCURRENCY",
            "scaling": {"mode": "FIXED", "min_workers": 1, "max_workers": 1, "min_connections": 2, "max_connections": 2},
            "columns": {"ID": "INTEGER", "NAME": "VARCHAR(100)", "VALUE": "FLOAT", "CATEGORY": "VARCHAR(50)"},
            "custom_point_lookup_pct": 50,
            "custom_point_lookup_query": "SELECT * FROM {table} WHERE ID = ?",
            "custom_range_scan_pct": 50,
            "custom_range_scan_query": "SELECT * FROM {table} WHERE ID BETWEEN ? AND ? + 10",
            "custom_insert_pct": 0,
            "custom_update_pct": 0
        }$$) AS config,
        PARSE_JSON('{}') AS tags
) AS source
ON target.template_id = source.template_id
WHEN NOT MATCHED THEN
    INSERT (template_id, template_name, config, tags)
    VALUES (source.template_id, source.template_name, source.config, source.tags);

-- =============================================================================
-- E2E_SAMPLE_DATA: Small test dataset for E2E tests
-- =============================================================================
CREATE TABLE IF NOT EXISTS E2E_SAMPLE_DATA (
    id INTEGER NOT NULL,
    name VARCHAR(100),
    value FLOAT,
    category VARCHAR(50),
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    CONSTRAINT PK_E2E_SAMPLE_DATA PRIMARY KEY (id)
);

-- Insert sample data (idempotent)
MERGE INTO E2E_SAMPLE_DATA AS target
USING (
    SELECT 
        ROW_NUMBER() OVER (ORDER BY SEQ4()) AS id,
        'Item_' || SEQ4()::VARCHAR AS name,
        RANDOM() * 1000 AS value,
        CASE MOD(SEQ4(), 4)
            WHEN 0 THEN 'CATEGORY_A'
            WHEN 1 THEN 'CATEGORY_B'
            WHEN 2 THEN 'CATEGORY_C'
            ELSE 'CATEGORY_D'
        END AS category
    FROM TABLE(GENERATOR(ROWCOUNT => 100))
) AS source
ON target.id = source.id
WHEN NOT MATCHED THEN
    INSERT (id, name, value, category)
    VALUES (source.id, source.name, source.value, source.category);

-- =============================================================================
-- Cleanup Procedure: Reset test state between runs
-- =============================================================================
CREATE OR REPLACE PROCEDURE E2E_CLEANUP()
RETURNS VARCHAR
LANGUAGE SQL
AS
$$
BEGIN
    -- Delete all test data (order matters due to foreign keys)
    DELETE FROM WORKER_HEARTBEATS;
    DELETE FROM RUN_CONTROL_EVENTS;
    DELETE FROM RUN_STATUS;
    
    RETURN 'E2E test data cleaned up successfully';
END;
$$;

-- Grant execute to test user (adjust role as needed)
-- GRANT USAGE ON PROCEDURE E2E_CLEANUP() TO ROLE <your_test_role>;
