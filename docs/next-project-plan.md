# Project Plan (Proposed Multi-Node)

This document outlines the transition plan to the new multi-node architecture.
It is intentionally duplicative for standalone use.

## Terminology

- **WORKER_ID**: Unique identifier for a worker process (string, e.g., `worker-0`)
- **WORKER_GROUP_ID**: Zero-based index for deterministic sharding (integer)
- **TARGET_CONNECTIONS**: Number of concurrent queries a worker should maintain
- **Warmup**: Run-level phase to prime Snowflake compute (not per-worker)

## Phase 1: Foundation (Current)

- [x] Basic controller and worker implementation.
- [x] Initial templates and workload generation.
- [x] Snowflake persistence for results.

## Phase 2: Architecture Hardening (Next)

**Goal**: Unify single/multi-node paths and establish authoritative state.

**Prerequisites**:
- Snowflake Enterprise Edition (required for Hybrid Tables)
- AWS or Azure commercial region (Hybrid Tables not available on GCP)

**Schema Layout**:
- `UNISTORE_BENCHMARK.TEST_RESULTS`: all running tests, results, and control-plane
  state.
- `UNISTORE_BENCHMARK.CONFIG`: templates and scenario config.

**Tasks**:

- [ ] **Control Tables**: Create `RUN_STATUS`, `RUN_CONTROL_EVENTS`,
  `WORKER_HEARTBEATS` as Hybrid Tables.
  - [ ] **Prepare SQL**: Verify `sql/schema/control_tables.sql` and
    `sql/schema/results_tables.sql` include all required columns before applying
    (update only if missing):
    - `WAREHOUSE_POLL_SNAPSHOTS`
    - `FIND_MAX_STEP_HISTORY`
    - `RUN_STATUS.FIND_MAX_STATE` (VARIANT)
    - `WORKER_METRICS_SNAPSHOTS.PHASE` (worker phase)
  - [ ] **Apply Schema**: Run `sql/schema/control_tables.sql` and
    `sql/schema/results_tables.sql`.
  - [ ] **Verify**: Check `SHOW HYBRID TABLES` and `DESCRIBE TABLE` for all
    columns.
  - *Note on Migration*: For future schema changes on Hybrid Tables, use the
    RENAME + CREATE + COPY pattern. Example:

    ```sql
    ALTER TABLE x RENAME TO x_backup;
    CREATE TABLE x ...;
    INSERT INTO x SELECT ... FROM x_backup;
    ```

- [ ] **Replace autoscale.py with OrchestratorService**:
  - [ ] Move subprocess spawning from `autoscale._run_autoscale()` to `OrchestratorService.start_run()`
  - [ ] Add `WorkerSpawner` abstraction with `uv` preferred and `python` fallback (local)
  - [ ] Move guardrail logic from `autoscale._guardrails_ok()` to `OrchestratorService._poll_loop()`
  - [ ] Implement `OrchestratorService.stop_run()` to write STOP events to `RUN_CONTROL_EVENTS`
  - [ ] Update API routes to use `OrchestratorService` instead of `autoscale`
  - [ ] Controller calls `OrchestratorService` directly (in-process) for create/start/stop
  - [ ] Update `OrchestratorService.start_run()` to emit `START` event to `RUN_CONTROL_EVENTS`.
  - [ ] Delete `backend/core/autoscale.py` after migration

- [ ] **Worker STOP Polling**: Update `scripts/run_worker.py`:
  - [ ] Update CLI arguments to accept `--run-id`, `--worker-id`, `--group-id`.
  - [ ] Add watchdog loop that polls `RUN_CONTROL_EVENTS` every 1s for STOP,
    `SET_PHASE`, and `SET_WORKER_TARGET` events (ordered by `SEQUENCE_ID`).
  - [ ] Add watchdog check for `RUN_STATUS` (terminal state or staleness) per
    `next-data-flow-and-lifecycle.md`.
  - [ ] Implement self-termination on STOP event or 60s connection failure
  - [ ] Add heartbeat writes to `WORKER_HEARTBEATS`

- [ ] **Unified Path**: Refactor single-node runs to use the Orchestrator (N=1).
  - All runs go through `OrchestratorService`, even with one worker

- [ ] **Aggregation**: Update Controller to aggregate from Snowflake snapshots only.
  - Remove in-memory registry fallback for parent runs
- [ ] **Warehouse Poller Persistence**: Add `WAREHOUSE_POLL_SNAPSHOTS` and use
  it for MCW live/history fallback when query history lags.
- [ ] **Acceptance Test (Local Multi-Node)**:
  - Run `scripts/acceptance_test_multinode.py` and validate STOP propagation,
    phase transitions, and `RUN_STATUS` updates under load.
- [ ] **WebSocket Schema**:
  - Implement unified payload structure with `run` + `workers` shape.
- [ ] **Find Max Control State**: Add `RUN_STATUS.FIND_MAX_STATE` and
  `FIND_MAX_STEP_HISTORY`. Emit per-worker `SET_WORKER_TARGET` events with
  explicit targets.

### Phase 2 Control-Plane Decisions (Internal Orchestrator Only)

- **Ownership**: Orchestrator owns `RUN_STATUS` and the parent `TEST_RESULTS`
  row. The controller is the API entrypoint and calls the orchestrator directly.
- **Invocation**: Direct async method calls (no internal HTTP/RPC) with a
  per-run background poll loop.
- **Event Ordering**: `RUN_CONTROL_EVENTS.SEQUENCE_ID` is monotonic per `RUN_ID`.
  Workers track the last seen sequence and process events in order.
- **Event Scoping**: `RUN_CONTROL_EVENTS.EVENT_DATA.scope` is one of `RUN`,
  `WORKER_GROUP`, or `WORKER`. `START`, `STOP`, `SET_PHASE` use `RUN` scope.
  Per-worker target updates use `WORKER` scope and include explicit targets.
- **Snapshot Cadence**: Workers write `WORKER_METRICS_SNAPSHOTS` every 1s; the
  controller aggregates on a 1s tick. Warehouse polling remains 5s.
- **Target Allocation**: For total delta changes, distribute evenly across
  workers using `WORKER_GROUP_ID` order: base = floor(delta / N), remainder
  distributed to lowest group IDs. Scale-down uses the same rule.
- **API Contract**: `POST /api/runs` creates a PREPARED run, `POST /api/runs/{run_id}/start`
  starts it, `POST /api/runs/{run_id}/stop` requests STOP. Controller does not
  make per-worker API calls; worker commands are broadcast via `RUN_CONTROL_EVENTS`.

### 2.13 (Deleted - Merged into 2.1)

### 2.14 Latency Aggregation Documentation
- [ ] **Document worst-worker approximation**: Ensure all UI/API code uses
  MAX(worker_p95) for aggregate P95/P99 and AVG(worker_p50) for P50.
- [ ] **Update WebSocket payload**: Add `latency_aggregation_method` field to
  indicate approximation in use.
- [ ] **Add UI tooltip**: Display "P95/P99 = worst worker (conservative)" on
  live dashboard latency cards.

## Phase 2 Detailed Checklist (Implementation-Level)

This checklist expands Phase 2 into concrete, verifiable tasks. Complete all
items before starting Phase 3.

### 2.1 Control Tables & Schema
- Apply `sql/schema/control_tables.sql` and verify all Hybrid Tables exist.
- Apply `sql/schema/results_tables.sql` to create new results tables.
- Confirm `RUN_STATUS` has `find_max_state` column.
- Confirm `WORKER_METRICS_SNAPSHOTS` has `PHASE` column (worker phase).
- Confirm `WAREHOUSE_POLL_SNAPSHOTS` and `FIND_MAX_STEP_HISTORY` exist.
Acceptance:
- `SHOW HYBRID TABLES` lists all control tables.
- `DESCRIBE TABLE` output matches expected columns for all new/modified tables.
- New parent runs persist correctly in `TEST_RESULTS`.

### 2.2 OrchestratorService: Create/Prepare
- Implement `create_run` to insert `RUN_STATUS` with `STATUS=PREPARED` and
  `PHASE=PREPARING`.
- Persist the template/config snapshot into `RUN_STATUS.SCENARIO_CONFIG`.
- Insert parent `TEST_RESULTS` row (`TEST_ID=RUN_ID`) with `STATUS=PREPARED`.
Acceptance:
- Creating a run produces both `RUN_STATUS` and parent `TEST_RESULTS` rows.

### 2.3 OrchestratorService: Start
- Update `RUN_STATUS` to `RUNNING` and set `START_TIME` if null.
- Record expected worker counts in `RUN_STATUS`.
- Emit `START` event to `RUN_CONTROL_EVENTS` to unblock workers.
- Spawn workers using `WorkerSpawner` abstraction (allows switching between
  Local subprocesses and SPCS).
Acceptance:
- `RUN_STATUS` shows `RUNNING` and correct expected worker counts.
- `RUN_CONTROL_EVENTS` contains a `START` event.
- Workers are launched with deterministic `WORKER_GROUP_ID`.

### 2.4 Worker Registration & Start Gate
- Update `run_worker.py` to accept `--run-id`, `--worker-id`, `--worker-group-id`,
  `--worker-group-count` args.
- On worker start, upsert `WORKER_HEARTBEATS` with `STATUS=STARTING`.
- Worker startup logic:
  1. Load `SCENARIO_CONFIG` and compute initial `TARGET_CONNECTIONS`.
  2. Check `RUN_STATUS`: if `RUNNING`, start immediately in current phase.
  3. If `PREPARED`, poll `RUN_CONTROL_EVENTS` for START event (ordered by `SEQUENCE_ID`).
  4. Determine initial phase from `RUN_STATUS.PHASE`:
     - If `WARMUP`: participate in warmup.
     - If `MEASUREMENT`: skip warmup (Snowflake already primed).
  5. Watch for `SET_PHASE` and `SET_WORKER_TARGET` events (event-driven),
     fall back to `RUN_STATUS` columns if missed.
- Worker polls `RUN_STATUS` for terminal states (COMPLETED/FAILED) or staleness
  (Orchestrator death).
- On START, worker creates child `TEST_RESULTS` row, transitions to `RUNNING`
  status, and begins load generation.
Acceptance:
- `WORKER_HEARTBEATS` contains STARTING then RUNNING status transitions.
- Workers start correctly even if `START` event was emitted before they polled
  (race condition fix).
- Workers self-terminate if `RUN_STATUS` indicates completion or staleness.
- Workers joining after warmup start directly in MEASUREMENT phase.

### 2.5 Orchestrator Poll Loop (Control Plane)
- Heartbeat scan: mark workers `STALE`/`DEAD` based on thresholds.
- Aggregate metrics from latest `WORKER_METRICS_SNAPSHOTS` (filter to MEASUREMENT phase).
- Update `RUN_STATUS` with rollup metrics and `UPDATED_AT`.
- Manage phase transitions (`WARMUP -> MEASUREMENT`) based on `warmup_seconds`.
- STOP scheduling based on `duration_seconds`.
- Use adaptive cadence: only recompute rollups on snapshot/state changes.
- Poll loop ticks every 1s; rollups update only when new snapshots arrive.
- Generate `SEQUENCE_ID` atomically via `RUN_STATUS.NEXT_SEQUENCE_ID`.
Acceptance:
- Dead workers are excluded from live aggregates.
- Rollups update only when new snapshots arrive.
- Warmup transitions to MEASUREMENT after `warmup_seconds` elapsed.

### 2.6 STOP Semantics (Two-Phase)
- Insert STOP event in `RUN_CONTROL_EVENTS` and set `RUN_STATUS=CANCELLING`.
- Workers stop accepting new work and drain in-flight queries.
- Enforce a timeout; if exceeded, force termination and mark the run
  `CANCELLED` with reason recorded in logs.
Acceptance:
- STOP propagates to workers within target latency.
- Parent status transitions to `CANCELLED` appropriately.

### 2.7 Aggregation & Parent Rollups
- Define parent aggregation query for counts/QPS/latency percentiles.
- Live aggregation excludes dead workers; final rollup includes all workers.
- Orchestrator writes parent `TEST_RESULTS` rollups at milestones.
- Persist controller warehouse poller samples to `WAREHOUSE_POLL_SNAPSHOTS` for
  MCW history and fallback.
Acceptance:
- History view matches full aggregate from all workers after completion.

### 2.8 Controller API Contract
- For parent runs, source status/phase/timing from `RUN_STATUS` only.
- Remove in-memory registry fallback for parent responses.
- Keep child run responses scoped to per-worker data.
- Run control endpoints:
  - `POST /api/runs` -> create PREPARED run (returns `run_id`)
  - `POST /api/runs/{run_id}/start` -> invoke orchestrator `start_run`
  - `POST /api/runs/{run_id}/stop` -> invoke orchestrator `stop_run`
- Controller never issues per-worker API calls; worker commands are written to
  `RUN_CONTROL_EVENTS`.
Acceptance:
- Parent API responses no longer depend on registry state.

### 2.9 UI Contract
- Implement unified payload structure with `run` + `workers` shape.
- Implement worker grid and inline per-worker detail panels (KPIs + tables/charts).
- MCW Active Clusters (real-time) uses the controller warehouse poller.
- Find Max live panel uses controller-owned step state.
- Find Max control events use `SET_WORKER_TARGET`, with live state in
  `RUN_STATUS.FIND_MAX_STATE` and history in `FIND_MAX_STEP_HISTORY`.
Acceptance:
- Worker grid shows health states and inline detail sections render.

### 2.10 Scaling & Sharding
- Validate fixed concurrency vs fixed rate behavior per worker.
- Ensure deterministic sharding via `WORKER_GROUP_ID`.
- Persist worker group metadata into snapshots for auditability.
- Target allocation for uneven deltas:
  - Compute base = floor(abs(delta) / worker_count)
  - Remainder distributed to lowest `WORKER_GROUP_ID` in order
  - Apply negative deltas symmetrically; never drop below `min_connections`
Acceptance:
- Sharding remains stable when scaling N up/down.

### 2.11 Ops & Runbooks
- Add `/health` endpoints for controller/orchestrator.
- Implement fail-fast checks: DB connectivity, schema existence, template validity.
- Execute local multi-worker acceptance run with STOP propagation checks.
Acceptance:
- Fail-fast prevents partial runs.
- Local runbook passes consistently.

### 2.12 Legacy Removal
- Remove legacy UI paths.
- Treat legacy runs as out of scope for the UI.
Acceptance:
- UI renders unified payload and parent-run aggregates.

## Traceability Matrix (next-* Docs -> Plan Tasks)

- `next-architecture-overview.md`: 2.2, 2.3, 2.7, 2.8
- `next-orchestrator-spec.md`: 2.2, 2.3, 2.4, 2.5, 2.6
- `next-data-flow-and-lifecycle.md`: 2.1, 2.2, 2.5, 2.6, 2.7, 2.13, 2.14
- `next-scaling.md`: 2.10, 2.14
- `next-ui-architecture.md`: 2.9, 2.12, 2.14
- `next-operations-and-runbooks.md`: 2.11
- `next-multi-node-gap-analysis.md`: 2.5, 2.6, 2.7, 2.8, 2.9, 2.13
- `next-specifications.md`: 2.1-2.14 (implementation details, schemas, SQL,
  acceptance tests)
- `next-worker-implementation.md`: 2.4 (complete worker implementation reference)

## Phase 3: SPCS Readiness

**Goal**: Prepare for running in Snowflake Native Apps / SPCS.

- [ ] **Containerization**: Dockerfiles for Controller, Orchestrator, Worker.
- [ ] **Service Specification**: SPCS YAML definitions.
- [ ] **Image Registry**: Push workflow to Snowregistry.

## Phase 4: Advanced Scale

**Goal**: Support 20+ workers and high-throughput ingestion (5,000+ concurrent
connections).

- [ ] **Batch Ingestion**: optimize `QUERY_EXECUTIONS` inserts.
- [ ] **Distributed Coordination**: Leader election (if Orchestrator needs HA).

## Migration Strategy

### Strategy: Roll Forward

- We are **not** migrating legacy data. The schema changes for Multi-Node
  (Hybrid Tables, Parent/Child linking) are significant.
- The UI targets new runs only. Legacy runs are out of scope.

## Reiterated Constraints

- No DDL is executed at runtime.
- Schema changes are rerunnable DDL in `sql/schema/`.
- Templates remain stored in `UNISTORE_BENCHMARK.CONFIG.TEST_TEMPLATES` and
  drive all runs.
