# Refined Metrics (Current Implementation)

Last updated: 2026-01-21

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

### Per-Worker Snapshots (Multi-Node Runs)

- Table: `UNISTORE_BENCHMARK.TEST_RESULTS.NODE_METRICS_SNAPSHOTS`
- One row per snapshot interval per worker group, keyed by parent_run_id +
  worker_group_id.

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
  and filters on the per-test query tag prefix
  (`unistore_benchmark:test_id=<id>%`).
- Query-history table functions return a maximum of 10,000 rows per call;
  enrichment paginates by END_TIME until it passes the test window.
- `update_test_overhead_percentiles()` computes app overhead percentiles
  and stores them on `TEST_RESULTS`.
- Per-cluster breakdown includes an "Unattributed" bucket for queries
  missing `SF_CLUSTER_NUMBER` (not enriched or no QUERY_HISTORY match).
- `QUERY_HISTORY_BY_WAREHOUSE` is an INFORMATION_SCHEMA table function
  (not ACCOUNT_USAGE) and can be used for same-day inspection when
  account_usage latency is too slow. Docs:
  <https://docs.snowflake.com/en/sql-reference/functions/query_history>
- Hybrid workloads: Snowflake may not emit per-query rows for short,
  high-frequency hybrid-only operations in QUERY_HISTORY/QUERY_HISTORY_BY_WAREHOUSE.
  Use AGGREGATE_QUERY_HISTORY for hybrid workload monitoring. Docs:
  <https://docs.snowflake.com/en/user-guide/tables-hybrid-monitor-workload>

### Enrichment Timeout and Scaling

- Default: max 50 pages (500k queries max), adaptive timeout based on query count.
- Adaptive timeout formula: `min(120 + (query_count // 1000), 900)` seconds.
- For high-QPS tests (>100k queries), enrichment may take 10-15 minutes.
- Stall detection: if 3 consecutive attempts show no progress and ratio > 50%,
  enrichment stops early (hybrid workload indicator).
- Dashboard polls `/api/tests/{test_id}/enrichment-status` every 5s during PENDING
  to show progress (enriched_queries / total_queries).

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

## Aggregation and SLO Notes (Multi-Node)

- Aggregated parent metrics are derived from per-worker snapshots.
- Avoid weighted averages for SLO decisions; they can hide slow workers or tails.
- For SLO latency, prefer merged distributions or worst-worker p95/p99.
- Parent runs are identified by `TEST_ID == RUN_ID`; children have `TEST_ID != RUN_ID`.
- The dashboard displays "(averaged across all workers)" for Resources in parent
  runs to clarify the data is aggregated from `NODE_METRICS_SNAPSHOTS`.

## Constraints

- No DDL/migrations are executed by the app.
- All schema changes are done via rerunnable DDL files in `sql/schema/`.
