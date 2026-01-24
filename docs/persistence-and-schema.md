# Persistence and Schema (Current)

Last updated: 2026-01-21

## Authoritative Schema

- `sql/schema/results_tables.sql`
  - Creates `UNISTORE_BENCHMARK` + `TEST_RESULTS` schema (rerunnable bootstrap).
  - Creates core results tables and several convenience views.
  - Uses `CREATE OR ALTER` for idempotent DDL.
- `sql/schema/templates_table.sql`
  - Creates `TEST_TEMPLATES` (template store used by the UI).
  - Preset workload types are UI convenience defaults; the backend normalizes
    them to CUSTOM on save (see `backend/api/routes/templates.py`).
- `sql/schema/template_value_pools_table.sql`
  - Creates `TEMPLATE_VALUE_POOLS` (large sampled pools for high concurrency).
- `sql/schema/test_logs_table.sql`
  - Creates `TEST_LOGS` (per-test log events).

These schema files are rerunnable (idempotent). There is no migrations system
in this repository.

## How the schema is applied

- `backend/setup_schema.py` executes the schema SQL files (in order).
- Run it manually when bootstrapping or repairing the results store:
  - `uv run python -m backend.setup_schema`
- The FastAPI app does **not** execute DDL at runtime.

## Core Tables

- `TEST_RESULTS`
  - Test summary, configuration, and derived metrics.
  - Includes `FIND_MAX_RESULT` JSON.
  - Includes `WAREHOUSE_CONFIG_SNAPSHOT` and `QUERY_TAG`.

- `METRICS_SNAPSHOTS`
  - Time-series metrics collected during tests.

- `NODE_METRICS_SNAPSHOTS`
  - Time-series metrics per worker group (multi-worker parent runs).

- `QUERY_EXECUTIONS`
  - Per-query execution records and optional enrichment fields.

- `TEST_LOGS`
  - Log events for test runs.

## Template Storage Tables

- `TEST_TEMPLATES`
  - Authoritative template store (Snowflake).
  - Consumed by the UI and `backend/core/test_registry.py` for runs.
- `TEMPLATE_VALUE_POOLS`
  - Optional large sampled pools generated during template creation/prep.
  - Keeps `TEST_TEMPLATES.CONFIG` small while enabling massive scale runs.

## Views (results schema)

Views are defined in `sql/schema/results_tables.sql` for convenience:

- `V_LATEST_TEST_RESULTS`
- `V_METRICS_BY_MINUTE`
- `V_WAREHOUSE_METRICS`
- `V_CLUSTER_BREAKDOWN`
- `V_WAREHOUSE_TIMESERIES`

## Enrichment

- Enrichment pulls from `INFORMATION_SCHEMA.QUERY_HISTORY` by query tag.
- Overhead percentiles are derived and stored on `TEST_RESULTS`.
