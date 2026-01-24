# Unistore Rules Index

This folder is the authoritative documentation for the current, implemented
architecture and behavior of Unistore Benchmark.

## Core Docs

- `SKILL.md` - entrypoint for agents; complete index of this docs folder
- `project-plan.md` - current architecture and status (not a roadmap)
- `operations-and-runbooks.md` - how to run, validate, and use headless entrypoints
- `Refined Metrics.md` - what the app captures and persists

## Architecture (Granular)

- `architecture-overview.md` - system context and runtime topology
- `backend-architecture.md` - FastAPI, registry, executor, connectors
- `data-flow-and-lifecycle.md` - test lifecycle and metrics flow
- `persistence-and-schema.md` - Snowflake results storage schema
- `templates-and-workloads.md` - template storage and workload normalization
- `scaling.md` - concurrency model and why/when to scale out
- `ui-architecture.md` - pages, JS modules, and routing
- `testing-and-validation.md` - tests location and scope
- `constraints-and-non-goals.md` - explicit constraints (no DDL/migrations)
