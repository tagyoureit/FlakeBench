# Runtime Query Model (Simplified)

Detailed implementation guide for extending the existing OLTP shortcuts with
`GENERIC_SQL`, rather than adding many OLAP-specific runtime enums.

## Key Design Change: Explicit Parameters

Unlike OLTP shortcut kinds (POINT_LOOKUP, RANGE_SCAN, INSERT, UPDATE) where
parameter types can be inferred, `GENERIC_SQL` uses **explicit parameter
specifications**. This allows:

- Multiple parameter types in one query
- Arbitrary dimension filters (not just id/time)
- Variable granularity (hour, day, week, month, year)
- Combinatorial variety for meaningful benchmarks

See `04-value-pools.md` for the full parameter specification system.

## Runtime Query Kinds

| Kind | Purpose | Typical Parameters |
|------|---------|-------------------|
| `POINT_LOOKUP` | Existing OLTP shortcut | key value |
| `RANGE_SCAN` | Existing OLTP shortcut | key/time range |
| `INSERT` | Existing OLTP shortcut | row values |
| `UPDATE` | Existing OLTP shortcut | key + updated values |
| `GENERIC_SQL` | Arbitrary SQL (READ or WRITE) | explicit placeholder mappings |

`ROLLUP`, `WINDOW`, `JOIN`, `APPROX_COUNT_DISTINCT`, and similar constructs are
SQL patterns expressed inside `GENERIC_SQL`, not separate runtime kinds.

## Mix Precision Contract

- `weight_pct` is a decimal with two digits (`0.00` to `100.00`)
- Sum across all active queries must equal `100.00`
- Minimum non-zero mix is `0.01%`, enabling roughly `10000:1` read:write ratios

## File Changes

### Table Placeholder Policy

Only `{table}` is a special placeholder substituted at runtime with the template's
primary table. All other tables (dimension tables, joined tables) should be specified
with fully-qualified names directly in the SQL.

**Rationale:** This simplifies the system - users/AI write complete SQL. The executor
only substitutes the primary table, which may vary between test runs.

```sql
-- {table} is substituted with the template's primary table
-- Dimension tables use fully-qualified names
FROM {table} f
JOIN ANALYTICS_DB.DIM.DIM_DATE d ON f.date_key = d.date_key
JOIN ANALYTICS_DB.DIM.DIM_PRODUCT p ON f.product_key = p.product_key
```

### 1. Constants (`backend/api/routes/templates_modules/constants.py`)

```python
# Keep existing OLTP shortcut keys.
_CUSTOM_QUERY_FIELDS: tuple[str, ...] = (
    "custom_point_lookup_query",
    "custom_range_scan_query",
    "custom_insert_query",
    "custom_update_query",
)

# Add one flexible list for arbitrary queries.
# Each item includes: id, name, query_kind, operation_type, weight_pct, sql, parameters, label.
GENERIC_QUERIES_FIELD = "generic_queries"

ALLOWED_QUERY_KINDS = {
    "POINT_LOOKUP",
    "RANGE_SCAN",
    "INSERT",
    "UPDATE",
    "GENERIC_SQL",
}
```

### 2. Default SQL Templates

```python
# Keep only OLTP shortcut defaults.
# Analytical/advanced SQL is user-authored under GENERIC_SQL entries.
_DEFAULT_CUSTOM_QUERIES_SNOWFLAKE = {
    "custom_point_lookup_query": "SELECT * FROM {table} WHERE id = ?",
    "custom_range_scan_query": "SELECT * FROM {table} WHERE id BETWEEN ? AND ? + 100",
    "custom_insert_query": "INSERT INTO {table} (id, data, timestamp) VALUES (?, ?, CURRENT_TIMESTAMP)",
    "custom_update_query": "UPDATE {table} SET data = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?",
}
```

### 3. Test Executor Metrics (`backend/core/test_executor.py`)

```python
# Initialize metrics for shortcut kinds + GENERIC_SQL

self._find_max_step_lat_by_kind_ms: dict[str, deque[float]] = {
    "POINT_LOOKUP": deque(maxlen=10000),
    "RANGE_SCAN": deque(maxlen=10000),
    "INSERT": deque(maxlen=10000),
    "UPDATE": deque(maxlen=10000),
    "GENERIC_SQL": deque(maxlen=10000),
}

self._find_max_step_ops_by_kind: dict[str, int] = {
    "POINT_LOOKUP": 0,
    "RANGE_SCAN": 0,
    "INSERT": 0,
    "UPDATE": 0,
    "GENERIC_SQL": 0,
}

self._find_max_step_errors_by_kind: dict[str, int] = {
    "POINT_LOOKUP": 0,
    "RANGE_SCAN": 0,
    "INSERT": 0,
    "UPDATE": 0,
    "GENERIC_SQL": 0,
}

self._lat_by_kind_ms: dict[str, list[float]] = {
    "POINT_LOOKUP": [],
    "RANGE_SCAN": [],
    "INSERT": [],
    "UPDATE": [],
    "GENERIC_SQL": [],
}

# Optional: secondary breakdown by user label for GENERIC_SQL
self._lat_by_generic_label_ms: dict[str, list[float]] = {}
```

### 4. Allowed Kinds Validation

```python
# Line ~615: Update allowed set
allowed = {
    "POINT_LOOKUP",
    "RANGE_SCAN",
    "INSERT",
    "UPDATE",
    "GENERIC_SQL",
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
    # Generic SQL defaults (can be overridden per-query in config if needed)
    "GENERIC_SQL": {"p95_ms": 5000, "p99_ms": 10000, "error_pct": 1.0},
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
    "GENERIC_SQL": "Generic SQL",
}
```

### 7. Execution Dispatch (`_execute_custom`)

```python
# Lines 3318-3470: Dispatch with GENERIC_SQL support
if query_kind == "GENERIC_SQL":
    # Generic SQL can be READ or WRITE. Both use explicit parameter mappings.
    # No query-shape inference is performed in this path.
    generator = self._get_param_generator(worker_id)
    params = generator.generate(query.parameters or [])
    operation_type = str(query.operation_type or "READ").upper()
else:
    # OLTP shortcut backward-compatible path.
    params = self._legacy_generate_params(query_kind)
    operation_type = "READ" if query_kind in {"POINT_LOOKUP", "RANGE_SCAN"} else "WRITE"
```

### Validation Rule: Generic SQL Requires Explicit Operation Type

```python
def validate_query_entry(query: QueryEntry) -> None:
    """Validate a query entry from custom_queries/generic_queries."""
    if query.query_kind == "GENERIC_SQL":
        if str(query.operation_type or "").upper() not in {"READ", "WRITE"}:
            raise ValidationError("GENERIC_SQL requires operation_type READ or WRITE.")
        # Parameters are optional only when the SQL has no placeholders.
        if sql_has_placeholders(query.sql) and not query.parameters:
            raise ValidationError(
                "GENERIC_SQL with placeholders must define parameters."
            )
    elif query.query_kind in {"POINT_LOOKUP", "RANGE_SCAN", "INSERT", "UPDATE"}:
        # Existing shortcut validations remain.
        pass
    else:
        raise ValidationError(
            f"Unsupported query_kind: {query.query_kind}"
        )
```

This guard should run at template save/prepare time so runtime failures are rare
and users get immediate feedback in the builder UI.

## Read vs Write Classification

```python
# Read/write classification
if query_kind == "GENERIC_SQL":
    is_read = str(operation_type or "").upper() == "READ"
else:
    is_read = query_kind in {"POINT_LOOKUP", "RANGE_SCAN"}
```

For `GENERIC_SQL`, read/write is explicit via `operation_type`.

## Testing Strategy

1. **Unit test** each new helper method
2. **Integration test** each query kind execution
3. **Validation test** that metrics are properly tracked
4. **End-to-end test** with sample YAML scenario
