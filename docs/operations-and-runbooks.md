# Operations and Runbooks (Current)

Last updated: 2026-01-27

This document is a practical map of entrypoints, scripts, and commands used to
run and validate FlakeBench.

## Common entrypoints

### Start the app (local)

- Server: `uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --log-config logging_config.yaml`
- Pages: start at `/` (templates)
- Health: `/health`
- API docs: `/api/docs` and `/api/redoc`

### Initialize / repair results schema

The app does **not** run DDL at runtime. Schema setup is performed out-of-band:

- Command: `uv run python -m backend.setup_schema`
- DDL sources (rerunnable): `sql/schema/`
  - `results_tables.sql` (DB+schema bootstrap + core results tables + views)
  - `templates_table.sql`
  - `template_value_pools_table.sql`
  - `test_logs_table.sql`
  - `control_tables.sql` (hybrid control-plane tables)

## Local runbook

1. Start the controller (FastAPI app).
2. Prepare a run from a template: `POST /api/tests/from-template/{id}`
   (or programmatic `POST /api/runs`).
3. Open `/dashboard/{test_id}`.
4. Start the run: `POST /api/tests/{test_id}/start`
   (or `POST /api/runs/{run_id}/start`).
5. Live metrics stream over `/ws/test/{test_id}` once status is RUNNING.
6. Stop via UI or `POST /api/runs/{run_id}/stop` / `POST /api/tests/{test_id}/stop`.

## Smoke checks (Taskfile)

Use Taskfile entrypoints to run short end-to-end checks through the running
server:

| Task | Description |
|------|-------------|
| `task test:variations:smoke` | Short smoke test (default 45s per test) |
| `task test:variations:smoke:long` | Long smoke test (5min, 10s warmup) |
| `task test:variations:setup` | Setup only (create tables + templates) |
| `task test:variations:cleanup` | Cleanup only (drop tables + templates) |

### Quick validation (fastest)

For a quick ~1-minute validation that everything works:

```bash
SKIP_POSTGRES=true DURATION_SECONDS=5 METRICS_WAIT_SECONDS=10 task test:variations:smoke
```

### Environment variable overrides

All smoke test parameters can be overridden via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DURATION_SECONDS` | 45 | Test duration per table type |
| `WARMUP_SECONDS` | 0 | Warmup period before measurement |
| `METRICS_WAIT_SECONDS` | 60 | Max wait for metrics after completion |
| `SMOKE_CONCURRENCY` | 5 | Concurrent connections |
| `SMOKE_ROWS` | 300 | Rows in smoke tables |
| `SKIP_POSTGRES` | false | Skip Postgres variation |
| `BASE_URL` | `http://127.0.0.1:8000` | API server URL |

### Notes

- These tasks assume the app server is already running.
- Smoke setup uses SnowCLI (`snow sql`) for DDL/DML in a dedicated smoke schema.
- Smoke tests use `tags.smoke=true` to bypass the warehouse isolation check
  (allowing the same warehouse for both smoke tests and results storage).

## Headless worker / orchestration scripts

### Worker (single worker)

- Script: `scripts/run_worker.py`
- Starts a test from a template and blocks until it finishes.
- Key flags:
  - `--template-id <id>` (required)
  - `--worker-group-id <n>` / `--worker-group-count <N>` for deterministic sharding
  - `--parent-run-id <uuid>` and `--worker-id <name>` for multi-worker attribution
  - `--concurrency`, `--min-concurrency`, `--start-concurrency`, `--target-qps` overrides

### Orchestrator (multi-worker runs)

- Runs are started via the UI or `POST /api/runs`; the orchestrator launches workers.

### Refresh parent aggregation (manual)

- Script: `scripts/refresh_parent_aggregate.py`
- Use when you need to recompute the parent run’s aggregate after-the-fact:
  - `uv run python scripts/refresh_parent_aggregate.py <parent_run_id>`

## Validation (multi-worker acceptance)

1. Start controller and orchestrator.
2. Create a multi-worker run via `POST /api/tests/from-template/{id}/autoscale`
   or `POST /api/runs`.
3. Start via `POST /api/tests/{test_id}/start-autoscale` or `POST /api/runs/{run_id}/start`.
4. Issue STOP and confirm:
   - STOP event appears in `RUN_CONTROL_EVENTS`.
   - `RUN_STATUS` transitions to `CANCELLING` and then `CANCELLED`.
5. Verify all worker processes exit and the parent `TEST_RESULTS` rollup updates.

## Front-end development (Tailwind CSS)

The UI uses Tailwind CSS v4 (via `pytailwindcss`). Styles are defined in
`backend/static/css/input.css` and compiled to `backend/static/css/tailwind.css`.

### Taskfile commands

| Task | Description |
|------|-------------|
| `task css:watch` | Watch mode — auto-rebuilds on changes (recommended for dev) |
| `task css:build` | One-time build, minified (for production) |
| `task css:dev` | One-time build, unminified (for debugging) |

### When to rebuild

Rebuild CSS after modifying:
- `backend/static/css/input.css` (Tailwind source with `@apply` directives)
- `backend/templates/**/*.html` (if adding new Tailwind utility classes)

### Development workflow

1. Start the CSS watcher in one terminal:
   ```bash
   task css:watch
   ```

2. Start the app server in another terminal:
   ```bash
   uv run uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000 --log-config logging_config.yaml
   ```

3. Edit `input.css` or templates — CSS rebuilds automatically.

### Browser caching

If CSS changes don't appear, hard-refresh the browser (Cmd+Shift+R / Ctrl+Shift+R)
or open DevTools and disable caching.

### File structure

- `backend/static/css/input.css` — Tailwind source (edit this)
- `backend/static/css/tailwind.css` — Compiled output (loaded by `base.html`)
- `backend/static/css/app.css` — Legacy file (not loaded, kept for reference)

## Python tests

- Tests live under `tests/`.
- Key coverage:
  - `test_connection_pools.py`, `test_table_managers.py`, `test_metrics_collector.py`
  - `test_executor.py`, `test_orchestrator_control_plane.py`, `test_runs_api.py`
  - `test_scaling_sharding.py`, `test_template_custom_workloads.py`
  - `test_ui_contract.py`, `test_dashboard_redirect.py`
- Most tests validate logic without requiring Snowflake credentials.
- Connection pool tests skip when credentials are not configured.

## Troubleshooting

### Tests Complete Immediately / Dashboard Shows 28800s (Timezone Bug)

**Symptom**: Tests configured for 10s warmup + 10s measurement complete in
2-4 seconds with `duration_elapsed` reason. OR the dashboard shows "Total Time:
28809s" (~8 hours) for a test that just started.

**Cause**: Python calculates elapsed time incorrectly due to timezone mismatch.
Snowflake returns `START_TIME` as a naive datetime in the **session timezone**
(often Pacific), but Python's `datetime.now(UTC)` returns UTC. The 8-hour
difference makes elapsed time appear much larger than actual.

**Solution**: Always calculate elapsed time in Snowflake SQL using `TIMESTAMPDIFF`:

```sql
SELECT TIMESTAMPDIFF(SECOND, START_TIME, CURRENT_TIMESTAMP()) AS ELAPSED_SECONDS
FROM RUN_STATUS WHERE RUN_ID = ?
```

### Workers Exit Immediately (Hot Reload)

**Symptom**: Workers spawn, run for 1-2 seconds, then "All workers exited" appears.
Status shows CANCELLING with 0 operations.

**Cause**: `APP_RELOAD=true` (default in development) causes Uvicorn's `watchfiles`
to restart the server when Python files change. This kills spawned worker subprocesses.

**Solution**: Run without hot-reload for test execution:

```bash
APP_RELOAD=false uv run python -m backend.main
```

### Workers Show COMPLETED but Test Shows FAILED

**Symptom**: Worker heartbeat shows `STATUS=COMPLETED`, but parent test shows
`STATUS=FAILED` with low operation count.

**Cause**: The orchestrator's poll loop detected all workers exited before the
expected duration. Usually tied to the timezone bug above.

**Diagnosis**: Check `RUN_CONTROL_EVENTS` for STOP reason:

```sql
SELECT EVENT_TYPE, EVENT_DATA, CREATED_AT
FROM RUN_CONTROL_EVENTS
WHERE RUN_ID = '<run_id>'
ORDER BY CREATED_AT;
```

If `STOP` has `reason: "duration_elapsed"` but timestamps are only seconds apart,
the timezone bug is the cause.

## SPCS runbook (future)

- Controller runs as a long-running SPCS service.
- Orchestrator runs as a separate service (or job controller).
- Workers run as job services or short-lived services per run.
- Prefer container parity between local and SPCS environments.

## Reiterated constraints

- No DDL is executed at runtime.
- Schema changes are rerunnable DDL in `sql/schema/`.
- Templates are stored in `FLAKEBENCH.TEST_RESULTS.TEST_TEMPLATES` with
  `CONFIG` as the authoritative JSON payload.
