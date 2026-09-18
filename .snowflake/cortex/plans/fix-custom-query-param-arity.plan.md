MODE: PLAN

## Rules Loaded
- /Users/rgoldin/Programming/ai_coding_rules/rules/000-global-core.md (foundation)
- /Users/rgoldin/Programming/FlakeBench/PROJECT.md (project context: subagent usage, file size limits, SPCS discipline)
- /Users/rgoldin/Programming/ai_coding_rules/rules/200-python-core.md (file extension: .py) — to load at ACT
- /Users/rgoldin/Programming/ai_coding_rules/rules/206-python-pytest.md (keyword: test) — to load at ACT
- /Users/rgoldin/Programming/ai_coding_rules/rules/800-project-changelog.md (keyword: changelog) — to load at ACT
- Note: no rule matched keyword "arity" or "bind variable"; foundation + Python domain apply.

Deferring the three ACT-phase rules per the AGENTS.md token-optimization note.

---

# Plan: Fix custom-query bind parameter arity

## Problem

A benchmark run against `UNISTORE_BENCHMARK.PUBLIC.TPCH_SF100_ORDERS_INT` failed
every POINT_LOOKUP query during warmup with:

```
002049 (42601): SQL compilation error: Bind variable ? not set.
```

The log shows `params: {count: 1, items: ["265997249"]}` against a template with
three `?` placeholders.

## Verified root cause

Three distinct defects, all confirmed by reading source:

**1. `POINT_LOOKUP` has a hardcoded arity of 1** — `backend/core/test_executor.py:3999-4001`

```python
elif query_kind == "POINT_LOOKUP":
    target_id = _choose_id()
    params = [target_id]
```

There is no `_count_placeholders()` call in this branch. Any template with more
than one placeholder fails at the driver.

**2. `RANGE_SCAN` silently caps at 2** — `test_executor.py:4004-4046`

It calls `_count_placeholders()` but only branches `ph == 1` vs. else, and the
else path hardcodes `params = [start_id, start_id]`. A 3-placeholder range
template fails identically.

**3. No per-placeholder type mapping for either kind** — both draw from
`_choose_id()`, a single key pool. The bound value `265997249` is an
`O_ORDERKEY`-magnitude integer that would have landed in an `O_ORDERDATE`
predicate. A date-first predicate is unrepresentable in these kinds regardless
of arity. `GENERIC_SQL` (`test_executor.py:3766-3970`) is the only kind with a
real spec mechanism, and it is also the only one that validates arity
(`test_executor.py:3792-3796`).

Contributing factor: the error surfaced as `Network error during query execution`
rather than a SQL compilation error. That is open **ISSUE-005**
(`snowflake_pool.py` masking failures) and made triage slower than it needed to
be. Cross-reference, do not fix here.

## Design decision

Reuse `_generate_generic_params` rather than building a second spec engine. It
already supports `sample_from_table`, `random_numeric`, `random_in_range`,
`choice`, `weighted_sample`, `literal` and `offset_from_previous`, plus arity
validation. The change is to make it reachable from `POINT_LOOKUP` and
`RANGE_SCAN` entries.

Backward compatibility: when an entry has no `parameters`, keep the existing
pool-based behavior for the arities it already handles (1 for POINT_LOOKUP, 1–2
for RANGE_SCAN). Only raise when the arity cannot be satisfied. Existing saved
templates keep working unchanged.

## Tasks

### 1. Log the three findings

Append `ISSUE-007`, `ISSUE-008`, `ISSUE-009` to `docs/ISSUES.md` (117 lines, no
rotation needed) using the skill's standardized format. Next ID is 007 per
`docs/ISSUES_INDEX.md`.

| ID | Severity | Component | Title |
|---|---|---|---|
| ISSUE-007 | High | `test_executor.py:3999` | POINT_LOOKUP hardcodes 1 bind param, breaking multi-placeholder templates |
| ISSUE-008 | High | `test_executor.py:4004` | RANGE_SCAN silently caps bind params at 2 |
| ISSUE-009 | Medium | `test_executor.py` + `configure.html` | No per-placeholder param strategy for custom POINT_LOOKUP/RANGE_SCAN queries |

Each gets Symptoms, validated Root Cause (with the quoted code), Evidence (the
warmup log and the `params.count: 1` field), and a Regression Test. Note in
ISSUE-007 that the misleading "Network error" label is ISSUE-005.

Then update `docs/ISSUES_INDEX.md` and run the skill's Step 8 validation
(re-read both files, verify field completeness, ID uniqueness across all three
issue files, index/file cross-reference, line counts).

### 2. Unblock the rerun with no code change

Deliver ready-to-paste GENERIC_SQL config. Point lookup:

```sql
SELECT "O_ORDERKEY", "O_ORDERDATE", "O_ORDERSTATUS", "O_ORDERPRIORITY", "O_TOTALPRICE"
FROM {table}
WHERE "O_ORDERDATE" = ? AND "O_CUSTKEY" BETWEEN ? AND ? + 2399
```

```json
[
  {"position": 1, "name": "odate", "strategy": "sample_from_table", "column": "O_ORDERDATE"},
  {"position": 2, "name": "ck_lo", "strategy": "random_numeric", "min": 1, "max": 14000000, "integer": true},
  {"position": 3, "strategy": "offset_from_previous", "depends_on": "ck_lo", "offset": 0}
]
```

Range scan is identical with `+ 999999`.

Rationale for each choice, verified against source:
- `sample_from_table` on `O_ORDERDATE` reads the target table's sampled row pool
  (`_sample_column_value`, `test_executor.py:3733`), so values are real DATEs
  that exist — no empty result sets, and the table's stray 2026-02-17 rows are a
  negligible sampling fraction.
- `offset_from_previous` with `offset: 0` (`test_executor.py:3925`) repeats
  param 2 into param 3, which `BETWEEN ? AND ? + N` requires.
- Do **not** use `random_in_range` for the date: it returns a datetime with a
  random second offset (`test_executor.py:3897`), and
  `O_ORDERDATE = <non-midnight timestamp>` matches zero rows.
- `O_CUSTKEY` max is 14,999,999 (measured); capping the low bound at 14,000,000
  leaves headroom for the band.

Measured selectivity on this table: 2,411 distinct days, ~62,200 rows/day, 10.0M
distinct custkeys over 1..15M. A 2,400-wide band inside one day averages ~10
rows; 1,000,000-wide averages ~4,250. EXPLAIN confirms 1/264 partitions and
18 MB assigned, versus 264/264 and 4.6 GB for the `O_ORDERKEY` predicate.

### 3. Fix arity in the executor

`backend/core/test_executor.py` — surgical edits to two branches.

`POINT_LOOKUP`: call `_count_placeholders(query)`. If `ph == 1`, keep
`[_choose_id()]`. If `ph > 1` with no configured `parameters`, raise a
`ValueError` naming the placeholder count and pointing at the parameters config
— the current failure mode is an opaque driver error repeated once per query.

`RANGE_SCAN`: keep the `ph == 1` time-cutoff path and the `ph == 2` id-BETWEEN
path unchanged; add an explicit `ph >= 3` branch that raises the same actionable
error when no specs are configured. Change the `else` to `elif ph == 2` so the
2-param assumption is stated rather than implied.

`test_executor.py` is ~2,600 lines and PROJECT.md flags it as a refactor
candidate at >2000. These edits are well under the 100-line threshold that
would require extracting a module, so they stay in place.

### 4. Thread parameter specs through the config path

- `backend/core/test_registry.py:186-206` — the `custom_queries` entry dict is
  built as `{"query_kind", "weight_pct", "sql"}`. Add an optional `parameters`
  key read from config (`custom_point_lookup_parameters`,
  `custom_range_scan_parameters`), omitted when absent.
- `backend/api/routes/templates_modules/constants.py` — register the two new
  config keys alongside the existing query keys (lines 10-11, 38-55).
- `backend/api/routes/templates_modules/config_normalizer.py:151-152` — normalize
  the new fields next to their existing pct/query pairs.
- `backend/api/routes/templates_modules/models.py:95-96` — add the optional
  fields to the response model.
- `test_executor.py` — in both branches, when `entry.get("parameters")` is a
  non-empty list, delegate to `_generate_generic_params(query, ...)` and skip
  the pool logic entirely. This reuses its arity validation for free.

Postgres note: `constants.py:50-51` shows a separate `$1`/`$2` default set.
`_count_placeholders` already falls back to a `$N` regex, so no extra work, but
the new fields must be registered for both backends.

### 5. Add the parameters editor to the UI

`backend/templates/pages/configure.html` — the two textareas at lines 658 and
687 have no companion parameters surface; only the GENERIC_SQL path does
(`parameters: []` at lines 1735 and 1755). Mirror that existing editor for both
custom queries, and show a live placeholder count vs. configured param count so
a mismatch is visible before save. Update the stale hint at line 1391 ("the `?`
parameters are bound from these sampled values"), which documents the old fixed
one-key/two-key model.

### 6. Preflight arity validation

`backend/core/orchestrator_modules/preflight.py` already has a warnings
mechanism (`_check_missing_clustering_key`, line 468). Add an analogous check
that compares placeholder count against configured parameters for every custom
query entry. A mismatch should fail the run at preflight, not produce one driver
error per query during warmup — the observed failure mode.

### 7. Tests

Add to the unit suite (`task test:unit`, mocked and fast):
- POINT_LOOKUP with 1 placeholder and no specs → 1 param, legacy behavior intact
- POINT_LOOKUP with 3 placeholders and no specs → raises with an actionable message
- POINT_LOOKUP with 3 placeholders and 3 specs → 3 params, correct types and order
- RANGE_SCAN with 1, 2, and 3 placeholders → cutoff / id-BETWEEN / raise-or-specs
- spec count ≠ placeholder count → raises the existing mismatch error
- `offset_from_previous` with `offset: 0` returns a value equal to its dependency
- preflight flags a mismatched entry

### 8. Validate and record

`Taskfile.yml` exposes no `validate` or `lint` task, so per the AGENTS.md tool
discovery order fall through to the domain rule's commands. The project uses uv
(`uv.lock` present): `uv run pytest` via `task test:unit`, plus `uvx ruff check`,
`uvx ruff format --check`, `uvx ty check` on touched files.

Then update `CHANGELOG.md`, move the three issues to `docs/ISSUES_COMPLETED.md`
with filled Resolution sections, re-run Step 8 validation, and write the new
regression checks to
`/memories/projects/Users-rgoldin-Programming-FlakeBench/regression-checklist.md`.

## Out of scope

- **ISSUE-005** (`snowflake_pool.py` mislabeling SQL errors as network errors).
  Related and it degraded triage here, but a separate open issue with its own
  blast radius.
- **Interactive vs. hybrid clustering mismatch.** `TPCH_SF100_ORDERS_INT` is
  clustered `LINEAR(O_ORDERDATE, O_CUSTKEY)` while `TPCH_SF100_ORDERS_HYBRID`
  keys on `O_ORDERKEY`. These templates are optimal for the former and
  suboptimal for the latter, so query-for-query comparison between them stays
  invalid. Worth deciding separately — either recreate the interactive table
  with `CLUSTER BY (O_ORDERKEY)` or compare each table on its own aligned
  template.
- Refactoring `test_executor.py` into modules.

## Risks

- Task 4 touches five files across the config path; a missed normalizer entry
  would silently drop `parameters` and fall back to the legacy path. Task 6's
  preflight check is the backstop — it would surface the drop as a hard failure
  rather than a wrong-value benchmark.
- Task 5 is UI work. Per PROJECT.md, automated tests passing does not mean the
  UI works; this needs a browser check of save/reload round-tripping the
  parameters JSON.

---

Authorization (required): Reply with `ACT` (or `ACT on items 1-3`).
