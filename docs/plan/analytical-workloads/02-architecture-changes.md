# Architecture Changes Overview

High-level modifications needed to support analytical workloads.

> **Decision update (2026-02-16):** Runtime kinds are simplified to
> `POINT_LOOKUP`, `RANGE_SCAN`, `INSERT`, `UPDATE`, and `GENERIC_SQL`.
> Analytical constructs (including `ROLLUP/CUBE`) are SQL patterns under
> `GENERIC_SQL`, with explicit `operation_type` and 2-decimal `weight_pct`.

## Current Architecture (OLTP-Focused)

```
┌─────────────────────────────────────────────────────────────┐
│                         UI / Config                          │
│  - User selects table                                        │
│  - System auto-detects key_column, time_column               │
│  - User sets workload mix (2-decimal weights, e.g. 99.99/0.01)│
│  - User can edit SQL templates                               │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Prepare (Profile)                        │
│  - Sample KEY values into TEMPLATE_VALUE_POOLS               │
│  - Sample RANGE (time) values into TEMPLATE_VALUE_POOLS      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Test Executor                            │
│  - Dispatch by query_kind (POINT_LOOKUP, RANGE_SCAN, etc.)  │
│  - Parameter type INFERRED from query_kind                   │
│  - Pull values from pre-sampled pools                        │
└─────────────────────────────────────────────────────────────┘
```

**Limitation:** Parameter types are inferred from query_kind. This works for OLTP
(point lookups always need an ID) but fails for OLAP where queries:
- Filter on arbitrary dimensions (not just id/time)
- Span multiple tables (JOINs)
- Have variable granularity (hour/day/week/month/year)

## Proposed Architecture (OLAP-Capable)

```
┌─────────────────────────────────────────────────────────────┐
│                    UI: Table Selection                       │
│  User selects tables to include in query:                    │
│    ☑ sales_fact    ☑ dim_region    ☑ dim_product            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 UI: Natural Language Intent                  │
│  User describes query: "Analyze sales by region and time,   │
│  filter by product category"                                 │
│                                                              │
│  [Generate SQL]                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    AI SQL Generation                         │
│  - Receives table schemas as context                         │
│  - Generates SQL with ? placeholders                         │
│  - User can refine/regenerate/edit                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 UI: Parameter Mapping                        │
│  For each ? placeholder:                                     │
│    ?1: [Table: sales_fact▼] [Column: order_date▼]           │
│        [Strategy: random_in_range▼]                          │
│    ?2: [Strategy: offset_from_previous▼] [Depends: ?1▼]     │
│    ?3: [Table: dim_product▼] [Column: category▼]            │
│        [Strategy: sample_from_table▼]                        │
└─────────────────────────────────────────────────────────────┘

> **Note on placeholder syntax:** The `?1`, `?2`, `?3` labels shown above are 
> **UI display notation only**. The actual SQL uses plain `?` placeholders which
> are bound positionally (first `?` gets first param, second `?` gets second, etc.).
> - **Snowflake:** `?` (positional) or `%(name)s` (named)
> - **Postgres:** `$1`, `$2`, `$n` (numbered)
> - **Table substitution:** `{table}` is replaced with the full qualified table name

                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Prepare: Column Profiling                    │
│  Profile ONLY columns referenced in parameter configs:       │
│    - sales_fact.order_date → min/max dates                  │
│    - dim_product.category → distinct values                 │
│  Store in TEMPLATE_COLUMN_PROFILES (not value pools)        │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                 Pre-Flight Correctness Gate                 │
│  - Validate placeholder mappings for OLAP queries           │
│  - Validate non-approx query semantics                      │
│  - Validate approximate-cardinality error tolerance          │
│  - Block benchmark run on failure                           │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                  Runtime: Parameter Generator                │
│  For each query execution:                                   │
│    - Read parameter configs                                  │
│    - Generate values on-the-fly from profiles               │
│    - Handle dependencies (end_date from start_date)         │
│    - Return ordered list to bind to SQL                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     Test Executor                            │
│  - Dispatch by query_kind (POINT/RANGE/INSERT/UPDATE/GENERIC_SQL) │
│  - Bind generated params to SQL                              │
│  - Track metrics per runtime kind + optional generic label   │
└─────────────────────────────────────────────────────────────┘
```

**Key changes:**
1. **UI-driven** - No manual YAML editing
2. **AI-assisted SQL** - Natural language → SQL with placeholders
3. **Multi-table support** - JOINs handled naturally
4. **Explicit parameter mapping** - User maps each ? to table.column + strategy
5. **Column profiles** - Lightweight metadata, not pre-sampled value pools
6. **Correctness gate** - Validates analytical templates before perf execution
7. **Inherited methodology controls** - Uses existing cache/warmup/trial controls

## Component Changes

### 1. New UI Components

| Component | Purpose |
|-----------|---------|
| Table Selector | Multi-select tables from schema |
| Intent Input | Natural language query description |
| SQL Generator | AI-powered SQL generation |
| SQL Editor | Review/edit generated SQL |
| Parameter Mapper | Configure each ? placeholder |
| Query Manager | Add/edit/delete multiple queries |

**Location:** `backend/templates/pages/configure.html`

### 2. Canonical Backend Endpoints (No Aliases)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/catalog/objects` | List objects in schema (tables/views, filterable to tables) |
| `GET /api/catalog/columns` | Get columns/types/samples for a selected table |
| `POST /api/templates/ai/generate-sql` | AI generates SQL from intent + schema context |
| `POST /api/templates/ai/validate-sql` | Validate SQL syntax/shape before save |
| `POST /api/templates/{template_id}/ai/profile-columns` | Profile referenced columns for the template |

**Route ownership (single surface per concern):**
- `backend/api/routes/catalog.py` for discovery metadata
- `backend/api/routes/templates.py` for template-scoped AI actions

### 3. Column Profiler (NEW)

```python
# backend/core/column_profiler.py

@dataclass
class ColumnProfile:
    """
    Statistical profile of a table column.
    
    CANONICAL DEFINITION: See 04-value-pools.md for the complete field list
    including null_count, total_count, and validation methods.
    """
    table: str
    column: str
    data_type: str
    min_value: Any | None
    max_value: Any | None
    distinct_count: int
    null_count: int           # For empty/NULL detection
    total_count: int          # For empty table detection
    sample_values: list[Any]
    value_weights: dict[Any, float]  # For weighted sampling

async def profile_columns(
    conn,
    column_refs: list[tuple[str, str]]  # [(table, column), ...]
) -> dict[str, ColumnProfile]:
    """Profile specific columns from potentially different tables."""
    ...
```

### 4. Parameter Generator (NEW)

```python
# backend/core/param_generator.py

class ParameterGenerator:
    def __init__(self, profiles: dict[str, ColumnProfile]):
        self._profiles = profiles
    
    def generate(self, param_configs: list[ParameterConfig]) -> list[Any]:
        """Generate values for all parameters in a query."""
        values = []
        context = {}  # For dependent params
        
        for config in param_configs:
            value = self._generate_one(config, context)
            values.append(value)
            context[config.position] = value
        
        return values
```

### 5. Extended Test Executor

**Location:** `backend/core/test_executor.py`

```python
# Use a simplified runtime kind model
ALLOWED_QUERY_KINDS = {
    "POINT_LOOKUP",
    "RANGE_SCAN",
    "INSERT",
    "UPDATE",
    "GENERIC_SQL",
}

async def _execute_custom(self, worker_id: int, warmup: bool = False):
    query = self._select_query_by_weight()

    if query.query_kind == "GENERIC_SQL":
        # Explicit mapping path for arbitrary SQL.
        generator = ParameterGenerator(self._column_profiles)
        params = generator.generate(query.parameters or [])
        operation_type = str(query.operation_type or "READ").upper()
    else:
        # Backward-compatible shortcut path.
        params = self._legacy_generate_params(query.query_kind)
        operation_type = "READ" if query.query_kind in {"POINT_LOOKUP", "RANGE_SCAN"} else "WRITE"

    result = await conn.execute(query.sql, params)
```

> **Architectural recommendation:** Consider extracting a `QueryKindDispatcher` class
> from `test_executor.py`. This would:
> - Centralize query kind registration and validation
> - Make it easier to add new query kinds without modifying executor core
> - Enable per-kind metric collection strategies
> - Improve testability by isolating dispatch logic
>
> ```python
> # backend/core/query_kind_dispatcher.py (future refactor)
> class QueryKindDispatcher:
>     """Registry for query kinds and their execution strategies."""
>     
>     _registry: dict[str, QueryKindConfig] = {}
>     
>     @classmethod
>     def register(cls, kind: str, config: QueryKindConfig):
>         cls._registry[kind] = config
>     
>     @classmethod
>     def get_slo(cls, kind: str) -> dict:
>         return cls._registry[kind].slo_thresholds
>     
>     @classmethod
>     def is_olap(cls, kind: str) -> bool:
>         return cls._registry[kind].category == "OLAP"
> ```

### 6. Storage Schema

**New table for column profiles:**

```sql
CREATE TABLE TEMPLATE_COLUMN_PROFILES (
    TEMPLATE_ID VARCHAR NOT NULL,
    TABLE_NAME VARCHAR NOT NULL,
    COLUMN_NAME VARCHAR NOT NULL,
    DATA_TYPE VARCHAR,
    MIN_VALUE VARIANT,
    MAX_VALUE VARIANT,
    DISTINCT_COUNT NUMBER,
    SAMPLE_VALUES VARIANT,  -- JSON array
    VALUE_WEIGHTS VARIANT,  -- JSON object
    PROFILED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (TEMPLATE_ID, TABLE_NAME, COLUMN_NAME)
);
```

**Extended template config (JSON):**

```json
{
  "analytical_queries": [
    {
      "id": "q1",
      "name": "Sales by Region",
      "query_kind": "GENERIC_SQL",
      "operation_type": "READ",
      "label": "aggregation",
      "weight_pct": 40.00,
      "sql": "SELECT r.region_name, SUM(f.amount) ...",
      "parameters": [
        {"position": 1, "table": "sales_fact", "column": "order_date", "strategy": "random_in_range"},
        {"position": 2, "table": "dim_region", "column": "region", "strategy": "sample_from_table"}
      ]
    }
  ]
}
```

## File Modification Summary

| File | Changes |
|------|---------|
| `backend/templates/pages/configure.html` | Add analytical query builder UI |
| `backend/api/routes/catalog.py` | Extend discovery endpoints with table-column metadata |
| `backend/api/routes/templates.py` | Add template-scoped SQL generation, validation, profiling endpoints |
| `backend/core/column_profiler.py` | NEW: Profile columns across tables |
| `backend/core/param_generator.py` | NEW: Generate params from profiles |
| `backend/core/test_executor.py` | Add OLAP query kinds, use param generator |
| `backend/api/routes/templates_modules/constants.py` | Add OLAP query kind constants |
| `backend/sql/schema/` | Add TEMPLATE_COLUMN_PROFILES table |

## Backward Compatibility

- Existing OLTP templates work unchanged
- `analytical_queries` is a new optional config section
- If no explicit parameters, falls back to legacy pool-based generation
- No migration needed for existing templates

## Mix Precision

- `weight_pct` supports two decimal places (`0.00` to `100.00`)
- Total query mix must equal exactly `100.00`
- This enables very skewed mixes (for example, approximately `10000:1` read:write)
