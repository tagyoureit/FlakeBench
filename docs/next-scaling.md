# Multi-Node Scaling (Proposed)

This document describes how the benchmark scales to N workers and how it manages
concurrency limits. It intentionally repeats key constraints for clarity.

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
- **Caps**: Bounded by host/cgroup CPU and memory guardrails.
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
- **Worker Calculation**: Always multi-node (orchestrator path even when
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
- **Latency aggregation**: Uses worst-worker P95/P99 (MAX across workers) for
    conservative saturation detection. See `next-data-flow-and-lifecycle.md`,
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
- Scale-out caps are based on **host/cgroup CPU and memory guardrails** (SPCS
  limits later).
- FIND_MAX is **multi-node only**, using aggregated metrics for stability checks.
- Workers are expected to be **homogeneous**; no per-worker capacity skew.
- **No rebalancing** of existing worker allocations when scaling out.
- **Warmup is run-level**: Workers joining after warmup ends start directly in
  MEASUREMENT phase.

Note: `FIND_MAX` refers to `FIND_MAX_CONCURRENCY`.

---

## Single-Node Code to Remove/Refactor

> **Migration note:** The following single-node patterns must be eliminated or
> refactored to always go through the multi-node orchestrator (even for N=1).

- `backend/main.py`: Direct `TestExecutor` invocation without orchestrator.
  Route through orchestrator.
- `backend/core/autoscale.py`: Subprocess spawning via `uv run`. Replace with
  orchestrator worker dispatch.
- `autoscale.py:288`: Local process management (`asyncio.create_subprocess_exec`).
  Replace with container/K8s job dispatch.
- `test_executor.py:1709-2447`: Single-node FIND_MAX loop. Refactor for
  multi-node coordination.
- `autoscale.py:419`: `per_node_concurrency` derived from
  `scenario.concurrent_connections`. Use explicit config or orchestrator
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
def compute_worker_targets(total_connections: int, worker_count: int) -> dict[str, int]:
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
- Templates remain stored in `UNISTORE_BENCHMARK.CONFIG.TEST_TEMPLATES` and
  drive all runs.
