/**
 * Dashboard Breakdown Module
 * Methods for toggling chart breakdown views (read/write vs by-kind).
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.breakdown = {
  setSfRunningBreakdown(mode) {
    const m = mode != null ? String(mode) : "";
    if (m === "by_kind") {
      this.sfRunningBreakdown = "by_kind";
    } else {
      this.sfRunningBreakdown = "read_write";
    }
    this.applySfRunningBreakdownToChart();
  },

  applySfRunningBreakdownToChart(opts) {
    const options = opts && typeof opts === "object" ? opts : {};
    const skipUpdate = !!options.skipUpdate;

    const canvas = document.getElementById("sfRunningChart");
    const chart =
      canvas &&
      (canvas.__chart ||
        (window.Chart && Chart.getChart ? Chart.getChart(canvas) : null));
    if (!canvas || !chart) return;

    const byKind = this.sfRunningBreakdown === "by_kind";
    const dsets =
      chart.data && Array.isArray(chart.data.datasets)
        ? chart.data.datasets
        : [];

    const isReadWrite = (label) => {
      const l = String(label || "").toLowerCase();
      return l.startsWith("reads") || l.startsWith("writes");
    };
    const isKind = (label) => {
      const l = String(label || "").toLowerCase();
      return (
        l.startsWith("point") ||
        l.startsWith("range") ||
        l.startsWith("insert") ||
        l.startsWith("update") ||
        l.startsWith("generic")
      );
    };

    for (const ds of dsets) {
      const label = ds && ds.label ? ds.label : "";
      if (isReadWrite(label)) ds.hidden = byKind;
      if (isKind(label)) ds.hidden = !byKind;
    }

    if (!skipUpdate) {
      chart.update();
    }
  },

  // Postgres Running Queries breakdown toggle
  setPgRunningBreakdown(mode) {
    const m = mode != null ? String(mode) : "";
    if (m === "by_kind") {
      this.pgRunningBreakdown = "by_kind";
    } else {
      this.pgRunningBreakdown = "read_write";
    }
    this.applyPgRunningBreakdownToChart();
  },

  applyPgRunningBreakdownToChart(opts) {
    const options = opts && typeof opts === "object" ? opts : {};
    const skipUpdate = !!options.skipUpdate;

    const canvas = document.getElementById("pgRunningChart");
    const chart =
      canvas &&
      (canvas.__chart ||
        (window.Chart && Chart.getChart ? Chart.getChart(canvas) : null));
    if (!canvas || !chart) return;

    const byKind = this.pgRunningBreakdown === "by_kind";
    const dsets =
      chart.data && Array.isArray(chart.data.datasets)
        ? chart.data.datasets
        : [];

    const isReadWrite = (label) => {
      const l = String(label || "").toLowerCase();
      return l.startsWith("reads") || l.startsWith("writes");
    };
    const isKind = (label) => {
      const l = String(label || "").toLowerCase();
      return (
        l.startsWith("point") ||
        l.startsWith("range") ||
        l.startsWith("insert") ||
        l.startsWith("update") ||
        l.startsWith("generic")
      );
    };

    for (const ds of dsets) {
      const label = ds && ds.label ? ds.label : "";
      if (isReadWrite(label)) ds.hidden = byKind;
      if (isKind(label)) ds.hidden = !byKind;
    }

    if (!skipUpdate) {
      chart.update();
    }
  },

  setOpsSecBreakdown(mode) {
    const m = mode != null ? String(mode) : "";
    if (m === "by_kind") {
      this.opsSecBreakdown = "by_kind";
    } else {
      this.opsSecBreakdown = "read_write";
    }
    this.applyOpsSecBreakdownToChart();
  },

  applyOpsSecBreakdownToChart(opts) {
    const options = opts && typeof opts === "object" ? opts : {};
    const skipUpdate = !!options.skipUpdate;

    const canvas = document.getElementById("opsSecChart");
    const chart =
      canvas &&
      (canvas.__chart ||
        (window.Chart && Chart.getChart ? Chart.getChart(canvas) : null));
    if (!canvas || !chart) return;

    const byKind = this.opsSecBreakdown === "by_kind";
    const dsets =
      chart.data && Array.isArray(chart.data.datasets)
        ? chart.data.datasets
        : [];

    const isReadWrite = (label) => {
      const l = String(label || "").toLowerCase();
      return l === "reads" || l === "writes";
    };
    const isKind = (label) => {
      const l = String(label || "").toLowerCase();
      return (
        l.startsWith("point") ||
        l.startsWith("range") ||
        l.startsWith("insert") ||
        l.startsWith("update") ||
        l.startsWith("generic")
      );
    };

    for (const ds of dsets) {
      const label = ds && ds.label ? ds.label : "";
      if (isReadWrite(label)) ds.hidden = byKind;
      if (isKind(label)) ds.hidden = !byKind;
    }

    if (!skipUpdate) {
      chart.update();
    }
  },

  setWarehouseQueueMode(mode) {
    const m = mode != null ? String(mode) : "";
    if (m === "total") {
      this.warehouseQueueMode = "total";
    } else {
      this.warehouseQueueMode = "avg";
    }
    this.renderWarehouseTimeseriesChart();
  },
};
