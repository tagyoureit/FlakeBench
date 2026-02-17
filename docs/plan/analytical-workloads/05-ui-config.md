# UI Configuration for Analytical Queries

This document describes the UI-based workflow for configuring OLAP queries.
No manual YAML editing required.

> **Decision update (2026-02-16):** Keep OLTP shortcuts and support any number of
> `GENERIC_SQL` entries in the same test mix. `ROLLUP/CUBE` is handled in SQL text
> (not as a runtime kind). Query weights use 2-decimal precision.

## Overview: SQL-First Approach

```
User selects tables → Describes intent (natural language) → AI generates SQL
→ User maps placeholders → System profiles columns → Ready to run
```

**Why SQL-first:**
- Supports multi-table JOINs naturally
- Profiles only columns actually used
- User has full context when mapping parameters

## API Contract (Canonical, No Aliases)

Use one endpoint family per concern:

| Concern | Endpoint |
|---------|----------|
| List tables/views for selection | `GET /api/catalog/objects` |
| Fetch selected table columns | `GET /api/catalog/columns` |
| Generate SQL from intent | `POST /api/templates/ai/generate-sql` |
| Validate SQL before save | `POST /api/templates/ai/validate-sql` |
| Profile mapped columns on prepare | `POST /api/templates/{template_id}/ai/profile-columns` |

## Complete UI Flow

### Step 1: Select Tables

User selects which tables to include in the analytical query:

```
┌─────────────────────────────────────────────────────────────┐
│ Analytical Query Builder                                    │
├─────────────────────────────────────────────────────────────┤
│ Select tables for this query:                               │
│                                                             │
│   Database: [ANALYTICS_DB ▼]  Schema: [PUBLIC ▼]           │
│                                                             │
│   ☑ sales_fact         (125M rows)   Fact table            │
│   ☑ dim_region         (50 rows)     Dimension             │
│   ☑ dim_product        (10K rows)    Dimension             │
│   ☐ dim_customer       (1M rows)     Dimension             │
│   ☐ dim_time           (3.6K rows)   Dimension             │
│                                                             │
│ Selected: 3 tables                                          │
└─────────────────────────────────────────────────────────────┘
```

**Implementation:** Call `GET /api/catalog/objects` (filtered to table objects) to list available tables.

### Step 2: Describe Intent (Natural Language)

User describes what they want to analyze:

```
┌─────────────────────────────────────────────────────────────┐
│ Describe your analytical query:                             │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Analyze sales performance by region and time period,   │ │
│ │ with filters for date range and product category.      │ │
│ │ Show total sales and order count.                      │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Query type: [Aggregation ▼]  (helps AI choose patterns)    │
│                                                             │
│ [Generate SQL]                                              │
└─────────────────────────────────────────────────────────────┘
```

**Query type hints** guide AI toward appropriate patterns:
- Aggregation → GROUP BY with SUM/COUNT/AVG
- Windowed → Window functions, QUALIFY
- Cardinality → APPROX_COUNT_DISTINCT

`ROLLUP/CUBE` is treated as a SQL pattern inside generated or user-edited SQL,
not a dedicated runtime query kind.

### Step 3: AI Generates SQL

System calls AI with schema context:

```
┌─────────────────────────────────────────────────────────────┐
│ Generated SQL                                               │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ SELECT                                                  │ │
│ │   r.region_name,                                        │ │
│ │   DATE_TRUNC(?, f.order_date) as period,               │ │
│ │   SUM(f.amount) as total_sales,                        │ │
│ │   COUNT(*) as order_count                              │ │
│ │ FROM sales_fact f                                       │ │
│ │ JOIN dim_region r ON f.region_id = r.region_id         │ │
│ │ JOIN dim_product p ON f.product_id = p.product_id      │ │
│ │ WHERE f.order_date BETWEEN ? AND ?                      │ │
│ │   AND p.category = ?                                    │ │
│ │ GROUP BY 1, 2                                           │ │
│ │ ORDER BY 1, 2                                           │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ✓ SQL syntax valid                                          │
│ ✓ 4 placeholders detected                                   │
│                                                             │
│ [Accept & Configure Parameters]  [Regenerate]  [Edit]       │
└─────────────────────────────────────────────────────────────┘
```

**Error handling:** If AI generates invalid SQL, the UI shows inline validation errors:

```
┌─────────────────────────────────────────────────────────────┐
│ Generated SQL                                               │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ SELECT foo, SUM(bar)                                    │ │
│ │ FROM sales_fact                                         │ │
│ │ WHERE created_at > ?                                    │ │
│ │ GROUP BY 1                                              │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ ✗ Validation failed:                                        │
│   Column 'foo' not found in table 'sales_fact'              │
│                                                             │
│ [Edit SQL]  [Regenerate]                                    │
│                                                             │
│ Note: "Accept" is disabled until SQL is valid.              │
└─────────────────────────────────────────────────────────────┘
```

**User-in-loop recovery:** The user can:
1. **Edit** - Manually fix the SQL in the editor
2. **Regenerate** - Try AI generation again (optionally with refined intent)

No automatic retry loop - the user controls recovery. The "Accept" button remains
disabled until validation passes.

**Refinement option** if SQL doesn't match intent:

```
┌─────────────────────────────────────────────────────────────┐
│ Refine your request (optional):                             │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Also add a filter for orders over $1000                │ │
│ └─────────────────────────────────────────────────────────┘ │
│ [Regenerate with refinement]                                │
└─────────────────────────────────────────────────────────────┘
```

### Step 4: Map Placeholders to Parameters

For each `?` placeholder, user configures how values are generated:

```
┌─────────────────────────────────────────────────────────────┐
│ Configure Parameters                                        │
├─────────────────────────────────────────────────────────────┤
│ Parameter ?1 - Granularity (DATE_TRUNC argument)           │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Type:     [Choice ▼]                                    │ │
│ │ Values:   [day] [week] [month] [quarter] [+]            │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Parameter ?2 - Start Date                                   │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Table:    [sales_fact ▼]                                │ │
│ │ Column:   [order_date ▼]                                │ │
│ │ Strategy: [Random in range ▼]                           │ │
│ │           Generates random dates between min/max        │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Parameter ?3 - End Date                                     │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Strategy: [Offset from previous ▼]                      │ │
│ │ Based on: [?2 Start Date ▼]                             │ │
│ │ Offsets:  [7] [30] [90] [365] days [+]                  │ │
│ │           Randomly picks offset to add to start date    │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Parameter ?4 - Category                                     │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Table:    [dim_product ▼]                               │ │
│ │ Column:   [category ▼]                                  │ │
│ │ Strategy: [Sample from table ▼]                         │ │
│ │           Picks random value from distinct values       │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                             │
│ Estimated query variety: ~43,800 unique combinations        │
│ (4 granularities × 365 dates × 6 offsets × 5 categories)   │
│                                                             │
│ [Save Query]  [Add Another Query]                           │
└─────────────────────────────────────────────────────────────┘
```

### Step 5: Prepare (Profile Columns)

When user clicks "Prepare", system profiles only the referenced columns:

```
┌─────────────────────────────────────────────────────────────┐
│ Preparing Analytical Queries...                             │
├─────────────────────────────────────────────────────────────┤
│ Profiling columns:                                          │
│   ✓ sales_fact.order_date                                   │
│     min: 2020-01-01, max: 2024-12-31                       │
│   ✓ dim_product.category                                    │
│     5 distinct values: Electronics, Clothing, Home, ...    │
│                                                             │
│ Storing column profiles...                                  │
│   ✓ Saved to TEMPLATE_COLUMN_PROFILES                       │
│                                                             │
│ Ready to run benchmarks!                                    │
└─────────────────────────────────────────────────────────────┘
```

## Strategy Options (Dropdown)

| Strategy | Description | When to use |
|----------|-------------|-------------|
| **Choice** | Pick from explicit list | Enums, granularity levels |
| **Random in range** | Random value between min/max | Dates, numeric thresholds |
| **Sample from table** | Random from distinct values | Categorical dimensions |
| **Weighted sample** | Frequency-weighted random | Realistic distributions |
| **Offset from previous** | Add offset to prior param | Date range end |
| **Sample list** | Pick N values for IN clause | Multi-select filters |

## Realism and Methodology Settings

Expose optional advanced controls in the UI with safe defaults:

```text
[Advanced Benchmark Controls]
  Realism profile: [BASELINE ▼]
  NULL rate override: [      ]   (optional)
  Skew factor:        [      ]   (optional)
  Late-arrival lags:  [0,1,3,7]  (optional)
  Selectivity bands:  [0.001,0.01,0.1,0.5] (optional)
```

Required defaults:

- Realism defaults to `BASELINE` when not set.
- Methodology controls are inherited from existing runner/template settings.
- Existing templates remain valid without additional fields.

## AI Prompt Construction

When user clicks "Generate SQL":

```python
async def generate_sql_from_intent(
    tables: list[str],
    intent: str,
    query_type: str
) -> GeneratedQuery:
    # Get schema for selected tables
    schemas = {}
    for table in tables:
        schemas[table] = await get_table_schema_via_catalog(table)
    
    prompt = f"""
Generate an analytical SQL query for Snowflake.

User intent: {intent}
Query type: {query_type}

Available tables and their columns:
{format_schemas_for_ai(schemas)}

Requirements:
1. Use ? placeholders for ALL dynamic filter values
2. Include appropriate JOINs between tables
3. Use aggregation functions (SUM, COUNT, AVG) for metrics
4. Add GROUP BY for dimensional grouping
5. For {query_type}:
   {"- Use GROUP BY with SUM/COUNT/AVG patterns" if query_type == "Aggregation" else ""}
   {"- Use window functions with OVER() and QUALIFY" if query_type == "Windowed" else ""}
   {"- Use APPROX_COUNT_DISTINCT for cardinality" if query_type == "Cardinality" else ""}
6. If hierarchical rollups are needed, use GROUP BY ROLLUP/CUBE directly in SQL

Return only valid Snowflake SQL. No explanations.
"""
    
    sql = await call_ai(prompt)

    # Validate SQL syntax via templates AI endpoint
    is_valid, error = await validate_sql_via_templates_api(sql)
    
    # Count placeholders
    placeholder_count = sql.count('?')
    
    return GeneratedQuery(
        sql=sql,
        is_valid=is_valid,
        error=error,
        placeholder_count=placeholder_count,
        tables_used=extract_tables_from_sql(sql)
    )
```

## Schema Context for AI

```python
def format_schemas_for_ai(schemas: dict[str, TableSchema]) -> str:
    """Format table schemas for AI prompt."""
    output = []
    for table, schema in schemas.items():
        output.append(f"Table: {table}")
        output.append(f"  Row count: ~{schema.row_count:,}")
        output.append(f"  Columns:")
        for col in schema.columns:
            sample = f" (e.g., {col.sample_values[:3]})" if col.sample_values else ""
            output.append(f"    - {col.name}: {col.data_type}{sample}")
        
        if schema.primary_key:
            output.append(f"  Primary key: {schema.primary_key}")
        if schema.foreign_keys:
            output.append(f"  Foreign keys: {schema.foreign_keys}")
        output.append("")
    
    return "\n".join(output)
```

Example output:
```
Table: sales_fact
  Row count: ~125,000,000
  Columns:
    - order_id: NUMBER (e.g., [1001, 1002, 1003])
    - order_date: DATE (e.g., ['2024-01-15', '2024-02-20'])
    - amount: NUMBER (e.g., [150.00, 299.99, 45.50])
    - region_id: NUMBER
    - product_id: NUMBER
  Primary key: order_id
  Foreign keys: region_id → dim_region.region_id, product_id → dim_product.product_id

Table: dim_region
  Row count: ~50
  Columns:
    - region_id: NUMBER
    - region_name: VARCHAR (e.g., ['US-EAST', 'US-WEST', 'EU-NORTH'])
    - country: VARCHAR
  Primary key: region_id
```

## Multiple Queries Per Template

Users can add multiple analytical queries with different weights:

```
┌─────────────────────────────────────────────────────────────┐
│ Analytical Queries                                          │
├─────────────────────────────────────────────────────────────┤
│ Query 1: Point Lookup Shortcut                  Weight: 20.00% │
│   SELECT * FROM {table} WHERE id = ?                          │
│   [Edit] [Delete]                                             │
│                                                               │
│ Query 2: Range Scan Shortcut                   Weight: 20.00% │
│   SELECT * FROM {table} WHERE id BETWEEN ? AND ? + 100        │
│   [Edit] [Delete]                                             │
│                                                               │
│ Query 3: Regional Sales Rollup (GENERIC_SQL)    Weight: 35.00% │
│   SELECT r.region_name, SUM(f.amount)...                    │
│   [Edit] [Delete]                                           │
│                                                             │
│ Query 4: Top Products (GENERIC_SQL)             Weight: 24.99% │
│   SELECT p.name, RANK() OVER (PARTITION BY...)...           │
│   [Edit] [Delete]                                           │
│                                                             │
│ Query 5: Corrective Update Shortcut             Weight: 0.01% │
│   UPDATE {table} SET ... WHERE id = ?                         │
│   [Edit] [Delete]                                             │
│                                                               │
│ Query 6: Cardinality Check (GENERIC_SQL)        Weight: 0.00% │
│   SELECT APPROX_COUNT_DISTINCT(customer_id)...              │
│   [Edit] [Delete]                                           │
│                                                             │
│ [+ Add Another Query]                                       │
│                                                             │
│ Total weight: 100.00% ✓                                    │
└─────────────────────────────────────────────────────────────┘
```

## Validation Rules

Before allowing "Prepare":

| Check | Error if fails |
|-------|----------------|
| SQL syntax valid | "SQL syntax error: {details}" |
| All placeholders mapped | "Parameter ?3 not configured" |
| Referenced columns exist | "Column 'foo' not found in table 'bar'" |
| Weights sum to 100.00% | "Query weights must sum to 100.00%" |
| At least one query defined | "Add at least one analytical query" |
| GENERIC_SQL has placeholders but no parameters | "GENERIC_SQL queries with placeholders require explicit parameter mappings" |

Weight precision rules:
- UI accepts 2 decimal places (`step=0.01`)
- Each weight must be in `[0.00, 100.00]`
- Total must equal `100.00` after normalization/rounding safeguards

## Data Model

```python
@dataclass
class AnalyticalQuery:
    """A single analytical query configuration."""
    id: str
    name: str                      # User-friendly name
    query_kind: str                # POINT_LOOKUP, RANGE_SCAN, INSERT, UPDATE, GENERIC_SQL
    operation_type: str            # READ or WRITE (required for GENERIC_SQL)
    label: str | None              # Optional UI grouping label (e.g., "windowed", "rollup")
    sql: str                       # SQL with ? placeholders
    weight_pct: float              # Execution weight (0.00-100.00, 2 decimal precision)
    parameters: list[ParameterConfig]

@dataclass
class ParameterConfig:
    """Configuration for a single ? placeholder."""
    position: int                  # ?1, ?2, etc.
    name: str                      # User-friendly name
    param_type: str                # choice, date, categorical, numeric
    strategy: str                  # random_in_range, sample_from_table, etc.
    
    # For table-derived values
    table: str | None
    column: str | None
    
    # For choice type
    values: list[Any] | None
    
    # For dependent params
    depends_on: int | None         # Position of param this depends on
    offsets: list[int] | None      # Offset values
    
    # For list params (IN clause)
    count: int | None              # Fixed count matching SQL placeholder count
```

## Storage

Analytical queries stored in template config:

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
      "sql": "SELECT r.region_name, DATE_TRUNC(?, f.order_date)...",
      "parameters": [
        {
          "position": 1,
          "name": "granularity",
          "param_type": "choice",
          "strategy": "choice",
          "values": ["day", "week", "month", "quarter"]
        },
        {
          "position": 2,
          "name": "start_date",
          "param_type": "date",
          "strategy": "random_in_range",
          "table": "sales_fact",
          "column": "order_date"
        }
      ]
    }
  ],
  "column_profiles": {
    "sales_fact.order_date": {
      "min_value": "2020-01-01",
      "max_value": "2024-12-31"
    },
    "dim_product.category": {
      "sample_values": ["Electronics", "Clothing", "Home", "Sports", "Books"]
    }
  }
}
```
