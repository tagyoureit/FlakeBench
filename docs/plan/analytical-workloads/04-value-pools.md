# Parameter Binding for Analytical Queries

How to generate meaningful parameter variety for OLAP workloads.

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

**Storage:** Extend `TEMPLATE_VALUE_POOLS` table with `POOL_KIND = 'COLUMN_PROFILE'` 
or create new `TEMPLATE_COLUMN_PROFILES` table.

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
    count: Optional[list[int]] = None  # How many values to generate
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
def generate_offset(spec: ParameterSpec, context: dict) -> Any:
    base_value = context[spec.depends_on]
    offset_value = random.choice(spec.offset)
    
    if isinstance(base_value, datetime):
        return base_value + timedelta(days=offset_value)
    else:
        return base_value + offset_value
```

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

### Simple Aggregation

```yaml
custom_queries:
  - query_kind: "AGGREGATION"
    weight_pct: 40
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
  - query_kind: "AGGREGATION"
    weight_pct: 30
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
  - query_kind: "AGGREGATION"
    weight_pct: 20
    sql: |
      SELECT region, channel, SUM(revenue)
      FROM {table}
      WHERE order_date BETWEEN ? AND ?
        AND region IN ({regions})
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
        count: [1, 2, 3]
        placeholder: "{regions}"  # Special placeholder for lists
      
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
