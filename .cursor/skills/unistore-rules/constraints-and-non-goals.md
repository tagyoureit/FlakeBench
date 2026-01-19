# Constraints and Non-Goals (Current)

Last updated: 2026-01-18

## Hard Constraints

- No table creation or DDL execution at runtime.
- No migration scripts exist in this repo.
- All schema changes are via rerunnable DDL in `sql/schema/`.
- All test runs are template-based (templates stored in Snowflake).

## Non-Goals (Current)

- Desktop app packaging is not implemented.
- Container or cloud deployment automation is not implemented.
- Workload generator framework is not implemented.
- YAML templates are reference-only and not used by the UI.
