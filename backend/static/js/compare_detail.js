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

  /**
   * Parse an ISO-ish datetime string into epoch milliseconds.
   *
   * The Snowflake/Python stack often produces microsecond timestamps like:
   *   "2026-01-08T18:24:28.734695"
   * Some browsers don't consistently parse 6-digit fractional seconds, so we
   * parse it ourselves and only keep millisecond precision.
   *
   * @param {unknown} value
   * @returns {number} ms since epoch (local time if timezone is missing); NaN if unparseable
   */
  const parseIsoToMs = (value) => {
    const s = value != null ? String(value) : "";
    if (!s) return Number.NaN;

    // YYYY-MM-DDTHH:MM:SS(.frac)?(Z|±HH:MM)?
    const m = s.match(
      /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})?$/,
    );
    if (!m) {
      const t = Date.parse(s);
      return Number.isFinite(t) ? t : Number.NaN;
    }

    const year = Number(m[1]);
    const month = Number(m[2]);
    const day = Number(m[3]);
    const hour = Number(m[4]);
    const minute = Number(m[5]);
    const second = Number(m[6]);
    const frac = m[7] != null ? String(m[7]) : "";
    const tz = m[8] != null ? String(m[8]) : "";

    const msStr = frac ? frac.padEnd(3, "0").slice(0, 3) : "0";
    const ms = Number(msStr);

    // If an explicit timezone is present, we can rely on Date.parse after normalizing
    // fractional seconds to 3 digits.
    if (tz) {
      const fracNorm = frac ? `.${frac.padEnd(3, "0").slice(0, 3)}` : "";
      const norm = `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}:${m[6]}${fracNorm}${tz}`;
      const t = Date.parse(norm);
      if (Number.isFinite(t)) return t;
    }

    // No timezone: treat as local time. We only care about relative elapsed times.
    return new Date(year, month - 1, day, hour, minute, second, ms).getTime();
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
   * Build monotonic x/y points using wall-clock time derived from snapshot timestamps.
   *
   * This avoids "scribble" artifacts when the backend resets elapsed_seconds (e.g.
   * when switching from start_time to measurement_start_time).
   *
   * @param {unknown} snapshots
   * @param {string} yKey
   * @returns {Array<{x:number,y:number}>}
   */
  const toWallElapsedPoints = (snapshots, yKey) => {
    const rows = Array.isArray(snapshots) ? snapshots : [];
    const out = [];
    let t0 = Number.NaN;

    for (const s of rows) {
      if (!s) continue;
      const tsMs = parseIsoToMs(s.timestamp);
      if (!Number.isFinite(tsMs)) continue;
      if (!Number.isFinite(t0)) t0 = tsMs;

      const x = (tsMs - t0) / 1000.0;
      const y = Number(s[yKey] || 0);
      if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
      out.push({ x, y });
    }

    // Fallback: if timestamp parsing failed (unexpected), fall back to raw elapsed_seconds.
    if (out.length === 0) {
      return toPoints(rows, "elapsed_seconds", yKey);
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

        this.renderCharts();
        this.ready = true;
      } catch (e) {
        console.error("Deep compare load failed:", e);
        this.error = e && e.message ? e.message : String(e);
        this.ready = false;
      } finally {
        this.loading = false;
      }
    },

    renderCharts() {
      const nameA =
        this.testA && (this.testA.template_name || this.testA.test_name)
          ? String(this.testA.template_name || this.testA.test_name)
          : "Primary";
      const nameB =
        this.testB && (this.testB.template_name || this.testB.test_name)
          ? String(this.testB.template_name || this.testB.test_name)
          : "Secondary";

      // Throughput (QPS)
      const opsA = toWallElapsedPoints(this.metricsA, "ops_per_sec");
      const opsB = toWallElapsedPoints(this.metricsB, "ops_per_sec");
      renderLineChart(
        "compareThroughputChart",
        [
          mkDataset({
            label: `${nameA} QPS`,
            points: opsA,
            color: "rgb(59, 130, 246)",
            dashed: false,
          }),
          mkDataset({
            label: `${nameB} QPS`,
            points: opsB,
            color: "rgb(156, 163, 175)",
            dashed: true,
          }),
        ],
        { yTitle: "QPS", yTickFormat: "compact" },
      );

      // Latency (P50/P95/P99)
      const p50A = toWallElapsedPoints(this.metricsA, "p50_latency");
      const p95A = toWallElapsedPoints(this.metricsA, "p95_latency");
      const p99A = toWallElapsedPoints(this.metricsA, "p99_latency");
      const p50B = toWallElapsedPoints(this.metricsB, "p50_latency");
      const p95B = toWallElapsedPoints(this.metricsB, "p95_latency");
      const p99B = toWallElapsedPoints(this.metricsB, "p99_latency");

      renderLineChart(
        "compareLatencyChart",
        [
          mkDataset({
            label: `${nameA} P50`,
            points: p50A,
            color: "rgb(16, 185, 129)",
          }),
          mkDataset({
            label: `${nameA} P95`,
            points: p95A,
            color: "rgb(245, 158, 11)",
          }),
          mkDataset({
            label: `${nameA} P99`,
            points: p99A,
            color: "rgb(239, 68, 68)",
          }),
          mkDataset({
            label: `${nameB} P50`,
            points: p50B,
            color: "rgb(156, 163, 175)",
            dashed: true,
          }),
          mkDataset({
            label: `${nameB} P95`,
            points: p95B,
            color: "rgb(107, 114, 128)",
            dashed: true,
          }),
          mkDataset({
            label: `${nameB} P99`,
            points: p99B,
            color: "rgb(55, 65, 81)",
            dashed: true,
          }),
        ],
        { yTitle: "Latency (ms)" },
      );

      // Concurrency:
      // - Snowflake tests: server-side RUNNING (sf_running)
      // - Postgres tests: client-side in-flight (active_connections)
      const ttA = String(this.testA?.table_type || "").toUpperCase();
      const ttB = String(this.testB?.table_type || "").toUpperCase();
      const isPgA = ["POSTGRES", "SNOWFLAKE_POSTGRES"].includes(ttA);
      const isPgB = ["POSTGRES", "SNOWFLAKE_POSTGRES"].includes(ttB);

      const keyA = isPgA ? "active_connections" : "sf_running";
      const keyB = isPgB ? "active_connections" : "sf_running";
      const ptsA = toWallElapsedPoints(this.metricsA, keyA);
      const ptsB = toWallElapsedPoints(this.metricsB, keyB);
      renderLineChart(
        "compareConcurrencyChart",
        [
          mkDataset({
            label: `${nameA} ${isPgA ? "in_flight" : "sf_running"}`,
            points: ptsA,
            color: "rgb(99, 102, 241)",
          }),
          mkDataset({
            label: `${nameB} ${isPgB ? "in_flight" : "sf_running"}`,
            points: ptsB,
            color: "rgb(156, 163, 175)",
            dashed: true,
          }),
        ],
        { yTitle: "Concurrent operations", yTickFormat: "compact" },
      );
    },
  };
}

