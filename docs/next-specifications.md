# Multi-Node Specifications (Implementation Details)

This document provides concrete schemas, SQL, and specifications for Phase 2
implementation. It fills gaps identified during plan review.

## Terminology

- **WORKER_ID**: Unique identifier for a worker process (string, e.g., `worker-0`)
- **WORKER_GROUP_ID**: Zero-based index for deterministic sharding (integer)
- **TARGET_CONNECTIONS**: Number of concurrent queries a worker should maintain
- **SEQUENCE_ID**: Monotonic counter for event ordering within a run
- **Warmup**: Run-level phase to prime Snowflake compute (not per-worker)

## Design Decisions

- **Worker START timeout**: 120 seconds (balance between startup delays and
  zombie detection).
- **Graceful drain timeout**: 120 seconds (allow in-flight queries to complete).
- **Poll loop**: Per-run background task (isolated lifecycle, easier cleanup).
- **Snapshot cadence**: 1 second for `WORKER_METRICS_SNAPSHOTS` and heartbeats.
- **Control event polling**: 1 second cadence for workers.
- **Event ordering**: `SEQUENCE_ID` is monotonic per `RUN_ID`, generated via
  `RUN_STATUS.NEXT_SEQUENCE_ID` atomic increment.
- **Schema versioning**: None (complete migration, no legacy support).
- **OrchestratorService location**: `backend/core/orchestrator_service.py`
  (parallel to existing `test_registry.py`).
- **Warmup model**: Single run-level warmup; workers joining after warmup
  inherit MEASUREMENT phase.

---

## 1. WebSocket Payload Schema

The WebSocket payload is the single source of truth for live dashboard data.
All runs (single-node and multi-node) use the same payload structure.

### WebSocket Event Semantics

The controller emits a single event type on `/ws/test/{run_id}`:

```json
{
  "event": "RUN_UPDATE",
  "data": { ...payload... }
}
```

Rules:

- One `RUN_UPDATE` is emitted every 1 second.
- Payload is a full snapshot (not a diff). The client replaces prior state.
- WebSocket is read-only: no control commands are sent over this channel.
- Control-plane commands are written by the orchestrator to `RUN_CONTROL_EVENTS`.

### Live Metrics Payload

```json
{
  "test_id": "uuid",
  "status": "RUNNING",
  "phase": "MEASUREMENT",
  "timestamp": "2026-01-23T10:15:30.123Z",
  
  "elapsed": 125.5,
  
  "ops": {
    "total": 125000,
    "current_per_sec": 1250.5
  },
  
  "operations": {
    "reads": 100000,
    "writes": 25000
  },
  
  "latency": {
    "p50": 12.5,
    "p95": 45.2,
    "p99": 98.7,
    "avg": 18.3
  },
  
  "errors": {
    "count": 5,
    "rate": 0.00004
  },
  
  "connections": {
    "active": 50,
    "target": 50
  },
  
  "workers": [
    {
      "worker_id": "worker-0",
      "worker_group_id": 0,
      "status": "RUNNING",
      "phase": "MEASUREMENT",
      "health": "HEALTHY",
      "last_heartbeat": "2026-01-23T10:15:28.000Z",
      "metrics": {
        "qps": 625.2,
        "p95_latency_ms": 42.1,
        "error_count": 2,
        "active_connections": 25
      }
    },
    {
      "worker_id": "worker-1",
      "worker_group_id": 1,
      "status": "RUNNING",
      "phase": "MEASUREMENT",
      "health": "HEALTHY",
      "last_heartbeat": "2026-01-23T10:15:29.000Z",
      "metrics": {
        "qps": 625.3,
        "p95_latency_ms": 48.3,
        "error_count": 3,
        "active_connections": 25
      }
    }
  ],
  
  "warehouse": {
    "name": "BENCHMARK_WH",
    "started_clusters": 2,
    "running": 45,
    "queued": 0
  },
  
  "find_max": {
    "current_step": 3,
    "target_workers": 35,
    "baseline_p95_ms": 42.5,
    "current_p95_ms": 48.2,
    "p95_vs_baseline_pct": 13.4,
    "qps_vs_prior_pct": 2.1,
    "queue_detected": false,
    "status": "STEPPING"
  },
  
  "custom_metrics": {
    "app_ops_breakdown": {},
    "sf_bench": {},
    "resources": {}
  }
}
```

### Worker Health States

| Health | Condition | UI Display |
|--------|-----------|------------|
| `HEALTHY` | Heartbeat within 30s | Green indicator |
| `STALE` | Heartbeat 30-60s old | Yellow indicator + warning |
| `DEAD` | No heartbeat for 60s+ | Red indicator + excluded from aggregates |

### Status Values

| Status | Meaning |
|--------|---------|
| `PREPARED` | Run created, waiting to start |
| `RUNNING` | Workers active, load generating |
| `CANCELLING` | STOP issued, draining in-flight queries |
| `COMPLETED` | All workers finished successfully |
| `FAILED` | Error during execution |
| `CANCELLED` | User-initiated stop completed |

### Phase Values

| Phase | Meaning |
|-------|---------|
| `PREPARING` | Setting up connections, validating config |
| `WARMUP` | Initial load, metrics not counted |
| `MEASUREMENT` | Main test period, metrics counted |
| `COOLDOWN` | Draining before finalization |
| `PROCESSING` | Post-run enrichment in progress |

---

## 2. Control Event Schemas

Events written to `RUN_CONTROL_EVENTS` by the orchestrator.

### STOP Event

```json
{
  "event_type": "STOP",
  "event_data": {
    "scope": "RUN",
    "reason": "user_requested",
    "initiated_by": "api",
    "drain_timeout_seconds": 120
  }
}
```

### START Event

```json
{
  "event_type": "START",
  "event_data": {
    "scope": "RUN",
    "expected_workers": 5
  }
}
```

### SET_PHASE Event

```json
{
  "event_type": "SET_PHASE",
  "event_data": {
    "scope": "RUN",
    "phase": "MEASUREMENT",
    "effective_at": "2026-01-23T10:15:30.000Z"
  }
}
```

### SET_WORKER_TARGET Event (Per-Worker Targeting)

```json
{
  "event_type": "SET_WORKER_TARGET",
  "event_data": {
    "scope": "WORKER",
    "worker_id": "worker-3",
    "worker_group_id": 3,
    "target_connections": 42,
    "target_qps": 250.0,
    "step_id": "uuid",
    "step_number": 3,
    "effective_at": "2026-01-23T10:15:30.000Z",
    "ramp_seconds": 5,
    "reason": "step_advance"
  }
}
```

### Event Targeting and Ordering

- `scope` determines which workers apply the event: `RUN` (all), `WORKER_GROUP`,
  or `WORKER`.
- For per-worker targets (QPS and FIND_MAX), the orchestrator emits one
  `SET_WORKER_TARGET` event per worker with explicit `target_connections`
  (and optional `target_qps`).
- `SEQUENCE_ID` is monotonic per `RUN_ID`. Workers track the last seen sequence
  and process events in order.

### Control Plane Processing Rules

- Workers ignore events with `SEQUENCE_ID <= last_seen_sequence`.
- `RUN`-scoped events apply to all workers.
- `WORKER_GROUP` events apply only to matching `worker_group_id`.
- `WORKER` events apply only to matching `worker_id`.
- `SET_WORKER_TARGET` uses absolute targets; workers do not compute deltas.

---

## 3. SCENARIO_CONFIG Schema

Stored in `RUN_STATUS.SCENARIO_CONFIG` as VARIANT.

```json
{
  "template_id": "uuid",
  "template_name": "High Concurrency Test",
  
  "target": {
    "table_name": "BENCHMARK_TABLE",
    "table_type": "HYBRID",
    "warehouse": "BENCHMARK_WH"
  },
  
  "workload": {
    "load_mode": "CONCURRENCY",
    "concurrent_connections": 100,
    "duration_seconds": 300,
    "warmup_seconds": 60,
    "read_percent": 80,
    "write_percent": 20
  },
  
  "scaling": {
    "worker_count": 5,
    "per_worker_capacity": 25,
    "worker_group_count": 5
  },
  
  "find_max": {
    "enabled": false,
    "start_concurrency": 5,
    "concurrency_increment": 10,
    "step_duration_seconds": 30,
    "qps_stability_pct": 5,
    "latency_stability_pct": 20,
    "max_error_rate_pct": 1
  },
  
  "guardrails": {
    "max_cpu_percent": 85,
    "max_memory_percent": 90
  }
}
```

---

## 4. Aggregation SQL

### Parent Rollup Query (Live)

Used by the orchestrator to compute aggregate metrics for the live payload and
to persist minimal rollups to `RUN_STATUS` (for example, `TOTAL_OPS`,
`ERROR_COUNT`, `CURRENT_QPS`, and worker counts).

```sql
WITH latest_per_worker AS (
    SELECT
        wms.*,
        ROW_NUMBER() OVER (
            PARTITION BY WORKER_ID
            ORDER BY TIMESTAMP DESC
        ) AS rn,
        TIMESTAMPDIFF('second', TIMESTAMP, CURRENT_TIMESTAMP()) AS stale_seconds
    FROM WORKER_METRICS_SNAPSHOTS wms
    WHERE RUN_ID = :run_id
      AND PHASE = 'MEASUREMENT'  -- Only aggregate MEASUREMENT phase
),
healthy_workers AS (
    SELECT * FROM latest_per_worker
    WHERE rn = 1 AND stale_seconds <= 60
)
SELECT
    -- Timing (max across workers)
    MAX(ELAPSED_SECONDS) AS elapsed_seconds,
    
    -- Counts (sum across workers)
    SUM(TOTAL_QUERIES) AS total_ops,
    SUM(QPS) AS aggregate_qps,
    SUM(READ_COUNT) AS total_reads,
    SUM(WRITE_COUNT) AS total_writes,
    SUM(ERROR_COUNT) AS total_errors,
    SUM(ACTIVE_CONNECTIONS) AS total_active_connections,
    SUM(TARGET_CONNECTIONS) AS total_target_connections,
    
    -- Latency (worst-worker for P95/P99, avg for P50)
    AVG(P50_LATENCY_MS) AS p50_latency_ms,
    MAX(P95_LATENCY_MS) AS p95_latency_ms,
    MAX(P99_LATENCY_MS) AS p99_latency_ms,
    AVG(AVG_LATENCY_MS) AS avg_latency_ms,
    
    -- Worker counts
    COUNT(*) AS healthy_worker_count,
    (SELECT COUNT(DISTINCT WORKER_ID) FROM latest_per_worker WHERE rn = 1) AS total_worker_count
    
FROM healthy_workers;
```

### Per-Worker Status Query

Used to populate the `workers` array in the WebSocket payload.

```sql
WITH latest_per_worker AS (
    SELECT
        wms.*,
        hb.STATUS AS worker_status,
        hb.LAST_HEARTBEAT,
        ROW_NUMBER() OVER (
            PARTITION BY wms.WORKER_ID
            ORDER BY wms.TIMESTAMP DESC
        ) AS rn
    FROM WORKER_METRICS_SNAPSHOTS wms
    LEFT JOIN WORKER_HEARTBEATS hb 
        ON wms.RUN_ID = hb.RUN_ID 
        AND wms.WORKER_ID = hb.WORKER_ID
    WHERE wms.RUN_ID = :run_id
)
SELECT
    WORKER_ID,
    WORKER_GROUP_ID,
    worker_status AS STATUS,
    PHASE,
    LAST_HEARTBEAT,
    TIMESTAMPDIFF('second', LAST_HEARTBEAT, CURRENT_TIMESTAMP()) AS stale_seconds,
    QPS,
    P95_LATENCY_MS,
    ERROR_COUNT,
    ACTIVE_CONNECTIONS,
    TARGET_CONNECTIONS
FROM latest_per_worker
WHERE rn = 1
ORDER BY WORKER_GROUP_ID;
```

### Final Parent Rollup Query (Post-Run)

True percentiles from all query executions.

```sql
SELECT
    COUNT(*) AS total_operations,
    SUM(
        CASE
            WHEN QUERY_KIND IN ('POINT_LOOKUP', 'RANGE_SCAN') THEN 1
            ELSE 0
        END
    ) AS read_operations,
    SUM(
        CASE
            WHEN QUERY_KIND IN ('INSERT', 'UPDATE', 'DELETE') THEN 1
            ELSE 0
        END
    ) AS write_operations,
    SUM(CASE WHEN SUCCESS = FALSE THEN 1 ELSE 0 END) AS failed_operations,
    
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p50_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p95_latency_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY APP_ELAPSED_MS) AS p99_latency_ms,
    AVG(APP_ELAPSED_MS) AS avg_latency_ms,
    MIN(APP_ELAPSED_MS) AS min_latency_ms,
    MAX(APP_ELAPSED_MS) AS max_latency_ms
    
FROM QUERY_EXECUTIONS qe
JOIN TEST_RESULTS tr ON qe.TEST_ID = tr.TEST_ID
WHERE tr.RUN_ID = :run_id
  AND qe.WARMUP = FALSE;
```

---

## 5. Schema DDL (Ensure Present in sql/schema/)

### results_tables.sql (verify presence)

```sql
-- =============================================================================
-- WAREHOUSE_POLL_SNAPSHOTS: Controller warehouse poller persistence
-- =============================================================================
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

-- =============================================================================
-- FIND_MAX_STEP_HISTORY: Step-by-step history for Find Max runs
-- =============================================================================
CREATE OR ALTER TABLE FIND_MAX_STEP_HISTORY (
    STEP_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    STEP_NUMBER INTEGER NOT NULL,
    
    -- Step Configuration
    TOTAL_TARGET_CONNECTIONS INTEGER NOT NULL,  -- Sum of all worker targets
    STEP_START_TIME TIMESTAMP_NTZ NOT NULL,
    STEP_END_TIME TIMESTAMP_NTZ,
    STEP_DURATION_SECONDS FLOAT,
    
    -- Aggregate Metrics (worst-worker for P95/P99)
    TOTAL_QUERIES INTEGER,
    QPS FLOAT,
    P50_LATENCY_MS FLOAT,
    P95_LATENCY_MS FLOAT,              -- MAX across workers (conservative)
    P99_LATENCY_MS FLOAT,              -- MAX across workers (conservative)
    ERROR_COUNT INTEGER,
    ERROR_RATE FLOAT,
    
    -- Stability Evaluation
    QPS_VS_PRIOR_PCT FLOAT,            -- % change vs prior step
    P95_VS_BASELINE_PCT FLOAT,         -- % change vs baseline (step 1)
    QUEUE_DETECTED BOOLEAN DEFAULT FALSE,
    
    -- Outcome
    OUTCOME VARCHAR(50),               -- STABLE, DEGRADED, ERROR_THRESHOLD, QUEUE_DETECTED
    STOP_REASON TEXT,                  -- Populated if this step triggered stop
    
    -- Audit
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);

-- =============================================================================
-- TEST_LOGS: Centralized worker logs
-- =============================================================================
CREATE TABLE IF NOT EXISTS TEST_LOGS (
    LOG_ID VARCHAR(36) NOT NULL,
    RUN_ID VARCHAR(36) NOT NULL,
    TEST_ID VARCHAR(36),              -- Nullable (orchestrator logs may not have test_id)
    WORKER_ID VARCHAR(100),           -- Nullable
    
    LEVEL VARCHAR(20) NOT NULL,       -- INFO, WARNING, ERROR, CRITICAL
    MESSAGE TEXT NOT NULL,
    DETAILS VARIANT,                  -- Optional structured context
    
    TIMESTAMP TIMESTAMP_NTZ NOT NULL,
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
);
```

### control_tables.sql (verify presence)

```sql
-- Add phase column to WORKER_METRICS_SNAPSHOTS (worker snapshots)
ALTER TABLE WORKER_METRICS_SNAPSHOTS ADD COLUMN IF NOT EXISTS PHASE VARCHAR(50);

-- Add find_max_state column to RUN_STATUS
ALTER TABLE RUN_STATUS ADD COLUMN IF NOT EXISTS FIND_MAX_STATE VARIANT;

-- Add worker_targets column to RUN_STATUS (fallback for missed events)
ALTER TABLE RUN_STATUS ADD COLUMN IF NOT EXISTS WORKER_TARGETS VARIANT;

-- Add next_sequence_id column to RUN_STATUS (atomic event ordering)
ALTER TABLE RUN_STATUS ADD COLUMN IF NOT EXISTS NEXT_SEQUENCE_ID INTEGER DEFAULT 1;
```

---

## 6. Poll Loop Lifecycle

The orchestrator poll loop runs as a **per-run background task** managed by
FastAPI's background task system.

### Lifecycle

```text
create_run() → Inserts RUN_STATUS, returns run_id
start_run() → Spawns workers, starts poll loop as background task
[poll loop runs every 1s]
stop_run() → Writes STOP event, waits for workers, cancels poll loop
```

### Implementation Pattern

```python
class OrchestratorService:
    def __init__(self):
        self._poll_tasks: dict[str, asyncio.Task] = {}
    
    async def start_run(self, run_id: str) -> None:
        # ... spawn workers ...
        
        # Start poll loop as background task
        task = asyncio.create_task(self._poll_loop(run_id))
        self._poll_tasks[run_id] = task
    
    async def stop_run(self, run_id: str) -> None:
        # Write STOP event
        await self._write_stop_event(run_id)
        
        # Wait for graceful drain (max 120s)
        await self._wait_for_workers(run_id, timeout=120)
        
        # Cancel poll loop
        if run_id in self._poll_tasks:
            self._poll_tasks[run_id].cancel()
            del self._poll_tasks[run_id]
    
    async def _poll_loop(self, run_id: str) -> None:
        while True:
            await asyncio.sleep(1.0)
            await self._check_heartbeats(run_id)
            await self._update_aggregates(run_id)
            await self._check_phase_transitions(run_id)
```

---

## 7. Worker Startup Sequence

### Current Flow (run_worker.py)

```text
1. Parse args (template-id, worker-group-id, etc.)
2. Call registry.start_from_template()
3. Wait for task completion
4. Exit with status code
```

### New Flow (with control plane)

```text
1. Parse args (run-id, worker-id, worker-group-id, worker-group-count)
2. Connect to Snowflake
3. Upsert WORKER_HEARTBEATS with STATUS='STARTING'
4. Load SCENARIO_CONFIG from RUN_STATUS
5. Compute initial TARGET_CONNECTIONS from config
6. Check RUN_STATUS.STATUS:
   - If RUNNING: start immediately with current RUN_STATUS.PHASE
   - If PREPARED: poll RUN_CONTROL_EVENTS for START (timeout: 120s)
7. Create child TEST_RESULTS row
8. Determine initial phase from RUN_STATUS.PHASE:
   - If WARMUP: participate in warmup
   - If MEASUREMENT: skip warmup (Snowflake already primed)
9. Begin workload
10. During run:
    - Write heartbeats every 1s
    - Write metrics snapshots every 1s
    - Poll for STOP, SET_PHASE, SET_WORKER_TARGET every 1s (ordered by SEQUENCE_ID)
    - Reconcile state from RUN_STATUS every 5s (fallback for missed events)
11. On STOP: Drain in-flight queries (max 120s), exit
12. On completion: Finalize child TEST_RESULTS, update heartbeat to COMPLETED, exit
```

### Worker Self-Termination Conditions

| Condition | Action |
|-----------|--------|
| STOP event received | Drain in-flight queries, exit |
| No START within 120s | Exit with error |
| No Snowflake connection for 60s | Exit (assume partition) |
| Parent RUN_STATUS is terminal | Exit |

---

## 8. Acceptance Test Criteria

### Local Multi-Node Acceptance Test

Create `scripts/acceptance_test_multinode.py`:

```python
"""
Acceptance test for local multi-node orchestration.

Tests:
1. Create a 2-worker run
2. Verify both workers start and register heartbeats
3. Verify aggregated metrics appear in WebSocket
4. Issue STOP and verify propagation within 10s
5. Verify final RUN_STATUS is CANCELLED
"""
```

### Test Checklist

- [ ] **Run Creation**: `RUN_STATUS` row created with `STATUS=PREPARED`
- [ ] **Worker Registration**: Both workers appear in `WORKER_HEARTBEATS`
- [ ] **START Propagation**: Workers transition to `RUNNING` within 2s of START
- [ ] **Metrics Flow**: `WORKER_METRICS_SNAPSHOTS` populated by both workers
- [ ] **Aggregation**: WebSocket shows combined QPS from both workers
- [ ] **Phase Transition**: `WARMUP` → `MEASUREMENT` at correct time
- [ ] **STOP Propagation**: Workers exit within 10s of STOP event
- [ ] **Final Status**: `RUN_STATUS.STATUS` = `CANCELLED`
- [ ] **Cleanup**: No orphan processes after test

### Automated Checks

```bash
# Run acceptance test
uv run python scripts/acceptance_test_multinode.py

# Expected output:
# [PASS] Run created: RUN_STATUS.STATUS = PREPARED
# [PASS] Workers registered: 2/2 in WORKER_HEARTBEATS
# [PASS] START propagated: workers RUNNING in 3.2s
# [PASS] Metrics flowing: WORKER_METRICS_SNAPSHOTS has 2 workers
# [PASS] Aggregation correct: combined QPS = 1250 (sum of 625 + 625)
# [PASS] STOP propagated: workers exited in 4.8s
# [PASS] Final status: RUN_STATUS.STATUS = CANCELLED
# 
# All 7 checks passed.
```

---

## 9. Documentation Consistency

- Use a single unified payload structure across all docs.
- Remove legacy payload compatibility language.

---

## Reiterated Constraints

- No DDL is executed at runtime.
- Schema changes are rerunnable DDL in `sql/schema/`.
- Templates remain stored in `UNISTORE_BENCHMARK.CONFIG.TEST_TEMPLATES`.
- Snowflake is the authoritative results store.
- No schema versioning - complete migration, single payload structure.
