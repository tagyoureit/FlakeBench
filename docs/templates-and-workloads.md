# Templates and Workloads (Current)

Last updated: 2026-01-21

## Template Storage

- Templates are persisted in Snowflake:
  `UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES`.
- All UI runs are template-based; there is no ad-hoc run UI.
- Autoscale settings are stored in template config (enable + host guardrails).
- CRUD is implemented in `backend/api/routes/templates.py`.
- Table DDL is in `sql/schema/templates_table.sql`.

## Workload Presets (UI Convenience Only)

- **Preset workload types are UI shortcuts for initial template creation.**
  When a user selects READ_ONLY, WRITE_ONLY, READ_HEAVY, WRITE_HEAVY, or MIXED,
  the UI populates default percentages as a starting point.
- **All templates become CUSTOM after creation.** The preset selection only
  sets initial values; users can freely modify all percentages afterward.
- **The system never enforces preset percentages.** Once saved, templates
  store explicit `custom_*_pct` values that the user fully controls.

## Template Persistence

- Custom SQL and percentages are persisted per template in `TEST_TEMPLATES.CONFIG`.
- The backend normalizes any preset workload type to CUSTOM on save (see
  `backend/api/routes/templates.py`).
- Table DDL is in `sql/schema/templates_table.sql` (CREATE only, no migrations).

## YAML Templates

- YAML files in `config/test_scenarios/` are reference examples only.
- The UI does not load these files.
- `backend/core/template_loader.py` can load them programmatically.

## Workloads

- Executor runs query kinds: `POINT_LOOKUP`, `RANGE_SCAN`, `INSERT`, `UPDATE`.
- All queries are against existing tables or views.

## Template Value Pools (High Concurrency)

- Large sampled value pools are stored in `TEMPLATE_VALUE_POOLS`.
- DDL is in `sql/schema/template_value_pools_table.sql`.
- These pools are optional and are designed to keep `TEST_TEMPLATES.CONFIG` small.

## Load Patterns

- Load pattern classes exist in `backend/core/load_patterns.py`.
- They are not wired to the executor.

## R180 Scenario (Reference Only)

- A YAML reference template exists: `config/test_scenarios/r180_poc.yaml`.
- It is not executed by the current UI or executor.

## Autoscale (Current)

- Autoscale is UI-driven and scale-out only.
- Total target is derived from load mode inputs:
  - `CONCURRENCY`/`FIND_MAX_CONCURRENCY`: `concurrent_connections` (total workers).
  - `QPS`: `target_qps` (total ops/sec across workers).
- In QPS autoscale:
  - `concurrent_connections` is the per-worker max connections (worker ceiling).
  - Workers scale out only after each worker hits its ceiling and total QPS is
    still below target.
  - Total QPS is split evenly across workers (`target_qps / worker_count`).
- The autoscale parent run is prepared first and only starts when the user
  clicks Start on the live dashboard.
