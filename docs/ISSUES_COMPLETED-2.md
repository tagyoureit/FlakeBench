# Completed Issues (continued)

> Continued from ISSUES_COMPLETED.md, which reached the 500-line cap.

## ISSUE-010: Quoted identifiers break GENERIC_SQL placeholder column extraction

| Field | Details |
|---|---|
| **ID** | ISSUE-010 |
| **Title** | Quoted identifiers break GENERIC_SQL placeholder column extraction |
| **Date Reported** | 2026-09-15 |
| **Date Resolved** | 2026-09-15 |
| **Status** | Resolved |
| **Severity** | High |
| **Component** | `backend/api/routes/templates.py` (`_extract_placeholder_columns`) |
| **Environment** | Local + SPCS |

### Symptoms
- A run with a GENERIC_SQL entry failed at warmup for every query with
  `ValueError: GENERIC_SQL query has placeholders but no parameters configuration`
  (`test_executor.py:3773`).
- The saved template had `"parameters":[]` despite SQL containing three `?`.
- "Update Table Metadata" reported success, giving no indication anything was
  wrong.

### Root Cause
`/ai/prepare` auto-generates the `parameters` specs: it calls
`_extract_placeholder_columns(sql)` to map each `?` to its column, samples those
columns into `TEMPLATE_VALUE_POOLS` under `POOL_KIND='GENERIC_SQL'`, synthesizes
one `sample_from_table` spec per placeholder, and writes them back into the
template config. The mechanism is complete and correct.

The extraction regex could not match a double-quoted identifier:

```python
col_pattern = r'(?:[\w]+\.)?(\w+)\s*(=|>|<|>=|<=|!=|<>|BETWEEN|IN|LIKE)\s*'
```

After `\w+` consumes `O_ORDERDATE` the next character is the closing `"`, which
matches neither `\s*` nor any operator. Zero columns extracted, so zero specs
generated, so `parameters` stayed `[]`.

Quoted identifiers are the house style for generated SQL, so any generic query
written the way the app itself writes SQL silently produced no parameters.

A second latent defect in the same pattern: the operator alternation put `>` and
`<` before `>=` and `<=`. Because regex alternation is leftmost-first, `col >= ?`
matched operator `>`, leaving `= ?` as the remainder, which does not start with
`?` — so `>=` and `<=` placeholders were dropped even on unquoted SQL.

### Evidence
Measured against the exact failing SQL before the fix:

```
placeholders in sql: 3
QUOTED   -> []
UNQUOTED -> [(O_ORDERDATE, =), (O_CUSTKEY, BETWEEN_START), (O_CUSTKEY, BETWEEN_END)]
```

### Resolution
Rewrote the identifier portion of the pattern to accept bare, `"quoted"` and
`[bracketed]` names (including a qualified `alias."Col"` prefix), stripped the
quoting from the captured name, and reordered the operator alternation so
multi-character operators precede their single-character prefixes. All nine
identifier and operator forms now extract every placeholder.

### Regression Test
- **Check:** every placeholder resolves to a column for all identifier styles
- **Command:** `uv run pytest tests/test_sql_shape.py -k extract -q`
- **Expected:** 10 passed, including quoted multi-line house-style SQL and
  `>=` / `<=` / `<>`

### Notes
- `parameters` is generated, never hand-authored. A manual JSON editor was
  prototyped and deliberately reverted — it contradicted the design.
- Consequence for save-time validation: `/ai/prepare` is
  `POST /{template_id}/ai/prepare` and needs an already-saved template, so an
  empty `parameters` is the legitimate pre-prepare state. Rejecting it on save
  would deadlock every new generic entry. `config_normalizer` therefore rejects
  only a *non-empty* list whose count disagrees with the placeholder count.
- Shortcut kinds (POINT_LOOKUP/RANGE_SCAN) never call this extractor, so they
  were unaffected.

## ISSUE-011: prepare reports success when placeholders yield no parameters

| Field | Details |
|---|---|
| **ID** | ISSUE-011 |
| **Title** | prepare reports success when placeholders yield no parameters |
| **Date Reported** | 2026-09-15 |
| **Date Resolved** | 2026-09-15 |
| **Status** | Resolved |
| **Severity** | Medium |
| **Component** | `backend/api/routes/templates.py` (`prepare_ai_template`) |
| **Environment** | Local + SPCS |

### Symptoms
- "Update Table Metadata" showed "Table metadata updated successfully" while
  leaving `parameters` empty or short.
- The failure only appeared later, at run warmup, as a parameter count mismatch
  or "no parameters configuration".

### Root Cause
Three silent `continue` paths in the generic-query loop:
`if not placeholder_cols: continue` when extraction found nothing, a skip when a
column could not be resolved against the main or joined tables, and a skip when
the sampling INSERT failed. Specs were then persisted only `if params_config:`,
so both "none" and "partial" outcomes were indistinguishable from success.

### Evidence
- ISSUE-010 produced exactly this: extraction returned `[]`, prepare succeeded,
  and the run failed at warmup with no prior warning.

### Resolution
Added a `generic_param_warnings` collector covering all three cases — no columns
identified, a partial spec count, and no sampleable columns — returned via the
existing `AiPrepareResponse.warnings` field. `updateTableMetadata()` now raises a
warning toast carrying those messages instead of an unconditional success toast.

### Regression Test
- **Check:** prepare warns rather than silently succeeding when a placeholder
  cannot be mapped
- **Command:** paste a generic query whose predicate uses an unsupported form
  (e.g. a function call around the column), click Update Table Metadata
- **Expected:** warning toast naming the entry and its placeholder count; no
  success toast
- **Note:** not covered by unit tests — the prepare endpoint needs live
  Snowflake sampling. Verify manually.

### Notes
- The app's own Snowflake pool currently fails with an invalid PAT
  (`250001 08001`), so prepare cannot be exercised locally without fresh
  credentials.

## ISSUE-012: Interactive warehouses displayed a fabricated "Gen 1" generation

| Field | Details |
|---|---|
| **ID** | ISSUE-012 |
| **Title** | Interactive warehouses displayed a fabricated "Gen 1" generation |
| **Date Reported** | 2026-09-16 |
| **Date Resolved** | 2026-09-16 |
| **Status** | Resolved |
| **Severity** | High |
| **Component** | `backend/api/routes/warehouses.py`, `backend/static/js/dashboard/display.js`, `backend/templates/pages/configure.html` |
| **Environment** | Local + SPCS |

### Symptoms
- The Configure page warehouse dropdown rendered
  `PERFTESTING_M_INTERACTIVE_1 (Gen1, Medium)`.
- The Warehouse Details panel asserted `Generation: Gen 1` and
  `Query Acceleration Service (QAS): Disabled` for the same warehouse.
- Both values are invented. Snowflake reports neither for interactive warehouses.

### Root Cause
Two independent defaults collapsed a "no value" into a positive claim:

1. `_parse_warehouse_row` had only two branches — adaptive and "everything else".
   Interactive warehouses fell into the standard branch, which reads
   `resource_constraint` (col 32) and the QAS columns (22/23).
2. The frontend then treated a falsy `resource_constraint` as Gen1:
   `wh.resource_constraint === 'STANDARD_GEN_2' ? 'Gen2' : 'Gen1'`.

`SHOW WAREHOUSES` returns **empty** `resource_constraint` and `generation` for
interactive warehouses, so the ternary's else-branch always fired.

Per docs, generation is not an interactive-warehouse concept at all:
- `CREATE INTERACTIVE WAREHOUSE` `objectProperties` contains no `GENERATION`,
  no `RESOURCE_CONSTRAINT`, and no `ENABLE_QUERY_ACCELERATION`.
  https://docs.snowflake.com/en/sql-reference/sql/create-interactive-warehouse
- `ALTER WAREHOUSE`: "GENERATION applies only to standard warehouses
  (WAREHOUSE_TYPE = STANDARD)."
  https://docs.snowflake.com/en/sql-reference/sql/alter-warehouse

### Evidence
- `SHOW WAREHOUSES LIKE 'PERFTESTING_M_INTERACTIVE_1'` against
  `sfsenorthamerica-rgoldin_aws1`: `resource_constraint` and `generation` both
  empty; `type = INTERACTIVE`.
- Same result for the account's other interactive warehouses (`BITGO_IWH`,
  `BTQ_REALTIME_WH`, `PERFTESTING_XS_INTERACTIVE_1`).
- Glean search surfaced no contradicting internal guidance.

### Resolution
- Added `is_interactive` to the parsed warehouse dict and a dedicated
  interactive branch in `_parse_warehouse_row`. It keeps size and cluster counts
  (both valid interactive properties) and reports `generation`,
  `resource_constraint`, and the two QAS fields as `None`.
- Added a single shared `warehouseGenerationLabel(wh)` helper in both
  `display.js` and `configure.html` that returns `''` for interactive and
  adaptive warehouses. Replaced all four inline ternaries with it.
- The Configure detail panel now hides the Generation and QAS rows entirely when
  `is_interactive` is true; the dropdown shows `(Interactive, Medium)`.

### Regression Test
- **Check:** Interactive warehouses never report or render a generation or QAS.
- **Command:** `uv run pytest tests/test_warehouse_generation.py -q`
- **Expected:** 10 passed. `TestInteractiveWarehouseGeneration` asserts
  `generation is None`, `resource_constraint is None`,
  `enable_query_acceleration is None`, and that size/cluster counts survive.
- **Browser check:** Configure page, select an INTERACTIVE warehouse. Dropdown
  reads `NAME (Interactive, <Size>)`. Detail panel shows no Generation row and
  no QAS row. The string "Gen" must not appear.

### Notes
- Related: ISSUE-013 (same fabrication on standard warehouses with no explicit
  generation), ISSUE-014 (authoritative column was never read), ISSUE-015
  (same bug for adaptive on the dashboard).

## ISSUE-013: Standard warehouses with unset generation were reported as Gen1

| Field | Details |
|---|---|
| **ID** | ISSUE-013 |
| **Title** | Standard warehouses with unset generation were reported as Gen1 |
| **Date Reported** | 2026-09-16 |
| **Date Resolved** | 2026-09-16 |
| **Status** | Resolved |
| **Severity** | Medium |
| **Component** | `backend/api/routes/warehouses.py`, `backend/static/js/dashboard/display.js`, `backend/templates/pages/configure.html` |
| **Environment** | Local + SPCS |

### Symptoms
- Standard warehouses whose `resource_constraint` and `generation` columns are
  both empty were displayed as `Gen1`.
- Affected in the test account: `CAPSTONE_AUDIT_WH`, `CORTEX_ANALYST_WH`,
  `RSGTB_TASTYBYTESZEROTOSNOWFLAKE_BUILD_WH`, `SYSTEM$STREAMLIT_NOTEBOOK_WH`.

### Root Cause
The blank-means-Gen1 assumption was encoded in the backend comment
(`# STANDARD_GEN_1, STANDARD_GEN_2, or None (treated as Gen1)`) and in the
frontend ternaries. That assumption is no longer safe: the default generation
for new standard warehouses is now Gen2, so an empty column is evidence of
*nothing* — it means no explicit setting was recorded, and the effective
generation is the account/region default.

- "If you create a standard warehouse without specifying the GENERATION clause,
  Snowflake defaults to GENERATION = '2' (Gen2), unless Gen2 isn't available in
  your region." https://docs.snowflake.com/en/user-guide/warehouses-gen2
- BCR-2250, "Standard warehouses: Gen2 is the default generation."
  https://docs.snowflake.com/en/release-notes/bcr-bundles/2026_03/bcr-2250

Guessing Gen1 is now wrong in the *more likely* direction for recent
warehouses, which matters because FlakeBench labels benchmark results by
generation.

### Evidence
- `SHOW WAREHOUSES` on `sfsenorthamerica-rgoldin_aws1`: 4 of 21 standard
  warehouses have empty `resource_constraint` and empty `generation`, while
  others carry explicit `STANDARD_GEN_1` / `STANDARD_GEN_2` with matching
  `generation` values of `1` / `2`.

### Resolution
`warehouseGenerationLabel` returns `''` when neither column has a value, rather
than falling through to Gen1. The Configure detail panel renders
`Not set (account default)` in that case. The backend reports
`generation: None` and `resource_constraint: None` instead of implying Gen1.

### Regression Test
- **Check:** A standard warehouse with no explicit generation is never labelled Gen1.
- **Command:** `uv run pytest tests/test_warehouse_generation.py -q`
- **Expected:** `test_unset_generation_is_none_not_gen1` passes —
  `generation is None` and `resource_constraint is None`.
- **Browser check:** Configure page, select `CORTEX_ANALYST_WH`. Generation row
  reads `Not set (account default)`, not `Gen 1`. Dropdown reads
  `CORTEX_ANALYST_WH (Large)` with no generation token.

### Notes
- Deliberately does not infer Gen2 either. Region availability affects the
  default, so the honest answer is "not set". If the effective generation is
  ever needed for cost math, read it per-query rather than inferring from DDL.

## ISSUE-014: Authoritative `generation` column from SHOW WAREHOUSES was never read

| Field | Details |
|---|---|
| **ID** | ISSUE-014 |
| **Title** | Authoritative `generation` column from SHOW WAREHOUSES was never read |
| **Date Reported** | 2026-09-16 |
| **Date Resolved** | 2026-09-16 |
| **Status** | Resolved |
| **Severity** | Low |
| **Component** | `backend/api/routes/warehouses.py` |
| **Environment** | Local + SPCS |

### Symptoms
- Generation was inferred by string-matching `resource_constraint` against
  `STANDARD_GEN_1` / `STANDARD_GEN_2`, even though `SHOW WAREHOUSES` exposes a
  dedicated `generation` column with a plain `'1'` / `'2'` value.

### Root Cause
`_COL_GENERATION` (index 33) was absent from the column-index constants. The
index map jumped from `_COL_RESOURCE_CONSTRAINT = 32` to
`_COL_QUERY_THROUGHPUT_MULTIPLIER = 34`, so the column was skipped when the
adaptive columns were added.

### Evidence
- `SHOW WAREHOUSES` column order confirmed against the live account:
  `... 32 resource_constraint, 33 generation, 34 query_throughput_multiplier,
  35 max_query_performance_level, 36 disabled_reasons, 37 tables`.
- Every warehouse with `STANDARD_GEN_2` also reports `generation = 2`; every
  `STANDARD_GEN_1` reports `generation = 1`.

### Resolution
Added `_COL_GENERATION = 33` and exposed `generation` on the API payload. Both
frontend helpers now prefer `generation` and fall back to `resource_constraint`
only for compatibility with cached/older payloads that lack the new field.

### Regression Test
- **Check:** `generation` is read from column 33 and surfaced on the API.
- **Command:** `uv run pytest tests/test_warehouse_generation.py -q`
- **Expected:** `test_generation_column_index_is_33`,
  `test_gen2_from_generation_column`, and `test_gen1_from_generation_column` pass.

### Notes
- `_parse_warehouse_row` remains tolerant of short rows via its `_get` helper;
  `test_short_row_does_not_crash` covers a 24-column row.
- `backend/core/results_store.py:72` still reads only `resource_constraint` for
  historical runs. That path is display-guarded (`history_compare.html` hides the
  row when the value is empty), so it does not fabricate a generation. Left as-is.

## ISSUE-015: Adaptive warehouses rendered as "Gen1" in the dashboard warehouse label

| Field | Details |
|---|---|
| **ID** | ISSUE-015 |
| **Title** | Adaptive warehouses rendered as "Gen1" in the dashboard warehouse label |
| **Date Reported** | 2026-09-16 |
| **Date Resolved** | 2026-09-16 |
| **Status** | Resolved |
| **Severity** | Low |
| **Component** | `backend/static/js/dashboard/display.js` (`formatWarehouseOption`) |
| **Environment** | Local + SPCS |

### Symptoms
- On the dashboard, an adaptive warehouse rendered as `ADAPTIVE_WH (Gen1)` —
  a fabricated generation plus an empty size, since adaptive warehouses have no
  size.

### Root Cause
There are two independent copies of `formatWarehouseOption`. The one in
`configure.html:2320` branches on `wh.is_adaptive` and renders MXPL/QTM
correctly. The copy in `display.js:60` had no adaptive branch, so adaptive
warehouses fell through to the standard formatting path and hit the same
`? 'Gen2' : 'Gen1'` ternary as ISSUE-012.

### Evidence
- `grep -n formatWarehouseOption backend/` shows two definitions; only the
  `configure.html` copy referenced `is_adaptive`.
- Account has 7 adaptive warehouses, all with `size` empty and
  `resource_constraint` empty — every one would render as `(Gen1, )`.

### Resolution
Gave `display.js`'s `formatWarehouseOption` an adaptive branch mirroring the
`configure.html` behaviour (`(Adaptive, max <MXPL>, QTM <n>)`), and routed its
generation token through the shared `warehouseGenerationLabel` helper so the
two copies can no longer diverge on this rule.

### Regression Test
- **Check:** Adaptive warehouses never render a generation or an empty size.
- **Command:** `task test:js` (runs `node tests/js/verify_warehouse_labels.mjs`)
- **Expected:** `ADAPTIVE_WH (Adaptive, max X-Large, QTM 2)`. The string "Gen"
  must not appear for any warehouse whose `is_adaptive` is true.
- **Browser check:** Dashboard with an adaptive warehouse selected — the
  warehouse label shows Adaptive/MXPL/QTM, not a generation.

### Notes
- The duplication between `display.js` and `configure.html` is the underlying
  hazard; this fix narrows it but does not remove it. Consolidating both into a
  single shared module would prevent the next divergence.

---

## ISSUE-016: Run reports "unsaved changes" immediately after a successful Update

| Field | Details |
|---|---|
| **ID** | ISSUE-016 |
| **Title** | Run reports "unsaved changes" immediately after a successful Save/Update |
| **Date Reported** | 2026-09-17 |
| **Date Resolved** | 2026-09-17 |
| **Status** | Resolved |
| **Severity** | High |
| **Component** | `backend/templates/pages/configure.html` (`reloadTemplate`, `_saveTemplate`) |
| **Environment** | Local + SPCS |

### Symptoms
- Click **Update** on an existing template; the toast confirms the template was
  updated.
- Click **Run** immediately afterwards; the confirm dialog "You have unsaved
  changes. Save before running?" appears, implying the Update did not save.
- Users read this as Update and Save being two different actions. They are not:
  one button renders "Save" in create mode and "Update" in edit mode, and both
  call `saveAndPrepare()` -> `_saveTemplate()` (POST for create, PUT for edit).

### Root Cause
`Run` (`prepareTemplate()`) gates on `isDirty()`, which compares
`JSON.stringify(getComparableConfig())` against `savedConfigSnapshot`.

The Update path always passes `prepareAfterSave: true`, so after the PUT it runs
`prepareAiWorkload()`, which ends in `reloadTemplate()`. `reloadTemplate()`
re-merged the server config into `this.config` but never re-baselined the
snapshot, and it rebuilt `config.scaling` / `config.guardrails` via
`{ ...defaults, ...serverValues }`. Because `isDirty()` stringifies those
objects, a difference in key insertion order alone is enough to report dirty —
on top of any server-side normalisation from `_normalize_template_config` /
`_enrich_postgres_instance_size`. The `snapshotConfig()` call inside
`_saveTemplate` runs *before* this reload, so it was always stale by the time
Run read it.

### Evidence
- `configure.html`: `snapshotConfig()` called in `_saveTemplate` before
  `prepareAiWorkload()`; `reloadTemplate()` had no `snapshotConfig()` call.
- `isDirty()` compares `scaling` and `guardrails` as `JSON.stringify(...)`,
  making the comparison key-order sensitive.
- `templates.py:1960-1966` normalises and enriches config server-side before
  persisting, so the returned config is not byte-identical to what was sent.

### Resolution
Added `this.snapshotConfig()` at the end of `reloadTemplate()`, after the config
has been merged and canonicalised. The dirty baseline now always reflects
persisted server state, so Run no longer prompts after a successful
Save/Update, while genuine post-save edits are still detected.

### Regression Test
- **Check:** Run does not prompt for unsaved changes right after Save/Update.
- **Command (browser):** Open `/configure?template_id=<id>`, click **Update**,
  wait for the success toast, then click **Run**.
- **Expected:** Test launches and redirects to the dashboard with no
  "You have unsaved changes" dialog.
- **Negative check:** After Update, change `duration`, then click **Run** — the
  unsaved-changes dialog MUST still appear.
- **Command:** `task test:js`
- **Expected:** All checks pass (no frontend regressions).

### Notes
- Related: the same stale-snapshot path affected the "Update Table Metadata"
  button, which also routes through `reloadTemplate()`.
- A sturdier long-term fix is to make `getComparableConfig()` order-insensitive
  (sort keys before stringify) so nested-object rebuilds cannot produce false
  dirty state.

---

## ISSUE-017: reloadTemplate aborted with a swallowed ReferenceError for templates with results

| Field | Details |
|---|---|
| **ID** | ISSUE-017 |
| **Title** | `reloadTemplate` referenced an undefined `templateId`, silently aborting analytics reload |
| **Date Reported** | 2026-09-17 |
| **Date Resolved** | 2026-09-17 |
| **Status** | Resolved |
| **Severity** | Medium |
| **Component** | `backend/templates/pages/configure.html` (`reloadTemplate`) |
| **Environment** | Local + SPCS |

### Symptoms
- For a template that already has runs (`usage_count > 0`), reloading after an
  AI prepare / metadata refresh produced only a
  `Failed to reload template:` console warning.
- Template analytics did not refresh, with no user-visible error.

### Root Cause
`reloadTemplate()` called `this.loadTemplateAnalytics(templateId)`, but
`templateId` is not defined in that function's scope — it exists only in the
page-init path that reads `template_id` from the URL. The resulting
`ReferenceError` was thrown inside the function's `try` block and swallowed by
its `catch (e) { console.warn(...) }`, so everything after that point in the
reload was skipped.

### Evidence
- The identifier `templateId` appears in `reloadTemplate()` with no local
  declaration, parameter, or component property of that name.
- Only the `this.hasResults` branch reached the bad call, which is why the bug
  was invisible on templates with no runs.

### Resolution
Changed the call to `this.loadTemplateAnalytics(template.template_id)`, using
the template object already fetched in that scope.

### Regression Test
- **Check:** Reloading a template that has runs does not warn and does refresh
  analytics.
- **Command (browser):** Open a template with `usage_count > 0`, click
  **Update Table Metadata**, and watch the JS console.
- **Expected:** No `Failed to reload template:` warning, no `ReferenceError`,
  and the run/analytics panels repopulate.

### Notes
- Found while fixing ISSUE-016; both live in the same function.
- The broad `try/catch` around the whole reload is what hid this for so long —
  narrowing it would surface similar mistakes sooner.
