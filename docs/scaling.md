# Scaling & Concurrency Model

This document explains how Unistore Benchmark generates load, why connection/thread settings matter, and what to do when you want to simulate **thousands** of end users without client-side queueing.

## How load is generated (today)

- The benchmark workload uses the **Snowflake Python connector**, which is **synchronous/blocking**.
- The FastAPI app is **async**, so all Snowflake calls are run via `asyncio` thread executors (see `backend/connectors/snowflake_pool.py`).
- Each "concurrent connection" in a scenario maps to a worker that executes operations; to avoid **client-side queueing**, the benchmark must have enough capacity to run those blocking calls without waiting on a shared thread pool.

## What changed (2026-01)

- The Snowflake pool now prevents a high-concurrency **connection stampede** (many workers simultaneously creating new connections).
- Each Snowflake pool can use its **own** thread executor:
  - **Results pool** (persistence / UI reads) uses `SNOWFLAKE_RESULTS_EXECUTOR_MAX_WORKERS`
  - **Benchmark per-test pool** uses a dedicated executor sized to the scenario's requested concurrency (up to `SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS`)
- The per-test Snowflake pool is sized so **max connections == requested concurrency** (no application-side queueing due to an undersized pool).

## Key settings

### Results (persistence) pool

- `SNOWFLAKE_POOL_SIZE`, `SNOWFLAKE_MAX_OVERFLOW`: results/persistence pool sizing (writes to `TEST_RESULTS.*`)
- `SNOWFLAKE_RESULTS_EXECUTOR_MAX_WORKERS`: threads reserved for results/persistence Snowflake work

### Benchmark (workload) pool

- `SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS`: maximum threads this node will allocate for **benchmark workload** Snowflake calls
- `SNOWFLAKE_POOL_MAX_PARALLEL_CREATES`: caps concurrent `connect()` calls so startup doesn't overwhelm the client

## Why a single node won’t reliably simulate “thousands” (with the current connector)

Because the Snowflake Python connector is synchronous, high concurrency requires either:
- a very large thread pool (eventually hits OS/thread/memory limits), or
- **multiple processes/nodes**, each with a bounded thread pool, so the overall system can scale horizontally.

If you request a scenario concurrency higher than `SNOWFLAKE_BENCHMARK_EXECUTOR_MAX_WORKERS`, the app will fail fast with a clear error asking you to scale out (multi-process/multi-node) or raise the limit.

## Recommended approach for thousands of simulated end users

### Target model

- Keep the **UI / controller** (FastAPI app) responsive and stable
- Run one or more **benchmark worker nodes** that generate load against Snowflake
- Aggregate metrics back to the results tables and/or stream summary metrics to the UI

### Practical sizing guideline

- Pick a **per-node** concurrency that is reliable on your hardware (commonly a few hundred).
- Run **N nodes** to reach the desired total simulated concurrency.

Example:
- Desired: 2,000 simulated users
- Run: 8 worker nodes × 250 concurrency each

This avoids client-side queueing while still allowing Snowflake/warehouse-side queueing (which is what you want to observe when the warehouse is undersized).

## Find Max Concurrency (step-load) mode: live dashboard metrics

When `load_mode=FIND_MAX_CONCURRENCY`, the benchmark runs a step-load controller that increases (or backs off) the worker count to find the maximum sustainable concurrency.

The dashboard surfaces additional live controller metrics:

- **Established P95 baseline**: step 1’s p95 latency (used as a baseline target)
- **Current P95**: rolling end-to-end p95 latency for the current step
- **% difference**: delta vs the baseline
- **P95 max threshold**: baseline + \(2 \times\) `latency_stability_pct` (matches the controller’s baseline drift guardrail)
- **Workers current → next**: current step target and the next planned target, with a countdown to the end-of-step decision
- **Conclusion reason**: plain-text reason for why the controller stopped/completed (persisted to results)

## Next steps (if you want the app to orchestrate multi-node runs)

If you want the UI to start/stop multiple worker nodes and aggregate their metrics in one dashboard run, we should add:
- a worker process mode (no web UI) that accepts a test payload and runs it
- an orchestration layer (local multi-process or remote multi-node)
- metrics aggregation (sum ops, merge latency distributions)




