# UI Architecture (Proposed Multi-Node)

This document describes the UI contract for multi-node runs. It intentionally
repeats key constraints for clarity.

## Terminology

- **WORKER_ID**: Unique identifier for a worker process (string, e.g., `worker-0`)
- **TARGET_CONNECTIONS**: Number of concurrent queries a worker should maintain
- **Warmup**: Run-level phase to prime Snowflake compute (not per-worker)

## Display Contract

The UI is "dumb" regarding topology. It consumes a unified data shape regardless
of whether the run is single-node or multi-node.

### Data Source

- **URL**: `/ws/test/{run_id}`
- **Source**: Controller aggregates data from Snowflake authoritative state.
- **Control Path**: WebSocket is read-only. Start/stop and target changes go
  through controller APIs to the orchestrator, which writes `RUN_CONTROL_EVENTS`.
- **Frequency**:
  - **Status/Health**: 1 second updates (fast feedback for "is it alive?").
  - **Aggregate Metrics**: 1 second updates (driven by 1s snapshots; rollups
    are lightweight and use the latest snapshot).
  - **Warehouse/MCW**: 5 seconds updates from a dedicated poller.

### WebSocket Event Semantics

The controller emits a single event type on `/ws/test/{run_id}`:

```json
{
  "event": "RUN_UPDATE",
  "data": { ...payload... }
}
```

Rules:

- One `RUN_UPDATE` per second.
- Full snapshot payload; client replaces prior state (no diffs).
- WebSocket is UI-only; control commands are not sent over this channel.

## Payload Schema

The WebSocket payload is a JSON object with two top-level keys:

```json
{
  "run": {
    "run_id": "uuid",
    "status": "RUNNING",
    "phase": "MEASUREMENT",
    "worker_count": 5,
    "elapsed_seconds": 120,
    "aggregate_metrics": {
      "qps": 5000,
      "p95_latency_ms": 45.2,
      "error_rate": 0.001
    }
  },
  "workers": [
    {
      "worker_id": "worker-1",
      "health": "HEALTHY",
      "phase": "MEASUREMENT",
      "qps": 1000,
      "last_heartbeat_ago_s": 2
    },
    {
      "worker_id": "worker-2",
      "health": "DEAD",
      "phase": "WARMUP",
      "qps": 0,
      "last_heartbeat_ago_s": 65
    }
  ]
}
```

Worker freshness uses `health` (`HEALTHY`, `STALE`, `DEAD`). If we need to surface
worker lifecycle separately, use `status` for `STARTING`, `RUNNING`, `COMPLETED`.

**Note**: `TARGET_CONNECTIONS` is the orchestrator-assigned target for concurrent
queries. `ACTIVE_CONNECTIONS` is the actual count of currently executing queries.

## Payload Compatibility

- The controller emits a single unified payload structure.
- No legacy payload variants are supported.

## Component Responsibility

### Header / Status Bar
- Shows parent run status (`RUNNING`, `COMPLETED`).
- Shows phase (`WARMUP`, `MEASUREMENT`).
- Shows global elapsed time (from parent start time).

### Aggregate Metrics Cards
- QPS (sum of all workers).
- Latency (p50/p95/p99 merged from all workers).
- Error Rate (global average).

### Worker Grid (New)
- Visual grid of N boxes.
- Color-coded by health (Green=Healthy, Yellow=Stale, Red=Dead).
- Tooltip shows per-worker QPS and errors.
- Clicking a worker expands inline per-worker details (KPIs and tables/charts) on
  the parent dashboard.

### MCW Active Clusters (Real-Time)
- Sourced from the controller's warehouse poller (dedicated Snowflake pool).
- Sampled every ~5 seconds via `SHOW WAREHOUSES`.
- Persist poller samples to `WAREHOUSE_POLL_SNAPSHOTS` (append-only).
- Use the poller result directly (max/last), never sum across workers.
- Workers do not query MCW/warehouse state.

### MCW Clusters + Queue (History)
- History chart uses `/api/tests/{test_id}/warehouse-timeseries`.
- Active clusters prefer `V_WAREHOUSE_TIMESERIES.ACTIVE_CLUSTERS`.
- When query history lags, fall back to poller snapshots.
- Queue metrics come from `V_WAREHOUSE_TIMESERIES` (QUERY_EXECUTIONS).

### Find Max (Step-Load) Live Panel
- Controller-owned step controller drives all worker changes.
- UI renders a single aggregated step state for the run.
- Workers report metrics only; they never decide step transitions.
- Surface: current step, target workers, baseline vs current P95/P99, error
  rate, and stop reason.

### Worker Health Timeline (Minimal)
- A compact timeline showing counts of HEALTHY/STALE/DEAD workers over time.
- Default collapsed; expand only on demand or when non-healthy counts appear.

## Inline Worker Details (Phase 2)

Clicking a worker in the grid expands per-worker KPIs and tables/charts inline on
the parent page. No child dashboard routes are created in Phase 2.

TODO: Consider a child drilldown page after the multi-node UI stabilizes.

## Latency vs. Freshness

- **Status Updates**: Pushed every 1s. Users need immediate feedback on state
  changes (e.g., stopping).
- **Metrics Updates**: Pushed every 1s using the latest snapshots. Heavy
  persistence remains adaptive and does not run every tick.

## Reiterated Constraints

- No DDL is executed at runtime.
- Schema changes are rerunnable DDL in `sql/schema/`.
- Templates remain stored in `UNISTORE_BENCHMARK.CONFIG.TEST_TEMPLATES` and
  drive all runs.
