# Data Flow and Test Lifecycle (Current)

Last updated: 2026-01-18

## Lifecycle Overview

1. Template selection (UI) or direct API call.
2. Registry prepares a test from `TEST_TEMPLATES`.
3. Test starts and executor runs workload.
4. Live metrics stream over WebSocket.
5. Results and query executions persist to Snowflake.
6. Optional enrichment from `QUERY_HISTORY`.

## Data Flow (High Level)

- UI actions -> `/api/templates/*` and `/api/tests/*`.
- Test metrics -> WebSocket (`/ws/test/{test_id}`) -> UI charts.
- Metrics snapshots -> `METRICS_SNAPSHOTS` table.
- Summary + metadata -> `TEST_RESULTS` table.
- Per-query executions -> `QUERY_EXECUTIONS` table.

## Execution Phases

- Warmup phase (if configured).
- Measurement phase (metrics reset at measurement start).
- Finalization and persistence.

## FIND_MAX_CONCURRENCY

- Step-based ramp to find max stable concurrency.
- Step history is persisted in `TEST_RESULTS.FIND_MAX_RESULT`.
- Backoff steps are recorded in step history at completion.
- QPS stability uses `qps_stability_pct` vs the previous stable step; the stop
  reason includes the threshold value when it triggers.
- Multiple backoffs are allowed when recovery is observed (bounded to 3 attempts
  per run).
