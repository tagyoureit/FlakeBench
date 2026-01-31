/**
 * Dashboard Find-Max Module
 * Methods for the FIND_MAX_CONCURRENCY load mode.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.findMax = {
  isFindMaxMode() {
    const loadMode = String(this.templateInfo?.load_mode || "").toUpperCase();
    if (loadMode === "FIND_MAX_CONCURRENCY") return true;
    const s = this.findMaxState();
    return !!(s && String(s.mode || "").toUpperCase() === "FIND_MAX_CONCURRENCY");
  },

  findMaxState() {
    if (this.findMaxController && typeof this.findMaxController === "object") {
      return this.findMaxController;
    }
    const raw = this.templateInfo?.find_max_result;
    if (raw && typeof raw === "object") return raw;
    return null;
  },

  findMaxBaselineP95Ms() {
    const s = this.findMaxState();
    if (!s) return null;
    const v = Number(s.baseline_p95_latency_ms);
    if (!Number.isFinite(v) || v <= 0) return null;
    return v;
  },

  findMaxBaselineP99Ms() {
    const s = this.findMaxState();
    if (!s) return null;
    const v = Number(s.baseline_p99_latency_ms);
    if (!Number.isFinite(v) || v <= 0) return null;
    return v;
  },

  _findMaxIsTerminal(s) {
    const statusUpper = (this.status || "").toString().toUpperCase();
    const phaseUpper = (this.phase || "").toString().toUpperCase();
    const controllerStatus = s && s.status != null ? String(s.status).toUpperCase() : "";
    return (
      phaseUpper === "COMPLETED" ||
      ["STOPPED", "FAILED", "CANCELLED"].includes(statusUpper) ||
      controllerStatus === "COMPLETED" ||
      !!(s && s.completed)
    );
  },

  _findMaxStepHistory() {
    const s = this.findMaxState();
    if (!s) return [];
    const hist = s.step_history;
    return Array.isArray(hist) ? hist : [];
  },

  _findMaxLastUnstableStep() {
    const hist = this._findMaxStepHistory();
    for (let i = hist.length - 1; i >= 0; i--) {
      const row = hist[i];
      if (!row || row.stable !== false) continue;
      if (row.is_backoff) continue;
      return row;
    }
    return null;
  },

  findMaxCurrentP95Ms() {
    const s = this.findMaxState();
    const terminal = this._findMaxIsTerminal(s);

    // Terminal: prefer the *unstable* step p95 (what caused the stop) when present.
    if (terminal) {
      const unstable = this._findMaxLastUnstableStep();
      if (unstable && unstable.p95_latency_ms != null) {
        const v = Number(unstable.p95_latency_ms);
        if (Number.isFinite(v) && v > 0) return v;
      }
      if (s && s.current_p95_latency_ms != null) {
        const v = Number(s.current_p95_latency_ms);
        if (Number.isFinite(v) && v > 0) return v;
      }
      const hist = this._findMaxStepHistory();
      const last = hist.length ? hist[hist.length - 1] : null;
      if (last && last.p95_latency_ms != null) {
        const v = Number(last.p95_latency_ms);
        if (Number.isFinite(v) && v > 0) return v;
      }
    }

    // Live: use rolling end-to-end p95 (the executor clears the latency buffer per step,
    // so this approximates the current step while it runs).
    if (this.mode === "live") {
      const v = Number(this.metrics?.p95_latency);
      if (!Number.isFinite(v) || v <= 0) return null;
      return v;
    }

    // History: prefer the persisted last-step p95 from find_max_result, else overall.
    if (s && s.current_p95_latency_ms != null) {
      const v = Number(s.current_p95_latency_ms);
      if (Number.isFinite(v) && v > 0) return v;
    }
    const v = Number(this.templateInfo?.p95_latency_ms);
    if (!Number.isFinite(v) || v <= 0) return null;
    return v;
  },

  findMaxCurrentP99Ms() {
    const s = this.findMaxState();
    const terminal = this._findMaxIsTerminal(s);

    if (terminal) {
      const unstable = this._findMaxLastUnstableStep();
      if (unstable && unstable.p99_latency_ms != null) {
        const v = Number(unstable.p99_latency_ms);
        if (Number.isFinite(v) && v > 0) return v;
      }
      if (s && s.current_p99_latency_ms != null) {
        const v = Number(s.current_p99_latency_ms);
        if (Number.isFinite(v) && v > 0) return v;
      }
      const hist = this._findMaxStepHistory();
      const last = hist.length ? hist[hist.length - 1] : null;
      if (last && last.p99_latency_ms != null) {
        const v = Number(last.p99_latency_ms);
        if (Number.isFinite(v) && v > 0) return v;
      }
    }

    if (this.mode === "live") {
      const v = Number(this.metrics?.p99_latency);
      if (!Number.isFinite(v) || v <= 0) return null;
      return v;
    }

    if (s && s.current_p99_latency_ms != null) {
      const v = Number(s.current_p99_latency_ms);
      if (Number.isFinite(v) && v > 0) return v;
    }
    const v = Number(this.templateInfo?.p99_latency_ms);
    if (!Number.isFinite(v) || v <= 0) return null;
    return v;
  },

  findMaxP95DiffPct() {
    const baseline = this.findMaxBaselineP95Ms();
    const current = this.findMaxCurrentP95Ms();
    if (!baseline || baseline <= 0 || current == null) return null;
    return ((current - baseline) / baseline) * 100.0;
  },

  findMaxP99DiffPct() {
    const baseline = this.findMaxBaselineP99Ms();
    const current = this.findMaxCurrentP99Ms();
    if (!baseline || baseline <= 0 || current == null) return null;
    return ((current - baseline) / baseline) * 100.0;
  },

  findMaxP95MaxThresholdMs() {
    const baseline = this.findMaxBaselineP95Ms();
    if (!baseline || baseline <= 0) return null;
    const s = this.findMaxState() || {};
    const pct = Number(s.latency_stability_pct);
    if (!Number.isFinite(pct) || pct <= 0) return null;
    // Baseline drift guardrail uses 2x the per-step latency threshold (matches controller logic).
    return baseline * (1.0 + (pct * 2.0) / 100.0);
  },

  findMaxP99MaxThresholdMs() {
    const baseline = this.findMaxBaselineP99Ms();
    if (!baseline || baseline <= 0) return null;
    const s = this.findMaxState() || {};
    const pct = Number(s.latency_stability_pct);
    if (!Number.isFinite(pct) || pct <= 0) return null;
    return baseline * (1.0 + (pct * 2.0) / 100.0);
  },

  findMaxCurrentErrorPct() {
    const s = this.findMaxState();
    const terminal = this._findMaxIsTerminal(s);

    if (terminal) {
      const unstable = this._findMaxLastUnstableStep();
      if (unstable && unstable.error_rate_pct != null) {
        const v = Number(unstable.error_rate_pct);
        if (Number.isFinite(v)) return v;
      }
      if (s && s.current_error_rate_pct != null) {
        const v = Number(s.current_error_rate_pct);
        if (Number.isFinite(v)) return v;
      }
      const hist = this._findMaxStepHistory();
      const last = hist.length ? hist[hist.length - 1] : null;
      if (last && last.error_rate_pct != null) {
        const v = Number(last.error_rate_pct);
        if (Number.isFinite(v)) return v;
      }
    }

    if (this.mode === "live") {
      const v = Number(this.metrics?.error_rate);
      if (!Number.isFinite(v)) return null;
      return v;
    }

    if (s && s.current_error_rate_pct != null) {
      const v = Number(s.current_error_rate_pct);
      if (Number.isFinite(v)) return v;
    }
    return null;
  },

  findMaxMaxErrorPct() {
    const s = this.findMaxState();
    if (!s) return null;
    const v = Number(s.max_error_rate_pct);
    return Number.isFinite(v) ? v : null;
  },

  findMaxCurrentWorkers() {
    const s = this.findMaxState();
    if (!s) return null;
    if (this._findMaxIsTerminal(s)) {
      const finalBest = Number(
        s.final_best_concurrency != null ? s.final_best_concurrency : s.best_concurrency,
      );
      return Number.isFinite(finalBest) ? Math.trunc(finalBest) : null;
    }
    const v = Number(s.current_concurrency);
    return Number.isFinite(v) ? Math.trunc(v) : null;
  },

  findMaxActiveWorkers() {
    const s = this.findMaxState();
    if (!s) return null;
    const v = Number(s.active_worker_count);
    return Number.isFinite(v) ? Math.trunc(v) : null;
  },

  findMaxNextWorkers() {
    const s = this.findMaxState();
    if (!s) return null;
    // When terminal, return null - no "next" workers to show
    if (this._findMaxIsTerminal(s)) {
      return null;
    }
    const v = Number(s.next_planned_concurrency);
    return Number.isFinite(v) ? Math.trunc(v) : null;
  },

  findMaxAtMax() {
    const s = this.findMaxState();
    if (!s) return false;
    const current = Number(s.current_concurrency);
    const max = Number(s.max_concurrency);
    return Number.isFinite(current) && Number.isFinite(max) && current >= max;
  },

  findMaxConclusionReason() {
    const s = this.findMaxState();
    if (!s) return null;
    const statusUpper = (this.status || "").toString().toUpperCase();
    const phaseUpper = (this.phase || "").toString().toUpperCase();
    const terminal =
      phaseUpper === "COMPLETED" ||
      ["STOPPED", "FAILED", "CANCELLED"].includes(statusUpper) ||
      !!s.completed;
    if (!terminal) return null;

    const finalReason = s.final_reason != null ? String(s.final_reason) : "";
    const trimmedFinal = finalReason.trim();
    if (trimmedFinal) {
      // Older runs may have a misleading final_reason due to controller state ordering.
      // If we have an explicit unstable step with a stop reason, prefer that.
      if (trimmedFinal.toLowerCase() === "reached max workers") {
        const unstable = this._findMaxLastUnstableStep();
        const stop = unstable && unstable.stop_reason != null ? String(unstable.stop_reason).trim() : "";
        if (stop) return stop;
      }
      return trimmedFinal;
    }
    const stopReason = s.stop_reason != null ? String(s.stop_reason) : "";
    if (stopReason.trim()) return stopReason.trim();
    const unstable = this._findMaxLastUnstableStep();
    const unstableStop = unstable && unstable.stop_reason != null ? String(unstable.stop_reason).trim() : "";
    if (unstableStop) return unstableStop;
    if (statusUpper === "CANCELLED") return "Cancelled by user";
    return null;
  },

  _clearFindMaxCountdown() {
    if (this._findMaxCountdownIntervalId) {
      clearInterval(this._findMaxCountdownIntervalId);
      this._findMaxCountdownIntervalId = null;
    }
    this._findMaxCountdownTargetEpochMs = null;
    this.findMaxCountdownSeconds = null;
  },

  syncFindMaxCountdown() {
    if (this.mode !== "live") {
      this._clearFindMaxCountdown();
      return;
    }
    if (!this.isFindMaxMode()) {
      this._clearFindMaxCountdown();
      return;
    }
    const s = this.findMaxState();
    if (!s) {
      this._clearFindMaxCountdown();
      return;
    }

    const statusUpper = (this.status || "").toString().toUpperCase();
    const phaseUpper = (this.phase || "").toString().toUpperCase();
    const terminal =
      phaseUpper === "COMPLETED" || ["STOPPED", "FAILED", "CANCELLED"].includes(statusUpper);
    if (terminal) {
      this._clearFindMaxCountdown();
      return;
    }

    const endEpoch = Number(s.step_end_at_epoch_ms);
    if (!Number.isFinite(endEpoch) || endEpoch <= 0) {
      this._clearFindMaxCountdown();
      return;
    }

    const target = Math.trunc(endEpoch);
    if (this._findMaxCountdownTargetEpochMs === target && this._findMaxCountdownIntervalId) {
      return;
    }

    this._clearFindMaxCountdown();
    this._findMaxCountdownTargetEpochMs = target;

    const tick = () => {
      const remaining = Math.max(0, Math.ceil((target - Date.now()) / 1000));
      this.findMaxCountdownSeconds = remaining;
      if (remaining <= 0 && this._findMaxCountdownIntervalId) {
        clearInterval(this._findMaxCountdownIntervalId);
        this._findMaxCountdownIntervalId = null;
      }
    };

    tick();
    this._findMaxCountdownIntervalId = setInterval(tick, 250);
  },
};
