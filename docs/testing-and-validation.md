# Testing and Validation (Current)

Last updated: 2026-01-18

## Test Locations

- `tests/` contains python tests and integration checks.

Key tests:

- `tests/test_connection_pools.py`
- `tests/test_table_managers.py`
- `tests/test_metrics_collector.py`
- `tests/test_template_custom_workloads.py`
- `tests/test_executor.py`
- `tests/test_app_setup.py`

## Scope

- Most tests validate logic without requiring Snowflake credentials.
- Connection pool tests skip when credentials are not configured.

## Notes

- There is no dedicated UI test framework.
- There is no migration test suite (no migrations exist).
