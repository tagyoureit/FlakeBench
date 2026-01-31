# Log Streaming Improvements Plan

This document outlines the implementation plan for improving worker log visibility
and filtering in the UI.

## Problem Statement

Current log display lacks:

1. Clear worker identification (which worker generated each log)
2. Log level filtering (users see all logs regardless of severity)
3. Verbose vs normal mode toggle
4. Per-worker log isolation

See [log-streaming-architecture.md](../log-streaming-architecture.md) for detailed
analysis.

## Proposed UI Enhancement

```text
┌──────────────────────────────────────────────────────┐
│ Run Logs                                              │
├──────────────────────────────────────────────────────┤
│ Worker: [All ▼]  Level: [INFO+ ▼]  □ Verbose Mode    │
├──────────────────────────────────────────────────────┤
│ 12:18:15 PM INFO [worker-0] Spawning worker...       │
│ 12:18:17 PM INFO [worker-0] Initialized pool...      │
│ 12:18:17 PM INFO [worker-0] Connection pool init...  │
│ 12:18:17 PM DEBUG [worker-0] Creating 1 connections  │  ← only in verbose
│ 12:18:18 PM INFO [worker-1] Starting...              │
└──────────────────────────────────────────────────────┘
```

## Implementation Tasks

### Task 2.22: Log Streaming Improvements

#### 2.22.1: Add worker_id to log events (Backend)

**Files to modify**:
- `backend/core/test_log_stream.py:18` - Add `CURRENT_WORKER_ID`
  contextvar
- `backend/core/test_log_stream.py:69-79` - Add `worker_id` field to
  event dict
- `backend/core/orchestrator.py:583` - Set `CURRENT_WORKER_ID` when
  spawning workers
- `scripts/run_worker.py` - Set `CURRENT_WORKER_ID` on worker startup

**Schema change** (optional, for persistence):
- Add `WORKER_ID VARCHAR` column to `TEST_LOGS` table

**Event contract notes**:
- `worker_id` is required for worker-generated logs; define a canonical
  label for non-worker logs (TBD).
- Ensure event payloads always include `worker_id` even if persistence is
  deferred (UI depends on it).
- If `WORKER_ID` is added, define handling for historical rows with NULL
  values (e.g., map to a neutral label in UI and filters).

**Estimated effort**: Small

#### 2.22.2: Add log level filtering to UI (Frontend)

**Files to modify**:
- `backend/templates/pages/dashboard.html:425-449` - Add filter
  dropdown
- `backend/static/js/dashboard/state.js:96-102` - Add `logLevelFilter`
  state
- `backend/static/js/dashboard/logs.js:92-104` - Filter in `logsText()`
  method

**Filter options**:
- ALL (show everything)
- DEBUG+ (show DEBUG and above)
- INFO+ (show INFO and above) - **default**
- WARNING+ (show WARNING and above)
- ERROR only

**Server-side filtering (optional, follow-up)**:
- Consider adding `level` and `worker_id` parameters to the WebSocket and
  HTTP log endpoints to reduce payload size.
- UI should pass filter state when supported, and fall back to
  client-side filtering otherwise.

**Estimated effort**: Small

#### 2.22.3: Add verbose mode toggle (Full-stack)

**Files to modify**:
- `backend/templates/pages/dashboard.html` - Add checkbox
- `backend/static/js/dashboard/state.js` - Add `logVerboseMode` state
- `backend/static/js/dashboard/logs.js` - Conditional formatting

**Behavior**:
- Normal mode: Shortened logger names, INFO+ by default
- Verbose mode: Full logger paths, DEBUG+ enabled, shows additional context

**UX behavior decisions**:
- Define whether `?verbose=true` also sets the default level filter
  (e.g., DEBUG+) or only toggles formatting.
- Define whether toggling verbose preserves the user-selected filter
  (recommended: preserve).

**URL parameter support**: `?verbose=true`

**Estimated effort**: Small

#### 2.22.4: Worker badges in log display (Frontend)

**Files to modify**:
- `backend/static/js/dashboard/logs.js:92-104` - Add worker badge
  formatting
- `backend/static/css/app.css:648-662` - Add badge CSS styles

**Design**:
- Format: `[worker-0]` prefix before log message
- Color-coded badges (different color per worker)
- Clickable to filter by that worker

**Interaction**:
- Clicking a badge sets the Worker filter to that worker; provide a clear
  way to reset.
- When `worker_id` is missing, show a neutral label (e.g., "Unknown") and
  include it in filters.

**Estimated effort**: Small

#### 2.22.5: Per-worker log tabs (Optional, Future)

**Description**: Tab-based interface showing logs per worker plus
"All Workers" view.

**Files to modify**:
- `backend/templates/pages/dashboard.html` - Add tab UI
- `backend/static/js/dashboard/logs.js` - Per-tab log buffers
- `backend/static/js/dashboard/state.js` - Tab state management

**Estimated effort**: Medium

**Status**: Deferred (evaluate after 2.22.1-2.22.4)

## Implementation Order

Recommended sequence:

1. **2.22.1** (worker_id in events) - Foundation for all other improvements
2. **2.22.4** (worker badges) - Immediate visual improvement
3. **2.22.2** (level filtering) - Reduces noise
4. **2.22.3** (verbose mode) - Power user feature
5. **2.22.5** (per-worker tabs) - Future enhancement if needed

## Performance Guardrails

- Consider tracking and surfacing log drops if queue overflows (counter
  and UI indicator).
- Guard against verbose mode increasing drop rate; document expected
  behavior under load.

## Information Streaming Assessment

| Aspect | Current | After Improvements |
|--------|---------|-------------------|
| Volume | All logs (no filtering) | Filterable by level |
| Filtering location | Client only | Client + optional server |
| Worker Context | Missing from events | Clear worker badges |
| Verbosity | INFO+ default | Toggle for DEBUG |
| Identification | Logger name only | Worker ID + logger |

## Testing and Validation

- [ ] Multi-worker run: `worker_id` appears in events and UI for each
  worker.
- [ ] Log level filtering matches expected ordering
  (DEBUG < INFO < WARNING < ERROR).
- [ ] Verbose mode toggles logger formatting and respects the chosen
  filter behavior.
- [ ] Worker badge click applies the Worker filter and can be cleared.
- [ ] Historical logs without `WORKER_ID` render with a neutral label and
  are filterable.
- [ ] No regression in log delivery under comparable load (use drop
  counter if available).

## Rollout and Migration

- Ship backend `worker_id` first; UI must handle missing values until all
  services are updated.
- If `WORKER_ID` is added, define migration and backfill policy;
  document whether historical rows remain NULL.
- Consider feature-flagging verbose mode and filters until both sides are
  deployed.

## Success Criteria

- [ ] Users can identify which worker generated each log line (or the
  canonical non-worker label)
- [ ] Users can filter logs by severity level
- [ ] Users can toggle verbose mode for debugging
- [ ] Worker badges are color-coded and clickable
- [ ] Filters behave consistently when `worker_id` is missing or unknown
- [ ] Verbose mode does not override user-selected filters unless
  explicitly defined
- [ ] No performance regression in log streaming

## Related Documents

- [../log-streaming-architecture.md](../log-streaming-architecture.md) -
  Current architecture
- [phase-2-checklist.md](phase-2-checklist.md) - Phase 2 tasks (2.1-2.21)
- [../metrics-streaming-debug.md](../metrics-streaming-debug.md) -
  Similar streaming pattern
