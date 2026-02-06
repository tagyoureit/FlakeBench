# Failed Timer Implementation Learnings

This document captures the history of timer-related issues in the FlakeBench
dashboard and the lessons learned from failed approaches. It serves as a reference
for the simplified timer implementation.

## Problem Summary

The dashboard timer system became overly complex due to attempts to synchronize
client-side timers with server-provided elapsed values. This led to:

- Counter anomalies (jumping backward)
- Race conditions on phase transitions
- Difficult-to-debug timing issues
- Multiple sources of truth causing conflicts

## Original Architecture (Failed)

```
+----------+     sync elapsed      +-----------+
| Backend  | ----timing.elapsed--> | Frontend  |
|          |     every WS msg      | Timer     |
+----------+                       +-----------+
     |                                  |
     +--phase changes---> recompute phase elapsed
     |
     polling every 1-3s for status/phase
```

The frontend received `timing.elapsed_display_seconds` from:
1. WebSocket `RUN_UPDATE` payloads (every 1s)
2. API `/api/tests/{id}` responses (polled every 3s)
3. API `loadTestInfo()` responses on page load

Each source could provide a different elapsed value, and the frontend tried to
reconcile these values while also maintaining its own local timer interval.

---

## Issue 1: Counter Anomaly (Frame 42: 3s→2s→4s)

### Symptom
During a test run, the elapsed counter displayed: 3s → 2s → 4s (jumping backward
then forward).

### Root Cause
The `syncElapsedTimer()` function in `timers.js` reset the timer base on every
WebSocket message:

```javascript
// timers.js (problematic code)
syncElapsedTimer(serverElapsed) {
  const elapsed = Number(serverElapsed);
  if (!Number.isFinite(elapsed) || elapsed < 0) return;
  this._elapsedBaseValue = elapsed;      // Reset base
  this._elapsedStartTime = Date.now();   // Reset start time
  this.elapsed = Math.floor(elapsed);
}
```

The local timer interval ran every 250ms:
```javascript
this._elapsedIntervalId = setInterval(() => {
  const secondsSinceStart = (Date.now() - this._elapsedStartTime) / 1000;
  this.elapsed = Math.floor(this._elapsedBaseValue + secondsSinceStart);
}, 250);
```

**The race condition:**
1. Local timer ticks at T+750ms, calculates elapsed = 3s
2. WebSocket message arrives with `elapsed_display_seconds: 2` (server lag)
3. `syncElapsedTimer(2)` resets base to 2, start time to now
4. Local timer ticks at T+250ms (from new start), calculates elapsed = 2s
5. Next tick at T+500ms calculates elapsed = 2s
6. Next tick at T+750ms calculates elapsed = 2s
7. Eventually catches up to 4s

### Why Server Could Send Lower Value
The server's `elapsed_display_seconds` was calculated using `TIMESTAMPDIFF(SECOND, START_TIME, CURRENT_TIMESTAMP())` in Snowflake. Due to query execution time and
network latency, the server value could be 1-2 seconds behind the client's
calculated value.

---

## Issue 2: Phase Transition Timing Errors

### Symptom
When transitioning from WARMUP to RUNNING, the phase-specific timer (`Xs/Ys`)
would show incorrect values or jump unexpectedly.

### Root Cause
The phase transition logic in `setPhaseIfAllowed()` recorded the elapsed time
at transition using the API-provided value:

```javascript
// phase.js (problematic code)
setPhaseIfAllowed(nextPhase, status, apiElapsed) {
  // ...
  const elapsedAtTransition = apiElapsed != null 
    ? Number(apiElapsed) 
    : Number(this.elapsed || 0);
  
  if (normalizedNext === "WARMUP") {
    this._warmupStartElapsed = elapsedAtTransition;
  } else if (normalizedNext === "RUNNING") {
    this._runningStartElapsed = elapsedAtTransition;
  }
}
```

Then `phaseElapsedSeconds()` calculated phase-specific elapsed as:
```javascript
phaseElapsedSeconds() {
  if (phase === "WARMUP") {
    const warmupStart = Number(this._warmupStartElapsed || 0);
    const phaseElapsed = Math.max(0, totalElapsed - warmupStart);
    return Math.min(phaseElapsed, warmup);
  }
  // ...
}
```

**The problem:**
- `apiElapsed` from server might be 2s behind actual elapsed
- `this.elapsed` from local timer might be 2s ahead of server
- Phase start time recorded with one value, elapsed calculated with another
- Results in negative phase elapsed or jumping values

---

## Issue 3: Multiple Sources of Truth

### Symptom
The timer would behave differently depending on whether updates came from
WebSocket, API polling, or local interval.

### Root Cause
Three different code paths could update the elapsed timer:

**1. WebSocket (dashboard.js:applyMetricsPayload)**
```javascript
if (serverElapsed !== null && isActiveStatus) {
  if (this._elapsedIntervalId) {
    this.syncElapsedTimer(serverElapsed);  // Sync path
  } else if (!isTerminal) {
    this.startElapsedTimer(serverElapsed);  // Start path
  }
}
```

**2. API Polling (data-loading.js:loadTestInfo)**
```javascript
if (hasElapsedDisplay && this.mode === "live" && isActiveStatus) {
  if (this._elapsedIntervalId) {
    this.syncElapsedTimer(elapsedDisplay);  // Another sync
  } else {
    this.startElapsedTimer(elapsedDisplay);  // Another start
  }
}
```

**3. Test Start (test-actions.js:startTest)**
```javascript
if (this.mode === "live") {
  this.startElapsedTimer(0);  // Optimistic start
}
```

Each path made different assumptions about the timer state, leading to:
- Timer started multiple times
- Sync overwriting optimistic values
- Race between API response and WebSocket message

---

## Issue 4: Status Backward Transition Rejection

### Symptom
Logs showed: `STATUS REJECTED (backward transition) {from: 'RUNNING', rejected: 'PREPARED'}`

### Root Cause
The `shouldAcceptStatus()` function in `phase.js` prevented backward status
transitions:

```javascript
shouldAcceptStatus(nextStatus) {
  const nextRank = this.statusRank(nextUpper);
  const currentRank = this.statusRank(currentUpper);
  return nextRank >= currentRank;
}
```

This was correct behavior, but the API polling could return stale `PREPARED`
status while WebSocket had already pushed `RUNNING`. The rejection was logged
but the root issue was the timing conflict between data sources.

---

## Issue 5: Running Phase Cut Short

### Symptom
Running phase showed `6s/10s` before transitioning to PROCESSING (should be `10s/10s`).

### Root Cause
This was NOT a timer bug. The test was terminated early by a memory guardrail:

```
backend.core.orchestrator - WARNING - Guardrail triggered for run 5ba1ca0f-...: 
memory_percent 85.20 >= 85.00
```

The UI correctly showed 6s because the test actually ran for only 6s before the
guardrail killed it. This was initially misdiagnosed as a timer issue.

---

## Previous Fix Attempts

### Attempt 1: Add Logging
Added extensive `[STATE-DEBUG]` console logging to track timer state changes.
This helped identify the issues but didn't fix them.

### Attempt 2: Guard Against Backward Sync
Added checks to ignore server elapsed if lower than current:
```javascript
if (Math.abs(prevBase - elapsed) > 2) {
  console.log("[STATE-DEBUG] TIMER SYNC", { prevBase, newBase: elapsed });
}
```
This reduced backward jumps but introduced timer drift.

### Attempt 3: Phase Start Time Tracking
Added `_warmupStartElapsed` and `_runningStartElapsed` to track phase starts.
This helped phase timers but complicated the code and didn't solve the sync
race condition.

### Attempt 4: Elapsed Source Priority
Tried prioritizing elapsed sources:
1. `timing.elapsed_display_seconds` from API
2. WebSocket payload elapsed
3. Local timer

This didn't help because different sources still conflicted.

---

## Lessons Learned

### 1. Local Timer Should Be Authoritative for Display
The client timer is for user feedback only. It doesn't need to match the server
exactly. A few seconds of drift is acceptable for UI purposes.

### 2. Sync Creates More Problems Than It Solves
Every sync attempt introduced race conditions. The server and client will never
be perfectly synchronized due to network latency and processing time.

### 3. Phase Transitions Should Be Event-Driven
Instead of inferring phase from elapsed time, the backend should emit explicit
phase transition events. The frontend should react to these events, not try to
predict them.

### 4. Single Source of Truth
Having multiple ways to update the timer (WebSocket, API, local) creates
conflicts. The new design uses:
- Local timer: only source for `this.elapsed`
- WebSocket events: only source for phase transitions

### 5. Debug Logging Is Essential
The `?debug=true` URL parameter allows verbose logging without cluttering
production. This should be maintained in the new implementation.

---

## New Architecture (Simplified)

```
+----------+                              +-----------+
| Backend  |                              | Frontend  |
|          |                              |           |
| WebSocket Stream (every 1s)             |           |
|  ├── RUN_UPDATE event                   |           |
|  │   ├── status: RUNNING/STOPPING/etc   |           |
|  │   ├── phase: WARMUP/MEASUREMENT/etc  |           |
|  │   ├── metrics: {ops, latency, ...}   |           |
|  │   ├── logs: [{seq, msg, ...}, ...]   |  Local    |
|  │   └── workers: [...]                 |  Timer    |
|  └── (no elapsed sync needed)           |           |
|                                         |           |
+----------+                              +-----------+
     |                                          |
     |  Phase transitions trigger               |
     |  recordPhaseStart() locally        just count up locally
     |                                    (timer starts on click)
```

Key changes:
1. **WebSocket-First**: All live data flows through WebSocket - no HTTP polling
   - Metrics stream every 1 second
   - Logs included in each RUN_UPDATE payload
   - Phase transitions come as status/phase fields
2. **Local Timer Only**: Timer starts on button click, counts up locally (no server sync)
3. **Phase Events**: Backend sends phase changes via WebSocket; frontend reacts
4. **No Polling During Active Test**: WebSocket handles metrics, logs, and phase updates
5. **Unified Debug Logging**: `_debugLog(module, message, data)` signature across all mixins

WebSocket connection criteria:
- Mode must be "live"
- Status must be RUNNING, CANCELLING, or STOPPING
- Once connected, WebSocket streams all data until terminal state

HTTP polling fallback:
- Only used when WebSocket fails to connect
- Disabled automatically when WebSocket is active

---

## References

- `backend/static/js/dashboard/timers.js` - Timer management
- `backend/static/js/dashboard/phase.js` - Phase tracking
- `backend/static/js/dashboard.js` - Main dashboard logic
- `docs/ui-architecture.md` - UI contract documentation
