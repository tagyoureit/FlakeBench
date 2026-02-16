// @ts-check

/**
 * Deep comparison page Alpine component.
 *
 * Fetches:
 * - /api/tests/{id} (summary / config)
 * - /api/tests/{id}/metrics (time-series snapshots)
 *
 * Then renders overlaid charts (primary in color, secondary in gray).
 */
function compareDetail() {
  const MAX_IDS = 2;

  const parseIds = (el) => {
    try {
      const raw = el && el.dataset ? String(el.dataset.testIds || "") : "";
      const parts = raw
        .split(",")
        .map((p) => p.trim())
        .filter(Boolean);
      if (parts.length === MAX_IDS) return parts;
    } catch (_) {}

    try {
      const params = new URLSearchParams(window.location.search || "");
      const raw = String(params.get("ids") || "");
      const parts = raw
        .split(",")
        .map((p) => p.trim())
        .filter(Boolean);
      return parts.slice(0, MAX_IDS);
    } catch (_) {}

    return [];
  };

  const fetchJson = async (url) => {
    const resp = await fetch(url);
    if (!resp.ok) {
      const payload = await resp.json().catch(() => ({}));
      const detail = payload && payload.detail ? payload.detail : null;
      const msg =
        (detail && (detail.message || detail.detail || detail)) ||
        `Request failed (HTTP ${resp.status})`;
      throw new Error(msg);
    }
    return resp.json();
  };

  const safeDestroyChart = (canvas) => {
    if (!canvas) return;
    try {
      const chart =
        canvas.__chart ||
        (window.Chart && Chart.getChart ? Chart.getChart(canvas) : null);
      if (chart && typeof chart.destroy === "function") {
        chart.destroy();
      }
    } catch (_) {}
    try {
      canvas.__chart = null;
    } catch (_) {}
  };

  const formatCompact = (value) => {
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "0";
    const abs = Math.abs(n);
    const fmt = (x, suffix) => `${x.toFixed(2)}${suffix}`;
    if (abs >= 1e12) return fmt(n / 1e12, "T");
    if (abs >= 1e9) return fmt(n / 1e9, "B");
    if (abs >= 1e6) return fmt(n / 1e6, "M");
    if (abs >= 1e3) return fmt(n / 1e3, "k");
    return n.toFixed(2);
  };

  const toPoints = (snapshots, xKey, yKey) => {
    const rows = Array.isArray(snapshots) ? snapshots : [];
    const out = [];
    for (const s of rows) {
      if (!s) continue;
      const x = Number(s[xKey] || 0);
      const y = Number(s[yKey] || 0);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      out.push({ x, y });
    }
    return out;
  };

  /**
   * Build x/y points using elapsed_seconds for the x-axis.
   *
   * This matches the behavior of the regular history page charts, which use
   * elapsed_seconds directly. The data is already sorted by elapsed_seconds
   * from the API.
   *
   * @param {Array} snapshots
   * @param {string} yKey
   * @param {object} options
   * @param {boolean} options.showWarmup - whether to include warmup data
   * @param {number} options.alignmentOffset - x-axis shift applied to the series
   * @returns {Array<{x:number,y:number}>}
   */
  const toElapsedPoints = (snapshots, yKey, options = {}) => {
    const showWarmup = options.showWarmup !== false;
    const alignmentOffset = Number(options.alignmentOffset || 0);
    const rows = Array.isArray(snapshots) ? snapshots : [];
    const out = [];
    for (const s of rows) {
      if (!s) continue;
      // Filter out warmup data if showWarmup is false
      if (!showWarmup && s.warmup) continue;
      const x = Number(s.elapsed_seconds || 0) + alignmentOffset;
      const y = Number(s[yKey] || 0);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      out.push({ x, y });
    }
    return out;
  };

  const mkDataset = ({
    label,
    points,
    color,
    dashed = false,
    yAxisID = "y",
  }) => {
    return {
      label,
      data: points,
      yAxisID,
      borderColor: color,
      backgroundColor: "transparent",
      borderWidth: 2,
      tension: 0.2,
      pointRadius: 0,
      pointHitRadius: 6,
      borderDash: dashed ? [6, 4] : undefined,
    };
  };

  const renderLineChart = (canvasId, datasets, options) => {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !window.Chart) return;
    safeDestroyChart(canvas);

    const ctx = canvas.getContext ? canvas.getContext("2d") : null;
    if (!ctx) return;

    // Build warmup annotations if provided
    const annotations = {};
    if (options && options.warmupAnnotations) {
      for (const ann of options.warmupAnnotations) {
        if (ann.x != null && ann.x > 0) {
          annotations[ann.key] = {
            type: "line",
            xMin: ann.x,
            xMax: ann.x,
            borderColor: ann.color || "rgba(255, 165, 0, 0.8)",
            borderWidth: 2,
            borderDash: [6, 4],
            label: {
              display: true,
              content: ann.label || "Warmup End",
              position: "start",
              backgroundColor: ann.color || "rgba(255, 165, 0, 0.8)",
              color: "#fff",
              font: { size: 10 },
            },
          };
        }
      }
    }

    canvas.__chart = new Chart(ctx, {
      type: "line",
      data: {
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 0 },
        parsing: true,
        interaction: { mode: "index", intersect: false },
        scales: {
          x: {
            type: "linear",
            title: { display: true, text: "Elapsed (s)" },
            ticks: { maxTicksLimit: 12 },
          },
          y: {
            beginAtZero: true,
            title: { display: true, text: options && options.yTitle ? options.yTitle : "" },
            ticks: options && options.yTickFormat === "compact"
              ? { callback: (v) => formatCompact(v) }
              : undefined,
          },
        },
        plugins: {
          legend: { display: true },
          tooltip: {
            callbacks: {
              label: (ctx2) => {
                const y = ctx2 && ctx2.parsed ? ctx2.parsed.y : null;
                if (y == null) return ctx2.dataset && ctx2.dataset.label ? ctx2.dataset.label : "";
                if (options && options.yTickFormat === "compact") {
                  return `${ctx2.dataset.label}: ${formatCompact(y)}`;
                }
                return `${ctx2.dataset.label}: ${Number(y).toFixed(2)}`;
              },
            },
          },
          annotation: Object.keys(annotations).length > 0 ? { annotations } : undefined,
        },
      },
    });
  };

  return {
    ids: [],
    loading: false,
    error: null,
    ready: false,

    testA: null,
    testB: null,
    metricsA: [],
    metricsB: [],
    warmupEndA: null,
    warmupEndB: null,
    showWarmup: false,
    alignmentMode: "wall_clock",

    // AI Comparison Analysis state
    aiCompareAnalysis: null,
    aiCompareLoading: false,
    aiCompareError: null,

    init() {
      this.load();
    },

    async load() {
      this.error = null;
      this.ready = false;
      this.loading = true;

      try {
        const ids = parseIds(this.$el);
        if (ids.length !== MAX_IDS) {
          throw new Error("Deep compare requires exactly 2 test ids.");
        }
        this.ids = ids;
        const [a, b] = ids;

        const [testA, testB, metricsA, metricsB] = await Promise.all([
          fetchJson(`/api/tests/${encodeURIComponent(a)}`),
          fetchJson(`/api/tests/${encodeURIComponent(b)}`),
          fetchJson(`/api/tests/${encodeURIComponent(a)}/metrics`),
          fetchJson(`/api/tests/${encodeURIComponent(b)}/metrics`),
        ]);

        this.testA = testA;
        this.testB = testB;
        this.metricsA = Array.isArray(metricsA && metricsA.snapshots)
          ? metricsA.snapshots
          : [];
        this.metricsB = Array.isArray(metricsB && metricsB.snapshots)
          ? metricsB.snapshots
          : [];
        this.warmupEndA = metricsA && metricsA.warmup_end_elapsed_seconds != null
          ? Number(metricsA.warmup_end_elapsed_seconds)
          : null;
        this.warmupEndB = metricsB && metricsB.warmup_end_elapsed_seconds != null
          ? Number(metricsB.warmup_end_elapsed_seconds)
          : null;

        this.renderCharts();
        this.ready = true;

        // Load additional data in parallel (non-blocking)
        this.loadStatistics();
        this.loadErrorTimeline();
        this.loadLatencyBreakdown();
        this.loadSuggestedComparisons();
      } catch (e) {
        console.error("Deep compare load failed:", e);
        this.error = e && e.message ? e.message : String(e);
        this.ready = false;
      } finally {
        this.loading = false;
      }
    },

    renderCharts() {
      const showWarmup = this.showWarmup;
      const warmupEndA = this.warmupEndA;
      const warmupEndB = this.warmupEndB;
      const alignment = this.getAlignmentConfig(warmupEndA, warmupEndB);

      // Build warmup annotations when showing warmup
      const warmupAnnotations = [];
      if (showWarmup) {
        if (warmupEndA != null && warmupEndA > 0) {
          warmupAnnotations.push({
            key: "warmupA",
            x: warmupEndA + alignment.offsetA,
            label: "Primary Measurement Start",
            color: "rgba(59, 130, 246, 0.8)",
          });
        }
        if (warmupEndB != null && warmupEndB > 0) {
          warmupAnnotations.push({
            key: "warmupB",
            x: warmupEndB + alignment.offsetB,
            label: "Secondary Measurement Start",
            color: "rgba(156, 163, 175, 0.8)",
          });
        }
      }

      // Throughput (QPS)
      const opsA = toElapsedPoints(this.metricsA, "ops_per_sec", {
        showWarmup,
        alignmentOffset: alignment.offsetA,
      });
      const opsB = toElapsedPoints(this.metricsB, "ops_per_sec", {
        showWarmup,
        alignmentOffset: alignment.offsetB,
      });
      renderLineChart(
        "compareThroughputChart",
        [
          mkDataset({
            label: "Primary",
            points: opsA,
            color: "rgb(59, 130, 246)",
            dashed: false,
          }),
          mkDataset({
            label: "Secondary",
            points: opsB,
            color: "rgb(156, 163, 175)",
            dashed: true,
          }),
        ],
        { yTitle: "QPS", yTickFormat: "compact", warmupAnnotations },
      );

      // Latency (P50/P95/P99)
      const p50A = toElapsedPoints(this.metricsA, "p50_latency", {
        showWarmup,
        alignmentOffset: alignment.offsetA,
      });
      const p95A = toElapsedPoints(this.metricsA, "p95_latency", {
        showWarmup,
        alignmentOffset: alignment.offsetA,
      });
      const p99A = toElapsedPoints(this.metricsA, "p99_latency", {
        showWarmup,
        alignmentOffset: alignment.offsetA,
      });
      const p50B = toElapsedPoints(this.metricsB, "p50_latency", {
        showWarmup,
        alignmentOffset: alignment.offsetB,
      });
      const p95B = toElapsedPoints(this.metricsB, "p95_latency", {
        showWarmup,
        alignmentOffset: alignment.offsetB,
      });
      const p99B = toElapsedPoints(this.metricsB, "p99_latency", {
        showWarmup,
        alignmentOffset: alignment.offsetB,
      });

      renderLineChart(
        "compareLatencyChart",
        [
          mkDataset({
            label: "Primary P50",
            points: p50A,
            color: "rgb(16, 185, 129)",
          }),
          mkDataset({
            label: "Primary P95",
            points: p95A,
            color: "rgb(245, 158, 11)",
          }),
          mkDataset({
            label: "Primary P99",
            points: p99A,
            color: "rgb(239, 68, 68)",
          }),
          mkDataset({
            label: "Secondary P50",
            points: p50B,
            color: "rgb(156, 163, 175)",
            dashed: true,
          }),
          mkDataset({
            label: "Secondary P95",
            points: p95B,
            color: "rgb(107, 114, 128)",
            dashed: true,
          }),
          mkDataset({
            label: "Secondary P99",
            points: p99B,
            color: "rgb(55, 65, 81)",
            dashed: true,
          }),
        ],
        { yTitle: "Latency (ms)", warmupAnnotations },
      );

      // Concurrency:
      // - Snowflake tests: server-side RUNNING (sf_running)
      // - Postgres tests: client-side in-flight (active_connections)
      const ttA = String(this.testA?.table_type || "").toUpperCase();
      const ttB = String(this.testB?.table_type || "").toUpperCase();
      const isPgA = ttA === "POSTGRES";
      const isPgB = ttB === "POSTGRES";

      const keyA = isPgA ? "active_connections" : "sf_running";
      const keyB = isPgB ? "active_connections" : "sf_running";
      const ptsA = toElapsedPoints(this.metricsA, keyA, {
        showWarmup,
        alignmentOffset: alignment.offsetA,
      });
      const ptsB = toElapsedPoints(this.metricsB, keyB, {
        showWarmup,
        alignmentOffset: alignment.offsetB,
      });
      renderLineChart(
        "compareConcurrencyChart",
        [
          mkDataset({
            label: `Primary ${isPgA ? "in_flight" : "sf_running"}`,
            points: ptsA,
            color: "rgb(99, 102, 241)",
          }),
          mkDataset({
            label: `Secondary ${isPgB ? "in_flight" : "sf_running"}`,
            points: ptsB,
            color: "rgb(156, 163, 175)",
            dashed: true,
          }),
        ],
        { yTitle: "Concurrent operations", yTickFormat: "compact", warmupAnnotations },
      );
    },

    toggleShowWarmup() {
      this.showWarmup = !this.showWarmup;
      this.renderCharts();
      // Re-render error timeline with updated warmup setting
      if (this.errorTimelineA || this.errorTimelineB) {
        this.renderErrorTimelineChart();
      }
    },

    toggleAlignmentMode() {
      this.alignmentMode =
        this.alignmentMode === "warmup_end" ? "wall_clock" : "warmup_end";
      this.renderCharts();
      if (this.errorTimelineA || this.errorTimelineB) {
        this.renderErrorTimelineChart();
      }
    },

    getAlignmentLabel() {
      return this.alignmentMode === "warmup_end"
        ? "Align: Warmup End"
        : "Align: Wall Clock";
    },

    getAlignmentIndicatorLabel() {
      return this.alignmentMode === "warmup_end"
        ? "Warmup-end aligned"
        : "Wall-clock aligned";
    },

    getAlignmentConfig(warmupEndA, warmupEndB) {
      if (this.alignmentMode !== "warmup_end") {
        return { offsetA: 0, offsetB: 0 };
      }
      const a =
        warmupEndA != null && Number.isFinite(Number(warmupEndA))
          ? Number(warmupEndA)
          : null;
      const b =
        warmupEndB != null && Number.isFinite(Number(warmupEndB))
          ? Number(warmupEndB)
          : null;
      if (a == null || b == null) {
        return { offsetA: 0, offsetB: 0 };
      }
      const target = Math.max(a, b);
      return { offsetA: target - a, offsetB: target - b };
    },

    getAlignmentDebug() {
      const warmupA =
        this.warmupEndA != null && Number.isFinite(Number(this.warmupEndA))
          ? Number(this.warmupEndA)
          : null;
      const warmupB =
        this.warmupEndB != null && Number.isFinite(Number(this.warmupEndB))
          ? Number(this.warmupEndB)
          : null;
      const alignment = this.getAlignmentConfig(warmupA, warmupB);
      const maxElapsedA = Math.max(
        0,
        ...((this.metricsA || []).map((m) => Number(m && m.elapsed_seconds ? m.elapsed_seconds : 0))),
      );
      const maxElapsedB = Math.max(
        0,
        ...((this.metricsB || []).map((m) => Number(m && m.elapsed_seconds ? m.elapsed_seconds : 0))),
      );
      return {
        mode: this.alignmentMode,
        showWarmup: this.showWarmup,
        warmupA,
        warmupB,
        offsetA: alignment.offsetA,
        offsetB: alignment.offsetB,
        maxElapsedA,
        maxElapsedB,
        projectedMaxA: maxElapsedA + alignment.offsetA,
        projectedMaxB: maxElapsedB + alignment.offsetB,
      };
    },

    getDebugLineToggles() {
      const d = this.getAlignmentDebug();
      return `toggles: warmup=${d.showWarmup ? "on" : "off"} align=${d.mode}`;
    },

    getDebugLinePrimary() {
      const d = this.getAlignmentDebug();
      const warmup = d.warmupA == null ? "null" : `${d.warmupA.toFixed(3)}s`;
      return `primary: warmup=${warmup} offset=${d.offsetA.toFixed(3)}s max=${d.maxElapsedA.toFixed(1)}s projected=${d.projectedMaxA.toFixed(1)}s`;
    },

    getDebugLineSecondary() {
      const d = this.getAlignmentDebug();
      const warmup = d.warmupB == null ? "null" : `${d.warmupB.toFixed(3)}s`;
      return `secondary: warmup=${warmup} offset=${d.offsetB.toFixed(3)}s max=${d.maxElapsedB.toFixed(1)}s projected=${d.projectedMaxB.toFixed(1)}s`;
    },

    // -------------------------------------------------------------------------
    // Statistics Panel (Phase A)
    // -------------------------------------------------------------------------

    statisticsA: null,
    statisticsB: null,
    statisticsLoading: false,
    statisticsError: null,

    async loadStatistics() {
      if (!this.ids || this.ids.length !== 2) return;
      this.statisticsLoading = true;
      this.statisticsError = null;

      try {
        const [a, b] = this.ids;
        const [statsA, statsB] = await Promise.all([
          fetchJson(`/api/tests/${encodeURIComponent(a)}/statistics`),
          fetchJson(`/api/tests/${encodeURIComponent(b)}/statistics`),
        ]);
        this.statisticsA = statsA;
        this.statisticsB = statsB;
        this.renderStatisticsPanel();
      } catch (e) {
        console.error("Statistics load failed:", e);
        this.statisticsError = e && e.message ? e.message : String(e);
      } finally {
        this.statisticsLoading = false;
      }
    },

    renderStatisticsPanel() {
      // Statistics are rendered via Alpine bindings in the HTML template
      // This method can be used for any post-render processing if needed
    },

    /**
     * Calculate the delta between two values as a percentage.
     * Positive means A > B (primary is higher).
     */
    calcDelta(valA, valB) {
      if (valB == null || valB === 0) return null;
      if (valA == null) return null;
      return ((valA - valB) / valB) * 100;
    },

    /**
     * Format a delta value with + or - prefix and percentage.
     */
    formatDelta(delta) {
      if (delta == null || !Number.isFinite(delta)) return "—";
      const sign = delta >= 0 ? "+" : "";
      return `${sign}${delta.toFixed(1)}%`;
    },

    /**
     * Get CSS class for delta (green for improvement, red for regression).
     * @param {number} delta - The delta percentage
     * @param {boolean} lowerIsBetter - If true, negative delta is good (e.g., latency)
     */
    getDeltaClass(delta, lowerIsBetter = false) {
      if (delta == null || !Number.isFinite(delta)) return "text-gray-500";
      const isGood = lowerIsBetter ? delta < 0 : delta > 0;
      return isGood ? "text-green-600" : "text-red-600";
    },

    /**
     * Calculate the cost delta between two values as a percentage.
     * Positive means A > B (primary is more expensive).
     */
    calcCostDelta(valA, valB) {
      if (valB == null || valB === 0) return null;
      if (valA == null) return null;
      return ((valA - valB) / valB) * 100;
    },

    /**
     * Format a cost delta value with appropriate messaging.
     * For costs, negative delta means savings (good).
     */
    formatCostDelta(delta) {
      if (delta == null || !Number.isFinite(delta)) return "—";
      const sign = delta >= 0 ? "+" : "";
      const label = delta < 0 ? " savings" : " more";
      return `${sign}${delta.toFixed(1)}%${label}`;
    },

    // -------------------------------------------------------------------------
    // Error Timeline Chart (Phase B)
    // -------------------------------------------------------------------------

    errorTimelineA: null,
    errorTimelineB: null,
    errorTimelineLoading: false,
    errorTimelineError: null,

    async loadErrorTimeline() {
      if (!this.ids || this.ids.length !== 2) return;
      this.errorTimelineLoading = true;
      this.errorTimelineError = null;

      try {
        const [a, b] = this.ids;
        const [errA, errB] = await Promise.all([
          fetchJson(`/api/tests/${encodeURIComponent(a)}/error-timeline`),
          fetchJson(`/api/tests/${encodeURIComponent(b)}/error-timeline`),
        ]);
        this.errorTimelineA = errA;
        this.errorTimelineB = errB;
        this.renderErrorTimelineChart();
      } catch (e) {
        console.error("Error timeline load failed:", e);
        this.errorTimelineError = e && e.message ? e.message : String(e);
      } finally {
        this.errorTimelineLoading = false;
      }
    },

    renderErrorTimelineChart() {
      const errA = this.errorTimelineA;
      const errB = this.errorTimelineB;

      // Check if there are any errors to display
      const hasErrorsA = errA && errA.available && errA.total_errors > 0;
      const hasErrorsB = errB && errB.available && errB.total_errors > 0;

      if (!hasErrorsA && !hasErrorsB) {
        // No errors to display - hide the chart section or show a message
        return;
      }

      const showWarmup = this.showWarmup;
      const warmupEndA = errA && errA.warmup_end_elapsed_seconds != null
        ? Number(errA.warmup_end_elapsed_seconds)
        : null;
      const warmupEndB = errB && errB.warmup_end_elapsed_seconds != null
        ? Number(errB.warmup_end_elapsed_seconds)
        : null;
      const alignment = this.getAlignmentConfig(warmupEndA, warmupEndB);

      // Build warmup annotations when showing warmup
      const warmupAnnotations = [];
      if (showWarmup) {
        if (warmupEndA != null && warmupEndA > 0) {
          warmupAnnotations.push({
            key: "warmupA",
            x: warmupEndA + alignment.offsetA,
            label: "Primary Measurement Start",
            color: "rgba(59, 130, 246, 0.8)",
          });
        }
        if (warmupEndB != null && warmupEndB > 0) {
          warmupAnnotations.push({
            key: "warmupB",
            x: warmupEndB + alignment.offsetB,
            label: "Secondary Measurement Start",
            color: "rgba(156, 163, 175, 0.8)",
          });
        }
      }

      // Convert error timeline points to chart data
      const toErrorPoints = (timeline, showWarmup, alignmentOffset) => {
        if (!timeline || !timeline.points) return [];
        const out = [];
        for (const p of timeline.points) {
          if (!showWarmup && p.warmup) continue;
          const x = Number(p.elapsed_seconds || 0) + Number(alignmentOffset || 0);
          const y = Number(p.error_rate_pct || 0);
          out.push({ x, y });
        }
        return out;
      };

      const ptsA = toErrorPoints(errA, showWarmup, alignment.offsetA);
      const ptsB = toErrorPoints(errB, showWarmup, alignment.offsetB);

      renderLineChart(
        "compareErrorTimelineChart",
        [
          mkDataset({
            label: "Primary Error Rate %",
            points: ptsA,
            color: "rgb(239, 68, 68)",
            dashed: false,
          }),
          mkDataset({
            label: "Secondary Error Rate %",
            points: ptsB,
            color: "rgb(156, 163, 175)",
            dashed: true,
          }),
        ],
        { yTitle: "Error Rate (%)", warmupAnnotations },
      );
    },

    // -------------------------------------------------------------------------
    // Duration Mismatch Warning (Phase E)
    // -------------------------------------------------------------------------

    getDurationMismatchWarning() {
      if (!this.testA || !this.testB) return null;
      const durA = Number(this.testA.duration_seconds || 0);
      const durB = Number(this.testB.duration_seconds || 0);
      if (durA === 0 || durB === 0) return null;

      const diff = Math.abs(durA - durB);
      const maxDur = Math.max(durA, durB);
      const pctDiff = (diff / maxDur) * 100;

      // Warn if duration differs by more than 20%
      if (pctDiff > 20) {
        return `Test durations differ significantly: Primary=${durA}s, Secondary=${durB}s (${pctDiff.toFixed(0)}% difference). Results may not be directly comparable.`;
      }
      return null;
    },

    // -------------------------------------------------------------------------
    // Zero-write handling (Phase E)
    // -------------------------------------------------------------------------

    hasWriteOperations(test) {
      if (!test) return false;
      return (test.write_operations || 0) > 0 ||
             (test.custom_insert_pct || 0) > 0 ||
             (test.custom_update_pct || 0) > 0;
    },

    // -------------------------------------------------------------------------
    // Latency Breakdown (Detailed Read/Write + Per-Query-Type)
    // -------------------------------------------------------------------------

    latencyBreakdownA: null,
    latencyBreakdownB: null,
    latencyBreakdownLoading: false,
    latencyBreakdownError: null,

    async loadLatencyBreakdown() {
      if (!this.ids || this.ids.length !== 2) return;
      this.latencyBreakdownLoading = true;
      this.latencyBreakdownError = null;

      try {
        const [a, b] = this.ids;
        const [breakdownA, breakdownB] = await Promise.all([
          fetchJson(`/api/tests/${encodeURIComponent(a)}/latency-breakdown`),
          fetchJson(`/api/tests/${encodeURIComponent(b)}/latency-breakdown`),
        ]);
        this.latencyBreakdownA = breakdownA;
        this.latencyBreakdownB = breakdownB;
      } catch (e) {
        console.error("Latency breakdown load failed:", e);
        this.latencyBreakdownError = e && e.message ? e.message : String(e);
      } finally {
        this.latencyBreakdownLoading = false;
      }
    },

    /**
     * Format a number with K suffix for thousands.
     */
    formatCount(val) {
      if (val == null) return "—";
      if (val >= 1000) {
        return (val / 1000).toFixed(2) + "k";
      }
      return val.toString();
    },

    /**
     * Format compact number (like 1.2k, 5M).
     */
    formatCompact(val) {
      const n = typeof val === "number" ? val : Number(val);
      if (!Number.isFinite(n)) return "0";
      const abs = Math.abs(n);
      const fmt = (x, suffix) => `${x.toFixed(2)}${suffix}`;
      if (abs >= 1e12) return fmt(n / 1e12, "T");
      if (abs >= 1e9) return fmt(n / 1e9, "B");
      if (abs >= 1e6) return fmt(n / 1e6, "M");
      if (abs >= 1e3) return fmt(n / 1e3, "k");
      return n.toFixed(2);
    },

    /**
     * Format ops/s with 2 decimal places.
     */
    formatOps(val) {
      if (val == null) return "—";
      return val.toFixed(2);
    },

    /**
     * Format milliseconds with 2 decimal places.
     */
    formatMs(val) {
      if (val == null) return "—";
      return val.toFixed(2);
    },

    /**
     * Get merged per-query-type data for comparison table.
     * Returns array of objects with query_type, primary stats, secondary stats.
     */
    getMergedQueryTypes() {
      const a = this.latencyBreakdownA;
      const b = this.latencyBreakdownB;
      if (!a?.per_query_type && !b?.per_query_type) return [];

      const map = new Map();

      // Add primary data
      if (a?.per_query_type) {
        for (const qt of a.per_query_type) {
          map.set(qt.query_type, { query_type: qt.query_type, primary: qt, secondary: null });
        }
      }

      // Add/merge secondary data
      if (b?.per_query_type) {
        for (const qt of b.per_query_type) {
          const existing = map.get(qt.query_type);
          if (existing) {
            existing.secondary = qt;
          } else {
            map.set(qt.query_type, { query_type: qt.query_type, primary: null, secondary: qt });
          }
        }
      }

      // Sort by query type order
      const order = {
        "POINT LOOKUP": 1, "Point Lookup": 1,
        "RANGE SCAN": 2, "Range Scan": 2,
        "SELECT": 3,
        "INSERT": 4, "Insert": 4,
        "UPDATE": 5, "Update": 5,
        "DELETE": 6, "Delete": 6,
      };

      return Array.from(map.values()).sort((x, y) => {
        const ox = order[x.query_type] || order[x.query_type.toUpperCase()] || 99;
        const oy = order[y.query_type] || order[y.query_type.toUpperCase()] || 99;
        return ox - oy;
      });
    },

    /**
     * Check if a query type is a read operation.
     */
    isReadOperation(queryType) {
      if (!queryType) return false;
      const upper = queryType.toUpperCase().replace(/_/g, " ");
      return upper === "POINT LOOKUP" || upper === "RANGE SCAN" || upper === "SELECT" || upper === "READ";
    },

    // -------------------------------------------------------------------------
    // Suggested Comparisons (Phase 4)
    // -------------------------------------------------------------------------

    suggestedBaselineComparisons: [],
    suggestedSimilarComparisons: [],
    suggestedComparisonsLoading: false,
    suggestedComparisonsError: null,
    suggestedComparisonsLoaded: false,

    async loadSuggestedComparisons() {
      if (!this.ids || this.ids.length < 1) return;
      if (this.suggestedComparisonsLoaded) return;

      this.suggestedComparisonsLoading = true;
      this.suggestedComparisonsError = null;

      try {
        // Load suggestions for the primary test
        const primaryId = this.ids[0];
        const ctx = await fetchJson(
          `/api/tests/${encodeURIComponent(primaryId)}/compare-context?baseline_count=5&comparable_limit=5&min_similarity=0.40`
        );

        if (ctx && !ctx.error) {
          // Keep baseline and similar suggestions distinct for clearer user intent.
          const maxSuggestionCards = 6;
          const targetPerGroup = 3;
          const secondaryId = this.ids.length > 1 ? this.ids[1] : null;
          const baselineAll = (ctx.comparable_candidates || [])
            .filter((c) => c.test_id !== secondaryId)
            .sort((a, b) => (b.similarity_score || 0) - (a.similarity_score || 0));

          const similarAll = (ctx.similar_candidates || [])
            .filter((c) => c.test_id !== secondaryId)
            .sort((a, b) => (b.similarity_score || 0) - (a.similarity_score || 0));

          // Max 6 total cards. Prefer a balanced 3/3 split when both groups exist.
          if (baselineAll.length > 0 && similarAll.length > 0) {
            let baselineTake = Math.min(targetPerGroup, baselineAll.length);
            let similarTake = Math.min(targetPerGroup, similarAll.length);
            let used = baselineTake + similarTake;

            if (used < maxSuggestionCards) {
              let remaining = maxSuggestionCards - used;
              const baselineLeft = baselineAll.length - baselineTake;
              const similarLeft = similarAll.length - similarTake;

              if (baselineLeft >= similarLeft) {
                const addBaseline = Math.min(remaining, baselineLeft);
                baselineTake += addBaseline;
                remaining -= addBaseline;
                similarTake += Math.min(remaining, similarLeft);
              } else {
                const addSimilar = Math.min(remaining, similarLeft);
                similarTake += addSimilar;
                remaining -= addSimilar;
                baselineTake += Math.min(remaining, baselineLeft);
              }
            }

            this.suggestedBaselineComparisons = baselineAll.slice(0, baselineTake);
            this.suggestedSimilarComparisons = similarAll.slice(0, similarTake);
          } else {
            this.suggestedBaselineComparisons = baselineAll.slice(0, maxSuggestionCards);
            this.suggestedSimilarComparisons = similarAll.slice(0, maxSuggestionCards);
          }
        }
        this.suggestedComparisonsLoaded = true;
      } catch (e) {
        console.error("Suggested comparisons load failed:", e);
        this.suggestedComparisonsError = e && e.message ? e.message : String(e);
      } finally {
        this.suggestedComparisonsLoading = false;
      }
    },

    /**
     * Switch secondary test to a suggested comparison.
     */
    switchToSuggested(testId) {
      if (!this.ids || this.ids.length < 1 || !testId) return;
      const primaryId = this.ids[0];
      window.location.href = `/history/compare?ids=${encodeURIComponent(primaryId)},${encodeURIComponent(testId)}`;
    },

    /**
     * Format similarity score as percentage.
     */
    formatSimilarity(score) {
      if (score == null || !Number.isFinite(score)) return "N/A";
      return `${(score * 100).toFixed(0)}%`;
    },

    formatSuggestionDate(iso) {
      if (!iso) return "Unknown date";
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "Unknown date";
      return d.toLocaleString();
    },

    formatRelativeAge(iso) {
      if (!iso) return "";
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return "";
      const diffMs = Date.now() - d.getTime();
      const minute = 60 * 1000;
      const hour = 60 * minute;
      const day = 24 * hour;
      if (diffMs < hour) return `${Math.max(1, Math.round(diffMs / minute))}m ago`;
      if (diffMs < day) return `${Math.round(diffMs / hour)}h ago`;
      return `${Math.round(diffMs / day)}d ago`;
    },

    calcSuggestionDeltaPct(primaryValue, candidateValue) {
      const p = Number(primaryValue);
      const c = Number(candidateValue);
      if (!Number.isFinite(p) || !Number.isFinite(c) || p === 0) return null;
      return ((c - p) / Math.abs(p)) * 100;
    },

    formatSuggestionDelta(deltaPct, lowerIsBetter = false) {
      if (deltaPct == null || !Number.isFinite(deltaPct)) {
        return { text: "N/A", className: "text-gray-500" };
      }
      const sign = deltaPct >= 0 ? "+" : "";
      const isGood = lowerIsBetter ? deltaPct < 0 : deltaPct > 0;
      return {
        text: `${sign}${deltaPct.toFixed(1)}%`,
        className: isGood ? "text-green-600" : "text-red-600",
      };
    },

    getSuggestionIntent(suggestion, idx, source) {
      const conf = String(suggestion?.confidence || "").toUpperCase();
      if (source === "baseline") {
        if (idx === 0 && conf === "HIGH") return "Best regression anchor";
        if (idx === 0) return "Primary baseline candidate";
        return "Alternative baseline";
      }
      if (idx === 0 && conf === "HIGH") return "Best cross-template analog";
      return "Cross-template alternative";
    },

    // -------------------------------------------------------------------------
    // AI Comparison Analysis
    // -------------------------------------------------------------------------

    /**
     * Load AI-powered comparison analysis for the two tests.
     */
    async loadAIComparison() {
      if (!this.ids || this.ids.length !== 2) return;
      if (this.aiCompareLoading) return;

      this.aiCompareLoading = true;
      this.aiCompareError = null;

      try {
        const [primaryId, secondaryId] = this.ids;
        const resp = await fetch("/api/tests/compare/ai-analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            primary_id: primaryId,
            secondary_id: secondaryId,
            force_regenerate: false,
          }),
        });

        if (!resp.ok) {
          const payload = await resp.json().catch(() => ({}));
          const detail = payload?.detail?.message || payload?.detail || `HTTP ${resp.status}`;
          throw new Error(detail);
        }

        const data = await resp.json();
        this.aiCompareAnalysis = data;
      } catch (e) {
        console.error("AI comparison analysis failed:", e);
        this.aiCompareError = e?.message || String(e);
      } finally {
        this.aiCompareLoading = false;
      }
    },

    /**
     * Get CSS class for verdict badge.
     */
    getVerdictBadgeClass(verdict) {
      const v = String(verdict || "").toUpperCase();
      switch (v) {
        case "IMPROVED":
          return "badge-success";
        case "REGRESSED":
          return "badge-error";
        case "MIXED":
          return "badge-warning";
        case "SIMILAR":
        default:
          return "badge-secondary";
      }
    },

    /**
     * Format a delta value for display.
     */
    formatAIDelta(delta, lowerIsBetter = false) {
      if (delta == null || !Number.isFinite(delta)) return "—";
      const sign = delta >= 0 ? "+" : "";
      const isGood = lowerIsBetter ? delta < 0 : delta > 0;
      return {
        text: `${sign}${delta.toFixed(1)}%`,
        class: isGood ? "text-green-600" : delta === 0 ? "text-gray-500" : "text-red-600",
      };
    },

    /**
     * Get formatted QPS delta.
     */
    getQpsDelta() {
      const delta = this.aiCompareAnalysis?.deltas?.qps_delta_pct;
      return this.formatAIDelta(delta, false);
    },

    /**
     * Get formatted P95 latency delta.
     */
    getP95Delta() {
      const delta = this.aiCompareAnalysis?.deltas?.p95_delta_pct;
      return this.formatAIDelta(delta, true);
    },

    /**
     * Get formatted error rate delta.
     */
    getErrorDelta() {
      const delta = this.aiCompareAnalysis?.deltas?.error_rate_delta_pct;
      return this.formatAIDelta(delta, true);
    },
  };
}

