# Implementation Steps

Phased approach to adding analytical workload support with UI-based configuration.

> **Decision update (2026-02-16):** Keep existing OLTP shortcuts (`POINT_LOOKUP`,
> `RANGE_SCAN`, `INSERT`, `UPDATE`) and add `GENERIC_SQL` for arbitrary SQL with
> explicit `operation_type` (`READ`/`WRITE`). Treat `ROLLUP/CUBE` as SQL patterns
> inside `GENERIC_SQL`, not standalone runtime kinds. Use 2-decimal `weight_pct`
> precision with total mix equal to `100.00`.

## Implementation Status

**Updated: 2026-02-16** — All implementation phases complete.

| Phase | Component | Status | Location |
|-------|-----------|--------|----------|
| 1.1b | GENERIC_SQL Auto-Profiler | ✅ DONE | `templates.py:2526-2714` — parses SQL, extracts placeholder columns, samples into `TEMPLATE_VALUE_POOLS` with `POOL_KIND='GENERIC_SQL'` |
| 1.2 | Parameter Generator | ✅ DONE | `test_executor.py:3585-3789` (`_generate_generic_params()`) — all 7 strategies: literal, choice, random_numeric, sample_from_table, weighted_sample, random_in_range, offset_from_previous |
| 3 (partial) | UI Components | ✅ DONE | `configure.html` — Generic SQL entries section with label, operation type, weight, SQL editor |
| 4.1 | Query Kind Constants | ✅ DONE | `constants.py` — `ALLOWED_QUERY_KINDS = ("POINT_LOOKUP", "RANGE_SCAN", "INSERT", "UPDATE", "GENERIC_SQL")` |
| 4.3 | Per-Worker Generators | ✅ DONE | Parameter generation per-execution with shared value pools |
| 4.4 | Execute Custom | ✅ DONE | `test_executor.py:3791-3800` — `_execute_custom()` handles GENERIC_SQL |
| 4.4b | Weight Precision | ✅ DONE | `config_normalizer.py` — 2-decimal precision, 100.00 sum enforcement |
| 4.5 | SLO Definitions | ✅ DONE | `test_executor.py:2296-2307` — `fmc_slo_by_kind` includes GENERIC_SQL |
| 4.6 | Load Mode Compatibility | ✅ DONE | Unified executor handles OLTP+OLAP mixed in all 3 modes |
| 5 (partial) | Metrics Surfacing | ✅ DONE | GENERIC_SQL latency breakdown in schema, API, frontend |
| 2.1 | Catalog Objects Endpoint | ✅ DONE | `catalog.py` — `/databases`, `/schemas`, `/objects` endpoints |
| 2.2 | Catalog Columns Endpoint | ✅ DONE | `catalog.py` — `/columns` endpoint for Snowflake + Postgres |
| 2.3 | AI SQL Generation | ✅ DONE | `templates.py` — `/ai/generate-sql` (Cortex AI_COMPLETE) + `/ai/validate-sql` (EXPLAIN); models in `templates_modules/models.py` |
| 5 | Correctness Gate | ✅ DONE | `test_executor.py` — `_validate_generic_sql_preflight()`: EXPLAIN validation, DDL blocking, READ/WRITE op-type enforcement |
| 6.1 | Throughput Metrics Schema | ✅ DONE | `results_tables.sql` + `test_result.py` + `results_store.py` — `generic_sql_rows_per_sec`, `bytes_scanned_per_sec`, `olap_total_*`, `olap_metrics VARIANT` |
| 6.2 | Query-Profile Capture | ✅ DONE | `results_tables.sql` + `results_store.py` — `sf_partitions_scanned/total`, `sf_bytes_spilled_local/remote` in QUERY_EXECUTIONS enrichment MERGE |
| 6.3-6.5 | Comparison Updates | ✅ DONE | `comparison.py` + `comparison_prompts.py` — per-kind P95 in fetch, deltas, verdict, rolling stats, AI prompts |
| 7 | Methodology Metadata | ✅ DONE | `results_tables.sql` + `test_result.py` + `results_store.py` — `run_temperature`, `trial_index`, `realism_profile` columns |

---

## Phase 0: Contract Alignment (No Behavior Changes)

**Goal:** Codify inherited controls and remove ambiguity before implementation.

### Step 0.1: Document Inherited Benchmark Controls

- Explicitly declare inherited cache/warmup/trial controls in OLAP docs.
- Persist methodology metadata in result payloads for auditability.
- Do not alter existing runner behavior in this phase.

### Step 0.2: Lock Explicit OLAP Parameter Contract

- `GENERIC_SQL` entries require explicit parameter mappings when placeholders exist.
- Save/prepare validation fails if `GENERIC_SQL` placeholders are unmapped.
- Legacy inferred parameter generation remains OLTP-shortcut-only (`POINT/RANGE/INSERT/UPDATE`).
- `ROLLUP/CUBE` and similar constructs are SQL patterns, not runtime kinds.

### Step 0.3: Add Realism Contract Fields (Optional)

- Add optional `realism` profile block to template config.
- Default to `BASELINE` when omitted for full backward compatibility.

## Phase 1: Backend Foundation

**Goal:** Build core parameter generation and column profiling.

### Step 1.1: Column Profiler

**File:** `backend/core/column_profiler.py` (new)

```python
@dataclass
class ColumnProfile:
    table: str
    column: str
    data_type: str
    min_value: Any | None = None
    max_value: Any | None = None
    distinct_count: int = 0
    sample_values: list[Any] = field(default_factory=list)
    value_weights: dict[Any, float] = field(default_factory=dict)

async def profile_column(conn, table: str, column: str) -> ColumnProfile:
    """Profile a single column from a table."""
    ...

async def profile_columns(
    conn, 
    refs: list[tuple[str, str]]
) -> dict[str, ColumnProfile]:
    """Profile multiple columns, potentially from different tables."""
    ...
```

### Step 1.1b: GENERIC_SQL Auto-Profiler ✅ IMPLEMENTED

**File:** `backend/api/routes/templates.py` (extend `prepare_ai_template()`)

> **Status (2026-02-16):** Fully implemented at `templates.py:2526-2714`. The actual
> implementation parses SQL, extracts placeholder columns, samples values into
> `TEMPLATE_VALUE_POOLS` with `POOL_KIND='GENERIC_SQL'`, and auto-generates parameter
> configs. The code below is the original design spec — see source for actual implementation.

This step parses GENERIC_SQL queries to identify placeholder columns and auto-generates
parameter configurations.

```python
import re
import sqlparse

def extract_placeholder_columns(sql: str, table_fqn: str) -> list[dict]:
    """
    Parse SQL to identify columns associated with ? placeholders.
    
    Handles patterns like:
    - WHERE col = ?
    - WHERE col BETWEEN ? AND ?  
    - JOIN ... ON t.col = ?
    - AND col IN (?, ?, ?)
    
    Returns list of column info: [{"column": "O_CUSTKEY", "position": 0}, ...]
    """
    columns = []
    placeholder_idx = 0
    
    # Pattern: column_name followed by operator and ?
    # e.g., "o_custkey = ?", "amount > ?", "date BETWEEN ? AND ?"
    pattern = r'(\w+)\s*(=|>|<|>=|<=|BETWEEN|IN|LIKE)\s*(\?|\([\s\?,]+\))'
    
    for match in re.finditer(pattern, sql, re.IGNORECASE):
        col_name = match.group(1).upper()
        operator = match.group(2).upper()
        placeholder_part = match.group(3)
        
        # Count placeholders in this match
        num_placeholders = placeholder_part.count('?')
        
        for i in range(num_placeholders):
            columns.append({
                "column": col_name,
                "position": placeholder_idx,
                "operator": operator
            })
            placeholder_idx += 1
    
    return columns


async def auto_profile_generic_sql_params(
    conn,
    template_id: str,
    generic_queries: list[dict],
    table_fqn: str,
    sample_count: int = 5000
) -> list[dict]:
    """
    For each GENERIC_SQL query with placeholders:
    1. Parse SQL to identify placeholder columns
    2. Sample values from those columns into TEMPLATE_VALUE_POOLS
    3. Generate parameter configs with sample_from_table strategy
    
    Returns updated generic_queries with auto-populated parameters.
    """
    for query in generic_queries:
        sql = query.get("sql", "")
        if not sql or "?" not in sql:
            continue
            
        # Already has explicit parameters - skip
        if query.get("parameters"):
            continue
            
        # Extract columns from placeholders
        placeholder_cols = extract_placeholder_columns(sql, table_fqn)
        if not placeholder_cols:
            continue
        
        # Sample each unique column and create value pool
        sampled_columns = set()
        parameters = []
        
        for pc in placeholder_cols:
            col_name = pc["column"]
            
            # Sample column values if not already done
            if col_name not in sampled_columns:
                pool_id = f"{template_id}:GENERIC_SQL:{col_name}"
                
                # Sample distinct values from column
                sample_sql = f"""
                    SELECT DISTINCT {col_name} 
                    FROM {table_fqn} 
                    WHERE {col_name} IS NOT NULL 
                    ORDER BY RANDOM()
                    LIMIT {sample_count}
                """
                values = [row[0] for row in await conn.execute(sample_sql)]
                
                # Store in TEMPLATE_VALUE_POOLS
                await _store_generic_sql_pool(
                    conn, template_id, col_name, values
                )
                sampled_columns.add(col_name)
            
            # Build parameter config
            parameters.append({
                "position": pc["position"],
                "name": col_name.lower(),
                "strategy": "sample_from_table",
                "column": col_name,
                "pool_id": f"{template_id}:GENERIC_SQL:{col_name}"
            })
        
        # Update query with auto-generated parameters
        query["parameters"] = parameters
    
    return generic_queries


async def _store_generic_sql_pool(
    conn, 
    template_id: str, 
    column_name: str,
    values: list
) -> None:
    """Store sampled values in TEMPLATE_VALUE_POOLS with GENERIC_SQL pool kind."""
    
    # Delete existing pool for this column
    await conn.execute(f"""
        DELETE FROM {{prefix}}.TEMPLATE_VALUE_POOLS
        WHERE TEMPLATE_ID = ? AND POOL_KIND = 'GENERIC_SQL' AND COLUMN_NAME = ?
    """, params=[template_id, column_name])
    
    # Insert new values
    for seq, value in enumerate(values):
        await conn.execute(f"""
            INSERT INTO {{prefix}}.TEMPLATE_VALUE_POOLS 
            (POOL_ID, TEMPLATE_ID, POOL_KIND, COLUMN_NAME, SEQ, VALUE)
            VALUES (?, ?, 'GENERIC_SQL', ?, ?, TO_VARIANT(?))
        """, params=[
            f"{template_id}:GENERIC_SQL:{column_name}",
            template_id,
            column_name,
            seq,
            value
        ])
```

**Integration point:** Call `auto_profile_generic_sql_params()` from `prepare_ai_template()`
after creating KEY/RANGE pools, before saving the template config.

---

### Step 1.2: Parameter Generator ✅ IMPLEMENTED

**File:** `backend/core/param_generator.py` (new)

> **Status (2026-02-16):** Fully implemented inline in `test_executor.py:3585-3789`
> (`_generate_generic_params()`). Supports all 7 strategies: literal, choice,
> random_numeric, sample_from_table, weighted_sample, random_in_range, offset_from_previous.
> Not a separate file — embedded in the executor for direct access to value pools.

```python
class ParameterGenerator:
    """
    Generates parameter values for analytical queries.
    
    Each worker gets its own generator instance with a unique seed.
    All workers share the same column profiles (read-only).
    Cache is disabled at template level, so overlap is acceptable.
    """
    
    def __init__(self, profiles: dict[str, ColumnProfile], worker_id: int):
        self._profiles = profiles  # Shared, read-only
        self._rng = random.Random(seed=worker_id)  # Unique per worker
    
    def generate(self, configs: list[ParameterConfig]) -> list[Any]:
        """Generate parameter values for a single query execution."""
        values = []
        context = {}  # For dependent params
        
        for config in configs:
            value = self._generate_one(config, context)
            values.append(value)
            context[config.position] = value
        
        return values
    
    def _generate_choice(self, config) -> Any:
        return self._rng.choice(config.values)
    
    def _generate_random_in_range(self, config) -> Any:
        profile = self._profiles[f"{config.table}.{config.column}"]
        if isinstance(profile.min_value, date):
            days = (profile.max_value - profile.min_value).days
            return profile.min_value + timedelta(days=self._rng.randint(0, days))
        else:
            return self._rng.uniform(profile.min_value, profile.max_value)
    
    def _generate_sample_from_table(self, config) -> Any:
        profile = self._profiles[f"{config.table}.{config.column}"]
        return self._rng.choice(profile.sample_values)
    
    def _generate_weighted_sample(self, config) -> Any:
        profile = self._profiles[f"{config.table}.{config.column}"]
        values = list(profile.value_weights.keys())
        weights = list(profile.value_weights.values())
        return self._rng.choices(values, weights=weights, k=1)[0]
    
    def _generate_offset_from_previous(self, config, context) -> Any:
        base = context[config.depends_on]
        offset = self._rng.choice(config.offsets)
        if isinstance(base, date):
            return base + timedelta(days=offset)
        return base + offset
    
    def _generate_sample_list(self, config) -> list[Any]:
        profile = self._profiles[f"{config.table}.{config.column}"]
        count = config.count  # Fixed count matching SQL placeholder count
        return self._rng.sample(profile.sample_values, min(count, len(profile.sample_values)))
```

### Step 1.3: Data Models

**File:** `backend/models/analytical_query.py` (new)

```python
@dataclass
class ParameterConfig:
    position: int
    name: str
    param_type: str        # choice, date, categorical, numeric
    strategy: str          # random_in_range, sample_from_table, etc.
    table: str | None = None
    column: str | None = None
    values: list[Any] | None = None
    depends_on: int | None = None
    offsets: list[int] | None = None
    count: int | None = None              # Fixed count matching SQL placeholder count

@dataclass
class AnalyticalQuery:
    id: str
    name: str
    query_kind: str
    sql: str
    weight_pct: int
    parameters: list[ParameterConfig]
```

### Step 1.4: Storage Table

**File:** `backend/sql/schema/template_column_profiles.sql` (new)

```sql
CREATE TABLE IF NOT EXISTS TEMPLATE_COLUMN_PROFILES (
    TEMPLATE_ID VARCHAR NOT NULL,
    TABLE_NAME VARCHAR NOT NULL,
    COLUMN_NAME VARCHAR NOT NULL,
    DATA_TYPE VARCHAR,
    MIN_VALUE VARIANT,
    MAX_VALUE VARIANT,
    DISTINCT_COUNT NUMBER,
    SAMPLE_VALUES VARIANT,
    VALUE_WEIGHTS VARIANT,
    PROFILED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    PRIMARY KEY (TEMPLATE_ID, TABLE_NAME, COLUMN_NAME)
);
```

### Step 1.5: Unit Tests

**File:** `tests/unit/test_param_generator.py`

- Test each generation strategy
- Test dependent parameters
- Test edge cases

---

## Phase 2: API Endpoints

**Goal:** Expose backend functionality via REST API.

### Step 2.1: Catalog Objects Endpoint (Reuse Existing Surface)

**File:** `backend/api/routes/catalog.py`

```python
# Full endpoint: /api/catalog/objects
@router.get("/objects")
async def list_objects(database: str, schema: str, filter_type: str = "TABLE"):
    """List selectable objects for analytical queries."""
    ...
```

### Step 2.2: Catalog Columns Endpoint (No Alias Routes)

```python
# Full endpoint: /api/catalog/columns
@router.get("/columns")
async def get_table_columns(database: str, schema: str, table: str):
    """Get columns, types, and sample values for a table."""
    ...
```

### Step 2.3: AI SQL Generation Endpoint

```python
# Full endpoint: /api/templates/ai/generate-sql
@router.post("/ai/generate-sql")
async def generate_sql(
    tables: list[str],
    intent: str,
    query_type: str  # Aggregation, Windowed, Cardinality (UI hint only)
):
    """Generate SQL from natural language intent."""
    # Get schemas for selected tables
    # Build AI prompt with schema context
    # Call AI, return generated SQL
    ...
```

### Step 2.4: SQL Validation Endpoint

```python
# Full endpoint: /api/templates/ai/validate-sql
@router.post("/ai/validate-sql")
async def validate_sql(sql: str):
    """Validate SQL syntax without executing."""
    # Use EXPLAIN or dry-run
    ...
```

### Step 2.5: Column Profiling Endpoint

```python
# Full endpoint: /api/templates/{template_id}/ai/profile-columns
@router.post("/{template_id}/ai/profile-columns")
async def profile_columns(
    template_id: str,
    columns: list[dict]  # [{table, column}, ...]
):
    """Profile specified columns and store results."""
    ...
```

---

## Phase 3: UI Components

**Goal:** Build the analytical query builder interface.

### Step 3.1: Table Selector Component

**File:** `backend/templates/pages/configure.html`

```html
<!-- Multi-select for tables -->
<div x-data="tableSelector()">
    <label>Select tables for this query:</label>
    <div class="table-list">
        <template x-for="table in availableTables">
            <label>
                <input type="checkbox" 
                       :value="table.name"
                       x-model="selectedTables">
                <span x-text="table.name"></span>
                <span class="text-gray-500" x-text="'(' + table.row_count + ' rows)'"></span>
            </label>
        </template>
    </div>
</div>
```

### Step 3.2: Intent Input & SQL Generator

```html
<div x-data="sqlGenerator()">
    <label>Describe your analytical query:</label>
    <textarea x-model="intent" 
              placeholder="Analyze sales by region and time..."></textarea>
    
    <select x-model="queryType">
        <option value="AGGREGATION">Aggregation (GROUP BY)</option>
        <option value="WINDOWED">Windowed (OVER)</option>
        <option value="APPROX_DISTINCT">Cardinality (APPROX_COUNT_DISTINCT)</option>
    </select>
    
    <button @click="generateSql()">Generate SQL</button>
    
    <!-- Generated SQL display -->
    <div x-show="generatedSql">
        <pre x-text="generatedSql"></pre>
        <button @click="acceptSql()">Accept</button>
        <button @click="generateSql()">Regenerate</button>
        <button @click="editMode = true">Edit</button>
    </div>
</div>
```

### Step 3.3: Parameter Mapper Component

```html
<div x-data="parameterMapper()">
    <h3>Configure Parameters</h3>
    
    <template x-for="(param, idx) in placeholders">
        <div class="parameter-config">
            <h4>Parameter ?<span x-text="idx + 1"></span></h4>
            
            <label>Name:</label>
            <input x-model="param.name" placeholder="e.g., start_date">
            
            <label>Strategy:</label>
            <select x-model="param.strategy" @change="updateStrategyFields(idx)">
                <option value="choice">Choice (explicit list)</option>
                <option value="random_in_range">Random in range</option>
                <option value="sample_from_table">Sample from table</option>
                <option value="weighted_sample">Weighted sample</option>
                <option value="offset_from_previous">Offset from previous</option>
                <option value="sample_list">Sample list (for IN)</option>
            </select>
            
            <!-- Conditional fields based on strategy -->
            <template x-if="param.strategy === 'choice'">
                <div>
                    <label>Values:</label>
                    <input x-model="param.valuesText" 
                           placeholder="day, week, month, quarter">
                </div>
            </template>
            
            <template x-if="['random_in_range', 'sample_from_table', 'weighted_sample'].includes(param.strategy)">
                <div>
                    <label>Table:</label>
                    <select x-model="param.table">
                        <template x-for="t in selectedTables">
                            <option :value="t" x-text="t"></option>
                        </template>
                    </select>
                    
                    <label>Column:</label>
                    <select x-model="param.column">
                        <template x-for="col in getColumnsForTable(param.table)">
                            <option :value="col.name" x-text="col.name + ' (' + col.type + ')'"></option>
                        </template>
                    </select>
                </div>
            </template>
            
            <template x-if="param.strategy === 'offset_from_previous'">
                <div>
                    <label>Based on:</label>
                    <select x-model="param.depends_on">
                        <template x-for="(p, i) in placeholders.slice(0, idx)">
                            <option :value="i + 1" x-text="'?' + (i + 1) + ' ' + p.name"></option>
                        </template>
                    </select>
                    
                    <label>Offsets (days):</label>
                    <input x-model="param.offsetsText" placeholder="7, 30, 90, 365">
                </div>
            </template>
        </div>
    </template>
    
    <div class="variety-estimate">
        Estimated query variety: <strong x-text="calculateVariety()"></strong> combinations
    </div>
</div>
```

### Step 3.4: Query Manager Component

```html
<div x-data="queryManager()">
    <h2>Analytical Queries</h2>
    
    <template x-for="query in queries">
        <div class="query-card">
            <div class="query-header">
                <span x-text="query.name"></span>
                <span class="badge" x-text="query.query_kind"></span>
                <span>Type: <select x-model="query.operation_type"><option>READ</option><option>WRITE</option></select></span>
                <span>Weight: <input type="number" x-model.number="query.weight_pct" min="0" max="100" step="0.01">%</span>
            </div>
            <pre class="query-sql" x-text="query.sql"></pre>
            <div class="query-actions">
                <button @click="editQuery(query)">Edit</button>
                <button @click="deleteQuery(query)">Delete</button>
            </div>
        </div>
    </template>
    
    <button @click="addQuery()">+ Add Query</button>
    
    <div class="weight-total" :class="{'text-red-500': Math.abs(totalWeight - 100.0) > 0.0001}">
        Total weight: <span x-text="totalWeight"></span>%
        <span x-show="Math.abs(totalWeight - 100.0) > 0.0001">(must equal 100.00%)</span>
    </div>
</div>
```

### Step 3.5: Integration with Prepare Flow

Update existing "Prepare" button to also profile analytical query columns:

```javascript
async prepareTemplate() {
    // Existing OLTP pool preparation...
    
    // NEW: Profile columns for analytical queries
    if (this.config.analytical_queries?.length) {
        const columnsToProfile = this.extractColumnsFromQueries();
        await this.profileColumns(columnsToProfile);
    }
}
```

---

## Phase 4: Executor Integration

**Goal:** Execute analytical queries with generated parameters.

### Step 4.1: Add Query Kind Constants ✅ IMPLEMENTED

**File:** `backend/api/routes/templates_modules/constants.py`

> **Status (2026-02-16):** Implemented. `ALLOWED_QUERY_KINDS` includes GENERIC_SQL.

```python
ALLOWED_QUERY_KINDS = {
    "POINT_LOOKUP",
    "RANGE_SCAN",
    "INSERT",
    "UPDATE",
    "GENERIC_SQL",
}

# Generic SQL can represent aggregation/window/join/rollup/approx patterns.
# operation_type is required for GENERIC_SQL rows.
```

If older snippets in this document still show names such as `AGGREGATION` or
`WINDOWED`, interpret those as optional `GENERIC_SQL` labels rather than runtime
`query_kind` values.

### Step 4.2: Load Column Profiles (Once, Shared)

**File:** `backend/core/test_executor.py`

```python
async def _load_column_profiles(self) -> None:
    """
    Load column profiles for analytical queries.
    
    Called once at startup. Profiles are shared read-only across all workers.
    """
    if not self._analytical_queries:
        return
    
    rows = await pool.execute_query(
        """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, 
               MIN_VALUE, MAX_VALUE, DISTINCT_COUNT,
               SAMPLE_VALUES, VALUE_WEIGHTS
        FROM TEMPLATE_COLUMN_PROFILES
        WHERE TEMPLATE_ID = ?
        """,
        params=[self._template_id]
    )
    
    # Shared across all workers (read-only)
    self._column_profiles = {
        f"{r[0]}.{r[1]}": ColumnProfile(...) for r in rows
    }
```

### Step 4.3: Create Per-Worker Generators ✅ IMPLEMENTED

> **Status (2026-02-16):** Implemented — parameter generation happens per-execution with shared value pools.

```python
def _get_param_generator(self, worker_id: int) -> ParameterGenerator:
    """
    Get or create a parameter generator for this worker.
    
    Each worker has its own generator with a unique random seed.
    All generators share the same column profiles (read-only).
    """
    if not hasattr(self, '_param_generators'):
        self._param_generators = {}
    
    if worker_id not in self._param_generators:
        self._param_generators[worker_id] = ParameterGenerator(
            profiles=self._column_profiles,  # Shared, read-only
            worker_id=worker_id              # Unique seed
        )
    
    return self._param_generators[worker_id]
```

### Step 4.4: Modify Execute Custom ✅ IMPLEMENTED

> **Status (2026-02-16):** Implemented at `test_executor.py:3791-3800`.

```python
async def _execute_custom(self, worker_id: int, warmup: bool = False):
    query = self._select_query_by_weight()

    if query.query_kind == "GENERIC_SQL":
        operation_type = str(query.operation_type or "READ").upper()
        if operation_type not in {"READ", "WRITE"}:
            raise ValueError("GENERIC_SQL requires operation_type READ or WRITE")
        generator = self._get_param_generator(worker_id)
        params = generator.generate(query.parameters or [])
    else:
        # Legacy OLTP shortcut path
        params = self._get_oltp_params(query.query_kind, worker_id)
        operation_type = (
            "READ" if query.query_kind in {"POINT_LOOKUP", "RANGE_SCAN"} else "WRITE"
        )
    
    # Execute with generated params
    start = time.perf_counter()
    result = await conn.execute(query.sql, params)
    latency = time.perf_counter() - start
    
    # Track metrics by query kind
    self._record_latency(query.query_kind, latency)
```

### Step 4.4b: Weight Precision ✅ IMPLEMENTED

> **Status (2026-02-16):** Implemented in `config_normalizer.py`.

Use 2-decimal precision for query mix so very skewed workloads are possible:

```python
# Validate each query weight
if query.weight_pct < 0 or query.weight_pct > 100:
    raise ValueError("weight_pct must be between 0.00 and 100.00")

# Enforce 2 decimal places at save time
query.weight_pct = round(float(query.weight_pct), 2)

# Validate total
total = round(sum(float(q.weight_pct) for q in queries), 2)
if total != 100.00:
    raise ValueError(f"Query weights must sum to 100.00 (got {total:.2f})")
```

### Step 4.5: SLO Definitions for OLAP ✅ IMPLEMENTED

> **Status (2026-02-16):** Implemented at `test_executor.py:2296-2307` (`fmc_slo_by_kind`).

```python
SLOS_BY_KIND = {
    # Existing shortcuts
    "POINT_LOOKUP": {"p95_ms": 100, "p99_ms": 200},
    "RANGE_SCAN": {"p95_ms": 200, "p99_ms": 500},
    "INSERT": {"p95_ms": 150, "p99_ms": 300},
    "UPDATE": {"p95_ms": 150, "p99_ms": 300},
    # Generic SQL baseline
    "GENERIC_SQL": {"p95_ms": 5000, "p99_ms": 10000},
}

# Optional per-label overrides (for GENERIC_SQL labels only)
GENERIC_SQL_LABEL_SLOS = {
    "aggregation": {"p95_ms": 5000, "p99_ms": 10000},
    "windowed": {"p95_ms": 5000, "p99_ms": 10000},
    "analytical_join": {"p95_ms": 8000, "p99_ms": 15000},
    "wide_scan": {"p95_ms": 10000, "p99_ms": 20000},
    "approx_distinct": {"p95_ms": 3000, "p99_ms": 5000},
}
```

> **SLO Calibration Assumptions:**
> - These defaults assume XS/S warehouse sizes with ~1M row tables
> - For larger tables or smaller warehouses, users should adjust thresholds
> - SLOs are per-runtime-kind; optional `GENERIC_SQL` label overrides can provide finer control
> - Consider exposing SLO thresholds in UI for user customization
> - Future: auto-calibrate based on initial profiling run

> **Note:** Initial implementation uses latency-based SLOs only, matching the existing
> OLTP pattern. Throughput-based SLOs are a future enhancement (see `00-overview.md`).

### Step 4.6: Load Mode Compatibility ✅ IMPLEMENTED

> **Status (2026-02-16):** Unified executor handles OLTP+OLAP mixed workloads in all 3 modes.

OLAP queries work with all three existing load modes. The key principle is **unified execution**: workers pick from a combined pool of OLTP + OLAP queries based on configured weights.

#### CONCURRENCY Mode

Fixed N workers, each runs queries continuously in a loop.

```
Workers: [W0] [W1] [W2] [W3] ... [Wn]
           │    │    │    │
           ▼    ▼    ▼    ▼
      Select query by weight (could be OLTP or OLAP)
           │    │    │    │
           ▼    ▼    ▼    ▼
      Generate params (OLTP: value pool, OLAP: profile+seed)
           │    │    │    │
           ▼    ▼    ▼    ▼
      Execute → Record latency by query_kind → Loop
```

**No changes needed** - existing loop handles mixed query types naturally.

#### QPS Mode

Target X queries per second, dynamically scales workers.

```python
# Worker count adjusts to hit target QPS
# OLAP queries are slower, so more workers may be needed

# Example: Target 50 QPS with mix of OLTP (10ms avg) and OLAP (500ms avg)
# - If workload is 80% OLTP, 20% OLAP:
#   - Effective avg latency: 0.8 * 10 + 0.2 * 500 = 108ms
#   - Workers needed ≈ target_qps * avg_latency = 50 * 0.108 ≈ 6 workers
```

**Considerations:**
- QPS targets should account for OLAP query mix (slower = lower achievable QPS)
- The existing auto-scaler adjusts worker count based on actual throughput
- UI should warn when QPS target seems unrealistic for OLAP-heavy workloads

**File:** `backend/core/orchestrator.py`

```python
# Add QPS target validation for OLAP-heavy workloads
def validate_qps_target(config):
    olap_weight = sum(q.weight for q in config.analytical_queries)
    if olap_weight > 50 and config.target_qps > 100:
        warnings.append(
            f"Target QPS {config.target_qps} may be unrealistic with "
            f"{olap_weight}% OLAP queries. Consider lowering target."
        )
```

#### FIND_MAX_CONCURRENCY Mode

Progressively increases concurrency until SLOs are violated.

```
Step 1: 5 workers  → Check SLOs (per query kind) → Pass → Continue
Step 2: 15 workers → Check SLOs (per query kind) → Pass → Continue  
Step 3: 25 workers → Check SLOs (per query kind) → FAIL (GENERIC_SQL:aggregation p95 > 5000ms)
Result: Max sustainable concurrency = 15 workers
```

**Key changes:**
- SLO checks must evaluate **each query kind separately** (OLTP and OLAP have different thresholds)
- A single query kind violating its SLO stops the ramp-up
- Results report which query kind was the bottleneck

```python
def check_slos_by_kind(metrics: dict) -> tuple[bool, str | None]:
    """Check SLOs for each query kind. Returns (passed, bottleneck_kind)."""
    
    all_slos = {**SLOS_BY_KIND}
    
    for kind, thresholds in all_slos.items():
        p95_key = f"{kind.lower()}_p95_latency_ms"
        if p95_key in metrics:
            actual_p95 = metrics[p95_key]
            if actual_p95 > thresholds["p95_ms"]:
                return False, kind  # This kind is the bottleneck
    
    return True, None  # All SLOs passed
```

#### Mixed Workload Recommendations

| Scenario | Recommended Load Mode | Notes |
|----------|----------------------|-------|
| OLAP-only benchmark | CONCURRENCY | Simpler, predictable load |
| OLTP + OLAP mixed | CONCURRENCY or QPS | Use weights to control mix |
| Find Snowflake limits | FIND_MAX_CONCURRENCY | Reports bottleneck query kind |
| Sustained throughput test | QPS | Set realistic target for OLAP mix |

---

## Phase 5: Correctness Gate

**Goal:** Ensure templates are semantically valid before benchmarking.

### Step 5.1: Add Pre-Flight Correctness Checks

- Run a correctness gate during template prepare or test preflight.
- For non-approx queries: compare against a reference query path.
- For `APPROX_DISTINCT`: validate relative error against configured threshold.
- Block performance run when correctness gate fails.

### Step 5.2: Persist Correctness Metadata

- Add `correctness_gate_passed`, failure counts, and approx error percentiles.
- Include correctness details in `olap_metrics` payload for compare UI.

---

## Phase 6: History & Comparison

**Goal:** Store OLAP metrics and enable comparison between test runs.

### Step 6.1: Schema Changes

**File:** `sql/schema/results_tables.sql`

Use hybrid OLAP metrics persistence (stable core + extensible payload):

```sql
-- Stable per-kind SLO columns
aggregation_p95_latency_ms FLOAT,
aggregation_count INTEGER DEFAULT 0,
windowed_p95_latency_ms FLOAT,
windowed_count INTEGER DEFAULT 0,
analytical_join_p95_latency_ms FLOAT,
analytical_join_count INTEGER DEFAULT 0,
wide_scan_p95_latency_ms FLOAT,
wide_scan_count INTEGER DEFAULT 0,
approx_distinct_p95_latency_ms FLOAT,
approx_distinct_count INTEGER DEFAULT 0,

-- Aggregate OLAP metrics
olap_total_operations INTEGER DEFAULT 0,
olap_total_rows_processed BIGINT DEFAULT 0,
olap_total_bytes_scanned BIGINT DEFAULT 0,

-- Extensible per-kind metrics payload
olap_metrics VARIANT,
```

### Step 6.2: Results Store Updates

**File:** `backend/core/results_store.py`

Update INSERT/UPDATE queries to persist both OLAP core columns and `olap_metrics` payload:

```python
async def persist_test_results(test_id: str, metrics: dict):
    """Persist test results including OLAP metrics."""
    
    # Compute OLAP rollups
    olap_metrics = compute_olap_rollups(metrics)
    
    await pool.execute_query(
        f"""
        UPDATE {prefix}.TEST_RESULTS
        SET 
            -- Existing OLTP columns...
            
            -- OLAP core columns
            aggregation_p95_latency_ms = ?,
            aggregation_count = ?,
            windowed_p95_latency_ms = ?,
            windowed_count = ?,
            olap_total_operations = ?,
            olap_total_rows_processed = ?,
            olap_total_bytes_scanned = ?,

            -- OLAP extensible details
            olap_metrics = PARSE_JSON(?)
        WHERE TEST_ID = ?
        """,
        params=[...olap_metrics, test_id]
    )
```

### Step 6.3: Shallow Compare Updates

**File:** `backend/api/routes/test_results.py`

Include OLAP metrics in comparison endpoints:

```python
@router.get("/api/tests/compare")
async def compare_tests(ids: str):
    """Compare multiple tests including OLAP metrics."""
    
    # Fetch tests with OLAP columns
    query = f"""
        SELECT 
            -- Existing columns
            test_id, test_name, table_type, qps, p95_latency_ms,
            point_lookup_p95_latency_ms, range_scan_p95_latency_ms,
            
            -- OLAP core columns
            aggregation_p95_latency_ms,
            windowed_p95_latency_ms,
            analytical_join_p95_latency_ms,
            wide_scan_p95_latency_ms,
            approx_distinct_p95_latency_ms,
            olap_total_operations,
            olap_total_rows_processed,
            olap_total_bytes_scanned,
            olap_metrics
        FROM {prefix}.TEST_RESULTS
        WHERE TEST_ID IN ({placeholders})
    """
```

### Step 6.4: Deep Compare Updates

**File:** `backend/static/js/compare_detail.js`

Add OLAP query kinds to comparison charts:

```javascript
const OLAP_QUERY_KINDS = [
    "AGGREGATION", "WINDOWED", "ANALYTICAL_JOIN", 
    "WIDE_SCAN", "APPROX_DISTINCT"
];

// Extend latency comparison chart
function buildLatencyComparisonChart(testA, testB) {
    const allKinds = [...OLTP_QUERY_KINDS, ...OLAP_QUERY_KINDS];
    // ... build chart with all active kinds
}

// NEW: Throughput comparison chart
function buildThroughputComparisonChart(testA, testB) {
    // Compare rows/sec for OLAP kinds
}
```

### Step 6.5: History Page Updates

**Files:** 
- `backend/templates/pages/history.html`
- `backend/static/js/history.js`
- `backend/templates/pages/history_compare.html`

Add OLAP columns (conditionally shown):

```html
<template x-if="showOlapColumns">
    <th>Aggregation p95</th>
    <th>Windowed p95</th>
    <th>Rows/sec</th>
</template>
```

**OLAP column visibility logic:**

```javascript
// history.js - detect if test has OLAP data

const OLAP_QUERY_KINDS = [
    "AGGREGATION", "WINDOWED", "ANALYTICAL_JOIN",
    "WIDE_SCAN", "APPROX_DISTINCT"
];

function hasOlapData(test) {
    // Check if any OLAP query kind has non-zero count
    return OLAP_QUERY_KINDS.some(kind => {
        const countKey = `${kind.toLowerCase()}_count`;
        return test[countKey] && test[countKey] > 0;
    });
}

// In Alpine component
get showOlapColumns() {
    return this.tests.some(test => hasOlapData(test));
}
```

---

## Phase 7: Realism Rollout and Validation

### Step 7.1: Realism Profiles

- Implement optional realism profiles:
  - `BASELINE`
  - `REALISTIC`
  - `STRESS_SKEW`
  - `NULL_HEAVY`
  - `LATE_ARRIVAL`
  - `SELECTIVITY_SWEEP`

### Step 7.2: Realism Scenario Validation

- Validate skew scenarios (heavy-hitter dimensions)
- Validate NULL-heavy dimensions and filters
- Validate late-arrival event-time behavior
- Validate selective vs non-selective filter bands

### Step 7.3: End-to-End + Documentation

- Test full flow: tables → intent → SQL → params → execute
- Verify query variety (no repeated identical queries)
- Compare Snowflake vs Postgres results
- Verify history storage and comparison
- User guide for analytical query builder
- API documentation
- Methodology + realism guide (`09-methodology-and-realism.md`)

---

## Summary

| Phase | Description | Key Deliverables |
|-------|-------------|------------------|
| Phase 0 | Contract Alignment | Inherited controls, explicit OLAP parameter contract, realism fields |
| Phase 1 | Backend Foundation | ColumnProfiler, ParameterGenerator, data models |
| Phase 2 | API Endpoints | catalog objects/columns + templates AI actions |
| Phase 3 | UI Components | Table selector, intent input, parameter mapper |
| Phase 4 | Executor Integration | Load profiles, generate params, execute queries |
| Phase 5 | Correctness Gate | Pre-flight semantic checks + approx error tolerance |
| Phase 6 | History & Comparison | Hybrid metrics schema (core + VARIANT), compare updates |
| Phase 7 | Realism Rollout and Validation | Profile scenarios, e2e validation, docs |

## Testing Strategy

### Unit Tests

- [ ] Each parameter generation strategy
- [ ] Dependent parameter handling
- [ ] Column profiling for different data types

### Integration Tests

- [ ] AI SQL generation with schema context
- [ ] SQL validation
- [ ] Column profiling across multiple tables
- [ ] Full query execution with generated params

### End-to-End Tests

- [ ] Complete UI flow
- [ ] Verify query variety
- [ ] Performance comparison: Snowflake vs Postgres
- [ ] Correctness gate pass/fail behavior (exact + approximate)
- [ ] Realism profiles produce expected behavior signatures

## Backward Compatibility

- Existing OLTP templates work unchanged
- `analytical_queries` is a new optional config section
- Legacy inferred generation remains only for OLTP shortcut kinds
- `GENERIC_SQL` with placeholders requires explicit parameters.
                                             