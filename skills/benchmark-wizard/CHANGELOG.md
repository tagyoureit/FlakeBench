# Changelog — benchmark-wizard

All notable changes to this skill are documented here. Newest first.

## 1.1.0

- **Fixed incorrect polling endpoint.** `workflows/03-execution.md` instructed
  agents to call `GET /api/runs/{run_id}/` to translate a run ID into a test ID.
  That route does not exist in `backend/api/routes/runs.py`, and the translation
  is unnecessary because `test_id` and `run_id` are the same UUID. Polling now
  uses `GET /api/tests/{run_id}` directly.
- **Switched the documented execution target to SPCS.** Benchmark runs execute
  client-side, so the API target determines where load originates. All workflow
  examples previously hardcoded `http://127.0.0.1:8000`, which silently produced
  locally generated load that is not comparable with SPCS-executed runs. Examples
  now use `${BASE_URL}` and `-H "$AUTH"`, with token setup documented in
  `workflows/03-execution.md`.
- Added `${BASE_URL}` / `$AUTH` convention notes to the requirements,
  configuration, and analysis workflows.
- Documented the `GET /api/tests/{id}` route in the API endpoint table.
- Updated prerequisites: SPCS reachability and key-pair auth replace the local
  backend server requirement.
- Added a Related Skills section pointing to `spcs-benchmark-runner` for
  multi-trial matrices.

## 1.0.0

Initial release.
