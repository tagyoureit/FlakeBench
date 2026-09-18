# Changelog — spcs-benchmark-runner

All notable changes to this skill are documented here. Newest first.

## 1.1.0

- `references/methodology.md` — new section on separating server-side SQL
  execution time from end-to-end latency. Documents that engine differences can
  be almost entirely hidden by compilation and client/network time (measured:
  6.7x server-side vs 1.4x end-to-end), that `QUERY_EXECUTIONS` is keyed by the
  per-worker `TEST_ID` and must be joined to the aggregate run on `RUN_ID`, that
  client overhead scales with throughput and so understates the better
  configuration, and that `SF_EXECUTION_MS` has integer-millisecond resolution.

## 1.0.0

Initial release.

- `scripts/spcs_auth.py` — mints a Snowflake OAuth token scoped to an SPCS
  ingress endpoint via key-pair JWT token exchange. Resolves credentials from
  `~/.snowflake/connections.toml`, explicit flags, or `SNOWFLAKE_*` environment
  variables. Handles the account-identifier underscore-to-hyphen conversion
  required for the token-exchange hostname.
- `scripts/run_sequence.py` — runs templates sequentially against the SPCS app,
  polling each to a terminal state before starting the next. Supports
  Latin-square ordering so cache warmth cannot alias onto one configuration.
  Re-mints the OAuth token per run to survive multi-hour matrices.
- `references/methodology.md` — measured constraints for valid comparisons:
  run-order rotation, the ~6% CV noise floor, metric selection by load point,
  warm-up requirements, why baseline-relative stop conditions are not comparable
  across runs, and holding data layout constant when comparing table types.
