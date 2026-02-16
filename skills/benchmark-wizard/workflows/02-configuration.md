# Phase 2: Configuration Generation

## Purpose

Transform gathered requirements into a valid test configuration JSON that can be submitted to the backend API.

## Step 0: Search for Existing Templates (MANDATORY)

**CRITICAL: Before creating ANY new template, the agent MUST search for existing matches and present them to the user.**

This step is NOT optional. Even if the user provides detailed requirements, existing templates may already exist that match their needs.

### Why This Matters
- Prevents duplicate templates cluttering the system
- Leverages proven, tested configurations  
- Shows historical results for reference
- Saves time when re-running similar tests

### Fetch Existing Templates

```bash
curl -sL "http://127.0.0.1:8000/api/templates/" | jq '.templates'
```

### REQUIRED: Score and Present Matches

After fetching templates, the agent MUST:
1. Score each template against the user's requirements
2. Filter to templates with score >= 50
3. Present matches to the user
4. Ask what they want to do BEFORE creating new templates

**DO NOT skip this step. DO NOT just fetch templates to "check if backend is running".**

### Match Scoring Algorithm

Score each existing template against the user's requirements:

| Field | Exact Match Points | Close Match Points | Notes |
|-------|-------------------|-------------------|-------|
| `table_name` | 30 | 0 | Must match for relevance |
| `table_type` | 20 | 0 | HYBRID vs POSTGRES vs STANDARD |
| `load_mode` | 20 | 0 | CONCURRENCY vs QPS vs FIND_MAX_CONCURRENCY |
| `start_concurrency` | 5 | 3 (within 20%) | Scaling config |
| `concurrency_increment` | 5 | 3 (within 20%) | Scaling config |
| `step_duration_seconds` | 5 | 3 (within 20%) | Scaling config |
| `workload_mix` | 10 | 5 (within 10% each) | Point/range/insert/update percentages |
| `duration_seconds` | 5 | 2 (any duration) | Often varies between runs |
| `warmup_seconds` | 0 | 0 | Minor detail |

**Scoring thresholds:**
- **Exact match:** Score >= 95 (same table, mode, scaling, workload)
- **Close match:** Score >= 70 (same table + mode, similar scaling)
- **Partial match:** Score >= 50 (same table, different mode or scaling)

### Example Matching Logic

```python
def score_template(template, requirements):
    score = 0
    config = template.get("config", {})
    
    # Table match (required for relevance)
    if config.get("table_name", "").upper() == requirements["table_name"].upper():
        score += 30
    else:
        return 0  # No point continuing if different table
    
    # Table type
    if config.get("table_type") == requirements["table_type"]:
        score += 20
    
    # Load mode
    if config.get("load_mode") == requirements["load_mode"]:
        score += 20
    
    # Scaling parameters (for FIND_MAX_CONCURRENCY)
    if requirements["load_mode"] == "FIND_MAX_CONCURRENCY":
        if config.get("start_concurrency") == requirements.get("start_concurrency"):
            score += 5
        elif abs(config.get("start_concurrency", 0) - requirements.get("start_concurrency", 0)) <= requirements.get("start_concurrency", 1) * 0.2:
            score += 3
            
        if config.get("concurrency_increment") == requirements.get("concurrency_increment"):
            score += 5
        elif abs(config.get("concurrency_increment", 0) - requirements.get("concurrency_increment", 0)) <= requirements.get("concurrency_increment", 1) * 0.2:
            score += 3
            
        if config.get("step_duration_seconds") == requirements.get("step_duration_seconds"):
            score += 5
        elif abs(config.get("step_duration_seconds", 0) - requirements.get("step_duration_seconds", 0)) <= requirements.get("step_duration_seconds", 1) * 0.2:
            score += 3
    
    # Workload mix
    workload_match = True
    for key in ["custom_point_lookup_pct", "custom_range_scan_pct", "custom_insert_pct", "custom_update_pct"]:
        req_val = requirements.get("workload_mix", {}).get(key.replace("custom_", "").replace("_pct", "_pct"), 0)
        tmpl_val = config.get(key, 0)
        if abs(req_val - tmpl_val) > 10:
            workload_match = False
            break
    if workload_match:
        score += 10
    
    # Duration (often varies, so partial credit)
    if config.get("duration_seconds") == requirements.get("duration_seconds"):
        score += 5
    else:
        score += 2  # Partial credit - duration often changes
    
    return score
```

### Present Matches to User

If matches are found, present them before creating a new template:

```markdown
## Existing Templates Found

I found templates that match your requirements:

### Exact Match (Score: 98/100)
**Template:** `postgres-tpch-find-max-20260210`
- Table: UNISTORE_BENCHMARK.PUBLIC.TPCH_SF100_ORDERS (POSTGRES)
- Mode: FIND_MAX_CONCURRENCY (10 start, +20 every 15s)
- Workload: 50% point lookup, 50% range scan
- Duration: 300s (yours: 300s ✓)
- Last run: 2026-02-10, Result: 1,282 QPS max

### Close Match (Score: 78/100)
**Template:** `postgres-tpch-find-max-20260208`
- Table: UNISTORE_BENCHMARK.PUBLIC.TPCH_SF100_ORDERS (POSTGRES)
- Mode: FIND_MAX_CONCURRENCY (5 start, +10 every 30s) ← different scaling
- Workload: 50% point lookup, 50% range scan
- Duration: 600s (yours: 300s)
- Last run: 2026-02-08, Result: 1,150 QPS max

---

What would you like to do?

A) **Use exact match** - Run the existing template as-is
B) **Clone and modify** - Copy the close match and adjust scaling
C) **Create new template** - Start fresh with your specifications
D) **View previous results** - See detailed results from these templates
```

### User Options

**If user selects A (Use existing):**
- Skip template creation
- Proceed directly to Phase 3 (Execution) with existing template_id
- Optionally ask if they want to adjust duration only

**If user selects B (Clone and modify):**
- Fetch the template config
- Apply user's modifications (scaling, duration, etc.)
- Save as new template with incremented name
- Proceed to Phase 3

**If user selects C (Create new):**
- Continue with normal template creation flow
- Use AI_ADJUST to generate SQL

**If user selects D (View results):**
- Show summary of previous runs with that template
- Then return to the A/B/C choice

### When to Skip Template Search

Skip the search if:
- User explicitly says "create new template"
- No templates exist yet (first-time use)
- User is testing a brand new table not previously benchmarked

## Input

Requirements object from Phase 1:

```json
{
  "table_type": "HYBRID",
  "target_table": "DATABASE.SCHEMA.TABLE_NAME",
  "load_mode": "CONCURRENCY",
  "workload_mix": {
    "point_lookup_pct": 50,
    "range_scan_pct": 50,
    "insert_pct": 0,
    "update_pct": 0
  },
  "concurrent_connections": 25,
  "duration_seconds": 300,
  "warmup_seconds": 10,
  "warehouse_size": "Medium",
  "think_time_ms": 0
}
```

## Configuration Generation Steps

### Step 1: Parse Table Reference

Extract database, schema, and table name:

```python
parts = target_table.split(".")
database = parts[0]
schema = parts[1]
table_name = parts[2]
```

### Step 2: Select Configuration Template

Based on `load_mode`, start with the appropriate template:

| Load Mode | Template File |
|-----------|---------------|
| CONCURRENCY | `templates/concurrency-test.json` |
| QPS | `templates/qps-test.json` |
| FIND_MAX_CONCURRENCY | `templates/find-max-test.json` |

### Step 3: Generate Custom Queries

The backend uses `custom_queries` array for workload definition. Generate based on workload mix:

```json
{
  "custom_queries": [
    {
      "name": "POINT_LOOKUP",
      "weight": 50,
      "sql": "SELECT * FROM {table} WHERE {key_column} = ?"
    },
    {
      "name": "RANGE_SCAN",
      "weight": 50,
      "sql": "SELECT * FROM {table} WHERE {time_column} >= ? ORDER BY {time_column} DESC LIMIT 100"
    }
  ]
}
```

**Note:** Actual SQL is generated by the backend's `/api/templates/ai/prepare` and `/api/templates/ai/adjust-sql` endpoints which introspect the table schema.

### How SQL Parameter Placeholders Work (Value Pools)

**DO NOT guess about this - it's a common question from users.**

The `?` and `$1` placeholders in SQL templates are replaced at runtime using **pre-sampled value pools**:

1. **Pool Preparation** (`/api/templates/ai/prepare`):
   - Backend samples actual values from the target table
   - Stores them in `TEMPLATE_VALUE_POOLS` table
   - Includes key columns (e.g., `O_ORDERKEY`) and time columns (e.g., `O_ORDERDATE`)

2. **Runtime Binding** (`backend/core/test_executor.py`):
   - Each worker loads the value pool at startup
   - Workers cycle through the pool with strides based on `worker_id`
   - This ensures different workers query different rows (no hot spots)

3. **Example Flow**:
   ```
   Pool: [1001, 50234, 99887, 1500432, ...]  (sampled from table)
   
   Worker 0: uses 1001, 99887, ...  (stride=2, offset=0)
   Worker 1: uses 50234, 1500432, ... (stride=2, offset=1)
   
   Executed SQL: SELECT * FROM orders WHERE o_orderkey = 1001
   ```

4. **For Range Scans**: The pool provides the starting value, and the query adds an offset (e.g., `BETWEEN ? AND ? + 399`)

**Key Code Locations:**
- `backend/core/test_executor.py:_load_value_pools()` - loads pools
- `backend/core/test_executor.py:_next_from_pool()` - worker value selection
- `backend/core/pool_refresh.py` - refreshes pools after writes

### Postgres Does NOT Use Snowflake Warehouses (CRITICAL)

**⛔ NEVER ask about warehouse for Postgres tests**

Postgres (Snowflake Postgres / PG-compatible endpoints) connects **directly** via a connection_id, NOT through Snowflake warehouses.

| Database Type | Uses Warehouse? | Connection Method |
|---------------|-----------------|-------------------|
| STANDARD      | ✅ Yes          | Snowflake warehouse |
| HYBRID        | ✅ Yes          | Snowflake warehouse |
| INTERACTIVE   | ✅ Yes (INTERACTIVE type) | Snowflake warehouse |
| **POSTGRES**  | ❌ **NO**       | Direct via `connection_id` |

**WRONG (do NOT ask this):**
```
Which warehouse should run the Postgres test?
```

**CORRECT:**
```
For the Postgres test, I'll use connection ID: f63ebd0d-44cc-426e-8506-1060583f3943
(Postgres connects directly - no Snowflake warehouse needed)
```

**When configuring Postgres tests, you need:**
- `connection_id` (from `/api/connections` endpoint)
- `target_table` (fully qualified: `database.schema.table`)
- Load configuration (concurrency, duration, etc.)

**You do NOT need and should NOT ask about:**
- Warehouse name
- Warehouse size
- Warehouse type

### Postgres Requires connection_id for AI_ADJUST

**When calling `/api/templates/{id}/ai/adjust-sql` for Postgres tables, you MUST include the connection_id.**

Without it, the backend cannot connect to Postgres to introspect the schema. It will fail with:
- "Connection refused" (tries localhost:5432)
- Or timeout errors

```bash
# CORRECT - include connection_id
curl -X POST "/api/templates/{id}/ai/adjust-sql" \
  -d '{
    "table_name": "unistore_benchmark.public.orders",
    "connection_id": "f63ebd0d-44cc-426e-8506-1060583f3943"
  }'
```

### Postgres Case Sensitivity

**All Postgres identifiers are case-sensitive and default to lowercase.**

| What | WRONG | CORRECT |
|------|-------|---------|
| Database | `UNISTORE_BENCHMARK` | `unistore_benchmark` |
| Schema | `PUBLIC` | `public` |
| Table | `TPCH_SF100_ORDERS` | `tpch_sf100_orders` |
| Column | `O_ORDERKEY` | `o_orderkey` |

**Common error:** `database "UNISTORE_BENCHMARK" does not exist`
- This means you used uppercase identifiers
- Postgres lowercases unquoted identifiers automatically
- Use lowercase throughout for Postgres tests

### Interactive Tables and Warehouse Binding (CRITICAL)

**This is a common failure mode that the agent MUST understand.**

Interactive Tables (Unistore) require an **Interactive Warehouse** AND the table must be **bound** to that warehouse.

#### How the System Detects Interactive Tables

The backend uses multiple methods (`backend/api/routes/catalog.py:385-452`):

1. **Static Interactive Tables**: `TABLE_TYPE='INTERACTIVE TABLE'` in INFORMATION_SCHEMA
2. **Dynamic Interactive Tables**: `IS_DYNAMIC=YES` AND appears in `SHOW INTERACTIVE TABLES`

```sql
-- Detection query used by the backend
SHOW INTERACTIVE TABLES IN SCHEMA <database>.<schema>
```

#### How the System Checks Warehouse Type

When configuring a test (`backend/api/routes/templates.py:786-801`):

```sql
SHOW WAREHOUSES LIKE '<warehouse_name>'
-- Column 2 shows type: 'STANDARD' vs 'INTERACTIVE'
```

If an Interactive Table is paired with a non-Interactive warehouse, the UI shows a warning:
> "Interactive Tables perform best with INTERACTIVE warehouses."

#### The Binding Requirement

Even with an Interactive Warehouse, the table MUST be explicitly bound:

```sql
ALTER WAREHOUSE <warehouse_name> ADD TABLES (<table_name>)
```

**Runtime Error Detection** (`backend/core/test_executor.py:332-339`):
If this binding is missing, the test will fail with:
> "not bound to the current warehouse"

The system detects this and provides a helpful hint:
> "Run: ALTER WAREHOUSE <name> ADD TABLE <table_name>"

#### What the Agent Should Do

1. **When user selects an Interactive Table**: Check if the warehouse is INTERACTIVE type
2. **When test fails with "not bound"**: 
   - STOP - do NOT automatically run the ALTER command
   - Explain the issue to the user
   - Show the exact command needed
   - Ask for permission before executing

**Example Conversation:**
```
Agent: The test failed because the Interactive Table 'ORDERS_INT' is not bound 
       to warehouse 'PERFTESTING_M_INTERACTIVE_1'.
       
       To fix this, you need to run:
       ALTER WAREHOUSE PERFTESTING_M_INTERACTIVE_1 ADD TABLES (ORDERS_INT)
       
       Should I run this command? [Yes/No]

User: Yes

Agent: [Only now execute the ALTER command]
```

#### Static vs Dynamic Interactive Tables

| Type | Created With | Binding |
|------|--------------|---------|
| Static | `CREATE INTERACTIVE TABLE ... WITH warehouse = WH` | Bound at creation |
| Dynamic | `CREATE INTERACTIVE TABLE ... AS SELECT ...` | Must bind separately |

**Key insight**: Static tables include `WITH warehouse = WH` in their DDL, so they're pre-bound. Dynamic tables (created from a SELECT) need explicit binding afterward.

#### Cluster Key Validation (Performance Critical)

Interactive Tables have a **5-second query timeout**. Queries MUST filter on cluster key columns for acceptable performance.

**How the system detects cluster keys** (`backend/api/routes/templates.py:768-782`):
```sql
SHOW INTERACTIVE TABLES LIKE '<table>' IN SCHEMA <db>.<schema>
-- Column 4 contains cluster_by, e.g., "(O_ORDERDATE, O_CUSTKEY)"
```

**Automatic validation** (`backend/api/routes/templates.py:1241-1264`):
The backend checks if query columns match the cluster key and warns if not:

| Query Type | Check | Warning |
|------------|-------|---------|
| Point Lookup | `key_col` in cluster_by? | "Point lookup uses 'X' but table is clustered on [Y, Z]. Queries on non-clustered columns will be slow (5-second timeout)." |
| Range Scan (ID) | `key_col` in cluster_by? | "Range scan uses 'X' but table is clustered on [Y, Z]." |
| Range Scan (Time) | `time_col` in cluster_by? | "Time-based queries may be slow if not aligned with cluster key." |

**Example warning the agent should surface to user:**
```
⚠️ Point lookup uses 'O_ORDERKEY' but table is clustered on ['O_ORDERDATE', 'O_CUSTKEY'].
   Queries on non-clustered columns will be slow (5-second timeout).
   For optimal performance, query on: O_ORDERDATE, O_CUSTKEY
```

**What the agent should do:**
1. When preparing templates for Interactive Tables, check the cluster key
2. If there's a mismatch, **proactively warn the user** before running tests
3. Suggest alternatives:
   - Use a different table that's clustered appropriately
   - Modify the workload to query on cluster key columns
   - Acknowledge the limitation and proceed (user's choice)

### Step 4: Map Warehouse Size to Name

```python
warehouse_size_map = {
    "X-Small": "COMPUTE_WH_XS",
    "Small": "COMPUTE_WH_S",
    "Medium": "COMPUTE_WH_M",
    "Large": "COMPUTE_WH_L",
    "X-Large": "COMPUTE_WH_XL"
}
```

Or use existing warehouse if user specified custom name.

### Step 5: Build Complete Configuration

Merge template with user requirements:

```json
{
  "template_name": "benchmark-wizard-{timestamp}",
  "description": "Generated by benchmark wizard",
  "config": {
    "table_type": "HYBRID",
    "database": "DATABASE",
    "schema": "SCHEMA",
    "table_name": "TABLE_NAME",
    
    "load_mode": "CONCURRENCY",
    "concurrent_connections": 25,
    "duration_seconds": 300,
    "warmup_seconds": 10,
    "think_time_ms": 0,
    
    "workload_type": "CUSTOM",
    "custom_point_lookup_pct": 50,
    "custom_range_scan_pct": 50,
    "custom_insert_pct": 0,
    "custom_update_pct": 0,
    
    "warehouse_name": "COMPUTE_WH_M",
    "warehouse_size": "Medium",
    
    "metrics_interval_seconds": 1.0,
    "collect_query_history": false
  }
}
```

## Mode-Specific Configuration

### CONCURRENCY Mode

```json
{
  "load_mode": "CONCURRENCY",
  "concurrent_connections": 25
}
```

### QPS Mode

```json
{
  "load_mode": "QPS",
  "target_qps": 500,
  "min_threads_per_worker": 1,
  "starting_threads": 5,
  "max_thread_increase": 15
}
```

### FIND_MAX_CONCURRENCY Mode

```json
{
  "load_mode": "FIND_MAX_CONCURRENCY",
  "start_concurrency": 5,
  "concurrency_increment": 10,
  "step_duration_seconds": 30,
  "qps_stability_pct": 5.0,
  "latency_stability_pct": 20.0,
  "max_error_rate_pct": 1.0
}
```

#### Scaling Rate Recommendations by Warehouse Type

**IMPORTANT:** The scaling rate (concurrency_increment and step_duration_seconds) should be adjusted based on the warehouse type and size. Aggressive scaling on small warehouses can cause premature saturation.

**Interactive Tables (INTERACTIVE warehouse type):**
Interactive warehouses are designed for low-latency, low-concurrency workloads. They scale differently than standard warehouses.

| Warehouse Size | Recommended Settings | Reasoning |
|----------------|---------------------|-----------|
| X-Small | `increment: 5, step: 45s` | Very limited resources, needs time to stabilize |
| Small | `increment: 10, step: 30s` | Conservative scaling |
| Medium+ | `increment: 15, step: 30s` | Can handle faster ramp-up |

**Signs of scaling too fast for interactive warehouses:**
- QPS plateaus early but latency keeps climbing
- Test reaches "backed off" state very quickly (< 2 minutes)
- P99 latency spikes while P50 remains stable
- Seeing "scaling triggered" in warehouse activity

**Standard/MCW Warehouses:**

| Warehouse Size | Recommended Settings | Reasoning |
|----------------|---------------------|-----------|
| X-Small | `increment: 10, step: 30s` | Limited but can handle moderate scaling |
| Small | `increment: 15, step: 30s` | Good balance |
| Medium | `increment: 20, step: 30s` | Can handle faster scaling |
| Large+ | `increment: 25, step: 20s` | Plenty of resources |

**Example for XS Interactive warehouse:**
```json
{
  "load_mode": "FIND_MAX_CONCURRENCY",
  "start_concurrency": 5,
  "concurrency_increment": 5,
  "step_duration_seconds": 45,
  "qps_stability_pct": 5.0,
  "latency_stability_pct": 20.0,
  "max_error_rate_pct": 1.0
}
```

**When analyzing results, watch for:**
- If max concurrency is reached in < 3 steps → scaling too aggressive
- If test runs full duration without backing off → consider more aggressive scaling
- If latency doubles between consecutive steps → near saturation point

## Guardrails Configuration

Guardrails automatically stop tests when resource thresholds are exceeded. **By default, guardrails are DISABLED** to allow tests to run to completion.

### Default Configuration (guardrails off)
```json
{
  "autoscale_enabled": false,
  "guardrails": {
    "enabled": false
  }
}
```

### Enabling Guardrails (optional)
If you want the test to stop automatically when resources are constrained:

```json
{
  "guardrails": {
    "enabled": true,
    "cpu_threshold_pct": 80,
    "memory_threshold_pct": 85,
    "latency_threshold_ms": 500
  }
}
```

**When guardrails trigger:**
- Test stops early with status `STOPPED`
- Reason provided: "CPU hit 97% (threshold: 80%)"
- Partial results are still available

**When to enable guardrails:**
- Production safety testing (don't want to overwhelm systems)
- Shared environments where resource usage matters
- Finding the resource-constrained limit (rather than error limit)

**When to disable guardrails (default):**
- Capacity planning (want to find true maximum)
- Dedicated test environments
- When you want to see what happens at saturation

## AI-Assisted SQL Generation

For non-trivial workloads, call the backend's AI endpoints to generate appropriate SQL:

### Step 1: Prepare Configuration

```bash
POST /api/templates/ai/prepare
Content-Type: application/json

{
  "table_type": "HYBRID",
  "database": "DATABASE",
  "schema": "SCHEMA",
  "table_name": "TABLE_NAME"
}
```

**Response includes:**
- `key_column`: Detected primary key column
- `time_column`: Detected timestamp column
- `columns_map`: Column names and types

### Step 2: Generate SQL

```bash
POST /api/templates/ai/adjust-sql
Content-Type: application/json

{
  "table_type": "HYBRID",
  "database": "DATABASE",
  "schema": "SCHEMA",
  "table_name": "TABLE_NAME",
  "custom_point_lookup_pct": 50,
  "custom_range_scan_pct": 50,
  "custom_insert_pct": 0,
  "custom_update_pct": 0
}
```

**Response includes:**
- `custom_point_lookup_sql`: Generated point lookup query
- `custom_range_scan_sql`: Generated range scan query
- `custom_insert_sql`: Generated insert statement
- `custom_update_sql`: Generated update statement
- `ai_summary`: Description of what was generated
- `issues`: Any warnings or problems detected

### Step 3: Present AI Summary to User

**IMPORTANT: Always show the AI summary and generated SQL to the user for review.**

```markdown
## AI-Generated SQL Configuration

**AI Summary:**
{ai_summary from response}

**Generated Queries:**

Point Lookup (90%):
```sql
{custom_point_lookup_sql}
```

Range Scan (10%):
```sql
{custom_range_scan_sql}
```

**Detected Issues:**
{issues array, or "None" if empty}

---

Does this look correct for your table? [Y/n/modify]
```

If user says no or wants to modify:
- Allow them to provide custom SQL instead
- Or adjust the workload percentages and regenerate

If there are issues in the response:
- Highlight them prominently
- Recommend switching to Custom SQL mode if issues are severe

## Configuration Validation

Before proceeding, validate the configuration:

### Required Fields Check

```python
required_fields = [
    "table_type",
    "database",
    "schema", 
    "table_name",
    "load_mode",
    "duration_seconds",
    "workload_type"
]

for field in required_fields:
    if field not in config:
        raise ValueError(f"Missing required field: {field}")
```

### Percentage Validation

```python
total_pct = (
    config.get("custom_point_lookup_pct", 0) +
    config.get("custom_range_scan_pct", 0) +
    config.get("custom_insert_pct", 0) +
    config.get("custom_update_pct", 0)
)

if total_pct != 100:
    raise ValueError(f"Workload percentages must sum to 100, got {total_pct}")
```

### Mode-Specific Validation

```python
if config["load_mode"] == "QPS" and not config.get("target_qps"):
    raise ValueError("QPS mode requires target_qps")

if config["load_mode"] == "CONCURRENCY" and not config.get("concurrent_connections"):
    raise ValueError("CONCURRENCY mode requires concurrent_connections")
```

## Cost Estimation

Provide estimated credit consumption:

```python
def estimate_cost(config):
    duration_hours = config["duration_seconds"] / 3600
    warmup_hours = config.get("warmup_seconds", 0) / 3600
    total_hours = duration_hours + warmup_hours
    
    size_credits = {
        "X-Small": 1,
        "Small": 2,
        "Medium": 4,
        "Large": 8,
        "X-Large": 16
    }
    
    credits_per_hour = size_credits.get(config["warehouse_size"], 1)
    estimated_credits = total_hours * credits_per_hour
    
    return round(estimated_credits, 3)
```

## Configuration Summary

Present the final configuration to user for approval:

```markdown
## Test Configuration Summary

**Template Name:** benchmark-wizard-20260213-143022

**Target Table:**
- Type: HYBRID
- Location: DATABASE.SCHEMA.TABLE_NAME

**Load Configuration:**
- Mode: CONCURRENCY (fixed 25 connections)
- Duration: 5 minutes + 10s warmup

**Workload:**
- Point lookups: 50%
- Range scans: 50%

**Generated SQL:**
```sql
-- Point Lookup
SELECT * FROM DATABASE.SCHEMA.TABLE_NAME WHERE ID = ?

-- Range Scan  
SELECT * FROM DATABASE.SCHEMA.TABLE_NAME 
WHERE CREATED_AT >= ? 
ORDER BY CREATED_AT DESC LIMIT 100
```

**Warehouse:** COMPUTE_WH_M (Medium, 4 credits/hour)

**Estimated Cost:** ~0.35 credits

---

Ready to save this configuration and create a test run?

A) Save and create run (proceed to execution)
B) Modify configuration
C) Cancel
```

## Save Template

If user approves, save to Snowflake:

**CRITICAL: API Format Requirements**

The template API requires a **nested `config` object** - all configuration fields must be inside `config`, NOT at the root level.

**WRONG (will fail with "Field required: body.config"):**
```json
{
  "template_name": "my-benchmark",
  "table_type": "POSTGRES",
  "load_mode": "FIND_MAX_CONCURRENCY",
  "duration_seconds": 300
}
```

**CORRECT (nested config structure):**
```bash
curl -sL -X POST "http://127.0.0.1:8000/api/templates/" \
  -H "Content-Type: application/json" \
  -d '{
    "template_name": "benchmark-wizard-20260213-143022",
    "description": "HYBRID table benchmark - 25 connections, read-only",
    "config": {
      "table_type": "HYBRID",
      "database": "DATABASE",
      "schema": "SCHEMA",
      "table_name": "TABLE_NAME",
      "connection_id": "uuid-for-postgres-only",
      
      "load_mode": "FIND_MAX_CONCURRENCY",
      "start_concurrency": 5,
      "concurrency_increment": 10,
      "step_duration_seconds": 30,
      
      "duration_seconds": 300,
      "warmup_seconds": 10,
      "think_time_ms": 0,
      
      "workload_type": "CUSTOM",
      "custom_point_lookup_pct": 90,
      "custom_range_scan_pct": 10,
      "custom_insert_pct": 0,
      "custom_update_pct": 0,
      
      "custom_point_lookup_query": "SELECT * FROM {table} WHERE o_orderkey = $1",
      "custom_range_scan_query": "SELECT * FROM {table} WHERE o_orderdate >= $1 ORDER BY o_orderdate LIMIT 100",
      
      "warehouse_name": "COMPUTE_WH_M",
      "warehouse_size": "Medium",
      
      "autoscale_enabled": false,
      "guardrails": {
        "enabled": false
      },
      
      "metrics_interval_seconds": 1.0,
      "collect_query_history": false
    },
    "tags": {
      "source": "benchmark-wizard",
      "table_type": "HYBRID",
      "load_mode": "FIND_MAX_CONCURRENCY"
    }
  }'
```

**Note:** Always use trailing slashes on API endpoints (e.g., `/api/templates/` not `/api/templates`).

**Response:**
```json
{
  "template_id": "abc123-def456",
  "template_name": "benchmark-wizard-20260213-143022",
  "created_at": "2026-02-13T14:30:22Z"
}
```

## Output

Pass to Phase 3 (Execution) with:

```json
{
  "template_id": "abc123-def456",
  "config": { ... },
  "estimated_credits": 0.35
}
```

## Error Handling

| Error | Action |
|-------|--------|
| AI SQL generation failed | Fall back to template defaults, warn user |
| Table introspection failed | Ask user for key/time column names manually |
| Template save failed | Show error, offer to retry or export JSON |
| Invalid configuration | Show validation errors, return to modification |

## Next Phase

→ `workflows/03-execution.md`
