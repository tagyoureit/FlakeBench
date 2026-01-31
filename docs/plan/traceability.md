# Traceability Matrix

Maps documentation files to implementation tasks in Phase 2.

## Docs → Plan Tasks

| Document | Related Tasks |
|----------|---------------|
| `architecture-overview.md` | 2.2, 2.3, 2.7, 2.8 |
| `orchestrator-spec.md` | 2.2, 2.3, 2.4, 2.5, 2.6, 2.16 |
| `data-flow-and-lifecycle.md` | 2.1, 2.2, 2.5, 2.6, 2.7, 2.14, 2.17, 2.19 |
| `scaling.md` | 2.10, 2.11, 2.14, 2.16 |
| `ui-architecture.md` | 2.9, 2.11, 2.13, 2.14, 2.15, 2.16, 2.17, 2.18, 2.19 |
| `operations-and-runbooks.md` | 2.12 |
| `multi-worker-gap-analysis.md` | 2.5, 2.6, 2.7, 2.8, 2.9, 2.14, 2.19 |
| `specifications.md` | 2.1-2.19 (implementation details, schemas, SQL, acceptance tests) |
| `worker-implementation.md` | 2.4, 2.11, 2.21 (worker implementation, scaling bounds, query tagging bugs) |

## Task → Docs

| Task | Primary Doc | Secondary Docs |
|------|-------------|----------------|
| 2.1 Control Tables | `specifications.md` | `data-flow-and-lifecycle.md` |
| 2.2-2.3 Orchestrator | `orchestrator-spec.md` | `architecture-overview.md` |
| 2.4 Worker Registration | `worker-implementation.md` | `orchestrator-spec.md` |
| 2.5 Poll Loop | `orchestrator-spec.md` | `data-flow-and-lifecycle.md` |
| 2.6 STOP Semantics | `orchestrator-spec.md` | `data-flow-and-lifecycle.md` |
| 2.7 Aggregation | `data-flow-and-lifecycle.md` | `architecture-overview.md` |
| 2.8 Controller API | `architecture-overview.md` | `ui-architecture.md` |
| 2.9 UI Contract | `ui-architecture.md` | - |
| 2.10 Scaling | `scaling.md` | - |
| 2.11 Manual Bounds | `scaling.md` | `ui-architecture.md`, `worker-implementation.md` |
| 2.12 Ops | `operations-and-runbooks.md` | - |
| 2.13 Legacy Removal | `ui-architecture.md` | - |
| 2.14 Latency Aggregation | `data-flow-and-lifecycle.md` | `scaling.md` |
| 2.15 Enhanced Comparison | `ui-architecture.md` | - |
| 2.16 Soft Guardrails | `orchestrator-spec.md` | `scaling.md` |
| 2.17 API Performance | `ui-architecture.md` | `data-flow-and-lifecycle.md` |
| 2.18-2.19 Timer Fixes | `ui-architecture.md` | `data-flow-and-lifecycle.md` |
| 2.20 Terminology | `worker-implementation.md` | `ui-architecture.md` |
| 2.21 Refactor Bugs | `worker-implementation.md` | `multi-worker-gap-analysis.md` |
