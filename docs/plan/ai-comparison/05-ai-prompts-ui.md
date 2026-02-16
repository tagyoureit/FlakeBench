# AI-Powered Test Comparison - AI Prompts & UI Changes

**Part of:** [AI-Powered Test Comparison Feature](00-overview.md)

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

### 12.4 Regression Investigation Prompts

When performance is classified as WARNING or REGRESSION (per Section 9.7 thresholds), include actionable next steps in the AI analysis:

**Template for Regression Analysis:**
```
PERFORMANCE CLASSIFICATION: {classification}

{classification_explanation}

SUGGESTED INVESTIGATION STEPS:
{investigation_steps}

RECOMMENDED FOLLOW-UP TESTS:
{followup_tests}
```

**Investigation Steps by Regression Type:**

For QPS Regression (QPS < -20%):
```
SUGGESTED INVESTIGATION STEPS:
1. Check if query patterns changed vs. baseline configuration
2. Verify warehouse size and scaling mode match baseline
3. Review error rates - elevated errors reduce effective QPS

RECOMMENDED FOLLOW-UP TESTS:
- Run FIND_MAX_CONCURRENCY to check if capacity ceiling dropped
- Try larger warehouse size to test if resource-bound
- Run with cache disabled to isolate cache dependency
```

For Latency Regression (P95 > +40% or P99 > +50%):
```
SUGGESTED INVESTIGATION STEPS:
1. Check P99/P95 ratio - if P99 >> P95, investigate tail latency outliers
2. Compare latency distribution shape (KL divergence if available)
3. Review if cache hit rates changed

RECOMMENDED FOLLOW-UP TESTS:
- Run with result caching disabled to test cold path performance
- Run FIND_MAX variant to find latency ceiling
- Compare at lower concurrency to isolate contention effects
```

For FIND_MAX Regression (Best Concurrency < -25%):
```
SUGGESTED INVESTIGATION STEPS:
1. Compare degradation reasons - different bottleneck than baseline?
2. Analyze step-by-step efficiency at matching concurrency levels
3. Check if degradation occurred earlier in the progression

RECOMMENDED FOLLOW-UP TESTS:
- Run with different warehouse size to isolate resource vs. workload issue
- Run steady-state CONCURRENCY test at old ceiling level
- Check if workload mix shifted (read/write ratio)
```

For Error Rate Increase (Error Rate > 5%):
```
SUGGESTED INVESTIGATION STEPS:
1. Check error breakdown by query type - which operations are failing?
2. Verify test configuration matches baseline (timeouts, retry settings)
3. Check for infrastructure issues during test window

RECOMMENDED FOLLOW-UP TESTS:
- Run at lower concurrency to isolate load-dependent errors
- Run with extended timeouts to check for slow query timeouts
- Verify target system health before re-running
```

### 12.5 FIND_MAX-Specific Prompt Section

For FIND_MAX_CONCURRENCY tests, include detailed step comparison:

```
FIND_MAX PROGRESSION ANALYSIS:
==============================

Capacity Comparison:
- Current best stable: {current_best_cc} connections @ {current_best_qps} QPS
- Baseline best stable: {baseline_best_cc} connections @ {baseline_best_qps} QPS
- Capacity change: {cc_delta:+d} connections ({cc_delta_pct:+.1f}%)
- Throughput at ceiling: {qps_delta_pct:+.1f}%

Degradation Analysis:
- Current test degraded at {current_deg_cc} connections
  Reason: "{current_deg_reason}"
- Baseline degraded at {baseline_deg_cc} connections
  Reason: "{baseline_deg_reason}"
- Interpretation: {degradation_interpretation}

Step-by-Step Comparison (aligned by concurrency):
{step_comparison_table}

Scaling Efficiency:
- Current: {current_efficiency:.1f} QPS per connection at ceiling
- Baseline: {baseline_efficiency:.1f} QPS per connection at ceiling
- Efficiency change: {efficiency_delta:+.1f}%
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

**Previous:** [04-api-specs.md](04-api-specs.md) - API specifications  
**Next:** [06-implementation.md](06-implementation.md) - Implementation phases, testing, success metrics
