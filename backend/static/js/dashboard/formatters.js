/**
 * Dashboard Formatters Module
 * Utility functions for formatting values (numbers, percentages, time, etc.)
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.formatters = {
  formatMsPrecise(value) {
    // Show exact milliseconds with commas for readability
    if (value == null) return "";
    const ms = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(ms)) return "";
    // Format with commas and 2 decimal places
    return `${ms.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ms`;
  },

  formatSecondsTenths(value) {
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "0";
    // Display in whole seconds (no tenths) for all charts/tooltips.
    return String(Math.trunc(n));
  },

  formatCompact(value) {
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "0";

    const abs = Math.abs(n);
    const format = (x, suffix) => {
      const formatted = x.toFixed(2);
      const clean = formatted.replace(/\.00$/, '');
      return `${clean}${suffix}`;
    };

    if (abs >= 1e12) return format(n / 1e12, "T");
    if (abs >= 1e9) return format(n / 1e9, "B");
    if (abs >= 1e6) return format(n / 1e6, "M");
    if (abs >= 1e3) return format(n / 1e3, "k");
    return Number.isInteger(n) ? n.toLocaleString() : n.toFixed(2);
  },

  formatMs(value) {
    if (value == null) return "N/A";
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "N/A";
    return Math.round(n).toLocaleString();
  },

  formatMsWithUnit(value) {
    if (value == null) return "N/A";
    const ms = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(ms)) return "N/A";
    
    // For small values, show milliseconds
    if (ms < 1000) {
      return `${ms.toFixed(2)} ms`;
    }
    
    // Convert to seconds
    const totalSeconds = ms / 1000;
    
    // For values < 1 minute, show ss.ss s
    if (totalSeconds < 60) {
      return `${totalSeconds.toFixed(2)}s`;
    }
    
    // For values < 1 hour, show Xm Ys format
    if (totalSeconds < 3600) {
      const minutes = Math.floor(totalSeconds / 60);
      const seconds = totalSeconds % 60;
      return `${minutes}m ${seconds.toFixed(2)}s`;
    }
    
    // For values >= 1 hour, show Xh Ym Zs format
    const hours = Math.floor(totalSeconds / 3600);
    const remainingAfterHours = totalSeconds % 3600;
    const minutes = Math.floor(remainingAfterHours / 60);
    const seconds = remainingAfterHours % 60;
    return `${hours}h ${minutes}m ${seconds.toFixed(2)}s`;
  },

  formatInt(value) {
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "0";
    return String(Math.trunc(n));
  },

  formatPct(value, digits = 2) {
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "N/A";
    const d = typeof digits === "number" ? digits : Number(digits);
    const pct = n > 1 ? n : n * 100.0;
    return `${pct.toFixed(Number.isFinite(d) ? d : 2)}%`;
  },

  formatPctValue(value, digits = 2) {
    // Always interpret value as a percentage already in [0,100].
    if (value == null) return "N/A";
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "N/A";
    const d = typeof digits === "number" ? digits : Number(digits);
    return `${n.toFixed(Number.isFinite(d) ? d : 2)}%`;
  },

  formatSignedPct(value, digits = 2) {
    if (value == null) return "N/A";
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "N/A";
    const d = typeof digits === "number" ? digits : Number(digits);
    const prefix = n >= 0 ? "+" : "";
    return `${prefix}${n.toFixed(Number.isFinite(d) ? d : 2)}%`;
  },

  formatTargetMs(value) {
    if (value == null) return "N/A";
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "N/A";
    if (n < 0) return "Disabled";
    // 0 is considered an invalid latency target; render explicitly.
    if (n === 0) return "Unset";
    return this.formatMs(n);
  },

  formatTargetPct(value, digits = 2) {
    if (value == null) return "N/A";
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n)) return "N/A";
    if (n < 0) return "Disabled";
    const d = typeof digits === "number" ? digits : Number(digits);
    return `${n.toFixed(Number.isFinite(d) ? d : 2)}%`;
  },

  formatBytes(value) {
    if (value == null) return "N/A";
    const n = typeof value === "number" ? value : Number(value);
    if (!Number.isFinite(n) || n < 0) return "N/A";
    
    const units = ["B", "KB", "MB", "GB", "TB"];
    let unitIndex = 0;
    let size = n;
    
    while (size >= 1024 && unitIndex < units.length - 1) {
      size /= 1024;
      unitIndex++;
    }
    
    // Show 2 decimal places for KB and above, whole numbers for bytes
    const formatted = unitIndex === 0 ? Math.round(size) : size.toFixed(2);
    return `${formatted} ${units[unitIndex]}`;
  },
};
