# Open Issues

## ISSUE-002: Debug alignment text visible in Deep Compare UI

| Field | Details |
|---|---|
| **ID** | ISSUE-002 |
| **Title** | Debug alignment text visible in Deep Compare UI |
| **Date Reported** | 2026-03-20 |
| **Status** | Open |
| **Severity** | Low |
| **Component** | backend/templates/pages/history_compare.html |
| **Environment** | Production (https://m2p7lf-sfsenorthamerica-rgoldin-aws1.snowflakecomputing.app/) |
| **WI** | WI-23 |

### Symptoms
- Debug alignment info rendered visibly in the floating toolbar area on `/history/compare`
- Text reads: "toggles: warmup=off align=wall_clock / primary: warmup=30.101s offset=0.000s max=239.3s projected=239.3s / secondary: warmup=29.051s offset=0.000s max=305.5s projected=305.5s"
- Styled as monospace 0.7rem — clearly developer debug output not intended for end users

### Root Cause
Three `<div x-text="...">` elements at `history_compare.html:75-79` render `getDebugLineToggles()`, `getDebugLinePrimary()`, and `getDebugLineSecondary()` unconditionally. No visibility gate or toggle exists.

### Resolution Plan
Wrap the debug div in a `<details>` element so it's collapsed by default but accessible for debugging.

---

## ISSUE-003: Detailed Latency Breakdown shows empty data on Deep Compare page

| Field | Details |
|---|---|
| **ID** | ISSUE-003 |
| **Title** | Detailed Latency Breakdown shows empty data on Deep Compare page |
| **Date Reported** | 2026-03-20 |
| **Status** | Open |
| **Severity** | Medium |
| **Component** | backend/api/routes/test_results.py, sql/schema/chart_procedures.sql |
| **Environment** | Production (https://m2p7lf-sfsenorthamerica-rgoldin-aws1.snowflakecomputing.app/) |
| **WI** | WI-23 |

### Symptoms
- "Detailed Latency Breakdown" section on `/history/compare` shows all dashes (— / —)
- Read Operations, Write Operations, and per-query-type table all empty
- Affects both primary and secondary test runs

### Root Cause
The `GET_LATENCY_BREAKDOWN` stored procedure was defined in `sql/schema/chart_procedures.sql` but **never deployed** to `FLAKEBENCH.TEST_RESULTS`. The API endpoint (`_call_sp(pool, "GET_LATENCY_BREAKDOWN", test_id)`) called a non-existent SP, received an error, and `_call_sp` returned `{}`. The UI rendered empty data (all dashes) because all fields were null/undefined.

The underlying query data is present — child tests have 339K and 480K qualifying rows respectively.

### Resolution
Deployed `GET_LATENCY_BREAKDOWN` SP to `FLAKEBENCH.TEST_RESULTS` schema. Verified SP returns correct data (339K read operations for primary test, 480K for secondary).

---

## ISSUE-005: Connection pool returns empty list on network error, masking failures as empty results

| Field | Details |
|---|---|
| **ID** | ISSUE-005 |
| **Title** | Connection pool returns empty list on network error, masking failures as empty results |
| **Date Reported** | 2026-09-01 |
| **Date Resolved** | N/A |
| **Status** | Open |
| **Severity** | Medium |
| **Component** | backend/connectors/snowflake_pool.py:602-604 |
| **Environment** | Local + SPCS |

### Symptoms
- A query that fails with a network/database error returns `[]` to the caller
  instead of raising, so callers cannot tell "no rows" from "query never ran".
- Observed while verifying ISSUE-004: with an expired PAT,
  `SHOW TABLES LIKE 'TPCH_SF100_ORDERS_INT' IN UNISTORE_BENCHMARK.PUBLIC`
  returned `[]` even though the table demonstrably exists. `table_exists()`
  therefore reported the table as absent.

### Root Cause
`SnowflakePool.execute_query()` catches `ReadTimeout`, `DatabaseError`, and
`OperationalError`, logs at error level, and returns `[]` (line 602-604). The
error is not propagated or attached to the result, so an existence check built on
a `SHOW` statement silently degrades to a false negative. Note that the sibling
method at line 726-733 does better — it returns `[], {"error": str(e)}` — so the
pattern for fixing this already exists in the file.

### Evidence
- `backend/connectors/snowflake_pool.py:602-604` — `return []` in the except block.
- Repro with an expired PAT:
  ```
  ERROR:backend.connectors.snowflake_pool:Network error during query execution:
    250001 (08001): ... Programmatic access token is invalid.
  SHOW TABLES LIKE 'TPCH_SF100_ORDERS_INT' IN UNISTORE_BENCHMARK.PUBLIC -> []
  ```
  while the same statement run with valid credentials returns 1 row
  (`is_interactive=Y`).

### Resolution
Not yet fixed. ISSUE-004 mitigated the *visible* symptom for setup errors by
recording exceptions that reach `table_exists()`, but errors swallowed at the
pool layer never reach it, so a connectivity failure can still be reported as a
missing table.

Proposed: either let `execute_query()` raise, or mirror the line 726-733 pattern
so callers receive the error alongside the (empty) rows. Existence checks must
treat "error" as indeterminate, not as absent.

### Regression Test
- **Check:** a pool-level network error does not present as an empty result set
- **Command:** `uv run pytest tests/test_connection_pools.py -q` (extend with a
  case that stubs the driver to raise `OperationalError` and asserts the caller
  can distinguish it from zero rows)
- **Expected:** caller observes an error, not `[]`

### Notes
- Discovered while validating ISSUE-004; the two share the `table_exists()` path.
- Any fix must audit callers of `execute_query()` that currently rely on `[]`
  being returned on failure rather than an exception propagating.
