# Plan: WebSocket Push Implementation

## Overview
Migrate from HTTP polling to WebSocket push for all live test data (metrics, logs, phase transitions). This eliminates polling overhead and ensures real-time updates.

## Current State
- WebSocket endpoint exists at `/ws/test/{test_id}`
- Backend sends `RUN_UPDATE` events with metrics every ~1 second
- **BUG**: WebSocket only connects when `phase === "RUNNING"`, missing WARMUP phase entirely
- Frontend polls `/api/tests/{id}/metrics` and `/api/tests/{id}/logs` via HTTP
- Each mixin has its own `_debugLog` that overwrites others

## Target State
- WebSocket connects immediately when test starts (PREPARING phase)
- All data flows through WebSocket: metrics, logs, phase transitions
- HTTP polling only used as fallback when WebSocket disconnects
- Single unified debug logging approach

## Implementation Steps

### Task 1: Fix WebSocket Connection Timing
**File**: `backend/static/js/dashboard.js`

Update `shouldUseWebSocket()`:
```javascript
shouldUseWebSocket() {
  if (this.mode !== "live") return false;
  const statusUpper = (this.status || "").toString().toUpperCase();
  // Connect during all active phases, not just RUNNING
  return ["RUNNING", "CANCELLING", "STOPPING"].includes(statusUpper);
}
```

Update `updateLiveTransport()` active test detection:
```javascript
const isActiveTest =
  ["RUNNING", "CANCELLING", "STOPPING"].includes(statusUpper);
```

### Task 2: Add Logs to Backend WebSocket Stream
**File**: `backend/main.py`

In `_stream_run_metrics()`, add log fetching:
```python
# Fetch recent logs for this test
logs = await _fetch_recent_logs(test_id, since_timestamp=last_log_timestamp)
if logs:
    payload["logs"] = logs
    last_log_timestamp = logs[-1]["timestamp"]
```

### Task 3: Handle Logs from WebSocket in Frontend
**File**: `backend/static/js/dashboard/websocket.js`

Extract logs from RUN_UPDATE payload:
```javascript
// In onmessage handler, after extracting wsPayload
if (wsPayload.logs && Array.isArray(wsPayload.logs)) {
  this.appendLogs(wsPayload.logs);
}
```

### Task 4: Remove HTTP Polling During WebSocket Mode
**File**: `backend/static/js/dashboard/data-loading.js`

Remove metrics/logs polling when WebSocket is active:
```javascript
// In loadTestInfo(), skip polling setup if WebSocket is connected
if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
  // WebSocket handles metrics and logs - no HTTP polling needed
  return;
}
```

### Task 5: Fix Debug Logging
Create a single shared debug function or use module-specific prefixes consistently.

Option A: Each mixin uses unique prefix in its logs (no shared function)
Option B: Single `_debugLog(prefix, message, data)` defined once in dashboard.js

### Task 6: Update Documentation
Update `docs/failed-timer-learnings.md` to document:
- WebSocket-first architecture
- No HTTP polling during active tests
- Fallback behavior when WebSocket disconnects

## Testing Checklist
- [ ] WebSocket connects when test starts (during PREPARING)
- [ ] Phase transitions appear in console with `?debug=true`
- [ ] Metrics update in real-time via WebSocket
- [ ] Logs appear in real-time via WebSocket
- [ ] No HTTP polling to /metrics or /logs during active test
- [ ] Timer counts continuously without jumps
- [ ] Warmup → Running transition is reflected in UI
