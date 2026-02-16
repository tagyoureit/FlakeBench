// @ts-check

/**
 * Shared display utilities for formatting test configurations.
 *
 * Used by templates_manager.js, history.js, and dashboard/display.js
 * for consistent display of load modes, scaling, workloads, etc.
 */

// =============================================================================
// Table Type Helpers
// =============================================================================

/**
 * Normalize table type to uppercase key.
 * @param {object | null | undefined} data - Object with table_type or config.table_type
 * @returns {string}
 */
function tableTypeKey(data) {
  // Handle both test results (data.table_type) and templates (data.config.table_type)
  const tableType = data?.table_type || data?.config?.table_type || "";
  return String(tableType).trim().toUpperCase();
}

/**
 * Get human-readable label for table type.
 * @param {object | null | undefined} data - Object with table_type
 * @returns {string}
 */
function tableTypeLabel(data) {
  const t = tableTypeKey(data);
  if (t === "POSTGRES") return "POSTGRES";
  if (t === "HYBRID") return "HYBRID";
  if (t === "STANDARD") return "STANDARD";
  if (t === "INTERACTIVE") return "INTERACTIVE";
  if (t === "VIEW") return "VIEW";
  return t || "";
}

/**
 * Get icon path for table type.
 * @param {object | null | undefined} data - Object with table_type
 * @returns {string}
 */
function tableTypeIconSrc(data) {
  const t = tableTypeKey(data);
  if (t === "POSTGRES") {
    return "/static/img/postgres_elephant.svg";
  }
  if (t === "HYBRID") {
    return "/static/img/table_hybrid.svg";
  }
  if (t === "STANDARD") {
    return "/static/img/table_standard.svg";
  }
  if (t === "INTERACTIVE") {
    return "/static/img/table_interactive.svg";
  }
  if (t === "VIEW") {
    return "/static/img/table_view.svg";
  }
  return "";
}

/**
 * Check if table type is Postgres.
 * @param {object | null | undefined} data - Object with table_type
 * @returns {boolean}
 */
function isPostgresType(data) {
  const t = tableTypeKey(data);
  return t === "POSTGRES";
}

// =============================================================================
// Load Mode Display
// =============================================================================

/**
 * Format load mode for display.
 * @param {object | null | undefined} config - Configuration object with load_mode
 * @returns {string} HTML string for display
 */
function loadModeDisplay(config) {
  const loadMode = String(config?.load_mode || "CONCURRENCY").toUpperCase();

  if (loadMode === "QPS") {
    const targetQps = config?.target_qps || "—";
    return `QPS: ${targetQps}`;
  }
  if (loadMode === "FIND_MAX_CONCURRENCY") {
    const start = config?.start_concurrency || 5;
    const inc = config?.concurrency_increment || 10;
    return `Find Max: ${start}+${inc}`;
  }
  // CONCURRENCY mode
  const threads = config?.concurrent_connections || "—";
  return `Fixed: ${threads} threads`;
}

/**
 * Format load mode for verbose display (used in dashboard).
 * @param {object | null | undefined} config - Configuration object with load_mode
 * @returns {string} Longer format string
 */
function loadModeDisplayVerbose(config) {
  const loadMode = String(config?.load_mode || "CONCURRENCY").toUpperCase();

  if (loadMode === "QPS") {
    const targetQps = config?.target_qps ?? "";
    const startingThreads = config?.starting_threads ?? config?.starting_qps ?? 0;
    const maxThreadIncrease = config?.max_thread_increase ?? config?.max_qps_increase ?? 15;
    return `QPS Mode: Target ${targetQps} QPS (start: ${startingThreads}, ±${maxThreadIncrease}/~10s)`;
  }

  if (loadMode === "FIND_MAX_CONCURRENCY") {
    const startConc = config?.start_concurrency ?? 5;
    const increment = config?.concurrency_increment ?? 10;
    return `Find Max: start ${startConc}, +${increment}/step`;
  }

  // CONCURRENCY mode
  const threads = config?.concurrent_connections ?? "";
  return `Concurrency Mode: ${threads} threads`;
}

// =============================================================================
// Scaling Display
// =============================================================================

/**
 * Format scaling configuration for display.
 * @param {object | null | undefined} config - Configuration object with scaling
 * @returns {string} HTML string for display
 */
function scalingDisplay(config) {
  const scaling = config?.scaling;
  if (!scaling) return "—";

  const mode = String(scaling.mode || "AUTO").toUpperCase();
  const minW = Number(scaling.min_workers ?? 1);
  const maxW = scaling.max_workers != null ? Number(scaling.max_workers) : null;
  const minC = Number(scaling.min_connections ?? 1);
  const maxC = scaling.max_connections != null ? Number(scaling.max_connections) : null;

  if (mode === "FIXED") {
    // FIXED mode uses min_workers and min_connections as the fixed values
    return `FIXED<br><span style="color: #6b7280; font-size: 0.85em;">${minW}w × ${minC}c</span>`;
  }

  if (mode === "AUTO") {
    // AUTO with no meaningful bounds - just show AUTO
    if (maxW === null || minW === maxW) {
      return "AUTO";
    }
    // AUTO with bounds specified
    return `AUTO<br><span style="color: #6b7280; font-size: 0.85em;">${minW}-${maxW}w</span>`;
  }

  // BOUNDED mode - show range with possible unbounded
  const workerPart = maxW === null ? `${minW}+w` : (minW === maxW ? `${minW}w` : `${minW}-${maxW}w`);
  const connPart = maxC === null ? `${minC}+c` : (minC === maxC ? `${minC}c` : `${minC}-${maxC}c`);
  return `BOUNDED<br><span style="color: #6b7280; font-size: 0.85em;">${workerPart} × ${connPart}</span>`;
}

/**
 * Get scaling mode from config.
 * @param {object | null | undefined} config - Configuration object
 * @returns {string}
 */
function scalingMode(config) {
  const scaling = config?.scaling;
  if (!scaling) return "FIXED";
  return String(scaling.mode || "AUTO").toUpperCase();
}

// =============================================================================
// Workload Display
// =============================================================================

/**
 * Format workload mix for display.
 * @param {object | null | undefined} config - Configuration object with workload percentages
 * @returns {string} HTML string for display
 */
function workloadMixDisplay(config) {
  const pl = Number(config?.custom_point_lookup_pct || 0);
  const rs = Number(config?.custom_range_scan_pct || 0);
  const ins = Number(config?.custom_insert_pct || 0);
  const upd = Number(config?.custom_update_pct || 0);
  const total = pl + rs + ins + upd;
  if (total === 0) return "—";

  const parts = [];
  if (pl > 0) parts.push(`PL ${pl}%`);
  if (rs > 0) parts.push(`RS ${rs}%`);
  if (ins > 0) parts.push(`INS ${ins}%`);
  if (upd > 0) parts.push(`UPD ${upd}%`);
  return parts.join("<br>");
}

/**
 * Format workload mix as single line (for compact display).
 * @param {object | null | undefined} config - Configuration object
 * @returns {string}
 */
function workloadMixCompact(config) {
  const pl = Number(config?.custom_point_lookup_pct || 0);
  const rs = Number(config?.custom_range_scan_pct || 0);
  const ins = Number(config?.custom_insert_pct || 0);
  const upd = Number(config?.custom_update_pct || 0);
  const total = pl + rs + ins + upd;
  if (total === 0) return "";

  const parts = [];
  if (pl > 0) parts.push(`PL ${pl}%`);
  if (rs > 0) parts.push(`RS ${rs}%`);
  if (ins > 0) parts.push(`INS ${ins}%`);
  if (upd > 0) parts.push(`UPD ${upd}%`);
  return parts.join(" • ");
}

/**
 * Format workload reads (Point Lookup + Range Scan) for display.
 * @param {object | null | undefined} config - Configuration object
 * @returns {string}
 */
function workloadReadsDisplay(config) {
  const pl = Number(config?.custom_point_lookup_pct || 0);
  const rs = Number(config?.custom_range_scan_pct || 0);
  const parts = [];
  if (pl > 0) parts.push(`PL ${pl}%`);
  if (rs > 0) parts.push(`RS ${rs}%`);
  if (parts.length === 0) return "";
  return parts.join(" • ");
}

/**
 * Format workload writes (Insert + Update) for display.
 * @param {object | null | undefined} config - Configuration object
 * @returns {string}
 */
function workloadWritesDisplay(config) {
  const ins = Number(config?.custom_insert_pct || 0);
  const upd = Number(config?.custom_update_pct || 0);
  const parts = [];
  if (ins > 0) parts.push(`INS ${ins}%`);
  if (upd > 0) parts.push(`UPD ${upd}%`);
  if (parts.length === 0) return "";
  return parts.join(" • ");
}

/**
 * Derive a workload label from percentages.
 * @param {object | null | undefined} config - Configuration object
 * @returns {string}
 */
function deriveWorkloadLabel(config) {
  const pl = Number(config?.custom_point_lookup_pct || 0);
  const rs = Number(config?.custom_range_scan_pct || 0);
  const ins = Number(config?.custom_insert_pct || 0);
  const upd = Number(config?.custom_update_pct || 0);

  const readPct = pl + rs;
  const writePct = ins + upd;

  if (readPct === 0 && writePct > 0) return "WRITE_ONLY";
  if (writePct === 0 && readPct > 0) return "READ_ONLY";
  if (readPct >= 75) return "READ_HEAVY";
  if (writePct >= 75) return "WRITE_HEAVY";
  return "MIXED";
}

// =============================================================================
// Duration Display
// =============================================================================

/**
 * Format duration with warmup breakdown.
 * @param {object | null | undefined} config - Configuration object with duration/warmup
 * @returns {string} HTML string for display
 */
function durationDisplay(config) {
  const loadMode = String(config?.load_mode || "CONCURRENCY").toUpperCase();
  
  if (loadMode === "FIND_MAX_CONCURRENCY") {
    const start = Number(config?.start_concurrency || 0);
    const inc = Number(config?.concurrency_increment || 0);
    if (start > 0 && inc > 0) {
      return `<span style="color: #6b7280; font-size: 0.85em;">start ${start}, +${inc}</span>`;
    }
    return "—";
  }

  const duration = Number(config?.duration || config?.duration_seconds || 0);
  const warmup = Number(config?.warmup || config?.warmup_seconds || 0);
  if (duration <= 0) return "—";

  const total = warmup + duration;
  if (warmup > 0) {
    return `${total}s<br><span style="color: #6b7280; font-size: 0.85em;">${warmup}s + ${duration}s</span>`;
  }
  return `${duration}s`;
}

/**
 * Format duration as simple text.
 * @param {object | null | undefined} config - Configuration object
 * @returns {string}
 */
function durationSimple(config) {
  const duration = Number(config?.duration || 0);
  const warmup = Number(config?.warmup || 0);
  if (duration <= 0) return "—";

  const total = warmup + duration;
  if (warmup > 0) {
    return `${total}s (${warmup}s warmup + ${duration}s)`;
  }
  return `${duration}s`;
}

// =============================================================================
// Warehouse / Size Display
// =============================================================================

/**
 * Format warehouse or instance size for display.
 * @param {object | null | undefined} data - Object with config or direct fields
 * @returns {string} HTML string for display
 */
function warehouseDisplay(data) {
  // Handle both templates (data.config) and test results (data directly)
  const config = data?.config || data;
  if (!config) return "—";

  const tableType = String(config.table_type || "").toUpperCase();
  if (tableType === "POSTGRES") {
    // Show Postgres instance size (e.g., STANDARD_M)
    const instanceSize = config.postgres_instance_size || "—";
    return instanceSize;
  }

  // For Snowflake, show warehouse size (and name if there's room)
  const name = config.warehouse_name || config.warehouse || "";
  const size = config.warehouse_size || "";
  if (size && name) {
    return `${size}<br><span style="color: #6b7280; font-size: 0.85em;">${name}</span>`;
  }
  if (size) return size;
  if (name) return name;
  return "—";
}

/**
 * Get simple size string (no HTML).
 * @param {object | null | undefined} data - Object with config or direct fields
 * @returns {string}
 */
function sizeSimple(data) {
  const config = data?.config || data;
  if (!config) return "—";

  const tableType = String(config.table_type || "").toUpperCase();
  if (tableType === "POSTGRES") {
    return config.postgres_instance_size || "—";
  }
  return config.warehouse_size || config.warehouse_name || "—";
}

// =============================================================================
// Table FQN Display
// =============================================================================

/**
 * Format fully qualified table name.
 * @param {object | null | undefined} data - Object with config or direct fields
 * @returns {string}
 */
function tableFqn(data) {
  const config = data?.config || data;
  const db = String(config?.database || "").trim();
  const sch = String(config?.schema || "").trim();
  const tbl = String(config?.table_name || "").trim();
  const parts = [db, sch, tbl].filter(Boolean);
  return parts.join(".");
}

/**
 * Format table name stacked (DB, Schema, Table on separate lines).
 * @param {object | null | undefined} data - Object with config or direct fields
 * @returns {string} HTML string with line breaks
 */
function tableFqnStacked(data) {
  const config = data?.config || data;
  const db = (config?.database ?? "").toString().trim();
  const sch = (config?.schema ?? "").toString().trim();
  const tbl = (config?.table_name ?? "").toString().trim();
  if (!db && !sch && !tbl) return "—";
  return `${db || "—"}<br><span style="color: #6b7280; font-size: 0.85em;">${sch || "—"}<br>${tbl || "—"}</span>`;
}

// =============================================================================
// Export
// =============================================================================

if (typeof window !== "undefined") {
  window.DisplayUtils = {
    // Table type helpers
    tableTypeKey,
    tableTypeLabel,
    tableTypeIconSrc,
    isPostgresType,

    // Load mode
    loadModeDisplay,
    loadModeDisplayVerbose,

    // Scaling
    scalingDisplay,
    scalingMode,

    // Workload
    workloadMixDisplay,
    workloadMixCompact,
    workloadReadsDisplay,
    workloadWritesDisplay,
    deriveWorkloadLabel,

    // Duration
    durationDisplay,
    durationSimple,

    // Warehouse/Size
    warehouseDisplay,
    sizeSimple,

    // Table FQN
    tableFqn,
    tableFqnStacked,
  };
}
