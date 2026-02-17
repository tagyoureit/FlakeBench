# Parameter Binding for Analytical Queries

How to generate meaningful parameter variety for OLAP workloads.

> **Decision update (2026-02-16):** Analytical SQL uses `GENERIC_SQL` entries
> with explicit `operation_type`. Placeholder parameters should be explicitly
> configured. Query mixes use 2-decimal `weight_pct` precision.

## When Are Column Profiles Calculated?

**Same timing as OLTP pools: During template preparation** (`prepare_ai_template()`).

When the user clicks "Prepare" in the UI, we:
1. Profile columns referenced in parameter specs (**NEW** for OLAP)
2. Sample KEY values for point lookups (existing OLTP)
3. Sample RANGE values for time scans (existing OLTP)

**Key difference from OLTP pools:**

| Aspect | OLTP Pools | OLAP Profiles |
|--------|-----------|---------------|
| What's stored | Every sampled value (5K-1M rows) | Just metadata (~1 row per column) |
| Storage size | Large | Tiny |
| Generation | Cycle through pre-sampled values | Generate on-the-fly from metadata |
| Variety | Limited to pool size | Effectively unlimited (combinatorial) |

**Storage decision:** Use a dedicated `TEMPLATE_COLUMN_PROFILES` table (do not overload `TEMPLATE_VALUE_POOLS`).

## Multi-Worker Execution

All workers share the same column profiles but use different random seeds:

```
┌─────────────────────────────────────────────────────────────┐
│                  Shared Column Profiles                      │
│  (loaded once at startup, read-only)                        │
│                                                              │
│  sales_fact.order_date: {min: 2020-01-01, max: 2024-12-31}  │
│  dim_region.region: ["US-EAST", "US-WEST", "EU", ...]       │
│  dim_product.category: ["Electronics", "Clothing", ...]     │
└─────────────────────────────────────────────────────────────┘
           │              │              │              │
           ▼              ▼              ▼              ▼
       Worker 0       Worker 1       Worker 2       Worker 3
       seed=1000      seed=1001      seed=1002      seed=1003
           │              │              │              │
           ▼              ▼              ▼              ▼
      Randomly        Randomly        Randomly        Randomly
      selects from    selects from    selects from    selects from
      same profiles   same profiles   same profiles   same profiles
```

**Key points:**
- Column profiles loaded once, shared by all workers (read-only)
- Each worker has unique random seed based on worker_id
- Workers independently select from the same pools
- Some parameter overlap between workers is fine - **cache is disabled at template level**
- No coordination or stride patterns needed

**Implementation:**

```python
class ParameterGenerator:
    def __init__(self, profiles: dict[str, ColumnProfile], worker_id: int):
        self._profiles = profiles  # Shared, read-only
        self._rng = random.Random(seed=worker_id)  # Unique per worker
    
    def generate(self, configs: list[ParameterConfig]) -> list[Any]:
        # Each call generates fresh random values
        ...
```

## OLTP vs OLAP Parameter Binding

| Aspect | OLTP (Point Lookup) | OLAP (Aggregation) |
|--------|---------------------|-------------------|
| Purpose | Identify specific rows | Define data slices |
| Validity | Must be existing key | Any valid dimension value |
| Source | Pre-sampled from table | Dynamically generated |
| Variety | Pool size (thousands) | Combinatorial (unlimited) |

**Key insight:** OLTP parameters identify **rows**. OLAP parameters define **slices**.

## The Problem with Pool-Based Binding

Current system:
```
query_kind → inferred parameter type → fixed pool
```

This fails for OLAP because:
1. Aggregations filter on **arbitrary dimensions**, not just IDs
2. Time granularity varies (hour, day, week, month, quarter, year)
3. Multiple parameters with **different types** in same query
4. Some parameters are **dependent** (end_date relative to start_date)

## Solution: Explicit Parameter Specifications

New model:
```
query template → [parameter specs] → [generators]
```

Each `?` placeholder has an explicit specification defining how to generate values.

## Parameter Specification Model

```python
@dataclass
class ParameterSpec:
    """Specification for generating a single query parameter."""
    
    name: str                     # Identifier for logging/debugging
    type: str                     # date, categorical, numeric, choice, list
    strategy: str                 # How to generate values
    
    # For table-derived values
    column: Optional[str] = None  # Source column for profiling
    
    # For explicit choices
    values: Optional[list] = None # Explicit value list
    
    # For dependent parameters
    depends_on: Optional[str] = None  # Reference to previous param
    offset: Optional[list] = None     # Offset values for dependent params
    
    # For list parameters (IN clauses)
    count: Optional[int] = None       # Fixed count matching SQL placeholders
```

## Generation Strategies

### 1. `choice` - Random from Explicit List

For enumerated values known at design time.

```yaml
parameters:
  - name: "granularity"
    type: "choice"
    values: ["hour", "day", "week", "month", "quarter", "year"]
```

**Generator:**
```python
def generate_choice(spec: ParameterSpec) -> Any:
    return random.choice(spec.values)
```

### 2. `random_in_range` - Random Within Column Bounds

For dates and numbers, uses table profile for valid range.

```yaml
parameters:
  - name: "start_date"
    type: "date"
    strategy: "random_in_range"
    column: "order_date"
```

**Generator:**
```python
def generate_random_in_range(spec: ParameterSpec, profile: ColumnProfile) -> Any:
    if profile.data_type == "date":
        range_days = (profile.max_value - profile.min_value).days
        offset = random.randint(0, range_days)
        return profile.min_value + timedelta(days=offset)
    elif profile.data_type == "number":
        return random.uniform(profile.min_value, profile.max_value)
```

### 3. `sample_from_table` - Random from Distinct Values

For categorical dimensions, samples from actual values in table.

```yaml
parameters:
  - name: "region"
    type: "categorical"
    strategy: "sample_from_table"
    column: "region"
```

**Generator:**
```python
def generate_sample_from_table(spec: ParameterSpec, profile: ColumnProfile) -> Any:
    return random.choice(profile.sample_values)
```

### 4. `weighted_sample` - Frequency-Weighted Random

For realistic distribution matching actual data skew.

**Cardinality limit:** `weighted_sample` is only available for columns with
≤10,000 distinct values. For higher cardinality columns, the profiler falls back
to `sample_from_table` (uniform distribution) to avoid storing large weight dictionaries.

```yaml
parameters:
  - name: "product_category"
    type: "categorical"
    strategy: "weighted_sample"
    column: "product_category"
```

**Generator:**
```python
def generate_weighted_sample(spec: ParameterSpec, profile: ColumnProfile) -> Any:
    # profile.value_weights: dict of {value: frequency}
    # Only populated for columns with ≤10K distinct values
    if not profile.value_weights:
        # Fallback for high-cardinality columns
        return random.choice(profile.sample_values)
    values = list(profile.value_weights.keys())
    weights = list(profile.value_weights.values())
    return random.choices(values, weights=weights, k=1)[0]
```

### 5. `offset_from_previous` - Relative to Another Parameter

For dependent parameters like date range end.

```yaml
parameters:
  - name: "start_date"
    type: "date"
    strategy: "random_in_range"
    column: "order_date"
  
  - name: "end_date"
    type: "date"
    strategy: "offset_from_previous"
    depends_on: "start_date"
    offset: [7, 14, 30, 90, 365]  # Random window sizes
```

**Generator:**
```python
def generate_offset(spec: ParameterSpec, context: dict, profile: ColumnProfile = None) -> Any:
    base_value = context[spec.depends_on]
    offset_value = random.choice(spec.offset)
    
    if isinstance(base_value, datetime):
        result = base_value + timedelta(days=offset_value)
        # Guard: clamp to max_value to prevent date overflow
        if profile and profile.max_value and result > profile.max_value:
            result = profile.max_value
        return result
    else:
        return base_value + offset_value
```

> **Date overflow protection:** When generating `end_date` from `start_date + offset`,
> the result may exceed the column's actual max value. The generator clamps to 
> `profile.max_value` to ensure all generated dates fall within valid table bounds.

### 6. `sample_list` - Multiple Values for IN Clauses

For queries with `WHERE region IN (?, ?, ?)`.

```yaml
parameters:
  - name: "regions"
    type: "categorical_list"
    strategy: "sample_list"
    column: "region"
    count: [1, 2, 3, 4]  # Randomly pick 1-4 regions
```

**Generator:**
```python
def generate_sample_list(spec: ParameterSpec, profile: ColumnProfile) -> list:
    count = random.choice(spec.count)
    return random.sample(profile.sample_values, min(count, len(profile.sample_values)))
```

### 7. `random_numeric` - Random Number in Bounds

For numeric thresholds and limits.

```yaml
parameters:
  - name: "min_amount"
    type: "numeric"
    strategy: "random_numeric"
    min: 100
    max: 10000
```

## Realism Profiles (Codified Contract)

Realism is codified as an optional, backward-compatible profile. If omitted, the
engine uses `BASELINE` behavior (current behavior).

| Profile | Purpose | Typical knobs |
|---------|---------|---------------|
| `BASELINE` | Keep current synthetic generation defaults | none |
| `REALISTIC` | Mild production-like skew and nulls | `null_rate`, `skew_factor` |
| `STRESS_SKEW` | Heavy 80/20 style skew | high `skew_factor` |
| `NULL_HEAVY` | Stress null semantics in dimensions/filters | high `null_rate` |
| `LATE_ARRIVAL` | Event-time vs ingest-time mismatch | `late_arrival_lag_days` |
| `SELECTIVITY_SWEEP` | Execute same query shape at varying selectivity | `selectivity_band` |

Suggested config shape:

```yaml
realism:
  profile: "REALISTIC"
  null_rate: 0.15                # 0.0 - 1.0
  skew_factor: 1.8               # 1.0 = near-uniform, higher = more skew
  late_arrival_lag_days: [0, 1, 3, 7]
  selectivity_band: [0.001, 0.01, 0.1, 0.5]
```

## Realism Strategy Extensions

These strategy extensions are additive and optional:

### 8. `nullable_sample` - Intentional NULL injection

Use for nullable dimensions and optional filter fields.

```yaml
parameters:
  - name: "channel"
    type: "categorical"
    strategy: "nullable_sample"
    column: "sales_channel"
    null_rate: 0.35
```

### 9. `late_arrival_offset` - Event-time lag simulation

Generates an ingest-time offset from a business/event time parameter.

```yaml
parameters:
  - name: "event_date"
    type: "date"
    strategy: "random_in_range"
    column: "event_date"

  - name: "ingest_date"
    type: "date"
    strategy: "late_arrival_offset"
    depends_on: "event_date"
    offsets: [0, 1, 3, 7]  # days after event_date
```

### 10. `target_selectivity` - Filter strength control

Constrains generated values toward a requested selectivity bucket.

```yaml
parameters:
  - name: "region_filter"
    type: "categorical"
    strategy: "target_selectivity"
    column: "region"
    target_selectivity: 0.01   # ~1% filter selectivity
```

## Realism Validation Matrix

Each realism profile should run at least one validation scenario:

1. **Skew scenario** - verify heavy-hitter categories dominate as expected.
2. **NULL-heavy scenario** - verify null handling and group/filter semantics.
3. **Late-arrival scenario** - verify event-time windows include expected lagged rows.
4. **Selectivity sweep** - run same query shape across low/medium/high selectivity.

The runner should tag each execution with realized realism metadata in
`olap_metrics` for later comparison (for example: realized null rate and
effective selectivity).

## Column Profiling

At template setup, profile ALL columns that may be used in parameters:

```python
@dataclass
class ColumnProfile:
    """Statistical profile of a table column."""
    
    name: str
    data_type: str                    # date, timestamp, number, string
    
    # Bounds (for dates and numbers)
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    
    # Cardinality
    distinct_count: int = 0
    null_count: int = 0
    total_count: int = 0
    
    # Sample values (for categoricals)
    sample_values: list[Any] = field(default_factory=list)
    
    # Frequency distribution (for weighted sampling)
    value_weights: dict[Any, float] = field(default_factory=dict)
```

### Edge Case Guards

**Empty table / all-NULL column detection:**

The profiler must validate that referenced columns have usable data before the test runs:

```python
def validate_column_profile(profile: ColumnProfile) -> list[str]:
    """Validate a column profile has usable data. Returns list of errors."""
    errors = []
    
    if profile.total_count == 0:
        errors.append(f"Column {profile.name}: table is empty")
    
    if profile.null_count == profile.total_count:
        errors.append(f"Column {profile.name}: all values are NULL")
    
    if profile.distinct_count == 0:
        errors.append(f"Column {profile.name}: no distinct non-NULL values")
    
    # For sample-based strategies, ensure we have samples
    if not profile.sample_values:
        errors.append(f"Column {profile.name}: no sample values available")
    
    return errors
```

**Cycle detection for `depends_on` references:**

When parameters reference other parameters via `depends_on`, the system must detect cycles
to prevent infinite loops during generation:

```python
def detect_dependency_cycles(parameters: list[ParameterSpec]) -> list[str]:
    """Detect circular dependencies in parameter specs. Returns list of cycles."""
    
    # Build dependency graph
    deps = {p.name: p.depends_on for p in parameters if p.depends_on}
    
    def find_cycle(start: str, visited: set) -> Optional[list[str]]:
        if start in visited:
            return [start]
        if start not in deps:
            return None
        
        visited.add(start)
        cycle = find_cycle(deps[start], visited)
        if cycle:
            cycle.append(start)
            return cycle
        visited.remove(start)
        return None
    
    cycles = []
    for param_name in deps:
        cycle = find_cycle(param_name, set())
        if cycle:
            cycles.append(" -> ".join(reversed(cycle)))
    
    return cycles

# Usage during template validation
cycles = detect_dependency_cycles(query.parameters)
if cycles:
    raise ValueError(f"Circular parameter dependencies detected: {cycles}")
```

**Profiling query:**
```sql
-- For each column
SELECT 
    COUNT(*) as total_count,
    COUNT(DISTINCT {column}) as distinct_count,
    COUNT(*) - COUNT({column}) as null_count,
    MIN({column}) as min_value,
    MAX({column}) as max_value
FROM {table};

-- For categorical columns (sample top values)
SELECT {column}, COUNT(*) as freq
FROM {table}
WHERE {column} IS NOT NULL
GROUP BY {column}
ORDER BY freq DESC
LIMIT 100;
```

## YAML Configuration Format

Although the UI is the primary configuration surface, this section documents the
equivalent serialized structure stored in template config.

Query entry contract in this plan version:
- Use `query_kind: "GENERIC_SQL"` for arbitrary analytical SQL
- Set `operation_type` explicitly to `READ` or `WRITE`
- `weight_pct` is two-decimal precision and all active query weights sum to `100.00`

### Simple Aggregation

```yaml
custom_queries:
  - query_kind: "GENERIC_SQL"
    operation_type: "READ"
    label: "aggregation"
    weight_pct: 40.00
    sql: |
      SELECT region, SUM(amount) AS total
      FROM {table}
      WHERE order_date >= ?
      GROUP BY 1
    
    parameters:
      - name: "date_cutoff"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"
```

### Multi-Parameter with Dependencies

```yaml
custom_queries:
  - query_kind: "GENERIC_SQL"
    operation_type: "READ"
    label: "aggregation"
    weight_pct: 30.00
    sql: |
      SELECT 
        DATE_TRUNC(?, order_date) AS period,
        region,
        SUM(amount) AS total
      FROM {table}
      WHERE order_date BETWEEN ? AND ?
        AND product_category = ?
      GROUP BY 1, 2
    
    parameters:
      - name: "granularity"
        type: "choice"
        values: ["day", "week", "month", "quarter"]
      
      - name: "start_date"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"
      
      - name: "end_date"
        type: "date"
        strategy: "offset_from_previous"
        depends_on: "start_date"
        offset: [7, 14, 30, 90]
      
      - name: "category"
        type: "categorical"
        strategy: "sample_from_table"
        column: "product_category"
```

### Complex with IN Clause

```yaml
custom_queries:
  - query_kind: "GENERIC_SQL"
    operation_type: "READ"
    label: "aggregation"
    weight_pct: 20.00
    sql: |
      SELECT region, channel, SUM(revenue)
      FROM {table}
      WHERE order_date BETWEEN ? AND ?
        AND region IN (?, ?, ?)
        AND amount > ?
      GROUP BY 1, 2
    
    parameters:
      - name: "start_date"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"
      
      - name: "end_date"
        type: "date"
        strategy: "offset_from_previous"
        depends_on: "start_date"
        offset: [30, 90, 180, 365]
      
      - name: "regions"
        type: "categorical_list"
        strategy: "sample_list"
        column: "region"
        count: 3  # Matches the 3 placeholders in SQL
      
      - name: "min_amount"
        type: "numeric"
        strategy: "random_numeric"
        min: 100
        max: 5000
```

## Variety Analysis

Example query with 4 parameters:

| Parameter | Strategy | Cardinality |
|-----------|----------|-------------|
| granularity | choice(4) | 4 |
| start_date | random_in_range(365 days) | ~365 |
| window_size | offset([7,14,30,90]) | 4 |
| category | sample_from_table(50 values) | 50 |

**Combinatorial variety:** 4 × 365 × 4 × 50 = **292,000 unique combinations**

With cache disabled, this provides meaningful variety for benchmarking.

## Execution Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Template Setup                            │
│                                                              │
│  1. Parse SQL template                                       │
│  2. Extract parameter specs from YAML                        │
│  3. Profile columns referenced in specs                      │
│  4. Pre-sample categorical values                            │
│  5. Store profiles for runtime use                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Query Execution                           │
│                                                              │
│  For each query:                                             │
│  1. Select query template by weight                          │
│  2. Generate params using specs + profiles                   │
│  3. Handle dependent params in order                         │
│  4. Bind params to SQL placeholders                          │
│  5. Execute query                                            │
│  6. Track metrics                                            │
└─────────────────────────────────────────────────────────────┘
```

## Backward Compatibility

For existing OLTP queries, provide **implicit parameter specs**:

```python
# POINT_LOOKUP without explicit params
IMPLICIT_PARAMS = {
    "POINT_LOOKUP": [
        ParameterSpec(
            name="id",
            type="numeric",
            strategy="sample_from_pool",  # Legacy pool-based
            column=None,  # Uses KEY pool
        )
    ],
    "RANGE_SCAN": [
        ParameterSpec(
            name="start_id",
            type="numeric", 
            strategy="sample_from_pool",
        ),
        ParameterSpec(
            name="end_id",
            type="numeric",
            strategy="offset_from_previous",
            depends_on="start_id",
            offset=[100],
        ),
    ],
}
```

Existing templates without `parameters` section continue to work using implicit specs.

## Summary

| Old Approach | New Approach |
|--------------|--------------|
| Infer param type from query_kind | Explicit param specs per query |
| Fixed pools | Multiple generation strategies |
| Single column profiling (id, time) | Full column profiling |
| No dependent params | Support for relative params |
| Limited variety | Combinatorial variety |
