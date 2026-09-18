/**
 * Regression check for warehouse generation labelling in the frontend.
 *
 * Guards ISSUE-012/013/014/015: neither interactive nor adaptive warehouses
 * have a generation, and a standard warehouse with no explicit generation must
 * not be labelled Gen1 (the account default is Gen2 per BCR-2250).
 *
 * The two `formatWarehouseOption` implementations are duplicated between
 * display.js and configure.html, so both are extracted and asserted against the
 * same fixtures to catch divergence.
 *
 * Run: node tests/js/verify_warehouse_labels.mjs
 */
import { readFileSync } from "fs";
import { fileURLToPath } from "url";
import { dirname, resolve } from "path";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const displaySrc = readFileSync(resolve(root, "backend/static/js/dashboard/display.js"), "utf8");
const configureSrc = readFileSync(resolve(root, "backend/templates/pages/configure.html"), "utf8");

/** Extract a `name(wh) { ... }` method body by brace matching. */
function extractMethod(src, name) {
  const start = src.indexOf(name + "(wh) {");
  if (start < 0) throw new Error(`method not found: ${name}`);
  let depth = 0;
  for (let i = src.indexOf("{", start); i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}" && --depth === 0) return src.slice(start, i + 1);
  }
  throw new Error(`unbalanced braces in ${name}`);
}

const build = (src) =>
  new Function(
    "return ({" +
      extractMethod(src, "warehouseGenerationLabel") +
      "," +
      extractMethod(src, "formatWarehouseOption") +
      "})"
  )();

const impls = { "display.js": build(displaySrc), "configure.html": build(configureSrc) };

// Fixtures mirror real SHOW WAREHOUSES rows from a live account.
const fixtures = [
  { name: "PERFTESTING_M_INTERACTIVE_1", type: "INTERACTIVE", is_interactive: true, is_adaptive: false, size: "Medium", min_cluster_count: 1, max_cluster_count: 1, generation: null, resource_constraint: null, enable_query_acceleration: null },
  { name: "BITGO_IWH", type: "INTERACTIVE", is_interactive: true, is_adaptive: false, size: "X-Small", min_cluster_count: 1, max_cluster_count: 1, generation: null, resource_constraint: null, enable_query_acceleration: null },
  { name: "WAREHOUSE_L_G2", type: "STANDARD", is_interactive: false, is_adaptive: false, size: "Large", min_cluster_count: 1, max_cluster_count: 1, generation: "2", resource_constraint: "STANDARD_GEN_2", enable_query_acceleration: false },
  { name: "AI_EDUCATION_WH", type: "STANDARD", is_interactive: false, is_adaptive: false, size: "X-Large", min_cluster_count: 1, max_cluster_count: 20, generation: "1", resource_constraint: "STANDARD_GEN_1", enable_query_acceleration: false },
  { name: "CORTEX_ANALYST_WH", type: "STANDARD", is_interactive: false, is_adaptive: false, size: "Large", min_cluster_count: 1, max_cluster_count: 1, generation: null, resource_constraint: null, enable_query_acceleration: false },
  { name: "BTQ_OPS_WH", type: "STANDARD", is_interactive: false, is_adaptive: false, size: "X-Small", min_cluster_count: 1, max_cluster_count: 1, generation: "2", resource_constraint: "STANDARD_GEN_2", enable_query_acceleration: true },
  { name: "ADAPTIVE_WH", type: "ADAPTIVE", is_interactive: false, is_adaptive: true, size: null, generation: null, resource_constraint: null, max_query_performance_level: "X-Large", query_throughput_multiplier: 2 },
];

const failures = [];
const fail = (msg) => failures.push(msg);

for (const [implName, impl] of Object.entries(impls)) {
  for (const wh of fixtures) {
    const label = impl.warehouseGenerationLabel(wh);
    const option = impl.formatWarehouseOption(wh);

    if (wh.is_interactive && label !== "") {
      fail(`${implName}: interactive ${wh.name} emitted generation ${JSON.stringify(label)}`);
    }
    if (wh.is_adaptive && label !== "") {
      fail(`${implName}: adaptive ${wh.name} emitted generation ${JSON.stringify(label)}`);
    }
    if ((wh.is_interactive || wh.is_adaptive) && /Gen/.test(option)) {
      fail(`${implName}: ${wh.type} ${wh.name} option contains "Gen": ${option}`);
    }
    if (!wh.is_interactive && !wh.is_adaptive && wh.generation === null && /Gen/.test(label)) {
      fail(`${implName}: unset standard ${wh.name} fabricated ${JSON.stringify(label)}`);
    }
    if (wh.generation === "2" && !/Gen ?2/.test(label)) {
      fail(`${implName}: ${wh.name} should be Gen2, got ${JSON.stringify(label)}`);
    }
    if (wh.generation === "1" && !/Gen ?1/.test(label)) {
      fail(`${implName}: ${wh.name} should be Gen1, got ${JSON.stringify(label)}`);
    }
    if (wh.is_adaptive && !/Adaptive/.test(option)) {
      fail(`${implName}: adaptive ${wh.name} not labelled Adaptive: ${option}`);
    }
    if (wh.is_interactive && !/Interactive/.test(option)) {
      fail(`${implName}: interactive ${wh.name} not labelled Interactive: ${option}`);
    }
  }
}

for (const wh of fixtures) {
  console.log(
    wh.name.padEnd(30),
    JSON.stringify(impls["display.js"].warehouseGenerationLabel(wh)).padEnd(9),
    impls["display.js"].formatWarehouseOption(wh)
  );
}

if (failures.length) {
  console.error("\nFAILURES:");
  for (const f of failures) console.error("  - " + f);
  process.exit(1);
}
console.log(`\nAll checks passed (${fixtures.length} fixtures x ${Object.keys(impls).length} implementations)`);
