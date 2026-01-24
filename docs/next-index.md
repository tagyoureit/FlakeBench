# Proposed Multi-Node Docs (Draft)

This doc set is a **new** proposal and does not replace the current docs.
It is intentionally duplicative so each file is self-contained.

## Terminology (Standard Across All Docs)

- **WORKER_ID**: Unique identifier for a worker process (string, e.g., `worker-0`)
- **WORKER_GROUP_ID**: Zero-based index for deterministic sharding (integer)
- **TARGET_CONNECTIONS**: Number of concurrent queries a worker should maintain
- **SEQUENCE_ID**: Monotonic counter for event ordering within a run
- **Warmup**: Run-level phase to prime Snowflake compute (not per-worker)

## Index

- `next-project-plan.md` - current vs target state summary. Includes a detailed
  implementation plan that covers all other documents.
- `next-specifications.md` - **concrete schemas, SQL, and implementation
  details** (WebSocket payloads, event schemas, aggregation queries, acceptance
  tests)
- `next-architecture-overview.md` - proposed runtime topology
- `next-orchestrator-spec.md` - OrchestratorService interface and behavior
- `next-data-flow-and-lifecycle.md` - authoritative state and metrics flow
- `next-scaling.md` - multi-node scaling modes and allocation logic
- `next-ui-architecture.md` - real-time display contract
- `next-operations-and-runbooks.md` - local and SPCS runbooks
- `next-multi-node-gap-analysis.md` - gaps, risks, and fixes
- `next-worker-implementation.md` - **complete worker implementation details**
  (CLI args, table schemas, SQL queries, state machine, pseudocode)

## Reiterated Constraints

- No DDL is executed at runtime.
- All schema changes are done via rerunnable DDL in `sql/schema/`.
- All run results and control-plane state live in `UNISTORE_BENCHMARK.TEST_RESULTS`.
- All configuration (templates + scenario config) lives in `UNISTORE_BENCHMARK.CONFIG`.
- All runs are template-based (templates stored in `UNISTORE_BENCHMARK.CONFIG.TEST_TEMPLATES`).
- Snowflake is the authoritative results store.
- Parent runs use `TEST_ID == RUN_ID`; child runs use `TEST_ID != RUN_ID`
  and point to the parent with `RUN_ID`.
- Warmup is a **run-level** concept to prime Snowflake compute. Workers joining
  after warmup ends start directly in MEASUREMENT phase.
