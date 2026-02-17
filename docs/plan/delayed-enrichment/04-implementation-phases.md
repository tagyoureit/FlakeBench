# Delayed Enrichment - Implementation Phases

**Document Version:** 0.2 (Review Pass 1)  
**Parent:** [00-overview.md](00-overview.md)

---

## Phase Overview

| Phase | Focus | Latency Addressed | Table Types |
|-------|-------|-------------------|-------------|
| **Phase 1** | ACCOUNT_USAGE.QUERY_HISTORY | 45 minutes | All Snowflake |
| **Phase 2** | AGGREGATE_QUERY_HISTORY | 3 hours | All (critical for hybrid) |
| **Phase 3** | LOCK_WAIT_HISTORY + HYBRID_TABLE_USAGE_HISTORY | 3 hours | Hybrid only |
| **Phase 4** | QUERY_INSIGHTS | 90 minutes | All Snowflake |

---

## Phase 1: ACCOUNT_USAGE.QUERY_HISTORY Enrichment

### Goal
Fill the existing empty columns in QUERY_EXECUTIONS (`sf_partitions_scanned`, `sf_partitions_total`, `sf_bytes_spilled_local`, `sf_bytes_spilled_remote`) using ACCOUNT_USAGE.QUERY_HISTORY, which provides these columns unlike INFORMATION_SCHEMA.QUERY_HISTORY().

### Prerequisites
- [ ] Verify ACCOUNT_USAGE access for the Snowflake user/role
- [ ] Verify QUERY_TAG is set correctly during test execution

### Schema Changes

**Files to modify:**
- `sql/schema/results_tables.sql`

```sql
-- Add to results_tables.sql

-- Add delayed enrichment tracking columns to TEST_RESULTS
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    DELAYED_ENRICHMENT_STATUS VARCHAR(20);

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    DELAYED_ENRICHMENT_ERROR TEXT;

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    DELAYED_ENRICHMENT_COMPLETED_AT TIMESTAMP_NTZ;

-- Add parameterized hash to QUERY_EXECUTIONS for future AGGREGATE joins
ALTER TABLE FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS ADD COLUMN IF NOT EXISTS
    QUERY_PARAMETERIZED_HASH VARCHAR(64);

-- Create delayed enrichment queue table
CREATE OR ALTER TABLE DELAYED_ENRICHMENT_QUEUE (
    JOB_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    TABLE_TYPE VARCHAR(50) NOT NULL,
    TEST_END_TIME TIMESTAMP_NTZ NOT NULL,
    EARLIEST_ENRICHMENT_TIME TIMESTAMP_NTZ NOT NULL,
    ENRICHMENT_TYPES VARIANT NOT NULL,
    STATUS VARCHAR(20) NOT NULL DEFAULT 'PENDING',  -- PENDING, IN_PROGRESS, COMPLETED, FAILED, SKIPPED, NOT_APPLICABLE
    ATTEMPTS INTEGER DEFAULT 0,
    LAST_ATTEMPT_AT TIMESTAMP_NTZ,
    LAST_ERROR TEXT,
    -- v0.2: Atomic job claim columns (D7 - Concurrency Control)
    CLAIMED_BY VARCHAR(100),
    CLAIMED_AT TIMESTAMP_NTZ,
    COMPLETED_TYPES VARIANT,
    COMPLETED_AT TIMESTAMP_NTZ,
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_DELAYED_ENRICHMENT_QUEUE PRIMARY KEY (JOB_ID)
);

ALTER TABLE DELAYED_ENRICHMENT_QUEUE CLUSTER BY (STATUS, EARLIEST_ENRICHMENT_TIME);
```

### Backend Changes

**Files to create:**
- `backend/core/delayed_enrichment.py` (partial implementation)

**Files to modify:**
- `backend/core/orchestrator.py` (line ~2464, after immediate enrichment)
- `backend/core/results_store.py` (add queue management functions)
- `backend/main.py` (add processor startup/shutdown)

### Tasks

1. **Create delayed_enrichment.py module**
   - [ ] Implement `DelayedEnrichmentProcessor` class with basic poll loop
   - [ ] Implement `create_delayed_enrichment_job()` function
   - [ ] Implement `_enrich_from_account_usage_query_history()` method
   - [ ] Add `EnrichmentType` enum with `QUERY_HISTORY` only

2. **Modify orchestrator.py**
   - [ ] Import `create_delayed_enrichment_job` in `_run_enrichment()`
   - [ ] Call `create_delayed_enrichment_job()` after immediate enrichment completes
   - [ ] Handle errors gracefully (don't fail test if job creation fails)

3. **Modify results_store.py**
   - [ ] Add `update_delayed_enrichment_status()` function
   - [ ] Add `get_delayed_enrichment_status()` function

4. **Modify main.py**
   - [ ] Import `get_delayed_enrichment_processor`
   - [ ] Start processor in lifespan startup
   - [ ] Stop processor in lifespan shutdown

5. **Run schema migrations**
   - [ ] Execute ALTER statements on TEST_RESULTS
   - [ ] Execute ALTER statement on QUERY_EXECUTIONS
   - [ ] Create DELAYED_ENRICHMENT_QUEUE table

6. **Queue cleanup routine**
   - [ ] Add cleanup task that purges COMPLETED/FAILED jobs older than 30 days
   - [ ] Schedule cleanup to run daily
   - [ ] Log cleanup statistics

### Acceptance Criteria

- [ ] New tests create DELAYED_ENRICHMENT_QUEUE entries
- [ ] Processor polls and processes eligible jobs
- [ ] QUERY_EXECUTIONS.sf_partitions_scanned populated after ~50 minutes
- [ ] QUERY_EXECUTIONS.sf_bytes_spilled_local populated
- [ ] TEST_RESULTS.DELAYED_ENRICHMENT_STATUS updated correctly
- [ ] Errors logged and stored in DELAYED_ENRICHMENT_ERROR
- [ ] No regression in immediate enrichment

### Verification SQL

```sql
-- Check queue status
SELECT STATUS, COUNT(*), AVG(ATTEMPTS) 
FROM FLAKEBENCH.TEST_RESULTS.DELAYED_ENRICHMENT_QUEUE 
GROUP BY STATUS;

-- Check enrichment effectiveness
SELECT 
    COUNT(*) AS total_queries,
    COUNT(SF_PARTITIONS_SCANNED) AS with_partitions,
    COUNT(SF_BYTES_SPILLED_LOCAL) AS with_spill_local
FROM FLAKEBENCH.TEST_RESULTS.QUERY_EXECUTIONS
WHERE TEST_ID = '<recent_test_id>';
```

---

## Phase 2: AGGREGATE_QUERY_HISTORY Enrichment

### Goal
Add server-side percentiles from AGGREGATE_QUERY_HISTORY. This is the **critical fix for hybrid tables** where individual queries are skipped from QUERY_HISTORY.

### Prerequisites
- [ ] Phase 1 complete and stable
- [ ] AGGREGATE_QUERY_METRICS table created

### Schema Changes

**Files to modify:**
- `sql/schema/results_tables.sql`

```sql
-- Create AGGREGATE_QUERY_METRICS table
CREATE OR ALTER TABLE AGGREGATE_QUERY_METRICS (
    METRIC_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    QUERY_PARAMETERIZED_HASH VARCHAR(64) NOT NULL,
    QUERY_TAG VARCHAR(500),
    INTERVAL_START TIMESTAMP_NTZ NOT NULL,
    INTERVAL_END TIMESTAMP_NTZ NOT NULL,
    INTERVAL_COUNT INTEGER NOT NULL,
    QUERY_COUNT BIGINT NOT NULL,
    ERRORS_COUNT INTEGER DEFAULT 0,
    EXEC_SUM_MS NUMBER(38,3),
    EXEC_AVG_MS NUMBER(38,3),
    EXEC_STDDEV_MS NUMBER(38,3),
    EXEC_MIN_MS NUMBER(38,3),
    EXEC_MEDIAN_MS NUMBER(38,3),
    EXEC_P90_MS NUMBER(38,3),
    EXEC_P95_MS NUMBER(38,3),  -- v0.2: Interpolated from p90/p99 at insert time
    EXEC_P99_MS NUMBER(38,3),
    EXEC_P999_MS NUMBER(38,3),
    EXEC_MAX_MS NUMBER(38,3),
    COMPILE_SUM_MS NUMBER(38,3),
    COMPILE_AVG_MS NUMBER(38,3),
    COMPILE_MIN_MS NUMBER(38,3),
    COMPILE_MEDIAN_MS NUMBER(38,3),
    COMPILE_P90_MS NUMBER(38,3),
    COMPILE_P99_MS NUMBER(38,3),
    COMPILE_MAX_MS NUMBER(38,3),
    ELAPSED_SUM_MS NUMBER(38,3),
    ELAPSED_AVG_MS NUMBER(38,3),
    ELAPSED_MIN_MS NUMBER(38,3),
    ELAPSED_MEDIAN_MS NUMBER(38,3),
    ELAPSED_P90_MS NUMBER(38,3),
    ELAPSED_P99_MS NUMBER(38,3),
    ELAPSED_MAX_MS NUMBER(38,3),
    QUEUED_OVERLOAD_SUM_MS NUMBER(38,3),
    QUEUED_OVERLOAD_AVG_MS NUMBER(38,3),
    QUEUED_OVERLOAD_MAX_MS NUMBER(38,3),
    QUEUED_PROVISIONING_SUM_MS NUMBER(38,3),
    QUEUED_PROVISIONING_AVG_MS NUMBER(38,3),
    QUEUED_PROVISIONING_MAX_MS NUMBER(38,3),
    HYBRID_REQUESTS_THROTTLED_COUNT INTEGER DEFAULT 0,
    BYTES_SCANNED_SUM BIGINT,
    BYTES_SCANNED_AVG BIGINT,
    BYTES_SCANNED_MAX BIGINT,
    ROWS_PRODUCED_SUM BIGINT,
    ROWS_PRODUCED_AVG BIGINT,
    ROWS_PRODUCED_MAX BIGINT,
    ERRORS_BREAKDOWN VARIANT,
    RAW_SAMPLE VARIANT,
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    SOURCE_VIEW VARCHAR(50) DEFAULT 'AGGREGATE_QUERY_HISTORY',
    CONSTRAINT PK_AGGREGATE_QUERY_METRICS PRIMARY KEY (METRIC_ID),
    CONSTRAINT UQ_AGG_METRICS_TEST_HASH UNIQUE (TEST_ID, QUERY_PARAMETERIZED_HASH)
);

ALTER TABLE AGGREGATE_QUERY_METRICS CLUSTER BY (TEST_ID);
ALTER TABLE AGGREGATE_QUERY_METRICS SET SEARCH_OPTIMIZATION = ON;

-- Add aggregate status column to TEST_RESULTS
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    AGGREGATE_ENRICHMENT_STATUS VARCHAR(20);

ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    THROTTLED_QUERY_COUNT INTEGER;

-- Create summary view
-- v0.2: EXEC_P95_MS is now a valid column (interpolated from p90/p99 at insert time)
CREATE OR REPLACE VIEW V_AGGREGATE_QUERY_STATS AS
SELECT
    TEST_ID, RUN_ID,
    COUNT(DISTINCT QUERY_PARAMETERIZED_HASH) AS unique_query_patterns,
    SUM(QUERY_COUNT) AS total_queries,
    SUM(EXEC_SUM_MS) AS total_exec_ms,
    SUM(EXEC_SUM_MS) / NULLIF(SUM(QUERY_COUNT), 0) AS weighted_avg_exec_ms,
    MAX(EXEC_MAX_MS) AS max_exec_ms,
    MAX(EXEC_P95_MS) AS worst_p95_exec_ms,
    MAX(EXEC_P99_MS) AS worst_p99_exec_ms,
    SUM(HYBRID_REQUESTS_THROTTLED_COUNT) AS total_throttled_requests,
    SUM(ERRORS_COUNT) AS total_errors
FROM AGGREGATE_QUERY_METRICS
GROUP BY TEST_ID, RUN_ID;
```

### Backend Changes

**Files to modify:**
- `backend/core/delayed_enrichment.py`

### Tasks

1. **Extend delayed_enrichment.py**
   - [ ] Add `EnrichmentType.AGGREGATE`
   - [ ] Implement `_enrich_from_aggregate_query_history()` method
   - [ ] Implement `_update_test_aggregate_summary()` helper
   - [ ] Update `get_enrichment_types_for_table_type()` to include AGGREGATE

2. **Add API endpoint**
   - [ ] Add `GET /api/tests/{test_id}/server-metrics` endpoint
   - [ ] Return aggregated percentiles from AGGREGATE_QUERY_METRICS

3. **Add frontend section**
   - [ ] Create `server_metrics_section.html` partial
   - [ ] Create `server_metrics_content.html` partial
   - [ ] Add section to test detail page

4. **Run schema migrations**
   - [ ] Create AGGREGATE_QUERY_METRICS table
   - [ ] Add columns to TEST_RESULTS
   - [ ] Create V_AGGREGATE_QUERY_STATS view

### Acceptance Criteria

- [ ] AGGREGATE_QUERY_METRICS populated for completed tests after 3+ hours
- [ ] Hybrid table tests show server-side percentiles
- [ ] THROTTLED_QUERY_COUNT tracked for hybrid tables
- [ ] Frontend shows "Server-Side Metrics" section
- [ ] Section shows loading state before data available
- [ ] Section shows percentiles after delayed enrichment

### Verification SQL

```sql
-- Check aggregate metrics for a hybrid test
SELECT 
    unique_query_patterns,
    total_queries,
    weighted_avg_exec_ms,
    worst_p95_exec_ms,
    total_throttled_requests
FROM FLAKEBENCH.TEST_RESULTS.V_AGGREGATE_QUERY_STATS
WHERE TEST_ID = '<hybrid_test_id>';

-- Compare client vs server-side latencies
SELECT 
    tr.P95_LATENCY_MS AS client_p95_ms,
    agg.worst_p95_exec_ms AS server_p95_exec_ms,
    agg.worst_p95_exec_ms / tr.P95_LATENCY_MS * 100 AS server_pct_of_client
FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS tr
JOIN FLAKEBENCH.TEST_RESULTS.V_AGGREGATE_QUERY_STATS agg ON tr.TEST_ID = agg.TEST_ID
WHERE tr.TABLE_TYPE = 'HYBRID' AND tr.TEST_ID = tr.RUN_ID;
```

---

## Phase 3: LOCK_WAIT_HISTORY + HYBRID_TABLE_USAGE_HISTORY

### Goal
Add row-level lock contention visibility and hybrid table credit tracking for hybrid/unistore tables.

### Prerequisites
- [ ] Phase 2 complete and stable
- [ ] Verify LOCK_WAIT_HISTORY access
- [ ] Verify HYBRID_TABLE_USAGE_HISTORY access

### Schema Changes

```sql
-- LOCK_CONTENTION_EVENTS table
CREATE OR ALTER TABLE LOCK_CONTENTION_EVENTS (
    EVENT_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    LOCK_TRANSACTION_ID NUMBER(38,0),
    BLOCKING_TRANSACTION_ID NUMBER(38,0),
    REQUESTED_AT TIMESTAMP_NTZ NOT NULL,
    LOCK_ACQUIRED_AT TIMESTAMP_NTZ,
    WAIT_DURATION_MS NUMBER(38,3),
    LOCK_TYPE VARCHAR(20) NOT NULL,
    OBJECT_ID NUMBER(38,0),
    OBJECT_NAME VARCHAR(500),
    SCHEMA_NAME VARCHAR(500),
    DATABASE_NAME VARCHAR(500),
    QUERY_ID VARCHAR(500),
    BLOCKING_QUERY_ID VARCHAR(500),
    RAW_EVENT VARIANT,
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_LOCK_CONTENTION_EVENTS PRIMARY KEY (EVENT_ID)
);

ALTER TABLE LOCK_CONTENTION_EVENTS CLUSTER BY (TEST_ID, REQUESTED_AT);

-- HYBRID_TABLE_CREDITS table
CREATE OR ALTER TABLE HYBRID_TABLE_CREDITS (
    CREDIT_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    TABLE_ID NUMBER(38,0),
    TABLE_NAME VARCHAR(500) NOT NULL,
    SCHEMA_NAME VARCHAR(500),
    DATABASE_NAME VARCHAR(500),
    START_TIME TIMESTAMP_NTZ NOT NULL,
    END_TIME TIMESTAMP_NTZ NOT NULL,
    CREDITS_USED NUMBER(38,3) NOT NULL,
    REQUESTS_COUNT BIGINT NOT NULL,
    CREDITS_BY_TYPE VARIANT,
    RAW_DATA VARIANT,
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CONSTRAINT PK_HYBRID_TABLE_CREDITS PRIMARY KEY (CREDIT_ID)
);

ALTER TABLE HYBRID_TABLE_CREDITS CLUSTER BY (TEST_ID);

-- Add summary columns to TEST_RESULTS
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    LOCK_WAIT_COUNT INTEGER;
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    LOCK_WAIT_TOTAL_MS FLOAT;
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    LOCK_WAIT_MAX_MS FLOAT;
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    HYBRID_CREDITS_USED FLOAT;
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    HYBRID_CREDITS_REQUESTS BIGINT;

-- Lock contention summary view
CREATE OR REPLACE VIEW V_LOCK_CONTENTION_SUMMARY AS
SELECT
    TEST_ID, RUN_ID,
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

### Backend Changes

**Files to modify:**
- `backend/core/delayed_enrichment.py`
- `backend/api/routes/test_results.py`

### Tasks

1. **Extend delayed_enrichment.py**
   - [ ] Add `EnrichmentType.LOCK_CONTENTION`
   - [ ] Add `EnrichmentType.HYBRID_CREDITS`
   - [ ] Implement `_enrich_from_lock_wait_history()` method
   - [ ] Implement `_enrich_from_hybrid_table_usage()` method
   - [ ] Update `get_enrichment_types_for_table_type()` for hybrid tables

2. **Add API endpoints**
   - [ ] Add `GET /api/tests/{test_id}/lock-contention` endpoint
   - [ ] Add `GET /api/tests/{test_id}/hybrid-credits` endpoint

3. **Add frontend sections**
   - [ ] Create `lock_contention_section.html` partial
   - [ ] Create `lock_contention_content.html` partial
   - [ ] Create `hybrid_credits_section.html` partial
   - [ ] Create `hybrid_credits_content.html` partial
   - [ ] Add Chart.js timeline for lock events

4. **Run schema migrations**
   - [ ] Create LOCK_CONTENTION_EVENTS table
   - [ ] Create HYBRID_TABLE_CREDITS table
   - [ ] Add columns to TEST_RESULTS
   - [ ] Create V_LOCK_CONTENTION_SUMMARY view

### Acceptance Criteria

- [ ] LOCK_CONTENTION_EVENTS populated for hybrid tests with contention
- [ ] HYBRID_TABLE_CREDITS populated for hybrid tests
- [ ] TEST_RESULTS.LOCK_WAIT_COUNT updated
- [ ] TEST_RESULTS.HYBRID_CREDITS_USED updated
- [ ] Frontend shows lock contention timeline (hybrid only)
- [ ] Frontend shows credit cost card (hybrid only)
- [ ] Sections hidden for non-hybrid table types

### Verification SQL

```sql
-- Check lock contention for a hybrid test
SELECT * FROM FLAKEBENCH.TEST_RESULTS.V_LOCK_CONTENTION_SUMMARY
WHERE TEST_ID = '<hybrid_test_id>';

-- Check credits for a hybrid test
SELECT 
    TABLE_NAME, CREDITS_USED, REQUESTS_COUNT,
    CREDITS_USED / REQUESTS_COUNT * 1000000 AS credits_per_million_requests
FROM FLAKEBENCH.TEST_RESULTS.HYBRID_TABLE_CREDITS
WHERE TEST_ID = '<hybrid_test_id>';
```

---

## Phase 4: QUERY_INSIGHTS Integration

### Goal
Surface automated query optimization suggestions from Snowflake's QUERY_INSIGHTS view.

### Prerequisites
- [ ] Phase 3 complete and stable
- [ ] Verify QUERY_INSIGHTS view access (may require specific account features)

### Schema Changes

```sql
-- QUERY_INSIGHTS_CACHE table
CREATE OR ALTER TABLE QUERY_INSIGHTS_CACHE (
    INSIGHT_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    QUERY_ID VARCHAR(500),
    QUERY_PARAMETERIZED_HASH VARCHAR(64),
    QUERY_TEXT TEXT,
    INSIGHT_TYPE VARCHAR(100) NOT NULL,
    INSIGHT_CATEGORY VARCHAR(50),
    INSIGHT_SEVERITY VARCHAR(20),
    RECOMMENDATION TEXT NOT NULL,
    RECOMMENDATION_DETAILS VARIANT,
    ESTIMATED_IMPROVEMENT_PCT FLOAT,
    AFFECTED_QUERY_COUNT INTEGER,
    RAW_INSIGHT VARIANT,
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    EXPIRES_AT TIMESTAMP_NTZ,
    CONSTRAINT PK_QUERY_INSIGHTS_CACHE PRIMARY KEY (INSIGHT_ID)
);

ALTER TABLE QUERY_INSIGHTS_CACHE CLUSTER BY (TEST_ID);

-- Add summary columns to TEST_RESULTS
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    QUERY_INSIGHTS_COUNT INTEGER;
ALTER TABLE FLAKEBENCH.TEST_RESULTS.TEST_RESULTS ADD COLUMN IF NOT EXISTS
    QUERY_INSIGHTS_HIGH_SEVERITY_COUNT INTEGER;
```

### Backend Changes

**Files to modify:**
- `backend/core/delayed_enrichment.py`
- `backend/api/routes/test_results.py`

### Tasks

1. **Extend delayed_enrichment.py**
   - [ ] Add `EnrichmentType.QUERY_INSIGHTS`
   - [ ] Implement `_enrich_from_query_insights()` method
   - [ ] Handle gracefully if QUERY_INSIGHTS not available

2. **Add API endpoint**
   - [ ] Add `GET /api/tests/{test_id}/query-insights` endpoint

3. **Add frontend section**
   - [ ] Create `query_insights_section.html` partial
   - [ ] Create `query_insights_content.html` partial
   - [ ] Style insights by severity

4. **Run schema migrations**
   - [ ] Create QUERY_INSIGHTS_CACHE table
   - [ ] Add columns to TEST_RESULTS

### Acceptance Criteria

- [ ] QUERY_INSIGHTS_CACHE populated after ~100 minutes
- [ ] TEST_RESULTS.QUERY_INSIGHTS_COUNT updated
- [ ] Frontend shows optimization suggestions
- [ ] High severity insights highlighted
- [ ] Graceful handling if QUERY_INSIGHTS unavailable

---

## Testing Strategy

### Unit Tests

**Files to create:**
- `tests/test_delayed_enrichment.py`

```python
# tests/test_delayed_enrichment.py

import pytest
from datetime import datetime, timedelta, UTC
from backend.core.delayed_enrichment import (
    EnrichmentType,
    get_enrichment_types_for_table_type,
    calculate_earliest_enrichment_time,
)


class TestEnrichmentTypes:
    def test_standard_table_types(self):
        types = get_enrichment_types_for_table_type("STANDARD")
        assert EnrichmentType.QUERY_HISTORY in types
        assert EnrichmentType.AGGREGATE in types
        assert EnrichmentType.LOCK_CONTENTION not in types
        assert EnrichmentType.HYBRID_CREDITS not in types
    
    def test_hybrid_table_types(self):
        types = get_enrichment_types_for_table_type("HYBRID")
        assert EnrichmentType.QUERY_HISTORY in types
        assert EnrichmentType.AGGREGATE in types
        assert EnrichmentType.LOCK_CONTENTION in types
        assert EnrichmentType.HYBRID_CREDITS in types
    
    def test_postgres_no_enrichment(self):
        types = get_enrichment_types_for_table_type("POSTGRES")
        assert types == []


class TestEarliestEnrichmentTime:
    def test_query_history_only(self):
        now = datetime.now(UTC)
        types = [EnrichmentType.QUERY_HISTORY]
        earliest = calculate_earliest_enrichment_time(now, types)
        # Should be ~50 minutes later
        delta = (earliest - now).total_seconds() / 60
        assert 45 <= delta <= 55
    
    def test_aggregate_determines_max(self):
        now = datetime.now(UTC)
        types = [EnrichmentType.QUERY_HISTORY, EnrichmentType.AGGREGATE]
        earliest = calculate_earliest_enrichment_time(now, types)
        # Should be ~3.25 hours later (AGGREGATE is longest)
        delta = (earliest - now).total_seconds() / 60
        assert 180 <= delta <= 200
```

### Integration Tests

**Manual test procedure:**

1. Run a hybrid table test
2. Verify DELAYED_ENRICHMENT_QUEUE entry created
3. Wait 3+ hours
4. Verify AGGREGATE_QUERY_METRICS populated
5. Verify TEST_RESULTS.DELAYED_ENRICHMENT_STATUS = 'COMPLETED'
6. Verify frontend shows server-side metrics

---

## Rollback Plan

### Phase 1 Rollback
```sql
-- Stop processor first (in Python)

-- v0.2: Backup before rollback
CREATE TABLE IF NOT EXISTS FLAKEBENCH.TEST_RESULTS.DELAYED_ENRICHMENT_QUEUE_ROLLBACK AS 
    SELECT * FROM FLAKEBENCH.TEST_RESULTS.DELAYED_ENRICHMENT_QUEUE;

-- Drop queue table
DROP TABLE IF EXISTS FLAKEBENCH.TEST_RESULTS.DELAYED_ENRICHMENT_QUEUE;

-- Columns can be left (they'll be NULL for new tests)
-- Or explicitly drop:
-- ALTER TABLE TEST_RESULTS DROP COLUMN DELAYED_ENRICHMENT_STATUS;
-- etc.
```

### Phase 2 Rollback
```sql
-- v0.2: Backup before rollback
CREATE TABLE IF NOT EXISTS FLAKEBENCH.TEST_RESULTS.AGGREGATE_QUERY_METRICS_ROLLBACK AS 
    SELECT * FROM FLAKEBENCH.TEST_RESULTS.AGGREGATE_QUERY_METRICS;

DROP TABLE IF EXISTS FLAKEBENCH.TEST_RESULTS.AGGREGATE_QUERY_METRICS;
DROP VIEW IF EXISTS FLAKEBENCH.TEST_RESULTS.V_AGGREGATE_QUERY_STATS;
```

### Phase 3 Rollback
```sql
-- v0.2: Backup before rollback
CREATE TABLE IF NOT EXISTS FLAKEBENCH.TEST_RESULTS.LOCK_CONTENTION_EVENTS_ROLLBACK AS 
    SELECT * FROM FLAKEBENCH.TEST_RESULTS.LOCK_CONTENTION_EVENTS;
CREATE TABLE IF NOT EXISTS FLAKEBENCH.TEST_RESULTS.HYBRID_TABLE_CREDITS_ROLLBACK AS 
    SELECT * FROM FLAKEBENCH.TEST_RESULTS.HYBRID_TABLE_CREDITS;

DROP TABLE IF EXISTS FLAKEBENCH.TEST_RESULTS.LOCK_CONTENTION_EVENTS;
DROP TABLE IF EXISTS FLAKEBENCH.TEST_RESULTS.HYBRID_TABLE_CREDITS;
DROP VIEW IF EXISTS FLAKEBENCH.TEST_RESULTS.V_LOCK_CONTENTION_SUMMARY;
```

### Phase 4 Rollback
```sql
-- v0.2: Backup before rollback
CREATE TABLE IF NOT EXISTS FLAKEBENCH.TEST_RESULTS.QUERY_INSIGHTS_CACHE_ROLLBACK AS 
    SELECT * FROM FLAKEBENCH.TEST_RESULTS.QUERY_INSIGHTS_CACHE;

DROP TABLE IF EXISTS FLAKEBENCH.TEST_RESULTS.QUERY_INSIGHTS_CACHE;
```

---

## Monitoring

### Key Metrics to Track

1. **Queue health**
   ```sql
   SELECT 
       STATUS,
       COUNT(*) AS job_count,
       AVG(ATTEMPTS) AS avg_attempts,
       MAX(ATTEMPTS) AS max_attempts
   FROM DELAYED_ENRICHMENT_QUEUE
   WHERE CREATED_AT > DATEADD('day', -1, CURRENT_TIMESTAMP())
   GROUP BY STATUS;
   ```

2. **Enrichment latency**
   ```sql
   SELECT 
       DATEDIFF('minute', TEST_END_TIME, COMPLETED_AT) AS enrichment_minutes,
       COUNT(*) AS count
   FROM DELAYED_ENRICHMENT_QUEUE
   WHERE STATUS = 'COMPLETED'
     AND COMPLETED_AT > DATEADD('day', -7, CURRENT_TIMESTAMP())
   GROUP BY enrichment_minutes
   ORDER BY enrichment_minutes;
   ```

3. **Error rate**
   ```sql
   SELECT 
       DATE_TRUNC('day', CREATED_AT) AS day,
       COUNT(*) AS total,
       SUM(IFF(STATUS = 'FAILED', 1, 0)) AS failed,
       SUM(IFF(STATUS = 'FAILED', 1, 0))::FLOAT / COUNT(*) * 100 AS fail_pct
   FROM DELAYED_ENRICHMENT_QUEUE
   GROUP BY day
   ORDER BY day DESC
   LIMIT 7;
   ```

---

## Alerting Thresholds (v0.2)

Define monitoring SLOs for the delayed enrichment system:

| Metric | Warning | Critical | Check Interval |
|--------|---------|----------|----------------|
| Queue depth (PENDING jobs) | > 50 | > 200 | 5 min |
| Job failure rate (24h rolling) | > 5% | > 15% | 15 min |
| Max job age (oldest PENDING) | > 6 hours | > 12 hours | 5 min |
| Enrichment latency (completion - eligible time) | > 30 min | > 60 min | 15 min |
| Stale IN_PROGRESS jobs (no update > 30 min) | > 1 | > 5 | 5 min |

### Alert SQL Examples

```sql
-- Queue depth check
SELECT COUNT(*) AS pending_count
FROM DELAYED_ENRICHMENT_QUEUE
WHERE STATUS = 'PENDING';

-- Stale IN_PROGRESS jobs (potential orphans)
SELECT COUNT(*) AS stale_count
FROM DELAYED_ENRICHMENT_QUEUE
WHERE STATUS = 'IN_PROGRESS'
  AND UPDATED_AT < DATEADD('minute', -30, CURRENT_TIMESTAMP());

-- 24h failure rate
SELECT 
    SUM(IFF(STATUS = 'FAILED', 1, 0))::FLOAT / NULLIF(COUNT(*), 0) * 100 AS fail_pct
FROM DELAYED_ENRICHMENT_QUEUE
WHERE CREATED_AT > DATEADD('hour', -24, CURRENT_TIMESTAMP());
```

---

## Deployment Sequence (v0.2)

Each phase follows this deployment order:

1. **Schema migrations** — Run DDL statements (CREATE TABLE, ALTER TABLE, CREATE VIEW)
2. **Backend deployment** — Deploy new Python code with feature flag disabled
3. **Permission verification** — Run D9 startup probe to confirm ACCOUNT_USAGE access
4. **Enable feature** — Enable delayed enrichment processing via config flag
5. **Smoke test** — Run a single test and verify queue entry created
6. **Monitor** — Watch alerting thresholds for 24 hours
7. **Full rollout** — Remove feature flag, enable for all tests

### Rollback trigger criteria
- Failure rate exceeds 15% within first 24 hours
- Queue depth exceeds 200 (backlog growing)
- Any data corruption detected in enriched results

---

## Future Considerations

### Backfill Existing Tests
After Phase 4 is stable, consider backfilling existing completed tests:
1. Query TEST_RESULTS for tests without DELAYED_ENRICHMENT_STATUS
2. Create jobs with `test_end_time` from historical END_TIME
3. Process with lower priority than real-time jobs

### Performance Optimization
If queue grows large:
- Add index on (STATUS, EARLIEST_ENRICHMENT_TIME)
- Increase processor parallelism
- Consider Snowflake Task for scheduling

### Cross-Account Support
For multi-account deployments:
- Add ACCOUNT_ID to queue and metrics tables
- Support different ACCOUNT_USAGE view access per account

---

**End of Implementation Phases**
