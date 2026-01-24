# Multi-Node Gap Analysis and Fixes (Proposed)

This document compares the current multi-node behavior to the target design.
It is intentionally duplicative for clarity.

## Summary

The current architecture mixes control-plane and data-plane responsibilities in
the controller process. This leads to ambiguous status sources and unreliable
stop behavior. The target design separates orchestration and defines a single
authoritative state in Snowflake.

Primary concern: the current system is a **half-built architecture**. The
timer drift and stop failures are **artifacts** of incomplete control-plane
ownership and inconsistent state, not standalone defects.

## Gap 1: Status and Timing Source-of-Truth

Current:

- UI polls `/api/tests/{id}` and may receive mixed timing/phase sources
  (parent in-memory registry, parent row, child rows).

Impact:

- Phase and timers jump and regress during multi-node runs.

Fix:

- For parent runs, use Snowflake authoritative state only.
- Persist parent timing fields in a single place and update them from the
  orchestrator.
- For child runs, keep per-worker timing isolated to the child row.

## Gap 2: Stop Propagation

Current:

- Parent stop calls only affect the controller registry.
- Child workers run in separate processes and do not receive the stop signal.

Impact:

- Stop button appears to work, but workers continue running.

Fix:

- Add a persisted control channel (STOP events).
- Orchestrator writes control events; workers poll and exit.
- Controller reflects `CANCELLING` until all workers exit.

## Gap 3: Control-Plane Coupling

Current:

- Controller spawns workers via subprocesses.

Impact:

- Difficult to run in SPCS or a distributed environment.

Fix:

- Phase 2: Orchestrator runs as an embedded task to avoid ops overhead.
- Phase 3: Externalize orchestration into a separate process/service.
- Controller remains UI/API only.

## Gap 4: Aggregation Consistency

Current:

- Aggregation is derived from per-worker snapshots, but timing and status are not
  consistently sourced.

Impact:

- Aggregated metrics are correct, but UI state is inconsistent.

Fix:

- Orchestrator computes parent rollups at an adaptive cadence (only when new
  snapshots or state changes arrive).
- UI always reads aggregate data for parent runs.

## Gap 5: UI Contract for Multi-Node

Current:

- No strict contract for which fields are aggregate vs per-worker.

Impact:

- UI can accidentally mix per-worker and parent fields.

Fix:

- Define a strict UI contract:
  - Parent: aggregate metrics + per-worker status list
  - Child: per-worker metrics only

### Per-Worker Status in UI

The UI displays individual worker status via the orchestrator. The WebSocket
payload includes a `workers` array with per-worker details:

- `worker_id`, `worker_group_id` (identity)
- `phase` (WARMUP, MEASUREMENT, COMPLETED)
- `health` (HEALTHY, STALE, DEAD) derived from heartbeat age
- `qps`, `error_rate`, `cpu`, `memory` (per-worker metrics)

This allows operators to:
- See which workers are contributing to aggregates
- Identify stale or dead workers during a run
- Debug per-worker performance issues

See `next-ui-architecture.md` for the full payload schema.

## Gap 6: Single-Node Path Divergence

Current:

- Single-node runs use an in-memory registry path.
- Multi-node runs use parent/child rows and aggregation from Snowflake.

Impact:

- Two different data paths create inconsistent UI timing and stop behavior.
- Fixes for multi-node do not automatically apply to single-node.

Fix:

- Treat single-node as multi-node with a worker count of 1.
- Orchestrator always creates a parent run and starts one worker.
- UI reads parent state and aggregate metrics for all runs.

## Gap 7: Phase Model Clarification

Current:

- Workers can enter warmup and measurement at different times.
- Parent phase and aggregation do not define how to handle mixed phases.

Impact:

- Parent timing appears inconsistent because workers are out of phase.
- Aggregates can mix warmup and measurement data.

Fix:

- **Warmup is run-level**: A single warmup phase primes Snowflake compute for the
  entire run. The orchestrator controls warmup-to-measurement transition.
- Workers that start during warmup participate in warmup.
- Workers that start after warmup (e.g., QPS scale-out) begin directly in
  MEASUREMENT—they assume Snowflake is already primed.
- Require per-worker phase tags in `WORKER_METRICS_SNAPSHOTS`.
- Aggregate only workers in MEASUREMENT phase.

## Open Questions & Risks

1. **SPCS Stack**: We need to define the exact Python base image and driver
   versions supported by SPCS to ensure our local environment matches.
   *(Deferred to Phase 3)*
2. **Orchestrator HA**: The Orchestrator is a single point of failure (SPOF)
   for control of a run. If it dies, the run stops (via watchdog). For
   Phase 4, do we need HA or leader election?
3. **Cost**: High-frequency Hybrid Table updates have a cost.
   *(Future enhancement: implement credit consumption tracking in run
   summaries.)*

## Decisions (Phase 2)

- **Canonical control schema**: Align docs and code to `sql/schema/control_tables.sql`.
- **Two-phase STOP**: Graceful drain on STOP event, then forced termination after
  a configurable timeout if workers do not exit. STOP always resolves to
  `CANCELLED`.
- **Adaptive aggregation**: Compute parent rollups only when new snapshots or
  worker status changes occur.
- **Fail-fast startup**: If any worker cannot be reached during startup, the run
  fails (no partial runs).
- **UI unified payload**: Single payload structure for all runs. No legacy payload
  support.

## Concrete Fix Plan (Near-Term)

1. Make parent status authoritative
   - Update `backend/api/routes/test_results.py` to return parent timing/phase
     from Snowflake only when `TEST_ID == RUN_ID`.
   - Never merge child timing fields into parent responses.
2. Centralize stop propagation
   - Add control tables as **Hybrid Tables** in Snowflake (DDL in `sql/schema/`).
   - Use Hybrid Tables for `RUN_STATUS`, `RUN_CONTROL_EVENTS`, and
     `WORKER_HEARTBEATS` to get row-level locking and ACID transactions.
   - **Replace** `backend/core/autoscale.py` with new `OrchestratorService`:
     - Move subprocess spawning logic to `OrchestratorService.start_run()`
     - Move guardrail checking to `OrchestratorService._poll_loop()`
     - Add STOP event writing to `OrchestratorService.stop_run()`
     - Delete `autoscale.py` after migration complete
   - Update `scripts/run_worker.py` to poll STOP events and exit cleanly.
3. Align aggregation cadence
   - Update `backend/core/results_store.py` to compute parent rollups on an
     adaptive cadence (only when new snapshots or worker status changes arrive).
   - Aggregate from `WORKER_METRICS_SNAPSHOTS` (renamed from NODE_METRICS_SNAPSHOTS).
4. Lock UI to the parent contract
   - Update `backend/static/js/dashboard.js` to display only aggregate metrics
     for parent runs and show per-worker status in a separate section.
   - Implement unified payload structure with `run` + `workers` shape.
   - Inline per-worker detail panels on the parent dashboard; no child pages in
     Phase 2 (future TODO).
   - Source MCW Active Clusters from the controller warehouse poller.
   - Persist poller samples to `WAREHOUSE_POLL_SNAPSHOTS` and use as fallback
     when query history lags.
   - Redesign Find Max to use controller-owned step state (not worker-local).
   - Emit `SET_WORKER_TARGET` events with `target_connections` and store live
     state in `RUN_STATUS.FIND_MAX_STATE` plus `FIND_MAX_STEP_HISTORY`.
5. Standardize terminology
   - Use `WORKER_ID` consistently (not `NODE_ID`).
   - Use `TARGET_CONNECTIONS` for concurrent query count.
   - Rename `NODE_METRICS_SNAPSHOTS` to `WORKER_METRICS_SNAPSHOTS`.
6. Clarify warmup model
   - Warmup is run-level, not per-worker.
   - Workers joining after warmup start directly in MEASUREMENT phase.

## Control Table Design (Hybrid Tables)

> **Important**: Hybrid Tables do **NOT** support `CREATE OR ALTER` syntax.
> Use `CREATE OR REPLACE HYBRID TABLE` (drops and recreates) or
> `CREATE HYBRID TABLE IF NOT EXISTS`.
> Schema modifications require `ALTER TABLE` for supported operations (add
> column, drop column) or `DROP TABLE` + `CREATE HYBRID TABLE` for unsupported
> changes.

`RUN_STATUS`, `RUN_CONTROL_EVENTS`, and `WORKER_HEARTBEATS` are implemented as
**Hybrid Tables** to provide:

- **Row-level locking**: Multiple workers update heartbeats concurrently without
  blocking each other or the orchestrator's phase transitions.
- **ACID transactions**: No need for optimistic concurrency (conditional UPDATE
  with version checks). Updates are guaranteed consistent.
- **Enforced primary keys**: `RUN_ID` uniqueness enforced at the database level.

This is the correct Snowflake pattern for control-plane state where multiple
processes write to the same rows concurrently.

Alternative considered: Postgres for even higher concurrency writes. Deferred
unless Hybrid Table performance is insufficient for expected load (<100
concurrent workers per run).

## Reiterated Constraints

- No DDL is executed at runtime.
- Schema changes are rerunnable DDL in `sql/schema/`.
- Templates remain stored in `UNISTORE_BENCHMARK.CONFIG.TEST_TEMPLATES` and
  drive all runs.
