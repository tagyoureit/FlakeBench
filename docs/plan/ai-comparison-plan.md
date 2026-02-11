# AI-Powered Test Comparison Feature - Complete Plan

**Document Version:** 1.2  
**Created:** 2026-02-11  
**Status:** Planning Complete, Ready for Implementation  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Knowns](#3-knowns)
4. [Assumptions](#4-assumptions)
5. [Unknowns](#5-unknowns)
6. [Remaining Questions](#6-remaining-questions)
7. [Ruled Out Approaches](#7-ruled-out-approaches)
8. [Architecture](#8-architecture)
9. [Scoring Contract](#9-scoring-contract)
10. [Derived Metrics Definitions](#10-derived-metrics-definitions)
11. [API Specifications](#11-api-specifications)
12. [AI Prompt Enhancements](#12-ai-prompt-enhancements)
13. [UI Changes](#13-ui-changes)
14. [Implementation Phases](#14-implementation-phases)
15. [Testing Strategy](#15-testing-strategy)
16. [Success Metrics](#16-success-metrics)
17. [Risks and Mitigations](#17-risks-and-mitigations)
18. [Future Considerations](#18-future-considerations)
19. [Appendix](#19-appendix)

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

### 7.3 Cortex Agent for v1

**Approach:** Use Snowflake Cortex Agents with tool-calling for comparison  
**Why Ruled Out:** Expert feedback - "Only need agent-style orchestration when you want multi-hop tool calls at runtime, adaptive investigations"  
**When to Reconsider:** After deterministic + AI_COMPLETE path is stable for "investigate root cause" workflows

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

## 8. Architecture

### 8.1 Three-Layer Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    User Request: "Analyze test XYZ"                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                 LAYER 1: Deterministic Compare Engine                       │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ Baseline        │  │ Similarity      │  │ Trend           │             │
│  │ Candidates      │  │ Scoring         │  │ Analysis        │             │
│  │                 │  │                 │  │                 │             │
│  │ • Same template │  │ • Hard gates    │  │ • Rolling median│             │
│  │ • Same load mode│  │ • Soft scores   │  │ • P10-P90 bands │             │
│  │ • Same table    │  │ • Confidence    │  │ • Direction     │             │
│  │ • Last N runs   │  │ • Exclusions    │  │ • Slope         │             │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘             │
│           │                    │                    │                       │
│           └────────────────────┼────────────────────┘                       │
│                                │                                            │
│                                ▼                                            │
│                    ┌───────────────────────┐                                │
│                    │   Compare Context     │                                │
│                    │   (Structured JSON)   │                                │
│                    └───────────────────────┘                                │
│                                                                             │
│  Latency Target: configurable per template/test type                        │
│  Data Source: Existing TEST_RESULTS + QUERY_EXECUTIONS + CONTROLLER_STEP_HISTORY │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     LAYER 2: AI Narrative (AI_COMPLETE)                     │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  Input:                                                                     │
│  • Current test metrics (existing prompt)                                   │
│  • Compare context from Layer 1 (NEW)                                       │
│  • Historical comparison section in prompt (NEW)                            │
│                                                                             │
│  Output:                                                                    │
│  • Natural language analysis                                                │
│  • Regression/improvement assessment                                        │
│  • Trend interpretation                                                     │
│  • Actionable recommendations                                               │
│                                                                             │
│  Latency: ~2-5s (existing)       Model: claude-4-sonnet via AI_COMPLETE    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              LAYER 3: Agentic Investigation (FUTURE - Phase 7)              │
│  ─────────────────────────────────────────────────────────────────────────  │
│                                                                             │
│  Use Case: "Why did this test regress?"                                     │
│                                                                             │
│  Tools:                                                                     │
│  • find_similar_tests() - Query comparable runs                             │
│  • get_test_details() - Fetch specific test data                            │
│  • compare_metrics() - Calculate deltas                                     │
│  • get_warehouse_history() - Check infrastructure changes                   │
│  • get_step_history() - FIND_MAX progression analysis                       │
│                                                                             │
│  Trigger: Explicit user request for root cause investigation                │
│  Prerequisites: Layer 1+2 stable and measurable                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Data Flow

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ TEST_RESULTS │────▶│   Compare    │────▶│  AI_COMPLETE │
│    Table     │     │   Service    │     │    Call      │
└──────────────┘     └──────────────┘     └──────────────┘
        │                   │                    │
        │                   │                    │
        ▼                   ▼                    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│ CONTROLLER_  │     │   Compare    │     │   Enhanced   │
│ STEP_HISTORY │     │   Context    │     │   Analysis   │
│    Table     │     │    JSON      │     │   Response   │
└──────────────┘     └──────────────┘     └──────────────┘
```

### 8.3 Component Responsibilities

| Component | Responsibility | Location |
|-----------|---------------|----------|
| `_fetch_baseline_candidates()` | Query same-template parent runs within 30 days | `test_results.py` |
| `_calculate_similarity_score()` | Score comparable tests (same-template in Phase 1) | `test_results.py` |
| `_calculate_rolling_statistics()` | Median, P10, P90, trend | `test_results.py` |
| `_build_compare_context()` | Assemble JSON for AI | `test_results.py` |
| `_generate_comparison_prompt()` | Add comparison section to prompt | `test_results.py` |
| `GET /api/tests/{id}/compare-context` | Expose comparison data | `test_results.py` |

---

## 9. Scoring Contract

### 9.1 Hard Gates (Must Pass ALL)

| Gate | Field | Rationale |
|------|-------|-----------|
| Same Template (Phase 1) | `TEST_CONFIG:template_id` | Phase 1 is same-template only |
| Same Load Mode | `TEST_CONFIG:template_config:load_mode` (scenario fallback) | CONCURRENCY/QPS/FIND_MAX are incomparable |
| Same Table Type | `TABLE_TYPE` | STANDARD/HYBRID/INTERACTIVE/DYNAMIC/POSTGRES behave differently |
| Same Target Type | Explicit template field in `TEST_CONFIG:template_config` | Do not infer engine type |
| Completed Status | `STATUS = 'COMPLETED'` | Failed/aborted tests are invalid |
| Parent Rollup Only | `TEST_ID = RUN_ID` (or equivalent parent-row test) | Avoid duplicate/partial worker rows |
| Quality Gate (non-FIND_MAX) | `steady_state_quality >= 0.5` | Unstable tests shouldn't be baselines |
| FIND_MAX Max-Focused Gate | `best_stable_concurrency` present | FIND_MAX compares discovered max behavior |

**Important:** Enrichment completeness is **not** a hard gate in Phase 1. It adjusts confidence using table-type-aware rules (for example, low enrichment on HYBRID is expected and not auto-excluded).

### 9.2 Soft Scoring - CONCURRENCY Mode

| Dimension | Weight | Calculation | Notes |
|-----------|--------|-------------|-------|
| Scale Mode Match | 0.20 | 1.0 if match, 0.5 if one NULL, 0.0 otherwise | AUTO vs FIXED vs BOUNDED |
| Concurrency Similarity | 0.25 | `clamp(1 - abs(a-b) / max(max(a,b),1), 0, 1)` | Target thread count |
| Duration Similarity | 0.15 | `clamp(1 - abs(a-b) / max(max(a,b),1), 0, 1)` | Tolerance ±15% |
| Warehouse Size Match | 0.20 | 1.0 exact, 0.5 adjacent, 0.0 otherwise | XS→S→M→L→XL→2XL... |
| Workload Mix Similarity | 0.15 | `1 - abs(read_pct_a - read_pct_b) / 100` | Read/write balance |
| Cache Mode Match | 0.05 | 1.0 if both match | Cached vs uncached |

### 9.3 Soft Scoring - QPS Mode

| Dimension | Weight | Calculation | Notes |
|-----------|--------|-------------|-------|
| Target QPS Similarity | 0.30 | `clamp(1 - abs(a-b) / max(max(a,b),1), 0, 1)` | Primary comparator |
| Scale Mode Match | 0.15 | 1.0 if match | How system responds to load |
| Duration Similarity | 0.15 | `clamp(1 - abs(a-b) / max(max(a,b),1), 0, 1)` | Tolerance ±15% |
| Warehouse Size Match | 0.20 | 1.0 exact, 0.5 adjacent | Capacity affects sustainability |
| Workload Mix Similarity | 0.15 | `1 - abs(read_pct_a - read_pct_b) / 100` | Read/write balance |
| Cache Mode Match | 0.05 | 1.0 if match | Affects latency dramatically |

### 9.4 Soft Scoring - FIND_MAX_CONCURRENCY Mode

| Dimension | Weight | Calculation | Notes |
|-----------|--------|-------------|-------|
| Best Stable Concurrency Similarity | 0.40 | `clamp(1 - abs(a-b) / max(max(a,b),1), 0, 1)` | Primary FIND_MAX objective |
| Best Stable QPS Similarity | 0.25 | `clamp(1 - abs(a-b) / max(max(a,b),1), 0, 1)` | Max-throughput comparability |
| Degradation Point Similarity | 0.10 | Same formula on degradation concurrency | Tail behavior near ceiling |
| Warehouse Size Match | 0.10 | 1.0 exact, 0.5 adjacent | Capacity normalization |
| Workload Mix Similarity | 0.10 | `1 - abs(read_pct_a - read_pct_b) / 100` | Affects ceiling |
| Cache Mode Match | 0.05 | 1.0 if match | Can shift max behavior |

### 9.5 Confidence Bands

| Score Range | Confidence | UI Treatment | Interpretation |
|-------------|------------|--------------|----------------|
| ≥ 0.85 | HIGH | Green indicator | Very comparable, deltas are meaningful |
| 0.70 - 0.84 | MEDIUM | Yellow indicator | Comparable with noted caveats |
| 0.55 - 0.69 | LOW | Orange indicator | Loosely comparable, interpret carefully |
| < 0.55 | EXCLUDED | Gray, show reasons | Not comparable, explain why |

### 9.6 Exclusion Reason Codes

| Code | Message Template | Example |
|------|------------------|---------|
| `WH_SIZE_DIFF` | "Warehouse size differs: {a} vs {b}" | "Warehouse size differs: XSMALL vs 4XLARGE" |
| `DURATION_DIFF` | "Duration differs by {pct}% ({a}s vs {b}s)" | "Duration differs by 85% (60s vs 300s)" |
| `SCALE_MODE_DIFF` | "Different scale mode: {a} vs {b}" | "Different scale mode: FIXED vs AUTO" |
| `CONCURRENCY_DIFF` | "Concurrency differs by {pct}%" | "Concurrency differs by 300%" |
| `WORKLOAD_DIFF` | "Workload mix differs: {a}% vs {b}% reads" | "Workload mix differs: 90% vs 10% reads" |
| `LOW_QUALITY` | "Baseline test had unstable steady state (quality={score})" | "Baseline had unstable steady state (quality=0.3)" |
| `CACHE_MODE_DIFF` | "Cache mode differs: {a} vs {b}" | "Cache mode differs: enabled vs disabled" |

---

## 10. Derived Metrics Definitions

### 10.1 SUSTAINED_QPS

**Definition:** Median QPS during the measurement phase (excluding warmup)

```python
def calculate_sustained_qps(
    metrics_snapshots: list[dict],
    warmup_seconds: int
) -> dict:
    """
    Args:
        metrics_snapshots: Time-series with {"elapsed_seconds": float, "qps": float}
        warmup_seconds: Warmup period from test config
    
    Returns:
        {
            "median": float,        # P50 of measurement phase
            "p10": float,           # 10th percentile (lower bound)
            "p90": float,           # 90th percentile (upper bound)  
            "cv": float,            # Coefficient of variation (stddev/mean)
            "sample_count": int,    # Number of data points used
            "valid": bool           # True if enough samples
        }
    """
    # Filter to measurement phase only
    measurement = [
        s["qps"] for s in metrics_snapshots
        if s["elapsed_seconds"] > warmup_seconds and s["qps"] > 0
    ]
    
    if len(measurement) < 5:
        return {"valid": False, "reason": "INSUFFICIENT_SAMPLES"}
    
    import numpy as np
    mean = np.mean(measurement)
    
    return {
        "median": float(np.percentile(measurement, 50)),
        "p10": float(np.percentile(measurement, 10)),
        "p90": float(np.percentile(measurement, 90)),
        "cv": float(np.std(measurement) / mean) if mean > 0 else 0,
        "sample_count": len(measurement),
        "valid": True
    }
```

### 10.2 STEADY_STATE_QUALITY (CONCURRENCY/QPS)

**Definition:** Score (0.0-1.0) indicating test stability and validity for comparison

```python
def calculate_steady_state_quality(
    qps_cv: float,
    latency_cv: float,
    warmup_completed: bool,
    error_rate: float,
    duration_pct_in_steady_state: float
) -> dict:
    """
    Returns:
        {
            "score": float,         # 0.0 to 1.0
            "grade": str,           # "EXCELLENT", "GOOD", "FAIR", "POOR"
            "issues": list[str]     # Reasons for deductions
        }
    """
    score = 1.0
    issues = []
    
    # QPS stability (weight: 0.35)
    if qps_cv > 0.30:
        score -= 0.35
        issues.append(f"High QPS variance (CV={qps_cv:.2f})")
    elif qps_cv > 0.15:
        score -= 0.15
        issues.append(f"Moderate QPS variance (CV={qps_cv:.2f})")
    
    # Latency stability (weight: 0.25)
    if latency_cv > 0.50:
        score -= 0.25
        issues.append(f"High latency variance (CV={latency_cv:.2f})")
    elif latency_cv > 0.25:
        score -= 0.12
        issues.append(f"Moderate latency variance (CV={latency_cv:.2f})")
    
    # Warmup completion (weight: 0.20)
    if not warmup_completed:
        score -= 0.20
        issues.append("Warmup period incomplete")
    
    # Error rate (weight: 0.10)
    if error_rate > 0.05:
        score -= 0.10
        issues.append(f"High error rate ({error_rate*100:.1f}%)")
    elif error_rate > 0.01:
        score -= 0.05
        issues.append(f"Elevated error rate ({error_rate*100:.1f}%)")
    
    # Steady state duration (weight: 0.10)
    if duration_pct_in_steady_state < 0.5:
        score -= 0.10
        issues.append(f"Short steady state ({duration_pct_in_steady_state*100:.0f}% of test)")
    
    score = max(0.0, score)
    
    if score >= 0.85:
        grade = "EXCELLENT"
    elif score >= 0.70:
        grade = "GOOD"
    elif score >= 0.50:
        grade = "FAIR"
    else:
        grade = "POOR"
    
    return {"score": score, "grade": grade, "issues": issues}
```

### 10.2A FIND_MAX_PEAK_COMPARABILITY

**Definition:** Max-focused quality and comparability metrics for `FIND_MAX_CONCURRENCY`.

```python
def calculate_find_max_peak_quality(steps: list[dict]) -> dict:
    """
    Emphasize the discovered max, not steady-state CV.

    Returns:
        {
            "valid": bool,
            "best_stable_concurrency": int | None,
            "best_stable_qps": float | None,
            "degradation_concurrency": int | None,
            "step_count": int,
            "quality_score": float,  # 0.0-1.0
            "issues": list[str]
        }
    """
    issues: list[str] = []
    stable_steps = [s for s in steps if s.get("outcome") == "STABLE"]
    degraded_steps = [s for s in steps if s.get("outcome") == "DEGRADED"]

    if not stable_steps:
        return {
            "valid": False,
            "best_stable_concurrency": None,
            "best_stable_qps": None,
            "degradation_concurrency": None,
            "step_count": len(steps),
            "quality_score": 0.0,
            "issues": ["No stable step found"],
        }

    best = max(stable_steps, key=lambda s: float(s.get("concurrency") or 0))
    later_degraded = [
        s for s in degraded_steps if int(s.get("step") or 0) > int(best.get("step") or 0)
    ]
    degradation = later_degraded[0] if later_degraded else None

    score = 1.0
    if len(steps) < 3:
        score -= 0.25
        issues.append("Low step count")
    if degradation is None:
        score -= 0.10
        issues.append("No explicit degradation point")

    return {
        "valid": True,
        "best_stable_concurrency": int(best.get("concurrency") or 0),
        "best_stable_qps": float(best.get("qps") or 0.0),
        "degradation_concurrency": (
            int(degradation.get("concurrency") or 0) if degradation else None
        ),
        "step_count": len(steps),
        "quality_score": max(0.0, score),
        "issues": issues,
    }
```

### 10.3 SQL Canonicalization

**Definition:** Normalize SQL for fingerprint comparison

```python
import re
import hashlib

def canonicalize_sql(sql: str) -> str:
    """
    Normalize SQL to enable pattern matching across runs.
    
    Rules applied:
    1. Strip numeric literals → ?
    2. Strip UUID literals → ?
    3. Strip quoted string literals → ?
    4. Strip timestamp/date literals → ?
    5. Collapse whitespace
    6. Uppercase SQL keywords (preserve quoted identifiers)
    """
    # Strip numeric literals (integers and decimals)
    sql = re.sub(r'\b\d+\.?\d*\b', '?', sql)
    
    # Strip UUID literals (in single quotes)
    sql = re.sub(
        r"'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'",
        '?',
        sql,
        flags=re.IGNORECASE
    )
    
    # Strip single-quoted string literals (but preserve double-quoted identifiers)
    sql = re.sub(r"'[^']*'", '?', sql)
    
    # Strip ISO timestamp literals
    sql = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?', '?', sql)
    
    # Strip date literals
    sql = re.sub(r'\d{4}-\d{2}-\d{2}', '?', sql)
    
    # Collapse whitespace
    sql = ' '.join(sql.split())
    
    return sql.strip()


def sql_fingerprint(sql: str) -> str:
    """Generate SHA-256 hash of canonicalized SQL."""
    canonical = canonicalize_sql(sql)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]
```

### 10.4 Workload Signature

**Definition:** Hash representing the workload shape for quick comparison

```python
def workload_signature(
    read_pct: float,
    write_pct: float,
    query_kinds: dict[str, float]  # {"POINT_LOOKUP": 0.9, "RANGE_SCAN": 0.1}
) -> str:
    """
    Generate signature for workload shape.
    
    Buckets percentages to reduce noise:
    - 0-10% → 0
    - 11-30% → 25
    - 31-70% → 50
    - 71-90% → 75
    - 91-100% → 100
    """
    def bucket(pct: float) -> int:
        if pct <= 10:
            return 0
        elif pct <= 30:
            return 25
        elif pct <= 70:
            return 50
        elif pct <= 90:
            return 75
        else:
            return 100
    
    # Sort query kinds for deterministic hashing
    sorted_kinds = sorted(query_kinds.items())
    kinds_str = ",".join(f"{k}:{bucket(v*100)}" for k, v in sorted_kinds)
    
    signature = f"R{bucket(read_pct)}W{bucket(write_pct)}|{kinds_str}"
    return hashlib.sha256(signature.encode()).hexdigest()[:12]
```

### 10.5 FIND_MAX Best Stable (Derived from Step History)

**Definition:** Extract best stable concurrency from CONTROLLER_STEP_HISTORY when FIND_MAX_RESULT is empty

```python
def derive_find_max_best_stable(steps: list[dict]) -> dict:
    """
    Derive best stable concurrency from step history.
    
    Args:
        steps: List of {"step": int, "concurrency": int, "qps": float, 
                        "outcome": str, "stop_reason": str}
    
    Returns:
        {
            "best_stable_concurrency": int,
            "best_stable_qps": float,
            "degradation_concurrency": int or None,
            "degradation_reason": str or None,
            "total_steps": int
        }
    """
    stable_steps = [s for s in steps if s["outcome"] == "STABLE"]
    degraded_steps = [s for s in steps if s["outcome"] == "DEGRADED"]
    
    if not stable_steps:
        return {
            "best_stable_concurrency": None,
            "best_stable_qps": None,
            "degradation_concurrency": steps[0]["concurrency"] if steps else None,
            "degradation_reason": "Never achieved stability",
            "total_steps": len(steps)
        }
    
    # Best stable = highest concurrency that was stable
    best = max(stable_steps, key=lambda s: s["concurrency"])
    
    # Degradation = first degradation after best stable
    later_degraded = [s for s in degraded_steps if s["step"] > best["step"]]
    degradation = later_degraded[0] if later_degraded else None
    
    return {
        "best_stable_concurrency": best["concurrency"],
        "best_stable_qps": best["qps"],
        "degradation_concurrency": degradation["concurrency"] if degradation else None,
        "degradation_reason": degradation["stop_reason"] if degradation else None,
        "total_steps": len(steps)
    }
```

---

## 11. API Specifications

### 11.1 GET /api/tests/{test_id}/compare-context

**Purpose:** Return all comparison data needed for AI analysis

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `baseline_count` | int | 5 | Number of baseline runs to consider |
| `comparable_limit` | int | 5 | Max comparable candidates to return |
| `min_similarity` | float | 0.55 | Minimum similarity score |
| `include_excluded` | bool | false | Include excluded candidates with reasons |

**Response Schema:**
```json
{
  "test_id": "string (UUID)",
  "template_id": "string (UUID)",
  "load_mode": "string (CONCURRENCY|QPS|FIND_MAX_CONCURRENCY)",
  
  "baseline": {
    "available": "boolean",
    "candidate_count": "integer",
    "used_count": "integer",
    "rolling_median": {
      "qps": "number",
      "p50_latency_ms": "number",
      "p95_latency_ms": "number",
      "p99_latency_ms": "number",
      "error_rate_pct": "number"
    },
    "confidence_band": {
      "qps_p10": "number",
      "qps_p90": "number",
      "latency_p10": "number",
      "latency_p90": "number"
    },
    "quality_filter_applied": "boolean",
    "quality_threshold": "number"
  },
  
  "vs_previous": {
    "test_id": "string (UUID)",
    "test_date": "string (ISO 8601)",
    "similarity_score": "number (0-1)",
    "confidence": "string (HIGH|MEDIUM|LOW)",
    "deltas": {
      "qps_delta_pct": "number",
      "p50_delta_pct": "number",
      "p95_delta_pct": "number",
      "p99_delta_pct": "number",
      "error_rate_delta_pct": "number"
    },
    "differences": ["string"]
  },
  
  "vs_median": {
    "qps_delta_pct": "number",
    "p95_delta_pct": "number",
    "verdict": "string (IMPROVED|REGRESSED|STABLE|INCONCLUSIVE)",
    "verdict_reasons": ["string"]
  },
  
  "trend": {
    "direction": "string (IMPROVING|REGRESSING|STABLE|INSUFFICIENT_DATA)",
    "qps_slope_per_run": "number",
    "p95_slope_per_run": "number",
    "sample_size": "integer",
    "r_squared": "number (goodness of fit)"
  },
  
  "comparable_runs": [
    {
      "test_id": "string (UUID)",
      "test_date": "string (ISO 8601)",
      "test_name": "string",
      "similarity_score": "number (0-1)",
      "confidence": "string (HIGH|MEDIUM|LOW)",
      "score_breakdown": {
        "scale_mode": "number",
        "concurrency": "number",
        "duration": "number",
        "warehouse": "number",
        "workload": "number",
        "cache": "number"
      },
      "match_reasons": ["string"],
      "differences": ["string"],
      "metrics": {
        "qps": "number",
        "p95_latency_ms": "number",
        "error_rate_pct": "number"
      }
    }
  ],
  
  "exclusions": [
    {
      "test_id": "string (UUID)",
      "score": "number",
      "reasons": ["string"]
    }
  ],
  
  "metadata": {
    "computed_at": "string (ISO 8601)",
    "computation_time_ms": "integer",
    "data_freshness": "string (ISO 8601)"
  }
}
```

**Example Response:**
```json
{
  "test_id": "382f1163-f01e-4e7b-9c9b-ff31f1894476",
  "template_id": "afd4d1b6-b9a1-46b1-baab-2fc82b6e9b4b",
  "load_mode": "FIND_MAX_CONCURRENCY",
  
  "baseline": {
    "available": true,
    "candidate_count": 8,
    "used_count": 5,
    "rolling_median": {
      "qps": 45.4,
      "p95_latency_ms": 961.4,
      "error_rate_pct": 0.0
    },
    "confidence_band": {
      "qps_p10": 19.5,
      "qps_p90": 49.1
    }
  },
  
  "vs_previous": {
    "test_id": "3b296cf0-1409-450a-b49a-d3793524961d",
    "test_date": "2026-02-10T04:14:17Z",
    "similarity_score": 0.92,
    "confidence": "HIGH",
    "deltas": {
      "qps_delta_pct": 281.4,
      "p95_delta_pct": 16.8
    }
  },
  
  "vs_median": {
    "qps_delta_pct": 135.2,
    "p95_delta_pct": -0.6,
    "verdict": "IMPROVED"
  },
  
  "trend": {
    "direction": "IMPROVING",
    "qps_slope_per_run": 12.3,
    "sample_size": 5
  },
  
  "comparable_runs": [
    {
      "test_id": "de220197-8df8-4842-ae7a-99768974c219",
      "similarity_score": 0.88,
      "confidence": "HIGH",
      "match_reasons": [
        "Same template and load mode",
        "Same warehouse size (MEDIUM)",
        "Same workload mix (100% reads)"
      ],
      "differences": [
        "Duration: 267s vs 300s"
      ],
      "metrics": {
        "qps": 43.9,
        "p95_latency_ms": 953.3
      }
    }
  ]
}
```

**Error Responses:**
| Status | Condition | Response |
|--------|-----------|----------|
| 404 | Test not found | `{"error": "Test not found", "test_id": "..."}` |
| 400 | Invalid parameters | `{"error": "Invalid parameter", "details": "..."}` |

### 11.2 Enhanced POST /api/tests/{test_id}/ai-analysis

**Changes:** Add optional `include_comparison` request-body field

**New Request Field (JSON body):**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `include_comparison` | bool | true | Include comparison context in AI analysis |

**Response Changes:**
Add `comparison_summary` field to response:
```json
{
  "analysis": "...",
  "comparison_summary": {
    "baseline_available": true,
    "vs_median_verdict": "IMPROVED",
    "qps_delta_pct": 135.2,
    "trend_direction": "IMPROVING",
    "confidence": "HIGH"
  }
}
```

---

## 12. AI Prompt Enhancements

### 12.1 New Prompt Section: Historical Comparison Context

Insert after test metrics section, before analysis instructions:

```
HISTORICAL COMPARISON CONTEXT:
=============================

Baseline Information:
- Template: {template_name} (ID: {template_id})
- Baseline set: {baseline_count} previous runs of this template
- Baseline period: {oldest_date} to {newest_date}

Rolling Median (last {baseline_count} runs):
- QPS: {median_qps} (range: {p10_qps} - {p90_qps})
- P95 Latency: {median_p95}ms (range: {p10_p95} - {p90_p95}ms)
- Error Rate: {median_error_rate}%

This Test vs Previous Run ({previous_date}):
- QPS: {current_qps} vs {previous_qps} ({qps_delta:+.1f}%)
- P95 Latency: {current_p95}ms vs {previous_p95}ms ({p95_delta:+.1f}%)
- Comparison confidence: {confidence}

This Test vs Rolling Median:
- QPS: {qps_vs_median_delta:+.1f}% {qps_verdict}
- P95 Latency: {p95_vs_median_delta:+.1f}% {p95_verdict}
- Overall verdict: {overall_verdict}

Trend Analysis (last {trend_sample_size} runs):
- Direction: {trend_direction}
- QPS trend: {qps_trend:+.1f} per run
- Statistical confidence: {trend_confidence}

{comparable_context}
```

### 12.2 Comparable Context Template

Only include if comparable runs exist with score >= 0.70:

```
Comparable Test Context:
The following test is highly comparable (similarity: {similarity_score:.0%}):
- Test: {comparable_test_name} ({comparable_date})
- Similarities: {match_reasons}
- Differences: {differences}
- That test achieved: {comparable_qps} QPS, {comparable_p95}ms P95
- Implication: {implication}
```

### 12.3 Updated Analysis Instructions

Add to existing instructions:

```
When comparing to historical data:
1. **Regression Assessment**: Is this test worse than the baseline median? By how much?
2. **Variance Check**: Is the delta within normal variance (P10-P90 range)?
3. **Trend Interpretation**: Is performance improving, degrading, or stable over time?
4. **Comparable Insights**: What can we learn from similar tests?

Use comparison confidence levels:
- HIGH confidence: Deltas are meaningful, make specific recommendations
- MEDIUM confidence: Note caveats, hedge recommendations
- LOW confidence: Emphasize limited comparability, focus on absolute metrics
```

---

## 13. UI Changes

### 13.1 Test Detail Page Enhancements

**New Section: "Performance Trend"**
- Location: Above AI Analysis section
- Content:
  - Sparkline showing QPS over last N runs
  - Delta vs previous run (with color: green=better, red=worse)
  - Delta vs median (with confidence indicator)
  - Trend direction badge (↑ Improving, ↓ Regressing, → Stable)

**Mockup:**
```
┌─────────────────────────────────────────────────────────────┐
│ Performance Trend                              [HIGH conf.] │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  QPS History (last 5 runs)                                  │
│  ▁▃▅▆█  Current: 106.8 QPS                                 │
│                                                             │
│  vs Previous:  +281.4% ↑    vs Median: +135.2% ↑           │
│                                                             │
│  Trend: IMPROVING (+12.3 QPS per run)                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**New Section: "Comparable Runs"**
- Location: Sidebar or collapsible panel
- Content:
  - List of top 3 comparable tests
  - Similarity score badge
  - Quick metrics comparison
  - Link to deep compare

### 13.2 AI Analysis Section Changes

- Add "Comparison Context" indicator showing:
  - Whether baseline was found
  - Confidence level
  - Number of comparable runs used
- Link to detailed compare-context JSON

### 13.3 Deep Compare Page Enhancements

- Add "Auto-Select Baseline" button
  - Automatically selects previous run of same template
- Add "Suggested Comparisons" panel
  - Shows top comparable candidates
  - One-click to add to comparison

---

## 14. Implementation Phases

### Phase 1: Scoring Contract Definition ✅ COMPLETE
**Deliverables:**
- [x] Document hard gates
- [x] Document soft scoring by load mode
- [x] Define confidence bands
- [x] Define exclusion reason codes
- [x] Define derived metric calculations
- [x] Review and approval

**Status:** Complete (this document)

### Phase 2: Compare Service Implementation
**Deliverables:**
- [ ] `_fetch_baseline_candidates()` function
- [ ] `_calculate_similarity_score()` function (3 load-mode variants)
- [ ] `_calculate_rolling_statistics()` function
- [ ] `_calculate_trend()` function
- [ ] `_derive_find_max_best_stable()` function
- [ ] `_build_compare_context()` function
- [ ] `GET /api/tests/{test_id}/compare-context` endpoint (parent-rollup only, 30-day baseline window)
- [ ] Unit tests with production data samples

**Estimated Effort:** 3-4 days  
**Dependencies:** None  
**Risks:** Query performance on large datasets

### Phase 3: AI Prompt Integration
**Deliverables:**
- [ ] Update `_generate_analysis_prompt()` with comparison section
- [ ] Conditional inclusion based on comparison availability
- [ ] Update `POST /api/tests/{test_id}/ai-analysis` endpoint
- [ ] Add `comparison_summary` to response
- [ ] Integration tests

**Estimated Effort:** 1-2 days  
**Dependencies:** Phase 2 complete  
**Risks:** Prompt length limits, AI interpretation quality

### Phase 4: UI Integration
**Deliverables:**
- [ ] Performance Trend component
- [ ] Comparable Runs panel
- [ ] AI Analysis comparison indicator
- [ ] Deep Compare auto-select baseline
- [ ] Deep Compare suggested comparisons

**Estimated Effort:** 2-3 days  
**Dependencies:** Phase 2 API complete  
**Risks:** UI/UX iteration cycles

### Phase 5: Validation and Tuning
**Deliverables:**
- [ ] Baseline precision measurement (target: >90%)
- [ ] Regression detection accuracy (target: >90%)
- [ ] Query latency profiling against per-template/test-type configured SLA
- [ ] Similarity threshold tuning
- [ ] User acceptance testing

**Estimated Effort:** 2-3 days  
**Dependencies:** Phases 2-4 complete  
**Risks:** May require scoring adjustments

### Phase 6: (Conditional) Derived Table
**Trigger:** Phase 5 shows compare-context latency exceeds configured SLA for the relevant template/test type

**Deliverables:**
- [ ] Design Snowflake-native schema (Dynamic Table)
- [ ] Create materialization logic
- [ ] Backfill historical tests
- [ ] Update compare service to use derived table
- [ ] Performance validation

**Estimated Effort:** 2-3 days  
**Dependencies:** Phase 5 latency results  
**May Not Be Needed:** If query performance is acceptable

### Phase 7: (Future) Agentic Investigation
**Trigger:** User demand for "why did this regress?" deep dives

**Deliverables:**
- [ ] Define tool contracts
- [ ] Implement Cortex Agent integration
- [ ] Create investigation workflow
- [ ] A/B test vs deterministic path
- [ ] Documentation

**Estimated Effort:** 5-7 days  
**Dependencies:** Phases 1-5 stable  
**Deferred:** Until Layer 1+2 proven and measured

---

## 15. Testing Strategy

### 15.1 Unit Tests

| Test Category | Coverage Target | Key Scenarios |
|---------------|-----------------|---------------|
| Hard gate filtering | 100% | All gate combinations |
| Soft scoring | 100% per load mode | Edge cases (NULL values, extreme ratios) |
| Confidence calculation | 100% | Boundary conditions |
| Rolling statistics | 100% | Empty data, single point, normal |
| Trend calculation | 100% | Flat, improving, regressing, insufficient |
| SQL canonicalization | 100% | All literal types, edge cases |

### 15.2 Integration Tests

| Test | Description | Data Source |
|------|-------------|-------------|
| Baseline query | Returns correct candidates | Production templates |
| Similarity scoring | Matches manual calculation | Known test pairs |
| Compare context assembly | All fields populated | Sample tests |
| AI prompt generation | Includes comparison section | Mock context |
| API response format | Matches schema | All endpoints |

### 15.3 Validation Tests (Phase 5)

| Metric | Method | Target |
|--------|--------|--------|
| Baseline precision | Expert review of 50 samples | >90% correct |
| Regression detection | Backtest on known regressions | >90% detected |
| False positive rate | Review flagged regressions | <10% |
| Latency P50 | APM monitoring | Within configured SLA by template/test type |
| Latency P95 | APM monitoring | Within configured SLA by template/test type |
| AI quality | Expert review of analyses | Improvement vs current |

### 15.4 Test Data

**Use existing production tests:**
- Template `afd4d1b6-b9a1-46b1-baab-2fc82b6e9b4b`: 8 FIND_MAX runs
- Various CONCURRENCY templates: 123 tests
- Various QPS templates: 117 tests

**Edge cases to create/simulate:**
- First run of new template (no baseline)
- Single baseline run
- All baselines excluded (low quality)
- Cross-warehouse size comparison
- Very old baselines (>30 days)

---

## 16. Success Metrics

### 16.1 Technical Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Compare context latency P50 | Within configured SLA by template/test type | APM |
| Compare context latency P95 | Within configured SLA by template/test type | APM |
| Baseline found rate | >90% | Log analysis |
| Comparable candidates found | >70% with 3+ | Log analysis |
| API error rate | <0.1% | Error monitoring |

### 16.2 Quality Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Baseline precision | >90% | Expert review |
| Regression detection rate | >90% | Backtest |
| False positive rate | <10% | Expert review |
| AI mentions comparison | 100% when available | Audit |

### 16.3 User Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Feature adoption | >50% of analyses use comparison | Analytics |
| Deep compare usage | +20% increase | Analytics |
| User satisfaction | >4.0/5.0 | Survey |

---

## 17. Risks and Mitigations

### 17.1 Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Query latency too high | Medium | High | Phase 6 derived table, query optimization |
| Scoring produces poor matches | Medium | Medium | Phase 5 tuning, expert validation |
| AI misinterprets comparison data | Low | Medium | Clear prompt structure, testing |
| Data quality issues | Low | Medium | Steady-state quality filtering |

### 17.2 Product Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Users don't understand confidence levels | Medium | Medium | UI education, tooltips |
| Comparison adds noise, not signal | Low | High | User testing, feedback loops |
| Feature scope creep | Medium | Medium | Strict phase boundaries |

### 17.3 Operational Risks

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Increased AI_COMPLETE costs | Low | Low | Context is small, single call |
| Backward compatibility | Low | Low | Additive changes only |

---

## 18. Future Considerations

### 18.1 Cross-Template Similarity (Phase 2 Candidate)

**Concept:** Find tests with similar workloads across different templates

**Why Deferred from Phase 1:**
- Phase 1 is intentionally same-template for trust and determinism
- Cross-template comparability needs canonical workload signatures and tighter validation
- Higher false positive risk without tuned signature rules

**When to Reconsider (Phase 2):**
- Phase 1 baseline/comparable quality targets are met
- Canonical workload signatures are validated on real data
- Users request "find similar workloads across templates"

### 18.2 Automated Regression Alerts

**Concept:** Proactively notify users when tests regress

**Why Deferred:**
- Requires baseline to be established first
- Notification infrastructure not in place
- False positive risk must be minimized first

**When to Reconsider:**
- Phase 5 shows >95% regression detection accuracy
- User demand for proactive alerts
- Notification system available

### 18.3 ML-Based Similarity

**Concept:** Use embeddings for semantic similarity

**Why Deferred:**
- Deterministic scoring is interpretable and debuggable
- Embedding infrastructure not in place
- Current approach should be sufficient

**When to Reconsider:**
- Deterministic scoring proves insufficient
- Large scale (10K+ tests) makes exact matching impractical
- Embedding infrastructure available

### 18.4 Multi-Run Comparison

**Concept:** Compare runs of runs (aggregate analysis)

**Why Deferred:**
- Individual test comparison is prerequisite
- Adds significant complexity
- Lower priority user need

**When to Reconsider:**
- Phase 1-5 complete and stable
- User demand for batch comparison
- Run-level aggregation needed

---

## 19. Appendix

### 19.1 Glossary

| Term | Definition |
|------|------------|
| **Baseline** | Set of previous runs of the same template used for comparison |
| **Hard Gate** | Filter that must pass for any comparison (template, load mode, etc.) |
| **Soft Score** | Weighted similarity metric for ranking comparable tests |
| **Confidence** | Level of trust in comparison (HIGH/MEDIUM/LOW) |
| **Rolling Median** | Median of last N baseline runs |
| **Trend** | Direction of performance change over recent runs |
| **Compare Context** | Structured JSON with all comparison data |
| **Steady-State Quality** | Stability score for CONCURRENCY/QPS comparisons |
| **FIND_MAX Peak Quality** | Max-focused comparability using best-stable/degradation points |
| **SQL Fingerprint** | Hash of canonicalized SQL for pattern matching |
| **Workload Signature** | Hash of workload shape for quick comparison |

### 19.2 SQL Queries (Reference)

**Baseline Candidates Query:**
```sql
WITH current_test AS (
    SELECT 
        TEST_ID,
        TEST_CONFIG:template_id::STRING as template_id,
        COALESCE(TEST_CONFIG:template_config:load_mode::STRING, TEST_CONFIG:scenario:load_mode::STRING) as load_mode,
        TABLE_TYPE
    FROM {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_RESULTS
    WHERE TEST_ID = ?
)
SELECT 
    t.TEST_ID,
    t.QPS,
    t.P95_LATENCY_MS,
    t.ERROR_RATE,
    t.START_TIME,
    ROW_NUMBER() OVER (ORDER BY t.START_TIME DESC) as recency_rank
FROM {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_RESULTS t
JOIN current_test c ON 
    t.TEST_CONFIG:template_id::STRING = c.template_id
    AND COALESCE(t.TEST_CONFIG:template_config:load_mode::STRING, t.TEST_CONFIG:scenario:load_mode::STRING) = c.load_mode
    AND t.TABLE_TYPE = c.TABLE_TYPE
WHERE t.TEST_ID != c.TEST_ID
  AND t.STATUS = 'COMPLETED'
  AND (
      t.RUN_ID IS NULL
      OR t.TEST_ID = t.RUN_ID
  ) -- prefer parent rollups; exclude child worker rows
  AND t.START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
ORDER BY t.START_TIME DESC
LIMIT 10;
```

**Rolling Statistics Query:**
```sql
SELECT 
    COUNT(*) as sample_count,
    MEDIAN(QPS) as median_qps,
    PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY QPS) as p10_qps,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY QPS) as p90_qps,
    MEDIAN(P95_LATENCY_MS) as median_p95,
    PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY P95_LATENCY_MS) as p10_p95,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY P95_LATENCY_MS) as p90_p95
FROM baseline_candidates
WHERE recency_rank <= 5;
```

### 19.3 Snowflake-Native Materialization Pattern (Phase 6)

Apply only if compare-context latency exceeds configured SLA.

```sql
CREATE OR REPLACE DYNAMIC TABLE {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_COMPARISON_FEATURES
    TARGET_LAG = '1 hour'
    WAREHOUSE = '{COMPUTE_WAREHOUSE}'
AS
SELECT
    tr.TEST_ID,
    tr.RUN_ID,
    tr.TABLE_TYPE,
    tr.WAREHOUSE_SIZE,
    tr.STATUS,
    tr.START_TIME,
    tr.QPS,
    tr.P95_LATENCY_MS,
    tr.ERROR_RATE,
    tr.TEST_CONFIG:template_id::STRING AS TEMPLATE_ID,
    COALESCE(tr.TEST_CONFIG:template_config:load_mode::STRING, tr.TEST_CONFIG:scenario:load_mode::STRING) AS LOAD_MODE,
    tr.TEST_CONFIG:template_config:scaling:mode::STRING AS SCALE_MODE
FROM {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_RESULTS tr
WHERE tr.STATUS = 'COMPLETED'
  AND (tr.RUN_ID IS NULL OR tr.TEST_ID = tr.RUN_ID);

ALTER TABLE {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_COMPARISON_FEATURES
    CLUSTER BY (TEMPLATE_ID, LOAD_MODE, TABLE_TYPE, START_TIME);

ALTER TABLE {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_COMPARISON_FEATURES
    ADD SEARCH OPTIMIZATION ON EQUALITY(TEST_ID);
```

### 19.4 File Locations

| Component | File | Notes |
|-----------|------|-------|
| AI Analysis Endpoint | `backend/api/routes/test_results.py` | `POST /api/tests/{test_id}/ai-analysis` |
| Prompt Builders | `backend/api/routes/test_results.py` | Mode-specific prompt construction |
| AI_COMPLETE Call | `backend/api/routes/test_results.py` | Single-call narrative layer |
| Step History Fetch | `backend/api/routes/test_results.py` | FIND_MAX derivations |
| Deep Compare JS | `backend/static/js/compare_detail.js` | Existing comparison UI |
| History Page JS | `backend/static/js/history.js` | Compare selection workflow |
| Test Model | `backend/models/test_result.py` | Unused comparison fields noted |

### 19.5 Related Documents

- `docs/plan/comparison-feature.md` - Original feature roadmap
- Test data analysis queries in Snowflake worksheet

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.2 | 2026-02-11 | AI Assistant | Migrated remaining useful content from superseded design doc (design principle + Snowflake-native materialization pattern), corrected load-mode SQL example in appendix, and prepared plan as single source of truth |
| 1.1 | 2026-02-11 | AI Assistant | Aligned with implementation realities and user decisions: same-template Phase 1 scope, explicit target type from template, FIND_MAX max-focused quality, 30-day baseline window, parent-rollup preference, enrichment as confidence modifier, POST ai-analysis alignment, and configurable latency SLAs |
| 1.0 | 2026-02-11 | AI Assistant | Initial complete plan |

---

**End of Document**
