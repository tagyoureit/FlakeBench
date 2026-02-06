# Project Plan Overview

This document outlines the transition plan to the new multi-worker architecture.

## Terminology

- **WORKER_ID**: Unique identifier for a worker process (string, e.g., `worker-0`)
- **WORKER_GROUP_ID**: Zero-based index for deterministic sharding (integer)
- **TARGET_CONNECTIONS**: Number of concurrent queries a worker should maintain
- **Warmup**: Run-level phase to prime Snowflake compute (not per-worker)
- **Multi-worker**: Architecture where 1+ workers execute workload in parallel

## Phase Summary

| Phase | Goal | Status |
|-------|------|--------|
| 1: Foundation | Basic controller/worker, templates, Snowflake persistence | ✅ Complete |
| 2: Architecture Hardening | Unify single/multi-worker paths, authoritative state | 🟡 In Progress |
| 3: SPCS Readiness | Containerization, service specs, image registry | ⬜ Not Started |
| 4: Advanced Scale | 20+ workers, 5000+ connections, batch ingestion | ⬜ Not Started |

## Phase 1: Foundation (Complete)

- [x] Basic controller and worker implementation.
- [x] Initial templates and workload generation.
- [x] Snowflake persistence for results.

## Phase 2: Architecture Hardening (Current)

**Goal**: Unify single/multi-worker paths and establish authoritative state.

**Prerequisites**:
- Snowflake Enterprise Edition (required for Hybrid Tables)
- AWS or Azure commercial region (Hybrid Tables not available on GCP)

**Schema Layout**:
- `FLAKEBENCH.TEST_RESULTS`: all running tests, results, and control-plane state.
- `FLAKEBENCH.CONFIG`: templates and scenario config.

See [phase-2-checklist.md](phase-2-checklist.md) for detailed implementation tasks.

## Phase 3: SPCS Readiness

**Goal**: Prepare for running in Snowflake Native Apps / SPCS.

- [ ] **Containerization**: Dockerfiles for Controller, Orchestrator, Worker.
- [ ] **Service Specification**: SPCS YAML definitions.
- [ ] **Image Registry**: Push workflow to Snowregistry.

## Phase 4: Advanced Scale

**Goal**: Support 50+ workers and high-throughput ingestion (5,000 QPS total).

See [query-execution-streaming.md](query-execution-streaming.md) for detailed design.

### 4.1 Query Execution Streaming

**Problem**: Current approach writes all query executions at test shutdown:
- 50k record cap per worker loses data at high QPS
- "Thundering herd" when 100+ workers write simultaneously
- Memory pressure on long-running tests

**Solution**: Stream query executions during test via background flush task.

- [ ] **QueryExecutionStreamer class**: New component for buffered streaming
  - Background flush every 5s OR 1000 records
  - Uses control pool (separate warehouse from benchmark)
  - Fail test on write failure
  - Graceful shutdown with p99-based timeout

- [ ] **Convert QUERY_EXECUTIONS to hybrid table**: Row-level locking for concurrent INSERTs
  - Add PRIMARY KEY on EXECUTION_ID
  - Migration script for existing data

- [ ] **Sampling for high-QPS scenarios**: Reduce storage while maintaining statistical accuracy
  - Never drop errors (100% retention)
  - Never drop warmup queries (100% retention)
  - Sample measurement queries based on QPS
  - Track sample_rate in TEST_RESULTS for downstream correction

- [ ] **Downstream query updates**: Adjust calculations for sampled data
  - Scale COUNTs by 1/sample_rate
  - Update QPS calculations
  - Add UI indicators for sampled data

### 4.2 Distributed Coordination (Future)

- [ ] **Leader election**: If Orchestrator needs HA
- [ ] **Cross-region support**: Multi-region worker deployment

## Migration Strategy

### Strategy: Roll Forward

- We are **not** migrating legacy data. The schema changes for Multi-Worker
  (Hybrid Tables, Parent/Child linking) are significant.
- The UI targets new runs only. Legacy runs are out of scope.

## Reiterated Constraints

- No DDL is executed at runtime.
- Schema changes are rerunnable DDL in `sql/schema/`.
- Templates remain stored in `FLAKEBENCH.TEST_RESULTS.TEST_TEMPLATES`
  with `CONFIG` as the authoritative payload for runs.

## Related Documents

- [decisions.md](decisions.md) - Recorded implementation decisions
- [phase-2-checklist.md](phase-2-checklist.md) - Detailed Phase 2 tasks (2.1-2.21)
- [traceability.md](traceability.md) - Docs-to-task mapping
