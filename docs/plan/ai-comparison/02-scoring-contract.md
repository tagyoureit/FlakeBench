# AI-Powered Test Comparison - Scoring Contract

**Part of:** [AI-Powered Test Comparison Feature](00-overview.md)

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
| Best Stable Concurrency Similarity | 0.35 | `clamp(1 - abs(a-b) / max(max(a,b),1), 0, 1)` | Primary capacity indicator |
| Best Stable QPS Similarity | 0.25 | `clamp(1 - abs(a-b) / max(max(a,b),1), 0, 1)` | Throughput at capacity |
| Degradation Point Similarity | 0.15 | Same formula on degradation concurrency | Where ceiling begins |
| Steps to Degradation | 0.10 | Same formula on step count | Convergence rate |
| QPS Efficiency | 0.10 | `clamp(1 - abs(eff_a - eff_b) / max(max(eff_a,eff_b),1), 0, 1)` where `eff = qps/concurrency` | Per-worker efficiency |
| Degradation Reason Match | 0.05 | 1.0 if same STOP_REASON category, 0.5 if related, 0.0 otherwise | Same failure mode? |

#### 9.4.1 FIND_MAX Key Metrics Definitions

**Best Stable Concurrency:** Highest concurrency level where step OUTCOME = 'STABLE' (from CONTROLLER_STEP_HISTORY). This is the primary capacity indicator—how many concurrent connections the system can handle while maintaining performance SLOs.

**Best Stable QPS:** Queries per second achieved at the best stable concurrency step. Represents peak sustainable throughput.

**Degradation Point:** First concurrency level where step OUTCOME = 'DEGRADED'. Indicates where the system ceiling begins. May be NULL if test hit max concurrency while still stable.

**Steps to Degradation:** Count of steps from start to first degradation. Measures how quickly the algorithm found the ceiling. Fewer steps = faster convergence.

**QPS Efficiency:** `best_stable_qps / best_stable_concurrency`. Measures throughput per worker. Higher efficiency = better resource utilization.

**Degradation Reason Categories:**
| Category | STOP_REASON Patterns | Meaning |
|----------|---------------------|---------|
| THROUGHPUT | "QPS dropped" | Hit throughput ceiling |
| LATENCY | "P95 latency increased", "P99 latency" | Hit latency ceiling |
| QUEUE | "Queue detected", "queued", "blocked" | Snowflake warehouse saturated |
| ERROR | "Error rate exceeded", "error threshold" | Error threshold breached |

#### 9.4.2 Step-by-Step Progression Comparison

When comparing two FIND_MAX runs, align steps by concurrency level (not step number) to identify where behavior diverges:

```
| Concurrency | Run A QPS | Run B QPS | Run A P95 | Run B P95 | Delta |
|-------------|-----------|-----------|-----------|-----------|-------|
| 5           | 120       | 115       | 45ms      | 48ms      | A: +4% QPS |
| 15          | 340       | 290       | 52ms      | 61ms      | A: +17% QPS |
| 25          | 480       | 410       | 68ms      | 89ms      | A: +17% QPS |
| 35          | 520       | DEGRADED  | 95ms      | -         | A reached higher ceiling |
| 45          | DEGRADED  | -         | -         | -         | A ceiling at 45 |
```

**Key Comparison Signals:**

1. **Ceiling Comparison:** Did `best_stable_concurrency` change?
   - Higher = capacity improved (can handle more concurrent connections)
   - Lower = regression in scaling capability

2. **Efficiency at Same Concurrency:** At matching concurrency levels, compare QPS
   - Large divergence early (at low concurrency) = fundamental performance difference
   - Divergence only at high concurrency = different scaling behavior

3. **Degradation Pattern Analysis:**
   - Same degradation reason = consistent ceiling behavior (compare ceiling levels)
   - Different reasons = different bottleneck (e.g., Run A hit latency ceiling, Run B hit queue saturation)

4. **Scaling Curve Shape:**
   - Linear QPS growth with concurrency = ideal scaling
   - Sub-linear early = resource contention or inefficiency
   - Plateau before degradation = approaching ceiling gracefully

#### 9.4.3 FIND_MAX Comparison for AI Prompt

Include in AI prompt when comparing FIND_MAX runs:

```
FIND_MAX Step Comparison:
- Current best stable: {current_best_cc} concurrent @ {current_best_qps} QPS
- Baseline best stable: {baseline_best_cc} concurrent @ {baseline_best_qps} QPS
- Capacity delta: {cc_delta:+d} connections ({cc_delta_pct:+.1f}%)
- Throughput delta at ceiling: {qps_delta:+.1f}%

Degradation Analysis:
- Current degraded at: {current_deg_cc} due to "{current_deg_reason}"
- Baseline degraded at: {baseline_deg_cc} due to "{baseline_deg_reason}"
- {degradation_interpretation}

Step Alignment (at matching concurrency levels):
{step_comparison_table}
```

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

### 9.7 Regression Classification Thresholds

Explicit thresholds for labeling performance changes. These are starting points—tune based on Phase 5 validation.

| Metric | Improvement | Neutral | Warning | Regression |
|--------|-------------|---------|---------|------------|
| QPS (all modes) | > +10% | ±10% | -10% to -20% | < -20% |
| P50 Latency | < -15% | ±15% | +15% to +30% | > +30% |
| P95 Latency | < -20% | ±20% | +20% to +40% | > +40% |
| P99 Latency | < -25% | ±25% | +25% to +50% | > +50% |
| Error Rate | < 0.1% | 0.1-1% | 1-5% | > 5% |
| FIND_MAX Best Concurrency | > +15% | ±15% | -15% to -25% | < -25% |
| FIND_MAX Best QPS | > +10% | ±10% | -10% to -20% | < -20% |

**Classification Logic:**
```python
def classify_change(metric: str, delta_pct: float) -> str:
    thresholds = REGRESSION_THRESHOLDS[metric]
    if delta_pct > thresholds["improvement"]:
        return "IMPROVEMENT"
    elif delta_pct < thresholds["regression"]:
        return "REGRESSION"
    elif delta_pct < thresholds["warning"]:
        return "WARNING"
    else:
        return "NEUTRAL"
```

**UI Treatment by Classification:**

| Classification | Color | Icon | User Action |
|---------------|-------|------|-------------|
| IMPROVEMENT | Green | ↑ | Consider as new baseline |
| NEUTRAL | Gray | → | No action needed |
| WARNING | Yellow | ⚠ | Investigate if trend continues |
| REGRESSION | Red | ↓ | Investigate root cause |

### 9.8 Suggested Next Steps by Classification

When AI analysis identifies poor performance, suggest concrete follow-up actions:

| Classification | Suggested Next Steps |
|---------------|---------------------|
| IMPROVEMENT | "Consider this the new baseline. Document what changed (config, code, infrastructure)." |
| NEUTRAL | "Performance consistent with historical runs. No action needed." |
| WARNING | "Performance degraded but within tolerance. Monitor next 2-3 runs. If trend continues, investigate." |
| REGRESSION | See detailed regression investigation steps below |

**Regression Investigation Prompts (include in AI analysis):**

For QPS regression:
- "Run FIND_MAX to check if capacity ceiling dropped"
- "Try larger warehouse size to test if resource-bound"
- "Check if query patterns changed vs. baseline"

For Latency regression:
- "Run with cache disabled to test cold path performance"
- "Check P99/P95 ratio—if P99 >> P95, investigate tail latency outliers"
- "Compare query execution plans if available"

For FIND_MAX regression:
- "Check degradation reason—different bottleneck than baseline?"
- "Compare step-by-step efficiency at matching concurrency levels"
- "Try with different warehouse size to isolate resource vs. workload issue"

For Error Rate increase:
- "Check error breakdown by query type"
- "Verify test configuration matches baseline (timeouts, retry settings)"
- "Check for infrastructure issues during test window"

---

**Previous:** [01-architecture.md](01-architecture.md) - Three-layer architecture design  
**Next:** [03-derived-metrics.md](03-derived-metrics.md) - Metric calculations and definitions
