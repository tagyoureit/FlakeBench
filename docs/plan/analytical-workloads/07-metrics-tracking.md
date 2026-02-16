# Metrics Tracking for Analytical Workloads

How to extend metrics collection for meaningful analytical benchmark results.

## Current Metrics

The existing system tracks per-query-kind metrics optimized for OLTP:

| Metric | Purpose | Relevance to Analytics |
|--------|---------|----------------------|
| Latency (p50, p95, p99) | Response time | Important |
| Operations/second | Throughput | Less meaningful for slow queries |
| Error rate | Reliability | Important |
| Query count | Volume | Important |

## New Metrics for Analytics

### 1. Throughput Metrics

**Rows per second:** Better than ops/sec for analytical workloads.

```python
# Add to TestExecutor
self._rows_processed_by_kind: dict[str, int] = {
    "AGGREGATION": 0,
    "WINDOWED": 0,
    "ANALYTICAL_JOIN": 0,
    "WIDE_SCAN": 0,
    "APPROX_DISTINCT": 0,
}

# Update after query execution
def _update_throughput_metrics(
    self,
    query_kind: str,
    rows_returned: int,
    bytes_scanned: int
):
    if query_kind in self._rows_processed_by_kind:
        self._rows_processed_by_kind[query_kind] += rows_returned
        self._bytes_scanned_by_kind[query_kind] += bytes_scanned
```

**Bytes scanned per second:** Measures I/O efficiency.

```python
self._bytes_scanned_by_kind: dict[str, int] = {
    "AGGREGATION": 0,
    "WINDOWED": 0,
    "ANALYTICAL_JOIN": 0,
    "WIDE_SCAN": 0,
    "APPROX_DISTINCT": 0,
}
```

### 2. Query Profile Metrics

Snowflake provides detailed query statistics via `QUERY_HISTORY`:

```sql
SELECT 
    QUERY_ID,
    EXECUTION_TIME,        -- Total execution time (ms)
    COMPILATION_TIME,      -- Query compilation time (ms)
    QUEUED_PROVISIONING_TIME,  -- Wait for warehouse (ms)
    QUEUED_OVERLOAD_TIME,  -- Queue due to concurrency (ms)
    BYTES_SCANNED,
    ROWS_PRODUCED,
    PARTITIONS_SCANNED,
    PARTITIONS_TOTAL
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE QUERY_ID = ?;
```

**Add to metrics:**
- `compilation_time_ms`: Important for understanding Snowflake overhead
- `queue_time_ms`: Warehouse contention
- `partitions_scanned`: Clustering efficiency

```python
@dataclass
class AnalyticalQueryMetrics:
    query_kind: str
    latency_ms: float
    compilation_time_ms: float
    execution_time_ms: float
    queue_time_ms: float
    rows_produced: int
    bytes_scanned: int
    partitions_scanned: int
    partitions_total: int
```

### 3. Per-Kind Summary Metrics

Extend the existing per-kind tracking:

```python
# Line 207-257 in test_executor.py

# Existing (latency focused)
self._lat_by_kind_ms: dict[str, list[float]]

# Add (throughput focused)
self._rows_by_kind: dict[str, list[int]] = {
    "POINT_LOOKUP": [], "RANGE_SCAN": [], "INSERT": [], "UPDATE": [],
    "AGGREGATION": [], "WINDOWED": [], "ANALYTICAL_JOIN": [],
    "WIDE_SCAN": [], "APPROX_DISTINCT": [],
}

self._bytes_by_kind: dict[str, list[int]] = {
    "POINT_LOOKUP": [], "RANGE_SCAN": [], "INSERT": [], "UPDATE": [],
    "AGGREGATION": [], "WINDOWED": [], "ANALYTICAL_JOIN": [],
    "WIDE_SCAN": [], "APPROX_DISTINCT": [],
}

self._compile_time_by_kind_ms: dict[str, list[float]] = {
    "AGGREGATION": [], "WINDOWED": [], "ANALYTICAL_JOIN": [],
    "WIDE_SCAN": [], "APPROX_DISTINCT": [],
}
```

### 4. SLO Definitions for Analytics

Update FIND_MAX_CONCURRENCY SLOs for analytical workloads:

```python
# Lines 2063-2116

fmc_slo_by_kind = {
    # OLTP (tight latency)
    "POINT_LOOKUP": {
        "p95_ms": 100,
        "p99_ms": 200,
        "error_pct": 1.0,
    },
    "RANGE_SCAN": {
        "p95_ms": 200,
        "p99_ms": 500,
        "error_pct": 1.0,
    },
    
    # OLAP (throughput focused)
    "AGGREGATION": {
        "p95_ms": 5000,      # 5 seconds acceptable
        "p99_ms": 10000,     # 10 seconds outlier
        "error_pct": 1.0,
        "min_rows_per_sec": 100000,  # New: throughput SLO
    },
    "WINDOWED": {
        "p95_ms": 5000,
        "p99_ms": 10000,
        "error_pct": 1.0,
        "min_rows_per_sec": 50000,
    },
    "ANALYTICAL_JOIN": {
        "p95_ms": 8000,
        "p99_ms": 15000,
        "error_pct": 1.0,
        "min_rows_per_sec": 200000,
    },
    "WIDE_SCAN": {
        "p95_ms": 3000,
        "p99_ms": 8000,
        "error_pct": 1.0,
        "min_bytes_per_sec": 10 * 1024 * 1024,  # 10 MB/s
    },
    "APPROX_DISTINCT": {
        "p95_ms": 2000,
        "p99_ms": 5000,
        "error_pct": 1.0,
    },
}
```

## Metrics Storage

### Extended `_QueryExecutionRecord`

```python
@dataclass
class _QueryExecutionRecord:
    # Existing fields
    execution_id: str
    query_kind: str
    duration_ms: float
    success: bool
    
    # New analytical fields
    rows_produced: Optional[int] = None
    bytes_scanned: Optional[int] = None
    compilation_time_ms: Optional[float] = None
    execution_time_ms: Optional[float] = None
    queue_time_ms: Optional[float] = None
    partitions_scanned: Optional[int] = None
    partitions_total: Optional[int] = None
```

### Summary Statistics

```python
def _compute_analytical_summary(self) -> dict:
    """Compute summary statistics for analytical workloads."""
    summary = {}
    
    for kind in ["AGGREGATION", "WINDOWED", "ANALYTICAL_JOIN", "WIDE_SCAN", "APPROX_DISTINCT"]:
        lats = self._lat_by_kind_ms.get(kind, [])
        rows = self._rows_by_kind.get(kind, [])
        bytes_ = self._bytes_by_kind.get(kind, [])
        
        if not lats:
            continue
        
        total_time_sec = sum(lats) / 1000
        total_rows = sum(rows)
        total_bytes = sum(bytes_)
        
        summary[kind] = {
            "query_count": len(lats),
            "p50_ms": np.percentile(lats, 50),
            "p95_ms": np.percentile(lats, 95),
            "p99_ms": np.percentile(lats, 99),
            "total_rows": total_rows,
            "rows_per_sec": total_rows / total_time_sec if total_time_sec > 0 else 0,
            "total_bytes": total_bytes,
            "bytes_per_sec": total_bytes / total_time_sec if total_time_sec > 0 else 0,
        }
    
    return summary
```

## UI Display

### Analytical Metrics Dashboard

| Metric | OLTP Display | OLAP Display |
|--------|-------------|--------------|
| Latency | p50, p95, p99 | p50, p95, p99 |
| Throughput | ops/sec | rows/sec, MB/sec |
| Efficiency | - | partitions scanned/total |
| Overhead | - | compile time % |

### New Dashboard Columns

```python
# For analytical query kinds, show:
columns = [
    "Query Kind",
    "Count",
    "p50 (ms)",
    "p95 (ms)", 
    "p99 (ms)",
    "Rows/sec",      # New
    "MB/sec",        # New
    "Compile %",     # New: compilation_time / total_time
    "Error %",
]
```

## Snowflake Query Profiling

### Capture Extended Metrics

```python
async def _capture_query_profile(
    self,
    query_id: str,
    conn
) -> Optional[dict]:
    """Fetch detailed query metrics from Snowflake."""
    
    sql = """
    SELECT 
        EXECUTION_TIME,
        COMPILATION_TIME,
        QUEUED_PROVISIONING_TIME,
        QUEUED_OVERLOAD_TIME,
        BYTES_SCANNED,
        ROWS_PRODUCED,
        PARTITIONS_SCANNED,
        PARTITIONS_TOTAL
    FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_SESSION())
    WHERE QUERY_ID = ?
    ORDER BY START_TIME DESC
    LIMIT 1
    """
    
    try:
        result = await conn.execute(sql, [query_id])
        row = await result.fetchone()
        if row:
            return {
                "execution_time_ms": row[0],
                "compilation_time_ms": row[1],
                "queue_provisioning_ms": row[2],
                "queue_overload_ms": row[3],
                "bytes_scanned": row[4],
                "rows_produced": row[5],
                "partitions_scanned": row[6],
                "partitions_total": row[7],
            }
    except Exception as e:
        logger.warning(f"Failed to capture query profile: {e}")
    
    return None
```

### Performance Considerations

- Query profile capture adds latency (~50-100ms per query)
- Consider sampling: capture profile for 1 in N queries
- Cache QUERY_HISTORY lookups to batch at end of test

```python
# Sampling strategy
PROFILE_SAMPLE_RATE = 0.1  # Capture 10% of queries

if random.random() < PROFILE_SAMPLE_RATE:
    profile = await self._capture_query_profile(query_id, conn)
    self._query_profiles.append(profile)
```

## Backward Compatibility

- Existing OLTP metrics unchanged
- New metrics are additive (optional fields)
- UI displays new columns only for analytical kinds
- API responses include new fields with null defaults
