function dashboard(opts) {
  const options = opts && typeof opts === "object" ? opts : {};
  const modeRaw = options.mode != null ? String(options.mode) : "live";
  const mode = modeRaw === "history" ? "history" : "live";

  return {
    mode,
    testRunning: false,
    testId: null,
    progress: 0,
    elapsed: 0,
    duration: 0,
    phase: null,
    warmupSeconds: 0,
    runSeconds: 0,
    status: null,
    templateInfo: null,
    metrics: {
      ops_per_sec: 0,
      p95_latency: 0,
      p99_latency: 0,
      error_rate: 0,
      total_errors: 0,
    },
    latencyView: "end_to_end", // 'end_to_end' | 'sf_execution'
    latencyViewUserSelected: false,
    didRefreshAfterComplete: false,
    // NOTE: Do not store Chart.js instances on Alpine reactive state.
    // Chart objects have circular refs/getters; Alpine Proxy wrapping can cause
    // recursion and Chart.js internal corruption.
    websocket: null,
    logs: [],
    _logSeen: {},
    logMaxLines: 1000,

    init() {
      this.initCharts();

      const el = this.$el;
      const initialTestId = el && el.dataset ? el.dataset.testId : "";
      if (initialTestId) {
        this.testId = initialTestId;
        this.loadTestInfo();
        if (this.mode === "live") {
          this.loadLogs();
          this.connectWebSocket();
        }
      }
    },

    async startTest() {
      if (!this.testId) return;
      try {
        const resp = await fetch(`/api/tests/${this.testId}/start`, {
          method: "POST",
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          const detail = err && err.detail ? err.detail : null;
          throw new Error(
            (detail && (detail.message || detail.detail || detail)) ||
              "Failed to start test",
          );
        }
        // Kick a refresh; status/details will update as soon as execution starts.
        await this.loadTestInfo();
      } catch (e) {
        console.error("Failed to start test:", e);
        window.toast.error(`Failed to start test: ${e.message || e}`);
      }
    },

    async stopTest() {
      if (!this.testId) return;
      try {
        const resp = await fetch(`/api/tests/${this.testId}/stop`, {
          method: "POST",
        });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          const detail = err && err.detail ? err.detail : null;
          throw new Error(
            (detail && (detail.message || detail.detail || detail)) ||
              "Failed to stop test",
          );
        }
        await this.loadTestInfo();
      } catch (e) {
        console.error("Failed to stop test:", e);
        window.toast.error(`Failed to stop test: ${e.message || e}`);
      }
    },

    openRunAnalysis() {
      if (!this.testId) return;
      window.location.href = `/dashboard/history/${this.testId}`;
    },

    workloadDisplay() {
      const info = this.templateInfo;
      if (!info) return "";

      const pct = (key) => {
        const v = info[key];
        const n = typeof v === "number" ? v : Number(v);
        return Number.isFinite(n) ? Math.round(n) : 0;
      };

      const parts = [];
      const add = (key, label) => {
        const p = pct(key);
        if (p > 0) parts.push(`${p}% ${label}`);
      };

      add("custom_point_lookup_pct", "point lookup");
      add("custom_range_scan_pct", "range scan");
      add("custom_insert_pct", "insert");
      add("custom_update_pct", "update");

      if (parts.length > 0) return parts.join(", ");
      return info.workload_type != null ? String(info.workload_type) : "";
    },

    formatSecondsTenths(value) {
      const n = typeof value === "number" ? value : Number(value);
      if (!Number.isFinite(n)) return "0";

      // Cap at one decimal place (tenths).
      const tenthsInt = Math.trunc(n * 10);
      if (tenthsInt % 10 === 0) return String(tenthsInt / 10);
      return (tenthsInt / 10).toFixed(1);
    },

    formatCompact(value) {
      const n = typeof value === "number" ? value : Number(value);
      if (!Number.isFinite(n)) return "0.00";

      const abs = Math.abs(n);
      const format = (x, suffix) => `${x.toFixed(2)}${suffix}`;

      if (abs >= 1e12) return format(n / 1e12, "T");
      if (abs >= 1e9) return format(n / 1e9, "B");
      if (abs >= 1e6) return format(n / 1e6, "M");
      if (abs >= 1e3) return format(n / 1e3, "k");
      return n.toFixed(2);
    },

    formatMs(value) {
      const n = typeof value === "number" ? value : Number(value);
      if (!Number.isFinite(n)) return "N/A";
      return n.toFixed(2);
    },

    formatMsWithUnit(value) {
      const n = typeof value === "number" ? value : Number(value);
      if (!Number.isFinite(n)) return "N/A";
      return `${n.toFixed(2)} ms`;
    },

    sfLatencyAvailable() {
      return !!(this.templateInfo && this.templateInfo.sf_latency_available);
    },

    sfLatencyDisabledReason() {
      if (!this.testId) return "Select a test to view SQL execution timings.";

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

    latencyViewLabel() {
      if (this.latencyView === "sf_execution") return "SQL execution (Snowflake)";
      return "End-to-end (app)";
    },

    currentLatencyMs(pct) {
      const p = Number(pct);
      if (this.latencyView === "sf_execution") {
        if (!this.templateInfo) return null;
        if (!this.sfLatencyAvailable()) return null;
        if (p === 95) return this.templateInfo.sf_p95_latency_ms;
        if (p === 99) return this.templateInfo.sf_p99_latency_ms;
        return null;
      }
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

    async loadTestInfo() {
      if (!this.testId) return;
      try {
        const resp = await fetch(`/api/tests/${this.testId}`);
        if (!resp.ok) return;
        const data = await resp.json();
        this.templateInfo = data;
        this.duration = data.duration_seconds || 0;
        this.status = data.status || null;

        const sfAvail = !!data.sf_latency_available;
        if (!this.latencyViewUserSelected) {
          if (this.mode === "history" && sfAvail) {
            this.latencyView = "sf_execution";
          } else {
            this.latencyView = "end_to_end";
          }
        } else if (this.latencyView === "sf_execution" && !sfAvail) {
          this.latencyView = "end_to_end";
        }
        
        // If test is completed, populate metrics from API response
        if (data.status === 'COMPLETED' || data.status === 'STOPPED' || data.status === 'FAILED' || data.status === 'CANCELLED') {
          this.metrics.ops_per_sec = data.operations_per_second || 0;
          this.metrics.p95_latency = data.p95_latency_ms || 0;
          this.metrics.p99_latency = data.p99_latency_ms || 0;
          this.metrics.error_rate = data.total_operations > 0 
            ? ((data.failed_operations || 0) / data.total_operations) * 100 
            : 0;
          this.metrics.total_errors = data.failed_operations || 0;
          
          // Load historical metrics for completed tests to populate charts
          await this.loadHistoricalMetrics();
        }
      } catch (e) {
        console.error("Failed to load test info:", e);
      }
    },

    async loadLogs() {
      if (!this.testId) return;
      try {
        const resp = await fetch(`/api/tests/${this.testId}/logs?limit=${this.logMaxLines}`);
        if (!resp.ok) return;
        const data = await resp.json().catch(() => ({}));
        const logs = data && Array.isArray(data.logs) ? data.logs : [];
        this.appendLogs(logs);
      } catch (e) {
        console.error("Failed to load logs:", e);
      }
    },

    appendLogs(logs) {
      if (!logs) return;
      const items = Array.isArray(logs) ? logs : [logs];
      for (const item of items) {
        if (!item) continue;
        const logId = item.log_id || item.logId || `${item.timestamp || ""}-${item.seq || ""}`;
        if (this._logSeen[logId]) continue;
        this._logSeen[logId] = true;
        this.logs.push({
          log_id: logId,
          seq: Number(item.seq || 0),
          timestamp: item.timestamp || null,
          level: item.level || "INFO",
          logger: item.logger || null,
          message: item.message || "",
          exception: item.exception || null,
        });
      }

      this.logs.sort((a, b) => (a.seq || 0) - (b.seq || 0));
      if (this.logs.length > this.logMaxLines) {
        const removeCount = this.logs.length - this.logMaxLines;
        const removed = this.logs.splice(0, removeCount);
        for (const r of removed) {
          if (r && r.log_id) delete this._logSeen[r.log_id];
        }
      }
    },

    logsText() {
      if (!this.logs || this.logs.length === 0) return "";
      return this.logs
        .map((l) => {
          const ts = l.timestamp ? new Date(l.timestamp).toLocaleTimeString() : "";
          const lvl = String(l.level || "").toUpperCase();
          const logger = l.logger ? ` ${l.logger}` : "";
          const msg = l.message || "";
          const exc = l.exception ? `\n${l.exception}` : "";
          return `${ts} ${lvl}${logger} - ${msg}${exc}`;
        })
        .join("\n");
    },

    async loadHistoricalMetrics() {
      if (!this.testId) return;
      try {
        const resp = await fetch(`/api/tests/${this.testId}/metrics`);
        if (!resp.ok) return;
        const data = await resp.json();
        
        if (!data.snapshots || data.snapshots.length === 0) {
          console.log("No historical metrics snapshots found for test");
          return;
        }
        
        // Populate charts with historical data
        const throughputCanvas = document.getElementById("throughputChart");
        const latencyCanvas = document.getElementById("latencyChart");
        const throughputChart = throughputCanvas && (throughputCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(throughputCanvas) : null));
        const latencyChart = latencyCanvas && (latencyCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(latencyCanvas) : null));
        
        // If charts don't exist yet, initialize them
        if (!throughputChart || !latencyChart) {
          this.initCharts();
        }
        
        // Get chart references again after potential init
        const throughputChart2 = throughputCanvas && (throughputCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(throughputCanvas) : null));
        const latencyChart2 = latencyCanvas && (latencyCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(latencyCanvas) : null));
        
        // Clear existing data
        if (throughputChart2) {
          throughputChart2.data.labels = [];
          throughputChart2.data.datasets[0].data = [];
        }
        if (latencyChart2) {
          latencyChart2.data.labels = [];
          latencyChart2.data.datasets[0].data = [];
          latencyChart2.data.datasets[1].data = [];
          latencyChart2.data.datasets[2].data = [];
        }
        
        // Populate with historical data
        for (const snapshot of data.snapshots) {
          const ts = new Date(snapshot.timestamp).toLocaleTimeString();
          
          if (throughputChart2) {
            throughputChart2.data.labels.push(ts);
            throughputChart2.data.datasets[0].data.push(snapshot.ops_per_sec);
          }
          
          if (latencyChart2) {
            latencyChart2.data.labels.push(ts);
            latencyChart2.data.datasets[0].data.push(snapshot.p50_latency);
            latencyChart2.data.datasets[1].data.push(snapshot.p95_latency);
            latencyChart2.data.datasets[2].data.push(snapshot.p99_latency);
          }
        }
        
        // Update charts
        if (throughputChart2) throughputChart2.update();
        if (latencyChart2) latencyChart2.update();
        
        console.log(`Loaded ${data.snapshots.length} historical metrics snapshots`);
      } catch (e) {
        console.error("Failed to load historical metrics:", e);
      }
    },

    initCharts() {
      // Make chart init idempotent. HTMX/Alpine can re-initialize components and
      // Chart.js will break if we re-use the same canvas without destroying.
      const safeDestroy = (chart) => {
        if (!chart) return;
        try {
          chart.destroy();
        } catch (_) {}
      };

      const formatCompact = (v) => this.formatCompact(v);

      const throughputCanvas = document.getElementById("throughputChart");
      // If Alpine re-initializes, our old chart refs are lost, but Chart.js still has
      // a chart bound to the canvas. Destroy by canvas first.
      if (throughputCanvas && window.Chart && Chart.getChart) {
        safeDestroy(Chart.getChart(throughputCanvas));
      }

      const throughputCtx = throughputCanvas && throughputCanvas.getContext
        ? throughputCanvas.getContext("2d")
        : null;
      if (throughputCtx) {
        // Store chart instance on the canvas (non-reactive).
        throughputCanvas.__chart = new Chart(throughputCtx, {
          type: "line",
          data: {
            labels: [],
            datasets: [
              {
                label: "Ops / Second",
                data: [],
                borderColor: "rgb(59, 130, 246)",
                backgroundColor: "rgba(59, 130, 246, 0.1)",
                tension: 0.4,
                fill: true,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            scales: {
              y: {
                beginAtZero: true,
                ticks: {
                  callback: (value) => formatCompact(value),
                },
              },
            },
            plugins: {
              tooltip: {
                callbacks: {
                  label: (ctx) => `${ctx.dataset.label}: ${formatCompact(ctx.parsed.y)}`,
                },
              },
            },
          },
        });
      }

      const latencyCanvas = document.getElementById("latencyChart");
      if (latencyCanvas && window.Chart && Chart.getChart) {
        safeDestroy(Chart.getChart(latencyCanvas));
      }

      const latencyCtx = latencyCanvas && latencyCanvas.getContext
        ? latencyCanvas.getContext("2d")
        : null;
      if (latencyCtx) {
        latencyCanvas.__chart = new Chart(latencyCtx, {
          type: "line",
          data: {
            labels: [],
            datasets: [
              {
                label: "P50",
                data: [],
                borderColor: "rgb(16, 185, 129)",
                backgroundColor: "transparent",
                tension: 0.4,
              },
              {
                label: "P95",
                data: [],
                borderColor: "rgb(245, 158, 11)",
                backgroundColor: "transparent",
                tension: 0.4,
              },
              {
                label: "P99",
                data: [],
                borderColor: "rgb(239, 68, 68)",
                backgroundColor: "transparent",
                tension: 0.4,
              },
            ],
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 0 },
            scales: {
              y: {
                beginAtZero: true,
                ticks: {
                  callback: (value) => `${Number(value).toFixed(2)} ms`,
                },
              },
            },
            plugins: {
              tooltip: {
                callbacks: {
                  label: (ctx) => `${ctx.dataset.label}: ${Number(ctx.parsed.y).toFixed(2)} ms`,
                },
              },
            },
          },
        });
      }
    },

    connectWebSocket() {
      if (!this.testId) return;
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const wsUrl = `${protocol}//${window.location.host}/ws/test/${this.testId}`;
      this.websocket = new WebSocket(wsUrl);

      this.websocket.onopen = () => {
        // WebSocket connection indicates the dashboard is live, not that the test is running.
        this.testRunning = true;
      };

      this.websocket.onmessage = (event) => {
        let data = null;
        try {
          data = JSON.parse(event.data);
        } catch (e) {
          console.error("WebSocket message parse failed:", e, event.data);
          return;
        }
        // Ignore the initial connected message.
        if (data && data.status === "connected") return;
        if (data && data.kind === "log") {
          this.appendLogs(data);
          return;
        }
        if (data && data.kind === "log_batch") {
          const logs = data.logs && Array.isArray(data.logs) ? data.logs : [];
          this.appendLogs(logs);
          return;
        }
        this.applyMetricsPayload(data);
      };

      this.websocket.onerror = (error) => {
        console.error("WebSocket error:", error);
      };

      this.websocket.onclose = () => {
        this.testRunning = false;
      };
    },

    disconnectWebSocket() {
      if (this.websocket) {
        this.websocket.close();
        this.websocket = null;
      }
    },

    phaseLabel() {
      const phase = this.phase ? String(this.phase) : "";
      const status = (this.status || "").toString().toUpperCase();

      // Terminal state should reflect actual status (e.g., FAILED) rather than the
      // terminal phase label ("COMPLETED" is used as the final phase even on failure).
      if (status === "FAILED" || status === "CANCELLED" || status === "STOPPED") {
        return status;
      }

      // If backend reports phase=COMPLETED but status is a failure, show the failure.
      if (phase.toUpperCase() === "COMPLETED" && status === "FAILED") {
        return "FAILED";
      }

      return phase;
    },

    phaseBadgeClass() {
      const phase = (this.phase || "").toString().toUpperCase();
      const status = (this.status || "").toString().toUpperCase();

      if (phase === "WARMUP") return "status-warmup";
      if (phase === "RUNNING") return "status-running";
      if (phase === "PROCESSING") return "status-processing";
      if (phase === "COMPLETED") {
        if (status === "FAILED") return "status-failed";
        return "status-completed";
      }
      return "";
    },

    phaseTimingText() {
      const warmup = Number(this.warmupSeconds || 0);
      const run = Number(this.runSeconds || 0);
      const total = warmup + run;

      const phase = (this.phase || "").toString().toUpperCase();
      if (phase === "WARMUP") {
        return `Warmup: start 0s • est ${warmup}s • est complete ${warmup}s`;
      }
      if (phase === "RUNNING") {
        return `Running: start ${warmup}s • est ${run}s • est complete ${total}s`;
      }
      if (phase === "PROCESSING") {
        return `Processing: start ${total}s`;
      }
      return "";
    },

    applyMetricsPayload(payload) {
      if (!payload) return;
      // Never allow dashboard updates to crash the whole Alpine component.
      // (Any exception here prevents subsequent metrics from rendering.)
      try {
        const throughputCanvas = document.getElementById("throughputChart");
        const latencyCanvas = document.getElementById("latencyChart");
        const throughputChart =
          throughputCanvas && (throughputCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(throughputCanvas) : null));
        const latencyChart =
          latencyCanvas && (latencyCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(latencyCanvas) : null));

        // If charts weren't available at init time (HTMX swaps), re-init on first payload.
        if (!throughputChart || !latencyChart) {
          this.initCharts();
        }

        const timing = payload.timing || {};
        const phase = payload.phase ? String(payload.phase) : null;
        const status = payload.status ? String(payload.status) : null;
        if (phase) this.phase = phase;
        if (status) this.status = status;

        const warmupSeconds = Number(timing.warmup_seconds);
        if (Number.isFinite(warmupSeconds) && warmupSeconds >= 0) {
          this.warmupSeconds = Math.round(warmupSeconds);
        }
        const runSeconds = Number(timing.run_seconds);
        if (Number.isFinite(runSeconds) && runSeconds >= 0) {
          this.runSeconds = Math.round(runSeconds);
        }
        const totalExpectedSeconds = Number(timing.total_expected_seconds);
        if (Number.isFinite(totalExpectedSeconds) && totalExpectedSeconds >= 0) {
          this.duration = Math.round(totalExpectedSeconds);
        }

        const elapsedDisplay = Number(timing.elapsed_display_seconds);
        if (Number.isFinite(elapsedDisplay) && elapsedDisplay >= 0) {
          this.elapsed = Math.round(elapsedDisplay);
        } else {
          // Backward-compat fallback (older payloads).
          this.elapsed = Math.round(payload.elapsed || 0);
        }

        if (this.duration > 0) {
          this.progress = Math.min(100, (this.elapsed / this.duration) * 100);
        } else {
          this.progress = 0;
        }

        const ts = payload.timestamp
          ? new Date(payload.timestamp).toLocaleTimeString()
          : new Date().toLocaleTimeString();

        const ops = payload.ops;
        const latency = payload.latency;
        const errors = payload.errors;
        const phaseUpper = (this.phase || "").toString().toUpperCase();
        const allowCharts =
          !phaseUpper || phaseUpper === "WARMUP" || phaseUpper === "RUNNING";

        if (ops) {
          this.metrics.ops_per_sec = ops.current_per_sec || 0;
        }
        if (latency) {
          this.metrics.p95_latency = latency.p95 || 0;
          this.metrics.p99_latency = latency.p99 || 0;
        }
        if (errors) {
          this.metrics.error_rate = (errors.rate || 0) * 100.0;
          this.metrics.total_errors = errors.count || 0;
        }

        const throughputChart2 =
          throughputCanvas && (throughputCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(throughputCanvas) : null));
        if (throughputChart2) {
          if (throughputChart2.data.labels.length > 60) {
            throughputChart2.data.labels.shift();
            throughputChart2.data.datasets[0].data.shift();
          }
          if (ops && allowCharts) {
            throughputChart2.data.labels.push(ts);
            throughputChart2.data.datasets[0].data.push(this.metrics.ops_per_sec);
            throughputChart2.update();
          }
        }

        const latencyChart2 =
          latencyCanvas && (latencyCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(latencyCanvas) : null));
        if (latencyChart2) {
          if (latencyChart2.data.labels.length > 60) {
            latencyChart2.data.labels.shift();
            latencyChart2.data.datasets.forEach((ds) => ds.data.shift());
          }
          if (latency && allowCharts) {
            latencyChart2.data.labels.push(ts);
            latencyChart2.data.datasets[0].data.push(latency.p50 || 0);
            latencyChart2.data.datasets[1].data.push(latency.p95 || 0);
            latencyChart2.data.datasets[2].data.push(latency.p99 || 0);
            latencyChart2.update();
          }
        }

        // Once we hit the terminal phase, refresh from the API so we pick up:
        // - persisted final metrics
        // - QUERY_HISTORY enrichment fields (sf_* latency summaries)
        if (
          phaseUpper === "COMPLETED" &&
          this.mode === "live" &&
          !this.didRefreshAfterComplete
        ) {
          this.didRefreshAfterComplete = true;
          this.loadTestInfo();
        }
      } catch (e) {
        console.error("applyMetricsPayload error:", e, payload);
      }
    },
  };
}


