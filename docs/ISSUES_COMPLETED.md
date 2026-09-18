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

---

## ISSUE-006: Toast close button barely visible and pushed outside the card on long messages

| Field | Details |
|---|---|
| **ID** | ISSUE-006 |
| **Title** | Toast close button barely visible and pushed outside the card on long messages |
| **Date Reported** | 2026-09-01 |
| **Date Resolved** | 2026-09-01 |
| **Status** | Resolved |
| **Severity** | Medium |
| **Component** | backend/static/css/input.css (`.toast__close`, `.toast__content`) |
| **Environment** | SPCS (mxp7lf-sfsenorthamerica-rgoldin-aws1.snowflakecomputing.app) |

### Symptoms
- The "×" dismiss button on toast notifications was barely visible on the right side.
- On the long error toast from ISSUE-004, the button was pushed **completely outside**
  the card and was effectively unreachable.
- Severity is raised by `toast.js` `durationFor()`: error and warning toasts return
  `null` (sticky, never auto-dismiss), so the × is the *only* way to clear them.

### Root Cause
Two separate defects:

1. **Low contrast / tiny target.** `.toast__close` was styled
   `text-gray-900/70 text-xl leading-none p-0` with no width or height, giving a
   faint glyph and roughly a 20px hit area with no hover affordance.
2. **Flex overflow (the "invisible" case).** `.toast__content` was `flex-1` with no
   `min-width: 0`. A flex item's default `min-width: auto` refuses to shrink below its
   content's intrinsic minimum, and the unbreakable token
   `UNISTORE_BENCHMARK.PUBLIC.TPCH_SF100_ORDERS_INT_STATIC` made that minimum wider
   than the available column — so the content box pushed `.toast__close` past the
   card's right edge. `break-words` alone does not help, because the overflow happens
   during flex sizing, before wrapping is considered.

### Evidence
Measured in a browser against the compiled CSS, before the fix:

| Toast | Close btn x-range | Card right edge | Result |
|---|---|---|---|
| error (long message) | 648–676 | 652 | **overflowed by 24px** |
| success (short) | 611–639 | 652 | inside (13px inset) |
| confirm (dark) | 611–639 | 652 | inside (13px inset) |

Hovering the overflowed button scrolled the container horizontally and clipped the
left edge of every line of the message text.

After the fix, all three toasts measure identically — button 611–639 inside a card
ending at 652 (13px inset), and for the error toast `content.right` = 599 vs
`close.left` = 611, a 12px gap with no overlap. Computed
`.toast__content { min-width: 0px }` and `.toast__close { flex-shrink: 0 }`.

### Resolution
In `backend/static/css/input.css`:
- `.toast__content` — added `min-w-0` so the flex item can shrink and long tokens
  wrap inside the card instead of forcing the button out.
- `.toast__close` — added `shrink-0`, `self-start`, an explicit `h-7 w-7` grid-centred
  box, `-mr-1` optical inset, `text-gray-900` (full contrast, up from `/70`),
  `text-2xl`, a `hover:bg-gray-900/10` rounded affordance, and a
  `focus-visible:ring-2` for keyboard users.
- `.toast--confirm .toast__close` — raised to full `text-gray-50` with a
  `hover:bg-white/15` and a light focus ring for the dark variant.
- Rebuilt the compiled stylesheet with `task css:build`.

### Regression Test
- **Check:** the close button stays inside the card even with an unbreakable long token
- **Command:** render a `.toast--error` whose message contains
  `UNISTORE_BENCHMARK.PUBLIC.TPCH_SF100_ORDERS_INT_STATIC`, then in the browser console:
  ```js
  const t = document.querySelector('.toast--error');
  const c = t.querySelector('.toast__content').getBoundingClientRect();
  const x = t.querySelector('.toast__close').getBoundingClientRect();
  console.log(c.right <= x.left, x.right <= t.getBoundingClientRect().right);
  ```
- **Expected:** `true true` — content does not reach the button, button does not exit the card
- **Check:** compiled CSS contains the fix (editing `input.css` alone changes nothing)
- **Command:** `grep -o '\.toast__content{[^}]*}' backend/static/css/tailwind.css`
- **Expected:** includes `min-width:0`

### Notes
- `backend/static/css/tailwind.css` is **gitignored** but IS baked into the image via
  `COPY backend/ ./backend/` (no `.dockerignore` exclusion). You must run
  `task css:build` before `docker build`, or the container ships stale CSS.
- A mojibake `Ã—` seen during testing was an artifact of the bare `python -m http.server`
  harness, not a product bug — `base.html` has `<meta charset="UTF-8">`.
- Separately repaired: `.venv/bin/tailwindcss` had a dangling shebang pointing at
  `/Users/rgoldin/Programming/unistore_performance_analysis/.venv/bin/python3`, which no
  longer exists, so `task css:build` failed with "Failed to spawn: tailwindcss". Fixed by
  `uv pip install --force-reinstall pytailwindcss` (0.3.0 → 0.3.1). Guarded permanently by
  a new internal `css:ensure-tailwind` Taskfile task that all three `css:*` tasks depend
  on: it probes `uv run tailwindcss --help` and force-reinstalls only when the probe fails.
- Deployed to SPCS 2026-09-04: image digest
  `sha256:36be9e40a09c9285c5f5c35f21ddb355a6e22e1a5c33e176933aeebe2074c063`,
  container start 2026-09-04T17:00:25Z. Registry push initially failed `UNAUTHORIZED`
  because the Docker registry token had expired — `snow spcs image-registry login -c default`
  resolves it (the `snow` CLI connection itself was fine).

## ISSUE-007: Template save accepts SQL whose shape does not match its query kind

| Field | Details |
|---|---|
| **ID** | ISSUE-007 |
| **Title** | Template save accepts SQL whose shape does not match its query kind |
| **Date Reported** | 2026-09-15 |
| **Date Resolved** | 2026-09-15 |
| **Status** | Resolved |
| **Severity** | High |
| **Component** | `backend/api/routes/templates_modules/config_normalizer.py` |
| **Environment** | Local + SPCS |

### Symptoms
- A benchmark run against `UNISTORE_BENCHMARK.PUBLIC.TPCH_SF100_ORDERS_INT`
  failed every POINT_LOOKUP query during warmup with
  `002049 (42601): SQL compilation error: Bind variable ? not set.`
- The failure repeated once per query rather than aborting the run.

### Root Cause
Save-time validation checked SQL *presence* only, never *shape*.
`config_normalizer.py:150-158` required non-empty SQL when a weight exceeded
zero and nothing more.

POINT_LOOKUP and RANGE_SCAN are fixed-arity kinds. `test_executor.py:3999-4001`
binds exactly one parameter for POINT_LOOKUP with no placeholder count at all:

```python
elif query_kind == "POINT_LOOKUP":
    target_id = _choose_id()
    params = [target_id]
```

`RANGE_SCAN` (`test_executor.py:4004-4046`) counts placeholders but its `else`
branch hardcodes two. The saved point-lookup SQL had three placeholders
(`WHERE "O_ORDERDATE" = ? AND "O_CUSTKEY" BETWEEN ? AND ? + 2399`), so one value
was bound and the driver rejected the statement.

### Evidence
- `SQL_ERROR_SAMPLE` log line: `"params": {"count": 1, "items": ["265997249"]}`
  against a three-placeholder query.
- The bound value was an `O_ORDERKEY`-magnitude integer headed for an
  `O_ORDERDATE` predicate, confirming the single shared key pool.
- Audit of all 44 saved template SQL fields: zero would be rejected by the new
  rules, so no existing template needed migration.

### Resolution
Added `backend/api/routes/templates_modules/sql_shape.py` with
`count_placeholders()` and `validate_query_shape()`, enforcing:

| Kind | Placeholders | Predicate |
|---|---|---|
| POINT_LOOKUP | exactly 1 | equality bound to the placeholder, no range operator |
| RANGE_SCAN | 1 or 2 | at least one range predicate |

Comments and single-quoted literals are stripped before inspection so a literal
containing `?` cannot inflate the count and a comment mentioning `BETWEEN`
cannot trigger a false match. Wired into `config_normalizer.py` (gated on
`pct > 0`, so unused zero-weight fields cannot block a save) and mirrored as a
client-side hard block in `configure.html` `_saveTemplate`. Error messages name
the offending construct, point at the correct field, and point at Generic SQL as
the escape hatch for arbitrary placeholder counts.

### Regression Test
- **Check:** mismatched SQL cannot be saved, and all shipped defaults still can
- **Command:** `uv run pytest tests/test_sql_shape.py -q`
- **Expected:** 38 passed. Cases live in `tests/fixtures/query_shape_cases.json`.

### Notes
- The executor's fixed arities were deliberately left unchanged. Arbitrary
  placeholder counts with per-placeholder types belong to GENERIC_SQL, which has
  its own spec mechanism at `test_executor.py:3766-3970`.
- Related open **ISSUE-005**: the underlying SQL compilation error was reported
  as `Network error during query execution` by `snowflake_pool`, which slowed
  triage. Not fixed here.
- The JS mirror in `configure.html` duplicates the Python regexes, following the
  existing `// Match server validation:` convention. Keep both in sync with the
  shared fixture.

## ISSUE-008: Config validation errors surface as a generic 500, losing the message

| Field | Details |
|---|---|
| **ID** | ISSUE-008 |
| **Title** | Config validation errors surface as a generic 500, losing the message |
| **Date Reported** | 2026-09-15 |
| **Date Resolved** | 2026-09-15 |
| **Status** | Resolved |
| **Severity** | High |
| **Component** | `backend/api/routes/templates.py` |
| **Environment** | Local + SPCS |

### Symptoms
- Saving a template with an invalid config returned
  `500 INTERNAL_ERROR: "create template failed."`
- The specific, user-actionable validation message was never shown.

### Root Cause
`_normalize_template_config` raises `ValueError`. Both save paths caught bare
`Exception` and routed through `http_exception`
(`backend/api/error_handling.py:74`), which has no `ValueError` branch and falls
through to a 500 at `:115-118`. Every config validation message was discarded,
including the pre-existing weights-must-sum-to-100 error.

### Evidence
- `templates.py:1899-1900` (create) and `:1987-1988` (update) both ended in
  `except Exception as e: raise http_exception(...)`.
- No `ValueError` exception handler exists in `backend/main.py`.

### Resolution
Added an explicit `except ValueError` branch ahead of the bare `except Exception`
in both `create_template` and `_update_template_internal`, raising
`HTTPException(400, detail={"error": "invalid_config", "message": str(e)})`.
This matches the existing structured-400 pattern from
`_check_pgbouncer_requirements` (`templates.py:1765-1776`), and the client
already extracts `detail.message` at `configure.html:3525`.

### Regression Test
- **Check:** invalid config returns 400 with the specific message, not a 500
- **Command:** `uv run pytest tests/test_sql_shape.py -k "returns_400 or weight_sum" -q`
- **Expected:** 3 passed, including the un-swallowed `sum to 100.00` message

### Notes
- This was a prerequisite for ISSUE-007: without it the new server-side shape
  messages would have been invisible.

## ISSUE-009: create_template re-wraps deliberate HTTPExceptions as 500

| Field | Details |
|---|---|
| **ID** | ISSUE-009 |
| **Title** | create_template re-wraps deliberate HTTPExceptions as 500 |
| **Date Reported** | 2026-09-15 |
| **Date Resolved** | 2026-09-15 |
| **Status** | Resolved |
| **Severity** | Medium |
| **Component** | `backend/api/routes/templates.py:1899` |
| **Environment** | Local + SPCS |

### Symptoms
- Deliberate 400 responses raised inside `create_template` were returned to the
  client as 500 `INTERNAL_ERROR`.

### Root Cause
`create_template` caught bare `Exception` without the `except HTTPException:
raise` guard that `_update_template_internal` has at `templates.py:1985-1986`.
Because `HTTPException` subclasses `Exception`, any intentional status code
raised inside the `try` block was swallowed and re-wrapped.

### Evidence
- The pre-existing PgBouncer 400s from `_check_pgbouncer_requirements`
  (`templates.py:1765-1776`, `:1793-1805`) were already affected on the create
  path, while the update path handled them correctly.

### Resolution
Added `except HTTPException: raise` as the first handler in `create_template`,
matching the update path.

### Regression Test
- **Check:** a deliberate 400 from within create_template reaches the client
- **Command:** `uv run pytest tests/test_sql_shape.py::test_create_template_returns_400_with_message -q`
- **Expected:** 1 passed, `status_code == 400`

### Notes
- Found while implementing ISSUE-008; independent of it, since it affects any
  intentional status code, not just `ValueError`-derived ones.

> Continued in ISSUES_COMPLETED-2.md
