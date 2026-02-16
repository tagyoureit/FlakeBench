# Implementation Steps

Phased approach to adding analytical workload support with explicit parameter specifications.

## Phase 1: Parameter Specification Foundation

**Goal:** Build the core parameter generation system.

### Step 1.1: Add ParameterSpec Model

**File:** `backend/models/parameter_spec.py` (new)

```python
from dataclasses import dataclass, field
from typing import Any, Optional, Literal

@dataclass
class ParameterSpec:
    """Specification for generating a single query parameter."""
    
    name: str
    type: Literal["date", "categorical", "numeric", "choice", "categorical_list"]
    strategy: str
    
    # For table-derived values
    column: Optional[str] = None
    
    # For explicit choices
    values: Optional[list] = None
    
    # For dependent parameters
    depends_on: Optional[str] = None
    offset: Optional[list] = None
    
    # For list parameters
    count: Optional[list[int]] = None
    placeholder: Optional[str] = None  # For IN clauses
    
    # For numeric range
    min: Optional[float] = None
    max: Optional[float] = None
    
    # For legacy pool-based (backward compat)
    pool: Optional[str] = None
```

**Effort:** 1 hour

### Step 1.2: Add ColumnProfile Model

**File:** `backend/core/column_profiler.py` (new)

```python
@dataclass
class ColumnProfile:
    """Statistical profile of a table column."""
    
    name: str
    data_type: str
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    distinct_count: int = 0
    null_count: int = 0
    total_count: int = 0
    sample_values: list[Any] = field(default_factory=list)
    value_weights: dict[Any, float] = field(default_factory=dict)


async def profile_column(
    conn,
    table: str,
    column: str,
    sample_size: int = 100
) -> ColumnProfile:
    """Profile a single column."""
    # Implementation...
```

**Effort:** 2 hours

### Step 1.3: Add Parameter Generator

**File:** `backend/core/param_generator.py` (new)

```python
class ParameterGenerator:
    """Generates parameter values based on specs and column profiles."""
    
    def __init__(self, column_profiles: dict[str, ColumnProfile]):
        self._profiles = column_profiles
    
    def generate(self, specs: list[ParameterSpec]) -> list[Any]:
        """Generate values for all parameter specs."""
        params = []
        context = {}  # For dependent params
        
        for spec in specs:
            value = self._generate_one(spec, context)
            params.append(value)
            context[spec.name] = value
        
        return params
    
    def _generate_one(self, spec: ParameterSpec, context: dict) -> Any:
        """Generate a single parameter value."""
        if spec.strategy == "choice":
            return random.choice(spec.values)
        
        elif spec.strategy == "random_in_range":
            profile = self._profiles[spec.column]
            return self._random_in_range(profile)
        
        elif spec.strategy == "sample_from_table":
            profile = self._profiles[spec.column]
            return random.choice(profile.sample_values)
        
        elif spec.strategy == "weighted_sample":
            profile = self._profiles[spec.column]
            return self._weighted_choice(profile.value_weights)
        
        elif spec.strategy == "offset_from_previous":
            base = context[spec.depends_on]
            offset = random.choice(spec.offset)
            return self._apply_offset(base, offset)
        
        elif spec.strategy == "sample_list":
            profile = self._profiles[spec.column]
            count = random.choice(spec.count)
            return random.sample(profile.sample_values, min(count, len(profile.sample_values)))
        
        elif spec.strategy == "random_numeric":
            return random.uniform(spec.min, spec.max)
        
        elif spec.strategy == "sample_from_pool":
            # Legacy compatibility
            return self._sample_from_pool(spec.pool)
        
        else:
            raise ValueError(f"Unknown strategy: {spec.strategy}")
```

**Effort:** 3 hours

### Step 1.4: Unit Tests for Parameter Generation

**File:** `tests/unit/test_param_generator.py`

- Test each generation strategy
- Test dependent parameters
- Test edge cases (empty profiles, missing values)

**Effort:** 2 hours

**Phase 1 Total:** ~1 day

---

## Phase 2: Integration with Executor

**Goal:** Wire parameter generation into test execution.

### Step 2.1: Parse Parameter Specs from YAML

**File:** `backend/api/routes/templates_modules/parser.py`

```python
def parse_custom_query(query_dict: dict) -> CustomQuerySpec:
    """Parse a custom query definition including parameter specs."""
    return CustomQuerySpec(
        query_kind=query_dict["query_kind"],
        weight_pct=query_dict["weight_pct"],
        sql=query_dict["sql"],
        parameters=[
            ParameterSpec(**p) for p in query_dict.get("parameters", [])
        ]
    )
```

**Effort:** 2 hours

### Step 2.2: Column Profiling at Template Setup

**File:** `backend/core/test_executor.py`

Add column profiling during template initialization:

```python
async def _setup_column_profiles(self):
    """Profile columns referenced in parameter specs."""
    columns_to_profile = set()
    
    for query in self._custom_queries:
        for param in query.parameters:
            if param.column:
                columns_to_profile.add(param.column)
    
    self._column_profiles = {}
    for column in columns_to_profile:
        self._column_profiles[column] = await profile_column(
            self._conn, self._table, column
        )
```

**Effort:** 2 hours

### Step 2.3: Modify `_execute_custom` to Use Generator

**File:** `backend/core/test_executor.py`

```python
async def _execute_custom(self, worker_id: int, warmup: bool = False):
    # Select query by weight
    query_spec = self._custom_next_query(worker_id)
    
    # Generate parameters using explicit specs
    if query_spec.parameters:
        generator = ParameterGenerator(self._column_profiles)
        params = generator.generate(query_spec.parameters)
    else:
        # Legacy: infer from query_kind (backward compat)
        params = self._legacy_generate_params(query_spec.query_kind)
    
    # Bind and execute
    sql = self._prepare_sql(query_spec.sql, params)
    result = await conn.execute(sql, params)
```

**Effort:** 3 hours

### Step 2.4: Integration Tests

- Test YAML parsing with parameter specs
- Test column profiling
- Test end-to-end execution with generated params

**Effort:** 2 hours

**Phase 2 Total:** ~1.5 days

---

## Phase 3: Add New Query Kinds

**Goal:** Add AGGREGATION, WINDOWED, etc. with appropriate defaults.

### Step 3.1: Add Query Kind Constants

**File:** `backend/api/routes/templates_modules/constants.py`

```python
_CUSTOM_QUERY_KINDS = {
    # OLTP
    "POINT_LOOKUP",
    "RANGE_SCAN", 
    "INSERT",
    "UPDATE",
    # OLAP
    "AGGREGATION",
    "WINDOWED",
    "ANALYTICAL_JOIN",
    "WIDE_SCAN",
    "APPROX_DISTINCT",
}
```

**Effort:** 30 minutes

### Step 3.2: Add Metrics Tracking for New Kinds

**File:** `backend/core/test_executor.py`

Initialize metrics dictionaries for new query kinds.

**Effort:** 1 hour

### Step 3.3: Add SLO Definitions

**File:** `backend/core/test_executor.py`

```python
fmc_slo_by_kind = {
    # OLTP (tight latency)
    "POINT_LOOKUP": {"p95_ms": 100, "p99_ms": 200},
    # OLAP (relaxed latency)
    "AGGREGATION": {"p95_ms": 5000, "p99_ms": 10000},
    "WINDOWED": {"p95_ms": 5000, "p99_ms": 10000},
    # ...
}
```

**Effort:** 1 hour

### Step 3.4: Default SQL Templates

Provide example SQL for each OLAP query kind.

**Effort:** 1 hour

**Phase 3 Total:** ~0.5 days

---

## Phase 4: Extended Metrics & Polish

**Goal:** Add analytics-specific metrics and documentation.

### Step 4.1: Add Throughput Metrics

- Rows per second
- Bytes scanned per second

**Effort:** 3 hours

### Step 4.2: Add Query Profile Capture

Optionally capture Snowflake query profile (compilation time, etc.)

**Effort:** 2 hours

### Step 4.3: Update UI Dashboard

Display throughput metrics for OLAP queries.

**Effort:** 4 hours

### Step 4.4: Create Example Scenarios

```yaml
# config/test_scenarios/analytical_comprehensive.yaml
```

**Effort:** 2 hours

### Step 4.5: Documentation

- Update user guide
- Add migration guide for existing templates

**Effort:** 2 hours

**Phase 4 Total:** ~2 days

---

## Summary Timeline

| Phase | Description | Effort |
|-------|-------------|--------|
| Phase 1 | Parameter Specification Foundation | 1 day |
| Phase 2 | Integration with Executor | 1.5 days |
| Phase 3 | Add New Query Kinds | 0.5 days |
| Phase 4 | Extended Metrics & Polish | 2 days |
| **Total** | **Full Implementation** | **~5 days** |

## Testing Strategy

### Unit Tests
- [ ] ParameterSpec model validation
- [ ] Each generation strategy
- [ ] Dependent parameter handling
- [ ] ColumnProfile generation

### Integration Tests
- [ ] YAML parsing with parameter specs
- [ ] Column profiling from live tables
- [ ] End-to-end query execution

### End-to-End Tests
- [ ] Full benchmark with analytical scenario
- [ ] Verify query variety (no repeated queries)
- [ ] Compare Snowflake vs Postgres results

### Variety Validation
- [ ] Log generated parameters
- [ ] Verify combinatorial diversity
- [ ] Check for cache-busting effectiveness

## Backward Compatibility

### Implicit Parameter Specs

Templates without `parameters` section use legacy behavior:

```python
IMPLICIT_PARAMS = {
    "POINT_LOOKUP": [
        ParameterSpec(name="id", type="numeric", strategy="sample_from_pool", pool="KEY")
    ],
    "RANGE_SCAN": [
        ParameterSpec(name="start", type="numeric", strategy="sample_from_pool", pool="KEY"),
        ParameterSpec(name="end", type="numeric", strategy="offset_from_previous", 
                     depends_on="start", offset=[100])
    ],
    # ...
}

def get_parameter_specs(query_spec) -> list[ParameterSpec]:
    if query_spec.parameters:
        return query_spec.parameters  # Explicit specs
    return IMPLICIT_PARAMS.get(query_spec.query_kind, [])  # Legacy
```

### Migration Path

1. Existing templates work unchanged (implicit specs)
2. New analytical templates use explicit specs
3. Users can gradually add explicit specs to existing templates
4. No breaking changes to API or YAML format

## Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Column profiling slow | Cache profiles, profile during setup only |
| Too many distinct values | Cap sample_values at configurable limit |
| Dependent param cycles | Validate DAG at parse time |
| Legacy compatibility breaks | Comprehensive regression tests |
