# UI Architecture (Current)

Last updated: 2026-01-18

## Rendering Model

- Server-rendered HTML via Jinja2.
- Alpine.js provides client-side state.
- Chart.js renders charts.
- HTMX handles partial navigation.

## Pages

- `/templates` (root): templates list and actions.
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
