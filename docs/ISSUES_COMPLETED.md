# Completed Issues

## ISSUE-001: Worker Details chart empty during live dashboard runs

| Field | Details |
|---|---|
| **ID** | ISSUE-001 |
| **Title** | Worker Details chart empty during live dashboard runs |
| **Date Reported** | 2026-03-13 |
| **Date Resolved** | 2026-03-13 |
| **Status** | Resolved |
| **Severity** | Medium |
| **Component** | backend/templates/pages/dashboard.html |
| **Environment** | Production (https://mxp7lf-sfsenorthamerica-rgoldin-aws1.snowflakecomputing.app/) |

### Symptoms
- Clicking a worker card on the live dashboard opened a "Worker Details" panel with an empty chart
- API returned `{available: false, workers: []}` because `WORKER_METRICS_SNAPSHOTS` table is empty during live runs
- Empty results were cached for 300 seconds, compounding the problem

### Root Cause
`FileBasedMetricsLogger` defers writing to `WORKER_METRICS_SNAPSHOTS` until the PROCESSING phase (after benchmark completes) via Parquet bulk load. During a live run, the table has zero rows for the current test. The Worker Details panel queried this empty table via `GET /api/tests/{testId}/worker-metrics` and displayed nothing. Additionally, the `_worker_metrics_cache` (TTL=300s) cached empty results, preventing fresh data from being served even after bulk load completed.

### Evidence
- Direct API call to `/api/tests/f84d8da8-ee39-4f9a-82bc-4ed6a15781fb/worker-metrics?nocache=true` returned `{available: false, workers: []}`
- `backend/core/file_metrics_logger.py` lines 13-14 confirm deferred bulk load design
- `backend/api/routes/test_results.py` line 83: `_worker_metrics_cache = _TTLCache(ttl_seconds=300, max_size=100)`

### Resolution
Removed the Worker Details click-to-expand functionality from the live dashboard since per-worker snapshot data is not available until after PROCESSING phase. The history dashboard retains full worker details functionality. Changes to `backend/templates/pages/dashboard.html`:
1. Removed "Click a worker to load per-worker snapshots." from Workers card subtitle
2. Changed worker cards from `<button>` to `<div>`, removing `@click="toggleLiveWorker(worker)"` handler and expanded styling
3. Removed the entire Worker Details card (snapshot chart, KPIs, detail table)

### Regression Test
- **Check:** Live dashboard worker cards display without click-to-expand behavior; history dashboard worker details still function
- **Command:** Navigate to live dashboard during a running test, verify worker cards are non-clickable divs. Then navigate to history dashboard for a completed test, click a worker, verify details panel opens with chart data.
- **Expected:** Live dashboard shows worker cards as read-only status indicators. History dashboard shows clickable workers with full Worker Details panel including chart, KPIs, and snapshot table.

### Notes
- Related data flow: WebSocket `liveWorkers` array provides real-time point-in-time metrics (QPS, errors, connections) for worker cards -- this still works
- The `loadLiveWorkerMetrics()` and `toggleLiveWorker()` functions in `data-loading.js` are now dead code for live mode but remain for potential future use
- The `_worker_metrics_cache` (300s TTL) issue in the API endpoint remains but is now irrelevant for live dashboard since it no longer queries that endpoint

---

## ISSUE-004: Table setup failure reports generic message, hiding the real cause

| Field | Details |
|---|---|
| **ID** | ISSUE-004 |
| **Title** | Table setup failure reports generic message, hiding the real cause |
| **Date Reported** | 2026-09-01 |
| **Date Resolved** | 2026-09-01 |
| **Status** | Resolved |
| **Severity** | Medium |
| **Component** | backend/core/table_managers/base.py, standard.py, hybrid.py, postgres.py, backend/core/test_executor.py |
| **Environment** | SPCS (mxp7lf-sfsenorthamerica-rgoldin-aws1.snowflakecomputing.app) |

### Symptoms
- Starting an Interactive Tables test failed with the toast:
  `Test failed: Worker failure: 1 worker(s) stopped responding. Error: Failed to setup table TPCH_SF100_ORDERS_INT_STATIC`
- The message gives no indication *why* setup failed, so a suspended interactive
  warehouse looked like the likely cause and was investigated first.
- Actual cause: the configured table did not exist. The existing interactive
  table is `TPCH_SF100_ORDERS_INT`; there is no `_STATIC` variant, and no
  FlakeBench code generates that suffix (it came from the test configuration).

### Root Cause
Two defects in the same code path:

1. `TableManager.setup()` (base.py) returned a bare `False` for three distinct
   failure modes — object missing, schema mismatch, and driver exception — and
   `test_executor.py` rendered all of them as `Failed to setup table {name}`.
   The specific reason was written to the log only, which is not visible from
   the dashboard.
2. `table_exists()` in `standard.py`, `hybrid.py`, and `postgres.py` caught every
   exception, logged at `debug` level, and returned `False`. A permission error
   or connectivity failure was therefore indistinguishable from a genuinely
   absent object, and the underlying error was discarded entirely.

### Evidence
- `SHOW TABLES LIKE 'TPCH_SF100_ORDERS_INT_STATIC' IN SCHEMA UNISTORE_BENCHMARK.PUBLIC` → 0 rows.
- `SELECT TABLE_NAME, TABLE_TYPE FROM UNISTORE_BENCHMARK.INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME ILIKE '%ORDERS%'`
  → `TPCH_SF100_ORDERS`, `_HYBRID`, `_INT` (INTERACTIVE TABLE), `_SO`. No `_STATIC`.
- `SHOW WAREHOUSES LIKE 'PERFTESTING_M_INTERACTIVE_1'` → `SUSPENDED`, `auto_resume=false`.
  Ruled out as the cause: `test_executor.py` explicitly issues `ALTER WAREHOUSE … RESUME`
  for Interactive/Hybrid tables and emits a *different* error
  (`Failed to resume suspended warehouse …`) when that fails.
- `grep -rn "_STATIC" --include='*.py' --include='*.html'` → no application source matches.

### Resolution
- Added `TableManager.setup_error` and `_classify_setup_exception()` to `base.py`.
  `setup()` now records a distinct, actionable reason for each failure mode:
  missing object, schema mismatch, not-authorized, no-warehouse, and other.
- Added `TableManager._record_exists_error()`; the three `table_exists()`
  implementations now record the swallowed exception instead of discarding it, so
  a failed *lookup* is no longer reported as a missing *object*.
- Added `TestExecutor._describe_setup_failure()`, which prefers the manager's
  specific reason and falls back to the old generic text only when none exists.
- The originally reported failure now surfaces as:
  `Table setup failed: UNISTORE_BENCHMARK.PUBLIC.TPCH_SF100_ORDERS_INT_STATIC does not exist (or the current role cannot see it). FlakeBench never creates tables — check the name in your test configuration, or create the object first.`
- Configuration fix for the user's test: point the dashboard at
  `UNISTORE_BENCHMARK.PUBLIC.TPCH_SF100_ORDERS_INT`.

### Regression Test
- **Check:** `setup()` produces a distinct, specific `setup_error` for each failure mode,
  and `TestExecutor._describe_setup_failure()` prefers it over the generic text
- **Command:** `uv run pytest tests/test_table_setup_errors.py -q`
- **Expected:** 7 passed. Covers absent object, not-authorized, no-warehouse,
  generic error, all-messages-distinct, executor prefers reason, executor fallback.
- **Check:** no new lint findings from this change
- **Command:** `uvx ruff check --output-format=concise backend/core/table_managers/base.py tests/test_table_setup_errors.py`
- **Expected:** `tests/test_table_setup_errors.py` clean; `base.py` reports only
  the pre-existing `I001` / `PIE790` / `BLE001` findings that predate this fix.

### Notes
- Interactive tables *are* returned by `SHOW TABLES` (with `is_interactive=Y`),
  so `table_exists()` correctly finds them; the miss was purely the wrong name.
- `PERFTESTING_M_INTERACTIVE_1` has `auto_resume=false`, so anything bypassing
  the executor's explicit RESUME will fail against it. Not a defect, but worth
  knowing when testing manually.
- Related follow-up filed as ISSUE-005: the connection pool returns `[]` on
  network failure, which can still make a present table look absent.
