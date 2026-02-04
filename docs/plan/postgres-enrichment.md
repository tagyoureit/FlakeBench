# PostgreSQL Statistics Enrichment Plan

Aggregate-level test enrichment using `pg_stat_statements` and related statistics views.

**Status**: ⬜ Not Started  
**Priority**: Medium  
**Complexity**: Medium-High  

## Executive Summary

Currently, Postgres tests skip enrichment entirely because `pg_stat_statements` provides aggregate statistics per query pattern rather than per-execution history like Snowflake's `QUERY_HISTORY`. However, we can capture **test-level deltas** by taking snapshots before and after test execution.

This gives us valuable insights that are **different but complementary** to Snowflake enrichment:
- Buffer cache efficiency (we can't get from Snowflake)
- I/O timing breakdown (if `track_io_timing` enabled)
- Planning time analysis
- Temp file usage patterns
- WAL generation metrics

## Current State Analysis

### Snowflake Enrichment (Working)

**Location**: `backend/core/results_store.py:1390-1540`

**Flow**:
1. Test completes → `ENRICHMENT_STATUS = 'PENDING'`
2. `_run_enrichment()` triggered as background task
3. Queries `INFORMATION_SCHEMA.QUERY_HISTORY` by `QUERY_TAG` and time window
4. MERGE updates `QUERY_EXECUTIONS` rows with `SF_*` fields
5. Compute `APP_OVERHEAD_MS = APP_ELAPSED_MS - SF_TOTAL_ELAPSED_MS`
6. Update overhead percentiles on `TEST_RESULTS`

**Metrics Captured**:
| Field | Source |
|-------|--------|
| `SF_TOTAL_ELAPSED_MS` | `TOTAL_ELAPSED_TIME` |
| `SF_EXECUTION_MS` | `EXECUTION_TIME` |
| `SF_COMPILATION_MS` | `COMPILATION_TIME` |
| `SF_QUEUED_OVERLOAD_MS` | `QUEUED_OVERLOAD_TIME` |
| `SF_QUEUED_PROVISIONING_MS` | `QUEUED_PROVISIONING_TIME` |
| `SF_TX_BLOCKED_MS` | `TRANSACTION_BLOCKED_TIME` |
| `SF_BYTES_SCANNED` | `BYTES_SCANNED` |
| `SF_ROWS_PRODUCED` | `ROWS_PRODUCED` |
| `SF_CLUSTER_NUMBER` | `CLUSTER_NUMBER` |

### Postgres Enrichment (Currently Skipped)

**Location**: `backend/core/orchestrator.py:1421-1431`

```python
if is_postgres_test:
    logger.info(
        "Skipping QUERY_HISTORY enrichment for Postgres test %s "
        "(pg_stat_statements provides aggregate stats only)",
        test_id,
    )
    await update_enrichment_status(
        test_id=test_id,
        status="SKIPPED",
        error="Postgres: no per-query history available",
    )
```

**Reason**: Correct decision - `pg_stat_statements` aggregates by normalized query pattern, not individual executions.

### Snowflake Postgres Verification (2025-02-04)

**Tested against**: `*.postgres.snowflake.app` (Snowflake-hosted Postgres)

| Feature | Status | Notes |
|---------|--------|-------|
| pg_stat_statements available | ✅ Yes | Already in `shared_preload_libraries` |
| Extension pre-installed | ✅ Yes | No `CREATE EXTENSION` needed |
| `track_io_timing` | ✅ ON | I/O timing available |
| `track_planning` | ❌ OFF | No planning time breakdown (acceptable) |

**Conclusion**: Full enrichment is possible on Snowflake Postgres out of the box.

### Why We Can Still Enrich

Key insight: **We control the test execution window**. By capturing snapshots at multiple points:
- **Snapshot 1**: Before warmup starts
- **Snapshot 2**: After warmup completes (before measurement)
- **Snapshot 3**: After measurement completes

This gives us:
- **Warmup delta** = Snapshot 2 - Snapshot 1 (warmup phase only)
- **Measurement delta** = Snapshot 3 - Snapshot 2 (measurement phase only)
- **Total delta** = Snapshot 3 - Snapshot 1 (entire test)

This matches the app's existing pattern of tracking warmup vs measurement phases separately.

## Available PostgreSQL Statistics

### Primary: pg_stat_statements (Recommended)

**Requirements**:
- Extension must be enabled: `CREATE EXTENSION pg_stat_statements`
- `shared_preload_libraries` must include `pg_stat_statements`
- `compute_query_id = on` or `auto`

**Available Fields** (PostgreSQL 14+):

| Field | Type | Description | Enrichment Value |
|-------|------|-------------|------------------|
| `queryid` | bigint | Hash of normalized query | Matching key |
| `query` | text | Representative query text | Verification |
| `calls` | bigint | Execution count | **HIGH** |
| `total_exec_time` | double | Total execution time (ms) | **HIGH** |
| `mean_exec_time` | double | Average execution time (ms) | **HIGH** |
| `min_exec_time` | double | Minimum execution time (ms) | **HIGH** |
| `max_exec_time` | double | Maximum execution time (ms) | **HIGH** |
| `stddev_exec_time` | double | Std deviation of exec time | **HIGH** |
| `rows` | bigint | Total rows returned/affected | **HIGH** |
| `shared_blks_hit` | bigint | Buffer cache hits | **HIGH** |
| `shared_blks_read` | bigint | Blocks read from disk | **HIGH** |
| `shared_blks_dirtied` | bigint | Blocks dirtied | MEDIUM |
| `shared_blks_written` | bigint | Blocks written | MEDIUM |
| `local_blks_hit` | bigint | Local cache hits | LOW |
| `local_blks_read` | bigint | Local blocks read | LOW |
| `temp_blks_read` | bigint | Temp blocks read | **HIGH** |
| `temp_blks_written` | bigint | Temp blocks written | **HIGH** |
| `shared_blk_read_time` | double | I/O read time (ms)* | **HIGH** |
| `shared_blk_write_time` | double | I/O write time (ms)* | **HIGH** |
| `wal_records` | bigint | WAL records generated | MEDIUM |
| `wal_bytes` | numeric | WAL bytes generated | MEDIUM |
| `total_plan_time` | double | Planning time (ms)** | **HIGH** |
| `mean_plan_time` | double | Avg planning time (ms)** | **HIGH** |

*Requires `track_io_timing = on`  
**Requires `pg_stat_statements.track_planning = on`

### Secondary: pg_stat_user_tables (Deferred to Phase 2+)

> **Note**: These stats add complexity and require table-specific tracking.
> `pg_stat_statements` already provides the most valuable metrics.
> Defer implementation until there's a demonstrated need.

**Available Fields**:

| Field | Description | Enrichment Value |
|-------|-------------|------------------|
| `seq_scan` | Sequential scans initiated | MEDIUM |
| `seq_tup_read` | Rows fetched by seq scans | MEDIUM |
| `idx_scan` | Index scans initiated | MEDIUM |
| `idx_tup_fetch` | Rows fetched by idx scans | MEDIUM |
| `n_tup_ins` | Rows inserted | **HIGH** |
| `n_tup_upd` | Rows updated | **HIGH** |
| `n_tup_del` | Rows deleted | **HIGH** |
| `n_tup_hot_upd` | HOT updates | MEDIUM |
| `n_dead_tup` | Dead tuples | LOW |
| `vacuum_count` | Vacuum operations | LOW |

### Secondary: pg_stat_user_indexes (Deferred to Phase 2+)

> **Note**: Deferred - index-level stats are useful for tuning but not critical for initial enrichment.

| Field | Description | Enrichment Value |
|-------|-------------|------------------|
| `idx_scan` | Index scans initiated | MEDIUM |
| `idx_tup_read` | Index entries read | MEDIUM |
| `idx_tup_fetch` | Live rows fetched | MEDIUM |

### System-Level: pg_stat_bgwriter

| Field | Description | Enrichment Value |
|-------|-------------|------------------|
| `buffers_clean` | Buffers written by bgwriter | LOW |
| `buffers_backend` | Buffers written by backends | MEDIUM |
| `buffers_backend_fsync` | Backend fsync calls | LOW |

## Comparison: Snowflake vs Postgres Enrichment

| Metric Category | Snowflake (QUERY_HISTORY) | Postgres (pg_stat_statements delta) |
|-----------------|---------------------------|-------------------------------------|
| **Granularity** | Per-query execution | Per-query-pattern aggregate |
| **Execution Time** | ✅ Per execution | ✅ Mean/min/max/stddev across test |
| **Planning/Compilation** | ✅ Per execution | ✅ If track_planning enabled |
| **Queuing Time** | ✅ Per execution | ❌ Not available |
| **Rows Processed** | ✅ Per execution | ✅ Total across test |
| **Buffer Cache Hits** | ❌ Not exposed | ✅ **Unique insight** |
| **Disk I/O Time** | ❌ Not exposed | ✅ **If track_io_timing** |
| **Temp File Usage** | ❌ Not exposed | ✅ **Unique insight** |
| **WAL Generation** | ❌ Not exposed | ✅ **Unique insight** |
| **Cluster/Node Info** | ✅ CLUSTER_NUMBER | ❌ Not applicable |

**Key Insight**: Postgres gives us **different** metrics than Snowflake, not fewer. Buffer cache efficiency and I/O timing are valuable insights we can't get from Snowflake.

## Design Decisions

### Decision 1: Storage Location

**Options**:

| Option | Pros | Cons |
|--------|------|------|
| A. New columns on `TEST_RESULTS` | Simple, co-located with test data | Table gets wider |
| B. New `TEST_PG_ENRICHMENT` table | Clean separation, schema flexibility | Extra JOIN for queries |
| C. VARIANT column (`PG_STATS`) | Schema flexibility, easy to extend | Harder to query/aggregate |

**Recommendation**: **Option A** (new columns on TEST_RESULTS) for frequently-queried metrics, with Option C (VARIANT) for extended stats.

**Rationale**: 
- Most valuable metrics (cache hit ratio, I/O time) should be easily queryable
- VARIANT can hold raw snapshots and secondary stats for debugging

### Decision 2: Query Pattern Matching

**Challenge**: Map `pg_stat_statements` queryid to our queries

**Options**:

| Option | Pros | Cons |
|--------|------|------|
| A. Match by query text pattern | Simple | Fragile, parameter variations |
| B. Store queryid during execution | Accurate | Requires capturing `pg_stat_statements` queryid per-query |
| C. Match by UB_KIND comment marker | Works with our existing markers | May not have pg_stat_statements queryid |
| D. Capture ALL queries, filter by time | Comprehensive | May include non-test queries |

**Recommendation**: **Option D** with time window filtering + **Option C** as secondary filter.

**Implementation**:
1. Capture full `pg_stat_statements` snapshot before test
2. Capture full snapshot after test
3. Compute delta for ALL queryids
4. Filter to queries containing `UB_KIND=` in query text
5. Aggregate by query kind (POINT_LOOKUP, RANGE_SCAN, etc.)

### Decision 3: What If pg_stat_statements Not Enabled?

**Detection**:
```sql
SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements';
```

**Behavior**:
- If not enabled: Set `ENRICHMENT_STATUS = 'SKIPPED'` with error "pg_stat_statements extension not available"
- If enabled but `track_io_timing = off`: Capture available stats, note I/O timing unavailable
- If enabled but `track_planning = off`: Capture available stats, note planning stats unavailable

### Decision 5: User Notification for Missing pg_stat_statements

**Context**: This app will test against many different Postgres instances. Some may not have 
`pg_stat_statements` available or enabled. Users should be informed proactively so they can
enable it if desired.

**Detection Point**: At test template loading / database selection time (before test starts).

**User Flow**:
1. User selects a Postgres database in template configuration
2. Backend checks for `pg_stat_statements` availability on that connection
3. If unavailable, return capability info in API response
4. Frontend displays toast notification:

```
⚠️ Server-side statistics unavailable

The Postgres instance does not have pg_stat_statements enabled.
Enrichment metrics (cache hit ratio, I/O timing) will not be available.

To enable: CREATE EXTENSION pg_stat_statements;
(Requires shared_preload_libraries configuration)

[Learn More] [Dismiss]
```

**API Response Structure**:
```json
{
  "database": "mydb",
  "connection_valid": true,
  "capabilities": {
    "pg_stat_statements": false,
    "track_io_timing": null,
    "track_planning": null
  },
  "capability_warnings": [
    {
      "type": "missing_extension",
      "extension": "pg_stat_statements",
      "impact": "Server-side statistics unavailable for enrichment",
      "remediation": "CREATE EXTENSION pg_stat_statements; (requires server restart with shared_preload_libraries)"
    }
  ]
}
```

**Toast Severity Levels**:
- **Warning (yellow)**: `pg_stat_statements` not available - enrichment will be skipped
- **Info (blue)**: `track_io_timing = off` - I/O timing unavailable but other stats work
- **Info (blue)**: `track_planning = off` - planning stats unavailable but other stats work

**Implementation Location**:
- Backend: `backend/api/routes/catalog.py` - add capability check endpoint
- Frontend: `backend/static/js/dashboard.js` - display toast on template load
- Reuse existing toast infrastructure if available, else add simple toast component

### Decision 4: Snapshot Storage for Debugging

Store raw before/after snapshots in VARIANT column for:
- Debugging enrichment issues
- Ad-hoc analysis
- Future metric extraction

## Proposed Schema Changes

### Option A: TEST_RESULTS Columns

Add to `sql/schema/results_tables.sql`:

```sql
-- =============================================================================
-- PostgreSQL Enrichment Fields (TEST_RESULTS)
-- =============================================================================
-- Add columns to TEST_RESULTS for Postgres aggregate stats

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS 
    pg_enrichment_status VARCHAR(20);  -- 'SUCCESS', 'SKIPPED', 'FAILED', 'PARTIAL'

-- Execution statistics (aggregated across all query patterns)
ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_total_exec_time_ms FLOAT;       -- Sum of mean_exec_time * calls for all patterns

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_mean_exec_time_ms FLOAT;        -- Weighted average execution time

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_total_plan_time_ms FLOAT;       -- Sum of planning time (if tracking enabled)

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_total_calls BIGINT;             -- Total query executions

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_total_rows BIGINT;              -- Total rows processed

-- Buffer cache efficiency
ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_shared_blks_hit BIGINT;         -- Buffer cache hits

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_shared_blks_read BIGINT;        -- Disk reads required

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_cache_hit_ratio FLOAT;          -- hit / (hit + read), 0-1

-- I/O timing (requires track_io_timing = on)
ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_blk_read_time_ms FLOAT;         -- Time spent reading from disk

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_blk_write_time_ms FLOAT;        -- Time spent writing

-- Temp file usage (indicates query memory pressure)
ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_temp_blks_read BIGINT;

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_temp_blks_written BIGINT;

-- WAL generation (write workload indicator)
ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_wal_records BIGINT;

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_wal_bytes BIGINT;

-- Raw enrichment data (for debugging and extended analysis)
ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_stats_before VARIANT;           -- Snapshot before test

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_stats_after VARIANT;            -- Snapshot after test

ALTER TABLE TEST_RESULTS ADD COLUMN IF NOT EXISTS
    pg_stats_delta VARIANT;            -- Computed delta by queryid
```

### Per-Query-Kind Breakdown (Optional)

For more granular analysis, store breakdown by query kind in VARIANT:

```sql
-- Example pg_stats_delta structure:
{
    "snapshot_time": {
        "before": "2024-01-15T10:00:00Z",
        "after": "2024-01-15T10:05:00Z"
    },
    "by_query_kind": {
        "POINT_LOOKUP": {
            "calls": 50000,
            "total_exec_time_ms": 2500.5,
            "mean_exec_time_ms": 0.05,
            "rows": 50000,
            "shared_blks_hit": 150000,
            "shared_blks_read": 500,
            "cache_hit_ratio": 0.9967
        },
        "RANGE_SCAN": {
            "calls": 10000,
            "total_exec_time_ms": 5000.2,
            "mean_exec_time_ms": 0.5,
            "rows": 1000000,
            "shared_blks_hit": 80000,
            "shared_blks_read": 20000,
            "cache_hit_ratio": 0.80
        },
        "INSERT": {...},
        "UPDATE": {...}
    },
    "totals": {
        "calls": 65000,
        "total_exec_time_ms": 8500.7,
        ...
    },
    "pg_settings": {
        "track_io_timing": true,
        "track_planning": false,
        "shared_buffers": "4GB"
    }
}
```

## Implementation Tasks

### Phase 1: Infrastructure (Backend)

#### Task 1.1: Create Postgres Stats Helper Module

**File**: `backend/core/postgres_stats.py` (new file)

```python
"""PostgreSQL statistics collection for test enrichment."""

from dataclasses import dataclass
from typing import Any

import asyncpg


@dataclass
class PgStatSnapshot:
    """Snapshot of pg_stat_statements at a point in time."""
    timestamp: datetime
    stats: dict[int, dict[str, Any]]  # queryid -> stats
    settings: dict[str, Any]  # pg settings affecting stats


async def check_pg_stat_statements_available(conn: asyncpg.Connection) -> bool:
    """Check if pg_stat_statements extension is installed."""
    ...


async def get_pg_settings(conn: asyncpg.Connection) -> dict[str, Any]:
    """Get relevant pg settings (track_io_timing, track_planning, etc.)."""
    ...


async def capture_pg_stat_snapshot(
    conn: asyncpg.Connection,
    query_filter: str | None = None,  # e.g., '%UB_KIND=%'
) -> PgStatSnapshot:
    """Capture current pg_stat_statements state."""
    ...


def compute_snapshot_delta(
    before: PgStatSnapshot,
    after: PgStatSnapshot,
) -> dict[str, Any]:
    """Compute delta between two snapshots."""
    ...


def extract_query_kind(query_text: str) -> str | None:
    """Extract UB_KIND from query text comment."""
    ...


def aggregate_by_query_kind(
    delta: dict[int, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Aggregate delta stats by query kind."""
    ...
```

#### Task 1.2: Integrate Snapshot Capture in Orchestrator

**File**: `backend/core/orchestrator.py` (preferred over test_executor for coordination)

> **Note**: Capture snapshots in orchestrator rather than test_executor to simplify 
> multi-worker coordination. Orchestrator has clear phase boundaries.

**Three-Point Snapshot Timing**:

```python
# 1. Before warmup starts
if is_postgres_test and pg_stat_statements_available:
    pg_snapshot_before_warmup = await capture_pg_stat_snapshot(pg_conn)

# 2. After warmup completes, before measurement starts
if is_postgres_test and pg_stat_statements_available:
    pg_snapshot_after_warmup = await capture_pg_stat_snapshot(pg_conn)

# 3. After measurement completes
if is_postgres_test and pg_stat_statements_available:
    pg_snapshot_after_measurement = await capture_pg_stat_snapshot(pg_conn)
```

**Delta Computation**:
```python
# Compute all three deltas for flexibility
warmup_delta = compute_snapshot_delta(pg_snapshot_before_warmup, pg_snapshot_after_warmup)
measurement_delta = compute_snapshot_delta(pg_snapshot_after_warmup, pg_snapshot_after_measurement)
total_delta = compute_snapshot_delta(pg_snapshot_before_warmup, pg_snapshot_after_measurement)
```

**Storage**: Store all snapshots and deltas in VARIANT columns for maximum flexibility.
UI can display whichever view the user selects (warmup-only, measurement-only, or total).

#### Task 1.3: Implement Postgres Enrichment in Orchestrator

**File**: `backend/core/orchestrator.py`

Replace current skip logic with:

```python
if is_postgres_test:
    logger.info("Starting Postgres enrichment for test %s", test_id)
    try:
        await enrich_postgres_test(test_id)
    except Exception as e:
        logger.exception("Postgres enrichment failed for %s: %s", test_id, e)
        await update_enrichment_status(
            test_id=test_id,
            status="FAILED",
            error=f"Postgres enrichment error: {e}",
        )
```

#### Task 1.4: Create Enrichment Function

**File**: `backend/core/results_store.py` (or new `postgres_enrichment.py`)

```python
async def enrich_postgres_test(
    *,
    test_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Enrich Postgres test with aggregate statistics.
    
    Returns enrichment summary including cache hit ratio, I/O times, etc.
    """
    # 1. Retrieve before/after snapshots from test execution
    # 2. Compute delta
    # 3. Aggregate by query kind
    # 4. Update TEST_RESULTS with pg_* columns
    # 5. Store raw data in VARIANT columns
    # 6. Update ENRICHMENT_STATUS
    ...
```

### Phase 2: Schema & Migration

#### Task 2.1: Create Schema Migration

**File**: `sql/migrations/add_postgres_enrichment.sql`

Add all `pg_*` columns to `TEST_RESULTS` table.

#### Task 2.2: Update Results Store

Add helper functions to persist Postgres enrichment data.

### Phase 3: API & Frontend

#### Task 3.0: Add Postgres Capability Check API (NEW)

**File**: `backend/api/routes/catalog.py`

Add endpoint to check pg_stat_statements availability when user selects a Postgres database:

```python
@router.get("/postgres/capabilities")
async def get_postgres_capabilities(
    database: str,
    pool_type: str = "snowflake_postgres"
) -> dict:
    """
    Check pg_stat_statements and related capabilities for a Postgres database.
    Called when user selects a database in template configuration.
    """
    # Returns: { capabilities: {...}, capability_warnings: [...] }
```

**Frontend Integration** (`backend/static/js/dashboard.js`):
- Call capability check when Postgres database is selected
- Display toast notification if pg_stat_statements unavailable
- Show info toast if track_io_timing or track_planning is off

#### Task 3.1: Update Test Results API

**File**: `backend/api/routes/test_results.py`

Add `pg_*` fields to API response for Postgres tests.

#### Task 3.2: Update Dashboard

**File**: `backend/templates/pages/dashboard_history.html`

Display Postgres-specific metrics:
- Buffer Cache Hit Ratio (with visual indicator)
- I/O Time breakdown
- Temp file usage (warning if high)

#### Task 3.3: Update Comparison View

**File**: `backend/templates/pages/history_compare.html`

Show Postgres vs Snowflake comparison with appropriate metrics for each.

### Phase 4: Testing & Documentation

#### Task 4.1: Unit Tests

- Test snapshot capture/delta computation
- Test query kind extraction
- Test enrichment flow

#### Task 4.2: Integration Tests

- End-to-end test with actual Postgres instance
- Verify enrichment completes successfully

#### Task 4.3: Documentation

- Update `docs/data-flow-and-lifecycle.md`
- Add `docs/postgres-enrichment.md` user guide

## Open Questions / Unknowns

### Unknown 1: pg_stat_statements Availability

**Question**: Is `pg_stat_statements` enabled on Snowflake Postgres by default?

**Investigation Required**:
```sql
-- Check if extension is available
SELECT * FROM pg_available_extensions WHERE name = 'pg_stat_statements';

-- Check if extension is installed
SELECT * FROM pg_extension WHERE extname = 'pg_stat_statements';

-- Check settings
SHOW shared_preload_libraries;
SHOW compute_query_id;
```

**Impact**: If not available by default, we need:
- Documentation for users to enable it
- Graceful degradation when unavailable

### Unknown 2: track_io_timing Setting

**Question**: Is `track_io_timing` enabled by default on Snowflake Postgres?

**Impact**: 
- If OFF: `blk_read_time` and `blk_write_time` will be 0
- We should detect this and note in enrichment status

### Unknown 3: pg_stat_statements Reset Behavior

**Question**: Does Snowflake Postgres auto-reset `pg_stat_statements` or is it persistent?

**Impact**:
- If reset on restart: Before snapshot must happen close to test start
- If persistent: Need to handle pre-existing query patterns

**Mitigation**: Always compute deltas, never use absolute values.

### Unknown 4: Query ID Stability

**Question**: Does the `queryid` hash remain stable across connections/sessions?

**Expected**: Yes, `queryid` is computed from normalized query text and should be stable.

**Verification**: Test by running same query from different connections.

### Unknown 5: Multi-Worker Postgres Tests

**Question**: How do we handle multi-worker Postgres tests?

**Considerations**:
- All workers hit same Postgres instance
- `pg_stat_statements` captures ALL queries (not per-connection)
- Before/after snapshot approach still works (captures aggregate)

**Implementation Note**: Snapshot capture should happen from orchestrator, not workers.

### Unknown 6: Connection Pooling Effects

**Question**: Does PgBouncer or other pooling affect `pg_stat_statements`?

**Expected**: No - `pg_stat_statements` is server-side, tracks all queries regardless of client pooling.

### Unknown 7: Statement Sampling Under High Load

**Question**: Does `pg_stat_statements` sample or capture all queries?

**Answer**: Captures all queries up to `pg_stat_statements.max` distinct query patterns (default 5000). Oldest entries are evicted when limit reached.

**Mitigation**: 
- Check `pg_stat_statements_info.dealloc` for eviction count
- If high eviction rate, stats may be incomplete

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| pg_stat_statements not available | Medium | HIGH | Graceful skip with clear error message |
| track_io_timing disabled | High | MEDIUM | Note in enrichment status, still capture other metrics |
| Query pattern eviction | Low | MEDIUM | Monitor dealloc count, warn if high |
| Performance impact of snapshot capture | Low | LOW | Query is lightweight |
| Matching queries to test | Low | MEDIUM | Use time window + UB_KIND marker |

## Success Criteria

### Minimum Viable

- [ ] Capture before/after `pg_stat_statements` snapshots
- [ ] Compute delta for test duration
- [ ] Store aggregate metrics in `TEST_RESULTS`
- [ ] Display cache hit ratio in dashboard
- [ ] Graceful handling when `pg_stat_statements` unavailable

### Full Implementation

- [ ] All metrics from design captured
- [ ] Per-query-kind breakdown in VARIANT
- [ ] Side-by-side comparison view with Snowflake tests
- [ ] I/O timing breakdown (when available)
- [ ] Temp file usage warnings
- [ ] WAL generation tracking for write workloads

## File Reference

| File | Purpose |
|------|---------|
| `backend/core/postgres_stats.py` | New - Stats collection helpers |
| `backend/core/results_store.py` | Enrichment functions |
| `backend/core/orchestrator.py:1421-1431` | Current skip logic to replace |
| `backend/core/test_executor.py:1078` | Snapshot capture injection point |
| `sql/schema/results_tables.sql` | Schema additions |
| `backend/api/routes/test_results.py` | API response updates |
| `backend/templates/pages/dashboard_history.html` | Dashboard display |
| `docs/data-flow-and-lifecycle.md` | Documentation update |

## Appendix A: pg_stat_statements Query

```sql
-- Query to capture snapshot (PostgreSQL 14+)
SELECT
    queryid,
    query,
    calls,
    total_exec_time,
    mean_exec_time,
    min_exec_time,
    max_exec_time,
    stddev_exec_time,
    rows,
    shared_blks_hit,
    shared_blks_read,
    shared_blks_dirtied,
    shared_blks_written,
    local_blks_hit,
    local_blks_read,
    temp_blks_read,
    temp_blks_written,
    shared_blk_read_time,
    shared_blk_write_time,
    wal_records,
    wal_bytes,
    total_plan_time,
    mean_plan_time
FROM pg_stat_statements
WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
  AND query LIKE '%UB_KIND=%'
ORDER BY queryid;
```

## Appendix B: Detecting pg_stat_statements Capabilities

```sql
-- Check available capabilities
SELECT
    -- Extension available
    EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS extension_installed,
    
    -- I/O timing available
    (SELECT setting::boolean FROM pg_settings WHERE name = 'track_io_timing') AS track_io_timing,
    
    -- Planning tracking available
    (SELECT setting::boolean FROM pg_settings WHERE name = 'pg_stat_statements.track_planning') AS track_planning,
    
    -- Current stats count
    (SELECT count(*) FROM pg_stat_statements) AS current_statements,
    
    -- Max statements allowed
    (SELECT setting::int FROM pg_settings WHERE name = 'pg_stat_statements.max') AS max_statements,
    
    -- Deallocation count (statements evicted due to max limit)
    (SELECT dealloc FROM pg_stat_statements_info) AS dealloc_count;
```

## Appendix C: Cache Hit Ratio Calculation

```python
def calculate_cache_hit_ratio(hits: int, reads: int) -> float:
    """
    Calculate buffer cache hit ratio.
    
    Returns value between 0.0 (all reads from disk) and 1.0 (all from cache).
    A healthy system should have > 0.99 for read-heavy workloads.
    """
    total = hits + reads
    if total == 0:
        return 1.0  # No I/O = perfect hit ratio
    return hits / total
```
