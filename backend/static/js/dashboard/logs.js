/**
 * Dashboard Logs Module
 * Methods for loading and managing test logs.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.logs = {
  async loadLogs() {
    if (!this.testId) return;
    if (this._destroyed) return;
    try {
      const params = new URLSearchParams({ limit: String(this.logMaxLines) });
      if (this.logSelectedTestId) {
        params.set("child_test_id", this.logSelectedTestId);
      }
      const resp = await fetch(
        `/api/tests/${this.testId}/logs?${params.toString()}`,
      );
      if (!resp.ok) return;
      const data = await resp.json().catch(() => ({}));
      if (data && Array.isArray(data.workers)) {
        this.logTargets = data.workers;
        const selected = data.selected_test_id || this.logSelectedTestId;
        if (selected) {
          this.logSelectedTestId = selected;
        } else if (this.logTargets.length) {
          this.logSelectedTestId = this.logTargets[0].test_id || null;
        }
      }
      const logs = data && Array.isArray(data.logs) ? data.logs : [];
      this.appendLogs(logs);
    } catch (e) {
      console.error("Failed to load logs:", e);
    }
  },

  onLogTargetChange() {
    this.logs = [];
    this._logSeen = {};
    this.loadLogs();
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

  startMultiNodeLogPolling() {
    if (this._logPollIntervalId) return;
    if (this._destroyed) return;
    const poll = () => {
      if (this._destroyed) {
        this.stopMultiNodeLogPolling();
        return;
      }
      this.loadLogs();
    };
    poll();
    this._logPollIntervalId = setInterval(poll, 1000);
  },

  stopMultiNodeLogPolling() {
    if (!this._logPollIntervalId) return;
    clearInterval(this._logPollIntervalId);
    this._logPollIntervalId = null;
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
};
