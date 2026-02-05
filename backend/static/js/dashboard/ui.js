/**
 * Dashboard UI Module
 * Methods for UI toggles and miscellaneous display helpers.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.ui = {
  toggleClusterBreakdown() {
    this.clusterBreakdownExpanded = !this.clusterBreakdownExpanded;
  },

  clusterBreakdownSummary() {
    const breakdown = this.templateInfo?.cluster_breakdown || [];
    if (!breakdown.length) return null;

    let count = 0;
    let totalQueries = 0;
    let sumP50 = 0;
    let sumP95 = 0;
    let sumQueueOverload = 0;
    let sumQueueProvisioning = 0;
    let totalPl = 0;
    let totalRs = 0;
    let totalIns = 0;
    let totalUpd = 0;
    let unattributedQueries = 0;

    for (const c of breakdown) {
      const clusterNumber = Number(c.cluster_number || 0);
      if (clusterNumber > 0) {
        count += 1;
      } else {
        unattributedQueries += Number(c.query_count || 0);
      }
      totalQueries += Number(c.query_count || 0);
      sumP50 += Number(c.p50_exec_ms || 0);
      sumP95 += Number(c.p95_exec_ms || 0);
      sumQueueOverload += Number(c.avg_queued_overload_ms || 0);
      sumQueueProvisioning += Number(c.avg_queued_provisioning_ms || 0);
      totalPl += Number(c.point_lookups || 0);
      totalRs += Number(c.range_scans || 0);
      totalIns += Number(c.inserts || 0);
      totalUpd += Number(c.updates || 0);
    }

    return {
      cluster_count: count,
      total_queries: totalQueries,
      avg_p50_exec_ms: count > 0 ? sumP50 / count : null,
      avg_p95_exec_ms: count > 0 ? sumP95 / count : null,
      avg_queued_overload_ms: count > 0 ? sumQueueOverload / count : null,
      avg_queued_provisioning_ms: count > 0 ? sumQueueProvisioning / count : null,
      total_point_lookups: totalPl,
      total_range_scans: totalRs,
      total_inserts: totalIns,
      total_updates: totalUpd,
      unattributed_queries: unattributedQueries,
    };
  },

  clusterLabel(cluster) {
    const clusterNumber = Number(cluster?.cluster_number || 0);
    return clusterNumber > 0 ? clusterNumber : "Unattributed";
  },

  toggleStepHistory() {
    this.stepHistoryExpanded = !this.stepHistoryExpanded;
  },

  toggleResourcesHistory() {
    this.resourcesHistoryExpanded = !this.resourcesHistoryExpanded;
  },

  toggleWorkerMetrics(worker) {
    if (!worker || !worker.key) return;
    const key = String(worker.key);
    this.workerMetricsExpanded[key] = !this.workerMetricsExpanded[key];
    if (this.workerMetricsExpanded[key]) {
      this.$nextTick(() => {
        this.renderWorkerMetricsChart(worker);
      });
    }
  },

  renderWorkerMetricsChart(worker) {
    if (!worker || !worker.key) return;
    const canvasId = `workerMetricsChart-${worker.key}`;
    const canvas = document.getElementById(canvasId);
    if (!canvas || !window.Chart) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // Destroy existing chart if any
    if (canvas.__chart) {
      try {
        canvas.__chart.destroy();
      } catch (_) {}
    }

    const snapshots = Array.isArray(worker.snapshots) ? worker.snapshots : [];
    const labels = snapshots.map((s) => s.timestamp);
    const qpsData = snapshots.map((s) => Number(s.qps || 0));
    const p95Data = snapshots.map((s) => Number(s.p95_latency || 0));

    canvas.__chart = new Chart(ctx, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "QPS",
            data: qpsData,
            borderColor: "rgb(59, 130, 246)",
            backgroundColor: "transparent",
            tension: 0.1,
            borderWidth: 2,
            yAxisID: "y",
          },
          {
            label: "P95 latency (ms)",
            data: p95Data,
            borderColor: "rgb(234, 88, 12)",
            backgroundColor: "transparent",
            tension: 0.1,
            borderWidth: 2,
            yAxisID: "y1",
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          y: {
            title: { display: true, text: "QPS" },
            ticks: { callback: (value) => this.formatCompact(value) },
          },
          y1: {
            position: "right",
            title: { display: true, text: "P95 (ms)" },
            ticks: { callback: (value) => this.formatCompact(value) },
            grid: { drawOnChartArea: false },
          },
          x: { display: false },
        },
        plugins: {
          legend: { display: true },
          tooltip: {
            callbacks: {
              label: (ctx) =>
                `${ctx.dataset.label}: ${this.formatCompact(ctx.parsed.y)}`,
            },
          },
        },
      },
    });
  },

  initFloatingToolbar() {
    if (this.mode !== "history") return;

    const SCROLL_THRESHOLD = 300;
    
    const handleScroll = () => {
      this.floatingToolbarVisible = window.scrollY > SCROLL_THRESHOLD;
    };

    window.addEventListener("scroll", handleScroll, { passive: true });
    this._floatingToolbarScrollHandler = handleScroll;
    handleScroll();

    const chartsSection = document.querySelector('[data-section="charts"]');
    const latencySection = document.querySelector('[data-section="latency"]');

    if (chartsSection || latencySection) {
      const observerCallback = (entries) => {
        for (const entry of entries) {
          const section = entry.target.dataset.section;
          if (section === "charts") {
            this.chartsInView = entry.isIntersecting;
          } else if (section === "latency") {
            this.latencyInView = entry.isIntersecting;
          }
        }
      };

      const observer = new IntersectionObserver(observerCallback, {
        root: null,
        rootMargin: "0px",
        threshold: 0,
      });

      if (chartsSection) observer.observe(chartsSection);
      if (latencySection) observer.observe(latencySection);
      this._floatingToolbarObserver = observer;
    }
  },

  destroyFloatingToolbar() {
    if (this._floatingToolbarScrollHandler) {
      window.removeEventListener("scroll", this._floatingToolbarScrollHandler);
      this._floatingToolbarScrollHandler = null;
    }
    if (this._floatingToolbarObserver) {
      this._floatingToolbarObserver.disconnect();
      this._floatingToolbarObserver = null;
    }
  },

  // Error Summary Drill-Down UI Methods
  errorSummaryTotalCount() {
    const h = this.errorSummaryHierarchy;
    if (!h || !h.by_level) return 0;
    return Object.values(h.by_level).reduce((sum, n) => sum + n, 0);
  },

  errorSummaryLevelCount(level) {
    const h = this.errorSummaryHierarchy;
    if (!h || !h.by_level) return 0;
    return h.by_level[level] || 0;
  },

  errorSummaryQueryTypeCount(level, queryType) {
    const h = this.errorSummaryHierarchy;
    if (!h || !h.by_query_type || !h.by_query_type[level]) return 0;
    return h.by_query_type[level][queryType] || 0;
  },

  errorSummaryQueryTypes(level) {
    const h = this.errorSummaryHierarchy;
    if (!h || !h.by_query_type || !h.by_query_type[level]) return [];
    const types = Object.entries(h.by_query_type[level])
      .filter(([_, count]) => count > 0)
      .sort((a, b) => b[1] - a[1])
      .map(([type, count]) => ({ type, count }));
    return types;
  },

  selectErrorLevel(level) {
    if (level === 'TOTAL') {
      this.errorSummarySelectedLevel = null;
      this.errorSummarySelectedQueryType = null;
    } else {
      this.errorSummarySelectedLevel = level;
      this.errorSummarySelectedQueryType = null;
    }
  },

  selectErrorQueryType(queryType) {
    if (queryType === 'TOTAL') {
      this.errorSummarySelectedQueryType = null;
    } else {
      this.errorSummarySelectedQueryType = queryType;
    }
  },

  errorSummaryBreadcrumb() {
    const parts = ['All'];
    if (this.errorSummarySelectedLevel) {
      parts.push(this.errorSummarySelectedLevel);
    }
    if (this.errorSummarySelectedQueryType) {
      parts.push(this.errorSummarySelectedQueryType);
    }
    return parts.join(' > ');
  },

  errorSummaryCanGoBack() {
    return this.errorSummarySelectedLevel || this.errorSummarySelectedQueryType;
  },

  errorSummaryGoBack() {
    if (this.errorSummarySelectedQueryType) {
      this.errorSummarySelectedQueryType = null;
    } else if (this.errorSummarySelectedLevel) {
      this.errorSummarySelectedLevel = null;
    }
  },

  errorSummaryFilteredRows() {
    const rows = this.errorSummaryRows || [];
    const level = this.errorSummarySelectedLevel;
    const queryType = this.errorSummarySelectedQueryType;
    
    return rows.filter(row => {
      if (level && row.level !== level) return false;
      if (queryType && row.query_type !== queryType) return false;
      return true;
    }).sort((a, b) => {
      // Sort by earliest_occurrence ascending (oldest first)
      const timeA = a.earliest_occurrence ? new Date(a.earliest_occurrence).getTime() : Infinity;
      const timeB = b.earliest_occurrence ? new Date(b.earliest_occurrence).getTime() : Infinity;
      return timeA - timeB;
    });
  },

  errorSummaryShowLevel1() {
    return !this.errorSummarySelectedLevel && !this.errorSummarySelectedQueryType;
  },

  errorSummaryShowLevel2() {
    return this.errorSummarySelectedLevel && !this.errorSummarySelectedQueryType;
  },

  errorSummaryShowDetail() {
    return this.errorSummarySelectedQueryType !== null;
  },

  async selectErrorRow(row) {
    if (this.errorSummarySelectedRow && this.errorSummarySelectedRow.message === row.message) {
      this.errorSummarySelectedRow = null;
      this.errorDetailRows = [];
      return;
    }
    this.errorSummarySelectedRow = row;
    this.errorDetailLoading = true;
    this.errorDetailError = null;
    this.errorDetailRows = [];

    try {
      const searchKey = this.extractErrorKey(row.message);
      const resp = await fetch(`/api/tests/${this.testId}/error-details?message=${encodeURIComponent(searchKey)}&limit=50`);
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      const data = await resp.json();
      // Sort by timestamp ascending (oldest first)
      this.errorDetailRows = (data.rows || []).sort((a, b) => {
        const timeA = a.timestamp ? new Date(a.timestamp).getTime() : 0;
        const timeB = b.timestamp ? new Date(b.timestamp).getTime() : 0;
        return timeA - timeB;
      });
    } catch (e) {
      this.errorDetailError = e.message || String(e);
    } finally {
      this.errorDetailLoading = false;
    }
  },

  extractErrorKey(message) {
    const m = message.match(/\(o_orderkey\)=\((\d+)\)/);
    if (m) return m[1];
    const m2 = message.match(/Key \([^)]+\)=\(([^)]+)\)/);
    if (m2) return m2[1];
    return message.substring(0, 100);
  },

  scrollToLogByTimestamp(timestamp, workerTestId, errorMessage) {
    const logSection = document.querySelector('.log-output');
    if (!logSection) return;

    if (workerTestId && this.logTargets) {
      const target = this.logTargets.find(t => String(t.test_id) === String(workerTestId));
      if (target && target.target_id) {
        this.logSelectedTargetIds = [String(target.target_id)];
        if (typeof this.onLogTargetChange === 'function') {
          this.onLogTargetChange();
        }
      }
    }

    logSection.scrollIntoView({ behavior: 'smooth', block: 'start' });

    setTimeout(() => {
      const targetTime = new Date(timestamp).getTime();
      const logLines = logSection.querySelectorAll('.log-line');
      let closest = null;
      let closestDiff = Infinity;
      let exactMatch = null;

      logLines.forEach(line => {
        const tsEl = line.querySelector('.log-ts');
        const msgEl = line.querySelector('.log-msg');
        if (tsEl) {
          const lineTime = new Date(tsEl.getAttribute('data-ts') || tsEl.textContent).getTime();
          const diff = Math.abs(lineTime - targetTime);
          
          if (errorMessage && msgEl) {
            const msgText = msgEl.textContent || '';
            if (msgText.includes(errorMessage) && diff < 60000) {
              exactMatch = line;
            }
          }
          
          if (diff < closestDiff) {
            closestDiff = diff;
            closest = line;
          }
        }
      });

      const targetLine = exactMatch || closest;
      if (targetLine) {
        targetLine.scrollIntoView({ behavior: 'smooth', block: 'center' });
        targetLine.style.backgroundColor = '#fef3c7';
        setTimeout(() => {
          targetLine.style.backgroundColor = '';
        }, 3000);
      }
    }, 500);
  },
};
