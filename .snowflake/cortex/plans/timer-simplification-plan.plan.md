---
name: "timer-simplification-plan"
created: "2026-01-28T15:26:57.288Z"
status: pending
---

# Plan: Simplify Frontend Timer with WebSocket Events

## Problem Statement

The current timer implementation has become overly complex due to multiple sources of truth and server-client synchronization. This causes:

- Counter anomalies (jumping backward)
- Race conditions on phase transitions
- Difficult-to-debug timing issues

## Desired Behavior

| Event                       | UI Behavior                                                                          |
| --------------------------- | ------------------------------------------------------------------------------------ |
| User clicks Start           | Button disabled, LOCAL timer starts at 0s, Preparing bubble active                   |
| First worker enters WARMUP  | PHASE\_CHANGED received, Warmup bubble active, show `Xs/Ys` countdown                |
| First worker enters RUNNING | PHASE\_CHANGED received, Running bubble active, show `Xs/Ys`                         |
| Last query completes        | PHASE\_CHANGED received, Processing bubble active                                    |
| Enrichment completes        | PHASE\_CHANGED received, Completed bubble active, TOTAL timer STOPS                  |
| Cancellation triggered      | PHASE\_CHANGED (phase=CANCELLING, reason=...), Toast with reason, "Cancelling" label |
| Cancellation finalized      | PHASE\_CHANGED (phase=CANCELLED), "Cancelled" label                                  |

## Architecture Change

```
BEFORE (Polling + Complex Sync)
+----------+     sync elapsed      +-----------+
| Backend  | ----timing.elapsed--> | Frontend  |
|          |     every WS msg      | Timer     |
+----------+                       +-----------+
     |                                  |
     +--phase changes---> recompute phase elapsed
     |
     polling every 1-3s for status/phase

AFTER (Event-Driven WebSocket)
+----------+     PHASE_CHANGED       +-----------+
| Backend  | ----------------------> | Frontend  |
|          |   phase: WARMUP         | Local     |
|          |   phase: RUNNING        | Timer     |
|          |   phase: PROCESSING     |           |
|          |   phase: COMPLETED      |           |
|          |   phase: CANCELLING     |           |
|          |   phase: CANCELLED      |           |
+----------+   (+ reason if cancel)  +-----------+
                                          |
                                   just count up locally
```

## Single Event Type Design

All phase transitions use one event: `PHASE_CHANGED`

```
// Normal phases
{ "event": "PHASE_CHANGED", "data": { "phase": "WARMUP", "warmup_seconds": 10, "run_seconds": 60 }}
{ "event": "PHASE_CHANGED", "data": { "phase": "RUNNING", "run_seconds": 60 }}
{ "event": "PHASE_CHANGED", "data": { "phase": "PROCESSING" }}
{ "event": "PHASE_CHANGED", "data": { "phase": "COMPLETED" }}

// Cancellation (reason included when applicable)
{ "event": "PHASE_CHANGED", "data": { "phase": "CANCELLING", "reason": "Memory guardrail triggered (85.2% >= 85%)" }}
{ "event": "PHASE_CHANGED", "data": { "phase": "CANCELLED", "reason": "Memory guardrail triggered (85.2% >= 85%)" }}
```

## Debug Logging

Add `?debug=true` URL parameter support:

- When `debug=true`: Console log all WebSocket events with timestamps
- When `debug=false` or missing: No console logging (production mode)

---

## Implementation Details

### Task 1: Create failed-timer-learnings.md

Location: `docs/failed-timer-learnings.md`

Document:

- Original timer sync approach and why it failed
- Race condition with `syncElapsedTimer()`
- Counter anomaly (frame 42: 3s->2s->4s) root cause
- Phase transition timing issues
- All previous fix attempts from memory file

### Task 2: Backend - Emit PHASE\_CHANGED Events

Files:

- `backend/core/orchestrator.py` - emit phase change events
- `backend/services/pubsub.py` - event emission helpers

Emit `PHASE_CHANGED` for all transitions:

| Trigger                | Phase Value  | Extra Fields                    |
| ---------------------- | ------------ | ------------------------------- |
| First worker warmup    | `WARMUP`     | `warmup_seconds`, `run_seconds` |
| First worker running   | `RUNNING`    | `run_seconds`                   |
| All queries complete   | `PROCESSING` | -                               |
| Enrichment complete    | `COMPLETED`  | -                               |
| Guardrail/user cancel  | `CANCELLING` | `reason`                        |
| Cancellation finalized | `CANCELLED`  | `reason`                        |

Example implementation in orchestrator:

```
async def _emit_phase_changed(self, test_id: str, phase: str, **kwargs):
    payload = {"phase": phase, **kwargs}
    await self.pubsub.publish(f"test:{test_id}", {
        "event": "PHASE_CHANGED",
        "data": payload
    })
```

### Task 3: Refactor timers.js

File: backend/static/js/dashboard/timers.js

Changes:

1. **Remove** `syncElapsedTimer()` entirely
2. **Simplify** `startElapsedTimer()` - no baseValue, always starts at 0
3. **Add** `recordPhaseStart(phase)` to track when phases started locally
4. **Add** `getPhaseElapsed(phase)` for phase-specific timing

```
window.DashboardMixins.timers = {
  startElapsedTimer() {
    this.stopElapsedTimer();
    this._elapsedStartTime = Date.now();
    this.elapsed = 0;
    if (this.debug) {
      console.log('[TIMER] Started at', new Date().toISOString());
    }
    this._elapsedIntervalId = setInterval(() => {
      this.elapsed = Math.floor((Date.now() - this._elapsedStartTime) / 1000);
    }, 250);
  },

  stopElapsedTimer() {
    if (this._elapsedIntervalId) {
      if (this.debug) {
        console.log('[TIMER] Stopped at', this.elapsed, 'seconds');
      }
      clearInterval(this._elapsedIntervalId);
      this._elapsedIntervalId = null;
    }
  },

  recordPhaseStart(phase) {
    const now = Date.now();
    if (this.debug) {
      console.log('[TIMER] Phase started:', phase, 'at', new Date(now).toISOString());
    }
    if (phase === 'WARMUP') {
      this._warmupStartTime = now;
    } else if (phase === 'RUNNING' || phase === 'MEASUREMENT') {
      this._runningStartTime = now;
    }
  },

  getPhaseElapsed(phase) {
    const now = Date.now();
    if (phase === 'WARMUP' && this._warmupStartTime) {
      return Math.floor((now - this._warmupStartTime) / 1000);
    }
    if ((phase === 'RUNNING' || phase === 'MEASUREMENT') && this._runningStartTime) {
      return Math.floor((now - this._runningStartTime) / 1000);
    }
    return 0;
  },

  // Keep existing processing log timer methods
  startProcessingLogTimer() { /* ... */ },
  stopProcessingLogTimer() { /* ... */ }
};
```

### Task 4: Simplify phase.js

File: backend/static/js/dashboard/phase.js

Changes:

1. **Remove** `_warmupStartElapsed` and `_runningStartElapsed` parameters
2. **Simplify** `phaseElapsedSeconds()` to use `getPhaseElapsed()`
3. **Update** `setPhaseIfAllowed()` - remove apiElapsed param, call `recordPhaseStart()`

```
// Simplified setPhaseIfAllowed - no apiElapsed parameter
setPhaseIfAllowed(nextPhase, status) {
  const prevPhase = this.phase;
  const accepted = this.shouldAcceptPhase(nextPhase, status);
  if (!accepted) return false;
  
  this.phase = nextPhase;
  const normalizedPrev = this.normalizePhase(prevPhase);
  const normalizedNext = this.normalizePhase(nextPhase);
  
  if (normalizedPrev !== normalizedNext) {
    if (this.debug) {
      console.log('[PHASE] Changed from', normalizedPrev, 'to', normalizedNext);
    }
    this.recordPhaseStart(normalizedNext);
  }
  return true;
}

// Simplified phaseElapsedSeconds
phaseElapsedSeconds() {
  const phase = this.normalizePhase(this.phase);
  const warmup = Number(this.warmupSeconds || 0);
  const run = Number(this.runSeconds || 0);

  if (phase === 'WARMUP') {
    const elapsed = this.getPhaseElapsed('WARMUP');
    return warmup > 0 ? Math.min(elapsed, warmup) : elapsed;
  }
  if (phase === 'RUNNING') {
    const elapsed = this.getPhaseElapsed('RUNNING');
    return run > 0 ? Math.min(elapsed, run) : elapsed;
  }
  return 0;
}
```

### Task 5: Update dashboard.js - PHASE\_CHANGED Handler

File: backend/static/js/dashboard.js

Add unified `handlePhaseChanged()` method:

```
handlePhaseChanged(data) {
  if (this.debug) {
    console.log('[WS-EVENT] PHASE_CHANGED', new Date().toISOString(), data);
  }
  
  const phase = data.phase;
  const reason = data.reason;
  
  // Update timing config if provided
  if (data.warmup_seconds != null) this.warmupSeconds = data.warmup_seconds;
  if (data.run_seconds != null) this.runSeconds = data.run_seconds;
  
  // Show toast for cancellation with reason
  if ((phase === 'CANCELLING' || phase === 'CANCELLED') && reason) {
    window.toast.error(`Test cancelled: ${reason}`);
  }
  
  // Set phase (calls recordPhaseStart internally)
  this.setPhaseIfAllowed(phase, this.status);
  
  // Update status for terminal phases
  if (phase === 'COMPLETED') {
    this.status = 'COMPLETED';
    this.stopElapsedTimer();
  } else if (phase === 'CANCELLING') {
    this.status = 'CANCELLING';
  } else if (phase === 'CANCELLED') {
    this.status = 'CANCELLED';
    this.stopElapsedTimer();
  }
  
  // Update transport based on new phase
  this.updateLiveTransport();
}
```

Update `applyMetricsPayload()` to route PHASE\_CHANGED:

```
applyMetricsPayload(payload) {
  if (!payload) return;
  
  try {
    // Handle PHASE_CHANGED events
    if (payload.event === "PHASE_CHANGED") {
      this.handlePhaseChanged(payload.data);
      return;
    }
    
    // Handle RUN_UPDATE as before (for metrics, charts)
    let data = payload;
    if (data && data.event === "RUN_UPDATE" && data.data) {
      data = data.data;
    }
    
    // ... existing metrics/chart handling ...
    // REMOVE: all syncElapsedTimer() calls
    // REMOVE: timer start/stop based on timing.elapsed_display_seconds
  } catch (e) {
    console.error("[dashboard] applyMetricsPayload error:", e);
  }
}
```

### Task 6: Add Debug Logging Throughout

Files: All frontend JS files

Add debug logging pattern:

```
if (this.debug) {
  console.log('[MODULE] Event/action description', details);
}
```

Locations:

- `websocket.js`: Log all received WebSocket messages
- `timers.js`: Log timer start/stop/phase events
- `phase.js`: Log phase transitions
- `test-actions.js`: Log start/stop actions
- `dashboard.js`: Log PHASE\_CHANGED handling

### Task 7: Clean Up Related Files

**test-actions.js** - Simplify `startTest()`:

```
async startTest() {
  // Start local timer immediately on click
  this.phase = "PREPARING";
  this.status = "RUNNING";
  this._warmupStartTime = null;
  this._runningStartTime = null;
  this.startElapsedTimer();
  
  if (this.debug) {
    console.log('[ACTION] Start clicked, timer started');
  }
  
  // ... API call ...
  // WebSocket will send PHASE_CHANGED events for transitions
}
```

**data-loading.js** - Remove timer sync from `loadTestInfo()`:

- Remove all `syncElapsedTimer()` calls
- Remove `startElapsedTimer(elapsedDisplay)` calls
- Keep only status/phase setting for initial load

**state.js** - Update state:

```
{
  // Add new fields
  _warmupStartTime: null,
  _runningStartTime: null,
  
  // Remove deprecated
  // _elapsedBaseValue: 0  // No longer needed
}
```

---

## Files to Modify

| File                                          | Changes                                  |
| --------------------------------------------- | ---------------------------------------- |
| `docs/failed-timer-learnings.md`              | New - document all timer issues          |
| `backend/core/orchestrator.py`                | Emit PHASE\_CHANGED events               |
| `backend/static/js/dashboard/timers.js`       | Remove sync, add local phase timing      |
| `backend/static/js/dashboard/phase.js`        | Simplify phase elapsed calculation       |
| `backend/static/js/dashboard/state.js`        | Add phase start times, remove deprecated |
| `backend/static/js/dashboard/websocket.js`    | Add debug logging                        |
| `backend/static/js/dashboard.js`              | Add handlePhaseChanged(), remove sync    |
| `backend/static/js/dashboard/test-actions.js` | Simplify startTest()                     |
| `backend/static/js/dashboard/data-loading.js` | Remove timer sync                        |

## Debug Logging Output Example

With `?debug=true`:

```
[INIT] Debug mode enabled
[ACTION] Start clicked, timer started
[TIMER] Started at 2026-01-28T10:30:00.123Z
[WS] Received: PHASE_CHANGED 2026-01-28T10:30:02.456Z {phase: "WARMUP", warmup_seconds: 10, run_seconds: 60}
[WS-EVENT] PHASE_CHANGED 2026-01-28T10:30:02.456Z {phase: "WARMUP", ...}
[PHASE] Changed from PREPARING to WARMUP
[TIMER] Phase started: WARMUP at 2026-01-28T10:30:02.456Z
[WS] Received: PHASE_CHANGED 2026-01-28T10:30:12.789Z {phase: "RUNNING", run_seconds: 60}
[WS-EVENT] PHASE_CHANGED 2026-01-28T10:30:12.789Z {phase: "RUNNING", ...}
[PHASE] Changed from WARMUP to RUNNING
[TIMER] Phase started: RUNNING at 2026-01-28T10:30:12.789Z
[WS] Received: PHASE_CHANGED 2026-01-28T10:30:45.000Z {phase: "CANCELLING", reason: "Memory guardrail triggered"}
[WS-EVENT] PHASE_CHANGED 2026-01-28T10:30:45.000Z {phase: "CANCELLING", reason: "..."}
[PHASE] Changed from RUNNING to CANCELLING
Toast: "Test cancelled: Memory guardrail triggered"
[WS] Received: PHASE_CHANGED 2026-01-28T10:30:46.000Z {phase: "CANCELLED"}
[PHASE] Changed from CANCELLING to CANCELLED
[TIMER] Stopped at 46 seconds
```

---

## Risk Assessment

| Risk                         | Mitigation                                          |
| ---------------------------- | --------------------------------------------------- |
| Timer drift from server      | Acceptable - display only, not accuracy-critical    |
| Phase timing off by 1-2s     | Better than current race conditions                 |
| PHASE\_CHANGED not delivered | RUN\_UPDATE still provides status/phase as fallback |
