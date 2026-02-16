# Dashboard Pages Feature - Overview

**Document Version:** 1.0  
**Created:** 2026-02-15  
**Status:** Planning  

---

## Document Index

| File | Description |
|------|-------------|
| [00-overview.md](00-overview.md) | Executive summary, problem statement, decisions |
| [01-architecture.md](01-architecture.md) | Technical architecture, data flow, component design |
| [02-sql-schema.md](02-sql-schema.md) | Dynamic tables, views, SQL definitions |
| [03-api-endpoints.md](03-api-endpoints.md) | FastAPI endpoint specifications |
| [04-ui-templates.md](04-ui-templates.md) | HTMX/Alpine.js template designs |
| [05-implementation.md](05-implementation.md) | Phases, tasks, acceptance criteria |

---

## 1. Executive Summary

### Goal
Create two new dashboard pages for principal architects to evaluate table type performance and analyze template behavior with statistical rigor and cost visibility.

### Pages

| Page | Primary Question | Target User |
|------|------------------|-------------|
| **Table Type Comparison** | "Which table type should I use?" | Architects evaluating technology choices |
| **Template Analysis** | "How does this template perform over time?" | Architects + Engineers debugging issues |

### Design Principles
1. **Cost-first**: Every metric paired with cost context
2. **Statistical rigor**: Badges, confidence indicators, significance testing
3. **Reuse existing**: Leverage comparison modules, cost calculator, statistical functions
4. **Progressive disclosure**: Summary cards → detailed charts → raw data

---

## 2. Problem Statement

### Current State
- No aggregate view of performance across table types
- No way to see "which table type wins for my workload?"
- Per-template analysis requires manual test selection
- Statistical analysis exists but isn't surfaced in dedicated views
- Cost data scattered, not prominently displayed for decisions

### Desired State
- Single page showing table type comparison with recommendations
- Template deep-dive with distribution analysis, trends, outliers
- Cost metrics prominently displayed alongside performance
- Statistical badges (winner, significant, stable) for quick decisions
- Historical all-time view with optional date filters

---

## 3. Knowns

### 3.1 Existing Data
| Data | Location | Coverage |
|------|----------|----------|
| Test metrics | `TEST_RESULTS` table | 100% |
| Table types | `TABLE_TYPE` column (STANDARD, HYBRID, INTERACTIVE, DYNAMIC, POSTGRES) | 100% |
| Template ID | `TEST_CONFIG:template_id` | 100% |
| Cost/credits | `WAREHOUSE_CREDITS_USED` + `CostCalculator` | 100% |
| Statistical functions | `backend/api/routes/test_results_modules/statistics.py` | Ready |
| Comparison logic | `backend/api/routes/test_results_modules/comparison*.py` | Ready |

### 3.2 Test Volume (Estimated)
- ~400+ completed tests
- 5 table types
- ~40 distinct templates
- Growing daily

### 3.3 Existing Views
| View | Purpose | Reusable? |
|------|---------|-----------|
| `V_LATEST_TEST_RESULTS` | Last 7 days summary | Partial (too narrow) |
| `V_METRICS_BY_MINUTE` | Time-series aggregation | Yes |
| `V_CLUSTER_BREAKDOWN` | Per-cluster stats | Yes |

### 3.4 Existing Stored Procedures
| Procedure | Purpose | Reusable? |
|-----------|---------|-----------|
| `COST_CALCULATOR_V2` | Credit/cost analysis | Yes |
| `CALCULATE_ROLLING_STATISTICS` | Baseline stats | Yes |
| `CALCULATE_TREND_ANALYSIS` | Trend detection | Yes |
| `MANN_WHITNEY_U_TEST` | Significance testing | Yes |

---

## 4. Decisions

### D1: Dynamic Tables vs Views vs API-Side

**Decision:** Hybrid approach

| Data Type | Approach | Rationale |
|-----------|----------|-----------|
| Table type aggregates | **Dynamic Table** | Frequently queried, stable schema, benefits from materialization |
| Template statistics | **Dynamic Table** | Per-template rollups benefit from pre-computation |
| Cost rollups | **Dynamic Table** | Historical cost tracking needed |
| Per-test details | **API-side** | Ad-hoc filtering, user-specific |
| Real-time calculations | **API-side** | Uses existing Python modules |

### D2: Page Structure

**Decision:** Two pages (not three)

| Option | Pros | Cons | Chosen |
|--------|------|------|--------|
| 1 page | Simple | Conflicting purposes, crowded | No |
| 2 pages | Clear separation, progressive disclosure | Navigation required | **Yes** |
| 3 pages | Maximum separation | Over-engineered, compare exists | No |

### D3: Recommendation Engine

**Decision:** Weighted scoring based on workload type

- OLTP workloads: Weight p95 latency highest
- Analytics workloads: Weight QPS highest
- Mixed workloads: Balance cost efficiency + latency

### D4: Statistical Badges

**Decision:** Use confidence-based badges

| Badge | Criteria |
|-------|----------|
| **Winner** | Statistically significant (p < 0.05), >10% better |
| **Stable** | CV < 15% |
| **Trending Up/Down** | R² > 0.7, slope significant |
| **Anomaly** | >3σ from rolling median |

### D5: Cost Display Priority

**Decision:** Cost per 1K operations as primary metric

- Most intuitive for architects ("how much to run 1M queries?")
- Normalizes across different test durations
- Secondary: Total credits, hourly rate, QPS per dollar

---

## 5. Ruled Out Approaches

### 5.1 Streamlit Dashboard
**Why Ruled Out:** Project uses HTMX/FastAPI/Alpine.js stack  
**Alternative:** Native HTMX templates with Chart.js

### 5.2 Real-time Live Panel
**Why Ruled Out:** User requested historical-only  
**When to Reconsider:** Future enhancement if users request

### 5.3 Pre-computed Similarity Matrix
**Why Ruled Out:** Same-template comparison only in v1  
**Alternative:** Calculate similarity on-demand

### 5.4 Single Global Winner
**Why Ruled Out:** "Best" depends on workload type  
**Alternative:** Per-workload-type recommendations

---

## 6. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Dynamic table refresh costs | Medium | Use downstream refresh (triggered by TEST_RESULTS inserts) |
| Slow aggregation queries | Medium | Index/clustering on TABLE_TYPE, TEMPLATE_ID |
| Statistical edge cases | Low | Minimum N=5 tests for significance claims |
| UI performance with charts | Low | Lazy-load charts, paginate tables |

---

## 7. Success Metrics

| Metric | Target |
|--------|--------|
| Page load time | < 2 seconds |
| Aggregation query time | < 500ms |
| User can identify "best table type" | Within 10 seconds of page load |
| Cost visibility | Present in 100% of comparison views |

---

**Next:** [01-architecture.md](01-architecture.md) - Technical architecture design
