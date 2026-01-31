# Multi-Worker Refactor Bugs (2.21)

**Status**: 🟡 In Progress

Bugs discovered during the single-worker to multi-worker architecture refactor.

## Issues Summary

| Issue | Severity | Status |
|-------|----------|--------|
| 1. QUERY_TAG not updating | HIGH | Fix applied |
| 2. Startup delay | MEDIUM | ✅ Resolved (4s vs 60s) |
| 3. QPS rolling average | MEDIUM | Fix applied |
| 4. WebSocket completion | MEDIUM | ✅ Resolved |

---

## Issue 1: QUERY_TAG Not Updating from WARMUP to RUNNING (HIGH)

### Behavior Observed

- All queries have `QUERY_TAG = :phase=WARMUP` even during MEASUREMENT phase
- `SET_PHASE` event was correctly written but never processed by worker
- Worker's internal `current_phase` DID transition (via RUN_STATUS reconciliation)
- Snowflake session QUERY_TAG was never updated

### Root Cause

Bug in `_wait_for_start()` function at `scripts/run_worker.py:730-736`.

The function processes all events and updates `last_seen_sequence`, but only acts on
`START` events. When `SET_PHASE` arrives during the wait period:

1. `last_seen_sequence` is incremented past the SET_PHASE event
2. Main event loop never sees SET_PHASE because `seq <= last_seen_sequence`
3. `_transition_to_measurement()` is never called
4. `pool.update_query_tag()` is never invoked

### Fix Applied

Only increment `last_seen_sequence` for START events:

```python
for event in events:
    seq = int(event.get("sequence_id") or 0)
    if seq <= last_seen_sequence:
        continue
    if event.get("event_type") == "START":
        last_seen_sequence = seq  # Only update for START
        return True
    # Other events will be processed by main loop
```

### Acceptance Criteria

- [ ] Queries during MEASUREMENT have `:phase=RUNNING` in QUERY_TAG
- [x] SET_PHASE events are not skipped
- [x] Acceptance test: `tests/test_query_tag_phases.py`

---

## Issue 2: Startup Delay (RESOLVED)

### Original Problem

- 60-second delay before first metrics appeared
- 100 connections / 8 parallel = 13 batches × ~4.5s ≈ 58.5 seconds

### Fix Applied

1. Changed `SNOWFLAKE_POOL_MAX_PARALLEL_CREATES` from 8 to 32
2. Added `pool_name` parameter for logging (`[control]`, `[benchmark]`, `[telemetry]`)
3. Orchestrator waits for worker READY heartbeat before setting START_TIME

### Results

- **Before**: ~60 seconds pool initialization
- **After**: ~4 seconds pool initialization

### Remaining Considerations

**Open Questions for Phase Redesign**:

1. Do we really need a warmup phase?
2. Should warmup be time-based or readiness-based?
3. Should PREPARING and WARMUP phases be collapsed?
4. Multi-worker: Initial workers need warmup, scale-up workers should start immediately
5. FIND_MAX mode: New workers spawned mid-test should inherit current phase

---

## Issue 3: QPS Rolling Average During PROCESSING (MEDIUM)

### Behavior Observed

- QPS display continued to "change" 38+ seconds into PROCESSING phase
- Dashboard maintains 30-element rolling history for `qps_avg_30s`
- During PROCESSING, same final QPS pushed repeatedly, average drifts

### Root Cause

`dashboard.js:1235-1240` pushes to `qpsHistory` regardless of phase:

```javascript
if (ops) {
  this.qpsHistory.push(this.metrics.ops_per_sec);  // BUG: Pushes during PROCESSING
  // ...
}
```

### Fix Applied

Gate `qpsHistory.push()` by `workers_active > 0`:

```javascript
if (ops && workers_active > 0) {
  this.qpsHistory.push(this.metrics.ops_per_sec);
}
```

---

## Issue 4: WebSocket Disconnects Before COMPLETED (RESOLVED)

### Behavior Observed

- Dashboard showed "stuck in PROCESSING" state
- WebSocket closed BEFORE enrichment completed
- Dashboard never received final `phase=COMPLETED` update

### Root Cause (Final)

Wrong query order in `_fetch_parent_enrichment_status()`:
- WebSocket checked **child rows first** for enrichment status
- Child rows exist but have NULL enrichment status (never updated)
- Function returned PENDING instead of checking parent row
- HTTP endpoint correctly checked parent row first

### Fix Applied

Rewrote `_fetch_parent_enrichment_status()` to check parent row FIRST:

```python
# Check parent first - it's the authoritative source
parent_rows = await pool.execute_query(
    "SELECT ENRICHMENT_STATUS FROM TEST_RESULTS WHERE TEST_ID = ?",
    params=[run_id],
)
if parent_status in ("COMPLETED", "FAILED", "SKIPPED"):
    return parent_status  # Immediate return
```

### Additional Fixes

1. **Frontend ordering**: Check phase BEFORE disconnecting WebSocket
2. **Fallback HTTP poll**: Poll on WebSocket close if not COMPLETED
3. **PROCESSING as active phase**: Timer continues during enrichment
4. **NULL handling**: Treat NULL enrichment status as PENDING

---

## Debugging Queries

### Check QUERY_TAG distribution

```sql
SELECT 
    QUERY_TAG,
    COUNT(*) as query_count,
    MIN(START_TIME) as first_query,
    MAX(START_TIME) as last_query
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_TAG LIKE '%<test_id>%'
GROUP BY QUERY_TAG
ORDER BY QUERY_TAG;
```

### Check queries by actual phase

```sql
WITH phase_times AS (
    SELECT 
        '<measurement_start>'::timestamp_ntz AS measurement_start,
        '<stop_time>'::timestamp_ntz AS stop_time
)
SELECT 
    CASE 
        WHEN START_TIME < p.measurement_start THEN 'WARMUP'
        WHEN START_TIME < p.stop_time THEN 'MEASUREMENT'
        ELSE 'AFTER_STOP'
    END as actual_phase,
    QUERY_TAG,
    COUNT(*) as count
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY, phase_times p
WHERE QUERY_TAG LIKE '%<test_id>%'
GROUP BY 1, 2
ORDER BY 1;
```

---

## Related Files

**Issue 1 (QUERY_TAG)**:
- `scripts/run_worker.py`: `_wait_for_start`, `_transition_to_measurement`, event loop
- `backend/core/test_executor.py`: `_transition_to_measurement_phase`
- `backend/connectors/snowflake_pool.py`: `update_query_tag`

**Issue 2 (Startup Delay)**:
- `backend/config.py:99`: `SNOWFLAKE_POOL_MAX_PARALLEL_CREATES`
- `backend/connectors/snowflake_pool.py`: `initialize()`
- `scripts/run_worker.py`: Pool initialization, READY heartbeat
- `backend/core/orchestrator.py`: Wait for workers READY

**Issue 3 (QPS Rolling Average)**:
- `backend/static/js/dashboard.js`: `qpsHistory` update logic

**Issue 4 (WebSocket Completion)**:
- `backend/main.py`: `_fetch_parent_enrichment_status()`, `_stream_run_metrics()`
- `backend/static/js/dashboard.js`: `updateLiveTransport()`
- `backend/static/js/dashboard/websocket.js`: `onclose` handler
- `backend/static/js/dashboard/data-loading.js`: Active phase check
