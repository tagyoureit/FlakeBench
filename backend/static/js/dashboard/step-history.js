/**
 * Dashboard Step History Module
 * Methods for displaying Find-Max step history.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.stepHistory = {
  hasStepHistory() {
    const fmr = this.templateInfo?.find_max_result;
    if (!fmr || typeof fmr !== "object") return false;
    const hist = fmr.step_history;
    return Array.isArray(hist) && hist.length > 0;
  },

  hasMultiWorkerStepHistory() {
    const workers = this.templateInfo?.worker_find_max_results;
    return Array.isArray(workers) && workers.length > 1;
  },

  stepHistoryWorkerOptions() {
    const opts = [];
    const agg = this.templateInfo?.aggregated_find_max_result;
    if (agg) {
      const totalQps = agg.final_best_qps ?? "?";
      const workerCount = agg.total_workers ?? "?";
      opts.push({
        value: "aggregate",
        label: `All ${workerCount} Workers (${typeof totalQps === "number" ? totalQps.toFixed(1) : totalQps} QPS total)`,
      });
    }
    const workers = this.templateInfo?.worker_find_max_results;
    if (Array.isArray(workers)) {
      workers.forEach((w, idx) => {
        const fmr = w.find_max_result;
        const bestCc = fmr?.final_best_concurrency ?? fmr?.best_concurrency ?? "?";
        const qps = fmr?.final_best_qps ?? fmr?.best_qps;
        const qpsStr = typeof qps === "number" ? ` @ ${qps.toFixed(1)} QPS` : "";
        opts.push({
          value: String(idx),
          label: `Worker ${w.worker_index} (best=${bestCc}${qpsStr})`,
        });
      });
    }
    return opts;
  },

  selectedFindMaxResult() {
    if (this.selectedStepHistoryWorker === "aggregate") {
      const agg = this.templateInfo?.aggregated_find_max_result;
      if (agg) return agg;
      return this.templateInfo?.find_max_result;
    }
    const idx = parseInt(this.selectedStepHistoryWorker, 10);
    const workers = this.templateInfo?.worker_find_max_results;
    if (Array.isArray(workers) && workers[idx]) {
      return workers[idx].find_max_result;
    }
    return this.templateInfo?.find_max_result;
  },

  stepHistory() {
    const fmr = this.selectedFindMaxResult();
    if (!fmr || typeof fmr !== "object") return [];
    const hist = fmr.step_history;
    return Array.isArray(hist) ? hist : [];
  },

  stepHistorySummary() {
    const fmr = this.selectedFindMaxResult();
    if (!fmr || typeof fmr !== "object") return null;
    const isAgg = !!fmr.is_aggregate;
    return {
      best_concurrency: fmr.final_best_concurrency ?? fmr.best_concurrency ?? null,
      best_qps: fmr.final_best_qps ?? fmr.best_qps ?? null,
      baseline_p95_ms: fmr.baseline_p95_latency_ms ?? null,
      final_reason: fmr.final_reason ?? null,
      total_steps: Array.isArray(fmr.step_history) ? fmr.step_history.length : 0,
      is_aggregate: isAgg,
      total_nodes: isAgg ? fmr.total_nodes : null,
    };
  },

  stepP99DiffPct(step) {
    const fmr = this.selectedFindMaxResult();
    const baseline = fmr?.baseline_p99_latency_ms;
    const current = Number(step?.p99_latency_ms);
    if (!baseline || baseline <= 0 || !Number.isFinite(current) || current <= 0) {
      return null;
    }
    return ((current - baseline) / baseline) * 100.0;
  },

  stepP95DiffPct(step) {
    const fmr = this.selectedFindMaxResult();
    const baseline = fmr?.baseline_p95_latency_ms;
    const current = Number(step?.p95_latency_ms);
    if (!baseline || baseline <= 0 || !Number.isFinite(current) || current <= 0) {
      return null;
    }
    return ((current - baseline) / baseline) * 100.0;
  },
};
