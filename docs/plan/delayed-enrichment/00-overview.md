# Delayed ACCOUNT_USAGE Enrichment - Overview

**Document Version:** 0.2 (Post-Review)  
**Created:** 2026-02-17  
**Last Updated:** 2026-02-17  
**Status:** Planning  
**Review Status:** Pass 1 complete (4 personas: Coder, Data Architect, UI Designer, DevOps). All critical issues addressed.

---

## Document Index

| File | Description |
|------|-------------|
| [00-overview.md](00-overview.md) | Executive summary, problem statement, gap analysis, decisions |
| [01-data-architecture.md](01-data-architecture.md) | Schema changes, new tables, data flow diagrams |
| [02-backend-implementation.md](02-backend-implementation.md) | Code changes, enrichment functions, scheduling strategy |
| [03-frontend-design.md](03-frontend-design.md) | UI changes, status indicators, progressive disclosure |
| [04-implementation-phases.md](04-implementation-phases.md) | Phased rollout with acceptance criteria |

---

## 1. Executive Summary

### Goal
Add delayed enrichment from Snowflake ACCOUNT_USAGE views to capture metrics unavailable in real-time INFORMATION_SCHEMA, specifically addressing the critical gap where **hybrid table queries are missing from QUERY_HISTORY**.

### Key Insight
The Unistore Field Implementation Guide states: *"AGGREGATE_QUERY_HISTORY is the primary view for analyzing hybrid table performance. QUERY_HISTORY will not contain all repetitive hybrid table queries."*

Currently, hybrid table tests show ~0.1% enrichment ratio because fast queries (~under 500ms) are SKIPPED from QUERY_HISTORY entirely. This makes Snowflake-side metrics (execution time, compilation time, partition stats) nearly useless for hybrid tables.

### Two-Pass Enrichment Model
```
Test Completes
     │
     ▼
┌─────────────────────────────────────┐
│  PASS 1: Immediate Enrichment       │  ← Current behavior
│  Source: INFORMATION_SCHEMA         │
│  Latency: ~45 seconds               │
│  Columns: sf_execution_ms, etc.     │
│  Coverage: ~90% for standard tables │
│            ~0.1% for hybrid tables  │
└─────────────────────────────────────┘
     │
     ▼ (3 hours later)
┌─────────────────────────────────────┐
│  PASS 2: Delayed Enrichment         │  ← NEW
│  Sources:                           │
│    - ACCOUNT_USAGE.QUERY_HISTORY    │
│    - AGGREGATE_QUERY_HISTORY        │
│    - LOCK_WAIT_HISTORY              │
│    - HYBRID_TABLE_USAGE_HISTORY     │
│    - QUERY_INSIGHTS                 │
│  Coverage: 100% (aggregated)        │
└─────────────────────────────────────┘
```

---

## 2. Problem Statement

### Current State
- Enrichment uses `INFORMATION_SCHEMA.QUERY_HISTORY()` (real-time, 7-day retention)
- Works well for standard/interactive tables (~90% enrichment)
- **Fails for hybrid tables** (~0.1% enrichment) because fast queries are skipped
- Several schema columns exist but are NEVER populated (partitions_scanned, bytes_spilled)
- No visibility into row-level lock contention on hybrid tables
- No tracking of hybrid table serverless credits
- No automated query optimization insights

### Desired State
- Full server-side metrics for ALL table types including hybrid
- Partition/spill statistics populated via ACCOUNT_USAGE.QUERY_HISTORY
- Aggregated percentiles (p50, p90, p95, p99, max) from AGGREGATE_QUERY_HISTORY
- Lock contention events captured and visualized
- Hybrid table credit costs tracked per test
- Query insights surfaced to users

---

## 3. Gap Analysis

| Gap | Current Source | Proposed Source | Latency | Impact |
|-----|---------------|-----------------|---------|--------|
| **Missing hybrid table queries** | INFORMATION_SCHEMA.QUERY_HISTORY | AGGREGATE_QUERY_HISTORY | 3 hours | **Critical** - hybrid tests show 0.1% enrichment |
| **Empty partition columns** | N/A | ACCOUNT_USAGE.QUERY_HISTORY | 45 min | Medium - can't analyze partition pruning |
| **Empty spill columns** | N/A | ACCOUNT_USAGE.QUERY_HISTORY | 45 min | Medium - can't detect spill issues |
| **No lock contention** | N/A | LOCK_WAIT_HISTORY | 3 hours | High - invisible row-level contention |
| **No credit tracking** | N/A | HYBRID_TABLE_USAGE_HISTORY | 3 hours | Medium - cost visibility gap |
| **No query insights** | N/A | QUERY_INSIGHTS | 90 min | Low - nice-to-have optimization hints |

### Latency Summary

| View | Latency | Use Case |
|------|---------|----------|
| INFORMATION_SCHEMA.QUERY_HISTORY() | Real-time | Current immediate enrichment |
| ACCOUNT_USAGE.QUERY_HISTORY | 45 minutes | Partition/spill columns |
| AGGREGATE_QUERY_HISTORY | Up to 3 hours | Hybrid table percentiles, throttling |
| LOCK_WAIT_HISTORY | 3 hours | Lock contention analysis |
| HYBRID_TABLE_USAGE_HISTORY | 3 hours | Credit consumption |
| QUERY_INSIGHTS | 90 minutes | Optimization suggestions |

---

## 4. Knowns

### 4.1 Existing Infrastructure

| Component | Location | Status |
|-----------|----------|--------|
| Immediate enrichment | `backend/core/results_store.py:enrich_query_executions_from_query_history()` | Working |
| Retry wrapper | `backend/core/results_store.py:enrich_query_executions_with_retry()` | Working |
| Enrichment status | `TEST_RESULTS.ENRICHMENT_STATUS` column | Working |
| WebSocket streaming | `backend/websocket/streaming.py` | Working |
| Query tag format | `flakebench:run_id={run_id}:test_id={test_id}:phase={phase}` | Working |

### 4.2 AGGREGATE_QUERY_HISTORY Structure

Key columns from AGGREGATE_QUERY_HISTORY:
- `QUERY_PARAMETERIZED_HASH` - Groups queries with same pattern
- `INTERVAL_START_TIME` - 1-minute aggregation buckets
- `QUERY_TAG` - Part of aggregation key (matches our tags)
- `EXECUTION_TIME` - OBJECT with sum, avg, stddev, min, median, p90, p99, p99.9, max
- `COMPILATION_TIME` - Same OBJECT structure
- `TOTAL_ELAPSED_TIME` - Same OBJECT structure
- `HYBRID_TABLE_REQUESTS_THROTTLED_COUNT` - Throttling indicator
- `ERRORS` - ARRAY of {error_code, error_message, count}

### 4.3 QUERY_TAG Matching Strategy

Our query tags follow the pattern: `flakebench:run_id={run_id}:test_id={test_id}:phase=MEASUREMENT`

AGGREGATE_QUERY_HISTORY uses QUERY_TAG as part of the aggregation key, so we can filter by:
```sql
WHERE QUERY_TAG LIKE 'flakebench:run_id=' || ? || '%'
  AND INTERVAL_START_TIME BETWEEN ? AND ?
```

---

## 5. Decisions

### D1: Scheduling Strategy

**Decision:** Background asyncio task with scheduled polling

**Options Considered:**
| Option | Pros | Cons |
|--------|------|------|
| Inline polling (wait 3hrs) | Simple | Blocks user, impractical |
| Snowflake Task | Native scheduling | Adds operational complexity, can't update Python state |
| Background asyncio task | Integrates with existing code, can use WebSocket | Requires process persistence |
| On-demand (user clicks) | Simple | User must remember to check back |

**Rationale:** Background task fits existing architecture (already have poll loops in orchestrator). Can check multiple tests in one pass, emit WebSocket updates.

### D2: Enrichment Pass Model

**Decision:** Keep immediate enrichment, ADD delayed pass

The existing immediate enrichment is valuable for standard tables and provides fast feedback. We add a second pass for delayed views without changing Pass 1.

### D3: Hybrid Table Metrics Storage

**Decision:** Store aggregated stats per-test, not per-query

AGGREGATE_QUERY_HISTORY provides aggregated percentiles already. We store these at the test level in a new `AGGREGATE_QUERY_METRICS` table rather than trying to map back to individual QUERY_EXECUTIONS rows.

### D4: Lock Contention Granularity

**Decision:** Store individual lock events

Lock contention is sparse and diagnostic. Store each event from LOCK_WAIT_HISTORY for timeline visualization.

### D5: Credit Tracking Scope

**Decision:** Store per-test totals from HYBRID_TABLE_USAGE_HISTORY

Sum credits consumed during test time window, store as denormalized columns on TEST_RESULTS.

### D6: Delayed Enrichment Status

**Decision:** Add new status column `DELAYED_ENRICHMENT_STATUS`

Separate from existing `ENRICHMENT_STATUS` to track the delayed pass independently:
- `ENRICHMENT_STATUS`: Immediate enrichment (Pass 1)
- `DELAYED_ENRICHMENT_STATUS`: Delayed enrichment (Pass 2)

Standardized status values across all enrichment columns:
`PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED`, `SKIPPED`, `NOT_APPLICABLE`

### D7: Concurrency Control (Added v0.2)

**Decision:** Atomic job claim via UPDATE...WHERE subquery pattern

Multiple app instances may run the processor. Jobs are claimed atomically:
```sql
UPDATE DELAYED_ENRICHMENT_QUEUE
SET STATUS = 'IN_PROGRESS', CLAIMED_BY = ?, CLAIMED_AT = CURRENT_TIMESTAMP()
WHERE JOB_ID = (
    SELECT JOB_ID FROM DELAYED_ENRICHMENT_QUEUE
    WHERE STATUS = 'PENDING' AND EARLIEST_ENRICHMENT_TIME <= CURRENT_TIMESTAMP()
    ORDER BY EARLIEST_ENRICHMENT_TIME LIMIT 1
)
```

Orphaned jobs (IN_PROGRESS > 30 minutes) are reclaimed on startup.

### D8: Idempotency Strategy (Added v0.2)

**Decision:** DELETE-then-INSERT for all enrichment operations

Before inserting enrichment data for a test, delete any existing rows for that TEST_ID. This makes retries safe and prevents duplicate data accumulation.

### D9: Startup Permission Check (Added v0.2)

**Decision:** Verify ACCOUNT_USAGE access at processor startup

On startup, the processor runs a lightweight probe query:
```sql
SELECT 1 FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY LIMIT 0
```
If this fails, the processor logs a CRITICAL error and disables itself rather than silently failing jobs.

---

## 6. Risks and Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| 3-hour delay frustrates users | Medium | High | Clear UI messaging, unified status indicator |
| Background task fails/crashes | High | Low | Persist pending jobs to DB, resume on restart, orphan recovery |
| ACCOUNT_USAGE access denied | High | Low | Startup permission check (D9), fail-fast with CRITICAL log |
| View latency increases | Medium | Low | Use conservative time buffers, retry logic |
| Data volume for AGGREGATE_QUERY_HISTORY | Low | Medium | Filter tightly by QUERY_TAG and time range |
| Multi-instance race conditions | High | Medium | Atomic job claim pattern (D7) |
| Duplicate data on retry | High | Medium | DELETE-then-INSERT idempotency (D8) |
| Queue table unbounded growth | Medium | High | 30-day cleanup of completed/failed jobs |
| Lock events from unrelated operations | Medium | Medium | Filter by QUERY_ID join to QUERY_EXECUTIONS where possible |

---

## 7. Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Hybrid table enrichment coverage | 100% (aggregated) | AGGREGATE_QUERY_METRICS populated for all hybrid tests |
| Partition/spill columns populated | 100% (standard tables) | Non-null sf_partitions_scanned for standard table queries |
| Delayed enrichment latency | < 3.5 hours from test end | DELAYED_ENRICHMENT_STATUS transition time |
| Lock events captured | 100% of row lock waits | LOCK_CONTENTION_EVENTS vs LOCK_WAIT_HISTORY audit |
| User awareness of delayed data | 100% | UI badge displayed on test detail pages |

---

## 8. Operational Requirements (Added v0.2)

### Credentials
- The Snowflake role used by the application must have `IMPORTED PRIVILEGES ON DATABASE SNOWFLAKE`
- Same credentials as the main application (no separate service account needed)
- Role must be able to query `SNOWFLAKE.ACCOUNT_USAGE.*` views

### Alerting SLOs
- Job completion rate: >95% within 4 hours of test end
- Alert if: >10 jobs in FAILED state in 24 hours
- Alert if: avg(ATTEMPTS) > 2.0 over 24 hours
- Alert if: queue depth > 100 PENDING jobs

### Health Check
- Processor status exposed via existing `/health` endpoint
- Reports: running state, last poll time, total jobs processed, permission status

### Queue Cleanup
- Completed/failed jobs older than 30 days are deleted by the processor
- Cleanup runs once per poll cycle, limited to 1000 rows per pass

---

## 9. Out of Scope (v1)

- Real-time lock contention (not available in Snowflake)
- Cross-account ACCOUNT_USAGE queries
- Historical backfill of existing tests
- Automatic retry of delayed enrichment failures
- QUERY_ACCELERATION_HISTORY integration

---

**Next:** [01-data-architecture.md](01-data-architecture.md) - Schema changes and data flow
