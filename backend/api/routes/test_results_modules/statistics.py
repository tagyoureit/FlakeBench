"""
Statistical utilities for test comparison.

Contains pure Python implementations of:
- percentile: Linear interpolation percentile calculation
- calculate_kl_divergence: Distribution comparison for latencies
- weighted_median: Recency-weighted statistical calculations
"""

from __future__ import annotations

import math
from typing import Sequence


def percentile(sorted_values: Sequence[float], p: float) -> float | None:
    """
    Calculate the p-th percentile using linear interpolation.

    Args:
        sorted_values: Pre-sorted sequence of numeric values (ascending order).
        p: Percentile to compute (0-100).

    Returns:
        The interpolated percentile value, or None if input is empty.

    Example:
        >>> percentile([1, 2, 3, 4, 5], 50)
        3.0
        >>> percentile([1, 2, 3, 4, 5], 25)
        2.0
    """
    if not sorted_values:
        return None

    n = len(sorted_values)
    if n == 1:
        return float(sorted_values[0])

    # Clamp percentile to valid range
    p = max(0.0, min(100.0, p))

    # Calculate the index using linear interpolation
    # This matches numpy's default "linear" interpolation method
    idx = (p / 100.0) * (n - 1)
    lower_idx = int(math.floor(idx))
    upper_idx = int(math.ceil(idx))

    if lower_idx == upper_idx:
        return float(sorted_values[lower_idx])

    # Linear interpolation between the two surrounding values
    fraction = idx - lower_idx
    lower_val = sorted_values[lower_idx]
    upper_val = sorted_values[upper_idx]

    return lower_val + fraction * (upper_val - lower_val)


def calculate_kl_divergence(
    latencies_a: Sequence[float],
    latencies_b: Sequence[float],
    num_bins: int = 20,
) -> dict:
    """
    Calculate KL divergence between two latency distributions.

    KL divergence measures how different two probability distributions are.
    Higher values indicate more divergence (different distributions).

    Args:
        latencies_a: Latency samples from test A (current test).
        latencies_b: Latency samples from test B (baseline).
        num_bins: Number of histogram bins (uses log-scale for latency data).

    Returns:
        Dictionary with:
        - kl_divergence: float or None - D_KL(A || B)
        - is_significant: bool - True if KL > 0.1
        - interpretation: str - Human-readable explanation
        - histogram_a: list[float] - Normalized bin counts for A
        - histogram_b: list[float] - Normalized bin counts for B
        - bin_edges: list[float] - Log-scale bin edges

    Thresholds:
        < 0.1: Similar distributions
        0.1 - 0.2: Slightly different
        0.2 - 0.5: Notably different
        > 0.5: Very different (investigate cache/plan changes)
    """
    # Minimum samples required for meaningful comparison
    min_samples = 10
    if len(latencies_a) < min_samples or len(latencies_b) < min_samples:
        return {
            "kl_divergence": None,
            "is_significant": False,
            "interpretation": "Insufficient samples for distribution analysis",
            "histogram_a": [],
            "histogram_b": [],
            "bin_edges": [],
        }

    # Filter out non-positive values (can't take log of <= 0)
    latencies_a_clean = [x for x in latencies_a if x > 0]
    latencies_b_clean = [x for x in latencies_b if x > 0]

    if len(latencies_a_clean) < min_samples or len(latencies_b_clean) < min_samples:
        return {
            "kl_divergence": None,
            "is_significant": False,
            "interpretation": "Insufficient positive latency samples",
            "histogram_a": [],
            "histogram_b": [],
            "bin_edges": [],
        }

    # Determine bin edges using log-scale (appropriate for latency distributions)
    all_latencies = latencies_a_clean + latencies_b_clean
    min_lat = max(min(all_latencies), 0.1)  # Avoid log(0)
    max_lat = max(all_latencies)

    # Generate log-spaced bin edges
    log_min = math.log10(min_lat)
    log_max = math.log10(max_lat)
    if log_max <= log_min:
        log_max = log_min + 1  # Ensure we have a valid range

    bin_edges = [
        10 ** (log_min + i * (log_max - log_min) / num_bins)
        for i in range(num_bins + 1)
    ]

    # Compute histograms (count samples in each bin)
    def compute_histogram(values: list[float], edges: list[float]) -> list[float]:
        counts = [0.0] * (len(edges) - 1)
        for v in values:
            for i in range(len(edges) - 1):
                if edges[i] <= v < edges[i + 1]:
                    counts[i] += 1
                    break
            else:
                # Handle edge case: value equals max
                if v >= edges[-1]:
                    counts[-1] += 1
        return counts

    hist_a = compute_histogram(latencies_a_clean, bin_edges)
    hist_b = compute_histogram(latencies_b_clean, bin_edges)

    # Normalize to probabilities and add epsilon to avoid division by zero
    epsilon = 1e-10
    total_a = sum(hist_a) or 1
    total_b = sum(hist_b) or 1

    prob_a = [(c / total_a) + epsilon for c in hist_a]
    prob_b = [(c / total_b) + epsilon for c in hist_b]

    # Renormalize after adding epsilon
    sum_a = sum(prob_a)
    sum_b = sum(prob_b)
    prob_a = [p / sum_a for p in prob_a]
    prob_b = [p / sum_b for p in prob_b]

    # Calculate KL divergence: D_KL(A || B) = sum(A * log(A/B))
    kl_div = sum(
        pa * math.log(pa / pb) for pa, pb in zip(prob_a, prob_b)
    )

    # Interpret the divergence
    if kl_div > 0.5:
        interpretation = (
            "Very different distributions - investigate cache behavior or query plan changes"
        )
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
        "histogram_a": [round(p, 6) for p in prob_a],
        "histogram_b": [round(p, 6) for p in prob_b],
        "bin_edges": [round(e, 2) for e in bin_edges],
    }


def weighted_median(
    values: Sequence[float],
    weights: Sequence[float] | None = None,
) -> float | None:
    """
    Calculate weighted median of values.

    For baseline comparisons, use exponential decay weights to prioritize
    recent runs: weights = [0.8 ** i for i in range(len(values))]

    Args:
        values: Sequence of numeric values.
        weights: Optional weights for each value. If None, uses equal weights.
                 Must be same length as values.

    Returns:
        The weighted median value, or None if input is empty.

    Example:
        >>> weighted_median([10, 20, 30], [1.0, 0.8, 0.64])
        # Returns value weighted toward more recent (higher weight) items
    """
    if not values:
        return None

    n = len(values)
    if n == 1:
        return float(values[0])

    # Default to equal weights if not provided
    if weights is None:
        weights = [1.0] * n

    if len(weights) != n:
        raise ValueError(f"weights length ({len(weights)}) must match values length ({n})")

    # Filter out zero/negative weights
    paired = [(v, w) for v, w in zip(values, weights) if w > 0]
    if not paired:
        return None

    # Sort by value
    paired.sort(key=lambda x: x[0])

    # Find the weighted median
    total_weight = sum(w for _, w in paired)
    cumulative = 0.0
    half_weight = total_weight / 2.0

    for i, (value, weight) in enumerate(paired):
        cumulative += weight
        if cumulative >= half_weight:
            # If we're exactly at the midpoint and there's a next value,
            # return average of this and next
            if cumulative == half_weight and i + 1 < len(paired):
                return (value + paired[i + 1][0]) / 2.0
            return float(value)

    # Fallback (shouldn't reach here)
    return float(paired[-1][0])


def calculate_coefficient_of_variation(values: Sequence[float]) -> float | None:
    """
    Calculate coefficient of variation (CV = stddev / mean).

    CV is useful for measuring relative variability. A high CV indicates
    high variance relative to the mean, which may indicate test instability.

    Args:
        values: Sequence of numeric values.

    Returns:
        The CV as a float (0.0 to inf), or None if invalid input.

    Interpretation:
        < 0.15: Low variance (stable)
        0.15 - 0.30: Moderate variance
        > 0.30: High variance (unstable)
    """
    if not values or len(values) < 2:
        return None

    n = len(values)
    mean = sum(values) / n
    if mean == 0:
        return None

    # Calculate standard deviation
    variance = sum((x - mean) ** 2 for x in values) / n
    stddev = math.sqrt(variance)

    return stddev / abs(mean)


def calculate_simple_trend(
    values: Sequence[float],
    timestamps: Sequence[float] | None = None,
) -> dict:
    """
    Calculate simple linear trend using least squares regression.

    Args:
        values: Sequence of metric values (e.g., QPS) ordered by time.
        timestamps: Optional timestamps. If None, uses indices (0, 1, 2, ...).

    Returns:
        Dictionary with:
        - slope: Change per unit time/index (positive = improving for QPS)
        - r_squared: Goodness of fit (0-1, higher = stronger trend)
        - direction: "IMPROVING", "REGRESSING", "STABLE", or "INSUFFICIENT_DATA"
        - sample_size: Number of data points used
    """
    if not values or len(values) < 3:
        return {
            "slope": None,
            "r_squared": None,
            "direction": "INSUFFICIENT_DATA",
            "sample_size": len(values) if values else 0,
        }

    n = len(values)

    # Use indices if no timestamps provided
    x_vals = list(timestamps) if timestamps else list(range(n))
    y_vals = list(values)

    # Calculate means
    x_mean = sum(x_vals) / n
    y_mean = sum(y_vals) / n

    # Calculate slope using least squares
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(x_vals, y_vals))
    denominator = sum((x - x_mean) ** 2 for x in x_vals)

    if denominator == 0:
        return {
            "slope": 0.0,
            "r_squared": None,
            "direction": "STABLE",
            "sample_size": n,
        }

    slope = numerator / denominator

    # Calculate R-squared (coefficient of determination)
    ss_res = sum((y - (slope * x + (y_mean - slope * x_mean))) ** 2
                 for x, y in zip(x_vals, y_vals))
    ss_tot = sum((y - y_mean) ** 2 for y in y_vals)

    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Determine direction based on slope magnitude relative to mean
    # Slope is considered significant if it represents >2% change per run
    slope_pct = abs(slope) / abs(y_mean) * 100 if y_mean != 0 else 0

    if slope_pct < 2 or r_squared < 0.3:
        direction = "STABLE"
    elif slope > 0:
        direction = "IMPROVING"
    else:
        direction = "REGRESSING"

    return {
        "slope": round(slope, 4),
        "r_squared": round(r_squared, 4),
        "direction": direction,
        "sample_size": n,
    }
