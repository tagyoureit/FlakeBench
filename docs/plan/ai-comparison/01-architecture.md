# AI-Powered Test Comparison - Architecture

**Part of:** [AI-Powered Test Comparison Feature](00-overview.md)

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

### 8.4 Comparison Strategy by Sample Size

Running 35+ benchmarks for statistical significance is unrealistic. The system uses different comparison strategies based on available baseline data:

| Baseline Count | Strategy | Display | Rationale |
|---------------|----------|---------|-----------|
| 0 | No comparison | "First run for this configuration" | Nothing to compare against |
| 1-2 | Direct comparison | "vs. previous: +X%" for each metric | Too few samples for statistics |
| 3-4 | Multi-run comparison | Show individual deltas, no averages | Limited but useful context |
| 5+ | Statistical comparison | Rolling median, P10-P90 bands, Mann-Whitney test | Sufficient for basic statistics |

**Direct Comparison (N < 3):**
- Compare current test to most recent run only
- Show raw deltas without statistical interpretation
- Label: "Compared to previous run (insufficient history for trends)"

**Multi-Run Comparison (N = 3-4):**
- Show comparison to last 2-3 runs individually
- Display each run's delta separately
- No averaging or median calculation
- Label: "Compared to recent runs (limited statistical context)"

**Statistical Comparison (N ≥ 5):**
- Calculate rolling median and P10-P90 confidence bands
- Apply Mann-Whitney U test for significance when labeling changes
- Weight recent runs higher (exponential decay: 1.0, 0.8, 0.64, 0.51...)
- Label changes as "likely real" (p < 0.05) or "within normal variance"

**Mann-Whitney U Test:**
Non-parametric significance test answering: "Are these two groups of measurements from different distributions?"
- Does not assume normal distribution (appropriate for latency data)
- Works with small samples (N ≥ 5 per group)
- Returns p-value: if p < 0.05, difference is likely real, not noise
- Use when comparing current test metrics against baseline set

**Recent Run Weighting:**
When computing comparisons, weight recent runs higher:
```python
weights = [0.8 ** i for i in range(len(baseline_runs))]
# Most recent: 1.0, then 0.8, 0.64, 0.51, 0.41...
```

---

**Previous:** [00-overview.md](00-overview.md) - Executive summary and decisions  
**Next:** [02-scoring-contract.md](02-scoring-contract.md) - Hard gates, soft scoring, confidence bands
