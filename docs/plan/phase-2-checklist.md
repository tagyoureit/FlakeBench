# Phase 2 Detailed Checklist

Implementation-level tasks for Phase 2: Architecture Hardening.

**Status Legend**: ✅ Complete | 🟡 In Progress | ⬜ Not Started

## 2.1 Control Tables & Schema ✅

- [x] Apply `sql/schema/control_tables.sql` and verify all Hybrid Tables exist.
- [x] Apply `sql/schema/results_tables.sql` to create new results tables.
- [x] Confirm `RUN_STATUS` has `find_max_state` column.
- [x] Confirm `RUN_STATUS` has `worker_targets` and `next_sequence_id`.
- [x] Confirm `WORKER_METRICS_SNAPSHOTS` has `PHASE` column (worker phase).
- [x] Confirm `WAREHOUSE_POLL_SNAPSHOTS` and `FIND_MAX_STEP_HISTORY` exist.

**Acceptance**:
- `SHOW HYBRID TABLES` lists all control tables.
- `DESCRIBE TABLE` output matches expected columns for all new/modified tables.
- New parent runs persist correctly in `TEST_RESULTS`.

## 2.2 OrchestratorService: Create/Prepare ✅

- [x] Implement `create_run` to insert `RUN_STATUS` with `STATUS=PREPARED` and `PHASE=PREPARING`.
- [x] Persist the template/config snapshot into `RUN_STATUS.SCENARIO_CONFIG`.
- [x] Insert parent `TEST_RESULTS` row (`TEST_ID=RUN_ID`) with `STATUS=PREPARED`.

**Acceptance**:
- Creating a run produces both `RUN_STATUS` and parent `TEST_RESULTS` rows.

## 2.3 OrchestratorService: Start ✅

- [x] Update `RUN_STATUS` to `RUNNING` and set `START_TIME` if null.
- [x] Record expected worker counts in `RUN_STATUS` (done in create_run).
- [x] Emit `START` event to `RUN_CONTROL_EVENTS` to unblock workers.
- [x] Spawn workers via local subprocess (embedded, SPCS deferred to Phase 3).
- [x] Start background poll loop (minimal; full logic in 2.5).

**Acceptance**:
- `RUN_STATUS` shows `RUNNING` and correct expected worker counts.
- `RUN_CONTROL_EVENTS` contains a `START` event.
- Workers are launched with deterministic `WORKER_GROUP_ID`.

## 2.4 Worker Registration & Start Gate ✅

- [x] Update `run_worker.py` to accept `--run-id`, `--worker-id`, `--worker-group-id`, `--worker-group-count` args.
- [x] On worker start, upsert `WORKER_HEARTBEATS` with `STATUS=STARTING`.
- [x] Worker startup logic (load config, check RUN_STATUS, poll for START, determine phase).
- [x] Worker polls `RUN_STATUS` for terminal states or staleness.
- [x] On START, worker creates child `TEST_RESULTS` row, transitions to `RUNNING`.

**Acceptance**:
- `WORKER_HEARTBEATS` contains STARTING then RUNNING status transitions.
- Workers start correctly even if `START` event was emitted before they polled.
- Workers self-terminate if `RUN_STATUS` indicates completion or staleness.

## 2.5 Orchestrator Poll Loop ✅

- [x] Heartbeat scan: mark workers `STALE`/`DEAD` based on thresholds.
- [x] Aggregate metrics from latest `WORKER_METRICS_SNAPSHOTS` (filter to MEASUREMENT phase).
- [x] Update `RUN_STATUS` with rollup metrics and `UPDATED_AT`.
- [x] Manage phase transitions (`WARMUP -> MEASUREMENT`) based on `warmup_seconds`.
- [x] STOP scheduling based on `duration_seconds`.
- [x] Use adaptive cadence: only recompute rollups on snapshot/state changes.
- [x] Generate `SEQUENCE_ID` atomically via `RUN_STATUS.NEXT_SEQUENCE_ID`.
- [x] **Timezone fix**: Calculate `elapsed_seconds` in Snowflake SQL using `TIMESTAMPDIFF`.
- [x] **Terminal state transition**: Poll loop properly transitions intermediate states.

**Acceptance**:
- Dead workers are excluded from live aggregates.
- Rollups update only when new snapshots arrive.
- Warmup transitions to MEASUREMENT after `warmup_seconds` elapsed.

## 2.6 STOP Semantics (Two-Phase) ✅

- [x] Insert STOP event in `RUN_CONTROL_EVENTS` and set `RUN_STATUS=CANCELLING`.
- [x] Workers stop accepting new work and drain in-flight queries.
- [x] Enforce a timeout; if exceeded, force termination and mark the run `CANCELLED`.

**Acceptance**:
- STOP propagates to workers within target latency.
- Parent status transitions to `CANCELLED` appropriately.
- Post-STOP query count reduced to effectively 0%.

## 2.7 Aggregation & Parent Rollups ✅

- [x] Define parent aggregation query for counts/QPS/latency percentiles.
- [x] Live aggregation excludes dead workers; final rollup includes all workers.
- [x] Orchestrator writes parent `TEST_RESULTS` rollups at milestones.
- [x] Persist controller warehouse poller samples to `WAREHOUSE_POLL_SNAPSHOTS`.

**Acceptance**:
- History view matches full aggregate from all workers after completion.

## 2.8 Controller API Contract ✅

- [x] For parent runs, source status/phase/timing from `RUN_STATUS` only.
- [x] Remove in-memory registry fallback for parent responses.
- [x] Keep child run responses scoped to per-worker data.
- [x] Run control endpoints documented and implemented.
- [x] Controller never issues per-worker API calls.

**Acceptance**:
- Parent API responses no longer depend on registry state.

## 2.9 UI Contract ✅

- [x] Implement unified payload structure with `run` + `workers` shape.
- [x] Implement worker grid and inline per-worker detail panels.
- [x] MCW Active Clusters (real-time) uses the controller warehouse poller.
- [x] Find Max live panel uses controller-owned step state.
- [x] **Phase-gated polling**: Dashboard HTTP polling only runs during WARMUP and MEASUREMENT phases.
- [x] **Warehouse details endpoint**: Implemented `/api/tests/{id}/warehouse-details`.

**Acceptance**:
- Worker grid shows health states and inline detail sections render.
- No excessive API calls when viewing dashboard before test starts.

## 2.10 Scaling & Sharding ✅

- [x] Validate fixed concurrency vs fixed rate behavior per worker.
- [x] Ensure deterministic sharding via `WORKER_GROUP_ID`.
- [x] Persist worker group metadata into snapshots for auditability.

**Acceptance**:
- Sharding remains stable when scaling N up/down.

## 2.11 Manual Scaling Bounds ✅

- [x] **Scaling Config Schema**: Add `scaling` block with `mode` and bounds.
- [x] **FIXED Mode**: Exact worker × connection distribution.
- [x] **BOUNDED Mode**: Auto-scale within user-specified limits.
- [x] **Creation Validation**: Reject impossible configs.
- [x] **Runtime Detection**: Cancel QPS runs with `BOUNDS_LIMIT_REACHED`.
- [x] **FIND_MAX Clarity**: Report `BOUNDED_MAX` vs `TRUE_MAX` in results.
- [x] **UI Integration**: Rationalized scaling mode and bounds display.

**Acceptance**:
- `5×200` and `2×500` configs produce comparable throughput.
- Impossible configs rejected at creation with actionable error message.

## 2.12 Ops & Runbooks ✅

- [x] Add `/health` endpoint for the controller.
- [x] Implement fail-fast checks in `create_run` and `start_run`.
- [x] Update local multi-worker acceptance steps to a manual runbook flow.

**Acceptance**:
- Fail-fast prevents partial runs.
- Local runbook passes consistently.

## 2.13 Legacy Removal ✅

- [x] Remove legacy UI paths (card view); retain `/comparison` for V2 updates.
- [x] Remove legacy run compatibility branches.
- [x] **Assess `scripts/run_multi_worker.py`**: Deleted and removed references.
- [x] **Remove legacy worker path**: Removed `_run_worker_legacy()` and `--template-id`.

**Acceptance**:
- UI renders unified payload and parent-run aggregates.

## 2.13.1 Complete Orchestrator Migration ✅

- [x] **Migrate `/api/tests/from-template/{template_id}`**: Use orchestrator.
- [x] **Migrate `/api/tests/{test_id}/start`**: Use orchestrator.
- [x] **Migrate `/api/tests/{test_id}/rerun`**: Use orchestrator.
- [x] **Remove `test_registry.py` execution methods**: Replaced by orchestrator.
- [x] **Unify WebSocket handler**: Use `_stream_run_metrics()` for all runs.
- [x] **Remove legacy helper functions**: `_is_multi_worker_parent()` removed.
- [x] **Keep `test_registry.py` for**: Template CRUD operations only.
- [x] **Remove `isMultiWorker` branching**: Frontend code cleaned up.

**Acceptance**:
- All dashboard tests show correct elapsed time.
- Single-worker tests behave identically to multi-worker.

## 2.14 Latency Aggregation Documentation ✅

- [x] Document slowest-worker approximation.
- [x] Update WebSocket payload with `latency_aggregation_method` field.
- [x] Add UI tooltip for latency cards.

## 2.15 Enhanced Comparison ⬜

See [comparison-feature.md](comparison-feature.md) for detailed implementation tasks.

**Summary**: Multi-run selection (2-5 runs), config diff table, time alignment, chart complexity management.

## 2.16 Soft Resource Guardrails ⬜

See [soft-guardrails.md](soft-guardrails.md) for detailed implementation tasks.

**Summary**: Change CPU/memory guardrails from hard limits to soft boundaries with adaptive scaling.

## 2.17 API Performance Optimization ✅

- [x] Identify parallelizable queries.
- [x] Implement helper functions for query logic.
- [x] Use `asyncio.gather` for concurrent execution.
- [x] Handle failures gracefully.
- [x] Document the optimization.

**Performance Impact**: 4-5x improvement (7+ seconds → 0.6-1.1 seconds warm).

## 2.18 Phase Display and Timer Fixes ⚠️ Superseded

**Status**: Superseded by 2.19. See [timer-fixes.md](timer-fixes.md) for details.

## 2.19 Elapsed Time & Dashboard State Bug Fixes ✅

- [x] Prepare before Start flow implemented.
- [x] Skip WebSocket for non-running tests.
- [x] Single source of truth for elapsed (TIMESTAMPDIFF).
- [x] Reset START_TIME on run start.
- [x] Handle completed tests with stored duration.
- [x] Continuous total timer + phase timers.
- [x] Keep 2.18 frontend fixes.

See [timer-fixes.md](timer-fixes.md) for root cause analysis and implementation details.

## 2.20 Terminology Refactor: "Connections" → "Threads" ✅

- [x] Document terminology refactor.
- [x] Update UI labels in `configure.html`.
- [x] Update Load Mode dropdown options.
- [x] Reorganize form layout with Tailwind grid.
- [x] Rename model fields with backward-compatible aliases.
- [x] Update orchestrator, executor, API, frontend, YAML configs, and tests.

## 2.21 Multi-Worker Refactor Bugs 🟡

See [refactor-bugs.md](refactor-bugs.md) for detailed analysis and implementation tasks.

**Issues**:
- Issue 1: QUERY_TAG not updating (HIGH) - Fix applied
- Issue 2: Startup delay (MEDIUM) - ✅ Resolved (4s vs 60s)
- Issue 3: QPS rolling average (MEDIUM) - Fix applied
- Issue 4: WebSocket completion (MEDIUM) - ✅ Resolved
