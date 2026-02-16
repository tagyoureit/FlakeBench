"""
AI prompt generation for test comparison.

Generates prompt sections for:
- Historical comparison context (Section 12.1)
- Comparable context (Section 12.2)
- Regression investigation steps (Section 12.4)
- FIND_MAX-specific analysis (Section 12.5)
"""

from __future__ import annotations

from typing import Any

from .comparison_scoring import classify_change, REGRESSION_THRESHOLDS


# =============================================================================
# MAIN PROMPT GENERATION
# =============================================================================

def generate_comparison_prompt(
    compare_context: dict[str, Any],
    load_mode: str,
) -> str:
    """
    Generate the historical comparison prompt section for AI analysis.

    This is inserted after the test metrics section in the AI prompt.

    Args:
        compare_context: Output from build_compare_context().
        load_mode: Test load mode (CONCURRENCY, QPS, FIND_MAX_CONCURRENCY).

    Returns:
        Formatted prompt string with comparison context.
    """
    if not compare_context or compare_context.get("error"):
        return ""

    baseline = compare_context.get("baseline", {})
    if not baseline.get("available"):
        return _generate_no_baseline_prompt(compare_context)

    sections = []

    # Header
    sections.append("HISTORICAL COMPARISON CONTEXT:")
    sections.append("=" * 30)
    sections.append("")

    # Baseline information
    sections.append(_generate_baseline_section(compare_context))

    # Rolling median section
    sections.append(_generate_rolling_median_section(compare_context))

    # vs Previous section
    vs_previous = compare_context.get("vs_previous")
    if vs_previous:
        sections.append(_generate_vs_previous_section(vs_previous))

    # vs Median section
    vs_median = compare_context.get("vs_median")
    if vs_median:
        sections.append(_generate_vs_median_section(vs_median))

    # Trend section
    trend = compare_context.get("trend", {})
    if trend.get("direction") != "INSUFFICIENT_DATA":
        sections.append(_generate_trend_section(trend))

    # Comparable runs section
    comparable_runs = compare_context.get("comparable_runs", [])
    if comparable_runs:
        sections.append(_generate_comparable_section(comparable_runs))

    # FIND_MAX specific section
    if load_mode.upper() == "FIND_MAX_CONCURRENCY":
        fm_section = _generate_find_max_section(compare_context)
        if fm_section:
            sections.append(fm_section)

    # Add analysis instructions
    sections.append(_generate_analysis_instructions())

    return "\n".join(sections)


def _generate_no_baseline_prompt(compare_context: dict[str, Any]) -> str:
    """Generate prompt when no baseline is available."""
    return """HISTORICAL COMPARISON CONTEXT:
==============================

Baseline Status: NOT AVAILABLE
This appears to be the first run for this configuration, or no comparable
baseline tests were found within the last 30 days.

Analysis should focus on:
1. Absolute performance metrics (QPS, latency, error rate)
2. Whether metrics meet expected thresholds for this workload type
3. Identification of any obvious performance issues

Note: Historical trend analysis will become available after 3+ runs.
"""


def _generate_baseline_section(compare_context: dict[str, Any]) -> str:
    """Generate the baseline information section."""
    baseline = compare_context.get("baseline", {})
    template_id = compare_context.get("template_id", "unknown")

    return f"""Baseline Information:
- Template ID: {template_id}
- Baseline set: {baseline.get('used_count', 0)} previous runs of this template
- Candidates found: {baseline.get('candidate_count', 0)}
- Baseline period: {baseline.get('oldest_date', 'N/A')} to {baseline.get('newest_date', 'N/A')}
"""


def _generate_rolling_median_section(compare_context: dict[str, Any]) -> str:
    """Generate the rolling median statistics section."""
    baseline = compare_context.get("baseline", {})
    median = baseline.get("rolling_median", {})
    band = baseline.get("confidence_band", {})

    qps = median.get("qps")
    p95 = median.get("p95_latency_ms")
    error = median.get("error_rate_pct")

    qps_range = ""
    if band.get("qps_p10") and band.get("qps_p90"):
        qps_range = f" (range: {band['qps_p10']:.1f} - {band['qps_p90']:.1f})"

    p95_range = ""
    if band.get("p95_p10") and band.get("p95_p90"):
        p95_range = f" (range: {band['p95_p10']:.1f} - {band['p95_p90']:.1f}ms)"

    # Pre-format values to handle None
    qps_str = f"{qps:.1f}" if qps is not None else "N/A"
    p95_str = f"{p95:.1f}" if p95 is not None else "N/A"
    error_str = f"{error:.2f}" if error is not None else "N/A"

    return f"""Rolling Median (last {baseline.get('used_count', 0)} runs):
- QPS: {qps_str}{qps_range}
- P95 Latency: {p95_str}ms{p95_range}
- Error Rate: {error_str}%
"""


def _generate_vs_previous_section(vs_previous: dict[str, Any]) -> str:
    """Generate the vs previous run comparison section."""
    deltas = vs_previous.get("deltas", {})

    qps_delta = deltas.get("qps_delta_pct")
    p95_delta = deltas.get("p95_delta_pct")

    qps_str = f"{qps_delta:+.1f}%" if qps_delta is not None else "N/A"
    p95_str = f"{p95_delta:+.1f}%" if p95_delta is not None else "N/A"

    return f"""This Test vs Previous Run ({vs_previous.get('test_date', 'unknown')}):
- QPS change: {qps_str}
- P95 Latency change: {p95_str}
- Comparison confidence: {vs_previous.get('confidence', 'N/A')}
"""


def _generate_vs_median_section(vs_median: dict[str, Any]) -> str:
    """Generate the vs rolling median comparison section."""
    qps_delta = vs_median.get("qps_delta_pct")
    p95_delta = vs_median.get("p95_delta_pct")
    verdict = vs_median.get("verdict", "INCONCLUSIVE")
    reasons = vs_median.get("verdict_reasons", [])

    qps_str = f"{qps_delta:+.1f}%" if qps_delta is not None else "N/A"
    p95_str = f"{p95_delta:+.1f}%" if p95_delta is not None else "N/A"

    # Add classification emojis
    qps_class = classify_change("qps", qps_delta) if qps_delta else "NEUTRAL"
    p95_class = classify_change("p95_latency", p95_delta) if p95_delta else "NEUTRAL"

    qps_indicator = _get_indicator(qps_class, is_latency=False)
    p95_indicator = _get_indicator(p95_class, is_latency=True)

    result = f"""This Test vs Rolling Median:
- QPS: {qps_str} {qps_indicator}
- P95 Latency: {p95_str} {p95_indicator}
- Overall verdict: {verdict}
"""
    if reasons:
        result += f"- Reasons: {'; '.join(reasons)}\n"

    return result


def _get_indicator(classification: str, is_latency: bool = False) -> str:
    """Get text indicator for classification."""
    indicators = {
        "IMPROVEMENT": "(IMPROVED)",
        "NEUTRAL": "(stable)",
        "WARNING": "(WARNING)",
        "REGRESSION": "(REGRESSION)",
    }
    return indicators.get(classification, "")


def _generate_trend_section(trend: dict[str, Any]) -> str:
    """Generate the trend analysis section."""
    direction = trend.get("direction", "INSUFFICIENT_DATA")
    slope = trend.get("slope")
    r_squared = trend.get("r_squared")
    sample_size = trend.get("sample_size", 0)

    slope_str = f"{slope:+.1f}" if slope is not None else "N/A"
    r_sq_str = f"{r_squared:.2f}" if r_squared is not None else "N/A"

    confidence = "low"
    if r_squared and r_squared >= 0.7:
        confidence = "high"
    elif r_squared and r_squared >= 0.4:
        confidence = "moderate"

    return f"""Trend Analysis (last {sample_size} runs):
- Direction: {direction}
- QPS trend: {slope_str} per run
- Statistical confidence: {confidence} (R²={r_sq_str})
"""


def _generate_comparable_section(comparable_runs: list[dict], base_url: str = "/dashboard/history") -> str:
    """Generate the comparable runs section with hyperlinks."""
    if not comparable_runs:
        return ""

    # Only include high-confidence comparables (>= 0.70)
    high_conf = [r for r in comparable_runs if r.get("similarity_score", 0) >= 0.70]

    if not high_conf:
        return ""

    best = high_conf[0]
    test_id = best.get('test_id', 'unknown')
    test_url = f"{base_url}/{test_id}"

    result = f"""Comparable Test Context:
The following test is highly comparable (similarity: {best['similarity_score']:.0%}):
- Test ID: {test_id}
- URL: {test_url}
- Date: {best.get('test_date', 'unknown')}
- That test achieved: {best.get('metrics', {}).get('qps', 'N/A'):.1f} QPS, {best.get('metrics', {}).get('p95_latency_ms', 'N/A'):.1f}ms P95
"""

    if best.get("differences"):
        result += f"- Differences: {', '.join(best['differences'])}\n"

    # If there are additional comparable tests, list them briefly
    if len(high_conf) > 1:
        result += "\nOther comparable tests:\n"
        for run in high_conf[1:4]:  # Show up to 3 more
            run_id = run.get('test_id', 'unknown')
            run_url = f"{base_url}/{run_id}"
            similarity = run.get('similarity_score', 0)
            qps = run.get('metrics', {}).get('qps')
            qps_str = f"{qps:.1f}" if qps else "N/A"
            result += f"- {run_id} ({similarity:.0%} similar, {qps_str} QPS): {run_url}\n"

    return result


def _generate_analysis_instructions() -> str:
    """Generate instructions for AI analysis."""
    return """
When comparing to historical data:
1. **Regression Assessment**: Is this test worse than the baseline median? By how much?
2. **Variance Check**: Is the delta within normal variance (P10-P90 range)?
3. **Trend Interpretation**: Is performance improving, degrading, or stable over time?
4. **Comparable Insights**: What can we learn from similar tests?

Use comparison confidence levels:
- HIGH confidence: Deltas are meaningful, make specific recommendations
- MEDIUM confidence: Note caveats, hedge recommendations
- LOW confidence: Emphasize limited comparability, focus on absolute metrics
"""


# =============================================================================
# FIND_MAX SPECIFIC PROMPTS (Section 12.5)
# =============================================================================

def _generate_find_max_section(compare_context: dict[str, Any]) -> str:
    """Generate FIND_MAX-specific comparison section."""
    vs_previous = compare_context.get("vs_previous")
    if not vs_previous:
        return ""

    # This would need actual FIND_MAX data from both tests
    # For now, return a template that can be filled in
    return """
FIND_MAX PROGRESSION ANALYSIS:
==============================

Note: Detailed step-by-step comparison requires FIND_MAX data from both tests.
Compare the following key metrics:

1. **Capacity Comparison**: Did best stable concurrency change?
   - Higher = capacity improved
   - Lower = regression in scaling capability

2. **Efficiency at Same Concurrency**: At matching concurrency levels, compare QPS
   - Large divergence early = fundamental performance difference
   - Divergence only at high concurrency = different scaling behavior

3. **Degradation Pattern**: Did the system hit the same bottleneck?
   - Same reason = consistent ceiling (compare levels)
   - Different reasons = different bottleneck
"""


def generate_find_max_comparison_prompt(
    current_steps: list[dict],
    baseline_steps: list[dict],
) -> str:
    """
    Generate detailed FIND_MAX step comparison for AI prompt.

    Args:
        current_steps: Step history from current test.
        baseline_steps: Step history from baseline test.

    Returns:
        Formatted comparison table and analysis.
    """
    if not current_steps or not baseline_steps:
        return ""

    # Find best stable for each
    def find_best_stable(steps: list[dict]) -> dict | None:
        stable = [s for s in steps if s.get("outcome") == "STABLE"]
        if not stable:
            return None
        return max(stable, key=lambda s: s.get("concurrency", 0))

    curr_best = find_best_stable(current_steps)
    base_best = find_best_stable(baseline_steps)

    if not curr_best or not base_best:
        return "Insufficient FIND_MAX data for comparison."

    # Calculate deltas
    cc_curr = curr_best.get("concurrency", 0)
    cc_base = base_best.get("concurrency", 0)
    qps_curr = curr_best.get("qps", 0)
    qps_base = base_best.get("qps", 0)

    cc_delta = cc_curr - cc_base
    cc_delta_pct = (cc_delta / cc_base * 100) if cc_base > 0 else 0
    qps_delta_pct = ((qps_curr - qps_base) / qps_base * 100) if qps_base > 0 else 0

    # Find degradation points
    def find_degradation(steps: list[dict]) -> dict | None:
        degraded = [s for s in steps if s.get("outcome") == "DEGRADED"]
        return degraded[0] if degraded else None

    curr_deg = find_degradation(current_steps)
    base_deg = find_degradation(baseline_steps)

    # Build step comparison table
    table_lines = ["| Concurrency | Current QPS | Baseline QPS | Current P95 | Baseline P95 | Delta |"]
    table_lines.append("|-------------|-------------|--------------|-------------|--------------|-------|")

    # Get all unique concurrency levels
    all_cc = sorted(set(
        [s.get("concurrency") for s in current_steps if s.get("concurrency")] +
        [s.get("concurrency") for s in baseline_steps if s.get("concurrency")]
    ))

    curr_by_cc = {s.get("concurrency"): s for s in current_steps}
    base_by_cc = {s.get("concurrency"): s for s in baseline_steps}

    for cc in all_cc[:10]:  # Limit rows
        curr = curr_by_cc.get(cc, {})
        base = base_by_cc.get(cc, {})

        curr_qps = curr.get("qps")
        base_qps = base.get("qps")
        curr_p95 = curr.get("p95_latency_ms")
        base_p95 = base.get("p95_latency_ms")

        curr_status = "DEGRADED" if curr.get("outcome") == "DEGRADED" else ""
        base_status = "DEGRADED" if base.get("outcome") == "DEGRADED" else ""

        curr_qps_str = f"{curr_qps:.1f}" if curr_qps else curr_status or "-"
        base_qps_str = f"{base_qps:.1f}" if base_qps else base_status or "-"
        curr_p95_str = f"{curr_p95:.1f}ms" if curr_p95 else "-"
        base_p95_str = f"{base_p95:.1f}ms" if base_p95 else "-"

        delta_str = ""
        if curr_qps and base_qps:
            delta = ((curr_qps - base_qps) / base_qps * 100)
            delta_str = f"Current: {delta:+.0f}%"

        table_lines.append(
            f"| {cc} | {curr_qps_str} | {base_qps_str} | {curr_p95_str} | {base_p95_str} | {delta_str} |"
        )

    # Degradation interpretation
    if curr_deg and base_deg:
        curr_reason = curr_deg.get("stop_reason", "unknown")
        base_reason = base_deg.get("stop_reason", "unknown")
        if curr_reason == base_reason:
            deg_interp = f"Same degradation reason ({curr_reason}) - compare ceiling levels"
        else:
            deg_interp = f"Different bottlenecks: current ({curr_reason}) vs baseline ({base_reason})"
    elif curr_deg:
        deg_interp = "Current test hit ceiling; baseline did not (or data missing)"
    elif base_deg:
        deg_interp = "Baseline hit ceiling; current did not - possible improvement"
    else:
        deg_interp = "Neither test reached degradation point"

    # Calculate efficiency
    curr_eff = qps_curr / cc_curr if cc_curr > 0 else 0
    base_eff = qps_base / cc_base if cc_base > 0 else 0
    eff_delta = ((curr_eff - base_eff) / base_eff * 100) if base_eff > 0 else 0

    return f"""
FIND_MAX PROGRESSION ANALYSIS:
==============================

Capacity Comparison:
- Current best stable: {cc_curr} connections @ {qps_curr:.1f} QPS
- Baseline best stable: {cc_base} connections @ {qps_base:.1f} QPS
- Capacity change: {cc_delta:+d} connections ({cc_delta_pct:+.1f}%)
- Throughput at ceiling: {qps_delta_pct:+.1f}%

Degradation Analysis:
- Current degraded at: {curr_deg.get('concurrency', 'N/A') if curr_deg else 'N/A'} due to "{curr_deg.get('stop_reason', 'N/A') if curr_deg else 'N/A'}"
- Baseline degraded at: {base_deg.get('concurrency', 'N/A') if base_deg else 'N/A'} due to "{base_deg.get('stop_reason', 'N/A') if base_deg else 'N/A'}"
- Interpretation: {deg_interp}

Step-by-Step Comparison (aligned by concurrency):
{chr(10).join(table_lines)}

Scaling Efficiency:
- Current: {curr_eff:.1f} QPS per connection at ceiling
- Baseline: {base_eff:.1f} QPS per connection at ceiling
- Efficiency change: {eff_delta:+.1f}%
"""


# =============================================================================
# REGRESSION INVESTIGATION PROMPTS (Section 12.4)
# =============================================================================

def generate_regression_investigation_prompt(
    classification: str,
    load_mode: str,
    deltas: dict[str, Any],
) -> str:
    """
    Generate regression investigation steps based on classification.

    Args:
        classification: Overall classification (REGRESSION, WARNING, etc.)
        load_mode: Test load mode.
        deltas: Dictionary of metric deltas.

    Returns:
        Formatted investigation steps for AI to include.
    """
    if classification not in ("REGRESSION", "WARNING"):
        return ""

    # Determine which metrics are problematic
    problems = []

    qps_delta = deltas.get("qps_delta_pct")
    if qps_delta is not None and classify_change("qps", qps_delta) in ("REGRESSION", "WARNING"):
        problems.append("qps")

    p95_delta = deltas.get("p95_delta_pct")
    if p95_delta is not None and classify_change("p95_latency", p95_delta) in ("REGRESSION", "WARNING"):
        problems.append("latency")

    error_delta = deltas.get("error_rate_delta_pct")
    if error_delta is not None:
        error_rate = deltas.get("error_rate", 0)
        if error_rate > 5:
            problems.append("error_rate")

    if not problems:
        return ""

    sections = [f"PERFORMANCE CLASSIFICATION: {classification}"]
    sections.append("")

    # Add problem-specific investigation steps
    if "qps" in problems:
        sections.append(_get_qps_investigation_steps(load_mode))

    if "latency" in problems:
        sections.append(_get_latency_investigation_steps(load_mode))

    if "error_rate" in problems:
        sections.append(_get_error_rate_investigation_steps())

    # Add FIND_MAX specific steps
    if load_mode.upper() == "FIND_MAX_CONCURRENCY":
        sections.append(_get_find_max_investigation_steps())

    return "\n".join(sections)


def _get_qps_investigation_steps(load_mode: str) -> str:
    """Get QPS regression investigation steps."""
    return """QPS Regression Investigation:
SUGGESTED INVESTIGATION STEPS:
1. Check if query patterns changed vs. baseline configuration
2. Verify warehouse size and scaling mode match baseline
3. Review error rates - elevated errors reduce effective QPS

RECOMMENDED FOLLOW-UP TESTS:
- Run FIND_MAX_CONCURRENCY to check if capacity ceiling dropped
- Try larger warehouse size to test if resource-bound
- Run with cache disabled to isolate cache dependency
"""


def _get_latency_investigation_steps(load_mode: str) -> str:
    """Get latency regression investigation steps."""
    return """Latency Regression Investigation:
SUGGESTED INVESTIGATION STEPS:
1. Check P99/P95 ratio - if P99 >> P95, investigate tail latency outliers
2. Compare latency distribution shape if available
3. Review if cache hit rates changed

RECOMMENDED FOLLOW-UP TESTS:
- Run with result caching disabled to test cold path performance
- Run FIND_MAX variant to find latency ceiling
- Compare at lower concurrency to isolate contention effects
"""


def _get_error_rate_investigation_steps() -> str:
    """Get error rate investigation steps."""
    return """Error Rate Investigation:
SUGGESTED INVESTIGATION STEPS:
1. Check error breakdown by query type - which operations are failing?
2. Verify test configuration matches baseline (timeouts, retry settings)
3. Check for infrastructure issues during test window

RECOMMENDED FOLLOW-UP TESTS:
- Run at lower concurrency to isolate load-dependent errors
- Run with extended timeouts to check for slow query timeouts
- Verify target system health before re-running
"""


def _get_find_max_investigation_steps() -> str:
    """Get FIND_MAX specific investigation steps."""
    return """FIND_MAX Regression Investigation:
SUGGESTED INVESTIGATION STEPS:
1. Compare degradation reasons - different bottleneck than baseline?
2. Analyze step-by-step efficiency at matching concurrency levels
3. Check if degradation occurred earlier in the progression

RECOMMENDED FOLLOW-UP TESTS:
- Run with different warehouse size to isolate resource vs. workload issue
- Run steady-state CONCURRENCY test at old ceiling level
- Check if workload mix shifted (read/write ratio)
"""


# =============================================================================
# SUMMARY GENERATION
# =============================================================================

# =============================================================================
# DEEP COMPARE PROMPT (Side-by-Side Benchmark Analysis)
# =============================================================================


def generate_deep_compare_prompt(
    test_a: dict[str, Any],
    test_b: dict[str, Any],
    statistics_a: dict[str, Any] | None = None,
    statistics_b: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Generate a deep comparison prompt for AI analysis of two benchmarks.

    This creates a side-by-side comparison of two specific test runs,
    highlighting configuration differences and performance deltas.

    Args:
        test_a: Primary test data (from /api/tests/{id}).
        test_b: Secondary test data (from /api/tests/{id}).
        statistics_a: Optional statistics for test A.
        statistics_b: Optional statistics for test B.

    Returns:
        Tuple of (prompt_string, deltas_dict) where deltas contains
        the calculated percentage differences between tests.
    """
    # Extract key metrics from test data or statistics
    qps_a = _get_metric(test_a, statistics_a, "qps", "throughput.avg_qps")
    qps_b = _get_metric(test_b, statistics_b, "qps", "throughput.avg_qps")
    p50_a = _get_metric(test_a, statistics_a, "p50_latency_ms", "latency.p50_ms")
    p50_b = _get_metric(test_b, statistics_b, "p50_latency_ms", "latency.p50_ms")
    p95_a = _get_metric(test_a, statistics_a, "p95_latency_ms", "latency.p95_ms")
    p95_b = _get_metric(test_b, statistics_b, "p95_latency_ms", "latency.p95_ms")
    p99_a = _get_metric(test_a, statistics_a, "p99_latency_ms", "latency.p99_ms")
    p99_b = _get_metric(test_b, statistics_b, "p99_latency_ms", "latency.p99_ms")
    error_a = _get_metric(test_a, statistics_a, "error_rate_pct", "errors.error_rate_pct")
    error_b = _get_metric(test_b, statistics_b, "error_rate_pct", "errors.error_rate_pct")

    # Calculate deltas (A vs B, positive means A is higher)
    deltas = {
        "qps_delta_pct": _calc_delta_pct(qps_a, qps_b),
        "p50_delta_pct": _calc_delta_pct(p50_a, p50_b),
        "p95_delta_pct": _calc_delta_pct(p95_a, p95_b),
        "p99_delta_pct": _calc_delta_pct(p99_a, p99_b),
        "error_rate_delta_pct": _calc_delta_pct(error_a, error_b),
    }

    # Identify configuration differences
    differences = _identify_config_differences(test_a, test_b)

    # Build prompt sections
    sections = []

    sections.append("DEEP COMPARISON ANALYSIS")
    sections.append("=" * 30)
    sections.append("")

    # Primary test (Test A)
    sections.append("PRIMARY TEST (Test A):")
    sections.append(_format_test_summary(test_a, qps_a, p50_a, p95_a, p99_a, error_a, statistics_a))
    sections.append("")

    # Secondary test (Test B)
    sections.append("SECONDARY TEST (Test B):")
    sections.append(_format_test_summary(test_b, qps_b, p50_b, p95_b, p99_b, error_b, statistics_b))
    sections.append("")

    # Configuration differences
    if differences:
        sections.append("CONFIGURATION DIFFERENCES:")
        for diff in differences:
            sections.append(f"  - {diff}")
        sections.append("")

    # Performance deltas
    sections.append("PERFORMANCE DELTAS (Primary vs Secondary):")
    sections.append(_format_delta_line("QPS", deltas["qps_delta_pct"], higher_is_better=True))
    sections.append(_format_delta_line("P50 Latency", deltas["p50_delta_pct"], higher_is_better=False))
    sections.append(_format_delta_line("P95 Latency", deltas["p95_delta_pct"], higher_is_better=False))
    sections.append(_format_delta_line("P99 Latency", deltas["p99_delta_pct"], higher_is_better=False))
    sections.append(_format_delta_line("Error Rate", deltas["error_rate_delta_pct"], higher_is_better=False))
    sections.append("")

    # Analysis instructions
    sections.append(_generate_deep_compare_instructions())

    prompt = "\n".join(sections)
    return prompt, deltas


def _get_metric(
    test_data: dict[str, Any],
    statistics: dict[str, Any] | None,
    test_key: str,
    stats_path: str,
) -> float | None:
    """Get a metric value from test data or statistics."""
    # Try test data first
    if test_data and test_key in test_data:
        val = test_data.get(test_key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                pass

    # Try statistics with nested path (e.g., "latency.p95_ms")
    if statistics:
        parts = stats_path.split(".")
        obj = statistics
        for part in parts:
            if obj is None:
                break
            obj = obj.get(part) if isinstance(obj, dict) else None
        if obj is not None:
            try:
                return float(obj)
            except (TypeError, ValueError):
                pass

    return None


def _calc_delta_pct(val_a: float | None, val_b: float | None) -> float | None:
    """Calculate percentage delta (A vs B). Positive means A is higher."""
    if val_a is None or val_b is None or val_b == 0:
        return None
    return ((val_a - val_b) / val_b) * 100


def _identify_config_differences(test_a: dict[str, Any], test_b: dict[str, Any]) -> list[str]:
    """Identify configuration differences between two tests."""
    differences = []

    # Define fields to compare with human-readable labels
    config_fields = [
        ("warehouse_size", "Warehouse size"),
        ("warehouse", "Warehouse"),
        ("concurrency", "Concurrency"),
        ("duration_seconds", "Duration"),
        ("load_mode", "Load mode"),
        ("workload_mix", "Workload mix"),
        ("table_type", "Table type"),
        ("scaling_mode", "Scaling mode"),
        ("read_percentage", "Read percentage"),
        ("write_percentage", "Write percentage"),
    ]

    for field, label in config_fields:
        val_a = test_a.get(field)
        val_b = test_b.get(field)
        if val_a != val_b and (val_a is not None or val_b is not None):
            a_str = str(val_a) if val_a is not None else "N/A"
            b_str = str(val_b) if val_b is not None else "N/A"
            differences.append(f"{label}: Primary={a_str}, Secondary={b_str}")

    return differences


def _format_test_summary(
    test: dict[str, Any],
    qps: float | None,
    p50: float | None,
    p95: float | None,
    p99: float | None,
    error_rate: float | None,
    statistics: dict[str, Any] | None = None,
) -> str:
    """Format a test summary section including SF execution data."""
    lines = []

    name = test.get("template_name") or test.get("test_name") or test.get("test_id", "Unknown")
    lines.append(f"  - Name: {name}")
    lines.append(f"  - Test ID: {test.get('test_id', 'N/A')}")

    table_type = test.get("table_type", "")
    if table_type.upper() != "POSTGRES":
        warehouse = test.get("warehouse", "N/A")
        warehouse_size = test.get("warehouse_size", "N/A")
        lines.append(f"  - Warehouse: {warehouse} ({warehouse_size})")
        
        # Scaling mode is important for MCW context
        scaling_mode = test.get("scaling_mode")
        if scaling_mode:
            lines.append(f"  - Scaling Mode: {scaling_mode}")
    else:
        lines.append("  - Database: Postgres")

    concurrency = test.get("concurrency", "N/A")
    lines.append(f"  - Concurrency: {concurrency}")

    duration = test.get("duration_seconds")
    if duration is not None:
        lines.append(f"  - Duration: {duration:.0f}s")

    load_mode = test.get("load_mode", "N/A")
    lines.append(f"  - Load Mode: {load_mode}")

    # Metrics
    qps_str = f"{qps:.1f}" if qps is not None else "N/A"
    lines.append(f"  - QPS: {qps_str}")

    p50_str = f"{p50:.2f}ms" if p50 is not None else "N/A"
    p95_str = f"{p95:.2f}ms" if p95 is not None else "N/A"
    p99_str = f"{p99:.2f}ms" if p99 is not None else "N/A"
    lines.append(f"  - P50/P95/P99: {p50_str} / {p95_str} / {p99_str}")

    error_str = f"{error_rate:.2f}%" if error_rate is not None else "N/A"
    lines.append(f"  - Error Rate: {error_str}")

    # Include SF execution data if available
    if statistics:
        # Cache warming info
        warmup = statistics.get("warmup", {})
        if warmup.get("warmup_queries_used"):
            lines.append(f"  - Cache Warming: Yes ({warmup.get('warmup_query_count', 0)} warmup queries)")
        else:
            lines.append("  - Cache Warming: No")

        # SF execution timing
        sf_exec = statistics.get("sf_execution", {})
        if sf_exec.get("available"):
            avg_sf = sf_exec.get("avg_sf_elapsed_ms")
            p95_sf = sf_exec.get("p95_sf_elapsed_ms")
            if avg_sf is not None:
                lines.append(f"  - SF Execution Time: avg={avg_sf:.1f}ms, p95={p95_sf:.1f}ms" if p95_sf else f"  - SF Execution Time: avg={avg_sf:.1f}ms")

        # Queue times
        queue = statistics.get("queue_times", {})
        avg_overload = queue.get("avg_overload_ms")
        avg_provision = queue.get("avg_provisioning_ms")
        pct_overload = queue.get("pct_with_overload", 0)
        pct_provision = queue.get("pct_with_provisioning", 0)
        
        if avg_overload is not None or avg_provision is not None:
            queue_parts = []
            if avg_overload and avg_overload > 0:
                queue_parts.append(f"overload={avg_overload:.1f}ms ({pct_overload:.1f}% of queries)")
            if avg_provision and avg_provision > 0:
                queue_parts.append(f"provisioning={avg_provision:.1f}ms ({pct_provision:.1f}% of queries)")
            if queue_parts:
                lines.append(f"  - Queue Times: {', '.join(queue_parts)}")
            else:
                lines.append("  - Queue Times: None (no queuing observed)")

        # Cache stats
        cache = statistics.get("cache", {})
        avg_cache = cache.get("avg_cache_hit_pct")
        full_cache_pct = cache.get("full_cache_hit_pct")
        if avg_cache is not None:
            lines.append(f"  - Cache Hit Rate: {avg_cache:.1f}% avg, {full_cache_pct:.1f}% full cache hits")

    return "\n".join(lines)


def _format_delta_line(label: str, delta: float | None, higher_is_better: bool) -> str:
    """Format a delta line with classification indicator."""
    if delta is None:
        return f"  - {label}: N/A"

    sign = "+" if delta >= 0 else ""
    delta_str = f"{sign}{delta:.1f}%"

    # Classify the change
    if higher_is_better:
        # For QPS: positive is good
        classification = classify_change("qps", delta)
    else:
        # For latency/errors: negative is good (lower is better)
        # Flip sign for classification since our thresholds assume higher-is-better
        classification = classify_change("p95_latency", delta)

    indicator = _get_indicator(classification, is_latency=not higher_is_better)

    return f"  - {label}: {delta_str} {indicator}"


def _generate_deep_compare_instructions() -> str:
    """Generate analysis instructions for deep comparison."""
    return """ANALYSIS INSTRUCTIONS:

Provide your analysis using the following structure with markdown formatting.
Use **bold** for section headers and bullet points (-) for all sub-items with proper indentation.

## 1. Performance Summary
Summarize the key performance differences:
   - Compare QPS between tests (which achieved higher throughput?)
   - Compare latency percentiles (P50, P95, P99)
   - Compare error rates
   - Overall: which test performed better?

## 2. Queue Time Analysis
If queue time data is available:
   - Are queue times a bottleneck for either test?
   - High overload queue times → warehouse capacity issues
   - High provisioning queue times → autoscaling delays (MCW spin-up)
   - "None" queue times → sufficient warehouse capacity

## 3. Cache Analysis
If cache data is available:
   - Compare cache hit rates between tests
   - Did one test use cache warming and the other didn't?
   - Impact of cache differences on latency

## 4. Configuration Impact
Analyze how configuration differences affected results:
   - Only attribute differences to settings that ACTUALLY differ
   - If warehouse sizes are the same, don't suggest sizing changes
   - If scaling mode shows MCW, note that autoscaling handles concurrency

## 5. Recommendations
Provide actionable recommendations based ONLY on the data shown:
   - What specific changes would improve performance?
   - Which test configuration is preferable and why?

## 6. Verdict
Based ONLY on the metrics shown, provide one verdict:
   - **IMPROVED**: Primary test clearly outperforms secondary
   - **REGRESSED**: Primary test clearly underperforms secondary
   - **SIMILAR**: Performance is within normal variance (~5%)
   - **MIXED**: Some metrics improved, others regressed

IMPORTANT CONSTRAINTS - DO NOT:
- Conclude "warehouse is undersized" unless queue time data shows consistent overload queuing
- Suggest "reduce concurrency" if the test uses MCW scaling (autoscaling handles this)
- Recommend "cache warming" if the test already shows warmup queries were used
- Make claims about "SF execution data unavailable" if SF Execution Time is shown above
- Speculate about bottlenecks not supported by the queue time or latency data

Keep analysis concise and actionable. Use bullet points with specific numbers from the data.
"""


def generate_comparison_summary(compare_context: dict[str, Any]) -> dict[str, Any]:
    """
    Generate a concise comparison summary for API response.

    This is the `comparison_summary` field added to ai-analysis response.

    Args:
        compare_context: Output from build_compare_context().

    Returns:
        Dictionary with summary fields.
    """
    if not compare_context or compare_context.get("error"):
        return {
            "baseline_available": False,
            "vs_median_verdict": None,
            "qps_delta_pct": None,
            "trend_direction": None,
            "confidence": None,
        }

    baseline = compare_context.get("baseline", {})
    vs_median = compare_context.get("vs_median", {})
    trend = compare_context.get("trend", {})
    vs_previous = compare_context.get("vs_previous", {})

    return {
        "baseline_available": baseline.get("available", False),
        "baseline_count": baseline.get("used_count", 0),
        "vs_median_verdict": vs_median.get("verdict") if vs_median else None,
        "qps_delta_pct": vs_median.get("qps_delta_pct") if vs_median else None,
        "p95_delta_pct": vs_median.get("p95_delta_pct") if vs_median else None,
        "trend_direction": trend.get("direction"),
        "confidence": vs_previous.get("confidence") if vs_previous else None,
    }
