---
name: unistore-rules
description: This is a new rule
---

# Overview

This folder is the authoritative documentation for the current, implemented
architecture of the Unistore Benchmark app.

Use these files as the source of truth before making changes:

- `project-plan.md`: current architecture and status (not a future roadmap)
- `phase2-completion-report.md`: current UI implementation status
- `phase3-completion-report.md`: current template/load pattern status
- `Refined Metrics.md`: what is captured now vs post-run enrichment

Key constraints that must be respected:

- Table creation and DDL changes are disabled in the app. Tests run against
  existing tables/views only.
- Results persistence is via idempotent DDL in `sql/schema/results_tables.sql`.
  There are no migration scripts; do not add migration-style DDL.
- Templates are stored in Snowflake (`UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES`);
  YAML in `config/test_scenarios/` is reference only.
