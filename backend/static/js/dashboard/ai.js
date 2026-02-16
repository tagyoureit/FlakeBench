/**
 * Dashboard AI Module
 * Methods for AI analysis and chat functionality.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.ai = {
  closeAiAnalysis() {
    this.aiAnalysisModal = false;
    this.aiAnalysis = null;
    this.aiAnalysisError = null;
    this.chatHistory = [];
    this.chatMessage = "";
  },

  /**
   * Check if a test status is terminal (test execution has finished).
   * Terminal statuses are: COMPLETED, FAILED, STOPPED, CANCELLED, ERROR
   */
  isTerminalStatus(status) {
    if (!status) return false;
    const s = String(status).toUpperCase();
    return ["COMPLETED", "FAILED", "STOPPED", "CANCELLED", "ERROR"].includes(s);
  },

  /**
   * Retry enrichment for a test that has failed enrichment.
   */
  async retryEnrichment() {
    if (!this.testId || this.enrichmentRetrying) return;

    this.enrichmentRetrying = true;
    try {
      const resp = await fetch(`/api/tests/${this.testId}/retry-enrichment`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        const detail = err.detail;
        const msg = typeof detail === 'object' && detail !== null
          ? (detail.message || JSON.stringify(detail))
          : (detail || `HTTP ${resp.status}`);
        throw new Error(msg);
      }
      const data = await resp.json();
      // Update templateInfo with the new enrichment status
      if (this.templateInfo) {
        this.templateInfo.enrichment_status = data.enrichment_status;
        this.templateInfo.enrichment_error = null;
        this.templateInfo.can_retry_enrichment = false;
      }
      if (window.toast && typeof window.toast.success === "function") {
        const ratio = data.stats?.enrichment_ratio || 0;
        window.toast.success(`Enrichment completed (${ratio}% queries enriched)`);
      }
      // Reload test info to refresh all metrics
      await this.loadTestInfo();
    } catch (e) {
      console.error("Retry enrichment failed:", e);
      if (window.toast && typeof window.toast.error === "function") {
        window.toast.error(`Enrichment failed: ${e.message || e}`);
      }
    } finally {
      this.enrichmentRetrying = false;
    }
  },

  async openAiAnalysis() {
    if (!this.testId) return;
    this.aiAnalysisModal = true;
    this.aiAnalysisLoading = true;
    this.aiAnalysisError = null;
    this.aiAnalysis = null;

    try {
      const resp = await fetch(`/api/tests/${this.testId}/ai-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      this.aiAnalysis = data;
    } catch (e) {
      console.error("AI analysis failed:", e);
      this.aiAnalysisError = e.message || String(e);
    } finally {
      this.aiAnalysisLoading = false;
    }
  },

  async sendChatMessage() {
    const msg = this.chatMessage.trim();
    if (!msg || !this.testId || this.chatLoading) return;

    this.chatHistory.push({ role: "user", content: msg });
    this.chatMessage = "";
    this.chatLoading = true;

    this.$nextTick(() => {
      const container = this.$refs.chatContainer;
      if (container) container.scrollTop = container.scrollHeight;
    });

    try {
      const resp = await fetch(`/api/tests/${this.testId}/ai-chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: msg,
          history: this.chatHistory,
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      this.chatHistory.push({ role: "assistant", content: data.response });
    } catch (e) {
      console.error("AI chat failed:", e);
      this.chatHistory.push({
        role: "assistant",
        content: `Error: ${e.message || e}`,
      });
    } finally {
      this.chatLoading = false;
      this.$nextTick(() => {
        const container = this.$refs.chatContainer;
        if (container) container.scrollTop = container.scrollHeight;
      });
    }
  },

  formatMarkdown(text) {
    if (!text) return "";
    let str = text;
    // Handle JSON-encoded strings from AI_COMPLETE
    if (str.startsWith('"') && str.endsWith('"')) {
      str = str.slice(1, -1);
    }
    str = str.replace(/\\n/g, "\n");
    
    // Use marked library if available for proper markdown rendering
    if (typeof marked !== "undefined" && marked.parse) {
      try {
        return marked.parse(str);
      } catch (e) {
        console.warn("Markdown parsing failed:", e);
      }
    }
    
    // Fallback: basic markdown conversion
    str = str.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    str = str.replace(/\*(.+?)\*/g, "<em>$1</em>");
    str = str.replace(/^### (.+)$/gm, "<h4 style='margin: 0.75rem 0 0.25rem; font-size: 1rem;'>$1</h4>");
    str = str.replace(/^## (.+)$/gm, "<h3 style='margin: 1rem 0 0.5rem; font-size: 1.1rem;'>$1</h3>");
    str = str.replace(/^# (.+)$/gm, "<h2 style='margin: 1rem 0 0.5rem; font-size: 1.25rem;'>$1</h2>");
    str = str.replace(/^- (.+)$/gm, "<li style='margin-left: 1rem;'>$1</li>");
    str = str.replace(/^(\d+)\. (.+)$/gm, "<li style='margin-left: 1rem;'>$2</li>");
    str = str.replace(/`([^`]+)`/g, "<code style='background: #e5e7eb; padding: 0.125rem 0.25rem; border-radius: 0.25rem; font-size: 0.875rem;'>$1</code>");
    str = str.replace(/\n/g, "<br>");
    return str;
  },
};
