# Enhanced Comparison Feature

**Goal**: Extend comparison capabilities beyond the current overlay-chart view to
support deeper analysis, multiple runs, and properly aligned time-series data.

## Chart Time Alignment Strategy

When comparing runs of different lengths, charts must handle alignment carefully:

- **X-Axis**: Use elapsed seconds (0-based), not wall-clock timestamps.
- **Alignment**: All runs start at X=0 regardless of actual start time.
- **Different Lengths**: Handle gracefully:
  - Shorter runs end where their data ends (no extrapolation).
  - Longer runs continue with only their series visible.
  - Chart X-axis range = `max(duration_seconds)` across all compared runs.
- **Visual Indicators**:
  - Add vertical marker at each run's end time with subtle annotation.
  - Fade/dim series after their run completes to avoid confusion.
  - Legend shows run duration next to each series label.
- **Zoom/Pan**: Allow users to zoom into specific time ranges; maintain alignment.
- **Phase Boundaries**: Optionally show warmup/measurement phase transitions as
  vertical bands.

## Latency Chart Considerations

- **Y-Axis Scale**: Use consistent scale across all series (auto-range to max).
- **Outlier Handling**: Consider log-scale toggle for latency charts when P99
  varies significantly across runs.
- **Missing Data**: If a run has gaps, show discontinuity rather than interpolating.

## Managing Chart Complexity

Multi-run comparison with multi-series charts (e.g., 5 runs × P50/P95/P99 = 15
series) can become unreadable. Use these strategies:

| View | Strategy | Rationale |
|------|----------|-----------|
| Quick Compare | Single-metric (P95 default) | Fast visual compare |
| Detail Compare | Small multiples (stacked) | Full analysis |
| Interactive | Toggle series (legend) | User control |

**Interactive Controls** (for both views):
- View toggle: Overlay vs Small Multiples
- Metric selector: P50 / P95 / P99 (default P95)
- Checkboxes to show/hide additional percentiles
- Run checkboxes to include/exclude specific runs

See `ui-architecture.md` for detailed strategy descriptions and mockups.

## Implementation Tasks

### Phase 1: Multi-Run Support & Core Tables

- [ ] **Multi-run selection (2-5 runs)**: Update `/history` UI to allow selecting
  up to 5 tests for comparison.
- [ ] **New route**: Add `/history/compare/detail?ids=<id1>,<id2>[,<id3>...]` for
  in-depth comparison view.
- [ ] **Configuration diff table**: Side-by-side table highlighting config
  differences (table type, warehouse, concurrency, workload mix).
- [ ] **Metrics comparison table**: Tabular view of final metrics with "Best"
  indicators (QPS, P50/P95/P99, error rate, total ops).
- [ ] **Time alignment**: Implement elapsed-seconds X-axis with proper handling
  of different run lengths.
- [ ] **End-time markers**: Add vertical markers and series fade for completed runs.
- [ ] **Chart complexity - Quick Compare**: Implement single-metric focus (P95
  default) with dropdown to switch percentiles.
- [ ] **Chart complexity - Detail Compare**: Implement small multiples layout.
- [ ] **Chart controls**: Add view toggle, metric selector, and run checkboxes.

### Phase 2: Per-Query-Type & Error Analysis

- [ ] **Per-query-type breakdown**: Compare latencies by operation type.
- [ ] **Error analysis comparison**: Compare error patterns/counts across runs.
- [ ] **API enhancement**: Add `by_query_type` breakdown to metrics response.
- [ ] **New endpoint**: Add `GET /api/tests/{test_id}/errors` for error categorization.

### Phase 3: Find Max & Worker Comparison

- [ ] **Find Max comparison**: Compare step-load progression for FIND_MAX runs.
- [ ] **Per-cluster breakdown comparison**: Compare MCW cluster distribution.
- [ ] **Worker distribution comparison**: For multi-worker runs, compare per-worker
  metrics side-by-side.
- [ ] **API enhancement**: Add `workers` array with per-worker final metrics.

### Phase 4: Resource & Warehouse Comparison

- [ ] **Warehouse metrics comparison**: Compare clusters used, queue times, cache hit rates.
- [ ] **MCW time-series overlay**: Overlay active clusters and queue depth charts.
- [ ] **App overhead comparison**: Compare client-side overhead.
- [ ] **Client resources comparison**: Compare CPU/memory usage.
- [ ] **New endpoint**: Add `GET /api/compare?ids=...` returning diff-optimized payload.

## Acceptance Criteria

- Comparison view handles 2-5 runs with consistent color palette.
- Time-series charts align at X=0 and handle different run lengths gracefully.
- Configuration and metrics tables highlight differences clearly.
- Per-query-type and error breakdowns are available for detailed analysis.
