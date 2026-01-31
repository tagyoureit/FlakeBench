# Timer & Phase Fixes (2.18/2.19)

Documents the elapsed time and phase display bugs and their resolution.

## Problem Analysis

The dashboard displays ~28810 seconds elapsed (8 hours) for a 20-second test.
Root cause analysis revealed multiple contributing factors:

### Timezone Mismatch (Root Cause)

**CRITICAL**: Snowflake returns naive datetime objects in the session timezone
(typically US/Pacific), but Python's `datetime.now(timezone.utc)` returns UTC.
When calculating elapsed time in Python:

```python
# BUGGY - 8 hour discrepancy:
elapsed = (datetime.now(timezone.utc) - snowflake_start_time).total_seconds()
# Returns ~28800 + actual_elapsed (Pacific is UTC-8)
```

**Solution**: Always calculate elapsed time in Snowflake using `TIMESTAMPDIFF`:

```sql
TIMESTAMPDIFF(SECOND, START_TIME, CURRENT_TIMESTAMP()) AS ELAPSED_SECONDS
```

### Contributing Factors

- **Missing TIMESTAMPDIFF in main.py**: WebSocket path didn't use TIMESTAMPDIFF.
- **Multiple data sources for elapsed**: WebSocket and API returned different values.
- **Stale START_TIME**: May be set at PREPARED, not actual start.
- **WebSocket polling for PREPARED tests**: Sent updates before test started.

## 2.18 Status: ⚠️ Superseded

Section 2.18 documented an attempted fix for phase display and timer issues. While
some frontend fixes (phase normalization, visibility control) were implemented,
the core elapsed time bug was not resolved.

**What was attempted**:
- Frontend: `normalizePhase()` mapping, `hasTestStarted()` visibility, CSS fixes
- Backend: Elapsed-based phase derivation in `test_results.py`

**Why it failed**: The fix only addressed the API path but the dashboard primarily
uses WebSocket updates from `main.py`, which has a separate implementation with the
same timezone bug.

## 2.19 Implementation (Completed)

### Tasks Completed

- [x] **Prepare before Start flow**: Templates page prepares run, dashboard shows "Ready" state.
- [x] **Skip WebSocket for non-running tests**: Only connect when RUNNING or STOPPING.
- [x] **Single source of truth for elapsed**: WebSocket includes `timing` block with
  `elapsed_display_seconds` from TIMESTAMPDIFF.
- [x] **Reset START_TIME on run start**: Always set `START_TIME = CURRENT_TIMESTAMP()`.
- [x] **Handle completed tests**: Use stored `duration_seconds` from TEST_RESULTS.
- [x] **Continuous total timer + phase timers**: Timer runs through all phases without reset.
- [x] **Keep 2.18 frontend fixes**: `normalizePhase()` and `hasTestStarted()` retained.

### SQL Fix Applied

In `main.py`, `_fetch_run_status` uses TIMESTAMPDIFF:

```sql
SELECT
  rs.STATUS,
  rs.PHASE,
  rs.START_TIME,
  rs.END_TIME,
  CASE
    WHEN rs.STATUS IN ('COMPLETED', 'FAILED', 'CANCELLED', 'STOPPED') THEN
      COALESCE(tr.DURATION_SECONDS, TIMESTAMPDIFF(SECOND, rs.START_TIME, rs.END_TIME))
    ELSE
      TIMESTAMPDIFF(SECOND, rs.START_TIME, CURRENT_TIMESTAMP())
  END AS ELAPSED_SECONDS
FROM RUN_STATUS rs
LEFT JOIN TEST_RESULTS tr ON tr.TEST_ID = rs.RUN_ID
WHERE rs.RUN_ID = ?
```

### Files Modified

- `backend/main.py`: TIMESTAMPDIFF-based elapsed values in WebSocket path.
- `backend/static/js/dashboard/*`: Gate WebSocket until RUNNING/STOPPING.
- `backend/static/js/templates_manager.js`: Prepare runs and redirect.
- `backend/api/routes/test_results.py`: TIMESTAMPDIFF in API responses.
- `backend/core/orchestrator.py`: `START_TIME` set on actual start.

## Debugging Notes

**DO NOT REMOVE** until fix verified: Frontend JavaScript files contain `console.log`
debugging statements added during investigation. Files:
- `backend/static/js/dashboard/data-loading.js`
- `backend/static/js/dashboard/phase.js`

## Testing Procedure

1. Select a template with 10s warmup + 10s running (20s total)
2. Click "Run Benchmark" → redirects to dashboard
3. Dashboard shows template info in "Ready" state, no elapsed ticking
4. Click "Start" → timer starts from 0
5. Timer progresses continuously through all phases
6. Final elapsed should be ~20s, not 28810s
7. Refresh page after completion → elapsed still shows ~20s

## Acceptance Criteria

- [x] Dashboard shows correct elapsed time (~20s for 20s test)
- [x] WebSocket and API return consistent elapsed values
- [x] Phase bubbles show correct transitions
- [x] Prepared run exists before Start without elapsed ticking
- [x] WebSocket only connects for RUNNING/STOPPING
- [x] `START_TIME` is always set at actual test start
- [x] Completed tests show final duration
- [x] Total timer is continuous through PROCESSING
