# AI-Powered Test Comparison - Derived Metrics Definitions

**Part of:** [AI-Powered Test Comparison Feature](00-overview.md)

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

### 10.5 Latency Distribution Analysis (KL Divergence)

**Definition:** Measure divergence between two latency distributions to detect shape changes not visible in percentile comparisons.

**Why This Matters:**
Even when P50/P95/P99 appear similar between runs, the latency distribution shape can change significantly:
- Bimodal vs. unimodal (cache hit/miss patterns)
- Tail shape changes (long tail vs. bounded tail)
- Distribution spread changes (tight vs. wide variance)

KL divergence quantifies these differences when percentiles alone miss them.

```python
import numpy as np
from typing import Optional

def calculate_latency_kl_divergence(
    latencies_a: list[float],
    latencies_b: list[float],
    num_bins: int = 20
) -> dict:
    """
    Calculate KL divergence between two latency distributions.
    
    Args:
        latencies_a: Latency samples from test A (current)
        latencies_b: Latency samples from test B (baseline)
        num_bins: Number of histogram bins (log-scale)
    
    Returns:
        {
            "kl_divergence": float,      # D_KL(A || B)
            "is_significant": bool,      # True if KL > 0.1
            "interpretation": str,       # Human-readable
            "histogram_a": list[float],  # Normalized bin counts
            "histogram_b": list[float],  # Normalized bin counts
            "bin_edges": list[float]     # Log-scale bin edges
        }
    """
    if len(latencies_a) < 10 or len(latencies_b) < 10:
        return {
            "kl_divergence": None,
            "is_significant": False,
            "interpretation": "Insufficient samples for distribution analysis",
            "histogram_a": [],
            "histogram_b": [],
            "bin_edges": []
        }
    
    # Use log-scale bins to handle latency's typical long-tail distribution
    all_latencies = latencies_a + latencies_b
    min_lat = max(min(all_latencies), 0.1)  # Avoid log(0)
    max_lat = max(all_latencies)
    
    bin_edges = np.logspace(np.log10(min_lat), np.log10(max_lat), num_bins + 1)
    
    # Compute histograms
    hist_a, _ = np.histogram(latencies_a, bins=bin_edges, density=True)
    hist_b, _ = np.histogram(latencies_b, bins=bin_edges, density=True)
    
    # Add small epsilon to avoid division by zero
    epsilon = 1e-10
    hist_a = hist_a + epsilon
    hist_b = hist_b + epsilon
    
    # Normalize
    hist_a = hist_a / hist_a.sum()
    hist_b = hist_b / hist_b.sum()
    
    # Calculate KL divergence: D_KL(A || B) = sum(A * log(A/B))
    kl_div = float(np.sum(hist_a * np.log(hist_a / hist_b)))
    
    # Interpret
    if kl_div > 0.5:
        interpretation = "Very different distributions - investigate cache behavior or query plan changes"
    elif kl_div > 0.2:
        interpretation = "Notably different distributions - tail behavior may have changed"
    elif kl_div > 0.1:
        interpretation = "Slightly different distributions - minor shape changes detected"
    else:
        interpretation = "Similar distributions - percentile comparison is sufficient"
    
    return {
        "kl_divergence": round(kl_div, 4),
        "is_significant": kl_div > 0.1,
        "interpretation": interpretation,
        "histogram_a": [round(x, 6) for x in hist_a.tolist()],
        "histogram_b": [round(x, 6) for x in hist_b.tolist()],
        "bin_edges": [round(x, 2) for x in bin_edges.tolist()]
    }
```

**AI Prompt Integration:**
When `is_significant` is True, include in AI analysis:
```
Latency Distribution Analysis:
The latency distribution shape changed significantly (KL divergence = {kl_divergence}).
{interpretation}

This may indicate:
- Cache behavior changes (hit/miss ratio shifted)
- Query plan differences
- Resource contention patterns changed

Even though percentile values appear similar, the underlying distribution differs.
```

**Thresholds:**
| KL Divergence | Classification | Action |
|---------------|----------------|--------|
| < 0.1 | Similar | Percentile comparison sufficient |
| 0.1 - 0.2 | Slightly different | Note in analysis, no alarm |
| 0.2 - 0.5 | Notably different | Flag for investigation |
| > 0.5 | Very different | Likely different workload or system behavior |

### 10.6 FIND_MAX Best Stable (Derived from Step History)

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

**Previous:** [02-scoring-contract.md](02-scoring-contract.md) - Hard gates, soft scoring, confidence bands  
**Next:** [04-api-specs.md](04-api-specs.md) - API specifications
