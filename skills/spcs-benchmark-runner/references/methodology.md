# Benchmark Methodology

Empirically derived constraints for comparing table types and warehouse
configurations with FlakeBench. Each rule below was established by measurement,
not assumption.

## Rotate run order — always

The single largest source of false results is **cache-warmth aliasing**. Whichever
configuration runs first benefits from an uncontended warehouse data cache, and
that advantage is large enough to invert a verdict.

Observed: comparing an interactive table against a clustered standard table in a
fixed order produced a 7.8% advantage for the interactive table, with clean
separation across three trials each. Re-running the identical matrix in rotated
order **reversed the sign** — the standard table then led. Pooling all runs, the
difference collapsed to 3.4% with fully overlapping ranges, i.e. no difference.

Use `run_sequence.py --order latin-square`, which runs N cycles of N templates so
each configuration occupies each within-cycle position exactly once.

A symptom of this problem: one configuration's throughput declining monotonically
across trials while another's stays flat.

## Know the noise floor before believing a difference

With 750-second runs, warm caches, and rotated ordering, run-to-run throughput
variation is roughly **6% CV** (standard deviation ~30 QPS on a mean of ~490).

Consequences:

- Treat any difference under ~10% as unresolved.
- Detecting a 3–4% difference at 80% power needs roughly **55 runs per
  configuration**. If the effect you care about is that small, it is not
  practically measurable at this scale — report it as "no measurable difference"
  rather than accumulating runs.
- Compare **medians across trials**, never single runs.

## Choose the metric to match the load point

At saturation, tail latency is pinned by queueing and becomes identical across
configurations. Measured at 45 connections on a Medium interactive warehouse,
three materially different table layouts all produced p95 of 147–153 ms while
their throughput differed by 19%.

| Goal | Load point | Metric |
|------|-----------|--------|
| Capacity / throughput ceiling | Past the saturation knee | QPS, plus p50 |
| Per-query latency | Well below the knee (~20 connections) | p50, p95 |

**Do not quote p95 as a discriminator from a saturated run.** Use QPS and p50.

## Separate server-side execution from end-to-end latency

`TEST_RESULTS.P50/P95/P99_LATENCY_MS` are end-to-end: client scheduling, network
round trip, Snowflake compilation, and execution. Engine differences can be
almost entirely hidden inside the other three terms. Isolate execution with
`QUERY_EXECUTIONS.SF_EXECUTION_MS` (Snowflake's `QUERY_HISTORY.EXECUTION_TIME`).

In the interactive zero-copy comparison, an unclustered table was **6.7x** slower
than a clustered one server-side at p50 and **7.7x** at p95, but only **1.4x** and
**1.0x** end-to-end. Median decomposition for the tuned configurations was 7 ms
execution, 27 ms compilation, ~37 ms client and network — execution was under a
tenth of what the application waited for.

Two traps:

- **`QUERY_EXECUTIONS` is keyed by the per-worker `TEST_ID`, not the aggregate
  run's.** Filtering on the aggregate `TEST_ID` silently returns zero rows. Join
  the aggregate row to its worker rows on `RUN_ID`:

  ```sql
  SELECT w.TEST_ID AS worker_id
  FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS w
  WHERE w.RUN_ID = ? AND w.CONCURRENT_CONNECTIONS < (
    SELECT CONCURRENT_CONNECTIONS FROM FLAKEBENCH.TEST_RESULTS.TEST_RESULTS
    WHERE TEST_ID = ?)
  ```

  Always filter `COALESCE(WARMUP, FALSE) = FALSE AND SUCCESS = TRUE`, and check
  `COUNT(SF_EXECUTION_MS) / COUNT(*)` — enrichment can be partial.

- **Client overhead scales with throughput, not with table quality.** A faster
  configuration pushes more traffic and so queues more on the client, inflating
  its own end-to-end numbers. End-to-end comparisons therefore *understate* the
  advantage of the better configuration.

`SF_EXECUTION_MS` has integer-millisecond resolution. Do not report 1–2 ms
differences as meaningful without saying so, even when they are significant.

## Pick a load point that can actually show a difference

Below saturation, every configuration returns the same throughput because nothing
is contended — the measurement is uninformative. Find each configuration's
saturation knee first (a `FIND_MAX_CONCURRENCY` ramp is a cheap way to do this),
then fix concurrency just past the weakest configuration's knee.

## Warm up for more than a few seconds

A running warehouse is not a warm warehouse. Two caches warm independently of
warehouse state:

- **Data cache** (per table, per micro-partition): first-vs-second execution of
  an identical query measured 342 ms then 28 ms.
- **Compile / metadata cache** (per query shape): 649 ms then 129 ms.

Both were observed on a warehouse that had been running for hours. Newly attached
tables warm lazily, because warming prioritises partitions needed by live queries
over background population of attached tables.

Set `warmup` to at least 30 seconds. A 5-second warmup leaves cold outliers in
the measurement window, concentrated in the tail.

## Avoid baseline-relative stop conditions

`FIND_MAX_CONCURRENCY` stops when p95 exceeds a percentage of the step-1
baseline. Because step 1 is a single cold worker, a noisy baseline sets the
threshold.

Observed: identical interactive-table configurations stopped at 41 versus 66
workers purely because one baseline was a cold 112 ms and the other a clean
71 ms. A *worse* baseline buys a run more headroom, which inverts the metric's
meaning.

Peak QPS from a ramp is trustworthy. Maximum concurrency from a ramp is not
comparable across runs. For head-to-head comparison, prefer fixed concurrency
(`CONCURRENCY` load mode).

## Hold data layout constant when comparing table types

Clustering dominates table type. Comparing a clustered standard table against an
unclustered one on the same warehouse and query: **+19% throughput and −30% p50**
for the clustered copy, with no overlap between the two groups.

If the comparison is about table *type*, both tables must carry equivalent
clustering, or the result measures layout instead. Verify with
`SYSTEM$CLUSTERING_INFORMATION` — check `average_depth` is comparable (≈1.0 for a
well-clustered table) before trusting a table-type conclusion.

Note that automatic clustering, including Optima Clustering, never starts on its
own: it requires a user-defined clustering key. An unclustered table stays
unclustered indefinitely.
