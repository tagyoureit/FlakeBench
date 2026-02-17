# Delayed Enrichment - Data Architecture

**Document Version:** 0.2 (Post-Review)  
**Parent:** [00-overview.md](00-overview.md)

---

## 1. Schema Changes Overview

### 1.1 New Tables

| Table | Purpose | Source View | Retention |
|-------|---------|-------------|-----------|
| `AGGREGATE_QUERY_METRICS` | Per-test aggregated stats from AGGREGATE_QUERY_HISTORY | AGGREGATE_QUERY_HISTORY | Same as TEST_RESULTS |
| `LOCK_CONTENTION_EVENTS` | Individual row-lock wait events | LOCK_WAIT_HISTORY | Same as TEST_RESULTS |
| `HYBRID_TABLE_CREDITS` | Per-test hybrid table credit consumption | HYBRID_TABLE_USAGE_HISTORY | Same as TEST_RESULTS |
| `QUERY_INSIGHTS_CACHE` | Cached query optimization insights | QUERY_INSIGHTS | 30 days |
| `DELAYED_ENRICHMENT_QUEUE` | Pending delayed enrichment jobs | Internal | 30 days after completion |

### 1.2 Column Additions

**TEST_RESULTS table:**
```sql
-- Delayed enrichment tracking
DELAYED_ENRICHMENT_STATUS VARCHAR(20),        -- PENDING, IN_PROGRESS, COMPLETED, FAILED, SKIPPED
DELAYED_ENRICHMENT_ERROR TEXT,
DELAYED_ENRICHMENT_COMPLETED_AT TIMESTAMP_NTZ,

-- Aggregate enrichment from AGGREGATE_QUERY_HISTORY  
AGGREGATE_ENRICHMENT_STATUS VARCHAR(20),      -- PENDING, COMPLETED, FAILED, NOT_APPLICABLE
THROTTLED_QUERY_COUNT INTEGER,                -- From HYBRID_TABLE_REQUESTS_THROTTLED_COUNT

-- Hybrid table credits from HYBRID_TABLE_USAGE_HISTORY
HYBRID_CREDITS_USED FLOAT,
HYBRID_CREDITS_REQUESTS BIGINT,
HYBRID_CREDITS_START_TIME TIMESTAMP_NTZ,
HYBRID_CREDITS_END_TIME TIMESTAMP_NTZ
```

**QUERY_EXECUTIONS table:**
```sql
-- Already exists but never populated from INFORMATION_SCHEMA:
-- sf_partitions_scanned BIGINT,
-- sf_partitions_total BIGINT,
-- sf_bytes_spilled_local BIGINT,
-- sf_bytes_spilled_remote BIGINT

-- New column for parameterized hash (for AGGREGATE_QUERY_HISTORY joins)
QUERY_PARAMETERIZED_HASH VARCHAR(64)
```

---

## 2. New Table DDL

### 2.1 AGGREGATE_QUERY_METRICS

Stores per-test aggregated metrics from AGGREGATE_QUERY_HISTORY. One row per (test, query_parameterized_hash) combination.

```sql
-- =============================================================================
-- AGGREGATE_QUERY_METRICS: Server-side percentiles from AGGREGATE_QUERY_HISTORY
-- Captures hybrid table query metrics that are MISSING from QUERY_HISTORY
-- =============================================================================
CREATE OR ALTER TABLE AGGREGATE_QUERY_METRICS (
    -- Identity
    METRIC_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    
    -- Query pattern identification
    QUERY_PARAMETERIZED_HASH VARCHAR(64) NOT NULL,
    QUERY_TAG VARCHAR(500),
    
    -- Time range of aggregation (summed across 1-minute intervals)
    INTERVAL_START TIMESTAMP_NTZ NOT NULL,
    INTERVAL_END TIMESTAMP_NTZ NOT NULL,
    INTERVAL_COUNT INTEGER NOT NULL,           -- Number of 1-minute intervals included
    
    -- Query counts
    QUERY_COUNT BIGINT NOT NULL,               -- Sum of queries across intervals
    ERRORS_COUNT INTEGER DEFAULT 0,
    
    -- Execution time percentiles (milliseconds, from EXECUTION_TIME OBJECT)
    -- v0.2: Changed FLOAT to NUMBER(38,3) for precise timing. Added P95.
    EXEC_SUM_MS NUMBER(38,3),
    EXEC_AVG_MS NUMBER(38,3),
    EXEC_STDDEV_MS NUMBER(38,3),
    EXEC_MIN_MS NUMBER(38,3),
    EXEC_MEDIAN_MS NUMBER(38,3),
    EXEC_P90_MS NUMBER(38,3),
    EXEC_P95_MS NUMBER(38,3),                  -- v0.2: Added (interpolated from p90/p99)
    EXEC_P99_MS NUMBER(38,3),
    EXEC_P999_MS NUMBER(38,3),
    EXEC_MAX_MS NUMBER(38,3),
    
    -- Compilation time percentiles (milliseconds)
    COMPILE_SUM_MS NUMBER(38,3),
    COMPILE_AVG_MS NUMBER(38,3),
    COMPILE_MIN_MS NUMBER(38,3),
    COMPILE_MEDIAN_MS NUMBER(38,3),
    COMPILE_P90_MS NUMBER(38,3),
    COMPILE_P99_MS NUMBER(38,3),
    COMPILE_MAX_MS NUMBER(38,3),
    
    -- Total elapsed time percentiles (milliseconds)
    ELAPSED_SUM_MS NUMBER(38,3),
    ELAPSED_AVG_MS NUMBER(38,3),
    ELAPSED_MIN_MS NUMBER(38,3),
    ELAPSED_MEDIAN_MS NUMBER(38,3),
    ELAPSED_P90_MS NUMBER(38,3),
    ELAPSED_P99_MS NUMBER(38,3),
    ELAPSED_MAX_MS NUMBER(38,3),
    
    -- Queue time percentiles (milliseconds)
    QUEUED_OVERLOAD_SUM_MS NUMBER(38,3),
    QUEUED_OVERLOAD_AVG_MS NUMBER(38,3),
    QUEUED_OVERLOAD_MAX_MS NUMBER(38,3),
    QUEUED_PROVISIONING_SUM_MS NUMBER(38,3),
    QUEUED_PROVISIONING_AVG_MS NUMBER(38,3),
    QUEUED_PROVISIONING_MAX_MS NUMBER(38,3),
    
    -- Hybrid table specific
    HYBRID_REQUESTS_THROTTLED_COUNT INTEGER DEFAULT 0,
    
    -- Bytes scanned percentiles
    BYTES_SCANNED_SUM BIGINT,
    BYTES_SCANNED_AVG BIGINT,
    BYTES_SCANNED_MAX BIGINT,
    
    -- Rows produced percentiles
    ROWS_PRODUCED_SUM BIGINT,
    ROWS_PRODUCED_AVG BIGINT,
    ROWS_PRODUCED_MAX BIGINT,
    
    -- Error breakdown (VARIANT for flexibility)
    ERRORS_BREAKDOWN VARIANT,                  -- [{error_code, error_message, count}, ...]
    
    -- Raw AGGREGATE_QUERY_HISTORY sample (for debugging, optional via config)
    RAW_SAMPLE VARIANT,
    
    -- Audit
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SOURCE_VIEW VARCHAR(50) DEFAULT 'AGGREGATE_QUERY_HISTORY',
    
    -- v0.2: Added PK and unique constraint per review feedback
    CONSTRAINT PK_AGGREGATE_QUERY_METRICS PRIMARY KEY (METRIC_ID),
    CONSTRAINT UQ_AGG_METRICS_TEST_HASH UNIQUE (TEST_ID, QUERY_PARAMETERIZED_HASH)
);

-- Clustering for efficient test-level queries
ALTER TABLE AGGREGATE_QUERY_METRICS CLUSTER BY (TEST_ID);

-- v0.2: Enable search optimization for hash lookups
ALTER TABLE AGGREGATE_QUERY_METRICS ADD SEARCH OPTIMIZATION ON EQUALITY(QUERY_PARAMETERIZED_HASH);
```

### 2.2 LOCK_CONTENTION_EVENTS

Stores individual lock wait events from LOCK_WAIT_HISTORY for timeline visualization.

```sql
-- =============================================================================
-- LOCK_CONTENTION_EVENTS: Row-level lock wait events from LOCK_WAIT_HISTORY
-- Only populated for hybrid tables (row-level locking)
-- =============================================================================
CREATE OR ALTER TABLE LOCK_CONTENTION_EVENTS (
    -- Identity
    EVENT_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    
    -- Lock event identification (from LOCK_WAIT_HISTORY)
    LOCK_TRANSACTION_ID NUMBER(38,0),
    BLOCKING_TRANSACTION_ID NUMBER(38,0),
    
    -- Timing (v0.2: standardized to TIMESTAMP_NTZ, convert LTZ at insert time)
    REQUESTED_AT TIMESTAMP_NTZ NOT NULL,
    LOCK_ACQUIRED_AT TIMESTAMP_NTZ,
    WAIT_DURATION_MS NUMBER(38,3),              -- Derived from timestamps
    
    -- Lock details
    LOCK_TYPE VARCHAR(20) NOT NULL,            -- 'ROW' for hybrid tables
    OBJECT_ID NUMBER(38,0),
    OBJECT_NAME VARCHAR(500),
    SCHEMA_NAME VARCHAR(500),
    DATABASE_NAME VARCHAR(500),
    
    -- Query context (if available)
    QUERY_ID VARCHAR(500),
    BLOCKING_QUERY_ID VARCHAR(500),
    
    -- Raw row (for debugging)
    RAW_EVENT VARIANT,
    
    -- Audit
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- v0.2: Added PK constraint
    CONSTRAINT PK_LOCK_CONTENTION_EVENTS PRIMARY KEY (EVENT_ID)
);

-- Clustering for efficient test timeline queries
ALTER TABLE LOCK_CONTENTION_EVENTS CLUSTER BY (TEST_ID, REQUESTED_AT);
```

### 2.3 HYBRID_TABLE_CREDITS

Stores hybrid table serverless credit consumption per test.

```sql
-- =============================================================================
-- HYBRID_TABLE_CREDITS: Serverless credit consumption from HYBRID_TABLE_USAGE_HISTORY
-- Tracks cost of hybrid table requests during test execution
-- =============================================================================
CREATE OR ALTER TABLE HYBRID_TABLE_CREDITS (
    -- Identity
    CREDIT_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    
    -- Table identification
    TABLE_ID NUMBER(38,0),
    TABLE_NAME VARCHAR(500) NOT NULL,
    SCHEMA_NAME VARCHAR(500),
    DATABASE_NAME VARCHAR(500),
    
    -- Time range (v0.2: standardized to TIMESTAMP_NTZ, convert LTZ at insert time)
    START_TIME TIMESTAMP_NTZ NOT NULL,
    END_TIME TIMESTAMP_NTZ NOT NULL,
    
    -- Credit consumption (v0.2: NUMBER(38,3) for precise decimal arithmetic)
    CREDITS_USED NUMBER(38,3) NOT NULL,
    REQUESTS_COUNT BIGINT NOT NULL,
    
    -- Breakdown by request type (VARIANT for flexibility)
    CREDITS_BY_TYPE VARIANT,                   -- {READ: x, WRITE: y, ...}
    
    -- Raw data (for debugging)
    RAW_DATA VARIANT,
    
    -- Audit
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- v0.2: Added PK constraint
    CONSTRAINT PK_HYBRID_TABLE_CREDITS PRIMARY KEY (CREDIT_ID)
);

-- Clustering for efficient test-level queries
ALTER TABLE HYBRID_TABLE_CREDITS CLUSTER BY (TEST_ID);
```

### 2.4 QUERY_INSIGHTS_CACHE

Caches automated query optimization insights.

```sql
-- =============================================================================
-- QUERY_INSIGHTS_CACHE: Automated optimization suggestions from QUERY_INSIGHTS
-- Provides actionable recommendations per query pattern
-- =============================================================================
CREATE OR ALTER TABLE QUERY_INSIGHTS_CACHE (
    -- Identity
    INSIGHT_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    
    -- Query identification
    QUERY_ID VARCHAR(500),
    QUERY_PARAMETERIZED_HASH VARCHAR(64),
    QUERY_TEXT TEXT,
    
    -- Insight details (from QUERY_INSIGHTS view)
    INSIGHT_TYPE VARCHAR(100) NOT NULL,        -- e.g., 'PARTITION_PRUNING', 'JOIN_ORDER'
    INSIGHT_CATEGORY VARCHAR(50),
    INSIGHT_SEVERITY VARCHAR(20),              -- 'HIGH', 'MEDIUM', 'LOW'
    
    -- Recommendation
    RECOMMENDATION TEXT NOT NULL,
    RECOMMENDATION_DETAILS VARIANT,
    
    -- Impact estimation
    ESTIMATED_IMPROVEMENT_PCT FLOAT,
    AFFECTED_QUERY_COUNT INTEGER,
    
    -- Raw insight (for debugging)
    RAW_INSIGHT VARIANT,
    
    -- Audit
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    EXPIRES_AT TIMESTAMP_NTZ,                  -- For cache invalidation
    
    -- v0.2: Added PK constraint
    CONSTRAINT PK_QUERY_INSIGHTS_CACHE PRIMARY KEY (INSIGHT_ID)
);

-- Clustering for efficient test-level queries
ALTER TABLE QUERY_INSIGHTS_CACHE CLUSTER BY (TEST_ID);
```

### 2.5 DELAYED_ENRICHMENT_QUEUE

Tracks pending delayed enrichment jobs for resilience.

```sql
-- =============================================================================
-- DELAYED_ENRICHMENT_QUEUE: Pending delayed enrichment jobs
-- Persists queue state for crash recovery and multi-instance coordination
-- =============================================================================
CREATE OR ALTER TABLE DELAYED_ENRICHMENT_QUEUE (
    -- Identity
    JOB_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    
    -- Scheduling
    TEST_END_TIME TIMESTAMP_NTZ NOT NULL,      -- When test completed
    EARLIEST_ENRICHMENT_TIME TIMESTAMP_NTZ NOT NULL,  -- When views should be available
    
    -- Job configuration
    TABLE_TYPE VARCHAR(50) NOT NULL,           -- Affects which views to query
    ENRICHMENT_TYPES VARIANT NOT NULL,         -- ['QUERY_HISTORY', 'AGGREGATE', 'LOCK', 'CREDITS', 'INSIGHTS']
    
    -- Status tracking
    -- v0.2: Expanded statuses: PENDING, IN_PROGRESS, COMPLETED, FAILED, SKIPPED, NOT_APPLICABLE
    STATUS VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    ATTEMPTS INTEGER DEFAULT 0,
    LAST_ATTEMPT_AT TIMESTAMP_NTZ,
    LAST_ERROR TEXT,
    
    -- v0.2: Atomic job claim columns (D7 - Concurrency Control)
    -- Used by UPDATE...WHERE subquery pattern to prevent race conditions
    CLAIMED_BY VARCHAR(100),                   -- Worker instance identifier (hostname:pid)
    CLAIMED_AT TIMESTAMP_NTZ,                  -- When the claim was made (stale claim detection)
    
    -- Completion tracking
    COMPLETED_TYPES VARIANT,                   -- Which enrichment types completed
    COMPLETED_AT TIMESTAMP_NTZ,
    
    -- Audit
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    
    -- Constraints
    CONSTRAINT PK_DELAYED_ENRICHMENT_QUEUE PRIMARY KEY (JOB_ID)
);

-- Index for pending job queries
ALTER TABLE DELAYED_ENRICHMENT_QUEUE CLUSTER BY (STATUS, EARLIEST_ENRICHMENT_TIME);
```

---

## 3. TEST_RESULTS Column Additions

Add these columns to the existing TEST_RESULTS table:

```sql
-- =============================================================================
-- ALTER TEST_RESULTS: Add delayed enrichment tracking columns
-- =============================================================================
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    DELAYED_ENRICHMENT_STATUS VARCHAR(20);

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    DELAYED_ENRICHMENT_ERROR TEXT;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    DELAYED_ENRICHMENT_COMPLETED_AT TIMESTAMP_NTZ;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    AGGREGATE_ENRICHMENT_STATUS VARCHAR(20);

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    THROTTLED_QUERY_COUNT INTEGER;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    HYBRID_CREDITS_USED FLOAT;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    HYBRID_CREDITS_REQUESTS BIGINT;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    HYBRID_CREDITS_START_TIME TIMESTAMP_NTZ;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    HYBRID_CREDITS_END_TIME TIMESTAMP_NTZ;

-- Lock contention summary (denormalized from LOCK_CONTENTION_EVENTS)
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    LOCK_WAIT_COUNT INTEGER;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    LOCK_WAIT_TOTAL_MS FLOAT;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    LOCK_WAIT_MAX_MS FLOAT;

-- Query insights summary
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    QUERY_INSIGHTS_COUNT INTEGER;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    QUERY_INSIGHTS_HIGH_SEVERITY_COUNT INTEGER;
```

---

## 4. QUERY_EXECUTIONS Column Additions

```sql
-- =============================================================================
-- ALTER QUERY_EXECUTIONS: Add parameterized hash for AGGREGATE_QUERY_HISTORY joins
-- =============================================================================
ALTER TABLE FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS ADD COLUMN IF NOT EXISTS
    QUERY_PARAMETERIZED_HASH VARCHAR(64);

-- Note: sf_partitions_scanned, sf_partitions_total, sf_bytes_spilled_local, 
-- sf_bytes_spilled_remote already exist but will now be populated from 
-- ACCOUNT_USAGE.QUERY_HISTORY instead of INFORMATION_SCHEMA
```

---

## 5. Data Flow Diagrams

### 5.1 Overall Enrichment Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           TEST EXECUTION                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  PHASE: PROCESSING (Immediate Enrichment)                                    │
│                                                                              │
│  Source: INFORMATION_SCHEMA.QUERY_HISTORY()                                  │
│  Target: QUERY_EXECUTIONS                                                    │
│  Columns: sf_execution_ms, sf_compilation_ms, sf_cluster_number, etc.       │
│  Coverage: ~90% standard, ~0.1% hybrid                                       │
│                                                                              │
│  Code: backend/core/results_store.py:enrich_query_executions_with_retry()   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STATUS UPDATE                                                               │
│                                                                              │
│  TEST_RESULTS.ENRICHMENT_STATUS = 'COMPLETED'                               │
│  TEST_RESULTS.DELAYED_ENRICHMENT_STATUS = 'PENDING'                         │
│                                                                              │
│  INSERT INTO DELAYED_ENRICHMENT_QUEUE (...)                                 │
│  - EARLIEST_ENRICHMENT_TIME = TEST_END_TIME + 3 hours                       │
│  - ENRICHMENT_TYPES based on TABLE_TYPE                                     │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    │ (3 hours later)
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  BACKGROUND TASK: Delayed Enrichment Processor                               │
│                                                                              │
│  Code: backend/core/delayed_enrichment.py:DelayedEnrichmentProcessor       │
│                                                                              │
│  Poll interval: 5 minutes                                                    │
│  Query: SELECT * FROM DELAYED_ENRICHMENT_QUEUE                              │
│         WHERE STATUS = 'PENDING'                                            │
│         AND EARLIEST_ENRICHMENT_TIME <= CURRENT_TIMESTAMP()                 │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    │               │               │
                    ▼               ▼               ▼
           ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
           │ Standard/     │ │ Hybrid/       │ │ All           │
           │ Interactive   │ │ Unistore      │ │ Table Types   │
           │ Tables        │ │ Tables        │ │               │
           └───────────────┘ └───────────────┘ └───────────────┘
                    │               │               │
                    ▼               ▼               ▼
           ┌───────────────┐ ┌───────────────┐ ┌───────────────┐
           │ ACCOUNT_USAGE │ │ AGGREGATE_    │ │ QUERY_        │
           │ .QUERY_HISTORY│ │ QUERY_HISTORY │ │ INSIGHTS      │
           │               │ │               │ │               │
           │ Fill:         │ │ Fill:         │ │ Fill:         │
           │ - partitions_ │ │ - AGGREGATE_  │ │ - QUERY_      │
           │   scanned     │ │   QUERY_      │ │   INSIGHTS_   │
           │ - partitions_ │ │   METRICS     │ │   CACHE       │
           │   total       │ │               │ │               │
           │ - bytes_      │ │ Hybrid only:  │ │               │
           │   spilled_*   │ │ - LOCK_       │ │               │
           │               │ │   CONTENTION_ │ │               │
           │               │ │   EVENTS      │ │               │
           │               │ │ - HYBRID_     │ │               │
           │               │ │   TABLE_      │ │               │
           │               │ │   CREDITS     │ │               │
           └───────────────┘ └───────────────┘ └───────────────┘
                    │               │               │
                    └───────────────┼───────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STATUS UPDATE                                                               │
│                                                                              │
│  TEST_RESULTS.DELAYED_ENRICHMENT_STATUS = 'COMPLETED'                       │
│  TEST_RESULTS.DELAYED_ENRICHMENT_COMPLETED_AT = CURRENT_TIMESTAMP()         │
│                                                                              │
│  DELAYED_ENRICHMENT_QUEUE.STATUS = 'COMPLETED'                              │
│                                                                              │
│  WebSocket: emit enrichment_complete event                                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 AGGREGATE_QUERY_HISTORY Enrichment Detail

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  INPUT: TEST_ID, RUN_ID, QUERY_TAG, START_TIME, END_TIME                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  QUERY: SNOWFLAKE.ACCOUNT_USAGE.AGGREGATE_QUERY_HISTORY                     │
│                                                                              │
│  SELECT                                                                      │
│      QUERY_PARAMETERIZED_HASH,                                              │
│      MIN(INTERVAL_START_TIME) AS interval_start,                            │
│      MAX(INTERVAL_END_TIME) AS interval_end,                                │
│      COUNT(*) AS interval_count,                                            │
│      SUM(QUERY_COUNT) AS query_count,                                       │
│      -- Execution time percentiles (from OBJECT columns)                    │
│      SUM(EXECUTION_TIME:sum) AS exec_sum_ms,                                │
│      AVG(EXECUTION_TIME:avg) AS exec_avg_ms,                                │
│      MIN(EXECUTION_TIME:min) AS exec_min_ms,                                │
│      MAX(EXECUTION_TIME:max) AS exec_max_ms,                                │
│      -- etc. for all percentile fields                                      │
│      SUM(HYBRID_TABLE_REQUESTS_THROTTLED_COUNT) AS throttled_count,         │
│      ARRAY_AGG(ERRORS) AS errors_array                                      │
│  FROM SNOWFLAKE.ACCOUNT_USAGE.AGGREGATE_QUERY_HISTORY                       │
│  WHERE QUERY_TAG LIKE 'flakebench:run_id=' || ? || '%'                      │
│    AND INTERVAL_START_TIME >= ? - INTERVAL '5 minutes'                      │
│    AND INTERVAL_END_TIME <= ? + INTERVAL '5 minutes'                        │
│  GROUP BY QUERY_PARAMETERIZED_HASH                                          │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  INSERT INTO AGGREGATE_QUERY_METRICS (...)                                  │
│                                                                              │
│  One row per QUERY_PARAMETERIZED_HASH                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  UPDATE TEST_RESULTS                                                         │
│  SET                                                                         │
│      AGGREGATE_ENRICHMENT_STATUS = 'COMPLETED',                             │
│      THROTTLED_QUERY_COUNT = (SELECT SUM(throttled) FROM above)             │
│  WHERE TEST_ID = ?                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Lock Contention Enrichment Detail

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  INPUT: TEST_ID, RUN_ID, TABLE_NAME, START_TIME, END_TIME                   │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  QUERY: SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY                           │
│                                                                              │
│  SELECT                                                                      │
│      LOCK_TRANSACTION_ID,                                                   │
│      BLOCKING_TRANSACTION_ID,                                               │
│      REQUESTED_AT,                                                          │
│      LOCK_ACQUIRED_AT,                                                      │
│      TIMESTAMPDIFF('millisecond', REQUESTED_AT, LOCK_ACQUIRED_AT)           │
│          AS wait_duration_ms,                                               │
│      LOCK_TYPE,                                                             │
│      OBJECT_ID,                                                             │
│      OBJECT_NAME,                                                           │
│      SCHEMA_NAME,                                                           │
│      DATABASE_NAME,                                                         │
│      QUERY_ID,                                                              │
│      BLOCKING_QUERY_ID                                                      │
│  FROM SNOWFLAKE.ACCOUNT_USAGE.LOCK_WAIT_HISTORY                             │
│  WHERE OBJECT_NAME = ?                                                      │
│    AND LOCK_TYPE = 'ROW'                                                    │
│    AND REQUESTED_AT >= ?                                                    │
│    AND REQUESTED_AT <= ?                                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  INSERT INTO LOCK_CONTENTION_EVENTS (...)                                   │
│                                                                              │
│  One row per lock wait event                                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  UPDATE TEST_RESULTS                                                         │
│  SET                                                                         │
│      LOCK_WAIT_COUNT = (SELECT COUNT(*) FROM LOCK_CONTENTION_EVENTS ...),  │
│      LOCK_WAIT_TOTAL_MS = (SELECT SUM(WAIT_DURATION_MS) ...),              │
│      LOCK_WAIT_MAX_MS = (SELECT MAX(WAIT_DURATION_MS) ...)                 │
│  WHERE TEST_ID = ?                                                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 6. Views for Analysis

### 6.1 V_AGGREGATE_QUERY_STATS

Aggregates AGGREGATE_QUERY_METRICS at test level for easy consumption.

```sql
CREATE OR REPLACE VIEW V_AGGREGATE_QUERY_STATS AS
SELECT
    TEST_ID,
    RUN_ID,
    COUNT(DISTINCT QUERY_PARAMETERIZED_HASH) AS unique_query_patterns,
    SUM(QUERY_COUNT) AS total_queries,
    
    -- Execution time aggregates (weighted by query count)
    SUM(EXEC_SUM_MS) AS total_exec_ms,
    SUM(EXEC_SUM_MS) / NULLIF(SUM(QUERY_COUNT), 0) AS weighted_avg_exec_ms,
    MAX(EXEC_MAX_MS) AS max_exec_ms,
    
    -- Use worst-case percentiles across patterns
    MAX(EXEC_P95_MS) AS worst_p95_exec_ms,
    MAX(EXEC_P99_MS) AS worst_p99_exec_ms,
    
    -- Throttling
    SUM(HYBRID_REQUESTS_THROTTLED_COUNT) AS total_throttled_requests,
    
    -- Errors
    SUM(ERRORS_COUNT) AS total_errors,
    
    -- Queue time
    SUM(QUEUED_OVERLOAD_SUM_MS) AS total_queued_overload_ms,
    MAX(QUEUED_OVERLOAD_MAX_MS) AS max_queued_overload_ms
    
FROM AGGREGATE_QUERY_METRICS
GROUP BY TEST_ID, RUN_ID;
```

### 6.2 V_LOCK_CONTENTION_SUMMARY

Summarizes lock contention at test level.

```sql
CREATE OR REPLACE VIEW V_LOCK_CONTENTION_SUMMARY AS
SELECT
    TEST_ID,
    RUN_ID,
    COUNT(*) AS lock_wait_count,
    SUM(WAIT_DURATION_MS) AS total_wait_ms,
    AVG(WAIT_DURATION_MS) AS avg_wait_ms,
    MAX(WAIT_DURATION_MS) AS max_wait_ms,
    MIN(REQUESTED_AT) AS first_lock_wait,
    MAX(REQUESTED_AT) AS last_lock_wait,
    COUNT(DISTINCT OBJECT_NAME) AS affected_tables,
    COUNT(DISTINCT BLOCKING_TRANSACTION_ID) AS unique_blockers
FROM LOCK_CONTENTION_EVENTS
GROUP BY TEST_ID, RUN_ID;
```

### 6.3 V_DELAYED_ENRICHMENT_STATUS

Shows pending and recent delayed enrichment jobs.

```sql
CREATE OR REPLACE VIEW V_DELAYED_ENRICHMENT_STATUS AS
SELECT
    q.JOB_ID,
    q.TEST_ID,
    q.RUN_ID,
    q.TABLE_TYPE,
    q.STATUS,
    q.TEST_END_TIME,
    q.EARLIEST_ENRICHMENT_TIME,
    TIMESTAMPDIFF('minute', CURRENT_TIMESTAMP(), q.EARLIEST_ENRICHMENT_TIME) AS minutes_until_eligible,
    q.ATTEMPTS,
    q.LAST_ERROR,
    -- v0.2: Added claim tracking columns
    q.CLAIMED_BY,
    q.CLAIMED_AT,
    tr.TEST_NAME,
    tr.ENRICHMENT_STATUS AS immediate_enrichment_status,
    tr.DELAYED_ENRICHMENT_STATUS
FROM DELAYED_ENRICHMENT_QUEUE q
-- v0.2: Fixed broken join (was tr.TEST_ID = tr.RUN_ID, now correctly joins on RUN_ID)
JOIN TEST_RESULTS tr ON q.TEST_ID = tr.TEST_ID AND q.RUN_ID = tr.RUN_ID
ORDER BY q.EARLIEST_ENRICHMENT_TIME ASC;
```

---

## 7. Data Volume Estimates (v0.2)

Estimates based on typical FlakeBench usage patterns:

| Table | Growth Driver | Est. Rows/Test | Est. Rows/Day (50 tests) | Retention |
|-------|--------------|----------------|--------------------------|-----------|
| AGGREGATE_QUERY_METRICS | 1 row per unique QUERY_PARAMETERIZED_HASH per test | 3-10 | 150-500 | Permanent |
| LOCK_CONTENTION_EVENTS | 1 row per lock wait event (hybrid tables only) | 0-50 | 0-500 | Permanent |
| HYBRID_TABLE_CREDITS | 1 row per table per 15-min interval | 1-4 | 50-200 | Permanent |
| QUERY_INSIGHTS_CACHE | 0-5 per test (only when Snowflake generates insights) | 0-5 | 0-250 | EXPIRES_AT TTL |
| DELAYED_ENRICHMENT_QUEUE | 1 per test | 1 | 50 | 30 days after completion |

**Storage impact**: Minimal. At 50 tests/day, ~1,500 new rows/day across all tables. VARIANT columns (RAW_EVENT, RAW_DATA, RAW_INSIGHT) are the largest; estimate ~2KB each. Total: ~3MB/day, ~1GB/year.

---

## 8. Foreign Key Documentation (v0.2, Informational Only)

These relationships are **NOT enforced** as Snowflake FK constraints (they're informational only and would add overhead). Documented here for data model clarity:

```
AGGREGATE_QUERY_METRICS.TEST_ID  → TEST_RESULTS.TEST_ID
AGGREGATE_QUERY_METRICS.RUN_ID   → TEST_RESULTS.RUN_ID
LOCK_CONTENTION_EVENTS.TEST_ID   → TEST_RESULTS.TEST_ID
LOCK_CONTENTION_EVENTS.RUN_ID    → TEST_RESULTS.RUN_ID
HYBRID_TABLE_CREDITS.TEST_ID     → TEST_RESULTS.TEST_ID
HYBRID_TABLE_CREDITS.RUN_ID      → TEST_RESULTS.RUN_ID
QUERY_INSIGHTS_CACHE.TEST_ID     → TEST_RESULTS.TEST_ID
QUERY_INSIGHTS_CACHE.RUN_ID      → TEST_RESULTS.RUN_ID
DELAYED_ENRICHMENT_QUEUE.TEST_ID → TEST_RESULTS.TEST_ID
DELAYED_ENRICHMENT_QUEUE.RUN_ID  → TEST_RESULTS.RUN_ID
```

Application-level enforcement: DELETE CASCADE is handled by the cleanup/purge routines, not DB constraints.

---

## 9. Migration Strategy

### 9.1 Schema Migration Order

1. Create new tables (AGGREGATE_QUERY_METRICS, LOCK_CONTENTION_EVENTS, etc.)
2. Add columns to TEST_RESULTS (non-breaking, all nullable)
3. Add column to QUERY_EXECUTIONS (non-breaking, nullable)
4. Create views
5. Deploy backend code
6. Backfill existing tests (optional, Phase 4+)

### 9.2 Rollback Plan

All changes are additive (new tables, new columns). Rollback:
1. Stop delayed enrichment processor
2. Drop new tables
3. (Optional) Drop new columns - or leave as NULL

---

**Next:** [02-backend-implementation.md](02-backend-implementation.md) - Code changes and scheduling strategy
