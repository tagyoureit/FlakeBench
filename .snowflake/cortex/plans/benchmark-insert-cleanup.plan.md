# Plan: Optional post-run cleanup of benchmark-inserted rows

## Rules Loaded
- `/Users/rgoldin/Programming/ai_coding_rules/rules/000-global-core.md` (foundation)
- `PROJECT.md` (subagent usage, file-size limits, SPCS discipline)
- Domain rules `100-snowflake-core.md`, `200-python-core.md`, `206-python-pytest.md`, `802-project-changelog.md` to be loaded at ACT time per AGENTS.md Step 3 token-deferral

## Design decision: Time Travel identifies, DELETE removes

Restore/clone is rejected (see "Alternatives considered"). But Time Travel is the
right *row-identification* mechanism, and better than the key range alone:

```sql
DELETE FROM <target>
WHERE <id_col> IN (
    SELECT <id_col> FROM <target>
    MINUS
    SELECT <id_col> FROM <target> AT (TIMESTAMP => <anchor>::TIMESTAMP_LTZ)
);
```

No cross-worker coordination, survives the `str(uuid4())` ID path, correct for
aborted runs, and naturally idempotent. Two mechanisms ship, because neither
covers everything:

| Mechanism | Used for | Limits |
|---|---|---|
| Time Travel anti-join (**primary**) | Snowflake STANDARD, HYBRID, INTERACTIVE-dynamic source | Needs `id_column` + rows inside retention window |
| Persisted key range (**fallback + audit**) | POSTGRES; out-of-retention; no usable `id_column` | Sparse per-worker windows; useless for uuid4 IDs |

The recorded range is persisted **unconditionally** (spec requirement 2) so cleanup
is auditable and re-runnable after the process exits, even when the anti-join is
the path actually taken.

## Verified constraints driving the design

1. **`profile.id_column` is not a key.** `table_profiler.py:388-409` falls through
   to `candidates[0]` even when the sampled 0.98-distinctness check *fails*, and
   skips it entirely for single candidates, hybrid tables and views
   (`:392-397`). `TableProfile` (`:157-167`) has no key list and no column types.
   Consequence: the count-first gate is a **hard safety requirement**, not a nicety
   — a duplicate pre-existing id value would otherwise over-delete.
2. **Warmup INSERTs write rows but are not counted.** `test_executor.py:4144-4146`
   increments `_insert_count` only when `not warmup`. Expected-count must come from
   `SUM(QUERY_EXECUTIONS.SF_ROWS_INSERTED) WHERE QUERY_KIND='INSERT'`
   (includes warmup rows), joined to `run_id` via `TEST_RESULTS.TEST_ID` —
   `QUERY_EXECUTIONS` has no `run_id` column.
3. **Nothing records inserted rows.** Confirmed: `_insert_count`
   (`test_executor.py:233`) and `metrics.rows_written`
   (`metrics_collector.py:192`) are scalars; `insert_id_seqs`
   (`executor/types.py:21`) is an in-memory `dict[int, Iterator[int]]`, never
   persisted; `profile.id_max` is *mutated mid-setup* at `test_executor.py:1155`
   (`state.profile = replace(state.profile, id_max=int(base))`), so reconstructing
   `base` post-hoc is unsafe. `TableRuntimeState` is **defined twice**
   (`executor/types.py:13` and `test_executor.py:53-56`) — both need the new field.
4. **`TEST_` prefix is unusable**, as the spec says: truncation yields `TES`/`TE`,
   `max_len == 1` yields a bare letter (`:3646`), non-string columns get no marker,
   and the UPDATE path uses a *different* format `f"TEST_{uuid4()}"` (`:4162`).
5. **No table manager reaches the `finally:` block.** `create_table_manager` is
   called once, at `orchestrator.py:1148` inside `_pre_validate_tables`, and the
   instance is discarded; only plain data survives (`:1166-1175`, which *does*
   carry `object_type`). `RunContext` (`:160-184`) has no manager. Cleanup must
   issue SQL directly against `self._pool`.
6. **VIEW targets need no cleanup.** Writes on views are already blocked at
   `test_executor.py:1007`. `object_type` is tracked on the manager
   (`base.py:35-37`) and cached at `:1172`.
7. **DYNAMIC targets need no cleanup and cannot have any.** Read-only
   (`dynamic.py:33`), and `DynamicTableManager` holds no source reference
   (whole file is 43 lines; `__init__` only calls `super()` and logs).
8. **POSTGRES is a fifth writable target** the spec omits. `PostgresTableManager`
   uses a separate asyncpg pool where `execute_query` returns a **status string,
   not rows** (`postgres_pool.py:176-194`), uses `$1` placeholders and positional
   `*args`, and `get_full_table_name()` omits the database qualifier.

## Table-type routing (docs-verified)

| Target | Path |
|---|---|
| STANDARD | Time Travel anti-join → `DELETE` on target |
| HYBRID | Same, but **`AT (TIMESTAMP => ...)` only** — `BEFORE`, `OFFSET`, `STATEMENT` unsupported ([hybrid limitations](https://docs.snowflake.com/en/user-guide/tables-hybrid-limitations)) |
| DYNAMIC | No-op; read-only, no source reference |
| VIEW (any type) | No-op; writes already blocked |
| INTERACTIVE, static | **No `DELETE`/`UPDATE`.** Only `INSERT OVERWRITE` — refuse and report, do not overwrite |
| INTERACTIVE, dynamic (`TARGET_LAG`) | **No DML at all.** Resolve source from `GET_DDL` (authoritative) / `SHOW INTERACTIVE TABLES.text`; delete from source; refresh propagates. Unresolvable → fail loudly |
| POSTGRES | Recorded key range only (no Time Travel); separate pool, `$1` params |

Time Travel *queries* are supported on interactive tables (docs: "Fail-safe… isn't
available for interactive tables. However, you can still use Time Travel with
interactive tables"), so the anti-join can run there — but the resulting `DELETE`
must still target the source.

---

## Task 1 — Verify interactive write path (blocking for tasks 5-6)

An open contradiction: interactive tables reject DML, yet 4,485 rows appeared in
`TPCH_SF100_ORDERS_INT` and manual cleanup on `TPCH_SF100_ORDERS` fixed it.
Determine where the executor actually sends INSERTs for an INTERACTIVE target —
whether it writes to the interactive table (and how that succeeds), or already
resolves a source. This decides whether task 5 needs source resolution at all.
Also confirm `DATA_RETENTION_TIME_IN_DAYS` on the real targets, since interactive
tables inherit it from schema/database/account and cannot set it themselves.

Deliverable: a short written finding, no code. Blocking — do not implement 5-6 first.

## Task 2 — Config flag and UI plumbing

- `backend/models/test_config.py`: add after the `use_pgbouncer` block
  (`:363-371`), matching its shape — plain `bool`, positional `False`, multi-line
  parenthesized description stating what it does and that it is disabled by default:
  ```python
  cleanup_inserted_rows_after_run: bool = Field(
      False,
      description=(...),
  )
  ```
- `backend/templates/pages/configure.html`: **do not copy `use_pgbouncer`'s
  checkbox** — it lives at `:541-550` inside a "Postgres Connection Settings" card
  gated by `x-show="isPostgresFamilyTableType(...)"` (`:538`). Copy the ungated
  `use_cached_result` pattern instead. Four edits:
  - checkbox in the Execution Options card
  - Alpine default beside `:1502`
  - save payload beside `:1633-1634`
  - **both** edit-load coercion sites: `:2932-2940` **and** `:3721-3727`
- No API route change needed: create/update accept an untyped `dict`; the Pydantic
  field is the only typed surface.

## Task 3 — Persist cleanup anchors

`sql/schema/results_tables.sql` uses `CREATE OR ALTER` (`:16-21`), so additive.

- New table `INSERTED_KEY_RANGES`: `RANGE_ID`, `RUN_ID`, `TEST_ID`,
  `WORKER_GROUP_ID`, `WORKER_ID`, `TABLE_NAME`, `TABLE_TYPE`, `ID_COLUMN`,
  `MIN_ID`, `MAX_ID`, `ROWS_INSERTED`, `ANCHOR_TIMESTAMP`, `USES_UUID_IDS`,
  `CLEANUP_STATUS`, `CLEANUP_ROWS_DELETED`, `CREATED_AT`, `UPDATED_AT`.
  Cluster by `RUN_ID`, as `WORKER_METRICS_SNAPSHOTS` does (`:341`).
- Add `CLEANUP_ANCHOR_TIMESTAMP` to `TEST_RESULTS`, captured via
  `SELECT CURRENT_TIMESTAMP()` **before workers launch** so it precedes even
  warmup inserts. `TEST_RESULTS.start_time` is close but not guaranteed
  pre-insert; an explicit column removes the ambiguity.
- `backend/core/results_store.py`: `upsert_inserted_key_range(...)` and
  `record_cleanup_outcome(...)`, following the house pattern at `:1190-1256` —
  keyword-only args, early `return` on empty, explicit `cols` list,
  `INSERT ... SELECT ... FROM VALUES` (not bare `VALUES`) so `TRY_PARSE_JSON`
  works in the projection, best-effort and documented as never failing the test.
- **Written incrementally**: row created on first INSERT, `MAX_ID` updated on the
  existing metrics-flush cadence and again on worker exit, so a run that aborts
  mid-flight still has a usable range.

## Task 4 — Track generated key ranges in the executor

`test_executor.py` is ~2,600 lines — a documented refactor candidate — so the
tracking logic goes in a **new** `backend/core/executor/insert_tracking.py`, with
only a thin call inserted at the generation sites.

- A small `InsertKeyRangeTracker` wrapping the per-worker `count(start_id)`
  (`:4106-4139`), recording first and last value actually consumed per worker.
- Add the tracker field to **both** `TableRuntimeState` definitions
  (`executor/types.py:13-21` and `test_executor.py:53-56`).
- Flag `uses_uuid_ids` when the `str(uuid4())` branch (`:4140-4141`) is taken —
  no range is derivable there, so cleanup must rely on the anti-join or refuse.
- Count warmup inserts into the range (they are written to the target).

## Task 5 — Cleanup service module

New package `backend/core/cleanup/` per PROJECT.md modularization
(`types.py`, `service.py`, `interactive_source.py`), because `orchestrator.py`
is ~4,000 lines and must not absorb this.

Algorithm, in order:

1. Resolve target kind and `object_type` from `ctx.scenario_config["target"]` and
   the pre-validation cache (`:1172`). VIEW or DYNAMIC → no-op, reported as such.
2. Read persisted ranges + anchor. **No recorded range and no anchor → refuse**,
   report `SKIPPED_NO_ANCHOR`. Never an unbounded `DELETE`.
3. Compute `expected` = `SUM(SF_ROWS_INSERTED)` over `QUERY_EXECUTIONS` for the
   run's `TEST_ID`s where `QUERY_KIND='INSERT'` (joined via `TEST_RESULTS`).
4. Resolve the delete target: for INTERACTIVE-dynamic, resolve the source via
   `GET_DDL` (authoritative), cross-checked against
   `SHOW INTERACTIVE TABLES`.`text`. Ambiguous or unresolvable → **raise with an
   actionable message naming the table and the DDL fragment**. Never fall back to
   `INSERT OVERWRITE`. INTERACTIVE-static → refuse with an explanatory message.
5. **Count first**: `SELECT COUNT(*)` over the same predicate as the delete. Log
   intended vs expected. Mismatch → abort the delete, `logger.warning`, record
   `ABORTED_COUNT_MISMATCH`. This is what protects against the non-unique
   `id_column`.
6. Delete, bounded by the identified key set **and** scoped to the run. Record
   actual rows deleted.
7. Idempotent: a second pass finds an empty anti-join / already-`COMPLETED` status
   and deletes nothing.
8. POSTGRES: recorded range only, via the asyncpg pool, `$1` placeholders,
   remembering `execute_query` returns a status string rather than rows.

## Task 6 — Orchestrator hook

Modelled precisely on the warehouse-suspend block at
`backend/core/orchestrator.py:4057-4077`, inserted in the same `finally:`
(`:3978`) after the suspend block and before the Postgres-stats teardown
(`:4079-4089`):

- re-fetch `ctx = self._active_runs.get(run_id)` rather than reusing outer scope
- guard `if ctx and <flag>:`
- read the flag from `ctx.scenario_config` with `.get(...) or {}` then coerce, as
  `:4060-4061` does
- `try:` / `except Exception as cleanup_err:` → `logger.warning(...)` with lazy
  `%s` args, no re-raise, so cleanup failure warns and the rest of `finally`
  continues
- `logger.info` before, `logger.info("✅ ...")` after, matching house style

Add `cleanup_anchor_timestamp` and `cleanup_rows_deleted` to `RunContext`
(`:160-184`), alongside `did_resume_warehouse` (`:176`) which is the existing
precedent for a run-scoped flag consumed in `finally`.

## Task 7 — Report rows deleted

There is no unified run-summary object today, so this is genuinely new plumbing
rather than a copy:

- `backend/models/test_result.py`: add `rows_deleted` beside the counters at
  `:84-87`, aggregate in `calculate_summary` (`:340`).
- Persist via `update_test_result_final` (`results_store.py:1356`) into a new
  `TEST_RESULTS.ROWS_DELETED` column, mirroring the existing
  `sf_rows_inserted` triplet (`results_store.py:1259`,
  `file_query_logger.py:98`).
- Render in `backend/templates/pages/dashboard_history.html`, following the
  `pg_enrichment` metric-card group (`:869-919`) — the closest existing pattern
  for a scalar row count. Render the status string too
  (`COMPLETED` / `SKIPPED_NO_ANCHOR` / `ABORTED_COUNT_MISMATCH` / `NOT_REQUESTED`)
  so a no-op cannot read as success.
- Live WebSocket surfacing is **out of scope**: `websocket/metrics.py:98-117`
  selects a fixed column list from `WORKER_METRICS_SNAPSHOTS`, so it would need a
  new column there too, and cleanup runs after the stream closes anyway.

## Task 8 — Tests, validation, CHANGELOG

**Baseline first.** The suite has 77 pre-existing failures / 578 passed. Get a
true baseline from a pristine worktree with its own cwd, so both tests and
backend come from HEAD:

```bash
git worktree add /tmp/fb_base HEAD --detach
cd /tmp/fb_base && /Users/rgoldin/Programming/FlakeBench/.venv/bin/python \
  -m pytest tests --ignore=tests/e2e -m "not e2e" -q
```

then diff sorted `FAILED` lists. Running the worktree's tests from the repo cwd
does not isolate the backend.

There is **no mock Snowflake connection/cursor fixture** — `conftest.py`
connection fixtures are real and `E2E_TEST=1`-gated. Use per-test
`unittest.mock.patch`, as `tests/test_ui_contract.py` does throughout.

New `tests/test_cleanup_inserted_rows.py`, plus extensions to
`tests/test_models.py` (Pydantic default), `tests/test_executor.py` (range
tracking), `tests/test_table_managers.py` (routing),
`tests/test_orchestrator_control_plane.py` (config threading),
`tests/test_ui_contract.py` (summary field — `:776` is the precedent).

Cases, per spec: flag off → no delete; range recorded on success, on failure and
on cancel; each table type routes correctly; VIEW and DYNAMIC no-op;
interactive-dynamic resolves and deletes from source; unresolvable source raises;
count mismatch aborts without deleting; second run deletes nothing; Postgres
takes the range path; no anchor → refuse rather than unbounded delete.

Validation gate — no `task validate` target exists; project uses uv:

```bash
task test:unit
uvx ruff check <touched>
uvx ruff format --check <touched>
uvx ty check <touched>
```

Never bare `uv sync` (dev deps are in `[project.optional-dependencies]`; it
uninstalls pytest and ruff) — use `uv sync --all-extras`. The app's Snowflake pool
currently fails with an invalid PAT (`250001 08001`), so anything needing live
Snowflake is verified separately.

Finally: `CHANGELOG.md` per `802-project-changelog.md`, then log the work via the
`plan-qa` skill.

---

## Alternatives considered

**Time Travel restore / `CLONE`** — rejected, not implemented.
`CREATE OR REPLACE TABLE t CLONE t AT(...)` drops and recreates the customer's
table: new object ID, grants lost without `COPY GRANTS`, Time Travel history
reset, and every dependent object invalidated. That breaches the
no-create/no-drop stance in `base.py:168-177`, `base.py:110-114` and
`standard.py:6` far more severely than a bounded row delete. Database-level clone
restores into a *new* database, so it does not fix the table being benchmarked —
and it is the only option for hybrid tables, since table- and schema-level clone
fails with `391411 (0A000): This feature is not supported for hybrid tables:
'CLONE'` and hybrid cloning is a **size-of-data physical copy** into the row store
(150M rows). Restore also reverts everything else that happened in the interval,
which is unacceptable on a shared customer table. Retention (default 1 day; 1 day
max on Standard Edition) can lapse during a long `FIND_MAX` sweep.

**`TEST_` prefix matching** — rejected; see verified constraint 4.

**Exact per-row ID persistence** — rejected as too high-volume; min/max per worker
plus the anti-join gives equivalent safety with the count gate.

## Out of scope

- Dropping or creating tables. Row deletion only; the no-create/no-drop stance is
  unchanged.
- Retroactive cleanup of past runs. Worth documenting as a manual one-off: if the
  run is still inside retention, the same anti-join recovers it with no recorded
  state — a much better recipe than `WHERE O_CLERK LIKE 'TEST\_%'`.
- Live WebSocket surfacing of the deleted count (task 7 rationale).

## Deploy

Changes are baked into the SPCS image. Use `./spcs/deploy.sh` — it handles build,
push, `ALTER SERVICE` and digest verification. A `docker push` alone does **not**
deploy: SPCS freezes the digest at deploy time and suspend/resume restarts on the
frozen digest. Requires Snowflake VPN. Read `spcs/service-spec.yaml` verbatim;
endpoint must be `app`.
