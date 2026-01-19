# Templates and Load Patterns Status (Current)

Last updated: 2026-01-18

This document reflects what is implemented today. It replaces the prior
"Phase 3 complete" report which described features that do not exist.

## Templates (Implemented)

### Authoritative Template Store

- Templates are persisted in Snowflake:
  `UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES`.
- CRUD is handled by `backend/api/routes/templates.py`.
- Templates are normalized to `CUSTOM` workloads with explicit per-kind weights.

### Template Execution

- Tests are prepared from templates via `/api/tests/from-template/{template_id}`.
- The registry manages the test lifecycle and publishes live metrics.

### YAML Templates (Reference Only)

- Reference templates exist in `config/test_scenarios/`.
- The UI does not use these files; they are examples.
- `backend/core/template_loader.py` can load YAML if used programmatically.

## Load Patterns (Module Present, Not Wired)

- Load pattern classes exist in `backend/core/load_patterns.py`.
- The executor does not currently consume these patterns.

## Workload Generator Framework (Not Implemented)

- There is no active workload generator framework in this repo.
- `backend/core/workload_generators/` exists but is empty.

## R180 Scenario

- A YAML reference template exists: `config/test_scenarios/r180_poc.yaml`.
- It is not executed by the current UI or executor.
