/**
 * Dashboard SLO Module
 * Methods for Service Level Objective tracking and display.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.slo = {
  _kindKey(kind) {
    const k = kind != null ? String(kind).toUpperCase() : "";
    if (k === "POINT_LOOKUP") return "point_lookup";
    if (k === "RANGE_SCAN") return "range_scan";
    if (k === "INSERT") return "insert";
    if (k === "UPDATE") return "update";
    return "";
  },

  workloadPct(kind) {
    const info = this.templateInfo;
    if (!info) return 0;
    const k = this._kindKey(kind);
    if (!k) return 0;
    const field =
      k === "point_lookup"
        ? "custom_point_lookup_pct"
        : k === "range_scan"
          ? "custom_range_scan_pct"
          : k === "insert"
            ? "custom_insert_pct"
            : "custom_update_pct";
    const n = Number(info[field] || 0);
    return Number.isFinite(n) ? n : 0;
  },

  sloTargetP95Ms(kind) {
    const info = this.templateInfo;
    if (!info) return null;
    const k = this._kindKey(kind);
    if (!k) return null;
    const field = `target_${k}_p95_latency_ms`;
    const n = Number(info[field] ?? -1);
    return Number.isFinite(n) ? n : null;
  },

  sloTargetP99Ms(kind) {
    const info = this.templateInfo;
    if (!info) return null;
    const k = this._kindKey(kind);
    if (!k) return null;
    const field = `target_${k}_p99_latency_ms`;
    const n = Number(info[field] ?? -1);
    return Number.isFinite(n) ? n : null;
  },

  sloTargetErrorPct(kind) {
    const info = this.templateInfo;
    if (!info) return null;
    const k = this._kindKey(kind);
    if (!k) return null;
    const field = `target_${k}_error_rate_pct`;
    const n = Number(info[field] ?? -1);
    return Number.isFinite(n) ? n : null;
  },

  sloObservedP95Ms(kind) {
    // Always use end-to-end (app) latencies for SLO evaluation.
    //
    // In FIND_MAX_CONCURRENCY, prefer per-step, per-kind latencies so the SLO
    // table reflects the step currently being evaluated (or the unstable step
    // when the run terminates).
    if (this.isFindMaxMode()) {
      const s = this.findMaxState();
      const terminal = this._findMaxIsTerminal(s);
      const step = terminal
        ? (this._findMaxLastUnstableStep() || null)
        : null;
      const hist = this._findMaxStepHistory();
      const effectiveStep = step || (hist.length ? hist[hist.length - 1] : null);
      return this.stepSloObservedP95Ms(kind, effectiveStep);
    }

    const info = this.templateInfo;
    if (!info) return null;
    const k = this._kindKey(kind);
    if (!k) return null;
    const field = `${k}_p95_latency_ms`;
    const n = Number(info[field] || 0);
    return Number.isFinite(n) && n > 0 ? n : null;
  },

  sloObservedP99Ms(kind) {
    // Always use end-to-end (app) latencies for SLO evaluation.
    if (this.isFindMaxMode()) {
      const s = this.findMaxState();
      const terminal = this._findMaxIsTerminal(s);
      const step = terminal
        ? (this._findMaxLastUnstableStep() || null)
        : null;
      const hist = this._findMaxStepHistory();
      const effectiveStep = step || (hist.length ? hist[hist.length - 1] : null);
      return this.stepSloObservedP99Ms(kind, effectiveStep);
    }

    const info = this.templateInfo;
    if (!info) return null;
    const k = this._kindKey(kind);
    if (!k) return null;
    const field = `${k}_p99_latency_ms`;
    const n = Number(info[field] || 0);
    return Number.isFinite(n) && n > 0 ? n : null;
  },

  sloObservedErrorPct(kind) {
    if (this.isFindMaxMode()) {
      const s = this.findMaxState();
      const terminal = this._findMaxIsTerminal(s);
      const step = terminal
        ? (this._findMaxLastUnstableStep() || null)
        : null;
      const hist = this._findMaxStepHistory();
      const effectiveStep = step || (hist.length ? hist[hist.length - 1] : null);
      return this.stepSloObservedErrorPct(kind, effectiveStep);
    }

    const info = this.templateInfo;
    if (!info) return null;
    const k = this._kindKey(kind);
    if (!k) return null;
    const field = `${k}_error_rate_pct`;
    const v = info[field];
    if (v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  },

  hasSloTargets() {
    const kinds = ["POINT_LOOKUP", "RANGE_SCAN", "INSERT", "UPDATE"];
    for (const k of kinds) {
      if (this.workloadPct(k) <= 0) continue;
      const t95 = this.sloTargetP95Ms(k);
      const t99 = this.sloTargetP99Ms(k);
      const terr = this.sloTargetErrorPct(k);
      if (
        (t95 != null && t95 >= 0) ||
        (t99 != null && t99 >= 0) ||
        (terr != null && terr >= 0)
      ) {
        return true;
      }
    }
    return false;
  },

  _stepKindMetric(step, kind, field) {
    if (!step || typeof step !== "object") return null;
    const metrics = step.kind_metrics;
    if (!metrics || typeof metrics !== "object") return null;
    const row = metrics[kind];
    if (!row || typeof row !== "object") return null;
    const v = row[field];
    if (v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  },

  stepSloObservedP95Ms(kind, step) {
    const n = this._stepKindMetric(step, kind, "p95_latency_ms");
    return Number.isFinite(n) && n > 0 ? n : null;
  },

  stepSloObservedP99Ms(kind, step) {
    const n = this._stepKindMetric(step, kind, "p99_latency_ms");
    return Number.isFinite(n) && n > 0 ? n : null;
  },

  stepSloObservedErrorPct(kind, step) {
    return this._stepKindMetric(step, kind, "error_rate_pct");
  },

  stepSloRowStatus(step, kind) {
    const weight = this.workloadPct(kind);
    if (weight <= 0) return "N/A";

    const t95 = this.sloTargetP95Ms(kind);
    const t99 = this.sloTargetP99Ms(kind);
    const terr = this.sloTargetErrorPct(kind);
    const p95Enabled = t95 != null && t95 >= 0;
    const p99Enabled = t99 != null && t99 >= 0;
    const errEnabled = terr != null && terr >= 0;

    if (!p95Enabled && !p99Enabled && !errEnabled) return "DISABLED";
    if (p95Enabled && !(t95 > 0)) return "UNCONFIGURED";
    if (p99Enabled && !(t99 > 0)) return "UNCONFIGURED";
    if (errEnabled && (terr < 0 || terr > 100)) return "UNCONFIGURED";

    const o95 = p95Enabled ? this.stepSloObservedP95Ms(kind, step) : null;
    const o99 = p99Enabled ? this.stepSloObservedP99Ms(kind, step) : null;
    const oerr = errEnabled ? this.stepSloObservedErrorPct(kind, step) : null;
    if (
      (p95Enabled && o95 == null) ||
      (p99Enabled && o99 == null) ||
      (errEnabled && oerr == null)
    ) {
      return "PENDING";
    }

    const ok =
      (!p95Enabled || (o95 != null && o95 <= t95)) &&
      (!p99Enabled || (o99 != null && o99 <= t99)) &&
      (!errEnabled || (oerr != null && oerr <= terr));
    return ok ? "PASS" : "FAIL";
  },

  stepSloStatus(step) {
    const kinds = ["POINT_LOOKUP", "RANGE_SCAN", "INSERT", "UPDATE"];
    let anyTargetsEnabled = false;
    let sawPending = false;
    let sawUnconfigured = false;

    for (const k of kinds) {
      if (this.workloadPct(k) <= 0) continue;
      const s = this.stepSloRowStatus(step, k);
      if (s === "FAIL") return "FAIL";
      if (s === "PENDING") sawPending = true;
      if (s === "UNCONFIGURED") sawUnconfigured = true;
      if (s !== "DISABLED") anyTargetsEnabled = true;
    }

    if (!anyTargetsEnabled) return "DISABLED";
    if (sawPending) return "PENDING";
    if (sawUnconfigured) return "UNCONFIGURED";
    return "PASS";
  },

  stepSloBadgeClass(step) {
    const s = String(this.stepSloStatus(step) || "").toUpperCase();
    if (s === "PASS") return "status-running";
    if (s === "FAIL") return "status-failed";
    if (s === "PENDING") return "status-processing";
    if (s === "UNCONFIGURED") return "status-preparing";
    return "status-prepared";
  },

  thresholdClass(observed, target, allowZeroTarget = false) {
    const o = Number(observed);
    const t = Number(target);
    if (!Number.isFinite(o) || !Number.isFinite(t)) return "";
    if (t < 0) return "";
    if (t === 0) {
      return allowZeroTarget && o > 0 ? "metric-over" : "";
    }
    if (o > t) return "metric-over";
    if (o >= t * 0.9) return "metric-near";
    return "";
  },

  sloRowStatus(kind) {
    if (this.isFindMaxMode()) {
      const s = this.findMaxState();
      const terminal = this._findMaxIsTerminal(s);
      const step = terminal
        ? (this._findMaxLastUnstableStep() || null)
        : null;
      const hist = this._findMaxStepHistory();
      const effectiveStep = step || (hist.length ? hist[hist.length - 1] : null);
      return this.stepSloRowStatus(effectiveStep, kind);
    }

    const weight = this.workloadPct(kind);
    if (weight <= 0) return "N/A";

    const t95 = this.sloTargetP95Ms(kind);
    const t99 = this.sloTargetP99Ms(kind);
    const terr = this.sloTargetErrorPct(kind);
    const p95Enabled = t95 != null && t95 >= 0;
    const p99Enabled = t99 != null && t99 >= 0;
    const errEnabled = terr != null && terr >= 0;

    if (!p95Enabled && !p99Enabled && !errEnabled) return "DISABLED";
    if (p95Enabled && !(t95 > 0)) return "UNCONFIGURED";
    if (p99Enabled && !(t99 > 0)) return "UNCONFIGURED";
    if (errEnabled && (terr < 0 || terr > 100)) return "UNCONFIGURED";

    const o95 = p95Enabled ? this.sloObservedP95Ms(kind) : null;
    const o99 = p99Enabled ? this.sloObservedP99Ms(kind) : null;
    const oerr = errEnabled ? this.sloObservedErrorPct(kind) : null;
    if (
      (p95Enabled && o95 == null) ||
      (p99Enabled && o99 == null) ||
      (errEnabled && oerr == null)
    ) {
      return "PENDING";
    }

    const ok =
      (!p95Enabled || (o95 != null && o95 <= t95)) &&
      (!p99Enabled || (o99 != null && o99 <= t99)) &&
      (!errEnabled || (oerr != null && oerr <= terr));
    return ok ? "PASS" : "FAIL";
  },

  sloBadgeClass(kind) {
    const s = String(this.sloRowStatus(kind) || "").toUpperCase();
    if (s === "PASS") return "status-running";
    if (s === "FAIL") return "status-failed";
    if (s === "PENDING") return "status-processing";
    if (s === "UNCONFIGURED") return "status-preparing";
    return "status-prepared";
  },

  sloOverallStatus() {
    if (this.isFindMaxMode()) {
      const s = this.findMaxState();
      const terminal = this._findMaxIsTerminal(s);
      const step = terminal
        ? (this._findMaxLastUnstableStep() || null)
        : null;
      const hist = this._findMaxStepHistory();
      const effectiveStep = step || (hist.length ? hist[hist.length - 1] : null);
      return this.stepSloStatus(effectiveStep);
    }

    const kinds = ["POINT_LOOKUP", "RANGE_SCAN", "INSERT", "UPDATE"];
    let anyTargetsEnabled = false;
    let sawPending = false;
    let sawUnconfigured = false;

    for (const k of kinds) {
      const weight = this.workloadPct(k);
      if (weight <= 0) continue;
      const s = this.sloRowStatus(k);
      if (s === "FAIL") return "FAIL";
      if (s === "PENDING") sawPending = true;
      if (s === "UNCONFIGURED") sawUnconfigured = true;
      if (s !== "DISABLED") anyTargetsEnabled = true;
    }

    if (!anyTargetsEnabled) return "DISABLED";
    if (sawPending) return "PENDING";
    if (sawUnconfigured) return "UNCONFIGURED";
    return "PASS";
  },

  sloOverallBadgeClass() {
    const s = String(this.sloOverallStatus() || "").toUpperCase();
    if (s === "PASS") return "status-running";
    if (s === "FAIL") return "status-failed";
    if (s === "PENDING") return "status-processing";
    if (s === "UNCONFIGURED") return "status-preparing";
    return "status-prepared";
  },
};
