# Dashboard Pages - Architecture

**Parent:** [00-overview.md](00-overview.md)

---

## 1. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (HTMX)                          │
├─────────────────────────────────────────────────────────────────┤
│  Page: Table Type Comparison    │  Page: Template Analysis      │
│  /dashboard/table-types         │  /dashboard/templates/{id}    │
│  ┌───────────────────────────┐  │  ┌───────────────────────────┐│
│  │ KPI Cards (5 table types) │  │  │ Summary Cards             ││
│  │ Recommendation Panel      │  │  │ Scatter Plots (Chart.js)  ││
│  │ Comparison Table          │  │  │ Histograms                ││
│  │ Performance Charts        │  │  │ Box Plots                 ││
│  │ Cost Efficiency Section   │  │  │ Statistical Health        ││
│  │ Recent Tests Table        │  │  │ All Runs Table            ││
│  └───────────────────────────┘  │  └───────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     FastAPI Backend                             │
├─────────────────────────────────────────────────────────────────┤
│  Routes: backend/api/routes/dashboard.py (NEW)                  │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ GET /api/dashboard/table-types/summary                    │  │
│  │ GET /api/dashboard/table-types/comparison                 │  │
│  │ GET /api/dashboard/table-types/recommendations            │  │
│  │ GET /api/dashboard/templates                              │  │
│  │ GET /api/dashboard/templates/{id}/statistics              │  │
│  │ GET /api/dashboard/templates/{id}/distribution            │  │
│  │ GET /api/dashboard/templates/{id}/trend                   │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Modules (Reused):                                              │
│  ┌─────────────────────┐  ┌─────────────────────────────────┐  │
│  │ statistics.py       │  │ comparison_scoring.py           │  │
│  │ - percentile()      │  │ - classify_change()             │  │
│  │ - kl_divergence()   │  │ - REGRESSION_THRESHOLDS         │  │
│  │ - trend_analysis()  │  │ - get_confidence_level()        │  │
│  └─────────────────────┘  └─────────────────────────────────┘  │
│  ┌─────────────────────┐  ┌─────────────────────────────────┐  │
│  │ cost_calculator.py  │  │ NEW: dashboard_modules/         │  │
│  │ - credits_used      │  │ - aggregations.py               │  │
│  │ - cost_per_op       │  │ - recommendations.py            │  │
│  │ - efficiency        │  │ - badges.py                     │  │
│  └─────────────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Snowflake Data Layer                        │
├─────────────────────────────────────────────────────────────────┤
│  Dynamic Tables (NEW):                                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ DT_TABLE_TYPE_SUMMARY         - Per table type aggregates │  │
│  │ DT_TEMPLATE_STATISTICS        - Per template rollups      │  │
│  │ DT_DAILY_COST_ROLLUP          - Daily cost tracking       │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Existing Tables:                                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ TEST_RESULTS                  - Source of truth           │  │
│  │ QUERY_EXECUTIONS              - Per-query details         │  │
│  │ TEST_TEMPLATES                - Template definitions      │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Existing Procedures:                                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ CALCULATE_ROLLING_STATISTICS  - Reused for baselines      │  │
│  │ CALCULATE_TREND_ANALYSIS      - Reused for trends         │  │
│  │ COST_CALCULATOR_V2            - Reused for cost metrics   │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow

### 2.1 Table Type Comparison Page

```
User loads /dashboard/table-types
         │
         ▼
┌─────────────────────────────────────┐
│  1. HTMX requests summary endpoint  │
│     GET /api/dashboard/table-types/ │
│         summary                     │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  2. FastAPI queries dynamic table   │
│     SELECT * FROM                   │
│     DT_TABLE_TYPE_SUMMARY           │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  3. Enrich with cost calculations   │
│     CostCalculator.calculate_       │
│     cost_efficiency()               │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  4. Generate recommendations        │
│     recommendations.py              │
│     score_table_types()             │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  5. Apply badges                    │
│     badges.py                       │
│     determine_winners()             │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  6. Return JSON response            │
│     {                               │
│       kpi_cards: [...],             │
│       comparison_table: [...],      │
│       recommendations: [...],       │
│       badges: {...}                 │
│     }                               │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  7. HTMX updates DOM                │
│     Alpine.js renders components    │
│     Chart.js draws visualizations   │
└─────────────────────────────────────┘
```

### 2.2 Template Analysis Page

```
User loads /dashboard/templates/{template_id}
         │
         ▼
┌─────────────────────────────────────┐
│  1. Parallel HTMX requests:         │
│     - GET .../statistics            │
│     - GET .../distribution          │
│     - GET .../trend                 │
│     - GET .../runs                  │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  2. FastAPI queries:                │
│     - DT_TEMPLATE_STATISTICS        │
│     - QUERY_EXECUTIONS (histogram)  │
│     - TEST_RESULTS (scatter data)   │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  3. Statistical analysis:           │
│     - calculate_kl_divergence()     │
│     - calculate_simple_trend()      │
│     - coefficient_of_variation()    │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  4. Build chart datasets:           │
│     - Scatter: [{x, y}, ...]        │
│     - Histogram: {bins, counts}     │
│     - Box: {min, q1, med, q3, max}  │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  5. Return structured responses     │
│     Chart.js consumes data          │
│     Alpine.js renders cards         │
└─────────────────────────────────────┘
```

---

## 3. Component Design

### 3.1 New Backend Modules

```
backend/
├── api/
│   └── routes/
│       ├── dashboard.py              # NEW: Route definitions
│       └── dashboard_modules/        # NEW: Module directory
│           ├── __init__.py
│           ├── aggregations.py       # Query builders for DT
│           ├── recommendations.py    # Scoring & recommendation engine
│           ├── badges.py             # Statistical badge logic
│           └── chart_builders.py     # Chart.js data formatters
```

### 3.2 New Frontend Templates

```
backend/
├── templates/
│   └── pages/
│       ├── dashboard_table_types.html    # NEW: Table type comparison
│       └── dashboard_template_analysis.html  # NEW: Template deep-dive
```

### 3.3 Reused Components

| Component | Source | Usage |
|-----------|--------|-------|
| `statistics.py` | Existing | KL divergence, CV, trend |
| `comparison_scoring.py` | Existing | Thresholds, classification |
| `cost_calculator.py` | Existing | Cost/credit calculations |
| `base.html` | Existing | Layout, Tailwind, Chart.js |
| `latency_sections.html` | Existing | Latency display pattern |

---

## 4. API Response Contracts

### 4.1 Table Type Summary Response

```json
{
  "generated_at": "2026-02-15T10:30:00Z",
  "kpi_cards": [
    {
      "table_type": "HYBRID",
      "test_count": 89,
      "avg_qps": 2145.3,
      "avg_p95_ms": 34.2,
      "avg_error_rate": 0.02,
      "cost_per_1k_ops": 0.023,
      "trend": "stable",
      "badges": ["winner_qps", "stable"]
    }
  ],
  "comparison_table": {
    "columns": ["Metric", "STANDARD", "HYBRID", "INTERACTIVE", "DYNAMIC", "POSTGRES"],
    "rows": [
      {"metric": "QPS (avg)", "values": [1200, 2145, 890, null, 650], "winner": "HYBRID"},
      {"metric": "p50 (ms)", "values": [12, 8, 15, 22, 18], "winner": "HYBRID"},
      {"metric": "p95 (ms)", "values": [48, 35, 52, 45, 67], "winner": "HYBRID"},
      {"metric": "p99 (ms)", "values": [120, 89, 98, 78, 145], "winner": "DYNAMIC"},
      {"metric": "Cost/1K ops", "values": [0.04, 0.023, 0.08, 0.01, 0.03], "winner": "DYNAMIC"},
      {"metric": "Error %", "values": [0.1, 0.05, 0.2, 0.0, 0.08], "winner": "DYNAMIC"}
    ]
  },
  "recommendations": [
    {
      "workload_type": "OLTP",
      "recommended": "HYBRID",
      "confidence": 0.95,
      "rationale": "Best p95 latency (35ms) with competitive cost ($0.023/1K ops)"
    },
    {
      "workload_type": "Analytics",
      "recommended": "DYNAMIC",
      "confidence": 0.87,
      "rationale": "Lowest cost ($0.01/1K ops) for read-only workloads"
    }
  ]
}
```

### 4.2 Template Statistics Response

```json
{
  "template_id": "afd4d1b6-b9a1-46b1-baab-2fc82b6e9b4b",
  "template_name": "oltp_point_lookup_hybrid",
  "total_runs": 47,
  "summary": {
    "avg_qps": 2145.3,
    "avg_p50_ms": 8.2,
    "avg_p95_ms": 34.2,
    "avg_cost_per_run": 1.23,
    "coefficient_of_variation": 0.082,
    "stability_badge": "stable"
  },
  "trend": {
    "direction": "stable",
    "slope": 0.0012,
    "r_squared": 0.92,
    "last_10_change_pct": 2.3
  },
  "statistical_health": {
    "kl_divergence_vs_baseline": 0.12,
    "consistency_badge": "consistent",
    "outlier_count": 2,
    "outliers": [
      {"test_id": "234", "date": "2024-01-15", "p99_ms": 189, "reason": "3.2σ above median"}
    ]
  },
  "cost_summary": {
    "total_credits": 58.4,
    "avg_cost_per_run": 1.23,
    "cost_per_1k_ops_avg": 0.023,
    "qps_per_dollar": 1744
  }
}
```

### 4.3 Template Distribution Response (for histograms)

```json
{
  "template_id": "afd4d1b6-b9a1-46b1-baab-2fc82b6e9b4b",
  "latency_distribution": {
    "metric": "p95_latency_ms",
    "bins": [20, 25, 30, 35, 40, 45, 50],
    "counts": [3, 8, 15, 12, 6, 2, 1],
    "mean": 34.2,
    "std_dev": 4.2,
    "distribution_type": "normal"
  },
  "qps_distribution": {
    "metric": "qps",
    "bins": [1800, 1900, 2000, 2100, 2200, 2300, 2400],
    "counts": [2, 5, 12, 18, 7, 2, 1],
    "mean": 2145,
    "std_dev": 176
  }
}
```

### 4.4 Template Scatter Data Response

```json
{
  "template_id": "afd4d1b6-b9a1-46b1-baab-2fc82b6e9b4b",
  "scatter_plots": {
    "duration_vs_qps": {
      "x_label": "Duration (seconds)",
      "y_label": "QPS",
      "data": [
        {"x": 300, "y": 2100, "test_id": "abc123"},
        {"x": 600, "y": 2180, "test_id": "def456"}
      ]
    },
    "concurrency_vs_p95": {
      "x_label": "Concurrent Connections",
      "y_label": "p95 Latency (ms)",
      "data": [
        {"x": 10, "y": 25, "test_id": "abc123"},
        {"x": 20, "y": 35, "test_id": "def456"}
      ]
    },
    "qps_vs_cost": {
      "x_label": "QPS",
      "y_label": "Cost per 1K Ops ($)",
      "data": [
        {"x": 2100, "y": 0.022, "test_id": "abc123"},
        {"x": 2180, "y": 0.024, "test_id": "def456"}
      ]
    }
  }
}
```

---

## 5. Badge Logic

### 5.1 Winner Badges

```python
def determine_winner(metric: str, values: dict[str, float]) -> str | None:
    """Determine winner for a metric across table types."""
    if not values:
        return None
    
    # Lower is better for these metrics
    lower_is_better = {"p50_latency_ms", "p95_latency_ms", "p99_latency_ms", 
                       "error_rate", "cost_per_1k_ops"}
    
    if metric in lower_is_better:
        winner = min(values, key=lambda k: values[k] if values[k] is not None else float('inf'))
    else:
        winner = max(values, key=lambda k: values[k] if values[k] is not None else float('-inf'))
    
    return winner
```

### 5.2 Statistical Significance

```python
def is_statistically_significant(values_a: list, values_b: list) -> tuple[bool, float]:
    """Check if difference is statistically significant using Mann-Whitney U."""
    if len(values_a) < 5 or len(values_b) < 5:
        return False, 0.0
    
    # Use existing MANN_WHITNEY_U_TEST procedure or Python implementation
    p_value = mann_whitney_u_test(values_a, values_b)
    return p_value < 0.05, 1 - p_value  # confidence = 1 - p_value
```

### 5.3 Stability Badge

```python
def get_stability_badge(cv: float) -> str:
    """Determine stability based on coefficient of variation."""
    if cv < 0.10:  # < 10%
        return "very_stable"
    elif cv < 0.15:  # < 15%
        return "stable"
    elif cv < 0.25:  # < 25%
        return "moderate"
    else:
        return "volatile"
```

---

## 6. Chart.js Configurations

### 6.1 Grouped Bar Chart (Performance Comparison)

```javascript
const performanceChart = {
  type: 'bar',
  data: {
    labels: ['QPS', 'p50', 'p95', 'p99', 'Cost/1K'],
    datasets: [
      { label: 'STANDARD', data: [...], backgroundColor: '#2563EB' },
      { label: 'HYBRID', data: [...], backgroundColor: '#16A34A' },
      { label: 'INTERACTIVE', data: [...], backgroundColor: '#9333EA' },
      { label: 'DYNAMIC', data: [...], backgroundColor: '#EA580C' },
      { label: 'POSTGRES', data: [...], backgroundColor: '#6B7280' }
    ]
  },
  options: {
    responsive: true,
    plugins: {
      legend: { position: 'top' },
      tooltip: { callbacks: { ... } }
    }
  }
};
```

### 6.2 Scatter Plot (Template Analysis)

```javascript
const scatterChart = {
  type: 'scatter',
  data: {
    datasets: [{
      label: 'Duration vs QPS',
      data: scatterData.map(d => ({ x: d.duration, y: d.qps })),
      backgroundColor: 'rgba(37, 99, 235, 0.6)'
    }]
  },
  options: {
    scales: {
      x: { title: { display: true, text: 'Duration (seconds)' } },
      y: { title: { display: true, text: 'QPS' } }
    },
    plugins: {
      tooltip: {
        callbacks: {
          label: (ctx) => `Test ${ctx.raw.test_id}: ${ctx.raw.y} QPS`
        }
      }
    }
  }
};
```

### 6.3 Histogram (Distribution Analysis)

```javascript
const histogramChart = {
  type: 'bar',
  data: {
    labels: distribution.bins,
    datasets: [{
      label: 'p95 Latency Distribution',
      data: distribution.counts,
      backgroundColor: 'rgba(22, 163, 74, 0.6)',
      borderColor: '#16A34A',
      borderWidth: 1
    }]
  },
  options: {
    scales: {
      x: { title: { display: true, text: 'p95 Latency (ms)' } },
      y: { title: { display: true, text: 'Count' } }
    }
  }
};
```

---

**Next:** [02-sql-schema.md](02-sql-schema.md) - Dynamic tables and SQL definitions
