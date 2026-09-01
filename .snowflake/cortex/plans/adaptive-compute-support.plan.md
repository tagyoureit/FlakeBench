# Plan: Adaptive Compute Support

## Overview

Adaptive Warehouses differ from standard warehouses in three fundamental ways that FlakeBench must handle:
1. **No size/MCW/QAS properties** — replaced by `MAX_QUERY_PERFORMANCE_LEVEL` + `QUERY_THROUGHPUT_MULTIPLIER`
2. **Query-based billing** — credits come from `QUERY_METERING_HISTORY`, not size×duration estimation
3. **State model** — ENABLED/DISABLED instead of STARTED/SUSPENDED

Changes span 9 areas in dependency order.

---

## Task 1 — Discover adaptive SHOW WAREHOUSES column positions

**Files:** none (investigation only)

Run `SHOW WAREHOUSES` against an account with at least one adaptive warehouse and inspect the result set column metadata to find the exact 0-based indices for:
- `MAX_QUERY_PERFORMANCE_LEVEL`
- `QUERY_THROUGHPUT_MULTIPLIER`
- `DISABLED_REASONS`

From the Snowflake docs, these are new columns added to `SHOW WAREHOUSES`. They're likely appended at the end (indices 34+), but must be verified empirically before the parsing code is written.

**Option A (preferred):** Run `SHOW WAREHOUSES` via the Snowflake UI or `cortex sql` in a region where adaptive warehouses are available (AWS US West 2 qualifies) and inspect the column list.

**Option B (fallback):** Switch `warehouses.py` to use named column lookup from cursor description (`cursor.description`) instead of hardcoded integer indices — eliminates fragility for all future schema additions.

---

## Task 2 — Update warehouse API SHOW WAREHOUSES parsing

**Files:** `backend/api/routes/warehouses.py`

### Changes

Both `list_warehouses()` and `get_warehouse_details()` parse `SHOW WAREHOUSES` rows by column index. Extend both to:

1. **Detect adaptive type:** `is_adaptive = (row[2] == 'ADAPTIVE')`

2. **Add adaptive fields** with safe length guards:
```python
"is_adaptive": row[2] == 'ADAPTIVE',
"max_query_performance_level": row[IDX_MXPL] if is_adaptive and len(row) > IDX_MXPL else None,
"query_throughput_multiplier": row[IDX_QTM] if is_adaptive and len(row) > IDX_QTM else None,
"disabled_reasons": row[IDX_DR] if is_adaptive and len(row) > IDX_DR else None,
```

3. **Null out inapplicable fields for adaptive:**
```python
"size": row[3] if not is_adaptive else None,
"min_cluster_count": (row[4] if row[4] else 1) if not is_adaptive else None,
"max_cluster_count": (row[5] if row[5] else 1) if not is_adaptive else None,
"scaling_policy": (row[31] if ...) if not is_adaptive else None,
"enable_query_acceleration": ... if not is_adaptive else None,
"resource_constraint": row[33] if not is_adaptive else None,
```

4. **State field:** For adaptive, `state` (col 1) returns `ENABLED`/`DISABLED`. This is already read at col 1 — no change needed to the field key, just note the different vocabulary.

**Note:** `IDX_MXPL`, `IDX_QTM`, `IDX_DR` are filled in after Task 1 determines the real column positions.

---

## Task 3 — Pydantic model and cost calculator

**Files:**
- `backend/models/test_config.py` — `WarehouseConfig`
- `backend/core/cost_calculator.py`
- `backend/static/js/cost-utils.js`

### `test_config.py` changes

```python
class WarehouseConfig(BaseModel):
    name: str
    size: Optional[WarehouseSize] = Field(None, ...)  # None for adaptive
    
    # Adaptive-only fields
    max_query_performance_level: Optional[str] = Field(None, ...)
    query_throughput_multiplier: Optional[int] = Field(None, ...)

    @model_validator(mode="after")
    def validate_warehouse_type(self):
        is_adaptive = (self.size is None or 
                       str(self.size).upper() == 'ADAPTIVE')
        if not is_adaptive and self.size is None:
            raise ValueError("size required for non-adaptive warehouses")
        # MCW validator only for standard
        if not is_adaptive and self.max_cluster_count < self.min_cluster_count:
            raise ValueError("max_cluster_count must be >= min_cluster_count")
        return self
```

### `cost_calculator.py` changes

Add 'ADAPTIVE' to the lookup table as a sentinel:
```python
WAREHOUSE_CREDITS_PER_HOUR["ADAPTIVE"] = 0.0  # actual credits from QUERY_METERING_HISTORY

def is_adaptive_warehouse(size: Optional[str]) -> bool:
    return size is not None and size.upper() == 'ADAPTIVE'
```

Update `calculate_credits()` (and the equivalent in `cost-utils.js`) to return `None` (not `0`) when `is_adaptive=True`, so callers know "no estimate available, use actual data."

---

## Task 4 — Configure UI for adaptive warehouse display

**File:** `backend/templates/pages/configure.html`

### `formatWarehouseOption()` (~line 2202)

Current: `Gen1/Gen2 | Size | MCW? | QAS?`

New logic:
```js
if (wh.is_adaptive) {
    const mxpl = wh.max_query_performance_level || 'XLarge';
    const qtm = wh.query_throughput_multiplier ?? 2;
    return `${wh.name} (Adaptive, MXPL: ${mxpl}, QTM: ${qtm})`;
}
// existing standard path unchanged
```

### Warehouse detail panel (~line 474)

Add an `x-show="selectedWarehouseDetails?.is_adaptive"` block:
```html
<template x-if="selectedWarehouseDetails?.is_adaptive">
  <div>
    <strong>Type:</strong> Adaptive Compute<br>
    <strong>State:</strong> <span x-text="selectedWarehouseDetails?.state"></span><br>
    <strong>Max Performance Level:</strong> 
      <span x-text="selectedWarehouseDetails?.max_query_performance_level || 'XLarge'"></span><br>
    <strong>Throughput Multiplier:</strong> 
      <span x-text="selectedWarehouseDetails?.query_throughput_multiplier ?? 2"></span><br>
    <em>Size, MCW, and QAS are auto-managed by Adaptive Compute.</em>
  </div>
</template>
<template x-if="!selectedWarehouseDetails?.is_adaptive">
  <!-- existing Gen/MCW/QAS display -->
</template>
```

### Warehouse config population (~lines 2998-3001)

```js
if (wh.is_adaptive) {
    this.config.warehouse_size = 'ADAPTIVE';
    this.config.multi_cluster = false;
    this.config.min_clusters = null;
    this.config.max_clusters = null;
} else {
    this.config.warehouse_size = sizeMap[this.selectedWarehouseDetails.size] || ...;
    this.config.multi_cluster = this.selectedWarehouseDetails.max_cluster_count > 1;
    ...
}
```

---

## Task 5 — SQL schema updates

**File:** `sql/schema/results_tables.sql`

### `TEST_RESULTS` additions (add after `warehouse_size`)
```sql
warehouse_type          VARCHAR(50),    -- 'ADAPTIVE', 'STANDARD', 'INTERACTIVE', etc.
max_query_performance_level VARCHAR(50),-- e.g. 'XLARGE', 'XXLARGE'
query_throughput_multiplier INTEGER,    -- e.g. 2, 6, 10
```

### `WAREHOUSE_POLL_SNAPSHOTS` additions
```sql
warehouse_state         VARCHAR(20),    -- ENABLED/DISABLED (adaptive) or STARTED/SUSPENDED (standard)
max_query_performance_level VARCHAR(50),
query_throughput_multiplier INTEGER,
```

Both tables use `CREATE OR ALTER`, so these are non-breaking additions.

Also update `backend/core/results_store.py` INSERT statements to populate `warehouse_type`, `max_query_performance_level`, and `query_throughput_multiplier` from the warehouse config passed at test start.

---

## Task 6 — Dashboard SQL objects: adaptive cost handling

**File:** `sql/schema/dashboard_tables.sql`

The credit estimation `CASE` block appears in four objects (`DT_TABLE_TYPE_SUMMARY`, `DT_TEMPLATE_STATISTICS`, `DT_DAILY_COST_ROLLUP`, `V_TEMPLATE_RUNS`). In all four, the innermost `CASE UPPER(COALESCE(WAREHOUSE_SIZE, 'MEDIUM'))` needs one new branch added before the `ELSE`:

```sql
WHEN 'ADAPTIVE' THEN NULL  -- no size-based estimate; use actual WAREHOUSE_CREDITS_USED
```

With `NULL` returned, the outer `COALESCE(WAREHOUSE_CREDITS_USED, <estimate>)` reduces to just `WAREHOUSE_CREDITS_USED` — which is what we want: if enrichment has run, we get the real number; if not, the field is NULL and the UI shows a "pending" indicator rather than a wrong estimate.

---

## Task 7 — Post-run QUERY_METERING_HISTORY enrichment

**File:** `backend/core/results_store.py`

For adaptive warehouses, the existing `WAREHOUSE_CREDITS_USED` is NULL after test completion (no size-based estimate). Add a new enrichment function alongside the existing `QUERY_HISTORY` enrichment:

```python
async def enrich_adaptive_credits(test_id: str, warehouse_name: str, 
                                   start_time: datetime, end_time: datetime):
    """Query QUERY_METERING_HISTORY for actual per-query credits."""
    sql = """
    SELECT SUM(credits_used_compute) AS total_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_METERING_HISTORY
    WHERE warehouse_name = ?
      AND start_time >= ?
      AND end_time <= ?
    """
    result = await pool.execute_query(sql, [warehouse_name, start_time, end_time])
    total_credits = result[0][0] if result and result[0][0] else None
    
    if total_credits is not None:
        await pool.execute_query(
            "UPDATE TEST_RESULTS SET WAREHOUSE_CREDITS_USED = ? WHERE TEST_ID = ?",
            [total_credits, test_id]
        )
```

**Integration:** Plug this into the existing delayed-enrichment scheduler. The 1-hour latency of `QUERY_METERING_HISTORY` means the enrichment should run after the standard `QUERY_HISTORY` enrichment delay already in place (or at the same delay checkpoint). The `ENRICHMENT_STATUS` column already tracks pending/complete states — extend to cover the new credit enrichment pass.

---

## Task 8 — History page and live dashboard display

**Files:**
- `backend/templates/pages/dashboard_history.html`
- `backend/websocket/queries.py`
- `backend/websocket/metrics.py`

### History page

The "warehouse metrics" section (~lines 648-751) currently shows cluster count, queued time, and queuing rate. When `warehouse_size == 'ADAPTIVE'`:
- Hide "Clusters used" row (replace with "Adaptive: no cluster management")
- Show `max_query_performance_level` and `query_throughput_multiplier` as configuration metadata
- Keep `sf_queued_overload_ms` and `sf_queued_provisioning_ms` — these still apply to adaptive warehouses
- Show "Credits used" from `WAREHOUSE_CREDITS_USED` (actual, from QUERY_METERING_HISTORY enrichment) with a "pending enrichment" placeholder if NULL

### WebSocket poll loop

In the controller poll that reads `SHOW WAREHOUSES` and writes `WAREHOUSE_POLL_SNAPSHOTS`, add:
- Write `max_query_performance_level` and `query_throughput_multiplier` when adaptive
- Write `warehouse_state` (the ENABLED/DISABLED value) instead of relying on the old STARTED/SUSPENDED interpretation
- Guard against NULL `started_clusters` without crashing the loop

---

## Task 9 — Semantic view and chart procedures

**Files:**
- `sql/schema/semantic_view.sql`
- `sql/schema/chart_procedures.sql`

### `semantic_view.sql`

Add computed dimension:
```sql
- name: is_adaptive
  expr: "CASE WHEN UPPER(WAREHOUSE_SIZE) = 'ADAPTIVE' THEN TRUE ELSE FALSE END"
  data_type: BOOLEAN
  description: "Whether the test ran on an Adaptive Compute warehouse"

- name: max_query_performance_level
  expr: MAX_QUERY_PERFORMANCE_LEVEL
  data_type: TEXT
  description: "Upper bound on per-query performance (Adaptive warehouses only)"
```

Filter note: size-based dimensions and the `credits_per_1k_ops` metric should be conditionally excluded when `is_adaptive = TRUE` in any verified queries, since the estimate is meaningless.

### `chart_procedures.sql`

`GET_TEST_SUMMARY`: add `max_query_performance_level`, `query_throughput_multiplier` to the returned JSON.

`GET_WAREHOUSE_TIMESERIES`: when `warehouse_size = 'ADAPTIVE'`, set MCW cluster count fields to `NULL` in output so callers don't render spurious cluster lines on charts.

---

## Dependency Order

```
Task 1 (discover columns)
  └─ Task 2 (API parsing)
       └─ Task 3 (model + cost calc)     Task 5 (schema DDL)
            └─ Task 4 (configure UI)          └─ Task 6 (dashboard SQL)
                                               └─ Task 7 (QUERY_METERING enrichment)
                                               └─ Task 8 (history + live dashboard)
                                               └─ Task 9 (semantic view)
```

Tasks 5-9 are independent of Tasks 1-4 and can proceed in parallel once the schema column names are confirmed in Task 1.

---

## What is NOT changing

- `QUERY_HISTORY` enrichment (`sf_queued_overload_ms`, `sf_execution_ms`, etc.) — works unchanged for adaptive; `warehouse_size = 'ADAPTIVE'` appears in the rows and the existing tag-based filtering is unaffected
- `INFORMATION_SCHEMA.QUERY_HISTORY_BY_WAREHOUSE` polling during live runs — still valid
- Table types (`STANDARD`, `HYBRID`, `INTERACTIVE`, `DYNAMIC`, `POSTGRES`) — unrelated to warehouse type
- Test execution engine — the benchmark harness itself doesn't care what type of warehouse runs the queries
