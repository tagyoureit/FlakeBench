# Architecture Overview (Current)

Last updated: 2026-01-18

## System Purpose

Unistore Benchmark is a FastAPI app that benchmarks existing Snowflake and
Postgres-family tables. It runs controlled workloads, captures app-side
latency and throughput, and persists results to Snowflake.

## Runtime Topology

- Single FastAPI process (`backend/main.py`).
- WebSocket endpoint for live metrics streaming: `/ws/test/{test_id}`.
- Snowflake is the authoritative results store.
- Postgres connections are optional and used only for Postgres-family tests.

## High-Level Components

- UI (Jinja2 + Alpine.js + Chart.js) in `backend/templates/` and
  `backend/static/`.
- Execution orchestration in `backend/core/test_registry.py` and
  `backend/core/test_executor.py`.
- Persistence in `backend/core/results_store.py`.
- Templates stored in Snowflake (`UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES`).

## Key Constraints

- No table creation or DDL execution at runtime.
- Results schema is maintained via rerunnable DDL in `sql/schema/`.
- No migration framework exists in this repository.
