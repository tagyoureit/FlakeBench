# Metrics Tracking for Analytical Workloads

How to extend metrics collection for meaningful analytical benchmark results under
the simplified runtime contract.

## Runtime Contract

Runtime query kinds are:
- `POINT_LOOKUP`
- `RANGE_SCAN`
- `INSERT`
- `UPDATE`
- `GENERIC_SQL`

Analytical behavior is represented by `GENERIC_SQL` entries. Optional
per-query labels are user-defined metadata and must not be treated as required
runtime enums.

## Core Metrics (Keep)

The existing OLTP metrics remain first-class:
- latency (`p50`, `p95`, `p99`)
- throughput (`ops/sec`)
- error rate
- read/write operation counts

## Analytical Metrics (Add)

### 1) Correctness + Methodology Metadata

Persist benchmark context with each run:
- `correctness_gate_passed` (bool)
- `correctness_failures` (count)
- `approx_error_pct_p50`, `approx_error_pct_p95` (when cardinality checks are used)
- `run_temperature` (`cold`/`warm`)
- `trial_index`, `trial_count`
- `seed`
- `confidence_level`, `confidence_interval_pct`

### 2) Throughput + Efficiency Metrics

Track these per runtime kind (`GENERIC_SQL` included):
- rows produced / processed
- bytes scanned
- rows/sec
- bytes scanned/sec
- bytes spilled (local/remote)

```python
self._rows_processed_by_kind: dict[str, int] = {
    "POINT_LOOKUP": 0,
    "RANGE_SCAN": 0,
    "INSERT": 0,
    "UPDATE": 0,
    "GENERIC_SQL": 0,
}

self._bytes_scanned_by_kind: dict[str, int] = {
    "POINT_LOOKUP": 0,
    "RANGE_SCAN": 0,
    "INSERT": 0,
    "UPDATE": 0,
    "GENERIC_SQL": 0,
}
```

### 3) Snowflake Query-Profile Metrics

Capture per-query profile fields when available:
- `compilation_time_ms`
- `queue_time_ms`
- `rows_produced`
- `bytes_scanned`
- `partitions_scanned`
- `partitions_total`
- `bytes_spilled_local`
- `bytes_spilled_remote`

```sql
SELECT
  QUERY_ID,
  EXECUTION_TIME,
  COMPILATION_TIME,
  QUEUED_PROVISIONING_TIME,
  QUEUED_OVERLOAD_TIME,
  ROWS_PRODUCED,
  BYTES_SCANNED,
  PARTITIONS_SCANNED,
  PARTITIONS_TOTAL
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_ID = ?;
```

## Executor Tracking Changes

Keep kind-indexed arrays/maps and ensure `GENERIC_SQL` is included in all of them:

```python
self._lat_by_kind_ms: dict[str, list[float]] = {
    "POINT_LOOKUP": [],
    "RANGE_SCAN": [],
    "INSERT": [],
    "UPDATE": [],
    "GENERIC_SQL": [],
}
```

If label-level reporting is needed, track it separately:

```python
self._lat_by_generic_label_ms: dict[str, list[float]] = {}
```

## FIND_MAX_CONCURRENCY SLO Contract

Continue using per-kind SLOs:
- OLTP shortcut kinds use existing tight latency targets
- `GENERIC_SQL` uses one default SLO bucket
- optional label overrides may be added as a second layer (label-specific tuning)

```python
fmc_slo_by_kind = {
    "POINT_LOOKUP": {...},
    "RANGE_SCAN": {...},
    "INSERT": {...},
    "UPDATE": {...},
    "GENERIC_SQL": {
        "target_p95_ms": 5000,
        "target_p99_ms": 10000,
        "target_err_pct": 1.0,
    },
}
```

## Storage Model

Use **core columns + VARIANT**:

1. Core columns for high-value dashboard/SLO fields
2. `olap_metrics VARIANT` for extensible deep details

Recommended core additions:
- `generic_sql_count`
- `generic_sql_p95_latency_ms`
- `generic_sql_p99_latency_ms`
- `generic_sql_rows_per_sec`
- `generic_sql_bytes_scanned_per_sec`
- aggregate OLAP rollups:
  - `olap_total_operations`
  - `olap_total_rows_processed`
  - `olap_total_bytes_scanned`

Example `olap_metrics` payload:

```json
{
  "GENERIC_SQL": {
    "p50_ms": 1200.0,
    "p95_ms": 2800.0,
    "p99_ms": 4500.0,
    "rows_per_sec": 185000.0,
    "bytes_scanned_per_sec": 22400000.0,
    "avg_compile_ms": 140.0,
    "avg_queue_ms": 12.0
  },
  "GENERIC_LABELS": {
    "monthly_rollup": {
      "p95_ms": 3100.0,
      "rows_per_sec": 120000.0
    },
    "cardinality_check": {
      "p95_ms": 900.0,
      "approx_error_pct_p95": 1.8
    }
  },
  "METHODOLOGY": {
    "cache_policy": "INHERITED",
    "warmup_strategy": "INHERITED",
    "confidence_level": 0.95,
    "confidence_interval_pct": 4.2
  }
}
```

## Dashboard and Comparison Updates

### Shallow Compare

Expose:
- existing OLTP metrics
- `GENERIC_SQL` latency/throughput summary fields
- aggregate OLAP totals

### Deep Compare

Add:
- per-kind trend lines including `GENERIC_SQL`
- optional per-label view for `GENERIC_SQL` entries
- throughput timelines (`rows/sec`, `bytes/sec`)

## Backward Compatibility

- Existing OLTP metrics stay unchanged.
- New analytical fields are additive.
- API responses default missing new fields to `null`/`0`.
- Historical runs without `GENERIC_SQL` remain valid.

