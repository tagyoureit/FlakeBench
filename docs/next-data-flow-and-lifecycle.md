# Data Flow and Test Lifecycle (Proposed Multi-Node)

This document defines the **authoritative** lifecycle and data flow for
multi-node runs. It intentionally repeats key concepts for clarity.

## Identities and Terminology

- **Parent run**: `TEST_ID == RUN_ID`
- **Child run**: `TEST_ID != RUN_ID` and `RUN_ID` references the parent
- **Single-node run**: parent + one child (N=1) using the orchestrator path
- **WORKER_ID**: unique identifier for a worker process (string, e.g., `worker-0`)
- **WORKER_GROUP_ID**: zero-based index of the worker group for deterministic sharding
- **WORKER_GROUP_COUNT**: total worker group count for deterministic sharding
- **TARGET_CONNECTIONS**: number of concurrent queries a worker should maintain

## Authoritative State (Source of Truth)

Rule: For parent runs, the authoritative state is persisted in Snowflake.
The controller must not alternate between in-memory registry and child rows.

Recommended persisted state (stored in Snowflake, DDL defined in
`sql/schema/control_tables.sql`):

### RUN_STATUS (per parent run) - Hybrid Table

Fields (canonical to `sql/schema/control_tables.sql`):
- `RUN_ID`, `TEST_ID`
- `TEMPLATE_ID`, `TEST_NAME`, `SCENARIO_CONFIG`
- `STATUS`, `PHASE`
  - `STATUS` values: `PREPARED`, `RUNNING`, `CANCELLING`, `COMPLETED`, `FAILED`, `CANCELLED`
  - `PHASE` values: `PREPARING`, `WARMUP`, `MEASUREMENT`, `COOLDOWN`, `PROCESSING`
- `START_TIME`, `WARMUP_END_TIME`, `END_TIME`
- `TOTAL_WORKERS_EXPECTED`, `WORKERS_REGISTERED`, `WORKERS_ACTIVE`, `WORKERS_COMPLETED`
- `TOTAL_OPS`, `ERROR_COUNT`, `CURRENT_QPS`
- `WORKER_TARGETS` (VARIANT) - current TARGET_CONNECTIONS for each worker
- `NEXT_SEQUENCE_ID` (INTEGER) - monotonic counter for event ordering
- `CREATED_AT`, `UPDATED_AT`

### WORKER_TARGETS Column Schema

The `WORKER_TARGETS` VARIANT stores current targets as a fallback for missed
events:

```json
{
  "worker-0": { "target_connections": 25 },
  "worker-1": { "target_connections": 25 },
  "worker-2": { "target_connections": 24 }
}
```

Updated by orchestrator whenever it emits `SET_WORKER_TARGET` events.

### RUN_CONTROL_EVENTS (append-only control messages) - Hybrid Table

- `EVENT_ID`, `RUN_ID`, `EVENT_TYPE`, `EVENT_DATA`, `SEQUENCE_ID`, `CREATED_AT`
- `EVENT_TYPE` values: `START`, `STOP`, `SET_PHASE`, `SET_WORKER_TARGET`
- `EVENT_DATA.scope`: `RUN`, `WORKER_GROUP`, or `WORKER` (default `RUN`)
- Targeted events include `EVENT_DATA.worker_group_id` or `EVENT_DATA.worker_id`
- `SEQUENCE_ID` is monotonic per `RUN_ID`; workers process events in order

Workers and orchestrator update these records; the controller reads them for UI.

### Control Plane Processing Rules

- Workers track `last_seen_sequence` per `RUN_ID`.
- Ignore events with `SEQUENCE_ID <= last_seen_sequence`.
- Apply events based on `EVENT_DATA.scope`:
  - `RUN` -> all workers
  - `WORKER_GROUP` -> matching `worker_group_id`
  - `WORKER` -> matching `worker_id`
- `SET_WORKER_TARGET` events carry absolute targets; workers do not compute
  deltas.

### Why Hybrid Tables for Control State

`RUN_STATUS` and `RUN_CONTROL_EVENTS` use **Hybrid Tables** (not Standard Tables)
because they require:

- **Row-level locking**: Multiple workers and the orchestrator update the same
  parent run concurrently. Hybrid Tables provide row-level locking for high
  concurrency without partition or table-level blocking.
- **ACID transactions**: Orchestrator phase transitions and worker heartbeats
  must be atomic and consistent. Hybrid Tables enforce transactional semantics.
- **Enforced primary keys**: `RUN_ID` uniqueness is guaranteed by the database,
  not application logic.

This eliminates the need for optimistic concurrency patterns (conditional UPDATE
with version checks). Updates are guaranteed consistent.

## Lifecycle (Proposed)

1. Prepare
   - Controller requests a run from a template.
   - Orchestrator creates the parent run and registers expected worker groups.
2. Start
   - Orchestrator writes `RUN_STATUS=RUNNING`, emits START events.
   - Workers start and create child run rows (`TEST_RESULTS`).
3. Warmup
   - Workers emit warmup metrics and logs.
   - Orchestrator updates `PHASE=WARMUP` in parent state.
4. Measurement
   - Workers reset metrics at measurement start.
   - Orchestrator sets `PHASE=MEASUREMENT`.
5. Finalize
   - Workers persist final aggregates and query executions.
   - Orchestrator computes parent aggregates from per-worker snapshots.
6. Post-processing
   - Query history enrichment runs after completion.
   - Controller polls enrichment status for UI.

## Lifecycle Write Contract (Orchestrator-Owned)

All control-plane writes are idempotent updates to `RUN_STATUS` plus append-only
entries in `RUN_CONTROL_EVENTS`. The orchestrator also owns the parent
`TEST_RESULTS` row for rollups at key milestones.

1. Prepare
   - INSERT `RUN_STATUS` with `STATUS=PREPARED`, `PHASE=PREPARING`,
     `SCENARIO_CONFIG`, and expected worker counts.
   - INSERT parent row in `TEST_RESULTS` (`TEST_ID=RUN_ID`) with `STATUS=PREPARED`.
2. Start
   - UPDATE `RUN_STATUS` to `STATUS=RUNNING`, set `START_TIME` if null.
   - Optionally append a START event for observability.
3. Warmup
   - UPDATE `RUN_STATUS.PHASE=WARMUP`.
4. Measurement
   - UPDATE `RUN_STATUS.PHASE=MEASUREMENT`, set `WARMUP_END_TIME`.
5. Stop requested (two-phase)
   - INSERT STOP event in `RUN_CONTROL_EVENTS`.
   - UPDATE `RUN_STATUS.STATUS=CANCELLING`.
6. Finalize
   - UPDATE `RUN_STATUS.STATUS` to `COMPLETED`, `FAILED`, or `CANCELLED` and set
     `END_TIME`.
   - UPDATE parent `TEST_RESULTS` rollups from per-worker snapshots and final
     counts.

Single-node runs follow the same sequence with an expected worker count of 1.

## Phase Model (Run-Level Warmup)

**Warmup is a run-level concept**, not per-worker. The purpose of warmup is to
prime Snowflake compute resources (warehouse clusters, caches, etc.) before
measurement begins.

### Key Principles

1. **Single warmup phase**: The orchestrator controls a single warmup period for
   the entire run. When warmup ends, the run transitions to MEASUREMENT.

2. **Workers inherit run phase**: Workers that start during warmup participate in
   warmup. Workers that start after warmup (e.g., QPS scale-out) begin directly
   in MEASUREMENT phase—they assume Snowflake is already primed.

3. **No per-worker warmup**: A worker does not have its own warmup period. Its
   phase matches the run phase (with a brief sync delay).

### Phase Transitions

```
Run Phase:     PREPARING → WARMUP → MEASUREMENT → COOLDOWN → PROCESSING
Worker Phase:  (join run) → inherit run phase → follow SET_PHASE events
```

### Orchestrator Warmup Logic

```python
async def check_warmup_complete(run_id: str) -> bool:
    """
    Check if warmup should end.
    
    Criteria:
    - warmup_seconds has elapsed since RUN_STATUS.START_TIME
    - OR all initial workers have registered (fail-fast if incomplete)
    """
    run = await get_run_status(run_id)
    elapsed = (now() - run['start_time']).total_seconds()
    
    if elapsed >= run['scenario_config']['workload']['warmup_seconds']:
        return True
    
    return False
```

### Worker Phase Assignment

```python
def determine_initial_phase() -> str:
    """Worker determines its initial phase from RUN_STATUS."""
    run_phase = query_run_status_phase()
    
    if run_phase in ('WARMUP', 'MEASUREMENT'):
        return run_phase  # Inherit run phase
    else:
        # PREPARING, COOLDOWN, PROCESSING - shouldn't happen at worker start
        raise WorkerStartError(f"Cannot start worker in phase: {run_phase}")
```

### Aggregation by Phase

- Each worker writes its current phase into `WORKER_METRICS_SNAPSHOTS.PHASE`.
- Aggregation includes only workers in the **MEASUREMENT** phase.
- During warmup, aggregate metrics are suppressed or labeled "warming up".
- The UI shows a phase indicator (not per-worker phase counts).

## Heartbeat and Timing

Workers emit heartbeats on every metrics snapshot cycle. Recommended intervals:

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Heartbeat interval | 1 second | Matches metrics snapshot cadence |
| Staleness threshold | 30 seconds | 30 missed heartbeats = likely stale |
| Dead threshold | 60 seconds | Force-mark worker as dead |

Workers write `LAST_HEARTBEAT_AT` to `WORKER_METRICS_SNAPSHOTS` on every snapshot.
Orchestrator queries staleness via:

```sql
TIMESTAMPDIFF('second', MAX(TIMESTAMP), CURRENT_TIMESTAMP())
```

### Worker Auth + Heartbeat Error Handling

- Workers use the standard application credentials and maintain their own
  Snowflake connection pools.
- Heartbeats are written on the snapshot cadence. Transient write failures
  trigger exponential backoff, but workers continue attempting until the
  60-second no-connection threshold is reached.
- If a worker cannot successfully connect for >60 seconds, it exits
  (self-termination) to avoid running without control-plane visibility.

### Worker Watchdog & Self-Termination

To prevent "zombie workers" (workers running after the controller/orchestrator
has died), each worker MUST implement a strict local watchdog:

1. **Polling**: Worker polls `RUN_CONTROL_EVENTS` every 1 second.
2. **Logic**: Exit immediately on `STOP`. Exit after > 60 seconds without a
   successful Snowflake connection (assume partition). Exit if parent status
   from `RUN_STATUS` is `COMPLETED`, `FAILED`, or `CANCELLED`.

This ensures that even if the Orchestrator crashes hard (OOM, power loss) and
cannot send a STOP signal, workers will self-terminate once they detect the
control plane is unreachable or the run is dead.

### Watchdog Crash Scenarios

If the watchdog itself crashes (e.g., the entire worker process is killed by
OOM, SIGKILL, or host failure), the **orchestrator** detects this via heartbeat
staleness:

| Scenario | Detection | Resolution |
|----------|-----------|------------|
| Worker OOM/SIGKILL | No heartbeat for 60s | Mark worker DEAD |
| Host crash | No heartbeat for 60s | Mark worker DEAD |
| Partition | Conn failures + stale | Worker exits; mark DEAD |
| Orchestrator crash | Conn failures | Worker exits after 60s |

**Orchestrator-side staleness check** (runs every 1s):

```sql
SELECT
  WORKER_ID,
  TIMESTAMPDIFF('second', LAST_HEARTBEAT, CURRENT_TIMESTAMP())
    AS stale_seconds
FROM WORKER_HEARTBEATS
WHERE RUN_ID = ?
  AND TIMESTAMPDIFF('second', LAST_HEARTBEAT, CURRENT_TIMESTAMP()) > 60
```

Workers detected as stale are marked `DEAD` in `WORKER_HEARTBEATS.STATUS` and
excluded from live aggregation.

## Metrics Flow

### Real-time (during run)
- Workers emit per-worker snapshots to `WORKER_METRICS_SNAPSHOTS` every 1 second.
- Each snapshot row is per worker (`WORKER_ID`) and represents that 1-second tick.
- Each snapshot includes the worker's current phase and heartbeat timestamp.
- Controller streams **aggregated parent metrics** over WebSocket.
- Per-worker status is surfaced for health and guardrails.
- Controller polls warehouse state every ~5 seconds using a dedicated Snowflake
  pool. This is the sole source of MCW/warehouse metrics.
- Controller persists poller snapshots to `WAREHOUSE_POLL_SNAPSHOTS` for the
  parent run (append-only time series).
- FIND_MAX runs publish aggregated step-controller state for the live panel.

### WORKER_METRICS_SNAPSHOTS.PHASE Column

The PHASE column supports filtering aggregation to measurement-phase workers:

```sql
ALTER TABLE WORKER_METRICS_SNAPSHOTS ADD COLUMN IF NOT EXISTS PHASE VARCHAR(50);
```

Values: `WARMUP`, `MEASUREMENT`, `COOLDOWN`. The orchestrator filters to
`PHASE='MEASUREMENT'` when computing aggregate metrics.

### Warehouse Poller Persistence
- `WAREHOUSE_POLL_SNAPSHOTS` stores raw `SHOW WAREHOUSES` results plus extracted
  fields (`STARTED_CLUSTERS`, `RUNNING`, `QUEUED`) per 5-second sample.
- Deprecate worker-level `WORKER_METRICS_SNAPSHOTS.CUSTOM_METRICS.WAREHOUSE` for
  MCW; controller is the sole source for multi-node.
- History charts prefer `V_WAREHOUSE_TIMESERIES` (QUERY_EXECUTIONS) and fall
  back to poller snapshots when query history lags.

### WAREHOUSE_POLL_SNAPSHOTS Table

```sql
CREATE OR ALTER TABLE WAREHOUSE_POLL_SNAPSHOTS (
    snapshot_id VARCHAR(36) NOT NULL,
    run_id VARCHAR(36) NOT NULL,
    
    -- Timing
    timestamp TIMESTAMP_NTZ NOT NULL,
    elapsed_seconds FLOAT,
    
    -- Warehouse Identity
    warehouse_name VARCHAR(500) NOT NULL,
    
    -- MCW Metrics (from SHOW WAREHOUSES)
    started_clusters INTEGER,
    running INTEGER,
    queued INTEGER,
    
    -- Scaling State
    min_cluster_count INTEGER,
    max_cluster_count INTEGER,
    scaling_policy VARCHAR(50),
    
    -- Raw SHOW WAREHOUSES row (for debugging)
    raw_result VARIANT,
    
    -- Audit
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

Used for:
1. **Live MCW display**: Real-time active cluster count.
2. **Queue detection**: `queued > 0` triggers Find Max stop condition.
3. **History fallback**: When `V_WAREHOUSE_TIMESERIES` (query history) lags.

### Post-run (after completion)
- Query history enrichment updates `QUERY_EXECUTIONS` and
  `TEST_RESULTS` app-overhead metrics.
- Full per-query detail is available for inline analysis on the parent
  dashboard.

## Controller Aggregation Contract

For parent runs, the controller must:

1. Query the most recent per-worker snapshots for the parent `RUN_ID`.
2. Compute aggregate metrics deterministically (sum counts/QPS, merge
   distributions for latency).
3. Stream the aggregate payload over `/ws/test/{RUN_ID}` on a 1-second cadence,
   using the most recent snapshot if no new data arrived.
4. Persist parent rollups at an adaptive cadence (only when new snapshots or
   worker status changes arrive) for history views.

## Aggregation Rules

- **Counts/QPS**: sum across workers.
- **Latency percentiles**: See "Latency Aggregation Strategy" below.
- **Resource telemetry**: average for trend + peak for guardrails.
- **Node health**: derived from last heartbeat and control events.

## Latency Aggregation Strategy

Real-time latency aggregation across N workers is non-trivial because percentiles
are not additive. This section defines the strategy for live dashboards, SLO
guardrails, and Find Max stability checks.

### The Problem

Given P95 latencies from 5 workers (e.g., 42ms, 45ms, 38ms, 51ms, 44ms), there is
no mathematically correct way to derive a "true" aggregate P95 without access to
the underlying query-level latencies. True percentile merge requires either:

1. **Full distribution data**: All individual latencies (expensive to transfer).
2. **Sketch structures**: t-digest, DDSketch, or similar (adds complexity).

### Real-Time Strategy: Worst-Worker Approximation

For **live dashboards** and **SLO guardrails**, we use a **worst-worker
approximation**:

```text
aggregate_p95 = MAX(worker_1_p95, worker_2_p95, ..., worker_n_p95)
aggregate_p99 = MAX(worker_1_p99, worker_2_p99, ..., worker_n_p99)
aggregate_p50 = AVG(worker_1_p50, worker_2_p50, ..., worker_n_p50)
  -- median uses avg
```

**Rationale**:
- **P95/P99 (tail latency)**: MAX is conservative—if any worker is slow, the
  aggregate reflects it. This is appropriate for SLO guardrails where we care
  about worst-case user experience.
- **P50 (median)**: AVG approximates the true median when workers have similar
  query distributions. Acceptable error for dashboard display.

### Find Max Stability Checks

Find Max uses latency to detect saturation. The stability check compares current
step P95 to baseline:

```text
latency_degradation_pct = (current_p95 - baseline_p95) / baseline_p95 * 100
IF latency_degradation_pct > latency_stability_pct THEN stop
```

Using **worst-worker P95** for this check is conservative:
- If one worker is saturated, we detect it immediately.
- False positives (stopping early) are safer than false negatives (missing
  saturation).

### Acceptable Error Bounds

| Metric | Method | Error vs True Aggregate | Acceptable? |
|--------|--------|-------------------------|-------------|
| P50 | AVG of worker P50s | ±5-10% typical | Yes (display only) |
| P95 | MAX of worker P95s | 0-15% high (conservative) | Yes (SLO-safe) |
| P99 | MAX of worker P99s | 0-20% high (conservative) | Yes (SLO-safe) |

These bounds assume homogeneous workloads across workers. Heterogeneous workloads
(e.g., read-heavy vs write-heavy workers) may have higher variance.

### Post-Run Enrichment (True Percentiles)

After run completion, `QUERY_EXECUTIONS` contains all individual query latencies.
History views compute **true percentiles** from this data:

```sql
SELECT
  PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY app_elapsed_ms) AS true_p50,
  PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY app_elapsed_ms) AS true_p95,
  PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY app_elapsed_ms) AS true_p99
FROM QUERY_EXECUTIONS
WHERE test_id = ? AND warmup = FALSE
```

This provides accurate final metrics for the test summary.

### Future Enhancement: T-Digest Sketches

If worst-worker approximation proves too conservative (e.g., consistently
overestimating P95 by >15%), consider adding t-digest columns to
`WORKER_METRICS_SNAPSHOTS`:

- Workers compute local t-digests and serialize to `latency_sketch VARIANT`.
- Orchestrator merges sketches for true aggregate percentiles.
- Complexity: Requires t-digest library in Python and merge logic.

Deferred unless real-world testing shows unacceptable approximation error.

## Find Max Control Loop (Multi-Node)

- The controller/orchestrator owns step transitions and target concurrency.
- Worker targets are distributed via per-worker `SET_WORKER_TARGET` events with
  explicit `target_connections`; workers do not self-adjust.
- Aggregated step state is emitted in the live payload for the UI panel.
- Queueing detection uses the controller's warehouse poller, not worker data.
- Live state is stored in `RUN_STATUS.FIND_MAX_STATE` (VARIANT).
- Step history is appended to `FIND_MAX_STEP_HISTORY`.
- Final summary is stored in `TEST_RESULTS.FIND_MAX_RESULT`.

### FIND_MAX_STEP_HISTORY Table

Persists step-by-step history for post-run analysis and UI timeline:

```sql
CREATE OR ALTER TABLE FIND_MAX_STEP_HISTORY (
    step_id VARCHAR(36) NOT NULL,
    run_id VARCHAR(36) NOT NULL,
    step_number INTEGER NOT NULL,
    
    -- Step Configuration
    target_workers INTEGER NOT NULL,
    step_start_time TIMESTAMP_NTZ NOT NULL,
    step_end_time TIMESTAMP_NTZ,
    step_duration_seconds FLOAT,
    
    -- Aggregate Metrics (worst-worker for P95/P99)
    total_queries INTEGER,
    qps FLOAT,
    p50_latency_ms FLOAT,
    p95_latency_ms FLOAT,
    p99_latency_ms FLOAT,
    error_count INTEGER,
    error_rate FLOAT,
    
    -- Stability Evaluation
    qps_vs_prior_pct FLOAT,         -- % change vs prior step
    p95_vs_baseline_pct FLOAT,      -- % change vs baseline (step 1)
    queue_detected BOOLEAN DEFAULT FALSE,
    
    -- Outcome
    outcome VARCHAR(50),            -- STABLE, DEGRADED, ERROR_THRESHOLD, QUEUE_DETECTED
    stop_reason TEXT,               -- Populated if this step triggered stop
    
    -- Audit
    created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

### RUN_STATUS.FIND_MAX_STATE Column

Add VARIANT column to `RUN_STATUS` for live Find Max state:

```sql
ALTER TABLE RUN_STATUS ADD COLUMN IF NOT EXISTS find_max_state VARIANT;
```

Schema for `find_max_state` VARIANT:

```json
{
  "current_step": 3,
  "target_workers": 35,
  "baseline_p95_ms": 42.5,
  "current_p95_ms": 48.2,
  "p95_vs_baseline_pct": 13.4,
  "qps": 1250,
  "qps_vs_prior_pct": 2.1,
  "error_rate": 0.001,
  "queue_detected": false,
  "status": "STEPPING",
  "last_updated": "2026-01-23T10:15:30Z"
}
```

### Worker Health States

Each worker has a health state derived from heartbeat recency:

| State | Condition | Behavior |
|-------|-----------|----------|
| HEALTHY | Heartbeat within 30s | Included in live aggregation |
| STALE | Heartbeat 30-60s old | Marked in UI, still included in aggregation |
| DEAD | No heartbeat for 60s+ | Excluded from live aggregation |

### Dead Node Handling (Live vs History)

**Live aggregation (during run):**
- Dead workers are **excluded** from real-time aggregate metrics.
- UI shows a warning: "1/5 workers unresponsive".
- Live QPS/latency reflects only healthy workers to avoid stale data.

**Final results and history:**
- Dead workers are **included** in final aggregates.
- All queries executed before the worker died are valid and counted.
- The parent run records which workers completed vs died early.
- History dashboard shows full metrics from all workers that contributed.

This distinction ensures live dashboards reflect current state while history
preserves the complete picture of work performed.

## Stop Semantics (Proposed)

- Controller issues STOP to the **orchestrator** (not directly to workers).
- Orchestrator writes a STOP event to `RUN_CONTROL_EVENTS`.
- Workers poll `RUN_CONTROL_EVENTS` on every heartbeat cycle (1s) and stop
  accepting new work (graceful drain).
- Orchestrator updates parent `RUN_STATUS` to `CANCELLING` and then
  `CANCELLED` once all workers exit.
- If workers do not exit within a configurable timeout, the orchestrator
  forces termination (local SIGTERM fallback) and marks the run `CANCELLED`
  with the reason recorded in logs.

### Stop Timing

| Scenario | Target Latency | How |
|----------|----------------|-----|
| Typical | 1 second | Worker polls at heartbeat interval |
| Worst-case | 2 seconds | 2x heartbeat interval + Snowflake write latency |
| Local fallback | Immediate | SIGTERM via subprocess handle (local only) |

Worker STOP polling query:

```sql
SELECT 1 FROM RUN_CONTROL_EVENTS
WHERE RUN_ID = ?
  AND EVENT_TYPE = 'STOP'
  AND CREATED_AT > ?
LIMIT 1
```

### Hybrid Table Polling Latency

Hybrid Tables are optimized for point lookups. Expected latencies:

| Operation | Expected Latency | Notes |
|-----------|------------------|-------|
| Point read (by PK) | **10-50ms** | Warm steady-state after warmup |
| Point write (INSERT/UPDATE) | **20-100ms** | Row-level locking, no contention |
| First query (cold) | **200-500ms** | Compilation + connection setup |

The 1-second polling interval provides ample margin. Even with 100ms query
latency, workers can reliably detect STOP events within 1-2 seconds.

For local runs, the orchestrator retains subprocess handles and sends SIGTERM
as a fallback if workers do not exit within 10 seconds of STOP event.

## Reiterated Constraints

- No DDL is executed at runtime. All tables are pre-created.
- Schema changes are rerunnable DDL in `sql/schema/`.
- Templates remain stored in `UNISTORE_BENCHMARK.CONFIG.TEST_TEMPLATES` and
  drive all runs.
