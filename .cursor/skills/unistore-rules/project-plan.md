# Unistore Benchmark - Current Architecture and Status

This document describes the implemented architecture and the current runtime
behavior of the project. It is intentionally factual and avoids roadmap
speculation.

## Purpose

Unistore Benchmark is a FastAPI application that benchmarks existing
Snowflake (STANDARD, HYBRID, INTERACTIVE) and Postgres-family tables by
running controlled workloads and storing detailed results in Snowflake.

## Runtime Topology

- Single FastAPI process (`backend/main.py`).
- WebSocket endpoint for live metrics streaming.
- Snowflake is the authoritative results store.
- Optional Postgres connections are supported for Postgres-family tests.

There is no packaging layer (no desktop app bundle) and no container
deployment in this codebase.

## Core Components

### Entry Point

- `backend/main.py` wires routes, templates, static files, and WebSocket
  streaming. Root route is `/templates`.

### Execution Orchestration

- `backend/core/test_registry.py`
  - Manages prepared/running tests, pubsub to WebSocket subscribers,
    and persistence hooks.
  - Runs tests from stored templates (`TEST_TEMPLATES`) and exposes
    lifecycle controls (start/stop).
- `backend/core/test_executor.py`
  - Executes the workload, collects app-level metrics and per-query
    execution records, and emits live metrics payloads.
  - Supports load modes: `CONCURRENCY`, `QPS`, `FIND_MAX_CONCURRENCY`.

### Table Managers (No DDL)

- `backend/core/table_managers/*`
  - Table creation and teardown are disabled.
  - Tests run against existing tables or views only.
  - Schema is validated and introspected at runtime.

### Metrics and Persistence

- `backend/core/metrics_collector.py`
  - App-level metrics aggregation (QPS, latency, error rates, throughput).
- `backend/core/results_store.py`
  - Writes to `UNISTORE_BENCHMARK.TEST_RESULTS.*` tables.
  - Persists test start, time-series snapshots, query executions, and
    final aggregates.
  - Optional enrichment from `INFORMATION_SCHEMA.QUERY_HISTORY`.

### Templates

- Templates are stored in Snowflake:
  `UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES`.
- YAML templates in `config/test_scenarios/` are reference examples only.
- `backend/core/template_loader.py` supports loading YAML when used
  programmatically, but the UI consumes Snowflake templates.

## User Interface (Pages)

All pages are server-rendered with Jinja2; Alpine.js manages client state,
Chart.js renders charts, and HTMX is used for partial loads.

- `/templates` (root) - template list and actions.
- `/configure` - create/edit template (writes to Snowflake).
- `/dashboard` and `/dashboard/{test_id}` - live metrics view.
- `/dashboard/history/{test_id}` - read-only analysis view.
- `/dashboard/history/{test_id}/data` - query execution drilldown.
- `/history` - search, filter, and compare results (comparison is integrated).
- `/history/compare?ids=<id1>,<id2>` - deep comparison view.
- `/comparison` - redirects to `/history`.

## API Surface (Selected)

- `/api/templates/*` - CRUD for templates in Snowflake.
- `/api/tests/*` - start/stop runs, history, search, and drilldown.
- `/api/warehouses/*`, `/api/catalog/*` - Snowflake metadata helpers.
- `/ws/test/{test_id}` - live metrics stream for dashboards.

## Data Stores

### Snowflake (Results)

- DDL is defined in `sql/schema/results_tables.sql`.
- Objects live in `UNISTORE_BENCHMARK.TEST_RESULTS`.
- DDL is rerunnable using `CREATE OR ALTER`.
- There are no migration scripts.

### Postgres (Optional)

- Used only for Postgres-family benchmarks.
- Connection pooling is managed in `backend/connectors/postgres_pool.py`.

## Constraints and Non-Goals (Current)

- No table creation, DDL, or migration logic in the app.
- No desktop packaging or cloud deployment automation.
- No workload generator framework beyond current executor behavior.
- No separate comparison page; comparisons are in `/history`.

## Testing (Current)

Tests live in `tests/` and focus on:

- Connectors (`tests/test_connection_pools.py`)
- Table managers (`tests/test_table_managers.py`)
- Metrics collector (`tests/test_metrics_collector.py`)
- Executor behaviors (`tests/test_executor.py`)
- Template normalization (`tests/test_template_custom_workloads.py`)
- App setup (`tests/test_app_setup.py`)
