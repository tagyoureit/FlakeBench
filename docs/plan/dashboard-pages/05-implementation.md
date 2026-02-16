# Dashboard Pages - Implementation Plan

**Parent:** [00-overview.md](00-overview.md)

---

## 1. Implementation Phases

| Phase | Focus | Deliverables | Estimated Effort |
|-------|-------|--------------|------------------|
| **Phase 1** | SQL Infrastructure | Dynamic tables, views, migration script | Small |
| **Phase 2** | Backend API | FastAPI endpoints, Pydantic models | Medium |
| **Phase 3** | Table Type Page | UI template, charts, recommendations | Medium |
| **Phase 4** | Template Analysis Page | Scatter plots, histograms, statistics | Medium |
| **Phase 5** | Polish & Testing | Integration tests, performance tuning | Small |

---

## 2. Phase 1: SQL Infrastructure

### 2.1 Tasks

| # | Task | Files | Dependencies |
|---|------|-------|--------------|
| 1.1 | Create `DT_TABLE_TYPE_SUMMARY` dynamic table | `sql/schema/dashboard_tables.sql` | None |
| 1.2 | Create `DT_TEMPLATE_STATISTICS` dynamic table | `sql/schema/dashboard_tables.sql` | None |
| 1.3 | Create `DT_DAILY_COST_ROLLUP` dynamic table | `sql/schema/dashboard_tables.sql` | None |
| 1.4 | Create `V_TEMPLATE_RUNS` view | `sql/schema/dashboard_tables.sql` | None |
| 1.5 | Create migration script | `sql/migrations/add_dashboard_tables.sql` | 1.1-1.4 |
| 1.6 | Verify dynamic table refresh | Manual testing | 1.5 |

### 2.2 Acceptance Criteria

- [ ] All 3 dynamic tables created with correct schema
- [ ] Dynamic tables refresh automatically on TEST_RESULTS insert
- [ ] V_TEMPLATE_RUNS view returns expected columns
- [ ] Migration script is idempotent (can run multiple times)
- [ ] Queries against dynamic tables return data in < 500ms

### 2.3 Validation Queries

```sql
-- Verify DT_TABLE_TYPE_SUMMARY
SELECT table_type, test_count, avg_qps 
FROM DT_TABLE_TYPE_SUMMARY
ORDER BY test_count DESC;
-- Expected: 5 rows, one per table type

-- Verify DT_TEMPLATE_STATISTICS  
SELECT COUNT(*) as template_count FROM DT_TEMPLATE_STATISTICS;
-- Expected: > 0 templates

-- Verify refresh works
INSERT INTO TEST_RESULTS (...);  -- Insert test data
-- Wait 1 minute
SELECT refreshed_at FROM DT_TABLE_TYPE_SUMMARY;
-- Should show recent timestamp
```

---

## 3. Phase 2: Backend API

### 3.1 Tasks

| # | Task | Files | Dependencies |
|---|------|-------|--------------|
| 2.1 | Create Pydantic models | `backend/api/routes/dashboard_modules/models.py` | None |
| 2.2 | Create aggregation queries | `backend/api/routes/dashboard_modules/aggregations.py` | 2.1 |
| 2.3 | Create recommendation engine | `backend/api/routes/dashboard_modules/recommendations.py` | 2.1 |
| 2.4 | Create badge logic | `backend/api/routes/dashboard_modules/badges.py` | 2.1 |
| 2.5 | Create chart data builders | `backend/api/routes/dashboard_modules/chart_builders.py` | 2.1 |
| 2.6 | Implement table type endpoints | `backend/api/routes/dashboard.py` | 2.1-2.5 |
| 2.7 | Implement template endpoints | `backend/api/routes/dashboard.py` | 2.1-2.5 |
| 2.8 | Register routes in main.py | `backend/main.py` | 2.6-2.7 |

### 3.2 Module Breakdown

**`models.py`** (~200 lines)
- All Pydantic response models from 03-api-endpoints.md
- Type hints for all fields

**`aggregations.py`** (~150 lines)
- `fetch_table_type_summary(db) -> list[dict]`
- `fetch_template_statistics(db, template_id) -> dict`
- `fetch_template_runs(db, template_id, limit, offset) -> list[dict]`
- `fetch_daily_costs(db, start_date, end_date) -> list[dict]`

**`recommendations.py`** (~200 lines)
- `WORKLOAD_WEIGHTS` config dict
- `score_table_types(summary, workload_type) -> list[ScoredType]`
- `generate_rationale(scored, workload_type) -> str`
- `get_runner_up(scores) -> ScoredType`

**`badges.py`** (~100 lines)
- `determine_winner(metric, values) -> str`
- `is_statistically_significant(a, b) -> tuple[bool, float]`
- `get_stability_badge(cv) -> str`
- `determine_badges(row, all_rows) -> list[str]`

**`chart_builders.py`** (~150 lines)
- `build_histogram_data(values, num_bins) -> HistogramData`
- `build_scatter_data(x_values, y_values) -> ScatterData`
- `build_box_plot_data(values) -> BoxPlotData`
- `classify_distribution(values, skewness) -> str`

### 3.3 Acceptance Criteria

- [ ] All endpoints return valid JSON matching Pydantic models
- [ ] `GET /api/dashboard/table-types/summary` returns data for all 5 table types
- [ ] `GET /api/dashboard/templates/{id}/statistics` returns complete stats
- [ ] Cost fields are populated using `CostCalculator`
- [ ] Badges are correctly determined based on thresholds
- [ ] Endpoints return 404 for non-existent templates
- [ ] Response times < 500ms for all endpoints

---

## 4. Phase 3: Table Type Comparison Page

### 4.1 Tasks

| # | Task | Files | Dependencies |
|---|------|-------|--------------|
| 3.1 | Create page route | `backend/api/routes/pages.py` | Phase 2 |
| 3.2 | Create HTML template | `backend/templates/pages/dashboard_table_types.html` | None |
| 3.3 | Create Alpine.js component | `backend/static/js/dashboard_table_types.js` | 3.2 |
| 3.4 | Implement KPI cards | `dashboard_table_types.html` | 3.2 |
| 3.5 | Implement recommendation panel | `dashboard_table_types.html` | 3.2 |
| 3.6 | Implement comparison table | `dashboard_table_types.html` | 3.2 |
| 3.7 | Implement performance chart | `dashboard_table_types.js` | 3.3 |
| 3.8 | Implement cost chart | `dashboard_table_types.js` | 3.3 |
| 3.9 | Add navigation link | `backend/templates/base.html` | 3.2 |

### 4.2 Acceptance Criteria

- [ ] Page loads at `/dashboard/table-types`
- [ ] KPI cards display for all 5 table types
- [ ] Winner badges appear on correct table types
- [ ] Recommendation panel shows 3 workload recommendations
- [ ] Comparison table highlights winners per metric
- [ ] Performance chart renders with grouped bars
- [ ] Cost chart renders with efficiency metrics
- [ ] Page loads in < 2 seconds
- [ ] Responsive layout works on tablet/desktop

---

## 5. Phase 4: Template Analysis Page

### 5.1 Tasks

| # | Task | Files | Dependencies |
|---|------|-------|--------------|
| 4.1 | Create page route | `backend/api/routes/pages.py` | Phase 2 |
| 4.2 | Create HTML template | `backend/templates/pages/dashboard_template_analysis.html` | None |
| 4.3 | Create Alpine.js component | `backend/static/js/dashboard_template_analysis.js` | 4.2 |
| 4.4 | Implement summary cards | `dashboard_template_analysis.html` | 4.2 |
| 4.5 | Implement scatter plot | `dashboard_template_analysis.js` | 4.3 |
| 4.6 | Implement histogram | `dashboard_template_analysis.js` | 4.3 |
| 4.7 | Implement box plot | `dashboard_template_analysis.js` | 4.3 |
| 4.8 | Implement statistical health section | `dashboard_template_analysis.html` | 4.2 |
| 4.9 | Implement runs table with pagination | `dashboard_template_analysis.html` | 4.2 |
| 4.10 | Add template list page | `backend/templates/pages/dashboard_templates.html` | 4.1 |

### 5.2 Acceptance Criteria

- [ ] Page loads at `/dashboard/templates/{id}`
- [ ] Summary cards show correct aggregate metrics
- [ ] Scatter plot renders with correct axes
- [ ] Scatter plot includes correlation coefficient
- [ ] Histogram shows distribution with bin labels
- [ ] Box plot shows percentiles correctly
- [ ] Statistical health section shows CV, KL divergence, trend
- [ ] Outliers are highlighted with reasons
- [ ] Runs table is paginated and sortable
- [ ] Page loads in < 2 seconds

---

## 6. Phase 5: Polish & Testing

### 6.1 Tasks

| # | Task | Files | Dependencies |
|---|------|-------|--------------|
| 5.1 | Write API integration tests | `tests/api/test_dashboard.py` | Phase 2 |
| 5.2 | Write UI smoke tests | `tests/ui/test_dashboard_pages.py` | Phase 3-4 |
| 5.3 | Performance profiling | N/A | All |
| 5.4 | Add loading states | All UI files | Phase 3-4 |
| 5.5 | Add error handling | All UI files | Phase 3-4 |
| 5.6 | Documentation | `docs/user-guide/dashboard.md` | All |

### 6.2 Acceptance Criteria

- [ ] All API endpoints have test coverage
- [ ] UI pages render without JavaScript errors
- [ ] Loading states shown during data fetch
- [ ] Error messages shown on API failures
- [ ] All queries execute in < 500ms
- [ ] Dynamic tables refresh within 1 minute of TEST_RESULTS insert

---

## 7. File Checklist

### New Files to Create

```
sql/
└── schema/
    └── dashboard_tables.sql           # Dynamic tables + views

backend/
├── api/
│   └── routes/
│       ├── dashboard.py               # Route definitions
│       └── dashboard_modules/
│           ├── __init__.py
│           ├── models.py              # Pydantic models
│           ├── aggregations.py        # Query builders
│           ├── recommendations.py     # Scoring engine
│           ├── badges.py              # Badge logic
│           └── chart_builders.py      # Chart data formatters
├── templates/
│   └── pages/
│       ├── dashboard_table_types.html
│       ├── dashboard_templates.html   # List view
│       └── dashboard_template_analysis.html
└── static/
    └── js/
        ├── dashboard_table_types.js
        └── dashboard_template_analysis.js

tests/
├── api/
│   └── test_dashboard.py
└── ui/
    └── test_dashboard_pages.py

docs/
└── plan/
    └── dashboard-pages/               # This plan
        ├── 00-overview.md
        ├── 01-architecture.md
        ├── 02-sql-schema.md
        ├── 03-api-endpoints.md
        ├── 04-ui-templates.md
        └── 05-implementation.md
```

### Files to Modify

```
backend/
├── main.py                            # Register dashboard routes
└── templates/
    └── base.html                      # Add navigation link

sql/
└── migrations/
    └── add_dashboard_tables.sql       # Migration script
```

---

## 8. Dependencies & Prerequisites

### Python Packages (Already Available)
- FastAPI (routing)
- Pydantic (models)
- snowflake-connector-python (DB access)
- numpy (statistics) - may need to add if not present

### JavaScript Libraries (Already in base.html)
- Alpine.js (reactivity)
- HTMX (partial updates)
- Chart.js (visualizations)
- Tailwind CSS (styling)

### Database Requirements
- Snowflake warehouse with permission to create dynamic tables
- Existing TEST_RESULTS table with data

---

## 9. Risk Mitigation

| Risk | Mitigation | Fallback |
|------|------------|----------|
| Dynamic table refresh latency | Set target_lag to 1 minute | Use views with query caching |
| Chart.js performance with many points | Limit to last 100 runs | Add date range filter |
| Complex statistical calculations | Use existing Python modules | Simplify to basic stats |
| API response size | Paginate all list endpoints | Add compression |

---

## 10. Definition of Done

### Feature Complete When:
1. ✅ All SQL objects created and verified
2. ✅ All API endpoints implemented and tested
3. ✅ Table Type Comparison page functional
4. ✅ Template Analysis page functional
5. ✅ Cost metrics prominently displayed
6. ✅ Statistical badges working
7. ✅ Navigation integrated into main app
8. ✅ Documentation updated

### Quality Gates:
- [ ] All tests passing
- [ ] No console errors in UI
- [ ] Page load < 2 seconds
- [ ] API responses < 500ms
- [ ] Code reviewed and merged
