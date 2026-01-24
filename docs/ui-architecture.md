# UI Architecture (Current)

Last updated: 2026-01-21

## Rendering Model

- Server-rendered HTML via Jinja2.
- Alpine.js provides client-side state.
- Chart.js renders charts.
- HTMX handles partial navigation.

## Pages

- `/templates` (root) and `/`: templates list and actions.
- `/configure`: create/edit templates.
- `/dashboard`, `/dashboard/{test_id}`: live metrics and control.
- `/dashboard/history/{test_id}`: read-only analysis.
- `/dashboard/history/{test_id}/data`: query execution drilldown.
- `/history`: filter/search and compare (up to 2).
- `/history/compare`: deep compare.
- `/comparison`: redirects to `/history`.

History list status notes:

- When `enrichment_status=PENDING` and the run is otherwise completed, the
  history list reports status as `PROCESSING` to indicate post-processing.

## Frontend Modules

- `backend/static/js/dashboard.js` - live + history dashboards.
- `backend/static/js/history.js` - history list and compare.
- `backend/static/js/templates_manager.js` - templates list actions.
- `backend/static/css/app.css` - styling.

## Autoscale UI Flow

- When autoscale is enabled on a template, the templates list "Run Benchmark"
  prepares an autoscale parent run and redirects to the live dashboard.
- The live dashboard Start button calls `/api/tests/{id}/start-autoscale` for
  autoscale runs (standard runs use `/api/tests/{id}/start`).

## Chart.js Lifecycle Management

Charts in the dashboard use Chart.js and require careful lifecycle handling to
avoid race conditions:

- Charts are stored on canvas elements via `canvas.__chart` or accessed via
  `Chart.getChart(canvas)`.
- The `initCharts()` function in `dashboard.js` is idempotent - it preserves
  existing charts instead of destroying and recreating them.
- The warehouse/MCW chart is initialized separately by `loadWarehouseTimeseries()`
  and must not be destroyed by subsequent `initCharts()` calls from
  `loadHistoricalMetrics()`.

Pattern for safe chart creation:

```javascript
const existingChart = canvas.__chart ||
  (window.Chart && Chart.getChart ? Chart.getChart(canvas) : null);
if (existingChart) {
  // Chart already exists, skip recreation
  return;
} else {
  canvas.__chart = new Chart(ctx, config);
}
```

## Alpine.js Data Access

Alpine.js component data can be accessed programmatically via the data stack:

```javascript
const alpineData = element._x_dataStack[0];
```

This is used for debugging and testing dashboard state (e.g., `isMultiNode`,
`templateInfo`, `historicalMetrics`).
