# Architecture Changes Overview

High-level modifications needed to support analytical workloads.

## Current Architecture (OLTP-Focused)

```
┌─────────────────────────────────────────────────────────────┐
│                    YAML Template/Scenario                    │
│  workload_type: CUSTOM                                       │
│  custom_point_lookup_pct: 70                                 │
│  custom_range_scan_pct: 30                                   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Test Registry                            │
│  Builds custom_queries list from template                    │
│  [{"query_kind": "POINT_LOOKUP", "weight_pct": 70, ...}]    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Test Executor                            │
│  _execute_custom() dispatches by query_kind                  │
│  Allowed: POINT_LOOKUP, RANGE_SCAN, INSERT, UPDATE          │
│  Parameter type INFERRED from query_kind                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Value Pools                              │
│  KEY pool → point lookup IDs                                 │
│  RANGE pool → time cutoffs                                   │
│  ROW pool → full row data                                    │
│  (Fixed pools, pre-sampled at setup)                        │
└─────────────────────────────────────────────────────────────┘
```

**Limitation:** Parameter types are inferred from query_kind. This works for OLTP
(point lookups always need an ID) but fails for OLAP where queries filter on
arbitrary dimensions with varying granularities.

## Proposed Architecture (OLAP-Capable)

```
┌─────────────────────────────────────────────────────────────┐
│                    YAML Template/Scenario                    │
│  custom_queries:                                             │
│    - query_kind: "AGGREGATION"                               │
│      sql: "SELECT ... WHERE date >= ? AND region = ?"       │
│      parameters:                    ◄── NEW: Explicit specs  │
│        - {type: date, strategy: random_in_range}            │
│        - {type: categorical, strategy: sample_from_table}   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Column Profiler (NEW)                     │
│  Profiles ALL columns referenced in parameter specs         │
│  - Date columns: min/max bounds                              │
│  - Categorical: distinct values + frequencies                │
│  - Numeric: min/max/distribution                             │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Parameter Generator (NEW)                   │
│  For each query execution:                                   │
│  - Iterate through parameter specs in order                  │
│  - Apply generation strategy (random_in_range, sample, etc.) │
│  - Handle dependent params (end_date from start_date)        │
│  - Return ordered list of values to bind                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Test Executor                            │
│  _execute_custom() dispatches by query_kind                  │
│  Binds generated params to SQL placeholders                  │
│  Tracks metrics per query kind                               │
└─────────────────────────────────────────────────────────────┘
```

**Key change:** Parameters are **explicitly specified** per query, not inferred from query_kind.

## Core Changes

### 1. Explicit Parameter Specifications

Each `?` placeholder gets a specification defining how to generate values:

```yaml
parameters:
  - name: "start_date"
    type: "date"
    strategy: "random_in_range"    # Random within column bounds
    column: "order_date"
  
  - name: "end_date"
    type: "date"
    strategy: "offset_from_previous"  # Relative to prior param
    depends_on: "start_date"
    offset: [7, 30, 90, 365]
  
  - name: "region"
    type: "categorical"
    strategy: "sample_from_table"  # Random from distinct values
    column: "region"
```

See `04-value-pools.md` for full specification.

### 2. Column Profiling

Profile ALL columns that may be used in parameters (not just id/time):

```python
@dataclass
class ColumnProfile:
    name: str
    data_type: str              # date, number, string
    min_value: Any              # For dates/numbers
    max_value: Any
    distinct_count: int
    sample_values: list[Any]    # For categoricals
    value_weights: dict         # For weighted sampling
```

### 3. Generation Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `choice` | Random from explicit list | Granularity, enums |
| `random_in_range` | Random in column min/max | Dates, numbers |
| `sample_from_table` | Random from distinct values | Categoricals |
| `weighted_sample` | Frequency-weighted random | Realistic distribution |
| `offset_from_previous` | Relative to prior param | Date range end |
| `sample_list` | Multiple values for IN clause | Multi-select filters |
| `sample_from_pool` | Legacy pool-based (OLTP) | Backward compat |

### 4. Add New Query Kinds

**Location:** `backend/api/routes/templates_modules/constants.py`

```python
# Proposed (9 kinds)
_CUSTOM_QUERY_FIELDS = (
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
```

### 5. Modify Test Executor Dispatch

**Location:** `backend/core/test_executor.py`

Replace query_kind-based parameter inference with explicit spec-based generation:

```python
async def _execute_custom(self, worker_id: int, warmup: bool = False):
    # Select query by weight
    query_spec = self._select_query_by_weight()
    
    # Generate parameters using explicit specs (NEW)
    params = self._generate_params(query_spec.parameters, worker_id)
    
    # Bind and execute
    sql = query_spec.sql.replace("{table}", full_name)
    result = await conn.execute(sql, params)
```

### 6. Add Analytics-Specific Metrics

**Current metrics focus:** Latency per operation (p50, p95, p99)

**Add:**
- Rows processed per second
- Bytes scanned per second
- Query compile time vs execution time
- Warehouse queue time

### 7. Update SLO Definitions

**Location:** `backend/core/test_executor.py:2063-2116`

Analytical queries have different latency expectations:
- Point lookup: <50ms target
- Aggregation: <5000ms target (acceptable for analytics)

## File Modification Summary

| File | Changes |
|------|---------|
| `constants.py` | Add 5 new query field tuples, default SQL |
| `test_executor.py` | Add dispatch branches, metrics dicts, SLO defs |
| `test_config.py` | Validate new query kinds in model |
| `table_profiler.py` | Add column statistics for analytical queries |
| `test_registry.py` | Build custom_queries for new kinds |

## Backward Compatibility

- Existing OLTP workloads unchanged
- New query kinds are additive
- Templates without analytical queries work as before
- `workload_type: CUSTOM` supports any mix of kinds

## Phased Approach

**Phase 1:** Add AGGREGATION query kind only
- Simplest parameter binding (single date cutoff)
- Validates architecture changes work

**Phase 2:** Add WINDOWED, WIDE_SCAN
- Requires date range parameters
- Tests window function metrics

**Phase 3:** Add ANALYTICAL_JOIN, APPROX_DISTINCT
- Requires dimension pools
- More complex binding logic

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| New query kinds | Medium | Add one at a time, validate |
| Value pool changes | Low | Additive, doesn't break existing |
| Metrics changes | Low | New fields, existing unchanged |
| Executor dispatch | Medium | Comprehensive test coverage |
