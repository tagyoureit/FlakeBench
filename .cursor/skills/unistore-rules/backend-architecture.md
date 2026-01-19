# Backend Architecture (Current)

Last updated: 2026-01-18

## Entry Point

- `backend/main.py`
  - Initializes FastAPI, templates, static files, and routes.
  - Root route is `/templates` (also served at `/`).

## Core Runtime

### Test Registry

- `backend/core/test_registry.py`
  - Creates and tracks running tests.
  - Publishes metrics payloads to WebSocket subscribers.
  - Coordinates persistence to Snowflake via `results_store`.

### Test Executor

- `backend/core/test_executor.py`
  - Runs workloads and maintains app-side metrics.
  - Supports load modes:
    - `CONCURRENCY` (fixed workers)
    - `QPS` (auto-adjust workers to hit app-side QPS target)
    - `FIND_MAX_CONCURRENCY` (step-load to find max sustainable workers)
  - Captures per-query execution records for persistence.

### Table Managers

- `backend/core/table_managers/*`
  - Standard/Hybrid/Interactive/Postgres managers.
  - All assume existing tables or views; creation is disabled.
  - Schema validation and profiling occur during setup.

### Connectors

- `backend/connectors/snowflake_pool.py`
- `backend/connectors/postgres_pool.py`

These provide pooled connections and health checks.

## Persistence Layer

- `backend/core/results_store.py` writes to
  `UNISTORE_BENCHMARK.TEST_RESULTS.*` tables.
- Post-run enrichment queries `INFORMATION_SCHEMA.QUERY_HISTORY`.
