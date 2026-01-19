# Refined Metrics (Current Implementation)

Last updated: 2026-01-18

This document describes what the app captures today and where those metrics
are stored. It avoids speculative additions.

## Live Metrics (In-Memory + WebSocket)

The executor emits live metrics using the `backend/models/metrics.py` schema
and streams them via `/ws/test/{test_id}`.

Key live metrics include:

- QPS (current, average, peak)
- Read/write counts and latency percentiles
- Overall latency percentiles (p50/p95/p99)
- Error counts and error rate
- Throughput (bytes/sec, rows/sec)
- Target worker count (for `QPS` and `FIND_MAX_CONCURRENCY`)

## Persistent Storage (Snowflake)

### Results Summary

- Table: `UNISTORE_BENCHMARK.TEST_RESULTS.TEST_RESULTS`
- Summary fields include:
  - Test metadata, status, timing
  - Read/write and per-kind latency percentiles
  - App overhead percentiles (derived after enrichment)
  - `find_max_result` JSON for `FIND_MAX_CONCURRENCY`
  - `warehouse_config_snapshot` and `query_tag`

### Time-Series Snapshots

- Table: `UNISTORE_BENCHMARK.TEST_RESULTS.METRICS_SNAPSHOTS`
- One row per snapshot interval with QPS, latency, counts, throughput,
  active connections, and custom metrics.

### Per-Query Executions

- Table: `UNISTORE_BENCHMARK.TEST_RESULTS.QUERY_EXECUTIONS`
- Captured at execution time:
  - query_id, query_text, start/end, duration
  - query_kind, worker_id, warmup flag
  - app_elapsed_ms (end-to-end latency)
  - rows_affected, bytes_scanned
  - connection_id and custom_metadata
- Enriched fields (post-run):
  - SF timing and queueing columns from `INFORMATION_SCHEMA.QUERY_HISTORY`
  - APP_OVERHEAD_MS (app_elapsed_ms - sf_total_elapsed_ms)

### Test Logs

- Table: `UNISTORE_BENCHMARK.TEST_RESULTS.TEST_LOGS`
- Inserted by `insert_test_logs()` in `backend/core/results_store.py`.
- DDL is in `sql/schema/test_logs_table.sql`.

## Post-Run Enrichment

- `enrich_query_executions_from_query_history()` merges
  `INFORMATION_SCHEMA.QUERY_HISTORY` into `QUERY_EXECUTIONS` by QUERY_ID
  and filters on the `unistore_benchmark%` query tag prefix.
- `update_test_overhead_percentiles()` computes app overhead percentiles
  and stores them on `TEST_RESULTS`.

## What Must Be Captured During the Test

These cannot be reliably reconstructed later and are captured by the app:

- End-to-end latency (app_elapsed_ms)
- Query kind (POINT_LOOKUP, RANGE_SCAN, INSERT, UPDATE)
- Query text
- Start/end timestamps
- Worker id and warmup flag

## What Can Be Enriched After the Test

From `INFORMATION_SCHEMA.QUERY_HISTORY`:

- Snowflake execution time and queueing breakdowns
- Bytes scanned and rows produced
- Cluster number (for MCW analysis)

## Constraints

- No DDL/migrations are executed by the app.
- All schema changes are done via rerunnable DDL files in `sql/schema/`.
