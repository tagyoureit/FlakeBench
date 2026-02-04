/**
 * Dashboard Latency Module
 * Methods for latency view management and display.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.latency = {
  sfLatencyAvailable() {
    if (!this.templateInfo) return false;
    if (this.templateInfo.sf_latency_available) return true;
    if (this.templateInfo.sf_estimated_available) return true;
    return false;
  },

  sfEnrichmentLowWarning() {
    return !!(this.templateInfo && this.templateInfo.sf_enrichment_low_warning);
  },

  sfEnrichmentRatioPct() {
    if (!this.templateInfo) return null;
    return this.templateInfo.sf_enrichment_ratio_pct;
  },

  sfEnrichmentSampleCount() {
    if (!this.templateInfo) return null;
    return this.templateInfo.sf_enrichment_enriched_queries;
  },

  sfEnrichmentTotalQueries() {
    if (!this.templateInfo) return null;
    return this.templateInfo.sf_enrichment_total_queries;
  },

  sfEstimatedAvailable() {
    return !!(this.templateInfo && this.templateInfo.sf_estimated_available);
  },

  isEnrichmentComplete() {
    const status = (this.templateInfo?.enrichment_status || "")
      .toString()
      .toUpperCase();
    return status === "COMPLETED";
  },

  isFinalMetricsReady() {
    const status = (this.status || "").toString().toUpperCase();
    const phase = (this.phase || "").toString().toUpperCase();

    // For historical rows (no in-memory phase), status alone is the best signal.
    if (!phase) return status === "COMPLETED";

    // When phase is available, allow base metrics during PROCESSING.
    if (status !== "COMPLETED") return false;
    return phase === "COMPLETED" || phase === "PROCESSING";
  },

  sfLatencyDisabledReason() {
    if (!this.testId) return "Select a test to view SQL execution timings.";

    const phase = (this.phase || "").toString().toUpperCase();
    if (phase && phase !== "COMPLETED") {
      return "SQL execution timings are available after processing completes.";
    }

    const status = (this.status || "").toString().toUpperCase();
    if (status && status !== "COMPLETED") {
      return "SQL execution timings are available after processing completes.";
    }

    return "SQL execution timings are not available for this run.";
  },

  setLatencyView(view) {
    const v = view != null ? String(view) : "";
    if (v === "sf_execution") {
      if (!this.sfLatencyAvailable()) return;
      this.latencyView = "sf_execution";
      this.latencyViewUserSelected = true;
      return;
    }
    this.latencyView = "end_to_end";
    this.latencyViewUserSelected = true;
  },

  toggleLatencyView() {
    if (this.latencyView === "sf_execution") {
      this.setLatencyView("end_to_end");
    } else {
      this.setLatencyView("sf_execution");
    }
  },

  latencyViewLabel() {
    if (this.latencyView === "sf_execution") {
      if (this.sfEnrichmentLowWarning()) {
        const estP50 = this.templateInfo?.sf_estimated_p50_latency_ms;
        if (this.sfEstimatedAvailable() && estP50 != null && estP50 > 0) {
          return "SQL execution (estimated)";
        }
        return "SQL execution (sample)";
      }
      return "SQL execution (Snowflake)";
    }
    return "End-to-end (app)";
  },

  latencyCardTitle(pct) {
    const p = Number(pct);
    const base =
      p === 50
        ? "P50 latency (selected view): 50% of operations complete faster than this (the median). This represents the typical user experience. End-to-end (app) includes client/network + Snowflake; SQL execution (Snowflake) uses QUERY_HISTORY.EXECUTION_TIME and excludes client/network."
        : p === 95
          ? "P95 latency (selected view): 95% of operations complete faster than this. End-to-end (app) includes client/network + Snowflake; SQL execution (Snowflake) uses QUERY_HISTORY.EXECUTION_TIME and excludes client/network."
          : p === 99
            ? "P99 latency (selected view): 99% of operations complete faster than this. End-to-end (app) includes client/network + Snowflake; SQL execution (Snowflake) uses QUERY_HISTORY.EXECUTION_TIME and excludes client/network."
            : "Latency (selected view).";
    const showWorstWorker =
      this.mode === "live" && (p === 95 || p === 99);
    if (!showWorstWorker) return base;
    return `${base} P95/P99 = slowest worker (conservative).`;
  },

  currentLatencyMs(pct) {
    const p = Number(pct);
    if (this.latencyView === "sf_execution") {
      if (!this.templateInfo) return null;
      if (!this.sfLatencyAvailable() && !this.sfEstimatedAvailable()) return null;

      if (this.sfEnrichmentLowWarning() && this.sfEstimatedAvailable()) {
        const estVal = p === 50 ? this.templateInfo.sf_estimated_p50_latency_ms
                     : p === 95 ? this.templateInfo.sf_estimated_p95_latency_ms
                     : p === 99 ? this.templateInfo.sf_estimated_p99_latency_ms
                     : null;
        if (estVal != null && estVal > 0) return estVal;
      }
      if (p === 50) return this.templateInfo.sf_p50_latency_ms;
      if (p === 95) return this.templateInfo.sf_p95_latency_ms;
      if (p === 99) return this.templateInfo.sf_p99_latency_ms;
      return null;
    }
    if (p === 50) return this.metrics.p50_latency;
    if (p === 95) return this.metrics.p95_latency;
    if (p === 99) return this.metrics.p99_latency;
    return null;
  },

  detailLatency(fieldName) {
    if (!this.templateInfo) return null;
    const base = fieldName != null ? String(fieldName) : "";
    if (!base) return null;

    if (this.latencyView === "sf_execution") {
      if (!this.sfLatencyAvailable()) return null;
      const sfKey = `sf_${base}`;
      return this.templateInfo[sfKey];
    }
    return this.templateInfo[base];
  },

  /**
   * Get the latency spread ratio (P95/P50) for the current latency view.
   * When viewing SF execution latency, uses sf_latency_spread_ratio.
   * When viewing end-to-end latency, uses latency_spread_ratio.
   * Returns null if not available.
   */
  latencySpreadRatio() {
    if (!this.templateInfo) return null;
    if (this.latencyView === "sf_execution" && this.sfLatencyAvailable()) {
      return this.templateInfo.sf_latency_spread_ratio;
    }
    return this.templateInfo.latency_spread_ratio;
  },

  /**
   * Check if latency spread exceeds the warning threshold (>5x).
   * Uses the spread for the currently-viewed latency mode.
   */
  latencySpreadWarning() {
    if (!this.templateInfo) return false;
    if (this.latencyView === "sf_execution" && this.sfLatencyAvailable()) {
      return !!this.templateInfo.sf_latency_spread_warning;
    }
    return !!this.templateInfo.latency_spread_warning;
  },

  /**
   * Get CSS class for spread indicator based on ratio.
   * Green (<3x), amber (3-5x), red (>5x)
   */
  latencySpreadClass() {
    const ratio = this.latencySpreadRatio();
    if (ratio == null) return "";
    if (ratio > 5) return "bg-red-100 text-red-800";
    if (ratio > 3) return "bg-amber-100 text-amber-800";
    return "bg-green-100 text-green-800";
  },
};
