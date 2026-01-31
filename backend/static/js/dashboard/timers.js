/**
 * Dashboard Timers Module
 * Methods for managing elapsed time and processing timers.
 * 
 * SIMPLIFIED DESIGN (2024-01):
 * - Timer is purely LOCAL - no server sync
 * - Starts on button click or first active phase
 * - Counts up continuously, never resets mid-run
 * - Stops only on terminal states (COMPLETED, FAILED, CANCELLED)
 * - Phase-specific timing uses local timestamps recorded at transitions
 * 
 * See docs/failed-timer-learnings.md for history of previous issues.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.timers = {
  _debugLog(module, message, data) {
    if (!this.debug) return;
    if (data !== undefined) {
      console.log(`[${module}] ${message}`, data);
    } else {
      console.log(`[${module}] ${message}`);
    }
  },

  startElapsedTimer(initialValue) {
    this.stopElapsedTimer();
    const base = Number(initialValue) || 0;
    this._elapsedBaseValue = base;
    this._elapsedStartTime = Date.now();
    this._debugLog("TIMER", "STARTED", { initialValue: base, phase: this.phase });
    
    this._elapsedIntervalId = setInterval(() => {
      const secondsSinceStart = (Date.now() - this._elapsedStartTime) / 1000;
      this.elapsed = Math.floor(this._elapsedBaseValue + secondsSinceStart);
      if (this.duration > 0) {
        this.progress = Math.min(100, (this.elapsed / this.duration) * 100);
      }
    }, 250);
  },

  stopElapsedTimer() {
    if (this._elapsedIntervalId) {
      if (this._elapsedStartTime) {
        const secondsSinceStart = (Date.now() - this._elapsedStartTime) / 1000;
        this.elapsed = Math.floor(this._elapsedBaseValue + secondsSinceStart);
      }
      this._debugLog("TIMER", "STOPPED", { finalElapsed: this.elapsed, phase: this.phase });
      clearInterval(this._elapsedIntervalId);
      this._elapsedIntervalId = null;
    }
    this._elapsedStartTime = null;
  },

  recordPhaseStart(phaseName) {
    const now = Date.now();
    const currentElapsed = this.elapsed || 0;
    
    if (phaseName === "WARMUP") {
      this._warmupStartTime = now;
      this._warmupStartElapsed = currentElapsed;
      this._debugLog("TIMER", "WARMUP_START", { elapsed: currentElapsed });
    } else if (phaseName === "RUNNING" || phaseName === "MEASUREMENT") {
      this._runningStartTime = now;
      this._runningStartElapsed = currentElapsed;
      this._debugLog("TIMER", "RUNNING_START", { elapsed: currentElapsed });
    }
  },

  getPhaseElapsed(phaseName) {
    const currentElapsed = this.elapsed || 0;
    
    if (phaseName === "WARMUP") {
      const startElapsed = this._warmupStartElapsed || 0;
      return Math.max(0, currentElapsed - startElapsed);
    } else if (phaseName === "RUNNING" || phaseName === "MEASUREMENT") {
      const startElapsed = this._runningStartElapsed || 0;
      return Math.max(0, currentElapsed - startElapsed);
    }
    return 0;
  },

  isTimerRunning() {
    return !!this._elapsedIntervalId;
  },

  startProcessingLogTimer() {
    this.stopProcessingLogTimer();
    this._processingLogStartMs = Date.now();
    this._processingLogIntervalId = setInterval(() => {
      const elapsedSeconds = Math.floor(
        (Date.now() - this._processingLogStartMs) / 1000,
      );
      console.log(
        `[dashboard] Post-processing still running (${elapsedSeconds}s elapsed)`,
      );
    }, 30000);
  },

  stopProcessingLogTimer() {
    if (this._processingLogIntervalId) {
      clearInterval(this._processingLogIntervalId);
      this._processingLogIntervalId = null;
    }
    this._processingLogStartMs = null;
  },
};
