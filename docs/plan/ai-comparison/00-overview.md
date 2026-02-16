# AI-Powered Test Comparison Feature - Overview

**Document Version:** 1.4  
**Created:** 2026-02-11  
**Last Updated:** 2026-02-12  
**Status:** Planning Complete, Ready for Implementation  

---

## Document Index

This plan is split into multiple files for easier navigation:

| File | Sections | Description |
|------|----------|-------------|
| [00-overview.md](00-overview.md) | 1-7 | Executive summary, problem, knowns, assumptions, decisions |
| [01-architecture.md](01-architecture.md) | 8 | Three-layer architecture design |
| [02-scoring-contract.md](02-scoring-contract.md) | 9 | Hard gates, soft scoring, confidence bands |
| [03-derived-metrics.md](03-derived-metrics.md) | 10 | Metric calculations and definitions |
| [04-api-specs.md](04-api-specs.md) | 11 | API specifications |
| [05-ai-prompts-ui.md](05-ai-prompts-ui.md) | 12-13 | AI prompt enhancements and UI changes |
| [06-implementation.md](06-implementation.md) | 14-17 | Phases, testing, success metrics, risks |
| [07-agent-skill-strategy.md](07-agent-skill-strategy.md) | 19 | Cortex Agent & CoCo Skill hybrid strategy |
| [08-appendix.md](08-appendix.md) | 18, 20 | Future considerations, glossary, reference SQL |

---

## 1. Executive Summary

### Goal
Enhance AI analysis to automatically compare tests against historical baselines and find comparable runs, enabling users to understand performance changes in context.

### Design Principle
**Make it work -> make it right -> make it fast**

- First, deliver deterministic comparison using existing persisted data.
- Then improve correctness/quality with scoring and confidence tuning.
- Finally optimize with materialization only when measured latency requires it.

### Approach
Three-layer architecture:
1. **Deterministic Compare Engine** - SQL queries against existing data with explicit scoring
2. **AI Narrative Layer** - Single `AI_COMPLETE` call with rich comparison context
3. **Agentic Investigation** - (Future) Multi-hop tool calls for deep root cause analysis

### Key Decision
Start with a **compare service over existing data** before creating any new tables. Persist derived features only if latency becomes a problem.

---

## 2. Problem Statement

### Current State
- AI analysis operates on a single test in isolation
- No automatic comparison to previous runs of the same template
- No way to find similar tests for context
- Users must manually select tests to compare (max 2)
- Deep compare shows charts but no AI-powered insights

### Desired State
- AI analysis automatically includes historical context
- System identifies appropriate baselines (same template, recent runs)
- System suggests comparable tests with explicit similarity scores
- AI explains regressions, improvements, and trends
- Comparison confidence is clearly communicated

### User Stories
1. "How did this test do compared to previous runs?" → Auto-baseline comparison
2. "Is this a regression or normal variance?" → Statistical context (rolling median, confidence bands)
3. "What similar tests can I compare against?" → Scored comparable candidates
4. "Why is this test slower than before?" → (Future) Agentic root cause investigation

---

## 3. Knowns

### 3.1 Existing Data Structure

**Verified via SQL queries against production data:**

| Data Point | Location | Coverage |
|------------|----------|----------|
| Template ID | `TEST_CONFIG:template_id` | 100% of tests |
| Load Mode | `TEST_CONFIG:template_config:load_mode` (scenario fallback) | 100% |
| Scale Mode | `TEST_CONFIG:template_config:scaling:mode` | ~80% (some NULL) |
| Target Type | Explicit template field in `TEST_CONFIG:template_config` | 100% |
| Table Type | `TABLE_TYPE` column | 100% |
| Warehouse Size | `WAREHOUSE_SIZE` column | 100% |
| Target Concurrency | `CONCURRENT_CONNECTIONS` + template config fields (`start_concurrency`, scaling bounds) | 100% |
| Target QPS | `TEST_CONFIG:scenario:target_qps` | 100% for QPS mode |
| Read/Write Mix | `READ_OPERATIONS / TOTAL_OPERATIONS` | 100% |
| Query Patterns | `TEST_CONFIG:scenario:custom_queries` (CUSTOM mode), derived from `QUERY_EXECUTIONS` otherwise | Mixed by mode |
| Cache Mode | `TEST_CONFIG:template_config:use_cached_result` | 100% |
| Workload Mix | `TEST_CONFIG:template_config:custom_*_pct` | 100% |
| Duration | `DURATION_SECONDS` column | 100% |
| Performance Metrics | `QPS`, `P50/P95/P99_LATENCY_MS`, `ERROR_RATE` | 100% |
| FIND_MAX Steps | `CONTROLLER_STEP_HISTORY` table | 100% for FIND_MAX |

**Test Volume (as of 2026-02-11):**
- FIND_MAX_CONCURRENCY: 143 completed tests, 12 distinct templates
- CONCURRENCY: 123 completed tests, 18 distinct templates
- QPS: 117 completed tests, 10 distinct templates

### 3.2 Verified Query Capabilities

**Baseline candidate query works:**
```sql
-- Returns 8 candidates for template afd4d1b6-b9a1-46b1-baab-2fc82b6e9b4b
SELECT ... FROM TEST_RESULTS 
WHERE template_id = ? AND load_mode = ? AND table_type = ? AND status = 'COMPLETED'
```

**Rolling median calculation works:**
```sql
-- Successfully calculated: median_qps=45.4, p10=19.5, p90=49.1
SELECT MEDIAN(QPS), PERCENTILE_CONT(0.1), PERCENTILE_CONT(0.9) FROM baseline_candidates
```

**Delta calculation works:**
```sql
-- Calculated: +183.7% QPS vs median, +0.2% P95 vs median
SELECT (current - median) / median * 100 as delta_pct
```

### 3.3 Existing Comparison Features

| Feature | Status | Limitations |
|---------|--------|-------------|
| Basic Compare | ✅ Works | Max 2 tests, manual selection |
| Deep Compare | ✅ Works | Overlay charts, no AI insights |
| Search | ✅ Works | Text-based LIKE queries only |
| AI Analysis | ✅ Works | Single test only |
| Model fields | ❌ Unused | `comparison_baseline`, `comparison_metrics` exist but empty |

### 3.4 Current AI Analysis Pipeline

Located in `backend/api/routes/test_results.py`:
- `POST /api/tests/{test_id}/ai-analysis` - Main analysis endpoint
- `POST /api/tests/{test_id}/ai-chat` - Follow-up conversation endpoint
- Mode-specific prompt builders (`_build_concurrency_prompt`, `_build_qps_prompt`, `_build_find_max_prompt`)
- `AI_COMPLETE(...)` call with a single model invocation per request

---

## 4. Assumptions

### 4.1 Technical Assumptions

| Assumption | Basis | Risk if Wrong |
|------------|-------|---------------|
| Existing data is sufficient for comparison | Verified via SQL queries | Low - we validated this |
| Compare-context latency can meet configured SLO | Simple joins on ~400 tests | Medium - may need optimization at scale |
| Template ID is stable across runs | Observed in data | Low - it's a UUID |
| CONTROLLER_STEP_HISTORY has complete FIND_MAX data | Verified for test 382f1163 | Low - verified |

### 4.2 Product Assumptions

| Assumption | Basis | Risk if Wrong |
|------------|-------|---------------|
| Users want automatic baseline comparison | Expert DBA feedback | Low - standard practice |
| 5-10 baseline runs is sufficient for statistics | Statistical best practice | Low - adjustable parameter |
| Similarity score 0.65+ is "comparable enough" for non-FIND_MAX | Expert recommendation | Medium - may need tuning |
| Users understand confidence levels | UX assumption | Medium - may need education |

### 4.3 Performance Assumptions

| Assumption | Basis | Risk if Wrong |
|------------|-------|---------------|
| AI_COMPLETE latency is acceptable (~2-5s) | Current production behavior | Low - already accepted |
| Compare context adds overhead within configured SLA | Simple SQL queries | Medium - needs validation |
| No new table needed initially | Expert recommendation | Low - can add later if needed |

---

## 5. Unknowns

### 5.1 Critical Unknowns (Must Resolve Before Implementation)

| Unknown | Impact | Resolution Plan |
|---------|--------|-----------------|
| FIND_MAX_RESULT column population | Missing data for some tests | Derive from CONTROLLER_STEP_HISTORY |
| Template target-type field consistency | Impacts hard-gate filtering | Validate template field mapping in Phase 2 |
| Cross-template signature strategy for Phase 2 | Affects future expansion | Defer; keep same-template only in Phase 1 |

### 5.2 Known Unknowns (Can Resolve During Implementation)

| Unknown | Impact | Resolution Plan |
|---------|--------|-----------------|
| SQL canonicalization depth | Query pattern matching accuracy | Start simple, iterate if noisy |
| Similarity score thresholds | False positive/negative rate | Tune based on Phase 5 validation |
| UI layout for comparison panels | User experience | Design mockups, user testing |

### 5.3 Unknown Unknowns (Risks)

| Risk Category | Mitigation |
|---------------|------------|
| Edge cases in scoring | Extensive unit tests with real data |
| Cross-template comparison needs | Explicitly scoped out for v1 |
| Data quality issues | Validate steady-state quality before comparison |

---

## 6. Resolved Decisions

### 6.1 Product Decisions (Confirmed)

| # | Decision | Outcome |
|---|----------|---------|
| D1 | Baseline scope in Phase 1 | Same `template_id` only |
| D2 | Comparable scope in Phase 1 | Same `template_id` only; cross-template signatures deferred to Phase 2 |
| D3 | Baseline recency window | Last N runs **and** within 30 days |
| D4 | No baseline behavior | Show "No baseline" (do not auto-pivot to other templates in Phase 1) |
| D5 | Parent/child handling | Prefer parent rollups; exclude worker child rows from baseline/comparable sets |

### 6.2 Technical Decisions (Confirmed)

| # | Decision | Outcome |
|---|----------|---------|
| D6 | Target type source | Use explicit field from template snapshot in `TEST_CONFIG:template_config`; do not infer |
| D7 | SQL canonicalization depth | Literal stripping only (Phase 1) |
| D8 | Similarity precompute | No precomputed matrix in Phase 1 |
| D9 | Enrichment requirement | Not a hard exclusion; apply table-type-aware confidence adjustment |
| D10 | FIND_MAX quality approach | Use max-focused comparison (`best_stable_concurrency`, related max signals), not generic steady-state CV gate |

### 6.3 Operational Decisions (Confirmed)

| # | Decision | Outcome |
|---|----------|---------|
| D11 | Compare-context latency target | Configurable by test type/template (not a single global threshold) |
| D12 | Candidate transparency | Keep exclusion reason support; UI exposure is configurable |

---

## 7. Ruled Out Approaches

### 7.1 New Table First

**Approach:** Create `TEST_COMPARISON_METADATA` table before building service  
**Why Ruled Out:** Expert feedback - "Start with deterministic compare service over existing data, then persist derived features once scoring stabilizes"  
**Risk Avoided:** Premature optimization, schema churn as requirements evolve

### 7.2 Traditional Database Indexes

**Approach:** `CREATE INDEX` on comparison columns  
**Why Ruled Out:** Snowflake doesn't support traditional indexes; uses micro-partition pruning instead  
**Alternative:** Clustering keys, Search Optimization Service, Dynamic Tables

### 7.3 Cortex Agent for v1 Comparison

**Approach:** Use Snowflake Cortex Agents with tool-calling for comparison  
**Why Ruled Out for v1:** Expert feedback - "Only need agent-style orchestration when you want multi-hop tool calls at runtime, adaptive investigations"  
**When to Reconsider:** After deterministic + AI_COMPLETE path is stable for "investigate root cause" workflows

**Clarification (Added 2026-02-12):** Cortex Agent is NOT ruled out entirely—it's the **correct architecture** for:
- **Phase 7+**: Agentic investigation ("Why did this regress?")
- **Analysis queries**: Natural language → SQL over test results via Semantic Views
- **Multi-hop investigations**: Agent can call multiple tools to trace root causes

See [07-agent-skill-strategy.md](07-agent-skill-strategy.md) for the complete hybrid architecture recommendation.

### 7.4 Single Baseline Comparison

**Approach:** Compare only to the most recent previous run  
**Why Ruled Out:** Too noisy - single runs can be outliers  
**Alternative:** Rolling median over last N runs with P10-P90 confidence bands

### 7.5 Cross-Template Similarity

**Approach:** Find similar tests across different templates  
**Why Ruled Out:** Different templates = different workloads; comparisons would be misleading  
**When to Reconsider:** For "similar workload discovery" feature (separate from baseline comparison)

### 7.6 Generic Scoring Weights

**Approach:** Same similarity weights for all load modes  
**Why Ruled Out:** CONCURRENCY, QPS, and FIND_MAX measure fundamentally different things  
**Alternative:** Load-mode-specific scoring profiles

### 7.7 AI-Only Comparison

**Approach:** Let AI figure out what to compare without structured context  
**Why Ruled Out:** Unpredictable, expensive (multiple LLM calls), hard to debug  
**Alternative:** Deterministic engine provides facts, AI provides narrative

---

**Next:** [01-architecture.md](01-architecture.md) - Three-layer architecture design
