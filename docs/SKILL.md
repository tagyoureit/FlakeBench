---
name: flakebench-rules
description: >-
  Authoritative index for current FlakeBench docs. Use when updating
  or verifying behavior, orchestration, templates, and persistence.
version: 1.3.0
---

# SKILL: FlakeBench Docs Index

This file is the authoritative index for agents working in this repository.

## Start here

- `index.md` — human landing page for the docs set
- `architecture-overview.md` — system purpose, topology, components
- `operations-and-runbooks.md` — run, validate, troubleshoot
- `project-plan.md` — implementation checklist and open work
- `specifications.md` — schemas, payloads, and implementation details

## Architecture and lifecycle

- `data-flow-and-lifecycle.md` — lifecycle, control-plane state, metrics flow
- `metrics-streaming-debug.md` — **debug guide**: phase transitions, QPS=0 issues, websocket flow
- `orchestrator-spec.md` — orchestrator contract and behaviors
- `worker-implementation.md` — worker CLI, state machine, SQL, and flow details
- `scaling.md` — scaling model, guardrails, sharding
- `multi-worker-gap-analysis.md` — gaps, risks, and fixes

## UI

- `ui-architecture.md` — UI contracts and dashboard behavior

## Notes

- `docs/archive/` contains historical snapshots. Do not edit or reference as
  authoritative sources.

## Canonical constraints (must remain true)

- No DDL or table creation at runtime; schema changes live in `sql/schema/`.
- No migration framework exists in this repository.
- Templates are stored in `FLAKEBENCH.TEST_RESULTS.TEST_TEMPLATES` with
  `CONFIG` as the authoritative payload.
- YAML templates in `config/test_scenarios/` are reference-only for the UI.
- Snowflake is the authoritative results store.
- QPS autoscale uses `concurrent_connections` as per-worker max connections;
  total `target_qps` is split across workers.
- AUTO/BOUNDED runs use the orchestrator path; FIXED runs use the legacy registry
  path.
