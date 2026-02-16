# YAML Configuration for Analytical Workloads

How to configure analytical scenarios with explicit parameter specifications.

## Key Concept: Explicit Parameters

Unlike OLTP queries where parameter types are inferred from query kind, analytical queries require **explicit parameter specifications** for each `?` placeholder.

```yaml
custom_queries:
  - query_kind: "AGGREGATION"
    sql: "SELECT ... WHERE date >= ? AND region = ?"
    parameters:           # NEW: Explicit specs for each ?
      - name: "date"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"
      - name: "region"
        type: "categorical"
        strategy: "sample_from_table"
        column: "region"
```

## Full Template Structure

```yaml
# ============================================================================
# TEMPLATE METADATA
# ============================================================================
name: "Analytical Benchmark - Multi-Dimension"
description: "Tests columnar performance with varied parameter combinations"
version: "2.0"
category: "OLAP"

# ============================================================================
# TABLE CONFIGURATION
# ============================================================================
table:
  name: "fact_orders"
  table_type: "STANDARD"
  database: "ANALYTICS_DB"
  schema: "PUBLIC"
  
  columns:
    order_id: "NUMBER"
    order_date: "DATE"
    region: "VARCHAR(50)"
    product_category: "VARCHAR(50)"
    channel: "VARCHAR(50)"
    quantity: "NUMBER"
    amount: "NUMBER(12,2)"
  
  clustering_keys:
    - "order_date"
    - "region"

# ============================================================================
# COLUMN PROFILING (for parameter generation)
# ============================================================================
profile_columns:
  - name: "order_date"
    type: "date"
    # System will auto-detect min/max
  
  - name: "region"
    type: "categorical"
    sample_size: 100      # Top 100 values by frequency
  
  - name: "product_category"
    type: "categorical"
    sample_size: 100
  
  - name: "channel"
    type: "categorical"
    sample_size: 50
  
  - name: "amount"
    type: "numeric"
    # System will auto-detect min/max

# ============================================================================
# WORKLOAD CONFIGURATION
# ============================================================================
workload:
  type: "CUSTOM"

custom_queries:
  # -------------------------------------------------------------------------
  # Query 1: Simple aggregation with date filter
  # -------------------------------------------------------------------------
  - query_kind: "AGGREGATION"
    weight_pct: 25
    sql: |
      SELECT 
        region,
        SUM(amount) AS total_revenue,
        COUNT(*) AS order_count
      FROM {table}
      WHERE order_date >= ?
      GROUP BY 1
      ORDER BY 2 DESC
    
    parameters:
      - name: "date_cutoff"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"

  # -------------------------------------------------------------------------
  # Query 2: Time-series with variable granularity
  # -------------------------------------------------------------------------
  - query_kind: "AGGREGATION"
    weight_pct: 20
    sql: |
      SELECT 
        DATE_TRUNC(?, order_date) AS period,
        SUM(amount) AS total
      FROM {table}
      WHERE order_date BETWEEN ? AND ?
      GROUP BY 1
      ORDER BY 1
    
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
        offset: [7, 14, 30, 90, 180, 365]

  # -------------------------------------------------------------------------
  # Query 3: Multi-dimension filter
  # -------------------------------------------------------------------------
  - query_kind: "AGGREGATION"
    weight_pct: 20
    sql: |
      SELECT 
        region,
        product_category,
        SUM(amount) AS total
      FROM {table}
      WHERE order_date BETWEEN ? AND ?
        AND region = ?
        AND channel = ?
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
        offset: [30, 90]
      
      - name: "region"
        type: "categorical"
        strategy: "sample_from_table"
        column: "region"
      
      - name: "channel"
        type: "categorical"
        strategy: "sample_from_table"
        column: "channel"

  # -------------------------------------------------------------------------
  # Query 4: Window function
  # -------------------------------------------------------------------------
  - query_kind: "WINDOWED"
    weight_pct: 15
    sql: |
      SELECT 
        order_id,
        order_date,
        amount,
        SUM(amount) OVER (
          PARTITION BY region 
          ORDER BY order_date
          ROWS UNBOUNDED PRECEDING
        ) AS cumulative
      FROM {table}
      WHERE order_date BETWEEN ? AND ?
        AND region = ?
      ORDER BY order_date
      LIMIT 10000
    
    parameters:
      - name: "start_date"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"
      
      - name: "end_date"
        type: "date"
        strategy: "offset_from_previous"
        depends_on: "start_date"
        offset: [30, 60, 90]
      
      - name: "region"
        type: "categorical"
        strategy: "sample_from_table"
        column: "region"

  # -------------------------------------------------------------------------
  # Query 5: Approximate distinct with threshold
  # -------------------------------------------------------------------------
  - query_kind: "APPROX_DISTINCT"
    weight_pct: 10
    sql: |
      SELECT 
        DATE_TRUNC(?, order_date) AS period,
        region,
        APPROX_COUNT_DISTINCT(customer_id) AS unique_customers
      FROM {table}
      WHERE order_date BETWEEN ? AND ?
        AND amount > ?
      GROUP BY 1, 2
      HAVING APPROX_COUNT_DISTINCT(customer_id) > ?
    
    parameters:
      - name: "granularity"
        type: "choice"
        values: ["day", "week", "month"]
      
      - name: "start_date"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"
      
      - name: "end_date"
        type: "date"
        strategy: "offset_from_previous"
        depends_on: "start_date"
        offset: [30, 90, 180]
      
      - name: "min_amount"
        type: "numeric"
        strategy: "random_numeric"
        min: 0
        max: 1000
      
      - name: "min_customers"
        type: "numeric"
        strategy: "choice"
        values: [10, 50, 100, 500]

  # -------------------------------------------------------------------------
  # Query 6: OLTP baseline (for comparison)
  # -------------------------------------------------------------------------
  - query_kind: "POINT_LOOKUP"
    weight_pct: 10
    sql: |
      SELECT * FROM {table} WHERE order_id = ?
    
    parameters:
      - name: "order_id"
        type: "numeric"
        strategy: "sample_from_pool"
        pool: "KEY"

# ============================================================================
# TEST PARAMETERS
# ============================================================================
test:
  duration_seconds: 600
  concurrent_connections: 10
  warmup_seconds: 60
  
  targets:
    min_ops_per_second: 5
    max_p95_latency_ms: 10000
    max_p99_latency_ms: 20000
    max_error_rate_percent: 1.0
```

## Parameter Type Reference

### `choice` - Explicit List

```yaml
- name: "granularity"
  type: "choice"
  values: ["hour", "day", "week", "month", "quarter", "year"]
```

### `date` with `random_in_range`

```yaml
- name: "start_date"
  type: "date"
  strategy: "random_in_range"
  column: "order_date"    # Uses profiled min/max
```

### `date` with `offset_from_previous`

```yaml
- name: "end_date"
  type: "date"
  strategy: "offset_from_previous"
  depends_on: "start_date"
  offset: [7, 14, 30, 90, 365]  # Days
```

### `categorical` with `sample_from_table`

```yaml
- name: "region"
  type: "categorical"
  strategy: "sample_from_table"
  column: "region"
```

### `categorical` with `weighted_sample`

```yaml
- name: "product_category"
  type: "categorical"
  strategy: "weighted_sample"  # Match data distribution
  column: "product_category"
```

### `categorical_list` for IN clauses

```yaml
- name: "regions"
  type: "categorical_list"
  strategy: "sample_list"
  column: "region"
  count: [1, 2, 3, 4]     # Random count
  placeholder: "{regions}"  # Special placeholder
```

SQL usage:
```sql
WHERE region IN ({regions})
```

### `numeric` with `random_numeric`

```yaml
- name: "min_amount"
  type: "numeric"
  strategy: "random_numeric"
  min: 0
  max: 10000
```

### `numeric` with `sample_from_pool` (OLTP compatibility)

```yaml
- name: "order_id"
  type: "numeric"
  strategy: "sample_from_pool"
  pool: "KEY"
```

## Placeholder Syntax

### Standard Placeholders

| Database | Syntax | Example |
|----------|--------|---------|
| Snowflake | `?` | `WHERE id = ?` |
| Postgres | `$1, $2, ...` | `WHERE id = $1` |

Parameters are bound **in order** of the `parameters` list.

### List Placeholders

For IN clauses, use named placeholders:

```yaml
parameters:
  - name: "regions"
    type: "categorical_list"
    placeholder: "{regions}"
```

```sql
WHERE region IN ({regions})
```

The system expands `{regions}` to `?, ?, ?` (or `$1, $2, $3`) based on generated count.

### Table Placeholders

| Placeholder | Replacement |
|-------------|-------------|
| `{table}` | Fully qualified fact table name |
| `{dim_date}` | Dimension table (if configured) |

## Scenario Examples

### Pure OLAP - High Variety

```yaml
name: "OLAP High Variety"
category: "OLAP"

custom_queries:
  - query_kind: "AGGREGATION"
    weight_pct: 100
    sql: |
      SELECT 
        DATE_TRUNC(?, order_date) AS period,
        region,
        product_category,
        SUM(amount) AS total
      FROM {table}
      WHERE order_date BETWEEN ? AND ?
        AND region = ?
      GROUP BY 1, 2, 3
    
    parameters:
      # 6 granularities × 365 start dates × 6 windows × 5 regions
      # = 65,700 unique combinations
      - name: "granularity"
        type: "choice"
        values: ["hour", "day", "week", "month", "quarter", "year"]
      
      - name: "start_date"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"
      
      - name: "end_date"
        type: "date"
        strategy: "offset_from_previous"
        depends_on: "start_date"
        offset: [1, 7, 30, 90, 180, 365]
      
      - name: "region"
        type: "categorical"
        strategy: "sample_from_table"
        column: "region"
```

### HTAP Mixed Workload

```yaml
name: "HTAP Mixed"
category: "HTAP"

custom_queries:
  # 40% OLTP
  - query_kind: "POINT_LOOKUP"
    weight_pct: 30
    sql: "SELECT * FROM {table} WHERE order_id = ?"
    parameters:
      - name: "id"
        type: "numeric"
        strategy: "sample_from_pool"
        pool: "KEY"
  
  - query_kind: "INSERT"
    weight_pct: 10
    sql: "INSERT INTO {table} (order_id, amount) VALUES (?, ?)"
    parameters:
      - name: "id"
        type: "numeric"
        strategy: "sequence"
      - name: "amount"
        type: "numeric"
        strategy: "random_numeric"
        min: 10
        max: 1000
  
  # 60% OLAP
  - query_kind: "AGGREGATION"
    weight_pct: 40
    sql: |
      SELECT region, SUM(amount) FROM {table}
      WHERE order_date BETWEEN ? AND ?
      GROUP BY 1
    parameters:
      - name: "start"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"
      - name: "end"
        type: "date"
        strategy: "offset_from_previous"
        depends_on: "start"
        offset: [7, 30, 90]
  
  - query_kind: "APPROX_DISTINCT"
    weight_pct: 20
    sql: |
      SELECT APPROX_COUNT_DISTINCT(customer_id)
      FROM {table}
      WHERE order_date >= ?
    parameters:
      - name: "cutoff"
        type: "date"
        strategy: "random_in_range"
        column: "order_date"
```

## Validation Rules

1. **Parameter count must match placeholders** - Number of `?` in SQL = number of `parameters`
2. **Dependent params must reference earlier params** - `depends_on` must reference a previously defined parameter
3. **Column references must exist** - `column` must be in `profile_columns`
4. **Pool references require pool type** - `strategy: sample_from_pool` needs `pool: KEY|RANGE`
5. **List placeholders need placeholder name** - `categorical_list` requires `placeholder` field
6. **Weight percentages must sum to 100**

## Backward Compatibility

Existing OLTP templates without `parameters` section continue to work:

```yaml
# Old format (still works)
custom_queries:
  - query_kind: "POINT_LOOKUP"
    weight_pct: 100
    sql: "SELECT * FROM {table} WHERE id = ?"
    # No parameters section - uses implicit OLTP binding
```

The system applies **implicit parameter specs** based on query_kind for backward compatibility.
