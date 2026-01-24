# Persistence and Schema (Current)

Last updated: 2026-01-18

## Authoritative Schema

- `sql/schema/results_tables.sql`
- `sql/schema/test_logs_table.sql`

These are rerunnable DDL files using `CREATE OR ALTER`.
There are no migration scripts in this repository.

## Core Tables

- `TEST_RESULTS`
  - Test summary, configuration, and derived metrics.
  - Includes `FIND_MAX_RESULT` JSON.
  - Includes `WAREHOUSE_CONFIG_SNAPSHOT` and `QUERY_TAG`.

- `METRICS_SNAPSHOTS`
  - Time-series metrics collected during tests.

- `NODE_METRICS_SNAPSHOTS`
  - Time-series metrics per worker group (multi-node parent runs).

- `QUERY_EXECUTIONS`
  - Per-query execution records and optional enrichment fields.

- `TEST_LOGS`
  - Log events for test runs.

## Enrichment

- Enrichment pulls from `INFORMATION_SCHEMA.QUERY_HISTORY` by query tag.
- Overhead percentiles are derived and stored on `TEST_RESULTS`.
