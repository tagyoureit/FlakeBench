# Phase 1: Requirements Gathering

## Purpose

Interactively gather benchmark requirements through structured questions. This phase determines WHAT to test and HOW to measure it.

## CRITICAL: Mandatory User Interaction Points

**The agent MUST pause and ask questions at these checkpoints, even if the user provided detailed initial requirements:**

### Checkpoint 1: Configuration Confirmation (REQUIRED)
Before generating any templates or configs, the agent MUST:
1. Summarize what it understood from the user's request
2. Ask user to confirm or correct the interpretation
3. Ask about anything the user didn't specify (workload mix, SLOs, etc.)

**Example:**
```markdown
## Let me confirm your benchmark requirements:

**What I understood:**
- Benchmark type: FIND_MAX_CONCURRENCY
- Tables: Postgres (tpch_sf100_orders) vs Interactive (TPCH_SF100_ORDERS_INT)
- Starting threads: 10, increment: 20, step: 15s

**I still need to know:**
1. What's your workload mix? (default is 50% point lookups, 50% range scans)
2. Do you have latency SLO targets? (helps interpret results)
3. Test duration - how long should each test run?

Please confirm or adjust these settings.
```

### Checkpoint 2: SQL Review (REQUIRED)
After calling AI_ADJUST to generate SQL, the agent MUST:
1. Show the generated SQL to the user
2. Explicitly ask for approval before proceeding
3. Never auto-proceed - wait for user confirmation

**Example:**
```markdown
## Generated SQL for Postgres test:

**Point Lookup (50%):**
```sql
SELECT * FROM tpch_sf100_orders WHERE o_orderkey = $1
```

**Range Scan (50%):**
```sql
SELECT * FROM tpch_sf100_orders WHERE o_orderdate >= $1 ORDER BY o_orderdate LIMIT 100
```

Does this look correct? [Yes/No/Modify]
```

### Checkpoint 3: Pre-Execution Confirmation (REQUIRED)
Before starting ANY test run, the agent MUST:
1. Show the complete test configuration
2. Show estimated duration and cost
3. Ask "Ready to start this test?" and wait for explicit "yes"

**Example:**
```markdown
## Ready to start Postgres benchmark

- Template: postgres-find-max-20260214
- Mode: FIND_MAX_CONCURRENCY (10 → ? threads, +20 every 15s)
- Estimated duration: 5-10 minutes
- Estimated cost: ~0.15 credits

Start this test? [Yes/No]
```

### DO NOT:
- Auto-proceed after gathering information
- Start tests without explicit user confirmation  
- Skip showing generated SQL
- Assume defaults without mentioning them to user
- Run multiple tests without confirming each one

### WHY THIS MATTERS:
Users need visibility into what the agent is doing. Even when they provide detailed requirements, they expect:
- Confirmation that the agent understood correctly
- Opportunity to adjust before execution
- Clear checkpoints where they can intervene

## Workflow Entry Point

Start when user invokes benchmark wizard with phrases like:
- "Help me benchmark..."
- "I want to performance test..."
- "Compare my tables..."
- "Run a load test..."

## Question Flow

### Q1: What do you want to benchmark?

**Ask:**
```
What type of table do you want to benchmark?

A) HYBRID table (Snowflake hybrid with row-level indexes)
B) STANDARD table (Traditional Snowflake columnar)
C) POSTGRES table (Snowflake Postgres preview)
D) Compare multiple table types (side-by-side comparison)
```

**Store:** `table_type` = user selection

**If D selected:** Ask which types to compare (checkbox: HYBRID, STANDARD, POSTGRES)

### Q2: Target Table

**IMPORTANT: Connection handling varies by table type:**

#### For POSTGRES table type:

**DO NOT query Snowflake to find Postgres tables.** Postgres tables are on separate Postgres instances, not in regular Snowflake.

**Step 1: List available Postgres connections from backend:**
```bash
curl -sL "http://127.0.0.1:8000/api/connections/"
```

This returns stored connections with their IDs:
```json
[
  {
    "id": "f63ebd0d-44cc-426e-8506-1060583f3943",
    "name": "my_postgres",
    "host": "xxx.postgres.snowflake.app",
    "database": "mydb",
    "user": "benchmark_app"
  }
]
```

**Step 2: Ask user to select or provide connection:**
```
What Postgres connection should we use?

Available connections from backend:
[List connections from /api/connections/ response]

Or provide new connection details:
- Instance host: ___
- Database: ___
- Username: ___
- Password: ___
- Schema (default: public): ___
- Table name: ___
```

**If user selects existing connection:**
- Store the `connection_id` for template config
- No need to handle credentials directly

**If user provides new connection:**
- Store via `POST /api/connections/` with encrypted credentials
- Get back `connection_id` to use in template

**Step 3: Verify connection works:**
```bash
# Test connection via backend
curl -sL "http://127.0.0.1:8000/api/connections/{connection_id}/test"
```

**IMPORTANT: PgBouncer Connection Limitations**

When using Snowflake Postgres with PgBouncer (connection pooling), the `snowflake_admin` user **CANNOT be used for benchmark testing**. This is because:
- PgBouncer requires specific authentication that snowflake_admin doesn't support
- You'll see errors like: `InvalidAuthorizationSpecificationError: Snowflake authentication failed`

**Use a dedicated benchmark user** (e.g., `benchmark_app`) instead of `snowflake_admin` for all benchmark connections.

If you see authentication failures:
1. Check if the connection uses `snowflake_admin` - if so, switch to a different connection
2. Test the connection with `POST /api/connections/{id}/test` before proceeding
3. Create a new connection with a non-admin user if needed

**Store:** 
- `connection_id` = UUID from backend (REQUIRED for Postgres)
- `postgres_database` = database name
- `postgres_schema` = schema name
- `target_table` = table name

#### For HYBRID / STANDARD table types:

**Ask:**
```
What is the fully qualified table name?

Format: DATABASE.SCHEMA.TABLE_NAME

Example: PROD_DB.PUBLIC.ORDERS
```

**Validation:**
- Must contain exactly 2 dots
- Each component must be valid identifier
- Verify table exists (optional, can defer to preflight)

**Store:** `target_table` = user input

**For comparison mode:** Ask for each table type being compared

### Q2b: Table Discovery & Validation

**IMPORTANT: Discover table metadata BEFORE asking about workload mix.**

This step determines what operations are possible on the target table.

#### For HYBRID / STANDARD tables:

**Run discovery query:**
```sql
SHOW TABLES LIKE '{table_name}' IN {database}.{schema};
-- or for views:
SHOW VIEWS LIKE '{table_name}' IN {database}.{schema};
```

**Extract and store:**
- `is_view` = true if object is a VIEW
- `is_dynamic_table` = true if KIND = 'DYNAMIC TABLE'
- `is_interactive` = true if table type indicates INTERACTIVE
- `is_external` = true if table is EXTERNAL
- `can_write` = false if (is_view OR is_dynamic_table OR is_external), true otherwise

**Also get table structure:**
```sql
DESCRIBE TABLE {target_table};
```

**Store:**
- `table_columns` = list of column names and types
- `primary_key_columns` = columns that appear to be PKs (for point lookup generation)

#### For POSTGRES tables:

**Run discovery via Postgres connection:**
```sql
-- Using the postgres instance connection
SELECT column_name, data_type, is_nullable
FROM information_schema.columns 
WHERE table_schema = '{schema}' AND table_name = '{table}';

-- Check if it's a view
SELECT table_type FROM information_schema.tables
WHERE table_schema = '{schema}' AND table_name = '{table}';
```

**Store:**
- `is_view` = true if table_type = 'VIEW'
- `can_write` = false if is_view, true otherwise
- `table_columns` = list of columns
- `primary_key_columns` = from pg_constraint or detected from column names

#### Discovery Output Summary:

Present discovered info to user:
```
Table Discovery Results:
========================
Table: {target_table}
Type: {HYBRID|STANDARD|POSTGRES} {VIEW|DYNAMIC TABLE|TABLE}
Columns: {count} columns
Primary Key: {pk_columns or "Not detected - you'll need to specify"}
Write Operations: {"Supported" if can_write else "NOT SUPPORTED (read-only object)"}
```

### Q3: What do you want to measure?

**Ask:**
```
What's your primary goal?

A) Measure latency at a specific load level (CONCURRENCY mode)
   → "How fast are queries at X concurrent users?"

B) Test if system can sustain a target throughput (QPS mode)
   → "Can the system handle Y queries per second?"

C) Find maximum sustainable throughput (FIND_MAX_CONCURRENCY mode)
   → "What's the highest QPS before performance degrades?"

D) Not sure - recommend based on my use case
```

**Store:** `load_mode` = CONCURRENCY | QPS | FIND_MAX_CONCURRENCY

**If D selected:** Ask follow-up:
```
What's your use case?

A) Capacity planning for production launch
   → Recommend: FIND_MAX_CONCURRENCY

B) Validating SLA requirements
   → Recommend: QPS mode with target from SLA

C) Comparing configurations (warehouse sizes, table types)
   → Recommend: CONCURRENCY for fair comparison

D) General performance baseline
   → Recommend: CONCURRENCY at expected production load
```

### Q4: Workload Mix

**IMPORTANT: Options vary based on `can_write` from table discovery.**

#### If `can_write` = false (VIEWs, DYNAMIC TABLEs, EXTERNAL TABLEs, INTERACTIVE):

**Ask:**
```
What type of queries will you run?

Note: This is a read-only object - write operations are not available.

A) Point lookups only (SELECT by primary key)
   → 100% point lookup

B) Range scans only (SELECT with WHERE clause ranges)
   → 100% range scan

C) Mixed reads (point lookups + range scans)
   → 50% point, 50% range

D) Custom SQL queries (provide your own SELECT statements)
   → You'll provide specific SQL templates

E) Custom mix - I'll specify read percentages
```

#### If `can_write` = true (regular HYBRID, STANDARD, POSTGRES tables):

**Ask:**
```
What type of queries will you run?

A) Point lookups only (SELECT by primary key)
   → 100% point lookup

B) Range scans only (SELECT with WHERE clause ranges)
   → 100% range scan

C) Read-heavy mixed (mostly reads, some writes)
   → 40% point, 40% range, 15% insert, 5% update

D) Write-heavy mixed (mostly writes, some reads)
   → 20% point, 10% range, 50% insert, 20% update

E) Custom SQL queries (provide your own SQL statements)
   → You'll provide specific SQL templates

F) Custom mix - I'll specify percentages
```

**Store:** `workload_mix` = { point_pct, range_pct, insert_pct, update_pct } OR `workload_type` = "CUSTOM"

**If Custom SQL selected:**
```
Provide your custom SQL queries. You can specify multiple queries with weights.

Query 1 (required):
  SQL: ___
  Weight (1-100, default 100): ___

Query 2 (optional):
  SQL: ___
  Weight: ___

[Add more queries as needed]

Tips:
- Use :pk for primary key placeholder (e.g., WHERE id = :pk)
- Use :range_start/:range_end for range queries
- Weights determine relative frequency (e.g., weight 80 + weight 20 = 80%/20% split)
{if can_write: "- INSERT/UPDATE/DELETE statements are supported"}
{if not can_write: "- Only SELECT statements are allowed for this read-only object"}
```

**Store:** `custom_queries` = list of { sql, weight }

**If Custom percentages selected:** 
- If `can_write`: Ask for point_pct, range_pct, insert_pct, update_pct (must sum to 100)
- If not `can_write`: Ask for point_pct, range_pct only (must sum to 100)

### Q4b: SQL Generation Strategy

**CRITICAL: You MUST either use AI_ADJUST or provide Custom SQL. NEVER use default template SQL - it will NOT match your table's column names and will fail.**

**Ask (unless user already selected "Custom SQL queries" in Q4):**
```
How should we generate the SQL queries for your workload?

A) AI_ADJUST (recommended)
   → Automatically analyze your table schema and generate correct SQL
   → Uses the backend's AI endpoint to detect key columns and generate queries
   → Handles case-sensitivity (e.g., Postgres lowercase columns)
   → Best for: Most use cases - ensures queries match your actual table structure

B) Custom SQL (manual)
   → You provide the exact SQL queries to execute
   → Full control over query structure
   → Best for: Complex queries, specific access patterns, or when you know the exact SQL needed
```

**Store:** `sql_generation_strategy` = AI_ADJUST | CUSTOM

**If AI_ADJUST selected:**
- Backend will call `/api/templates/ai/prepare` to introspect table
- Then `/api/templates/ai/adjust-sql` to generate correct queries
- Present generated SQL to user for review before proceeding
- **Important for Postgres:** Column names are case-sensitive. AI_ADJUST handles this correctly.

**If CUSTOM selected:**
- Already handled in Q4 - user provides custom queries
- Remind user about case-sensitivity for Postgres tables

### Q5: Load Parameters (varies by mode)

#### For CONCURRENCY mode:
```
How many concurrent connections?

A) Light load (5 connections)
B) Medium load (25 connections)
C) Heavy load (100 connections)
D) Custom - I'll specify
```

**Store:** `concurrent_connections` = integer

#### For QPS mode:
```
What's your target queries per second (QPS)?

Enter a number (e.g., 500)
```

**Store:** `target_qps` = float

#### For FIND_MAX_CONCURRENCY mode:
```
Configure FIND_MAX_CONCURRENCY parameters:

Starting concurrency (default: 5): ___
Increment per step (default: 10): ___
Step duration seconds (default: 30): ___
```

**Store:** `start_concurrency`, `concurrency_increment`, `step_duration_seconds`

### Q6: Duration

**Ask:**
```
How long should the test run?

A) Quick test (60 seconds) - good for initial validation
B) Standard test (5 minutes) - recommended for benchmarks
C) Extended test (15 minutes) - for stability testing
D) Custom duration
```

**Store:** `duration_seconds` = integer

**Note:** For FIND_MAX_CONCURRENCY mode, this is total duration; actual duration may vary based on step count.

### Q7: Warehouse Configuration

**Ask:**
```
Which warehouse size?

A) X-Small (1 credit/hour) - development/testing
B) Small (2 credits/hour) - light production
C) Medium (4 credits/hour) - standard production
D) Large (8 credits/hour) - high throughput
E) Compare multiple sizes (side-by-side)
```

**Store:** `warehouse_size` = string or list

**If E selected:** Ask which sizes to compare (checkbox)

**Warehouse Status Reporting:**

When checking warehouse status with `SHOW WAREHOUSES`, report the actual state from Snowflake:
- `STARTED` / `RUNNING` = warehouse is active
- `SUSPENDED` = warehouse is stopped (will auto-resume on use)
- `RESIZING` = warehouse is changing size

**Do NOT say "Started" unless you explicitly ran `ALTER WAREHOUSE ... RESUME`.** The warehouse may already be running from previous use. Simply report the current state as returned by Snowflake.

### Q8: SLO / Latency Targets (Important for Analysis)

**Ask:**
```
Do you have latency SLOs or performance targets for this workload?

A) Yes, I have specific targets
B) No specific targets, just exploring performance
C) Compare against baseline (another table/warehouse)
```

**If A selected, ask:**
```
What are your latency targets? (milliseconds)

- P50 latency target: ___ ms (typical request)
- P95 latency target: ___ ms (most requests)  
- P99 latency target: ___ ms (worst case acceptable)
```

**Store:** `slo_targets` = object or null
```json
{
  "p50_ms": 50,
  "p95_ms": 200,
  "p99_ms": 500
}
```

**Why This Matters:** SLO targets help analyze results in context:
- "You achieved P95 of 45ms, which is well under your 200ms target"
- "At 100 threads, P99 exceeded your 500ms SLO - consider scaling warehouse"
- Helps determine if FIND_MAX_CONCURRENCY results are acceptable

### Q9: Additional Options (Optional)

**Ask:**
```
Any additional configuration? (optional, press Enter to skip)

- Warmup period (default: 10 seconds): ___
- Think time between queries (default: 0ms): ___
- Custom warehouse name: ___
- Test name/description: ___
```

**Store:** Optional parameters

## Requirements Summary

After gathering all inputs, present a summary:

```markdown
## Benchmark Requirements Summary

**Target:** DATABASE.SCHEMA.TABLE_NAME (HYBRID)
{if can_write = false: "**Note:** This is a read-only object (VIEW/DYNAMIC TABLE) - write operations disabled"}
**Goal:** Measure latency at fixed concurrency (CONCURRENCY mode)

**Workload Mix:**
- Point lookups: 50%
- Range scans: 50%
{if can_write: "- Inserts: 0%"}
{if can_write: "- Updates: 0%"}

**Load Configuration:**
- Concurrent connections: 25
- Duration: 300 seconds (5 minutes)
- Warmup: 10 seconds

**Warehouse:** Medium (4 credits/hour)

**Estimated Cost:** ~0.33 credits (5 min × 4 credits/hour)

Proceed to generate configuration? [Y/n]
```

## Output

Pass to Phase 2 (Configuration) with collected parameters:

**For HYBRID/STANDARD tables:**
```json
{
  "table_type": "HYBRID",
  "target_table": "DATABASE.SCHEMA.TABLE_NAME",
  "can_write": true,
  "object_kind": "TABLE",
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

**For read-only objects (VIEWs, DYNAMIC TABLEs):**
```json
{
  "table_type": "STANDARD",
  "target_table": "DATABASE.SCHEMA.VIEW_NAME",
  "can_write": false,
  "object_kind": "VIEW",
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

**For POSTGRES tables:**
```json
{
  "table_type": "POSTGRES",
  "postgres_instance": "my_postgres_instance",
  "postgres_database": "mydb",
  "postgres_schema": "public",
  "target_table": "orders",
  "can_write": true,
  "load_mode": "CONCURRENCY",
  "workload_mix": {
    "point_lookup_pct": 100,
    "range_scan_pct": 0,
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

**For Custom SQL workload:**
```json
{
  "table_type": "HYBRID",
  "target_table": "DATABASE.SCHEMA.TABLE_NAME",
  "can_write": true,
  "object_kind": "TABLE",
  "load_mode": "CONCURRENCY",
  "workload_type": "CUSTOM",
  "custom_queries": [
    { "sql": "SELECT * FROM orders WHERE order_id = :pk", "weight": 80 },
    { "sql": "SELECT * FROM orders WHERE customer_id = :pk AND order_date > :range_start", "weight": 20 }
  ],
  "concurrent_connections": 25,
  "duration_seconds": 300,
  "warmup_seconds": 10,
  "warehouse_size": "Medium",
  "think_time_ms": 0
}
```

## Validation Rules

| Field | Rule |
|-------|------|
| table_type | Must be HYBRID, STANDARD, or POSTGRES |
| target_table | For HYBRID/STANDARD: DATABASE.SCHEMA.TABLE format; For POSTGRES: just table name |
| postgres_instance | Required if table_type=POSTGRES; must exist in SHOW POSTGRES INSTANCES |
| postgres_database | Required if table_type=POSTGRES |
| can_write | Boolean from table discovery; false for VIEWs, DYNAMIC TABLEs, EXTERNAL, INTERACTIVE |
| workload_mix | Percentages must sum to 100 (unless workload_type=CUSTOM) |
| workload_mix.insert_pct | Must be 0 if can_write=false |
| workload_mix.update_pct | Must be 0 if can_write=false |
| custom_queries | Required if workload_type=CUSTOM; at least 1 query with valid SQL |
| custom_queries (writes) | INSERT/UPDATE/DELETE only allowed if can_write=true |
| concurrent_connections | 1-1000 |
| target_qps | 1-100000 |
| duration_seconds | 10-3600 |
| warmup_seconds | 0-300 |

## Error Handling

| Error | Action |
|-------|--------|
| Invalid table format | Re-prompt with example |
| Percentages don't sum to 100 | Show current sum, ask to adjust |
| Value out of range | Show valid range, re-prompt |
| User wants to cancel | Confirm cancellation, exit wizard |

## Next Phase

→ `workflows/02-configuration.md`
