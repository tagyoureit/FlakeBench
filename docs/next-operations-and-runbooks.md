# Operations and Runbooks (Proposed Multi-Node)

This document describes target operational flows for multi-node runs.
It is intentionally duplicative for standalone use.

## Local Runbook (Target)

1. Start the **controller** (FastAPI app).
2. Orchestrator runs as an **embedded task** in Phase 2 and launches N workers
   (subprocesses or local processes).
3. Controller streams aggregate metrics from Snowflake.

Phase 3+ (SPCS prep): Orchestrator runs as a separate service/process.

Local entrypoints (existing references):

- `scripts/run_worker.py` (single worker)
- `scripts/run_multi_node.py` (N local workers)

## Single-Node Runbook (Target)

1. Start the **controller** (FastAPI app).
2. Orchestrator runs as an **embedded task** in Phase 2.
3. Orchestrator launches one worker (N=1) and creates a parent run.
4. UI reads parent state and aggregate metrics (from one worker).

## SPCS Runbook (Target)

### Service roles

- Controller: long-running service
- Orchestrator: long-running service or job controller
- Workers: job services (one per worker) or short-lived services

### Steps (high level)

1. Build OCI images for controller, orchestrator, and worker.
2. Deploy controller and orchestrator services to a compute pool.
3. Orchestrator launches worker job services for each worker.
4. Workers write metrics and query executions to Snowflake.
5. Controller reads authoritative state and aggregated metrics.

### Environment Parity

To prevent "works on my machine" issues, we must enforce strict environment
parity between Local and SPCS:
- **Container-First**: Even local development should ideally run workers in
  containers (Docker), or strictly pin dependencies via `uv.lock`.
- **Driver Versions**: The Snowflake Python Connector version must be identical
  in the `Dockerfile` and the local `pyproject.toml`.

## Health and Observability

- Every service exposes a `/health` endpoint.
- Logs are written to stdout/stderr for platform collection.
- Orchestrator persists STOP signals to Snowflake for workers.

### Startup Health Check (Fail Fast)

The Orchestrator implements a "Fail Fast" check before launching workers:
1. **DB Check**: Verify connection to Snowflake.
2. **Schema Check**: Verify `RUN_STATUS` and `TEST_RESULTS` tables exist.
3. **Template Check**: Verify the requested `template_id` exists and is valid
   in `UNISTORE_BENCHMARK.CONFIG.TEST_TEMPLATES`.

If any check fails, the run is aborted immediately with a clear error message,
preventing partial/zombie runs.

## Validation (Target)

Local acceptance checklist for multi-node correctness:

1. Start controller and orchestrator.
2. Launch a local multi-worker run via `scripts/acceptance_test_multinode.py`.
3. Issue STOP from the UI (or API) and confirm:
   - STOP event appears in `RUN_CONTROL_EVENTS`.
   - `RUN_STATUS` transitions to `CANCELLING` and then `CANCELLED`.
4. Verify all worker processes exit and the parent `TEST_RESULTS` rollup updates.

## Reiterated Constraints

- No DDL is executed at runtime.
- Schema changes are rerunnable DDL in `sql/schema/`.
- Templates remain stored in `UNISTORE_BENCHMARK.CONFIG.TEST_TEMPLATES` and
  drive all runs.
