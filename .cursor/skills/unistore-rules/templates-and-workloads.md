# Templates and Workloads (Current)

Last updated: 2026-01-18

## Template Storage

- Templates are persisted in Snowflake:
  `UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES`.
- All UI runs are template-based; there is no ad-hoc run UI.

## Template Normalization

- Preset workloads (READ_ONLY/WRITE_ONLY/READ_HEAVY/WRITE_HEAVY/MIXED)
  are normalized into `CUSTOM` workloads with explicit per-kind weights.
- Custom SQL is persisted per template and executed at runtime.

## YAML Templates

- YAML files in `config/test_scenarios/` are reference examples only.
- The UI does not load these files.
- `backend/core/template_loader.py` can load them programmatically.

## Workloads

- Executor runs query kinds: `POINT_LOOKUP`, `RANGE_SCAN`, `INSERT`, `UPDATE`.
- All queries are against existing tables or views.

## Load Patterns

- Load pattern classes exist in `backend/core/load_patterns.py`.
- They are not wired to the executor.
