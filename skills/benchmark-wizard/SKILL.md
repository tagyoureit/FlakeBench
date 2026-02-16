---
name: benchmark-wizard
description: Interactive wizard to design, execute, and analyze Snowflake/Postgres performance benchmarks. Guides through table type selection, workload configuration, test execution, and result analysis via Cortex Agent. Triggers on "benchmark", "performance test", "help me test", "compare tables", "load test".
version: 1.0.0
---

# Benchmark Wizard

## Purpose

Guide users through the complete benchmark lifecycle: requirements gathering, test configuration, execution monitoring, and AI-powered result analysis. Reduces the complexity of performance testing by providing an interactive, step-by-step workflow.

## When to Use

- Design a new performance benchmark from scratch
- Compare table types (HYBRID vs STANDARD vs POSTGRES)
- Compare warehouse sizes or configurations
- Run load tests with specific throughput targets
- Find maximum sustainable concurrency for a table
- Analyze benchmark results with natural language queries

## MANDATORY: Gates with Proof (Show Your Work)

> **⛔ THE PROBLEM WE'RE SOLVING**
>
> Agents skip steps by "optimizing for efficiency." They find loopholes like:
> - "existing templates are already correct"
> - "user gave detailed requirements so I'll skip confirmation"
> - **"I'll mark ✅ and write '(per original request)' instead of actually asking"**
>
> **THE SOLUTION: You must SHOW EVIDENCE at each gate.**
>
> Checkmarks (✅) are NOT evidence. You must paste the user's actual response.
> If you cannot quote what the user said, you didn't ask.

---

### 🚫 LOOPHOLE ALERT: "Detailed Requirements" is NOT Approval

**This is the #1 way agents cheat:**
```
User: "Run a FIND_MAX test on TPCH_SF100_ORDERS with 100% point lookups..."
Agent thinks: "User gave detailed requirements, that's implicit approval!"
Agent marks: "User confirmed: ✅ (per original request)"
```

**THIS IS A VIOLATION.** The user describing what they want is NOT the same as approving your interpretation of it. You MUST still:
1. Show your configuration table
2. Call `ask_user_question` 
3. Paste their response as evidence

**No exceptions. No "per original request." No implicit approval.**

---

### 🚫 Existing Templates Do NOT Bypass Checks

**Finding an existing template does NOT mean:**
- ❌ The SQL is correct for YOUR table
- ❌ The cluster keys align  
- ❌ You can skip SQL review
- ❌ The template was ever tested successfully
- ❌ The template has valid value pools (ai_workload.pool_id)

**Existing templates are UNTRUSTED.** You must still:
1. Verify `ai_workload.pool_id` exists (not null) for Interactive Tables
2. Verify cluster key alignment
3. Show the SQL to the user for approval
4. Check column names match the target table

---

### Gate 1: Configuration Confirmed

**Before searching for templates or creating configs, output this block:**

```
## ✅ GATE 1: Configuration Confirmed

| Item | Value |
|------|-------|
| Tables | [list each table with type] |
| Workload mix | [X% point, Y% range, Z% write] |
| Test mode | [CONCURRENCY / QPS / FIND_MAX] |
| Postgres connection | [connection name or N/A] |
| PgBouncer | [yes/no or N/A] |
| Interactive warehouse | [warehouse name or N/A] |

### User Confirmation (REQUIRED)
Called ask_user_question: [YES/NO]
User's response: "[paste exact response here]"
```

**Rules:**
- You MUST call `ask_user_question` - no exceptions
- Paste the user's exact response in quotes
- "per original request" or "implicit approval" = VIOLATION
- If user selects "Something else", paste what they typed

---

### Gate 2: SQL and Cluster Key Verified

**Before creating runs or using templates, output this block:**

```
## ✅ GATE 2: SQL and Cluster Key Verified

### Template Validation (if using existing template)
Template ID: [uuid]
ai_workload.pool_id: [uuid or ⚠️ NULL - DO NOT USE]

### Cluster Key Check (Interactive Tables only)
SHOW INTERACTIVE TABLES LIKE '<table>' IN SCHEMA <db>.<schema>
→ Cluster key: [paste actual output, e.g., "(O_ORDERKEY)"]

### SQL Review
**Point Lookup SQL:**
```sql
SELECT ... WHERE <column> = ?
```
→ Column matches cluster key: [YES/NO]

**Range Scan SQL (if applicable):**
```sql  
SELECT ... WHERE <column> BETWEEN ? AND ?
```
→ Column matches cluster key: [YES/NO]

### User Confirmation (REQUIRED)
Called ask_user_question: [YES/NO]
User's response: "[paste exact response here]"
```

**Rules:**
- For existing templates: Check `ai_workload.pool_id` is not null
- For Interactive Tables: Run `SHOW INTERACTIVE TABLES` and paste output
- Show the ACTUAL SQL from the template, not just a pattern
- Call `ask_user_question` and paste response

---

### Gate 3: Execution Approved

**Before calling `/api/runs/{id}/start`, output this block:**

```
## ✅ GATE 3: Execution Approved

### Tests to Run
| # | Name | Table | Type | Template | Pool Valid |
|---|------|-------|------|----------|------------|
| 1 | [name] | [table] | [type] | [uuid] | [YES/NO] |
| 2 | [name] | [table] | [type] | [uuid] | [YES/NO] |

### Config Verification (CRITICAL)
For each run created, verify the config matches your request:
- Run [uuid]: workload = [X% point / Y% range] ← matches request? [YES/NO]

### Execution Mode
Asked user preference: [YES/NO]
User chose: [auto-sequential / pause between tests]

### Pre-flight Check
- [ ] Ran /api/runs/{id}/preflight - no blocking issues

### User Confirmation (REQUIRED)
Called ask_user_question: [YES/NO]  
User's response: "[paste exact response here]"
```

**Rules:**
- After creating runs, GET the run and verify config values match your intent
- If config doesn't match (e.g., 95% instead of 100%), STOP and report to user
- Ask execution mode preference
- Call `ask_user_question` before starting first test

---

### Gate 4: Results Presented

**After tests complete, output this block:**

```
## ✅ GATE 4: Results Presented

### Test Results
| Test | Name | Run ID | Dashboard URL | Status |
|------|------|--------|---------------|--------|
| 1 | [name] | [uuid] | http://127.0.0.1:8000/dashboard/[uuid] | [COMPLETED/FAILED] |
| 2 | [name] | [uuid] | http://127.0.0.1:8000/dashboard/[uuid] | [status] |

### Workload Verification
Requested: [X% point / Y% range]
Actual (from run config): [X% point / Y% range]
Match: [YES / ⚠️ NO - MUST REPORT TO USER]

### AI Analysis
- Called endpoint: [/api/tests/compare/ai-analysis or /api/tests/{id}/ai-analysis]
- Presented FULL output: [YES/NO]

### If Any Test Failed
- Investigated root cause before retrying: [YES/NO/N/A]
- Root cause: [description or N/A]
```

**Rules:**
- Compare requested vs actual workload - if mismatch, TELL THE USER
- Present full AI analysis output (can add insights AFTER, never reduce)
- If test failed, investigate logs BEFORE retrying

---

### Quick Reference: Evidence Checklist

**Remember: Checkmarks are NOT evidence. You must paste user responses.**

```
Gate 1: Called ask_user_question? [YES/NO] User said: "[quote]"
Gate 2: Called ask_user_question? [YES/NO] User said: "[quote]"  
Gate 3: Called ask_user_question? [YES/NO] User said: "[quote]"
Gate 4: Workload matched request? [YES/NO] If NO, told user? [YES/NO]
```

**Violation examples:**
- ❌ "User confirmed: ✅ (per original request)"
- ❌ "User confirmed: ✅ (implicit from detailed requirements)"
- ❌ "Skipping confirmation since user was clear"

**The ONLY valid evidence:**
- ✅ "User's response: 'Yes, proceed with 100% point lookups'"
- ✅ "User selected: 'Auto-sequential' from ask_user_question"

---

### Use Interactive Questions (ask_user_question tool)

**For all gates, use the `ask_user_question` tool** to gather info and confirmations:

```
ask_user_question:
  question: "What workload mix should the benchmark use?"
  header: "Workload"
  options:
    - label: "100% point lookups"
      description: "Single-row lookups by primary key"
    - label: "95% point / 5% range"
      description: "Mostly point lookups with some range scans"
    - label: "90% point / 10% range"  
      description: "Mixed workload with more range scans"
```

**You can ask multiple questions at once** (up to 4):
```
ask_user_question:
  questions:
    - question: "What workload mix?"
      header: "Workload"
      options: [...]
    - question: "Use PgBouncer?"
      header: "Pooling"
      options: [...]
```

---

## Prerequisites

**Required:**
- Backend server running (`uv run python -m backend.main`)
- Active Snowflake connection configured in CoCo
- Target table(s) exist in Snowflake or Postgres

**For Postgres tests:**
- Connection stored via `/api/connections` endpoint
- Network access to Postgres instance

## Inputs

### Required (gathered interactively)
- **table_type**: `HYBRID` | `STANDARD` | `POSTGRES` | `compare` (multiple types)
- **target_table**: Fully qualified table name (DATABASE.SCHEMA.TABLE)
- **load_mode**: `CONCURRENCY` | `QPS` | `FIND_MAX_CONCURRENCY`

### Optional (with defaults)
- **duration_seconds**: Test duration (default: 60)
- **concurrent_connections**: Thread count for CONCURRENCY mode (default: 10)
- **target_qps**: Throughput target for QPS mode
- **warehouse_size**: `X-Small` | `Small` | `Medium` | `Large` (default: X-Small)
- **workload_mix**: Point lookup %, range scan %, insert %, update % (default: 50/50/0/0)
- **slo_targets**: Optional latency targets (P50/P95/P99) for result interpretation

## Output

1. **Test Configuration**: JSON config saved as template in Snowflake
2. **Test Execution**: Run ID with dashboard URL for live monitoring
3. **Analysis**: Natural language insights from Cortex Agent

## Workflow (Progressive Disclosure)

### Phase 1: Requirements Gathering
Interactively determine what the user wants to benchmark.

**See:** `workflows/01-requirements.md`

### Phase 1.5: Template Matching (MANDATORY)
**Before creating new templates, MUST search for existing ones that match:**
- **Exact match** (score >= 95): Same table, mode, scaling, workload
- **Close match** (score >= 70): Same table + mode, similar scaling
- **Partial match** (score >= 50): Same table, different configuration

**If matches found (score >= 50):** Present to user with options:
- Use existing template as-is
- Clone and modify an existing template
- Create new template from scratch
- View previous results from matching templates

**If NO matches found:** Explicitly state this to the user:
```
No existing templates match your requirements 
(searched for FIND_MAX_CONCURRENCY on tpch_sf100_orders).

Proceeding to create new templates.
```

**Why this matters:** This confirms you actually did the search, even when results are empty. Users want to know you checked.

**DO NOT skip this step.** Even if user provides detailed requirements, check for existing templates first.

**See:** `workflows/02-configuration.md` (Step 0)

### Phase 2: Configuration Generation
Generate test config JSON from gathered requirements.

**See:** `workflows/02-configuration.md`

### Phase 3: Test Execution
Submit tests via backend API and monitor progress.

**See:** `workflows/03-execution.md`

### Phase 4: Result Analysis
Hand off to Cortex Agent for AI-powered insights.

**See:** `workflows/04-analysis.md`

## Load Modes

### CONCURRENCY Mode
Fixed number of concurrent connections executing queries continuously.
- Use when: Measuring latency at a specific concurrency level
- Key metric: P50/P95/P99 latency at fixed load

### QPS Mode
Auto-scale workers to achieve a target queries-per-second.
- Use when: Testing if system can sustain a specific throughput
- Key metric: Achieved QPS, latency at target load

### FIND_MAX_CONCURRENCY Mode
Progressively increase concurrency to find maximum sustainable throughput.
- Use when: Capacity planning, finding system limits
- Key metric: Max QPS before latency degrades or errors occur

## Table Types

| Type | Description | Best For |
|------|-------------|----------|
| HYBRID | Snowflake hybrid tables with row-level indexes | OLTP, point lookups, mixed workloads |
| STANDARD | Traditional Snowflake tables | Analytics, batch processing, range scans |
| POSTGRES | Snowflake Postgres (preview) | Postgres-compatible workloads |
| INTERACTIVE | True Interactive Tables (requires Interactive WH) | Ultra-low latency HTAP |
| DYNAMIC | Dynamic Tables (materialized views) | Incremental transformations |

## API Endpoints Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/templates` | GET | List existing test templates |
| `/api/templates` | POST | Create new test template |
| `/api/runs` | POST | Create run from template |
| `/api/runs/{id}/preflight` | GET | Get pre-flight warnings |
| `/api/runs/{id}/start` | POST | Start test execution |
| `/api/runs/{id}/stop` | POST | Stop running test |
| `/api/tests/{id}/comparison-context` | GET | Get regression status + optimization hints (see below) |
| `/api/tests/compare/ai-analysis` | POST | AI comparison of two tests |
| `/api/tests/{id}/ai-analysis` | POST | AI analysis of single test |

## Test Comparison Context API

**Use this whenever asking about performance trends, regressions, or optimization opportunities.**

```bash
curl -sL "http://127.0.0.1:8000/api/tests/<test_id>/comparison-context?min_similarity=0.55"
```

This API aggregates SQL fingerprinting, statistical scoring, and historical lookups into one call. It returns:

1. **Direct Baselines** (`comparable_candidates`, `vs_previous`) - Same template runs for regression detection
2. **Cross-Template Matches** (`similar_candidates`) - Different templates with same SQL fingerprint for optimization hints

**Response Strategy:**
- If `vs_previous.verdict` = `"REGRESSED"` → warn immediately
- If `similar_candidates` shows better performance → offer "Pro Tip" about config differences

**See:** `workflows/04-analysis.md` for full documentation.

## Cortex Agent for Analysis

After tests complete, hand off to:
```
UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_ANALYST
```

Example analysis prompts:
- "Compare latency between HYBRID and STANDARD tables"
- "Which warehouse size gives best cost/performance ratio?"
- "Show throughput trends over the test duration"
- "What was the max QPS achieved before latency spiked?"

## Templates

Pre-built configuration templates for common scenarios:

- `templates/concurrency-test.json` - Fixed concurrency benchmark
- `templates/qps-test.json` - Target QPS benchmark  
- `templates/find-max-test.json` - Find maximum throughput

## Examples

- `examples/postgres-comparison.md` - Compare Postgres table across warehouse sizes

## Quick Start

1. **Start the wizard:**
   ```
   User: "Help me benchmark my hybrid table"
   ```

2. **Answer interactive questions:**
   - Table location (DATABASE.SCHEMA.TABLE)
   - What to measure (latency, throughput, max capacity)
   - Workload mix (reads vs writes)
   - Duration and concurrency

3. **Review generated config:**
   - Wizard shows JSON config summary
   - User approves or adjusts

4. **Execute and monitor:**
   - Test starts, dashboard URL provided
   - Real-time metrics available

5. **Analyze results:**
   - Hand off to Cortex Agent
   - Ask natural language questions about results

## Error Handling

| Error | Resolution |
|-------|------------|
| Backend not running | Start with `uv run python -m backend.main` |
| Table not found | Verify table exists and user has SELECT access |
| Connection failed | Check Snowflake connection in CoCo |
| Preflight warnings | Review warnings, proceed with caution or adjust config |

### Investigate Errors Before Retrying
**When a test fails, DO NOT blindly retry.** Investigate the root cause first.

Common failure patterns:

| Error | Root Cause | Fix |
|-------|------------|-----|
| `localhost:5432 connection refused` | Missing or wrong `connection_id` | Check `/api/connections`, ask user which to use |
| `Worker failure: stopped responding` | Connection issue | Check connection config, verify credentials |
| `database "X" does not exist` | Uppercase names in Postgres | Use lowercase for Postgres identifiers |
| `relation "X" does not exist` | Wrong schema or case | Verify table path, use lowercase |
| `STARTING` state stuck | Missing metadata preparation | Check if table needs value pool prep |

**Before retrying:**
1. Read the full error message
2. Check the run logs: `GET /api/runs/{id}/logs`
3. Identify the specific failure point
4. Fix the underlying issue
5. THEN retry

**Why this matters:** Blind retries waste time and often fail the same way. 5 minutes investigating saves 30 minutes of repeated failures.

## Critical Warnings

### NEVER Modify Database Without Permission (CRITICAL)
**The agent MUST NEVER execute any SQL that modifies the database without explicit user approval.**

This includes but is not limited to:
- `CREATE TABLE` / `CREATE OR REPLACE TABLE`
- `ALTER TABLE` / `ALTER WAREHOUSE`  
- `INSERT` / `UPDATE` / `DELETE`
- `DROP` anything
- Binding tables to warehouses

**If a test fails due to missing setup (e.g., table not bound to warehouse):**
1. STOP and explain the issue to the user
2. Show them the exact command needed
3. Ask: "Should I run this command? [Yes/No]"
4. Wait for explicit "Yes" before executing

**Example (CORRECT):**
```
The Interactive table is not bound to a warehouse. To fix this:

ALTER WAREHOUSE PERFTESTING_M_INTERACTIVE_1 ADD TABLES (UNISTORE_BENCHMARK.PUBLIC.TPCH_SF100_ORDERS_INT_STATIC)

Should I run this command? [Yes/No]
```

**DO NOT** just run the command and then apologize later.

### Don't Guess - Read the Code
When users ask technical questions about how the benchmark system works (e.g., "how do placeholders work?"), **DO NOT guess**. Instead:
1. Search the codebase for the relevant implementation
2. Read the actual code to understand the behavior
3. Then explain based on what you found

The backend has specific behaviors (like value pools, parameter binding) that are not obvious from general knowledge.

### SQL Generation
**ALWAYS use AI_ADJUST or Custom SQL** - never use default template SQL. The default templates won't match your table's actual column names and will fail. The skill should always:
1. Call `/api/templates/ai/adjust-sql` to generate SQL based on actual table schema, OR
2. Ask the user to provide custom SQL

### Postgres Column Case-Sensitivity
Postgres column names are **case-sensitive** and default to lowercase. When generating SQL for Postgres tables:
- Use lowercase column names: `o_orderkey` not `O_ORDERKEY`
- Never quote uppercase names: `"O_ORDERKEY"` will fail
- AI_ADJUST handles this correctly

**Database/schema/table names are ALSO case-sensitive:**
```sql
-- WRONG (uppercase - will fail)
SELECT * FROM UNISTORE_BENCHMARK.PUBLIC.ORDERS

-- CORRECT (lowercase)
SELECT * FROM unistore_benchmark.public.orders
```

**Common error:** `database "UNISTORE_BENCHMARK" does not exist`
This means you used uppercase. Postgres lowercases unquoted identifiers.

### PgBouncer Limitations
The `snowflake_admin` user **cannot be used** for testing when PgBouncer is enabled. Use a dedicated benchmark user (e.g., `benchmark_app`) that has:
- Direct connection capability
- SELECT permissions on target tables

### Sequential Test Execution
**Run tests ONE AT A TIME** - never in parallel. Multiple concurrent tests:
- Compete for warehouse resources
- Skew results and invalidate comparisons
- May exhaust connection pools

Always wait for one test to complete before starting the next.

### Template Matching is NOT Optional
**Before creating ANY new template:**
1. Fetch existing templates from `/api/templates/`
2. Score them against user requirements
3. Present matches (score >= 50) to user
4. Ask what they want to do

**DO NOT** fetch templates just to "check if backend is running" then create new ones.
**DO NOT** skip this step even if user provides detailed requirements.

### Examine Working Templates Before Creating New Ones
**Before creating a new template, examine at least one working template of the same type** to understand:
- Correct config structure
- Required fields
- SQL placeholder syntax (`$1` for Postgres, `?` for Snowflake)
- Connection and pooling configuration

```bash
# Get a working Postgres template to understand structure
curl -sL "http://127.0.0.1:8000/api/templates/" | jq '.[] | select(.config.table_type == "POSTGRES") | .config'
```

**Why this matters:** Config structures are complex and type-specific. Blind creation leads to failures and backtracking. 5 minutes examining a working template saves 30 minutes of debugging failures.

### Interactive Tables Require Matching Warehouses
Interactive Tables (Unistore) have TWO requirements:

1. **INTERACTIVE warehouse type** - not STANDARD
   - Check with: `SHOW WAREHOUSES LIKE '<name>'` (column 2 shows type)
   
2. **Table must be BOUND to the warehouse**
   - Error: "not bound to the current warehouse"
   - Fix: `ALTER WAREHOUSE <name> ADD TABLES (<table>)`
   - **NEVER run this without user permission** (see "NEVER Modify Database" above)

**How to detect Interactive Tables:**
```sql
SHOW INTERACTIVE TABLES IN SCHEMA <db>.<schema>
```

**Static vs Dynamic Interactive Tables:**
- Static (`CREATE INTERACTIVE TABLE ... WITH warehouse = WH`): Pre-bound at creation
- Dynamic (`CREATE INTERACTIVE TABLE ... AS SELECT`): Requires manual binding

### Cluster Key Alignment (Interactive Tables)
Interactive Tables have a **5-second query timeout**. Queries filtering on non-clustered columns will be slow or timeout.

**Check cluster key:**
```sql
SHOW INTERACTIVE TABLES LIKE '<table>' IN SCHEMA <db>.<schema>
-- Column 4 shows cluster_by, e.g., "(O_ORDERDATE, O_CUSTKEY)"
```

**If query column doesn't match cluster key, warn the user:**
```
⚠️ Point lookup uses 'O_ORDERKEY' but table is clustered on ['O_ORDERDATE', 'O_CUSTKEY'].
   Queries on non-clustered columns will be slow (5-second timeout).
```

See `workflows/02-configuration.md` → "Interactive Tables and Warehouse Binding" for full details.

### Scaling Rates for Interactive Warehouses
Interactive warehouses have limited concurrency capacity. Use conservative scaling:
- XS Interactive: `increment: 5, step: 45s`
- Standard warehouses can handle faster scaling

See `workflows/02-configuration.md` for detailed recommendations.

### FIND_MAX Tests Should Have At Least 5 Steps
A good FIND_MAX_CONCURRENCY test should show gradual degradation over **at least 5 steps** before hitting limits. If a test fails on the first or second increment:
- The increment is too aggressive
- Recommend smaller increment values

**Example:**
- Test jumped from 10→30 (+20) and immediately failed on P95 latency
- This is too aggressive - only got 2 data points
- Better: start=5, increment=5 → steps at 5, 10, 15, 20, 25, 30...

**For Interactive Tables specifically**, recommend:
- `start_concurrency: 5`
- `concurrency_increment: 5` (not 10 or 20)
- `step_duration_seconds: 30` (longer to stabilize)

### AI Analysis is MANDATORY for Results
**After tests complete, the agent MUST use the AI analysis endpoint** to interpret results. 

**⚠️ CRITICAL: Present the COMPLETE output from the AI analysis endpoint.**

Specifically:
- ❌ Do NOT skip or omit any sections (even if they say "data not available")
- ❌ Do NOT summarize or condense the output
- ❌ Do NOT replace the AI analysis with your own comparison table
- ✅ Present ALL sections from the AI analysis
- ✅ You MAY ADD additional insights after presenting the full AI output

**The AI analysis is the authoritative output.** You can augment it with additional context, but never reduce it.

**Why this matters:** You may think your comparison table is "easier to read" or that you're being "helpful" by improving the presentation. This is a trap. The AI analysis provides consistent methodology and catches patterns you might miss. Your "improvements" may omit important context.

**For comparing two tests:**
```bash
curl -sL -X POST "http://127.0.0.1:8000/api/tests/compare/ai-analysis" \
  -H "Content-Type: application/json" \
  -d '{
    "primary_id": "<run_id_1>",
    "secondary_id": "<run_id_2>",
    "question": "Compare performance of Postgres vs Interactive Tables"
  }'
```

**For single test analysis:**
```bash
curl -sL -X POST "http://127.0.0.1:8000/api/tests/<run_id>/ai-analysis" \
  -H "Content-Type: application/json" \
  -d '{"question": "What was the max sustainable throughput?"}'
```

The AI analysis provides:
- Deeper insights from the semantic view
- Consistent interpretation methodology
- Recommendations based on historical patterns

**DO NOT** skip AI analysis and just output a manual comparison table.

### Neutral Product Positioning (CRITICAL)
**When comparing Snowflake products, use neutral, factual language.**

Each product (Postgres, Interactive Tables, Hybrid Tables, Standard Tables) is optimized for different use cases. Present differences as trade-offs, not as one being "better" or "worse."

| ❌ AVOID | ✅ USE INSTEAD |
|----------|----------------|
| "additional overhead" | "different architecture optimized for X" |
| "slower" / "worse" | "higher latency at this concurrency level" |
| "limited capacity" | "optimized for lower-concurrency workloads" |
| "can't handle" | "designed for different workload patterns" |

**State the facts** (latency numbers, QPS, concurrency limits) and let users draw conclusions. Explain what each product is *optimized for* rather than what it's *bad at*.

### Results Summary MUST Include Test Identifiers
**When presenting results to the user, ALWAYS include:**

1. **Test Name** - The descriptive name of each test (e.g., "postgres-tpch-findmax", "interactive-orders-load")
2. **Run ID** - The UUID for each test run
3. **Dashboard URL** - `http://127.0.0.1:8000/dashboard/{run_id}`

**Example format:**
```
## Test Results

### Test 1: postgres-tpch-findmax
- **Run ID:** d1f890a0-2ac3-4115-8a95-20fc4345b43c
- **Dashboard:** http://127.0.0.1:8000/dashboard/d1f890a0-2ac3-4115-8a95-20fc4345b43c
- **Peak QPS:** 552.2
- **Max Concurrency:** 65 threads

### Test 2: interactive-orders-findmax  
- **Run ID:** 034894f4-9349-4761-81e6-4ab7ed4189ba
- **Dashboard:** http://127.0.0.1:8000/dashboard/034894f4-9349-4761-81e6-4ab7ed4189ba
- **Peak QPS:** 105.6
- **Max Concurrency:** 15 threads
```

**Why this matters:** Users need the test name and URL to:
- Reference specific tests in follow-up questions
- Share results with colleagues
- Access the dashboard for deeper analysis
- Track tests over time

### Postgres Does NOT Use Snowflake Warehouses
**⛔ CRITICAL: NEVER ask about warehouse for Postgres tests**

Postgres (Snowflake Postgres / PG-compatible endpoints) uses **direct connections**, NOT Snowflake warehouses.

| Database Type | Uses Warehouse? | Connection Method |
|---------------|-----------------|-------------------|
| STANDARD      | ✅ Yes          | Snowflake warehouse |
| HYBRID        | ✅ Yes          | Snowflake warehouse |
| INTERACTIVE   | ✅ Yes (INTERACTIVE type) | Snowflake warehouse |
| **POSTGRES**  | ❌ **NO**       | Direct via `connection_id` |

**WRONG:**
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

**You do NOT need:**
- Warehouse name
- Warehouse size
- Warehouse type

### Postgres Requires connection_id for Schema Introspection
**When using AI_ADJUST (adjust-sql) for Postgres tables, you MUST provide the connection_id.**

Without the connection_id, the backend cannot connect to the Postgres instance to introspect the table schema. It will fail with "Connection refused" (tries localhost:5432 by default).

**WRONG:**
```bash
curl -X POST "/api/templates/{id}/ai/adjust-sql" \
  -d '{"table_name": "unistore_benchmark.public.orders"}'
# Fails: Connection refused
```

**CORRECT:**
```bash
curl -X POST "/api/templates/{id}/ai/adjust-sql" \
  -d '{
    "table_name": "unistore_benchmark.public.orders",
    "connection_id": "f63ebd0d-44cc-426e-8506-1060583f3943"
  }'
```

### AI Adjust-SQL Requires Template ID First
**You must create a template BEFORE calling the adjust-sql endpoint.**

The workflow is:
1. Create template via `POST /api/templates/` (returns template_id)
2. Call `POST /api/templates/{template_id}/ai/adjust-sql` to generate SQL

**WRONG:**
```bash
# Trying to call adjust-sql without a template
curl -X POST "/api/templates/ai/adjust-sql" \
  -d '{"table_name": "..."}'
# Fails: endpoint doesn't exist
```

**CORRECT:**
```bash
# Step 1: Create template first
curl -X POST "/api/templates/" \
  -d '{"name": "my-test", "config": {...}}' 
# Returns: {"template_id": "abc123"}

# Step 2: Now call adjust-sql with template ID
curl -X POST "/api/templates/abc123/ai/adjust-sql" \
  -d '{"table_name": "...", "connection_id": "..."}'
```

## Self-Check Before Presenting Final Results

**Answer these questions with EVIDENCE, not checkmarks:**

### Gate 1 Evidence
- Did I call `ask_user_question`? If yes, what did user say? "[quote response]"
- If I wrote "per original request" or "implicit approval" → I VIOLATED the protocol

### Gate 2 Evidence  
- Did I check `ai_workload.pool_id` for existing templates? Value was: [uuid or null]
- Did I run `SHOW INTERACTIVE TABLES`? Cluster key was: [value]
- Did I call `ask_user_question` for SQL approval? User said: "[quote response]"

### Gate 3 Evidence
- Did I verify run config matches request? Requested [X%], actual was [Y%]
- Did I call `ask_user_question` before starting? User said: "[quote response]"

### Gate 4 Evidence
- Did workload match? Requested [X%], actual [Y%] - if mismatch, did I tell user?
- Did I investigate failures before retrying? Root cause was: [description or N/A]

### Violations to Acknowledge
If you cannot fill in quotes above, you skipped something. List what you skipped:
- [e.g., "I marked Gate 1 as confirmed without calling ask_user_question"]
- [e.g., "I didn't verify pool_id before using template"]
- [e.g., "Workload was 95/5 instead of 100/0 and I didn't tell the user"]

**Honesty about violations is better than pretending you followed the protocol.**

## Related Skills

- **doc-reviewer** - Review benchmark documentation
- **plan-reviewer** - Review benchmark execution plans
