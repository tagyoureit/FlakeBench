/**
 * Dashboard Phase Module
 * Methods for test phase management and display.
 * 
 * SIMPLIFIED DESIGN (2024-01):
 * - Phase transitions come from WebSocket PHASE_CHANGED events
 * - Phase timing uses local timestamps from timers.js
 * - No server elapsed values used for phase tracking
 * 
 * See docs/failed-timer-learnings.md for history of previous issues.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.phase = {
  _debugLog(module, message, data) {
    if (!this.debug) return;
    if (data !== undefined) {
      console.log(`[${module}] ${message}`, data);
    } else {
      console.log(`[${module}] ${message}`);
    }
  },

  hasTestStarted() {
    const status = (this.status || "").toString().toUpperCase();
    const notStartedStatuses = ["PENDING", "PREPARED", ""];
    return !notStartedStatuses.includes(status);
  },

  statusRank(status) {
    const s = (status || "").toString().toUpperCase();
    const ranks = {
      "": 0,
      "PENDING": 0,
      "PREPARED": 1,
      "RUNNING": 2,
      "STOPPING": 3,
      "CANCELLING": 3,
      "COMPLETED": 4,
      "FAILED": 4,
      "CANCELLED": 4,
      "STOPPED": 4,
    };
    return ranks[s] ?? 0;
  },

  shouldAcceptStatus(nextStatus) {
    const nextUpper = (nextStatus || "").toString().toUpperCase();
    const currentUpper = (this.status || "").toString().toUpperCase();
    
    if (!currentUpper || currentUpper === "") return true;
    if (nextUpper === currentUpper) return true;
    
    const nextRank = this.statusRank(nextUpper);
    const currentRank = this.statusRank(currentUpper);
    
    return nextRank >= currentRank;
  },

  setStatusIfAllowed(nextStatus, cancellationReason) {
    const prevStatus = this.status;
    const accepted = this.shouldAcceptStatus(nextStatus);
    if (!accepted) {
      this._debugLog("PHASE", "STATUS_REJECTED", { from: prevStatus, rejected: nextStatus });
      return false;
    }
    this.status = nextStatus;
    if (prevStatus !== this.status) {
      this._debugLog("PHASE", "STATUS_CHANGED", { from: prevStatus, to: this.status });
      
      const statusUpper = (this.status || "").toString().toUpperCase();
      if ((statusUpper === "FAILED" || statusUpper === "CANCELLED") && !this._shownCancellationToast) {
        this._shownCancellationToast = true;
        const reason = cancellationReason || (statusUpper === "FAILED" ? "Test failed" : "Test cancelled");
        if (typeof window.toast !== "undefined" && typeof window.toast.error === "function") {
          window.toast.error(`Test ${statusUpper.toLowerCase()}: ${reason}`);
        }
      }
    }
    return true;
  },

  phaseLabel() {
    const phase = this.phase ? String(this.phase) : "";
    const status = (this.status || "").toString().toUpperCase();

    if (status === "CANCELLING") {
      return "Cancelling";
    }

    if (status === "FAILED" || status === "CANCELLED" || status === "STOPPED") {
      return status;
    }

    if (phase.toUpperCase() === "COMPLETED" && status === "FAILED") {
      return "FAILED";
    }

    return phase;
  },

  phaseBadgeClass() {
    const phase = this.normalizePhase(this.phase);
    const status = (this.status || "").toString().toUpperCase();

    if (status === "CANCELLING") return "status-cancelling";

    if (phase === "PREPARING") return "status-preparing";
    if (phase === "WARMUP") return "status-warmup";
    if (phase === "RUNNING") return "status-running";
    if (phase === "PROCESSING") return "status-processing";
    if (phase === "COMPLETED") {
      if (status === "FAILED") return "status-failed";
      if (status === "CANCELLED") return "status-cancelled";
      if (status === "STOPPED") return "status-stopped";
      return "status-completed";
    }
    if (phase === "FAILED") return "status-failed";
    if (phase === "CANCELLED") return "status-cancelled";
    if (phase === "STOPPED") return "status-stopped";

    if (status === "PENDING") return "status-prepared";
    if (status === "RUNNING") return "status-running";
    if (status === "COMPLETED") return "status-completed";
    if (status === "FAILED") return "status-failed";

    return "status-prepared";
  },

  phaseTimingText() {
    const phase = this.normalizePhase(this.phase);
    const status = (this.status || "").toString().toUpperCase();

    if (status === "CANCELLING") return "";

    if (phase === "WARMUP") {
      const ws = Number(this.warmupSeconds || 0);
      const elapsed = this.phaseElapsedSeconds();
      return ws > 0 ? `${Math.floor(elapsed)}s / ${ws}s` : `${Math.floor(elapsed)}s`;
    }
    if (phase === "RUNNING") {
      const rs = Number(this.runSeconds || 0);
      const elapsed = this.phaseElapsedSeconds();
      return rs > 0 ? `${Math.floor(elapsed)}s / ${rs}s` : `${Math.floor(elapsed)}s`;
    }
    return "";
  },

  phaseNames() {
    return ["PREPARING", "WARMUP", "RUNNING", "PROCESSING", "COMPLETED"];
  },

  normalizePhase(phase) {
    const p = (phase || "").toString().toUpperCase();
    if (p === "MEASUREMENT") return "RUNNING";
    return p;
  },

  phaseRank(phase) {
    const normalized = this.normalizePhase(phase);
    const phases = this.phaseNames();
    const idx = phases.indexOf(normalized);
    if (idx >= 0) return idx;
    if (["FAILED", "CANCELLED", "STOPPED"].includes(normalized)) {
      return phases.indexOf("COMPLETED");
    }
    return -1;
  },

  shouldAcceptPhase(nextPhase, status) {
    const normalizedNext = this.normalizePhase(nextPhase);
    if (!normalizedNext) return false;

    const statusUpper = (status || this.status || "").toString().toUpperCase();
    const isStatusTerminal = ["COMPLETED", "FAILED", "CANCELLED", "STOPPED"].includes(statusUpper);
    const isStatusActive = ["RUNNING", "CANCELLING", "STOPPING"].includes(statusUpper);
    const terminalPhases = ["COMPLETED", "FAILED", "CANCELLED", "STOPPED"];
    const isNextTerminal = terminalPhases.includes(normalizedNext);

    if (isStatusActive && isNextTerminal) return false;
    if (isStatusTerminal && !isNextTerminal && normalizedNext !== "PROCESSING") {
      return false;
    }

    const nextRank = this.phaseRank(normalizedNext);
    const currentRank = this.phaseRank(this.phase);
    if (nextRank < 0) return false;
    if (currentRank < 0) return true;
    return nextRank >= currentRank;
  },

  setPhaseIfAllowed(nextPhase, status) {
    const prevPhase = this.phase;
    const accepted = this.shouldAcceptPhase(nextPhase, status);
    if (!accepted) {
      this._debugLog("PHASE", "PHASE_REJECTED", { from: prevPhase, rejected: nextPhase });
      return false;
    }
    
    this.phase = nextPhase;
    const normalizedPrev = this.normalizePhase(prevPhase);
    const normalizedNext = this.normalizePhase(nextPhase);
    
    if (normalizedPrev !== normalizedNext) {
      this._debugLog("PHASE", "PHASE_CHANGED", { from: prevPhase, to: this.phase, status });
      
      if (typeof this.recordPhaseStart === "function") {
        this.recordPhaseStart(normalizedNext);
      }
    }
    return true;
  },

  phaseDisplayNames() {
    return {
      PREPARING: "Preparing",
      WARMUP: "Warmup",
      RUNNING: "Running",
      PROCESSING: "Processing",
      COMPLETED: "Completed",
    };
  },

  currentPhaseIndex() {
    const phase = this.normalizePhase(this.phase);
    const status = (this.status || "").toString().toUpperCase();
    if (status === "PREPARED" && !phase) {
      return -1;
    }
    if (status === "CANCELLING") {
      const idx = this.phaseNames().indexOf(phase);
      return idx >= 0 ? idx : 0;
    }
    const terminalStates = ["FAILED", "CANCELLED", "STOPPED"];
    if (terminalStates.includes(phase) || terminalStates.includes(status)) {
      return this.phaseNames().indexOf("COMPLETED");
    }
    const idx = this.phaseNames().indexOf(phase);
    return idx >= 0 ? idx : 0;
  },

  phaseState(phaseName) {
    const currentIdx = this.currentPhaseIndex();
    const phaseIdx = this.phaseNames().indexOf(phaseName);
    if (phaseIdx < currentIdx) return "completed";
    if (phaseIdx === currentIdx) return "current";
    return "pending";
  },

  phaseBadgeClassNew(phaseName) {
    const state = this.phaseState(phaseName);
    const status = (this.status || "").toString().toUpperCase();
    const isTerminalFailure = ["FAILED", "CANCELLED", "STOPPED"].includes(status);
    
    if (state === "completed") {
      if (isTerminalFailure) {
        return "phase-badge--completed phase-badge--terminal-failure";
      }
      return "phase-badge--completed";
    }
    if (state === "current") {
      if (status === "CANCELLING") return "phase-badge--active phase-badge--cancelling";
      if (isTerminalFailure && phaseName === "COMPLETED") {
        return "phase-badge--active phase-badge--failed";
      }
      const phaseClass = `phase-${phaseName.toLowerCase()}`;
      return `phase-badge--active ${phaseClass}`;
    }
    return "phase-badge--pending";
  },

  isTimedPhase() {
    const phase = this.normalizePhase(this.phase);
    return phase === "WARMUP" || phase === "RUNNING";
  },

  phaseElapsedSeconds() {
    const phase = this.normalizePhase(this.phase);
    
    if (typeof this.getPhaseElapsed === "function") {
      return this.getPhaseElapsed(phase);
    }
    
    const totalElapsed = Number(this.elapsed || 0);
    const warmup = Number(this.warmupSeconds || 0);
    const run = Number(this.runSeconds || 0);

    if (phase === "WARMUP") {
      const warmupStart = Number(this._warmupStartElapsed || 0);
      const phaseElapsed = Math.max(0, totalElapsed - warmupStart);
      return Math.min(phaseElapsed, warmup);
    }
    if (phase === "RUNNING") {
      const runningStart = Number(this._runningStartElapsed || 0);
      if (runningStart > 0) {
        const phaseElapsed = Math.max(0, totalElapsed - runningStart);
        if (run > 0) return Math.min(phaseElapsed, run);
        return phaseElapsed;
      }
      if (warmup > 0) {
        const afterWarmup = Math.max(0, totalElapsed - warmup);
        if (run > 0) return Math.min(afterWarmup, run);
        return afterWarmup;
      }
      if (run > 0) {
        return Math.min(totalElapsed, run);
      }
      return totalElapsed;
    }
    return 0;
  },

  phaseDurationSeconds() {
    const phase = this.normalizePhase(this.phase);
    if (phase === "WARMUP") {
      return Number(this.warmupSeconds || 0);
    }
    if (phase === "RUNNING") {
      return Number(this.runSeconds || 0);
    }
    return 0;
  },

  phaseProgressPercent() {
    const duration = this.phaseDurationSeconds();
    if (duration <= 0) return 0;
    const elapsed = this.phaseElapsedSeconds();
    return Math.min(100, (elapsed / duration) * 100);
  },

  phaseProgressBarClass() {
    const phase = this.normalizePhase(this.phase);
    const status = (this.status || "").toString().toUpperCase();
    if (status === "CANCELLING") return "phase-progress-bar-fill--cancelling";
    if (phase === "WARMUP") return "phase-progress-bar-fill--warmup";
    if (phase === "RUNNING") return "phase-progress-bar-fill--running";
    return "";
  },

  phaseTimingLabel() {
    const duration = this.phaseDurationSeconds();
    const elapsed = Math.floor(this.phaseElapsedSeconds());
    if (duration > 0) {
      return `${elapsed}s / ${duration}s`;
    }
    return `${elapsed}s`;
  },

  currentPhaseDisplayName() {
    const phase = this.normalizePhase(this.phase);
    const status = (this.status || "").toString().toUpperCase();
    if (status === "CANCELLING") return "Cancelling";
    return this.phaseDisplayNames()[phase] || phase;
  },

  completedPhaseDisplayName(phaseName) {
    const status = (this.status || "").toString().toUpperCase();
    const currentPhase = this.normalizePhase(this.phase);
    if (status === "CANCELLING" && currentPhase && phaseName === currentPhase) {
      return "Cancelling";
    }
    if (phaseName === "COMPLETED") {
      if (status === "FAILED") return "Failed";
      if (status === "CANCELLED") return "Cancelled";
      if (status === "STOPPED") return "Stopped";
    }
    return this.phaseDisplayNames()[phaseName] || phaseName;
  },
};
