// @ts-check

/**
 * Cost calculation and formatting utilities for the frontend.
 *
 * Mirrors the backend cost_calculator.py logic for consistent cost display.
 *
 * IMPORTANT: ALL Snowflake compute uses credits, but with different rates:
 * - STANDARD / HYBRID: Standard warehouse credits (Table 1(a))
 * - INTERACTIVE: Interactive warehouse credits (Table 1(d))
 * - SNOWFLAKE_POSTGRES / POSTGRES: Postgres Compute credits (Table 1(i))
 *
 * From Snowflake Service Consumption Table (February 2026):
 * https://www.snowflake.com/legal-files/CreditConsumptionTable.pdf
 */

/**
 * Table types by pricing category.
 */
const WAREHOUSE_TABLE_TYPES = new Set(["STANDARD", "HYBRID"]);
const INTERACTIVE_TABLE_TYPES = new Set(["INTERACTIVE"]);
const POSTGRES_TABLE_TYPES = new Set(["POSTGRES", "SNOWFLAKE_POSTGRES"]);

/**
 * Get the pricing category for a table type.
 * @param {string | null | undefined} tableType - Table type string
 * @returns {"warehouse" | "interactive" | "postgres"}
 */
function getTableTypeCategory(tableType) {
  if (!tableType) return "warehouse"; // Default
  const normalized = tableType.toUpperCase().trim();
  if (POSTGRES_TABLE_TYPES.has(normalized)) return "postgres";
  if (INTERACTIVE_TABLE_TYPES.has(normalized)) return "interactive";
  return "warehouse";
}

/**
 * Table 1(a): Standard Warehouse - Credits consumed per hour.
 */
const WAREHOUSE_CREDITS_PER_HOUR = {
  XSMALL: 1,
  "X-SMALL": 1,
  SMALL: 2,
  MEDIUM: 4,
  LARGE: 8,
  XLARGE: 16,
  "X-LARGE": 16,
  "2XLARGE": 32,
  "2X-LARGE": 32,
  XXLARGE: 32,
  "3XLARGE": 64,
  "3X-LARGE": 64,
  XXXLARGE: 64,
  "4XLARGE": 128,
  "4X-LARGE": 128,
  XXXXLARGE: 128,
  "5XLARGE": 256,
  "5X-LARGE": 256,
  XXXXXLARGE: 256,
  "6XLARGE": 512,
  "6X-LARGE": 512,
  XXXXXXLARGE: 512,
};

/**
 * Table 1(d): Interactive Warehouse - Credits consumed per hour.
 */
const INTERACTIVE_CREDITS_PER_HOUR = {
  XSMALL: 0.6,
  "X-SMALL": 0.6,
  SMALL: 1.2,
  MEDIUM: 2.4,
  LARGE: 4.8,
  XLARGE: 9.6,
  "X-LARGE": 9.6,
  "2XLARGE": 19.2,
  "2X-LARGE": 19.2,
  "3XLARGE": 38.4,
  "3X-LARGE": 38.4,
  "4XLARGE": 76.8,
  "4X-LARGE": 76.8,
};

/**
 * Table 1(i): Snowflake Postgres Compute - Credits per hour (AWS rates).
 * Instance families: STANDARD, HIGHMEM, BURST
 * Note: Azure rates are slightly higher (see full table for Azure-specific rates)
 */
const POSTGRES_CREDITS_PER_HOUR = {
  // Standard instance family
  STANDARD_M: 0.0356,
  STANDARD_L: 0.0712,
  STANDARD_XL: 0.1424,
  STANDARD_2X: 0.2848,
  STANDARD_4XL: 0.5696,
  STANDARD_8XL: 1.1392,
  STANDARD_12XL: 1.7088,
  STANDARD_24XL: 3.4176,
  // High Memory instance family
  HIGHMEM_L: 0.1024,
  HIGHMEM_XL: 0.2048,
  HIGHMEM_2XL: 0.4096,
  HIGHMEM_4XL: 0.8192,
  HIGHMEM_8XL: 1.6384,
  HIGHMEM_12XL: 2.4576,
  HIGHMEM_16XL: 3.2768,
  HIGHMEM_24XL: 4.9152,
  HIGHMEM_32XL: 6.5536,
  HIGHMEM_48XL: 9.8304,
  // Burst instance family
  BURST_XS: 0.0068,
  BURST_S: 0.0136,
  BURST_M: 0.0272,
  // Aliases using traditional warehouse size names (map to STANDARD family)
  XSMALL: 0.0068,    // Maps to BURST_XS
  "X-SMALL": 0.0068,
  SMALL: 0.0136,     // Maps to BURST_S
  MEDIUM: 0.0356,    // Maps to STANDARD_M
  LARGE: 0.0712,     // Maps to STANDARD_L
  XLARGE: 0.1424,    // Maps to STANDARD_XL
  "X-LARGE": 0.1424,
  "2XLARGE": 0.2848, // Maps to STANDARD_2X
  "2X-LARGE": 0.2848,
};

/**
 * Mapping from traditional warehouse size names to proper Postgres instance names.
 * Used to display correct instance names when warehouse sizes are used for Postgres.
 */
const WAREHOUSE_TO_POSTGRES_INSTANCE = {
  XSMALL: "BURST_XS",
  "X-SMALL": "BURST_XS",
  SMALL: "BURST_S",
  MEDIUM: "STANDARD_M",
  LARGE: "STANDARD_L",
  XLARGE: "STANDARD_XL",
  "X-LARGE": "STANDARD_XL",
  "2XLARGE": "STANDARD_2X",
  "2X-LARGE": "STANDARD_2X",
};

/**
 * Check if a size is a proper Postgres instance name.
 * @param {string} size - The size string to check
 * @returns {boolean}
 */
function isValidPostgresInstanceName(size) {
  if (!size) return false;
  const normalized = size.toUpperCase().trim();
  // Check if it starts with a valid Postgres family prefix
  return normalized.startsWith("STANDARD_") || 
         normalized.startsWith("HIGHMEM_") || 
         normalized.startsWith("BURST_");
}

/**
 * Get the proper Postgres instance name for a size.
 * If given a traditional warehouse size, returns the mapped Postgres instance name.
 * @param {string} size - The size string
 * @returns {{ instanceName: string, isAlias: boolean, originalName: string }}
 */
function getPostgresInstanceInfo(size) {
  if (!size) return { instanceName: "Unknown", isAlias: false, originalName: "" };
  const normalized = size.toUpperCase().trim();
  
  if (isValidPostgresInstanceName(normalized)) {
    return { instanceName: normalized, isAlias: false, originalName: normalized };
  }
  
  // Check if it's a warehouse size alias
  const mapped = WAREHOUSE_TO_POSTGRES_INSTANCE[normalized];
  if (mapped) {
    return { instanceName: mapped, isAlias: true, originalName: normalized };
  }
  
  // Unknown size
  return { instanceName: normalized, isAlias: false, originalName: normalized };
}

/**
 * Default cost per credit in dollars.
 * Can be overridden by user settings stored in localStorage.
 */
const DEFAULT_DOLLARS_PER_CREDIT = 4.0;

/**
 * localStorage key for user's cost settings.
 */
const COST_SETTINGS_KEY = "unistore_cost_settings";

/**
 * Get user's cost settings from localStorage.
 * @returns {{ dollarsPerCredit: number, showCredits: boolean, currency: string }}
 */
function getCostSettings() {
  try {
    const stored = localStorage.getItem(COST_SETTINGS_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      return {
        dollarsPerCredit: Number(parsed.dollarsPerCredit) || DEFAULT_DOLLARS_PER_CREDIT,
        showCredits: parsed.showCredits !== false,
        currency: parsed.currency || "USD",
      };
    }
  } catch (_) {
    // Ignore parse errors
  }
  return {
    dollarsPerCredit: DEFAULT_DOLLARS_PER_CREDIT,
    showCredits: true,
    currency: "USD",
  };
}

/**
 * Save user's cost settings to localStorage.
 * @param {{ dollarsPerCredit?: number, showCredits?: boolean, currency?: string }} settings
 */
function saveCostSettings(settings) {
  try {
    const current = getCostSettings();
    const updated = { ...current, ...settings };
    localStorage.setItem(COST_SETTINGS_KEY, JSON.stringify(updated));
  } catch (_) {
    // Ignore storage errors
  }
}

/**
 * Get the credits consumed per hour for a given warehouse size (standard warehouses).
 * @param {string | null | undefined} warehouseSize
 * @returns {number}
 */
function getCreditsPerHour(warehouseSize) {
  if (!warehouseSize) return 0;
  const normalized = String(warehouseSize).toUpperCase().trim();
  return WAREHOUSE_CREDITS_PER_HOUR[normalized] || 0;
}

/**
 * Get credits per hour based on table type and size.
 * @param {string | null | undefined} size - Warehouse or instance size
 * @param {string | null | undefined} tableType - Table type
 * @returns {number}
 */
function getCreditsPerHourForTableType(size, tableType) {
  if (!size) return 0;
  const normalized = String(size).toUpperCase().trim();
  const category = getTableTypeCategory(tableType);

  if (category === "postgres") {
    return POSTGRES_CREDITS_PER_HOUR[normalized] || 0;
  }
  if (category === "interactive") {
    return INTERACTIVE_CREDITS_PER_HOUR[normalized] || 0;
  }
  return WAREHOUSE_CREDITS_PER_HOUR[normalized] || 0;
}

/**
 * Calculate estimated credits consumed for a test run.
 * @param {number} durationSeconds - Duration of the test in seconds
 * @param {string | null | undefined} warehouseSize - Warehouse size string
 * @param {string | null | undefined} [tableType] - Table type
 * @returns {number}
 */
function calculateCreditsUsed(durationSeconds, warehouseSize, tableType) {
  if (!durationSeconds || durationSeconds <= 0) return 0;
  const creditsPerHour = getCreditsPerHourForTableType(warehouseSize, tableType);
  if (creditsPerHour <= 0) return 0;
  const durationHours = durationSeconds / 3600;
  return durationHours * creditsPerHour;
}

/**
 * Calculate the estimated cost for a test run.
 * ALL Snowflake compute uses credits, but with different rates by table type.
 * @param {number} durationSeconds - Duration of the test in seconds
 * @param {string | null | undefined} warehouseSize - Warehouse/instance size string
 * @param {number} [dollarsPerCredit] - Cost per credit (defaults to user setting)
 * @param {string | null | undefined} [tableType] - Table type (e.g., "HYBRID", "SNOWFLAKE_POSTGRES")
 * @returns {{ creditsUsed: number, estimatedCostUsd: number, costPerHour: number, creditsPerHour: number }}
 */
function calculateEstimatedCost(durationSeconds, warehouseSize, dollarsPerCredit, tableType) {
  const settings = getCostSettings();
  const rate = dollarsPerCredit ?? settings.dollarsPerCredit;
  const creditsPerHour = getCreditsPerHourForTableType(warehouseSize, tableType);
  const creditsUsed = calculateCreditsUsed(durationSeconds, warehouseSize, tableType);

  return {
    creditsUsed,
    estimatedCostUsd: creditsUsed * rate,
    costPerHour: creditsPerHour * rate,
    creditsPerHour,
  };
}

/**
 * Format a cost amount as a currency string.
 * Uses 4 decimal places for values under $1, 2 decimals otherwise.
 * @param {number | null | undefined} amount - Cost amount
 * @param {number} [decimals] - Number of decimal places (auto-determined if not provided)
 * @returns {string}
 */
function formatCost(amount, decimals) {
  if (amount === null || amount === undefined || !Number.isFinite(amount)) {
    return "$0.00";
  }
  // Auto-determine decimals: use 4 for values under $1, 2 otherwise
  const d = decimals !== undefined ? decimals : (Math.abs(amount) < 1 ? 4 : 2);
  return `$${amount.toFixed(d)}`;
}

/**
 * Format cost for a specific table type.
 * All table types now use credits - format consistently.
 * @param {number | null | undefined} amount - Cost amount
 * @param {string | null | undefined} tableType - Table type (e.g., "HYBRID", "SNOWFLAKE_POSTGRES")
 * @param {string | null | undefined} calculationMethod - How cost was calculated
 * @returns {string}
 */
function formatCostForTableType(amount, tableType, calculationMethod) {
  // All table types use credits now, just format the amount
  if (amount !== null && amount !== undefined && Number.isFinite(amount) && amount > 0) {
    return formatCost(amount);
  }
  // No cost available
  if (calculationMethod === "unavailable") {
    return "—";
  }
  return formatCost(amount);
}

/**
 * Format credits as a readable string.
 * @param {number | null | undefined} credits - Number of credits
 * @param {number} [decimals=4] - Number of decimal places
 * @returns {string}
 */
function formatCredits(credits, decimals = 4) {
  if (credits === null || credits === undefined || !Number.isFinite(credits)) {
    return "0 credits";
  }
  const suffix = credits === 1 ? "credit" : "credits";
  return `${credits.toFixed(decimals)} ${suffix}`;
}

/**
 * Format cost with optional credits display.
 * @param {number | null | undefined} costUsd - Cost in USD
 * @param {number | null | undefined} credits - Credits used
 * @param {boolean} [showCredits] - Whether to show credits (defaults to user setting)
 * @returns {string}
 */
function formatCostWithCredits(costUsd, credits, showCredits) {
  const settings = getCostSettings();
  const show = showCredits ?? settings.showCredits;

  const costStr = formatCost(costUsd);
  if (!show || credits === null || credits === undefined) {
    return costStr;
  }
  return `${costStr} (${formatCredits(credits)})`;
}

/**
 * Calculate cost delta between two values.
 * @param {number | null | undefined} primary - Primary (baseline) cost
 * @param {number | null | undefined} secondary - Secondary (comparison) cost
 * @returns {{ delta: number, deltaPercent: number, isBetter: boolean }}
 */
function calculateCostDelta(primary, secondary) {
  const p = Number(primary) || 0;
  const s = Number(secondary) || 0;
  const delta = p - s;
  const deltaPercent = s !== 0 ? ((p - s) / s) * 100 : 0;

  return {
    delta,
    deltaPercent,
    isBetter: p < s, // Lower cost is better
  };
}

/**
 * Format a cost delta for display.
 * @param {number} delta - Delta amount
 * @param {number} deltaPercent - Delta percentage
 * @returns {string}
 */
function formatCostDelta(delta, deltaPercent) {
  if (!Number.isFinite(delta) || !Number.isFinite(deltaPercent)) {
    return "—";
  }
  const sign = delta >= 0 ? "+" : "";
  return `${sign}${formatCost(delta)} (${sign}${deltaPercent.toFixed(1)}%)`;
}

/**
 * Get CSS class for cost delta display.
 * @param {number} delta - Delta amount (negative = cheaper = better)
 * @returns {string}
 */
function getCostDeltaClass(delta) {
  if (!Number.isFinite(delta)) return "text-gray-500";
  if (delta < 0) return "text-green-600"; // Cheaper is better
  if (delta > 0) return "text-red-600"; // More expensive is worse
  return "text-gray-500"; // No change
}

/**
 * Calculate cost efficiency metrics.
 * @param {number} totalCost - Total estimated cost in dollars
 * @param {number} totalOperations - Total number of operations executed
 * @param {number} qps - Queries/operations per second
 * @param {number} durationSeconds - Duration of the test in seconds
 * @returns {{ costPerOperation: number, costPer1000Ops: number, costPer1000Qps: number }}
 */
function calculateCostEfficiency(totalCost, totalOperations, qps, durationSeconds) {
  const result = {
    costPerOperation: 0,
    costPer1000Ops: 0,
    costPer1000Qps: 0,
  };

  if (totalOperations > 0 && totalCost > 0) {
    result.costPerOperation = totalCost / totalOperations;
    result.costPer1000Ops = (totalCost / totalOperations) * 1000;
  }

  if (qps > 0 && durationSeconds > 0 && totalCost > 0) {
    result.costPer1000Qps = (totalCost / qps) * 1000;
  }

  return result;
}

/**
 * Format cost per operation for display.
 * @param {number | null | undefined} costPerOp - Cost per operation
 * @returns {string}
 */
function formatCostPerOp(costPerOp) {
  if (costPerOp === null || costPerOp === undefined || !Number.isFinite(costPerOp)) {
    return "—";
  }
  if (costPerOp < 0.0001) {
    return `$${costPerOp.toExponential(2)}`;
  }
  return `$${costPerOp.toFixed(6)}`;
}

/**
 * Format cost per 1000 operations for display.
 * @param {number | null | undefined} costPer1000 - Cost per 1000 operations
 * @returns {string}
 */
function formatCostPer1000(costPer1000) {
  if (costPer1000 === null || costPer1000 === undefined || !Number.isFinite(costPer1000)) {
    return "—";
  }
  return formatCost(costPer1000, 4);
}

/**
 * Format duration in a human-readable way.
 * @param {number} seconds - Duration in seconds
 * @returns {string}
 */
function formatDuration(seconds) {
  if (!seconds || seconds <= 0) return "0s";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const minutes = seconds / 60;
  if (minutes < 60) return `${minutes.toFixed(1)} min`;
  const hours = minutes / 60;
  return `${hours.toFixed(2)} hrs`;
}

/**
 * Get a friendly label for a table type category.
 * @param {"warehouse" | "interactive" | "postgres"} category
 * @returns {string}
 */
function getCategoryLabel(category) {
  switch (category) {
    case "postgres": return "Postgres Compute";
    case "interactive": return "Interactive Warehouse";
    case "warehouse": return "Standard Warehouse";
    default: return "Warehouse";
  }
}

/**
 * Get the pricing table reference for a category.
 * @param {"warehouse" | "interactive" | "postgres"} category
 * @returns {string}
 */
function getPricingTableRef(category) {
  switch (category) {
    case "postgres": return "Table 1(i)";
    case "interactive": return "Table 1(d)";
    case "warehouse": return "Table 1(a)";
    default: return "";
  }
}

/**
 * Generate a detailed cost breakdown tooltip.
 * Shows exactly how the cost was calculated.
 * 
 * @param {Object} params - Parameters for tooltip generation
 * @param {string | null | undefined} params.warehouseSize - Warehouse or instance size
 * @param {string | null | undefined} params.tableType - Table type (e.g., "HYBRID", "POSTGRES")
 * @param {number | null | undefined} params.durationSeconds - Test duration in seconds
 * @param {number | null | undefined} params.creditsUsed - Credits consumed
 * @param {number | null | undefined} params.creditsPerHour - Credits per hour rate
 * @param {number | null | undefined} params.estimatedCostUsd - Estimated cost in USD
 * @param {number | null | undefined} params.dollarsPerCredit - Price per credit
 * @param {number | null | undefined} params.nodeCount - Number of nodes (for multi-node clusters)
 * @returns {string}
 */
function generateCostTooltip(params) {
  const {
    warehouseSize,
    tableType,
    durationSeconds,
    creditsUsed,
    creditsPerHour,
    estimatedCostUsd,
    dollarsPerCredit,
    nodeCount
  } = params;

  const settings = getCostSettings();
  const rate = dollarsPerCredit ?? settings.dollarsPerCredit;
  const category = getTableTypeCategory(tableType);
  const categoryLabel = getCategoryLabel(category);
  const tableRef = getPricingTableRef(category);
  
  // Normalize size display
  const rawSize = warehouseSize ? String(warehouseSize).toUpperCase() : "Unknown";
  
  // For Postgres, check if we need to show the mapped instance name
  let displaySize = rawSize;
  let sizeNote = "";
  if (category === "postgres") {
    const instanceInfo = getPostgresInstanceInfo(rawSize);
    if (instanceInfo.isAlias) {
      displaySize = instanceInfo.instanceName;
      sizeNote = ` (configured as ${instanceInfo.originalName})`;
    }
  }
  
  // Get actual credits/hour rate if not provided
  const actualCreditsPerHour = creditsPerHour ?? getCreditsPerHourForTableType(rawSize, tableType);
  
  // Calculate duration in a readable format
  const duration = formatDuration(durationSeconds || 0);
  const hours = (durationSeconds || 0) / 3600;
  
  // Calculate actual credits if not provided
  const actualCredits = creditsUsed ?? (hours * actualCreditsPerHour);
  
  // Calculate cost if not provided
  const cost = estimatedCostUsd ?? (actualCredits * rate);

  // Build the tooltip lines
  const lines = [];
  
  // Line 1: Type and size
  // For Postgres, the backend now provides the actual instance size (e.g., STANDARD_M)
  // So we just display it directly - no alias mapping needed anymore
  if (category === "postgres") {
    lines.push(`Postgres Instance: ${displaySize}`);
  } else {
    lines.push(`${categoryLabel}: ${displaySize}`);
  }
  
  // Line 2: Rate info with table reference
  if (actualCreditsPerHour > 0) {
    lines.push(`Rate: ${actualCreditsPerHour.toFixed(4)} credits/hr (${tableRef})`);
  }
  
  // Line 3: Duration
  lines.push(`Duration: ${duration}`);
  
  // Line 4: Node count if multi-node
  if (nodeCount && nodeCount > 1) {
    lines.push(`Nodes: ${nodeCount}`);
  }
  
  // Line 5: Calculation breakdown
  if (actualCreditsPerHour > 0 && hours > 0) {
    const effectiveNodes = nodeCount && nodeCount > 1 ? nodeCount : 1;
    if (effectiveNodes > 1) {
      lines.push(`Calculation: ${actualCreditsPerHour.toFixed(4)} × ${hours.toFixed(4)} hrs × ${effectiveNodes} nodes`);
    } else {
      lines.push(`Calculation: ${actualCreditsPerHour.toFixed(4)} × ${hours.toFixed(4)} hrs`);
    }
  }
  
  // Line 6: Credits used
  if (actualCredits > 0) {
    lines.push(`Credits: ${actualCredits.toFixed(4)}`);
  }
  
  // Line 7: Cost
  lines.push(`Cost: ${formatCost(cost)} @ $${rate.toFixed(2)}/credit`);
  
  return lines.join("\n");
}

/**
 * Generate a simple one-line cost summary.
 * @param {Object} params - Same params as generateCostTooltip
 * @returns {string}
 */
function generateCostSummary(params) {
  const {
    warehouseSize,
    tableType,
    durationSeconds,
    creditsPerHour,
    dollarsPerCredit
  } = params;

  const settings = getCostSettings();
  const rate = dollarsPerCredit ?? settings.dollarsPerCredit;
  const size = warehouseSize ? String(warehouseSize).toUpperCase() : "?";
  const actualCreditsPerHour = creditsPerHour ?? getCreditsPerHourForTableType(size, tableType);
  const duration = formatDuration(durationSeconds || 0);
  
  return `${size} @ ${actualCreditsPerHour.toFixed(4)} cr/hr × ${duration} @ $${rate.toFixed(2)}/cr`;
}

// Export for use in other scripts (if using modules) or make globally available
if (typeof window !== "undefined") {
  window.CostUtils = {
    getCostSettings,
    saveCostSettings,
    getCreditsPerHour,
    getCreditsPerHourForTableType,
    getTableTypeCategory,
    calculateCreditsUsed,
    calculateEstimatedCost,
    formatCost,
    formatCostForTableType,
    formatCredits,
    formatCostWithCredits,
    formatDuration,
    calculateCostDelta,
    formatCostDelta,
    getCostDeltaClass,
    calculateCostEfficiency,
    formatCostPerOp,
    formatCostPer1000,
    generateCostTooltip,
    generateCostSummary,
    getCategoryLabel,
    getPricingTableRef,
    getPostgresInstanceInfo,
    isValidPostgresInstanceName,
    // Pricing tables
    WAREHOUSE_CREDITS_PER_HOUR,
    INTERACTIVE_CREDITS_PER_HOUR,
    POSTGRES_CREDITS_PER_HOUR,
    WAREHOUSE_TO_POSTGRES_INSTANCE,
    // Table type sets
    WAREHOUSE_TABLE_TYPES,
    INTERACTIVE_TABLE_TYPES,
    POSTGRES_TABLE_TYPES,
    DEFAULT_DOLLARS_PER_CREDIT,
  };
}
