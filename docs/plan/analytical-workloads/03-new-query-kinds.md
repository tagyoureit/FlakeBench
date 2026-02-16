# New Query Kinds Implementation

Detailed implementation guide for adding analytical query kinds to the test executor.

## Key Design Change: Explicit Parameters

Unlike OLTP query kinds (POINT_LOOKUP, etc.) where parameter types are inferred,
OLAP query kinds use **explicit parameter specifications**. This allows:

- Multiple parameter types in one query
- Arbitrary dimension filters (not just id/time)
- Variable granularity (hour, day, week, month, year)
- Combinatorial variety for meaningful benchmarks

See `04-value-pools.md` for the full parameter specification system.

## New Query Kinds

| Kind | Purpose | Typical Parameters |
|------|---------|-------------------|
| `AGGREGATION` | GROUP BY with aggregates | date range, dimension filters |
| `WINDOWED` | Window functions | date range, partition column |
| `ANALYTICAL_JOIN` | Fact-dimension joins | date range, dimension filters |
| `WIDE_SCAN` | Multi-column scans | date range |
| `APPROX_DISTINCT` | HyperLogLog cardinality | date range, granularity |

## File Changes

### 1. Constants (`backend/api/routes/templates_modules/constants.py`)

```python
# Line ~9-20: Add new query fields
_CUSTOM_QUERY_FIELDS: tuple[str, ...] = (
    # OLTP (existing)
    "custom_point_lookup_query",
    "custom_range_scan_query",
    "custom_insert_query",
    "custom_update_query",
    # OLAP (new)
    "custom_aggregation_query",
    "custom_windowed_query",
    "custom_analytical_join_query",
    "custom_wide_scan_query",
    "custom_approx_distinct_query",
)

_CUSTOM_PCT_FIELDS: tuple[str, ...] = (
    # OLTP (existing)
    "custom_point_lookup_pct",
    "custom_range_scan_pct",
    "custom_insert_pct",
    "custom_update_pct",
    # OLAP (new)
    "custom_aggregation_pct",
    "custom_windowed_pct",
    "custom_analytical_join_pct",
    "custom_wide_scan_pct",
    "custom_approx_distinct_pct",
)
```

### 2. Default SQL Templates

```python
# Add to _DEFAULT_CUSTOM_QUERIES_SNOWFLAKE

"custom_aggregation_query": """
SELECT 
    DATE_TRUNC('month', created_at) AS month,
    region,
    SUM(amount) AS total,
    COUNT(*) AS cnt
FROM {table}
WHERE created_at >= ?
GROUP BY 1, 2
""",

"custom_windowed_query": """
SELECT 
    id,
    created_at,
    amount,
    SUM(amount) OVER (ORDER BY created_at ROWS UNBOUNDED PRECEDING) AS cumulative
FROM {table}
WHERE created_at BETWEEN ? AND ?
ORDER BY created_at
""",

"custom_analytical_join_query": """
SELECT 
    d.year,
    d.quarter,
    SUM(f.amount) AS total
FROM {table} f
JOIN {dim_table} d ON f.date_key = d.date_key
WHERE d.year = ?
GROUP BY 1, 2
""",

"custom_wide_scan_query": """
SELECT 
    col1, col2, col3, col4, col5,
    SUM(amount) AS total,
    AVG(quantity) AS avg_qty
FROM {table}
WHERE created_at BETWEEN ? AND ?
GROUP BY 1, 2, 3, 4, 5
""",

"custom_approx_distinct_query": """
SELECT 
    DATE_TRUNC('day', created_at) AS day,
    APPROX_COUNT_DISTINCT(user_id) AS unique_users
FROM {table}
WHERE created_at BETWEEN ? AND ?
GROUP BY 1
"""
```

### 3. Test Executor Metrics (`backend/core/test_executor.py`)

```python
# Lines 207-257: Initialize metrics for new kinds

self._find_max_step_lat_by_kind_ms: dict[str, deque[float]] = {
    # OLTP
    "POINT_LOOKUP": deque(maxlen=10000),
    "RANGE_SCAN": deque(maxlen=10000),
    "INSERT": deque(maxlen=10000),
    "UPDATE": deque(maxlen=10000),
    # OLAP (new)
    "AGGREGATION": deque(maxlen=10000),
    "WINDOWED": deque(maxlen=10000),
    "ANALYTICAL_JOIN": deque(maxlen=10000),
    "WIDE_SCAN": deque(maxlen=10000),
    "APPROX_DISTINCT": deque(maxlen=10000),
}

self._find_max_step_ops_by_kind: dict[str, int] = {
    "POINT_LOOKUP": 0, "RANGE_SCAN": 0, "INSERT": 0, "UPDATE": 0,
    "AGGREGATION": 0, "WINDOWED": 0, "ANALYTICAL_JOIN": 0,
    "WIDE_SCAN": 0, "APPROX_DISTINCT": 0,
}

self._find_max_step_errors_by_kind: dict[str, int] = {
    "POINT_LOOKUP": 0, "RANGE_SCAN": 0, "INSERT": 0, "UPDATE": 0,
    "AGGREGATION": 0, "WINDOWED": 0, "ANALYTICAL_JOIN": 0,
    "WIDE_SCAN": 0, "APPROX_DISTINCT": 0,
}

self._lat_by_kind_ms: dict[str, list[float]] = {
    "POINT_LOOKUP": [], "RANGE_SCAN": [], "INSERT": [], "UPDATE": [],
    "AGGREGATION": [], "WINDOWED": [], "ANALYTICAL_JOIN": [],
    "WIDE_SCAN": [], "APPROX_DISTINCT": [],
}
```

### 4. Allowed Kinds Validation

```python
# Line ~615: Update allowed set
allowed = {
    "POINT_LOOKUP", "RANGE_SCAN", "INSERT", "UPDATE",
    "AGGREGATION", "WINDOWED", "ANALYTICAL_JOIN", "WIDE_SCAN", "APPROX_DISTINCT"
}
```

### 5. SLO Definitions

```python
# Lines 2063-2116: Add SLO definitions for FIND_MAX_CONCURRENCY

fmc_slo_by_kind = {
    # OLTP (existing - tight latency)
    "POINT_LOOKUP": {"p95_ms": 100, "p99_ms": 200, "error_pct": 1.0},
    "RANGE_SCAN": {"p95_ms": 200, "p99_ms": 500, "error_pct": 1.0},
    "INSERT": {"p95_ms": 150, "p99_ms": 300, "error_pct": 1.0},
    "UPDATE": {"p95_ms": 150, "p99_ms": 300, "error_pct": 1.0},
    # OLAP (new - relaxed latency, acceptable for analytics)
    "AGGREGATION": {"p95_ms": 5000, "p99_ms": 10000, "error_pct": 1.0},
    "WINDOWED": {"p95_ms": 5000, "p99_ms": 10000, "error_pct": 1.0},
    "ANALYTICAL_JOIN": {"p95_ms": 8000, "p99_ms": 15000, "error_pct": 1.0},
    "WIDE_SCAN": {"p95_ms": 3000, "p99_ms": 8000, "error_pct": 1.0},
    "APPROX_DISTINCT": {"p95_ms": 2000, "p99_ms": 5000, "error_pct": 1.0},
}
```

### 6. Display Names

```python
# Lines 2422-2427: Add display names

_KIND_DISPLAY_NAMES = {
    "POINT_LOOKUP": "Point Lookup",
    "RANGE_SCAN": "Range Scan",
    "INSERT": "Insert",
    "UPDATE": "Update",
    "AGGREGATION": "Aggregation",
    "WINDOWED": "Windowed",
    "ANALYTICAL_JOIN": "Analytical Join",
    "WIDE_SCAN": "Wide Scan",
    "APPROX_DISTINCT": "Approx Distinct",
}
```

### 7. Execution Dispatch (`_execute_custom`)

```python
# Lines 3318-3470: Add dispatch branches

elif query_kind == "AGGREGATION":
    # Single date cutoff parameter
    cutoff = self._choose_date_cutoff(tc, runtime)
    params = [cutoff]

elif query_kind == "WINDOWED":
    # Date range parameters
    start_date, end_date = self._choose_date_range(tc, runtime)
    params = [start_date, end_date]

elif query_kind == "ANALYTICAL_JOIN":
    # Scalar parameter (year) or date range
    year_value = self._choose_scalar("year", tc, runtime)
    params = [year_value]

elif query_kind == "WIDE_SCAN":
    # Date range parameters
    start_date, end_date = self._choose_date_range(tc, runtime)
    params = [start_date, end_date]

elif query_kind == "APPROX_DISTINCT":
    # Date range parameters
    start_date, end_date = self._choose_date_range(tc, runtime)
    params = [start_date, end_date]

else:
    raise ValueError(f"Unsupported custom query kind {query_kind}")
```

## New Helper Methods

```python
def _choose_date_cutoff(
    self, 
    tc: TableConfig, 
    runtime: _TableRuntimeState
) -> datetime:
    """Choose a date cutoff for aggregation queries."""
    profile = runtime.profile
    
    # Try RANGE pool first
    cutoff = self._next_from_pool(worker_id, "RANGE", None)
    if cutoff:
        return cutoff
    
    # Fall back to profile time bounds
    if profile and profile.time_min:
        # Random date between time_min and time_max
        delta = (profile.time_max - profile.time_min).days
        offset_days = random.randint(0, max(1, delta))
        return profile.time_min + timedelta(days=offset_days)
    
    # Default: 30 days ago
    return datetime.now(UTC) - timedelta(days=30)


def _choose_date_range(
    self,
    tc: TableConfig,
    runtime: _TableRuntimeState
) -> tuple[datetime, datetime]:
    """Choose a date range for range-based analytical queries."""
    profile = runtime.profile
    
    # Try DATE_RANGE pool first
    range_val = self._next_from_pool(worker_id, "DATE_RANGE", None)
    if range_val and isinstance(range_val, (list, tuple)) and len(range_val) == 2:
        return range_val[0], range_val[1]
    
    # Fall back to profile time bounds with 30-day window
    if profile and profile.time_min and profile.time_max:
        end_date = profile.time_max
        start_date = end_date - timedelta(days=30)
        return max(start_date, profile.time_min), end_date
    
    # Default: last 30 days
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=30)
    return start_date, end_date


def _choose_scalar(
    self,
    scalar_type: str,
    tc: TableConfig,
    runtime: _TableRuntimeState
) -> Any:
    """Choose a scalar value (year, region, etc.) for analytical queries."""
    # Try SCALAR pool first
    value = self._next_from_pool(worker_id, "SCALAR", scalar_type)
    if value:
        return value
    
    # Default values by type
    defaults = {
        "year": datetime.now().year,
        "region": "WEST",
        "category": "DEFAULT",
    }
    return defaults.get(scalar_type, None)
```

## Read vs Write Classification

```python
# Update is_read classification for new kinds
is_read = query_kind in {
    "POINT_LOOKUP", "RANGE_SCAN",
    "AGGREGATION", "WINDOWED", "ANALYTICAL_JOIN", 
    "WIDE_SCAN", "APPROX_DISTINCT"
}
```

All analytical query kinds are **read operations**.

## Testing Strategy

1. **Unit test** each new helper method
2. **Integration test** each query kind execution
3. **Validation test** that metrics are properly tracked
4. **End-to-end test** with sample YAML scenario
