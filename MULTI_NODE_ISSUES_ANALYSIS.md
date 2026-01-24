# Multi-Node Benchmark Issues - Detailed Analysis

## Executive Summary

Three issues were identified with multi-node (autoscale) benchmark tests. One has been fixed; two remain unresolved.

| Issue | Description | Status |
|-------|-------------|--------|
| #1 | Phase/timer jumping between 3 different values | **UNRESOLVED** |
| #2 | Stop button doesn't stop the benchmark | **UNRESOLVED** |
| #3 | Run Logs show "No logs yet." for child workers | **FIXED** |

---

## Architecture Overview

### Multi-Node Test Structure

```
┌─────────────────────────────────────────────────────────────┐
│                    PARENT TEST                               │
│  test_id: b159079e-212c-43b9-bc1e-c2ad9bf68a2e              │
│  run_id:  b159079e-212c-43b9-bc1e-c2ad9bf68a2e              │
│                                                              │
│  - Created by API endpoint                                   │
│  - Orchestrates autoscale logic                              │
│  - Has its own TestRegistry instance (in uvicorn process)   │
│  - Row exists in TEST_RESULTS table                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ spawns via subprocess
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    CHILD WORKER                              │
│  test_id: b66a925c-cc6e-4519-aa8f-43b34f5025c5              │
│  run_id:  b159079e-212c-43b9-bc1e-c2ad9bf68a2e  (same!)     │
│                                                              │
│  - Spawned by scripts/run_worker.py                         │
│  - Has its OWN TestRegistry instance (separate process)     │
│  - Performs actual benchmark execution                       │
│  - Row exists in TEST_RESULTS table                          │
│  - Updates its own status/phase/timing                       │
└─────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `backend/core/autoscale.py` | Orchestrates multi-node tests, spawns workers |
| `scripts/run_worker.py` | Headless worker process that runs benchmarks |
| `backend/core/test_registry.py` | Manages test state, logging, phase transitions |
| `backend/api/routes/test_results.py` | API endpoints for test data |
| `backend/static/js/dashboard.js` | Frontend polling and display logic |

---

## Issue #1: Phase/Timer Jumping Around

### Observed Behavior
- Dashboard shows timer values that jump between 3 different numbers
- Phase alternates (e.g., PREPARING → RUNNING → WARMUP → RUNNING)
- Values don't progress linearly

### Hypothesis: Multiple Data Sources Conflict

The dashboard polls `GET /api/tests/{parent_test_id}` which returns timing/phase data. However, there are **multiple potential sources** for this data:

1. **Parent's in-memory TestRegistry** (uvicorn process)
2. **Child's in-memory TestRegistry** (worker subprocess - INACCESSIBLE)
3. **Parent row in Snowflake** (TEST_RESULTS table)
4. **Child row in Snowflake** (TEST_RESULTS table)

#### The API Endpoint Logic (lines 2703-2855 in test_results.py)

```python
# Simplified flow for GET /api/tests/{test_id}
async def get_test(test_id: str):
    # First tries in-memory registry
    running = registry.get(test_id)  # Gets PARENT's registry entry
    
    # Falls back to Snowflake DB query
    rows = await pool.execute_query(query, params=[test_id])
    
    # For multi-node: may aggregate from children
    # But timing/phase comes from... where?
```

#### Suspected Root Cause

The timing/phase data may be coming from **different sources on different poll cycles**:

1. **Poll 1**: Returns parent's Snowflake row (phase=PREPARING, elapsed=5s)
2. **Poll 2**: Returns child's Snowflake row (phase=RUNNING, elapsed=45s)  
3. **Poll 3**: Returns parent's in-memory state (phase=WARMUP, elapsed=10s)
4. **Poll 4**: Returns aggregated/computed timing (elapsed=50s)

This would explain why 3 different values appear and switch back and forth.

### Investigation Needed

1. **Trace the exact data flow** in `get_test()` for multi-node tests
2. **Check if parent vs child timing is being mixed**
3. **Verify which Snowflake row is being queried**
4. **Check if in-memory and DB states are out of sync**

### Relevant Code Sections

- `backend/api/routes/test_results.py` lines 200-400 (get_test endpoint)
- `backend/core/autoscale.py` lines 200-400 (parent/child coordination)
- `backend/core/test_registry.py` lines 400-600 (phase/timing updates)

---

## Issue #2: Stop Button Doesn't Work

### Observed Behavior
- Clicking "Stop" button on dashboard doesn't stop the benchmark
- Test continues running despite stop request
- Status may briefly show CANCELLING but reverts to RUNNING

### Architecture Problem

```
┌──────────────┐     POST /stop      ┌──────────────┐
│   Browser    │ ─────────────────▶  │   uvicorn    │
│  Dashboard   │                     │   process    │
└──────────────┘                     └──────────────┘
                                            │
                                            │ registry.stop(parent_id)
                                            ▼
                                     ┌──────────────┐
                                     │   Parent     │
                                     │  TestRegistry│ ✓ Can stop parent
                                     └──────────────┘
                                            │
                                            │ ??? How to stop child?
                                            ▼
                                     ┌──────────────┐
                                     │    Child     │
                                     │   Worker     │ ✗ Separate process!
                                     │  (subprocess)│
                                     └──────────────┘
```

### The Stop Endpoint (lines 1184-1240 in test_results.py)

```python
@router.post("/{test_id}/stop")
async def stop_test(test_id: str):
    # For parent runs, also stop child workers
    run_id = rows[0][0]
    is_parent = run_id == test_id
    
    if is_parent:
        # Get all child test IDs
        child_rows = await pool.execute_query(child_query, params=[test_id])
        for child_id in child_rows:
            running = await registry.stop(child_id)  # ← PROBLEM HERE
```

### Suspected Root Cause

`registry.stop(child_id)` tries to stop the child in the **parent's registry**, but the child worker is a **separate subprocess** with its own registry. The stop signal never reaches the actual child process.

The code does attempt to kill child processes via `pgrep`:

```python
result = subprocess.run(
    ["pgrep", "-f", f"parent-run-id {test_id}"],
    ...
)
```

But this may not be working correctly.

### Investigation Needed

1. **Check if pgrep pattern matches** the actual subprocess command
2. **Verify subprocess.run() is actually killing processes**
3. **Consider adding a stop file/signal mechanism** that child workers poll for
4. **Check if child writes its PID somewhere** for reliable termination

---

## Issue #3: Run Logs Not Loading (FIXED)

### Original Problem
- "Run Logs" section showed "No logs yet." for multi-node tests
- Child worker logs never appeared during execution

### Root Cause Identified
Child worker subprocess has its own `TestRegistry` with its own `log_buffer`. Logs were only flushed to Snowflake DB when:
1. Batch size (200 logs) reached, OR
2. Test completed

Since benchmarks rarely generate 200+ logs, they weren't persisted during execution.

### Fix Applied

**File**: `backend/core/test_registry.py`  
**Function**: `_drain_test_logs()`

Added time-based flushing (every 5 seconds):

```python
async def _drain_test_logs(
    self,
    *,
    test_id: str,
    q: asyncio.Queue,
    flush_batch_size: int = 200,
    flush_interval_seconds: float = 5.0,  # NEW
) -> None:
    pending_rows: list[dict[str, Any]] = []
    last_flush_time = time.monotonic()
    
    while True:
        try:
            event = await asyncio.wait_for(q.get(), timeout=1.0)
        except asyncio.TimeoutError:
            # Time-based flush check (NEW)
            if pending_rows and (time.monotonic() - last_flush_time) >= flush_interval_seconds:
                await insert_test_logs(rows=pending_rows)
                pending_rows.clear()
                last_flush_time = time.monotonic()
            continue
        ...
```

### Verification
- Started autoscale test `87216095-d840-40cb-8924-8770e9d8205f`
- Child worker `f236dff1-886f-4763-b777-47351e53e267` generated logs
- Logs appeared in Snowflake DB during execution (22 → 26 → 30 logs over time)
- API endpoint correctly retrieved logs from DB

---

## Summary of Work Performed

### Session Timeline

1. **Analyzed the log buffering architecture** in `_drain_test_logs()`
2. **Identified root cause** of Issue #3: batch-only flushing
3. **Implemented fix**: Added 5-second time-based flush interval
4. **Verified fix** with new autoscale test - logs now appear in real-time
5. **User reported** Issues #1 and #2 still occurring
6. **Observed** test `b159079e-212c-43b9-bc1e-c2ad9bf68a2e` showing unstable behavior
7. **Documented** findings in this analysis

### Files Modified

| File | Change |
|------|--------|
| `backend/core/test_registry.py` | Added time-based log flushing (5 second interval) |

### Tests Executed

| Test ID | Type | Purpose |
|---------|------|---------|
| `87216095-d840-40cb-8924-8770e9d8205f` | Autoscale | Verified log flushing fix |
| `b159079e-212c-43b9-bc1e-c2ad9bf68a2e` | Autoscale | User's test showing Issues #1/#2 |

---

## Recommended Next Steps

### For Issue #1 (Phase Jumping)

1. Add logging to `get_test()` to trace which data source returns timing
2. Check if parent row and child row have conflicting timing values
3. Consider making timing source deterministic (always use child's timing for multi-node)
4. Verify the dashboard isn't polling multiple endpoints that return different data

### For Issue #2 (Stop Not Working)

1. Debug the `pgrep` subprocess killing logic
2. Add a "stop file" mechanism: parent writes `/tmp/{test_id}.stop`, child polls for it
3. Consider using proper process management (e.g., process groups, SIGTERM propagation)
4. Add verification logging to confirm child processes are actually terminated

---

## Appendix: Key Database Queries

### Find child workers for a parent test
```sql
SELECT TEST_ID, STATUS, CREATED_AT 
FROM UNISTORE_BENCHMARK.TEST_RESULTS.TEST_RESULTS 
WHERE RUN_ID = '{parent_test_id}'
ORDER BY CREATED_AT;
```

### Check logs for a child worker
```sql
SELECT COUNT(*) 
FROM UNISTORE_BENCHMARK.TEST_RESULTS.TEST_LOGS 
WHERE TEST_ID = '{child_test_id}';
```

### Get timing data for comparison
```sql
SELECT TEST_ID, STATUS, 
       TEST_CONFIG:timing::variant as timing
FROM UNISTORE_BENCHMARK.TEST_RESULTS.TEST_RESULTS 
WHERE RUN_ID = '{parent_test_id}';
```
