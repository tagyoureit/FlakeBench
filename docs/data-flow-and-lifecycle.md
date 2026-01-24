# Data Flow and Test Lifecycle (Current)

Last updated: 2026-01-21

## Lifecycle Overview

1. Template selection (UI) or direct API call.
2. Registry prepares a test from `TEST_TEMPLATES`.
3. If autoscale is enabled, a parent run is prepared first (no autostart).
4. User starts the run from the live dashboard (standard or autoscale).
5. Test starts and executor runs workload.
6. Live metrics stream over WebSocket.
7. Results and query executions persist to Snowflake.
8. Optional enrichment from `QUERY_HISTORY`.

## Data Flow (High Level)

- UI actions -> `/api/templates/*` and `/api/tests/*`.
- Test metrics -> WebSocket (`/ws/test/{test_id}`) -> UI charts.
- Metrics snapshots -> `METRICS_SNAPSHOTS` table.
- Per-worker snapshots -> `NODE_METRICS_SNAPSHOTS` table (multi-node runs only).
- Summary + metadata -> `TEST_RESULTS` table.
- Per-query executions -> `QUERY_EXECUTIONS` table.

## Autoscale State (QPS)

- For QPS autoscale runs, the parent run stores autoscale state in
  `TEST_RESULTS.CUSTOM_METRICS.autoscale_state`.
- Child workers read `autoscale_state.node_count` to split total target QPS
  across workers (`target_qps_total / node_count`).

## Execution Phases

- Warmup phase (if configured).
- Measurement phase (metrics reset at measurement start).
- Finalization and persistence.
- Multi-node aggregation (parent run derived from per-worker snapshots).

## Multi-Node Run Detection

Parent vs child runs are distinguished by comparing `TEST_ID` and `RUN_ID`:

- **Parent run**: `TEST_ID == RUN_ID` - aggregated view across all child workers.
- **Child run**: `TEST_ID != RUN_ID` - single-worker execution;
  `RUN_ID` points to parent.

The dashboard uses this logic to determine `isMultiNode` for UI display purposes:

```javascript
this.isMultiNode = !!(data && data.run_id && data.run_id === data.test_id);
```

For parent runs, the Resources section displays "(averaged across all workers)"
to indicate the data is aggregated from `NODE_METRICS_SNAPSHOTS`.

## FIND_MAX_CONCURRENCY

- Step-based ramp to find max stable concurrency.
- Step history is persisted in `TEST_RESULTS.FIND_MAX_RESULT`.
- Backoff steps are recorded in step history at completion.
- QPS stability uses `qps_stability_pct` vs the previous stable step; the stop
  reason includes the threshold value when it triggers.
- Multiple backoffs are allowed when recovery is observed (bounded to 3 attempts
  per run).

## Post-Processing Phase

After test execution completes:

1. Test is saved as COMPLETED immediately (before enrichment).
2. QUERY_EXECUTIONS are persisted to Snowflake.
3. Enrichment polls QUERY_HISTORY (45+ second latency) to merge SF timing data.
4. Dashboard shows "Post-processing in progress..." with live query count progress.
5. Enrichment completes when 90% of queries are enriched, or timeout is reached.

Timeout scaling:
- Base: 120 seconds
- Scales: +1s per 1000 queries
- Max: 900 seconds (15 minutes)
- Example: 180k queries → ~300s timeout

The `/api/tests/{test_id}/enrichment-status` endpoint provides:
- `total_queries`, `enriched_queries`, `enrichment_ratio_pct`
- `is_complete` flag (true if COMPLETED/SKIPPED or ratio >= 90%)
- Dashboard polls this every 5s during PENDING status.
