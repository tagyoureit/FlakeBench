---
name: unistore-rules
description: >-
  Documents current, implemented Unistore Benchmark architecture and workflows.
  Use when updating or verifying app behavior, autoscale/multi-worker flow,
  templates, or metrics persistence/enrichment.
version: 1.2.0
---

# Overview

This folder is the authoritative documentation for the current, implemented
architecture of the Unistore Benchmark app.

## Index (all docs in this folder)

This file:

- `SKILL.md`: entrypoint + constraints + full index (this document)

Start here:

- `index.md`: human-friendly index for the docs set
- `project-plan.md`: canonical current architecture + status (not a roadmap)
- `operations-and-runbooks.md`: how to run the app + schema + smoke + headless multi-worker

Architecture:

- `architecture-overview.md`: system context and runtime topology
- `backend-architecture.md`: FastAPI, registry, executor, connectors
- `data-flow-and-lifecycle.md`: test lifecycle, WebSocket streaming, autoscale lifecycle

Persistence and metrics:

- `persistence-and-schema.md`: results/tables schema and how it is applied
- `Refined Metrics.md`: what is captured during the run vs post-run enrichment

Templates and workloads:

- `templates-and-workloads.md`: templates, workloads, normalization, load patterns

UI:

- `ui-architecture.md`: pages, JS modules, routing, and dashboard invariants

Scaling:

- `scaling.md`: concurrency model, thread pools, sharding, and why scale-out matters

Testing:

- `testing-and-validation.md`: test locations and expectations

Constraints:

- `constraints-and-non-goals.md`: hard constraints and explicit non-goals

## Canonical constraints (must remain true)

These constraints are treated as **design preferences** and must be respected:

- Table creation and DDL changes are disabled in the app. Tests run against
  existing tables/views only.
- Results/schema persistence is via rerunnable DDL in `sql/schema/` (no migrations).
  The app does not apply schema changes at runtime.
- Templates are stored in Snowflake (`UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES`);
  YAML in `config/test_scenarios/` is reference only.
- In QPS autoscale, `concurrent_connections` is the per-worker max connections, and
  total `target_qps` is split across workers.
