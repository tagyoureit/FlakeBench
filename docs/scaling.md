# Scaling & Concurrency Model

Last updated: 2026-01-21

This document explains how Unistore Benchmark generates load, why
connection/thread settings matter, and what to do when you want to simulate
thousands of end users without client-side queueing.

## How load is generated (today)

- The benchmark workload uses the Snowflake Python connector, which is
  synchronous/blocking.
- The FastAPI app is async, so all Snowflake calls are run via asyncio thread
  executors (see backend/connectors/snowflake_pool.py).
- Each "concurrent connection" in a scenario maps to a connection slot that executes
  operations; to avoid client-side queueing, the benchmark must have enough
  capacity to run those blocking calls without waiting on a shared thread pool.

## Implementation details that matter

- High-concurrency startup must avoid a connection stampede (many connection
  slots all calling `connect()` at once). The Snowflake pool caps parallel
  connection creates so startup doesn’t overwhelm the client.
- Results/persistence work is isolated from benchmark work via separate thread
  executors:
  - Results pool: `SNOWFLAKE_RESULTS_EXECUTOR_MAX_WORKERS`
  - Per-test benchmark pool: executor sized to requested concurrency (bounded by
    `SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS` as a safety cap)
- The per-test Snowflake pool targets max connections == requested concurrency
  to avoid application-side queueing caused by an undersized pool.
- Live + history dashboards include resource telemetry:
  - Per-process CPU/memory (benchmark worker process)
  - Host CPU/memory, cgroup-aware when running in containers

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

## Why a single worker won’t reliably simulate thousands (with the current connector)

Because the Snowflake Python connector is synchronous, high concurrency requires
either:
- a very large thread pool (eventually hits OS/thread/memory limits), or
- multiple processes/workers, each with a bounded thread pool, so the overall
  system can scale horizontally.

If you request a scenario concurrency higher than
SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS, the app will log a warning and
proceed. You are responsible for ensuring OS/thread/memory headroom.

## Recommended approach for thousands of simulated end users

### Target model

- Keep the UI / controller (FastAPI app) responsive and stable
- Run one or more benchmark workers that generate load against Snowflake
- Aggregate metrics back to the results tables and/or stream summary metrics to
  the UI

### QPS autoscale across workers

- In QPS mode, `concurrent_connections` is treated as the per-worker max connections
  (worker ceiling). Autoscale adds workers only after each worker reaches that ceiling
  and total QPS is still below target.
- Total target QPS is split evenly across workers:
  `target_qps_per_worker = target_qps_total / worker_count`.
- If you don’t know the worker ceiling, run a single-worker
  `FIND_MAX_CONCURRENCY` test to measure it and then set that value as the QPS
  max workers in the template.

### Practical sizing guideline

- Pick a per-worker concurrency that is reliable on your hardware (commonly a few
  hundred).
- Run N workers to reach the desired total simulated concurrency.

Example:
- Desired: 2,000 simulated users
- Run: 8 workers × 250 concurrency each

This avoids client-side queueing while still allowing Snowflake/warehouse-side
queueing (which is what you want to observe when the warehouse is undersized).

## Real-time capacity testing (per worker)

To find the true ceiling of a given machine:

1. Use load_mode=FIND_MAX_CONCURRENCY to step up workers until latency/error
   guardrails trip.
2. Watch CPU and memory in real time:
   - Process-level CPU/memory for the benchmark worker
   - Host-level CPU/memory (cgroup-aware when container limits apply)
3. Record the best sustainable concurrency for that machine, and use it as your
   per-worker baseline.

This keeps the concurrency target resource-driven, not tied to arbitrary limits.

### Recommended staging order

1. Find the single-worker ceiling using FIND_MAX_CONCURRENCY and host/cgroup
   metrics.
2. Use that per-worker ceiling to size a multi-worker run.
3. Implement orchestration (local first, then SPCS/K8s).

## Value pool sharding across worker groups

When scaling across multiple processes or workers, workers must avoid overlapping
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

## Multi-worker orchestration (current)

Multi-worker runs are supported in two ways:

### UI-driven autoscale (scale-out only)

- Orchestration loop: `backend/core/autoscale.py`
- Behavior:
  - Prepares a parent run first.
  - Spawns worker processes using `uv run python scripts/run_worker.py ...`.
  - Uses host-level guardrails (CPU/memory) based on telemetry stored in
    `NODE_METRICS_SNAPSHOTS` (cgroup-aware when available).
  - Writes autoscale state into `TEST_RESULTS.CUSTOM_METRICS.autoscale_state`.

### Headless local orchestration (CLI)

- Orchestrator: `scripts/run_multi_node.py` (spawns N local workers)
- Worker: `scripts/run_worker.py` (runs one headless worker from a template id)
- Parent aggregation:
  - `backend/core/results_store.py:update_parent_run_aggregate`
  - Manual trigger: `scripts/refresh_parent_aggregate.py`

## SLO-safe aggregation guidance (multi-worker)

- Do not use weighted averages for SLO decisions; they can mask slow workers or tails.
- For latency SLOs, prefer:
  - merged distributions (global p95/p99 from combined samples or histograms), or
  - worst-worker p95/p99 (guardrail for heterogeneous workers).

## Remote orchestration (design considerations)

If/when running workers remotely (K8s/SPCS/etc), keep the invariants:

- Each worker must have a stable `worker_group_id` and `worker_group_count` for
  deterministic sharding.
- Prefer cgroup-aware host telemetry for capacity/guardrail decisions.
- Preserve the “no client-side queueing” goal: per-worker benchmark executors
  should be sized to the per-worker concurrency target.
