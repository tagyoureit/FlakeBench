---
name: spcs-benchmark-runner
description: Runs FlakeBench benchmark templates sequentially against the SPCS-hosted application via its REST API, using key-pair JWT to OAuth authentication for the SPCS ingress endpoint. Applies Latin-square run ordering and statistical methodology so table-type and warehouse comparisons are not corrupted by cache-warmth ordering or sampling noise. Triggers on "run benchmark templates", "run benchmark matrix", "benchmark trials", "compare table types", "SPCS benchmark", "authenticate to SPCS endpoint", "rotate run order", "benchmark methodology".
version: 1.1.0
---

# SPCS Benchmark Runner

## Purpose

Execute multi-trial benchmark matrices against the SPCS-hosted FlakeBench
application unattended, with run ordering and metric selection that survive
statistical scrutiny.

## Use this skill when

- Running the same template multiple times to establish a median
- Comparing two or more templates (table types, warehouse sizes, clustering)
- A comparison must run unattended for hours
- Authenticating to the SPCS ingress endpoint programmatically
- Deciding which metric or load point makes a comparison valid
- A previous comparison produced a suspiciously clean or unstable result

Do NOT use this skill to design a single template from scratch — use
`benchmark-wizard` for requirements gathering and template configuration, then
return here to execute the matrix.

## Critical: runs execute client-side

The orchestrator spawns worker subprocesses inside whichever host serves the API.
Driving the SPCS deployment keeps load generation inside SPCS. Pointing at a
local server moves load generation onto the local machine, changing network
latency to Snowflake and making results incomparable with SPCS-executed runs.

**Always target the SPCS endpoint.** Never mix SPCS and local runs in one matrix.

## Inputs

### Required

- `endpoint`: `hostname` — SPCS ingress host without scheme. Obtain with
  `SHOW ENDPOINTS IN SERVICE <service>`.
- `template_id`: `uuid` — One per configuration being compared. Repeat the flag.

### Optional

- `connection`: `string` (default: `default`) — `~/.snowflake/connections.toml`
  entry supplying account, user, private key path, and role.
- `order`: `latin-square` | `as-given` (default: `latin-square`)
- `poll_seconds`: `int` (default: `20`)
- `max_run_seconds`: `int` (default: `3000`)
- `settle_seconds`: `int` (default: `15`)

Credentials resolve in this order: explicit flag, then the named connection, then
`SNOWFLAKE_ACCOUNT` / `SNOWFLAKE_USER` / `SNOWFLAKE_PRIVATE_KEY_FILE` /
`SNOWFLAKE_ROLE`. Nothing is hard-coded.

## Outputs

- Timestamped progress and a per-run status summary on stdout. Redirect to a log
  file; runs take ~13 minutes each, so a 3-template matrix runs ~2 hours.
- Exit code 0 only if every run reached `completed`.
- Results land in `<RESULTS_DATABASE>.<RESULTS_SCHEMA>.TEST_RESULTS`. Query the
  row where `CONCURRENT_CONNECTIONS` equals total connections for the aggregate;
  lower-valued rows are per-worker.

## Dependencies

Requires `pyjwt`, `cryptography`, and `requests`, all already in the project
environment. Key-pair authentication must be configured for the user
(`ALTER USER <user> SET RSA_PUBLIC_KEY=...`).

## Workflow

### Phase 1 — Validate inputs

1. Confirm the endpoint resolves and authentication succeeds:
   ```bash
   python skills/spcs-benchmark-runner/scripts/spcs_auth.py \
     --endpoint <host> --connection default | head -c 40
   ```
   A token prefix means success. A redirect to `sfc-endpoint-login` means the
   token was missing or rejected.
2. Confirm each template exists and shares identical `duration`, `warmup`,
   `concurrent_connections`, `load_mode`, and query SQL. **Only the variable under
   test may differ.** Query `TEST_TEMPLATES` to diff them.
3. Read `references/methodology.md` and verify the design satisfies it —
   especially `warmup` >= 30 and a load point past the weakest configuration's
   saturation knee.

### Phase 2 — Execute

```bash
python skills/spcs-benchmark-runner/scripts/run_sequence.py \
  --endpoint <host> \
  --template <uuid-a> --template <uuid-b> --template <uuid-c> \
  --order latin-square \
  2>&1 | tee benchmark-matrix.log
```

Three templates produce nine runs. Runs never overlap, so the warehouse serves
one load generator at a time.

Do not suspend the interactive warehouse mid-matrix: suspending resets the data
cache and incurs a fresh one-hour minimum billing period.

### Phase 3 — Analyse

Pool all trials per configuration and compare medians. Apply the metric-selection
and noise-floor rules in `references/methodology.md` before stating any
conclusion. Report differences below the ~10% noise floor as "no measurable
difference" rather than as a result.

## API reference

| Action | Call |
|--------|------|
| Create run | `POST {base_url}/api/runs/` with `{"template_id": "..."}` |
| Start run | `POST {base_url}/api/runs/{run_id}/start` |
| Preflight | `GET {base_url}/api/runs/{run_id}/preflight` |
| Poll status | `GET {base_url}/api/tests/{run_id}` |
| Stop run | `POST {base_url}/api/runs/{run_id}/stop` |

`base_url` is `https://<endpoint>`. Authorization header is
`Snowflake Token="<oauth-token>"`.

There is **no** `GET /api/runs/{run_id}/` route — poll `/api/tests/{run_id}`.
Terminal statuses are `completed`, `failed`, `cancelled`.

## Troubleshooting

- **302 to `sfc-endpoint-login`** — token absent, expired, or wrong scope. Tokens
  are scoped to one endpoint; re-mint for the endpoint being called.
- **`Hostname mismatch` during token exchange** — account identifiers containing
  underscores are not valid hostnames. The JWT claims keep the underscore; the
  `oauth/token` URL must use hyphens. `scripts/spcs_auth.py` handles this.
- **`Cannot run statement type ... on an interactive warehouse`** — DDL such as
  CTAS cannot run on an interactive warehouse. Use a standard warehouse.
- **Run stays `PREPARED`** — workers never registered. Check
  `WORKERS_REGISTERED` in `RUN_STATUS` and the service logs.
- **One configuration declines monotonically across trials** — cache-warmth
  aliasing. Confirm `--order latin-square` was used.

## Version History

See CHANGELOG.md.
