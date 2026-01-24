# Operations and Runbooks (Current)

Last updated: 2026-01-21

This document is a practical map of the **entrypoints, scripts, and commands**
used to run and validate Unistore Benchmark.

It is intentionally factual (not a roadmap).

## Common entrypoints

### Start the app (local)

- Server: `uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000`
- Pages: start at `/` (templates)
- Health: `/health`
- API docs: `/api/docs` and `/api/redoc`

### Initialize / repair results schema

The app does **not** run DDL at runtime. Schema setup is performed out-of-band:

- Command: `uv run python -m backend.setup_schema`
- DDL sources (rerunnable): `sql/schema/`
  - `results_tables.sql` (DB+schema bootstrap + core results tables + views)
  - `templates_table.sql`
  - `template_value_pools_table.sql`
  - `test_logs_table.sql`

## Smoke checks (API-driven)

Use the Taskfile entrypoints to run short end-to-end checks through the running
server:

- `task test:variations:smoke` (short)
- `task test:variations:smoke:long` (long)
- `task test:variations:setup` (setup only)
- `task test:variations:cleanup` (cleanup only)

Notes:

- These tasks assume the app server is already running (default `BASE_URL` is
  `http://127.0.0.1:8000`).
- Smoke setup uses SnowCLI (`snow sql`) for DDL/DML in a dedicated smoke schema.

## Headless multi-worker (local orchestration)

There are two supported “headless” entrypoints for multi-process local runs:

### Worker (single worker)

- Script: `scripts/run_worker.py`
- Starts a test from a template and blocks until it finishes.
- Key flags:
  - `--template-id <id>` (required)
  - `--worker-group-id <n>` / `--worker-group-count <N>` for deterministic sharding
  - `--parent-run-id <uuid>` and `--node-id <name>` for multi-worker attribution
  - `--concurrency`, `--min-concurrency`, `--start-concurrency`, `--target-qps` overrides

### Orchestrator (N local worker processes)

- Script: `scripts/run_multi_node.py`
- Launches N worker processes and (best-effort) updates the parent aggregate at
  the end of the run.
- Key flags:
  - `--template-id <id>` (required)
  - `--node-count <N>` (required; worker count)
  - Optional overrides:
    - `--concurrency`
    - `--min-concurrency`
    - `--start-concurrency`
    - `--target-qps`

### Refresh parent aggregation (manual)

- Script: `scripts/refresh_parent_aggregate.py`
- Use when you need to recompute the parent run’s aggregate after-the-fact:
  - `uv run python scripts/refresh_parent_aggregate.py <parent_run_id>`

## Where to look for behavior

- **Routes (FastAPI)**: `backend/api/routes/` and `backend/main.py`
- **Test lifecycle + enrichment**: `backend/core/test_registry.py`
- **Workload execution**: `backend/core/test_executor.py`
- **Autoscale orchestration (UI-driven, scale-out only)**: `backend/core/autoscale.py`
- **Persistence to Snowflake**: `backend/core/results_store.py`
- **Table setup / validation (no DDL on customer objects)**:
  `backend/core/table_managers/`

See also: `docs/index.md`.
