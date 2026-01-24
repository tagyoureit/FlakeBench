-- =============================================================================
-- Unistore Benchmark - Control Plane Schema (Hybrid Tables)
-- =============================================================================
-- This schema defines the coordination tables for multi-node benchmarking.
-- These tables MUST be Hybrid Tables (Unistore) to support:
-- 1. Row-level locking for concurrent heartbeats
-- 2. ACID transactions for phase transitions
-- 3. High-frequency updates (up to ~20 nodes at 5s intervals)
--
-- REQUIREMENTS:
-- - Snowflake Enterprise Edition or higher
-- - AWS or Azure commercial region (not GCP or SnowGov)
-- - Not supported in trial accounts
--
-- NOTE: Hybrid Tables do NOT support CREATE OR ALTER syntax.
-- Use CREATE ... IF NOT EXISTS for idempotent deployments, or
-- DROP TABLE + CREATE HYBRID TABLE for schema changes.
-- =============================================================================

USE DATABASE UNISTORE_BENCHMARK;
USE SCHEMA TEST_RESULTS;

-- =============================================================================
-- RUN_STATUS: Authoritative state for a parent run
-- =============================================================================
-- Tracks the lifecycle of a distributed test run.
-- Primary Key: RUN_ID (UUID)
-- =============================================================================
CREATE HYBRID TABLE IF NOT EXISTS RUN_STATUS (
    run_id VARCHAR(36) NOT NULL,
    test_id VARCHAR(36) NOT NULL, -- Usually same as RUN_ID for parent
    
    -- Configuration Snapshot
    template_id VARCHAR(36),
    test_name VARCHAR(500),
    scenario_config VARIANT, -- JSON blob of the full run config
    
    -- Lifecycle State
    status VARCHAR(50) NOT NULL, -- PREPARED, RUNNING, STOPPING, COMPLETED, FAILED
    phase VARCHAR(50) NOT NULL,  -- WARMUP, MEASUREMENT, COOLDOWN
    
    -- Timing (Authoritative)
    start_time TIMESTAMP_NTZ,
    end_time TIMESTAMP_NTZ,
    warmup_end_time TIMESTAMP_NTZ,
    
    -- Worker Orchestration
    total_workers_expected INTEGER DEFAULT 1,
    workers_registered INTEGER DEFAULT 0,
    workers_active INTEGER DEFAULT 0,
    workers_completed INTEGER DEFAULT 0,
    
    -- Aggregate Metrics (Updated by Orchestrator)
    total_ops INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    current_qps FLOAT DEFAULT 0.0,
    
    -- Find Max State (Live)
    find_max_state VARIANT, -- { current_step, target_workers, status, ... }

    -- Audit
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    CONSTRAINT PK_RUN_STATUS PRIMARY KEY (run_id)
);

-- =============================================================================
-- RUN_CONTROL_EVENTS: Command channel for workers
-- =============================================================================
-- Append-only log of control signals (STOP, PAUSE, PHASE_CHANGE).
-- Workers poll this table to know when to exit or change behavior.
-- =============================================================================
CREATE HYBRID TABLE IF NOT EXISTS RUN_CONTROL_EVENTS (
    event_id VARCHAR(36) NOT NULL,
    run_id VARCHAR(36) NOT NULL,
    
    -- Event Payload
    event_type VARCHAR(50) NOT NULL, -- STOP, PAUSE, RESUME, SET_PHASE
    event_data VARIANT,              -- JSON payload (e.g. { "phase": "MEASUREMENT" })
    
    -- Ordering
    sequence_id INTEGER,             -- Monotonic counter for this run
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    CONSTRAINT PK_RUN_CONTROL_EVENTS PRIMARY KEY (event_id),
    CONSTRAINT FK_RUN_CONTROL_EVENTS_RUN_ID FOREIGN KEY (run_id) 
        REFERENCES RUN_STATUS (run_id)
);

-- =============================================================================
-- WORKER_HEARTBEATS: Liveness tracking
-- =============================================================================
-- Workers upsert to this table every 1 second.
-- Orchestrator monitors this to detect dead/zombie nodes.
-- See docs/next-worker-implementation.md for full details.
-- =============================================================================
CREATE HYBRID TABLE IF NOT EXISTS WORKER_HEARTBEATS (
    run_id VARCHAR(36) NOT NULL,
    worker_id VARCHAR(100) NOT NULL, -- Unique per process/container
    worker_group_id INTEGER NOT NULL,
    
    -- Status
    status VARCHAR(50) NOT NULL, -- STARTING, WAITING, RUNNING, DRAINING, COMPLETED, DEAD
    phase VARCHAR(50),           -- WARMUP, MEASUREMENT, COOLDOWN (mirrors worker's current phase)
    
    -- Liveness
    last_heartbeat TIMESTAMP_NTZ NOT NULL,
    heartbeat_count INTEGER DEFAULT 0,
    
    -- Connection tracking
    active_connections INTEGER DEFAULT 0,
    target_connections INTEGER DEFAULT 0,
    
    -- Resources (optional)
    cpu_percent FLOAT,
    memory_percent FLOAT,
    
    -- Metrics Snapshot (Latest)
    queries_processed INTEGER DEFAULT 0,
    error_count INTEGER DEFAULT 0,
    
    -- Error tracking
    last_error TEXT,
    
    -- Audit
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    updated_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    CONSTRAINT PK_WORKER_HEARTBEATS PRIMARY KEY (run_id, worker_id),
    CONSTRAINT FK_WORKER_HEARTBEATS_RUN_ID FOREIGN KEY (run_id) 
        REFERENCES RUN_STATUS (run_id)
);

-- =============================================================================
-- Indexes for Polling Efficiency
-- =============================================================================
-- Hybrid Tables use primary keys for clustering, but secondary indexes 
-- can help with specific lookups if needed.
-- For now, we rely on point lookups by RUN_ID which are efficient.
