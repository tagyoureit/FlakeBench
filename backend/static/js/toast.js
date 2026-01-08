(() => {
  const CONTAINER_ID = "toast-container";
  const NEXT_TOASTS_KEY = "unistore_toast_next";

  const DEFAULT_CONFIRMATION_DURATION_MS = 10_000;
  const DEFAULT_CONFIRM_DURATION_MS = 10_000;

  /**
   * @typedef {"success"|"info"|"warning"|"error"} ToastType
   */

  /**
   * @param {ToastType} type
   */
  function roleForType(type) {
    return type === "error" ? "alert" : "status";
  }

  /**
   * @param {ToastType} type
   * @param {{ durationMs?: number } | undefined} options
   * @returns {number | null}
   */
  function durationFor(type, options) {
    if (options && typeof options.durationMs === "number") return options.durationMs;

    // Errors and warnings are sticky until dismissed.
    if (type === "error" || type === "warning") return null;

    // Confirmations (success/info) default to 10s.
    return DEFAULT_CONFIRMATION_DURATION_MS;
  }

  function ensureContainer() {
    let container = document.getElementById(CONTAINER_ID);
    if (container) return container;

    container = document.createElement("div");
    container.id = CONTAINER_ID;
    container.className = "toast-container";
    container.setAttribute("aria-live", "polite");
    container.setAttribute("aria-atomic", "true");
    document.body.appendChild(container);
    return container;
  }

  /**
   * @param {unknown} message
   * @returns {string}
   */
  function normalizeMessage(message) {
    if (message == null) return "";
    if (typeof message === "string") return message;
    if (message instanceof Error) return message.message || String(message);
    try {
      return JSON.stringify(message);
    } catch {
      return String(message);
    }
  }

  function createTimerEl(durationMs) {
    if (typeof durationMs !== "number" || !Number.isFinite(durationMs) || durationMs <= 0) {
      return null;
    }
    const timer = document.createElement("div");
    timer.className = "toast__timer";
    timer.setAttribute("aria-hidden", "true");
    timer.style.setProperty("--toast-duration", `${durationMs}ms`);
    return timer;
  }

  /**
   * @param {ToastType} type
   * @param {string} message
   * @param {{ durationMs?: number }=} options
   */
  function show(type, message, options) {
    const container = ensureContainer();

    const toast = document.createElement("div");
    toast.className = `toast toast--${type}`;
    toast.setAttribute("role", roleForType(type));
    toast.setAttribute("aria-live", type === "error" ? "assertive" : "polite");

    const content = document.createElement("div");
    content.className = "toast__content";
    content.textContent = message;

    const close = document.createElement("button");
    close.type = "button";
    close.className = "toast__close";
    close.setAttribute("aria-label", "Dismiss notification");
    close.textContent = "×";

    let dismissTimer = null;
    const removeToast = () => {
      if (dismissTimer) window.clearTimeout(dismissTimer);
      toast.classList.remove("toast--visible");
      window.setTimeout(() => {
        toast.remove();
      }, 180);
    };

    close.addEventListener("click", removeToast);
    toast.appendChild(content);
    toast.appendChild(close);

     const durationMs = durationFor(type, options);
     const timerEl = createTimerEl(durationMs);
     if (timerEl) {
       toast.classList.add("toast--timed");
       toast.appendChild(timerEl);
     }

    container.appendChild(toast);

    // Trigger CSS transitions
    window.requestAnimationFrame(() => {
      toast.classList.add("toast--visible");
    });

    if (typeof durationMs === "number") {
      dismissTimer = window.setTimeout(removeToast, durationMs);
    }
  }

  /**
   * Queue toasts for the next full page load (useful for redirects).
   * @param {ToastType} type
   * @param {unknown} message
   * @param {{ durationMs?: number }=} options
   */
  function queueNext(type, message, options) {
    const payload = {
      type,
      message: normalizeMessage(message),
      durationMs: options?.durationMs,
    };
    try {
      const existingRaw = window.sessionStorage.getItem(NEXT_TOASTS_KEY);
      const existing = existingRaw ? JSON.parse(existingRaw) : [];
      const next = Array.isArray(existing) ? existing.concat([payload]) : [payload];
      window.sessionStorage.setItem(NEXT_TOASTS_KEY, JSON.stringify(next));
    } catch {
      // If storage is unavailable, just show immediately.
      show(type, payload.message, { durationMs: payload.durationMs });
    }
  }

  function flushNextToasts() {
    try {
      const raw = window.sessionStorage.getItem(NEXT_TOASTS_KEY);
      if (!raw) return;
      window.sessionStorage.removeItem(NEXT_TOASTS_KEY);
      const items = JSON.parse(raw);
      if (!Array.isArray(items)) return;
      for (const item of items) {
        const type = item?.type;
        const message = item?.message;
        if (!type || !message) continue;
        show(type, String(message), { durationMs: item?.durationMs });
      }
    } catch {
      // ignore
    }
  }

  /**
   * @param {unknown} message
   * @param {{
   *   confirmText?: string,
   *   cancelText?: string,
   *   confirmVariant?: "danger" | "primary",
   *   timeoutMs?: number,
   * }=} options
   * @returns {Promise<boolean>}
   */
  function confirm(message, options) {
    const container = ensureContainer();
    const msg = normalizeMessage(message);
    const confirmText = options?.confirmText || "OK";
    const cancelText = options?.cancelText || "Cancel";
    const confirmVariant = options?.confirmVariant || "primary";
    const timeoutMs =
      typeof options?.timeoutMs === "number" ? options.timeoutMs : DEFAULT_CONFIRM_DURATION_MS;

    return new Promise((resolve) => {
      const toast = document.createElement("div");
      toast.className = "toast toast--confirm toast--timed";
      toast.setAttribute("role", "alertdialog");
      toast.setAttribute("aria-live", "assertive");

      const content = document.createElement("div");
      content.className = "toast__content";
      content.textContent = msg;

      const actions = document.createElement("div");
      actions.className = "toast__actions";

      const cancelBtn = document.createElement("button");
      cancelBtn.type = "button";
      cancelBtn.className = "toast__action toast__action--cancel";
      cancelBtn.textContent = cancelText;

      const confirmBtn = document.createElement("button");
      confirmBtn.type = "button";
      confirmBtn.className = `toast__action toast__action--confirm toast__action--${confirmVariant}`;
      confirmBtn.textContent = confirmText;

      const close = document.createElement("button");
      close.type = "button";
      close.className = "toast__close";
      close.setAttribute("aria-label", "Cancel");
      close.textContent = "×";

      let finished = false;
      let dismissTimer = null;

      const finish = (result) => {
        if (finished) return;
        finished = true;
        if (dismissTimer) window.clearTimeout(dismissTimer);
        toast.classList.remove("toast--visible");
        window.setTimeout(() => toast.remove(), 180);
        resolve(result);
      };

      cancelBtn.addEventListener("click", () => finish(false));
      close.addEventListener("click", () => finish(false));
      confirmBtn.addEventListener("click", () => finish(true));

      actions.appendChild(cancelBtn);
      actions.appendChild(confirmBtn);

      toast.appendChild(content);
      toast.appendChild(actions);
      toast.appendChild(close);

      const timerEl = createTimerEl(timeoutMs);
      if (timerEl) toast.appendChild(timerEl);

      container.appendChild(toast);

      window.requestAnimationFrame(() => {
        toast.classList.add("toast--visible");
        // Focus the primary action for keyboard users.
        confirmBtn.focus();
      });

      dismissTimer = window.setTimeout(() => finish(false), timeoutMs);
    });
  }

  const toastApi = {
    show: (type, message, options) =>
      show(type, normalizeMessage(message), options),
    success: (message, options) => show("success", normalizeMessage(message), options),
    info: (message, options) => show("info", normalizeMessage(message), options),
    warning: (message, options) =>
      show("warning", normalizeMessage(message), options),
    error: (message, options) => show("error", normalizeMessage(message), options),
    confirm,
    queueNext: (type, message, options) =>
      queueNext(type, message, options),
    flushNextToasts,
  };

  // Expose globally
  window.toast = toastApi;

  // Show any queued toasts once the DOM is ready.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", flushNextToasts);
  } else {
    flushNextToasts();
  }
})();


