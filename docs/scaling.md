# Scaling & Concurrency Model

This document explains how Unistore Benchmark generates load, why
connection/thread settings matter, and what to do when you want to simulate
thousands of end users without client-side queueing.

## How load is generated (today)

- The benchmark workload uses the Snowflake Python connector, which is
  synchronous/blocking.
- The FastAPI app is async, so all Snowflake calls are run via asyncio thread
  executors (see backend/connectors/snowflake_pool.py).
- Each "concurrent connection" in a scenario maps to a worker that executes
  operations; to avoid client-side queueing, the benchmark must have enough
  capacity to run those blocking calls without waiting on a shared thread pool.

## What changed (2026-01)

- The Snowflake pool now prevents a high-concurrency connection stampede
  (many workers simultaneously creating new connections).
- Each Snowflake pool can use its own thread executor:
  - Results pool (persistence / UI reads) uses
    SNOWFLAKE_RESULTS_EXECUTOR_MAX_WORKERS
  - Benchmark per-test pool uses a dedicated executor sized to the scenario's
    requested concurrency (with SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS acting
    as a default safety cap)
- The per-test Snowflake pool is sized so max connections == requested
  concurrency (no application-side queueing due to an undersized pool).
- Live + history dashboards now include resource telemetry for both:
  - Per-process CPU/memory (benchmark worker process)
  - Host CPU/memory, with cgroup-aware limits when running in containers

## Key settings

### Results (persistence) pool

- SNOWFLAKE_POOL_SIZE, SNOWFLAKE_MAX_OVERFLOW: results/persistence pool sizing
  (writes to TEST_RESULTS.*)
- SNOWFLAKE_RESULTS_EXECUTOR_MAX_WORKERS: threads reserved for
  results/persistence Snowflake work

### Benchmark (workload) pool

- SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS: default safety cap for benchmark
  workload Snowflake threads (configurable)
- SNOWFLAKE_POOL_MAX_PARALLEL_CREATES: caps concurrent connect() calls so
  startup doesn't overwhelm the client

## Why a single node won’t reliably simulate thousands (with the current connector)

Because the Snowflake Python connector is synchronous, high concurrency requires
either:
- a very large thread pool (eventually hits OS/thread/memory limits), or
- multiple processes/nodes, each with a bounded thread pool, so the overall
  system can scale horizontally.

If you request a scenario concurrency higher than
SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS, the app will log a warning and
proceed. You are responsible for ensuring OS/thread/memory headroom.

## Recommended approach for thousands of simulated end users

### Target model

- Keep the UI / controller (FastAPI app) responsive and stable
- Run one or more benchmark worker nodes that generate load against Snowflake
- Aggregate metrics back to the results tables and/or stream summary metrics to
  the UI

### Practical sizing guideline

- Pick a per-node concurrency that is reliable on your hardware (commonly a few
  hundred).
- Run N nodes to reach the desired total simulated concurrency.

Example:
- Desired: 2,000 simulated users
- Run: 8 worker nodes × 250 concurrency each

This avoids client-side queueing while still allowing Snowflake/warehouse-side
queueing (which is what you want to observe when the warehouse is undersized).

## Real-time capacity testing (per node)

To find the true ceiling of a given machine:

1. Use load_mode=FIND_MAX_CONCURRENCY to step up workers until latency/error
   guardrails trip.
2. Watch CPU and memory in real time:
   - Process-level CPU/memory for the benchmark worker
   - Host-level CPU/memory (cgroup-aware when container limits apply)
3. Record the best sustainable concurrency for that machine, and use it as your
   per-node baseline.

This keeps the concurrency target resource-driven, not tied to arbitrary limits.

### Recommended staging order

1. Find the single-node ceiling using FIND_MAX_CONCURRENCY and host/cgroup
   metrics.
2. Use that per-node ceiling to size a multi-node run.
3. Implement orchestration (local first, then SPCS/K8s).

## Value pool sharding across worker groups

When scaling across multiple processes or nodes, workers must avoid overlapping
value pools to prevent result-cache artifacts and unrealistic hot-spotting.

We support deterministic sharding using two scenario fields:

- worker_group_id: index of this worker group (0-based)
- worker_group_count: total number of worker groups

Each worker uses a global stride based on:

```text
global_stride = concurrent_connections * worker_group_count
global_worker_id = (worker_group_id * concurrent_connections) + local_worker_id
```

This assumes each group uses the same local concurrency. If you need variable
per-group concurrency, use separate test runs or adjust the sharding scheme.

## Find Max Concurrency (step-load) mode: live dashboard metrics

When load_mode=FIND_MAX_CONCURRENCY, the benchmark runs a step-load controller
that increases (or backs off) the worker count to find the maximum sustainable
concurrency.

The dashboard surfaces additional live controller metrics:

- Established P95 baseline: step 1’s p95 latency (used as a baseline target)
- Current P95: rolling end-to-end p95 latency for the current step
- % difference: delta vs the baseline
- P95 max threshold: baseline + (2 × latency_stability_pct) (matches the
  controller’s baseline drift guardrail)
- Workers current → next: current step target and the next planned target, with
  a countdown to the end-of-step decision
- Conclusion reason: plain-text reason for why the controller stopped/completed
  (persisted to results)

## Next steps (if you want the app to orchestrate multi-node runs)

If you want the UI to start/stop multiple worker nodes and aggregate their
metrics in one dashboard run, we should add:
- a worker process mode (no web UI) that accepts a test payload and runs it
- an orchestration layer (local multi-process or remote multi-node)
- metrics aggregation (sum ops, merge latency distributions)

## Multi-node orchestration plan (technical)

### Decisions

- Orchestrator: separate CLI tool (preferred for local)
- Aggregated results: stored in existing TEST_RESULTS tables
- Per-node metrics: stored in a new table
- UI: include per-node drilldown (tab or accordion)

### Phase 0: Baseline & constraints

- Find per-node ceilings using FIND_MAX_CONCURRENCY with host + cgroup metrics.
- Establish target total concurrency and per-node baseline.

### Phase 1: Worker process mode (headless)

- Add a worker entrypoint that runs a test scenario without UI.
- Inputs: scenario payload (same as existing API) + worker_group_id +
  worker_group_count + optional parent_run_id.
- Outputs: per-second snapshots + final summary persisted to results store.

### Phase 2: Orchestration (local first)

- CLI orchestrator launches N worker processes (worker_group_id = 0..N-1).
- Distributes the same scenario payload (deterministic sharding already in place).
- Tracks lifecycle and aggregates status/results.

### Phase 3: Metrics aggregation

- Aggregate across worker groups:
  - Sum rates (ops/sec), counts, errors
  - Merge latency distributions (prefer histograms or sample sets)
  - Aggregate resource metrics as separate views (per-node + total)
- Persist aggregates in existing TEST_RESULTS tables (parent run id).
- Persist per-node snapshots in a new table keyed by parent_run_id + worker_group_id.

### Phase 4: API + UI integration

- API endpoints:
  - Create multi-node run
  - Fetch aggregate metrics (live + history)
  - Fetch per-node metrics (drilldown)
- UI:
  - Show aggregated metrics by default
  - Add per-node drilldown (tab/accordion)

### Phase 5: K8s / SPCS readiness

- Containerize worker mode if needed.
- Define K8s / SPCS spec for N replicas with worker_group_id/count.
- Use cgroup-aware resource metrics for capacity planning.

### Phase 6: Validation & runbooks

- Add smoke flow for multi-node mode.
- Document runbooks:
  - Single-node max
  - Multi-node orchestration (local)
  - SPCS deployment
