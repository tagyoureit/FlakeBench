# Frontend Implementation Status (Current)

Last updated: 2026-01-18

This document describes the implemented UI and the actual frontend behavior.
It replaces earlier completion claims that are no longer accurate.

## Stack and Structure

- Server-rendered pages (Jinja2) under `backend/templates/`.
- Alpine.js for state management and UI behavior.
- Chart.js for charts.
- HTMX for partial updates and navigation.
- Static assets under `backend/static/`.

## Implemented Pages

### Templates (Root)

- Route: `/templates` (root `/` also renders this page).
- Template list with table and card views, search, and actions.
- Actions include prepare test, edit/view, duplicate, and delete.
- JS: `backend/static/js/templates_manager.js`.
- Templates are stored in Snowflake (`UNISTORE_BENCHMARK.TEST_RESULTS.TEST_TEMPLATES`).

### Configure

- Route: `/configure`.
- Create or edit templates that persist to Snowflake.
- Supports Snowflake and Postgres-family templates.

### Dashboard (Live)

- Routes: `/dashboard`, `/dashboard/{test_id}`.
- Live metrics view using WebSocket stream `/ws/test/{test_id}`.
- Start/stop actions call `/api/tests/{test_id}/start` and `/api/tests/{test_id}/stop`.
- JS: `backend/static/js/dashboard.js`.

### Dashboard History (Read-only)

- Route: `/dashboard/history/{test_id}`.
- Read-only analysis for completed tests.
- Query execution drilldown: `/dashboard/history/{test_id}/data`.
- JS: `backend/static/js/dashboard.js` (history mode).

### History (Search, Filter, Compare)

- Route: `/history`.
- Filters by table type, warehouse size, status, date range.
- Search and compare up to 2 tests.
- Deep compare view: `/history/compare?ids=<id1>,<id2>`.
- JS: `backend/static/js/history.js`.

### Comparison

- Route: `/comparison` redirects to `/history`.

## Implemented UI Assets

- Base layout: `backend/templates/base.html`.
- Shared components: `backend/templates/components/`.
- Styling: `backend/static/css/app.css`.

## Notes

- The UI assumes all runs are template-based.
- There is no separate React or build pipeline; all frontend logic is static JS.
