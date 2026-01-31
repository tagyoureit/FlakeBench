# Multi-Worker Scaling (Current)

This document describes how the benchmark scales to N workers and how it manages
concurrency limits for orchestrator-backed AUTO/BOUNDED runs. FIXED runs still
use the legacy registry/executor path.

## Terminology

- **WORKER_ID**: Unique identifier for a worker process (string, e.g., `worker-0`)
- **WORKER_GROUP_ID**: Zero-based index for deterministic sharding (integer)
- **TARGET_CONNECTIONS**: Number of concurrent queries a worker should maintain
- **Warmup**: Run-level phase to prime Snowflake compute (not per-worker)

## Scaling Model

The system uses a **process-based** scaling model where each worker is an
independent process (or container) that maintains its own connection pool to
Snowflake.

- **Process Isolation**: Each worker runs as a separate OS process.
- **Shared Nothing**: Workers do not communicate with each other. They only
  communicate with the authoritative state in Snowflake.
- **Linear Scaling**: 10 workers = 10x potential throughput (bottlenecked only by
  Snowflake warehouse size or client-side CPU).

### Target Scale

The primary target is **5,000+ concurrent connections** across **5-20 workers**.
Each worker should support **250-1,000 concurrent connections**
depending on
host resources. This architecture avoids needing 100+ workers by maximizing
per-worker concurrency.

## Connector Constraints (Current)

- The Snowflake Python connector is synchronous; high concurrency requires
  sufficient thread pool capacity to avoid client-side queueing.
- Snowflake work is isolated across executors:
  - Results/persistence pool: `SNOWFLAKE_RESULTS_EXECUTOR_MAX_WORKERS`
  - Benchmark workload pool: sized to requested concurrency, capped by
    `SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS`
- Connection pool sizing and safety caps:
  - `SNOWFLAKE_POOL_SIZE`, `SNOWFLAKE_MAX_OVERFLOW` (results/persistence pool)
  - `SNOWFLAKE_POOL_MAX_PARALLEL_CREATES` to cap concurrent `connect()` calls
    and avoid startup stampedes.

## Worker Count Inputs

Definitions:
- **Worker (process)**: A worker process/container managed by the orchestrator.
- **TARGET_CONNECTIONS**: Number of concurrent queries a worker should maintain.
- **Per-worker capacity**: The max TARGET_CONNECTIONS a worker can sustain.

### Per-worker capacity resolution

- **User-defined (fixed)**: Use an explicit per-worker TARGET_CONNECTIONS from the
  UI/template.
- **Auto-detect (default)**: Derive a per-worker limit from host resources using
  UI defaults.
  - `cpu_cap = cpu_cores * ui_default_connections_per_core`
  - `mem_cap = floor(memory_gb / ui_default_memory_per_connection_gb)`
  - `per_worker_cap = max(1, min(cpu_cap, mem_cap, ui_default_max_per_worker))`
- **Homogeneous workers**: All workers are expected to have the same capacity.

### Resource caps

- Scale-out is bounded by host/cgroup CPU and memory guardrails.
- Guardrails are **soft boundaries** by default (see [Resource Guardrails](#resource-guardrails-section-216)):
  - Single worker exceeding threshold triggers back-off, not run failure.
  - Only ALL workers exceeding for multiple intervals causes failure.
- For SPCS, use cluster resource limits when available (future).

## Load Modes

The benchmark supports three load modes configured via `load_mode`:

### 1. CONCURRENCY Mode (Default) — Fixed Worker Count

- **Goal**: Maximize throughput with a fixed number of TARGET_CONNECTIONS.
- **Config**: `concurrent_connections` is the total TARGET_CONNECTIONS across the
  cluster.
- **Per-worker cap**: Resolved via auto-detect or user override (see Worker Count
  Inputs).
- **Worker Calculation**:

  ```python
  worker_count = max(1, math.ceil(concurrent_connections / per_worker_cap))
  ```

- **Allocation**: Distribute `concurrent_connections` evenly across workers using
  the target allocation algorithm (see below). Workers may have slightly different
  TARGET_CONNECTIONS due to remainder distribution.
- **Behavior**: All workers are started upfront. Workers fire queries as fast as
  possible (no rate limiting). No rebalancing after start.

### 2. QPS Mode — Dynamic Scale-Out to Target Throughput

- **Goal**: Hit a specific throughput (ops/sec) with minimal resources.
- **Config**: `target_qps` (total target), `min_connections` (per-worker floor),
  per-worker ceiling from capacity resolution (user-defined
  `concurrent_connections` or auto-detect).
- **Per-worker TARGET_CONNECTIONS**: Controlled by the existing QPS controller.
  - Uses windowed/smoothed QPS, deadband (5% or 2 QPS), proportional gains,
    and rate-limited changes (max 10% per control tick).
  - Control interval is `max(5s, metrics_interval_seconds)`.
- **Worker Calculation**: Starts with **1 worker** and scales out.
- **Scale-Out Trigger**: When all workers are at max TARGET_CONNECTIONS AND
  aggregate QPS is < 98% of target for 2 consecutive intervals, a new worker is
  spawned.
- **Per-Worker Target**: `target_qps / worker_count` (split evenly across workers).
- **Control Events**: Orchestrator emits per-worker `SET_WORKER_TARGET` events
  with explicit `target_connections` and optional `target_qps`.
- **Allocation**: Existing workers keep their TARGET_CONNECTIONS (no rebalancing).
  New workers start at `min_connections` and scale independently.
- **Caps**: Bounded by host/cgroup CPU and memory guardrails (soft by default;
  see [Resource Guardrails](#resource-guardrails-section-216)).
- **Warmup**: New workers joining after warmup ends start directly in MEASUREMENT
  phase (Snowflake already primed).

### 3. FIND_MAX_CONCURRENCY Mode — Step-Load Discovery

- **Goal**: Find the maximum sustainable TARGET_CONNECTIONS for a workload.
- **Config**:
  - `start_connections`: Initial total TARGET_CONNECTIONS (default: 5)
  - `connections_increment`: TARGET_CONNECTIONS to add each step (default: 10)
  - `step_duration_seconds`: Duration per step (default: 30s)
  - `qps_stability_pct`: Max allowed QPS drop (default: 5%)
  - `latency_stability_pct`: Max allowed P95 latency increase (default: 20%)
  - `max_error_rate_pct`: Error threshold to stop (default: 1%)
- `concurrent_connections`: Per-worker ceiling when user-defined (auto-detect
    provides the cap otherwise)
- **Control Plane Ownership**:
  - The orchestrator computes step targets and sends them to workers.
  - Control events use per-worker `SET_WORKER_TARGET` with explicit
    `target_connections`.
  - Workers only apply targets and emit metrics; they do not decide steps.
  - Step state is aggregated centrally for the live Find Max panel.
  - Live state is stored in `RUN_STATUS.FIND_MAX_STATE`, with history in
    `FIND_MAX_STEP_HISTORY`.
- **Worker Calculation**: Always multi-worker (orchestrator path even when
  worker_count=1).
- **Scale Strategy**:
  - **Auto-detect capacity**: Fill existing workers to `per_worker_cap` before
    adding a new worker.
  - **Fixed worker count**: Distribute each increment evenly across workers.
- **Stability Evaluation**: Aggregate metrics across workers each step.
  - Stop when error rate exceeds `max_error_rate_pct`, QPS drops more than
    `qps_stability_pct` vs prior stable step, P95 latency increases more than
    `latency_stability_pct` vs **baseline (step 1)**, or Snowflake queueing appears.
  - Queueing detection uses the controller's warehouse poller (5s cadence).
- **Latency aggregation**: Uses slowest-worker P95/P99 (MAX across workers) for
  conservative saturation detection. See `data-flow-and-lifecycle.md`,
  "Latency Aggregation Strategy" for rationale.
- **Baseline**: Step 1's P95 latency is the baseline for all subsequent steps.
- **Output**: Best sustainable TARGET_CONNECTIONS and corresponding QPS/latency,
  persisted to `TEST_RESULTS.FIND_MAX_RESULT`.

## Worker Count Summary

| Mode | Worker Count | When Determined |
|------|-----------|-----------------|
| CONCURRENCY | `ceil(total / per_worker)` | At start (fixed) |
| QPS | 1 -> N (dynamic) | During run (scale-out) |
| FIND_MAX | 1 -> N (step-load) | During run |

---

## Worker Count Decisions (Resolved)

- `load_mode` defines how `concurrent_connections` is interpreted:
  - **CONCURRENCY**: Total TARGET_CONNECTIONS across the cluster.
  - **QPS**: Per-worker ceiling when user-defined; auto-detect provides the
    cap otherwise.
  - **FIND_MAX_CONCURRENCY**: Per-worker ceiling when user-defined; auto-detect
    provides the cap otherwise.
- Per-worker capacity comes from **user override** or **auto-detect** (default).
- Scale-out caps are based on **host/cgroup CPU and memory guardrails** (soft
  boundaries by default; see [Resource Guardrails](#resource-guardrails-section-216)).
- FIND_MAX is **multi-worker only**, using aggregated metrics for stability checks.
- Workers are expected to be **homogeneous**; no per-worker capacity skew.
- **No rebalancing** of existing worker allocations when scaling out.
- **Warmup is run-level**: Workers joining after warmup ends start directly in
  MEASUREMENT phase.

Note: `FIND_MAX` refers to `FIND_MAX_CONCURRENCY`.

---

## Value Pool Sharding (Deterministic)

When scaling across multiple worker processes, value pools must be sharded to
avoid overlapping keys (which would distort cache behavior).

Deterministic sharding uses two scenario fields:

- `worker_group_id`: index of this worker group (0-based)
- `worker_group_count`: total number of worker groups

Global stride and worker index:

```text
global_stride = concurrent_connections * worker_group_count
global_worker_id = (worker_group_id * concurrent_connections) + local_worker_id
```

This assumes homogeneous per-worker concurrency. If per-worker concurrency
differs, use separate runs or adjust the sharding scheme.

---

## Legacy Path Removal (Completed)

> **Status:** The API layer migration is complete. All runs now route through the
> OrchestratorService regardless of worker count. The frontend `isMultiWorker`
> conditionals have been removed.

**Remaining cleanup tasks:**

- `backend/core/test_registry.py`: Remove execution methods (`start_from_template`,
  `start_prepared`, `_run_and_persist`, `RunningTest` class). Keep template CRUD.
- `backend/core/autoscale.py`: Can be removed once orchestrator handles all
  subprocess spawning scenarios.
  assignment.
- `autoscale.py:107-127`: Guardrail checks against local host metrics. Replace
  with per-worker metrics reported to the orchestrator.

### Files requiring significant refactoring

1. **`backend/core/autoscale.py`** — Replace entirely with orchestrator-based
   dispatch
2. **`backend/core/test_executor.py`** — Extract FIND_MAX logic for orchestrator
   coordination
3. **`backend/main.py`** — Remove direct test execution paths; all runs go
   through orchestrator
4. **`scripts/run_worker.py`** — Keep as worker entry point, but launched by
   orchestrator (not autoscale.py)

---

## Allocation Logic

The orchestrator allocates work deterministically using `WORKER_GROUP_ID`:

```python
# Deterministic sharding for data generation or partition targeting
shard_id = worker_group_id % total_partitions
```

This ensures that if we scale from 1 to 10 workers, we can (optionally) target
different data ranges to avoid hot-spotting specific micro-partitions, or
deliberately overlap to test locking.

### Target Allocation for Uneven Deltas

When the orchestrator needs to distribute `total_connections` across `N` workers,
it computes per-worker targets deterministically:

```python
def compute_worker_targets(
    total_connections: int, worker_count: int
) -> dict[str, int]:
    """
    Distribute total_connections evenly across workers.
    Remainder goes to lowest WORKER_GROUP_IDs.
    
    Returns: {worker_id: target_connections}
    """
    base = total_connections // worker_count
    remainder = total_connections % worker_count
    
    targets = {}
    for i in range(worker_count):
        worker_id = f"worker-{i}"
        if i < remainder:
            targets[worker_id] = base + 1
        else:
            targets[worker_id] = base
    
    return targets
```

- `base = total_connections // worker_count`
- `remainder = total_connections % worker_count`
- Workers with `WORKER_GROUP_ID < remainder` get `base + 1`
- Enforce `min_connections` per worker; if a worker hits the floor, shift the
  remaining decrement to the next worker.

The orchestrator emits per-worker `SET_WORKER_TARGET` events with **absolute**
`target_connections` (no per-worker API calls). It also updates
`RUN_STATUS.WORKER_TARGETS` as a fallback for missed events.

## Warehouse Sizing Guide

Recommended Snowflake warehouse sizes for benchmark tiers:

| Workers | Concurrent Conns (Total) | Recommended Warehouse | Rationale |
|-------|--------------------------|-----------------------|-----------|
| 1 | 10-50 | X-Small | Baseline / dev |
| 5 | 50-250 | Small | moderate concurrency |
| 20 | 1000 | Medium/Large | High concurrency |
| 100 | 5000 | 2X-Large+ | Stress testing |

## Hybrid Table Concurrency

**Confirmed Viability**:
We have validated that Snowflake Hybrid Tables support the required concurrency
for the control plane.

- **Scenario**: 100 concurrent workers updating `RUN_STATUS` every 1 second.
- **Mechanism**: Hybrid Tables use **row-level locking**. Since each worker
  updates its own row (keyed by `WORKER_ID`), there is **no contention**.
- **Limit**: This pattern scales well to ~1000 workers. Beyond that, we would
  need to batch heartbeats or use a different aggregation strategy, but for the
  target scope (10-100 workers), it is performant.

## Connection Management

- **Connection Pooling**: Each worker maintains a persistent pool of
  connections.
- **Keep-Alive**: Connections are kept open to avoid handshake overhead.
- **Validation**: Stale connections are pruned automatically by the connector.

### Snowflake Session Limits

Snowflake does **not** impose a hard per-account concurrent connection limit.
However, practical limits exist:

- **Warehouse concurrency**: Each warehouse has a query queue. Very high
  concurrency (1000+) may cause queuing if the warehouse is undersized.
- **Session timeouts**: Idle sessions timeout after the configured session
  policy (default 4 hours). Active sessions do not count against any quota.
- **Best practice**: Size the warehouse appropriately for the target
  concurrency (see Warehouse Sizing Guide above).

## Reiterated Constraints

- No DDL is executed at runtime.
- Schema changes are rerunnable DDL in `sql/schema/`.
- Templates remain stored in `UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES`
  with `CONFIG` as the authoritative payload for runs.

---

## Manual Scaling Bounds

The benchmark supports explicit bounds on worker count and per-worker connections
to enable deterministic resource allocation and reproducible configurations.

### Scaling Modes

The `scaling.mode` field in the template config controls how scaling bounds are applied:

| Mode | Workers | Per-Worker Connections | Use Case |
|------|---------|------------------------|----------|
| `AUTO` | Computed from target | Auto-detect or override | Default (current) |
| `BOUNDED` | min ≤ N ≤ max | min ≤ C ≤ max | Auto-scale within guardrails |
| `FIXED` | Exactly as specified | Exactly as specified | Reproducible |

### Configuration Schema

```json
{
  "scaling": {
    "mode": "BOUNDED",
    "min_workers": 2,
    "max_workers": 10,
    "min_connections": 50,
    "max_connections": 500
  }
}
```

#### Field Definitions

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `mode` | enum | Yes | `AUTO` | `AUTO`, `BOUNDED`, or `FIXED` |
| `min_workers` | int \| null | No | 1 | Minimum worker count (BOUNDED/FIXED) |
| `max_workers` | int \| null | No | null | Max worker count (BOUNDED) |
| `min_connections` | int \| null | No | 1 | Per-worker floor (all modes) |
| `max_connections` | int \| null | No | null | Per-worker ceiling (BOUNDED) |

#### Representing "Unbounded" (Implementation Note)

- **In storage/API**: Use `null` to mean "no user-defined limit".
- **Accept `-1` as equivalent to `null`**: For consistency with existing
  `concurrent_connections=-1` pattern ("no cap").
- **Omitted fields**: Use defaults from table above.
- **In UI**: Display "No limit" placeholder for null/empty max fields.

```json
// Example: BOUNDED with only max_workers set (connections unbounded)
{
  "scaling": {
    "mode": "BOUNDED",
    "max_workers": 10
    // min_workers defaults to 1
    // min_connections defaults to 1  
    // max_connections defaults to null (use per_worker_cap)
  }
}
```

### Mode Behaviors

#### AUTO Mode (Default)

- Current behavior unchanged.
- Workers and connections computed from `concurrent_connections`, `target_qps`,
  or FIND_MAX config.
- `min_connections` still enforced as per-worker floor during scale-down.

#### BOUNDED Mode

- Auto-scaling operates within user-specified guardrails.
- QPS mode: Scale out until `max_workers × max_connections` ceiling is hit.
- FIND_MAX mode: Step-load capped at bounds; result marked `BOUNDED_MAX` if
  ceiling is reached.
- Orchestrator checks bounds before each scale-out decision.

#### FIXED Mode

- Exact resource allocation: `min_workers` workers, each with `min_connections`.
- No auto-scaling; worker count and connections are static for the entire run.
- Useful for reproducible benchmarks: `5×200` = 5 workers × 200 connections.
- `max_workers` and `max_connections` are ignored in FIXED mode.

### Validation Rules (Creation Time)

The orchestrator validates bounds at `create_run`:

1. **Impossible QPS**: If `target_qps` cannot be reached within bounds, reject
   with error: `"Target QPS {X} unreachable with max {W} workers × {C} connections"`
2. **Invalid ranges**: `min_workers > max_workers` or `min_connections > max_connections`
   → error.
3. **FIXED mode validation**: Both `min_workers` and `min_connections` must be
   specified.

### Runtime Behavior

#### QPS Mode with BOUNDED Scaling

If QPS mode cannot reach `target_qps` after N consecutive intervals at the
ceiling (`max_workers` at `max_connections`), the orchestrator:

1. Waits for `bounds_patience_intervals` (default: 3) consecutive intervals.
2. If still below target, sets `RUN_STATUS.STATUS = COMPLETED` with
   `COMPLETION_REASON = BOUNDS_LIMIT_REACHED`.
3. Records achieved QPS and the configured bounds in `TEST_RESULTS`.

#### FIND_MAX Mode with BOUNDED Scaling

If FIND_MAX hits the bounds ceiling before detecting saturation:

1. Continue stepping until stability thresholds are violated OR bounds are hit.
2. If bounds prevent further scaling, record:
   - `find_max_result.bounded = true`
   - `find_max_result.ceiling_reached = true`
   - `find_max_result.max_type = "BOUNDED_MAX"` (vs `"TRUE_MAX"` for unbounded)
3. The result message indicates: "Maximum within configured bounds (not system limit)".

### UI Integration

#### Template Configuration

- Show scaling mode selector (AUTO/BOUNDED/FIXED) in template editor.
- **AUTO mode**: Hide all worker/connection bounds fields (fully automatic).
- **BOUNDED mode**: Display all min/max fields for workers and connections.
- **FIXED mode**: Display singular "Workers" and "Connections" fields (no min/max
  labels), hide max fields entirely.
- **Resource Guardrails**: Show Max Host CPU % and Max Host Memory % fields for
  AUTO and BOUNDED modes only (not FIXED, since FIXED doesn't scale).
- Validate bounds client-side before submission.

#### Live Dashboard

- Show current bounds in run header when mode ≠ AUTO.
- Indicate when ceiling is reached: "At max workers (10/10)" or similar.
- FIND_MAX panel shows "BOUNDED_MAX" badge when bounds limit the result.

### Example Configurations

#### Reproducible High-Concurrency Test (FIXED)

```json
{
  "load_mode": "CONCURRENCY",
  "concurrent_connections": 1000,
  "scaling": {
    "mode": "FIXED",
    "min_workers": 5,
    "min_connections": 200
  }
}
```

Result: Exactly 5 workers, each with 200 connections (1000 total).

#### Bounded QPS Test

```json
{
  "load_mode": "QPS",
  "target_qps": 5000,
  "scaling": {
    "mode": "BOUNDED",
    "min_workers": 2,
    "max_workers": 10,
    "min_connections": 25,
    "max_connections": 500
  }
}
```

Result: Starts with 2 workers, scales up to 10 workers max, each worker scales
from 25 to 500 connections. If target cannot be reached at 10×500, run completes
with `BOUNDS_LIMIT_REACHED`.

---

## Resource Guardrails (Section 2.16)

Resource guardrails protect worker hosts from being overwhelmed during scaling.
Each worker reports its host's CPU and memory usage in its heartbeat, and the
orchestrator monitors these metrics to prevent resource exhaustion.

### Metric Sources

Workers report resource metrics with the following priority:

1. **cgroup metrics** (preferred for containers): `cgroup_cpu_percent`,
   `cgroup_memory_percent`
2. **Host metrics** (fallback): `host_cpu_percent`, `host_memory_percent`

For containerized deployments (SPCS, Docker), cgroup metrics reflect the
container's resource limits, which is more accurate than host-level metrics.

### Current Behavior (Hard Guardrails) — TO BE REPLACED

> **Note**: This section documents the current (legacy) behavior that will be
> replaced by soft guardrails per Section 2.16 of the project plan.

The orchestrator currently uses **hard guardrails**:

```sql
-- Current implementation (orchestrator.py)
SELECT MAX(COALESCE(CPU_PERCENT, 0)) AS max_cpu_percent,
       MAX(COALESCE(MEMORY_PERCENT, 0)) AS max_memory_percent
FROM WORKER_HEARTBEATS WHERE RUN_ID = ?
```

If **any single worker** exceeds the threshold, the entire run fails immediately:

```python
if max_cpu_seen >= max_cpu_percent:
    guardrail_reason = f"cpu_percent {max_cpu_seen:.2f} >= {max_cpu_percent:.2f}"
    # Emit STOP event, set STATUS = FAILED
```

**Problems with hard guardrails:**
- A single overloaded host fails the entire distributed run.
- No opportunity to redistribute load or scale out.
- Treats configurable targets as hard limits.
- Not suitable for heterogeneous environments.

### Desired Behavior (Soft Guardrails) — TO BE IMPLEMENTED

Soft guardrails treat resource thresholds as **targets** rather than hard limits,
enabling adaptive responses before failing the run.

#### Response Matrix

| Workers Over Threshold | Response |
|------------------------|----------|
| 0 | Normal operation |
| 1 to (N-1) | Back-off overloaded workers, redistribute, scale-out if possible |
| N (ALL) for < patience intervals | Warning state, continue monitoring |
| N (ALL) for >= patience intervals | Fail the run (true resource exhaustion) |

#### Adaptive Actions

When one or more workers exceed the threshold (but not all), the orchestrator
takes the following actions in order:

1. **Back-off (immediate)**: Emit `SCALE_DOWN` control event for overloaded
   worker(s), reducing their `TARGET_CONNECTIONS` by `back_off_percent`
   (default: 20%).

2. **Redistribute (if heterogeneous)**: If some workers have headroom, shift
   load from overloaded workers. This is a future enhancement; initial
   implementation focuses on back-off + scale-out.

3. **Scale-out (if bounds allow)**: If `scaling.mode` is AUTO or BOUNDED and
   worker count is below `max_workers`, spawn a new worker to absorb the shed
   load.

4. **Graceful degradation**: If scale-out is not possible (FIXED mode or at
   bounds ceiling), continue at reduced capacity with a warning. The run
   succeeds but may not reach target QPS.

5. **Fail (last resort)**: Only if ALL workers exceed thresholds for
   `patience_intervals` consecutive poll cycles, fail the run with
   `COMPLETION_REASON = RESOURCE_EXHAUSTION`.

#### Guardrails Configuration Schema

```json
{
  "guardrails": {
    "max_cpu_percent": 80,
    "max_memory_percent": 85,
    "mode": "soft",
    "back_off_percent": 20,
    "patience_intervals": 3,
    "fail_threshold": "all"
  }
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `max_cpu_percent` | float | 80 | CPU threshold (0-100) |
| `max_memory_percent` | float | 85 | Memory threshold (0-100) |
| `mode` | enum | `soft` | `soft` (adaptive) or `hard` (legacy fail-fast) |
| `back_off_percent` | int | 20 | % to reduce TARGET_CONNECTIONS on back-off |
| `patience_intervals` | int | 3 | Intervals before taking action or failing |
| `fail_threshold` | enum | `all` | `all`, `majority`, or `any` |

**`fail_threshold` options:**
- `all`: Only fail if ALL workers exceed thresholds (recommended).
- `majority`: Fail if >50% of workers exceed thresholds.
- `any`: Fail if ANY worker exceeds (legacy behavior, same as `mode: hard`).

#### State Tracking

The orchestrator tracks soft guardrail state in `RUN_STATUS.CUSTOM_METRICS`:

```json
{
  "soft_guardrails": {
    "workers_over_cpu": ["worker-2"],
    "workers_over_memory": [],
    "over_threshold_intervals": 1,
    "actions_taken": [
      {
        "timestamp": "2024-01-15T10:30:00Z",
        "action": "back_off",
        "worker_id": "worker-2",
        "previous_target": 500,
        "new_target": 400
      }
    ],
    "state": "warning"
  }
}
```

**States:**
- `normal`: No workers over threshold.
- `warning`: Some workers over threshold, adaptive actions in progress.
- `critical`: All workers over threshold, approaching failure.
- `degraded`: Running at reduced capacity due to resource constraints.

#### Control Events

New control events for soft guardrails:

```json
// Back-off event
{
  "event_type": "SCALE_DOWN",
  "event_data": {
    "scope": "WORKER",
    "worker_id": "worker-2",
    "reason": "soft_guardrail",
    "detail": "cpu_percent 85.2 >= 80.0",
    "previous_target_connections": 500,
    "new_target_connections": 400
  }
}

// Warning event (no action yet, just monitoring)
{
  "event_type": "GUARDRAIL_WARNING",
  "event_data": {
    "scope": "RUN",
    "workers_over_threshold": ["worker-2"],
    "threshold_type": "cpu",
    "intervals_remaining": 2
  }
}
```

#### UI Indicators

| State | Indicator | Color |
|-------|-----------|-------|
| Normal | (none) | - |
| Warning | "1/4 workers over CPU threshold" | Yellow |
| Critical | "All workers over threshold (2/3 intervals)" | Orange |
| Degraded | "Running at reduced capacity" | Yellow + info icon |
| Failed | "Resource exhaustion" | Red |

#### Interaction with Scaling Modes

| Scaling Mode | Soft Guardrail Behavior |
|--------------|------------------------|
| AUTO | Back-off + unlimited scale-out |
| BOUNDED | Back-off + scale-out up to max_workers |
| FIXED | Back-off only (no scale-out), may degrade |

For FIXED mode, soft guardrails still provide value by allowing the run to
continue at reduced capacity rather than failing immediately.

#### Migration from Hard to Soft

Existing configurations with `autoscale_max_cpu_percent` and
`autoscale_max_memory_percent` are automatically migrated to the new format:

```json
// Old format (deprecated, auto-migrated)
{
  "autoscale_enabled": true,
  "autoscale_max_cpu_percent": 80,
  "autoscale_max_memory_percent": 85
}

// New format
{
  "scaling": { "mode": "AUTO" },
  "guardrails": {
    "max_cpu_percent": 80,
    "max_memory_percent": 85,
    "mode": "soft"
  }
}
```

**Migration Complete**: The `autoscale_enabled` checkbox has been removed from
the UI. Its functionality is now controlled by `scaling.mode`:

- **AUTO**: Equivalent to `autoscale_enabled: true` — fully automatic scaling
  with resource guardrails.
- **BOUNDED**: Auto-scale within user-specified min/max bounds with guardrails.
- **FIXED**: Equivalent to `autoscale_enabled: false` — exact worker × connection
  allocation with no scaling (guardrails hidden since no scaling occurs).
