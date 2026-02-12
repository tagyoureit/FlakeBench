/**
 * Dashboard Comparison Module
 * Fetches and displays performance trend and comparable runs data.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.comparison = {
  // Comparison state
  compareContext: null,
  compareContextLoading: false,
  compareContextError: null,
  compareContextLoaded: false,

  /**
   * Load comparison context for the current test.
   * Only meaningful for history mode (completed tests).
   */
  async loadCompareContext() {
    if (!this.testId || this.mode !== "history") return;
    if (this.compareContextLoaded) return;

    this.compareContextLoading = true;
    this.compareContextError = null;

    try {
      const resp = await fetch(
        `/api/tests/${encodeURIComponent(this.testId)}/compare-context?baseline_count=5&comparable_limit=3&min_similarity=0.55`
      );
      if (!resp.ok) {
        const payload = await resp.json().catch(() => ({}));
        const detail = payload?.detail;
        const msg =
          typeof detail === "object" && detail !== null
            ? detail.message || JSON.stringify(detail)
            : detail || `HTTP ${resp.status}`;
        throw new Error(msg);
      }
      this.compareContext = await resp.json();
      this.compareContextLoaded = true;
    } catch (e) {
      console.error("Compare context load failed:", e);
      this.compareContextError = e.message || String(e);
    } finally {
      this.compareContextLoading = false;
    }
  },

  /**
   * Check if comparison context is available and valid.
   */
  hasCompareContext() {
    return (
      this.compareContext &&
      !this.compareContext.error &&
      this.compareContext.baseline?.available
    );
  },

  /**
   * Get the performance trend data.
   */
  getPerformanceTrend() {
    if (!this.hasCompareContext()) return null;
    const ctx = this.compareContext;
    const baseline = ctx.baseline || {};
    const vsMedian = ctx.vs_median || {};
    const vsPrevious = ctx.vs_previous || {};
    const rolling = ctx.rolling_statistics || {};

    return {
      // Baseline info
      baselineAvailable: baseline.available || false,
      baselineCount: baseline.candidate_count || 0,
      confidence: baseline.confidence || "EXCLUDED",

      // Current test metrics
      currentQps: ctx.current_test?.qps_avg || null,
      currentP95: ctx.current_test?.p95_avg || null,

      // Rolling statistics (sparkline data)
      qpsHistory: rolling.qps_values || [],
      medianQps: rolling.median_qps || null,
      medianP95: rolling.median_p95 || null,
      trend: rolling.trend || null,

      // Delta vs median
      qpsDeltaPct: vsMedian.qps_delta_pct || null,
      p95DeltaPct: vsMedian.p95_delta_pct || null,
      verdict: vsMedian.verdict || null,
      verdictReasons: vsMedian.verdict_reasons || [],

      // Delta vs previous
      vsPreviousQpsDelta: vsPrevious.qps_delta_pct || null,
      vsPreviousP95Delta: vsPrevious.p95_delta_pct || null,
      vsPreviousTestId: vsPrevious.test_id || null,
      vsPreviousSimilarity: vsPrevious.similarity || null,
    };
  },

  /**
   * Get comparable runs for display.
   */
  getComparableRuns() {
    if (!this.compareContext) return [];
    return this.compareContext.comparable_candidates || [];
  },

  /**
   * Format a delta percentage with color indication.
   * @param {number} delta - The delta percentage
   * @param {boolean} higherIsBetter - If true, positive is good (e.g., QPS)
   */
  formatDeltaWithSign(delta, higherIsBetter = true) {
    if (delta == null || !Number.isFinite(delta)) return "N/A";
    const sign = delta >= 0 ? "+" : "";
    return `${sign}${delta.toFixed(1)}%`;
  },

  /**
   * Get CSS class for delta color.
   * @param {number} delta - The delta percentage
   * @param {boolean} higherIsBetter - If true, positive is good
   */
  getDeltaColorClass(delta, higherIsBetter = true) {
    if (delta == null || !Number.isFinite(delta)) return "text-gray-500";
    const isGood = higherIsBetter ? delta > 0 : delta < 0;
    if (Math.abs(delta) < 5) return "text-gray-600"; // Negligible change
    return isGood ? "text-green-600" : "text-red-600";
  },

  /**
   * Get arrow icon for delta direction.
   */
  getDeltaArrow(delta) {
    if (delta == null || !Number.isFinite(delta)) return "";
    if (Math.abs(delta) < 1) return "→";
    return delta > 0 ? "↑" : "↓";
  },

  /**
   * Get confidence badge class.
   */
  getConfidenceBadgeClass(confidence) {
    const conf = String(confidence || "").toUpperCase();
    switch (conf) {
      case "HIGH":
        return "badge-success";
      case "MEDIUM":
        return "badge-warning";
      case "LOW":
        return "badge-error";
      default:
        return "badge-secondary";
    }
  },

  /**
   * Get trend badge class and text.
   */
  getTrendInfo(trend) {
    if (!trend) return { text: "N/A", class: "badge-secondary", icon: "→" };
    const dir = String(trend.direction || "").toUpperCase();
    switch (dir) {
      case "IMPROVING":
        return { text: "Improving", class: "badge-success", icon: "↑" };
      case "REGRESSING":
        return { text: "Regressing", class: "badge-error", icon: "↓" };
      case "STABLE":
        return { text: "Stable", class: "badge-secondary", icon: "→" };
      default:
        return { text: "N/A", class: "badge-secondary", icon: "→" };
    }
  },

  /**
   * Get verdict badge class.
   */
  getVerdictBadgeClass(verdict) {
    const v = String(verdict || "").toUpperCase();
    switch (v) {
      case "IMPROVED":
        return "badge-success";
      case "REGRESSED":
        return "badge-error";
      case "STABLE":
        return "badge-secondary";
      case "INCONCLUSIVE":
        return "badge-warning";
      default:
        return "badge-secondary";
    }
  },

  /**
   * Format similarity score as percentage.
   */
  formatSimilarity(score) {
    if (score == null || !Number.isFinite(score)) return "N/A";
    return `${(score * 100).toFixed(0)}%`;
  },

  /**
   * Generate sparkline SVG path for QPS history.
   * Returns an SVG path string for a simple line chart.
   */
  generateSparklinePath(values, width = 100, height = 24) {
    if (!Array.isArray(values) || values.length < 2) return "";
    const nums = values.filter((v) => v != null && Number.isFinite(v));
    if (nums.length < 2) return "";

    const min = Math.min(...nums);
    const max = Math.max(...nums);
    const range = max - min || 1;
    const step = width / (nums.length - 1);
    const padding = 2;

    const points = nums.map((v, i) => {
      const x = i * step;
      const y = padding + ((max - v) / range) * (height - 2 * padding);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    });

    return `M ${points.join(" L ")}`;
  },

  /**
   * Navigate to deep compare with a specific test.
   */
  openDeepCompareWith(otherTestId) {
    if (!this.testId || !otherTestId) return;
    window.location.href = `/history/compare?ids=${encodeURIComponent(
      this.testId
    )},${encodeURIComponent(otherTestId)}`;
  },
};
