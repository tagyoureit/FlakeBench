# Dashboard Pages - API Endpoints

**Parent:** [00-overview.md](00-overview.md)

---

## 1. Route Structure

All dashboard endpoints live under `/api/dashboard/`:

```
/api/dashboard/
├── table-types/
│   ├── GET /summary              # KPI cards + comparison table
│   ├── GET /recommendations      # Workload-based recommendations
│   └── GET /chart-data           # Chart.js formatted data
├── templates/
│   ├── GET /                     # List all templates with stats
│   ├── GET /{template_id}/summary        # Template overview
│   ├── GET /{template_id}/statistics     # Detailed stats + badges
│   ├── GET /{template_id}/distribution   # Histogram data
│   ├── GET /{template_id}/scatter        # Scatter plot data
│   ├── GET /{template_id}/trend          # Trend analysis
│   └── GET /{template_id}/runs           # All runs table
└── costs/
    └── GET /daily                # Daily cost rollup
```

---

## 2. Table Type Endpoints

### 2.1 GET /api/dashboard/table-types/summary

Returns aggregate metrics for all table types with comparison data.

**Response:**
```python
class TableTypeSummaryResponse(BaseModel):
    generated_at: datetime
    kpi_cards: list[TableTypeKPI]
    comparison_table: ComparisonTable
    totals: DashboardTotals

class TableTypeKPI(BaseModel):
    table_type: str
    test_count: int
    unique_templates: int
    avg_qps: float | None
    median_qps: float | None
    avg_p50_ms: float | None
    avg_p95_ms: float | None
    avg_p99_ms: float | None
    avg_error_rate: float | None
    total_credits: float | None
    credits_per_1k_ops: float | None
    
    # Derived cost fields (calculated by CostCalculator)
    estimated_cost_usd: float | None
    cost_per_1k_ops_usd: float | None
    
    # Badges
    badges: list[str]  # e.g., ["winner_qps", "stable", "cost_efficient"]
    
    # Trend
    trend_direction: str | None  # "up", "down", "stable"

class ComparisonTable(BaseModel):
    columns: list[str]  # ["Metric", "STANDARD", "HYBRID", ...]
    rows: list[ComparisonRow]

class ComparisonRow(BaseModel):
    metric: str
    values: dict[str, float | None]  # {table_type: value}
    winner: str | None
    lower_is_better: bool
```

**Implementation:**
```python
@router.get("/table-types/summary")
async def get_table_type_summary(
    db: SnowflakeConnection = Depends(get_db)
) -> TableTypeSummaryResponse:
    """
    Fetch table type summary from DT_TABLE_TYPE_SUMMARY,
    enrich with cost calculations and badges.
    """
    # 1. Query dynamic table
    raw_data = await db.fetch_all(
        "SELECT * FROM DT_TABLE_TYPE_SUMMARY"
    )
    
    # 2. Enrich with cost calculations
    kpi_cards = []
    for row in raw_data:
        kpi = TableTypeKPI(**row)
        
        # Calculate USD costs
        kpi.estimated_cost_usd = CostCalculator.credits_to_usd(
            row["total_credits"]
        )
        kpi.cost_per_1k_ops_usd = CostCalculator.credits_to_usd(
            row["credits_per_1k_ops"]
        )
        
        # Apply badges
        kpi.badges = determine_badges(row, all_rows=raw_data)
        
        kpi_cards.append(kpi)
    
    # 3. Build comparison table
    comparison_table = build_comparison_table(kpi_cards)
    
    return TableTypeSummaryResponse(
        generated_at=datetime.utcnow(),
        kpi_cards=kpi_cards,
        comparison_table=comparison_table,
        totals=calculate_totals(kpi_cards)
    )
```

### 2.2 GET /api/dashboard/table-types/recommendations

Returns workload-based recommendations.

**Query Parameters:**
- `workload_type`: Optional[str] - Filter to specific workload (OLTP, Analytics, Mixed)

**Response:**
```python
class RecommendationsResponse(BaseModel):
    recommendations: list[Recommendation]

class Recommendation(BaseModel):
    workload_type: str  # "OLTP", "Analytics", "Mixed"
    recommended_table_type: str
    confidence: float  # 0.0 - 1.0
    rationale: str
    metrics_summary: dict[str, float]  # Key metrics that drove decision
    runner_up: str | None
    runner_up_rationale: str | None
```

**Implementation:**
```python
@router.get("/table-types/recommendations")
async def get_recommendations(
    workload_type: str | None = None,
    db: SnowflakeConnection = Depends(get_db)
) -> RecommendationsResponse:
    """
    Generate recommendations using scoring weights.
    """
    # Fetch summary data
    summary = await db.fetch_all("SELECT * FROM DT_TABLE_TYPE_SUMMARY")
    
    # Score each table type for each workload
    recommendations = []
    for wl_type in ["OLTP", "Analytics", "Mixed"]:
        if workload_type and wl_type != workload_type:
            continue
            
        scores = score_table_types(summary, wl_type)
        winner = max(scores, key=lambda x: x["score"])
        runner_up = sorted(scores, key=lambda x: x["score"], reverse=True)[1]
        
        recommendations.append(Recommendation(
            workload_type=wl_type,
            recommended_table_type=winner["table_type"],
            confidence=winner["confidence"],
            rationale=generate_rationale(winner, wl_type),
            metrics_summary=winner["key_metrics"],
            runner_up=runner_up["table_type"],
            runner_up_rationale=generate_rationale(runner_up, wl_type)
        ))
    
    return RecommendationsResponse(recommendations=recommendations)
```

### 2.3 GET /api/dashboard/table-types/chart-data

Returns Chart.js-ready data for visualizations.

**Query Parameters:**
- `chart_type`: str - "bar", "line", "scatter"
- `metric`: str - "qps", "p95", "cost", etc.

**Response:**
```python
class ChartDataResponse(BaseModel):
    chart_type: str
    labels: list[str]
    datasets: list[ChartDataset]

class ChartDataset(BaseModel):
    label: str
    data: list[float | None]
    backgroundColor: str | list[str]
    borderColor: str | None = None
```

---

## 3. Template Endpoints

### 3.1 GET /api/dashboard/templates

Lists all templates with summary statistics.

**Query Parameters:**
- `table_type`: Optional[str] - Filter by table type
- `sort_by`: str = "last_run" - Sort field
- `limit`: int = 50

**Response:**
```python
class TemplateListResponse(BaseModel):
    templates: list[TemplateSummary]
    total_count: int

class TemplateSummary(BaseModel):
    template_id: str
    template_name: str
    table_type: str
    warehouse_size: str
    load_mode: str
    total_runs: int
    last_run: datetime
    avg_qps: float | None
    avg_p95_ms: float | None
    stability_badge: str
    cost_per_1k_ops_usd: float | None
```

### 3.2 GET /api/dashboard/templates/{template_id}/statistics

Returns detailed statistics for a single template.

**Response:**
```python
class TemplateStatisticsResponse(BaseModel):
    template_id: str
    template_name: str
    table_type: str
    load_mode: str
    
    # Counts
    total_runs: int
    recent_runs: int  # Last 10
    
    # Performance stats
    qps_stats: MetricStats
    p50_stats: MetricStats
    p95_stats: MetricStats
    p99_stats: MetricStats
    error_stats: MetricStats
    
    # Cost stats
    cost_stats: CostStats
    
    # Stability
    stability: StabilityMetrics
    
    # Badges
    badges: list[str]

class MetricStats(BaseModel):
    avg: float | None
    min: float | None
    max: float | None
    median: float | None
    stddev: float | None
    cv: float | None  # Coefficient of variation

class CostStats(BaseModel):
    total_credits: float
    avg_credits_per_run: float
    credits_per_1k_ops: float
    total_cost_usd: float
    avg_cost_per_run_usd: float
    cost_per_1k_ops_usd: float
    qps_per_dollar: float | None

class StabilityMetrics(BaseModel):
    cv_qps: float | None
    cv_p95: float | None
    badge: str  # "very_stable", "stable", "moderate", "volatile"
    trend_direction: str | None
    trend_pct: float | None
```

### 3.3 GET /api/dashboard/templates/{template_id}/distribution

Returns histogram data for distribution analysis.

**Query Parameters:**
- `metric`: str = "p95_latency_ms" - Which metric to histogram

**Response:**
```python
class DistributionResponse(BaseModel):
    template_id: str
    metric: str
    
    # Histogram data
    bins: list[float]  # Bin edges
    counts: list[int]  # Count per bin
    
    # Summary stats
    mean: float
    std_dev: float
    min_val: float
    max_val: float
    
    # Distribution shape analysis
    distribution_type: str  # "normal", "skewed_right", "bimodal", etc.
    skewness: float | None
```

**Implementation:**
```python
@router.get("/templates/{template_id}/distribution")
async def get_distribution(
    template_id: str,
    metric: str = "p95_latency_ms",
    num_bins: int = 20,
    db: SnowflakeConnection = Depends(get_db)
) -> DistributionResponse:
    """
    Calculate histogram distribution for a metric across all runs.
    """
    # Get all values for this template
    values = await db.fetch_all(f"""
        SELECT {metric} as value
        FROM V_TEMPLATE_RUNS
        WHERE template_id = :template_id
        AND {metric} IS NOT NULL
    """, {"template_id": template_id})
    
    if not values:
        raise HTTPException(404, "No data for template")
    
    # Calculate histogram
    data = [v["value"] for v in values]
    counts, bin_edges = np.histogram(data, bins=num_bins)
    
    # Calculate stats
    mean = np.mean(data)
    std_dev = np.std(data)
    skewness = scipy.stats.skew(data) if len(data) >= 8 else None
    
    # Determine distribution type
    dist_type = classify_distribution(data, skewness)
    
    return DistributionResponse(
        template_id=template_id,
        metric=metric,
        bins=bin_edges.tolist(),
        counts=counts.tolist(),
        mean=mean,
        std_dev=std_dev,
        min_val=min(data),
        max_val=max(data),
        distribution_type=dist_type,
        skewness=skewness
    )
```

### 3.4 GET /api/dashboard/templates/{template_id}/scatter

Returns scatter plot data for correlation analysis.

**Query Parameters:**
- `x_metric`: str = "duration_seconds"
- `y_metric`: str = "qps"

**Response:**
```python
class ScatterResponse(BaseModel):
    template_id: str
    x_metric: str
    y_metric: str
    x_label: str
    y_label: str
    data: list[ScatterPoint]
    correlation: float | None  # Pearson correlation coefficient
    trend_line: TrendLine | None

class ScatterPoint(BaseModel):
    x: float
    y: float
    test_id: str
    label: str  # For tooltip

class TrendLine(BaseModel):
    slope: float
    intercept: float
    r_squared: float
```

### 3.5 GET /api/dashboard/templates/{template_id}/trend

Returns trend analysis over time.

**Response:**
```python
class TrendResponse(BaseModel):
    template_id: str
    
    # QPS trend
    qps_trend: TrendAnalysis
    
    # Latency trend
    p95_trend: TrendAnalysis
    
    # Cost trend
    cost_trend: TrendAnalysis
    
    # Time series data for charting
    time_series: list[TimeSeriesPoint]

class TrendAnalysis(BaseModel):
    direction: str  # "improving", "degrading", "stable"
    slope: float
    r_squared: float
    confidence: float
    change_pct: float  # % change from first to last
    
class TimeSeriesPoint(BaseModel):
    date: date
    qps: float | None
    p95_ms: float | None
    cost_per_1k_ops: float | None
    test_count: int
```

### 3.6 GET /api/dashboard/templates/{template_id}/runs

Returns paginated list of all runs for the template.

**Query Parameters:**
- `limit`: int = 50
- `offset`: int = 0
- `sort_by`: str = "start_time"
- `sort_order`: str = "desc"

**Response:**
```python
class TemplateRunsResponse(BaseModel):
    template_id: str
    runs: list[TemplateRun]
    total_count: int
    page: int
    page_size: int

class TemplateRun(BaseModel):
    test_id: str
    start_time: datetime
    duration_seconds: float
    concurrent_connections: int
    qps: float | None
    p50_ms: float | None
    p95_ms: float | None
    p99_ms: float | None
    error_rate: float
    credits_used: float | None
    cost_per_1k_ops_usd: float | None
    
    # Outlier detection
    is_outlier: bool
    outlier_reason: str | None  # e.g., "p99 3.2σ above median"
```

---

## 4. Cost Endpoints

### 4.1 GET /api/dashboard/costs/daily

Returns daily cost rollup for budget tracking.

**Query Parameters:**
- `start_date`: Optional[date]
- `end_date`: Optional[date]
- `table_type`: Optional[str]

**Response:**
```python
class DailyCostResponse(BaseModel):
    data: list[DailyCostEntry]
    totals: CostTotals

class DailyCostEntry(BaseModel):
    run_date: date
    table_type: str
    warehouse_size: str | None
    test_count: int
    total_credits: float
    total_cost_usd: float
    total_operations: int
    credits_per_1k_ops: float | None
    avg_qps: float | None

class CostTotals(BaseModel):
    total_credits: float
    total_cost_usd: float
    total_tests: int
    total_operations: int
    avg_credits_per_1k_ops: float
```

---

## 5. File Structure

```
backend/api/routes/
├── dashboard.py                    # Route definitions
└── dashboard_modules/
    ├── __init__.py
    ├── models.py                   # Pydantic response models
    ├── aggregations.py             # Dynamic table query builders
    ├── recommendations.py          # Scoring & recommendation engine
    ├── badges.py                   # Badge determination logic
    ├── chart_builders.py           # Chart.js data formatters
    ├── statistics.py               # Extended stats (histogram, trend)
    └── constants.py                # Scoring weights, thresholds
```

---

## 6. Error Handling

```python
class DashboardError(HTTPException):
    """Base exception for dashboard errors."""
    pass

class NoDataError(DashboardError):
    """Raised when no data exists for query."""
    def __init__(self, entity: str, identifier: str):
        super().__init__(
            status_code=404,
            detail=f"No data found for {entity}: {identifier}"
        )

class InsufficientDataError(DashboardError):
    """Raised when insufficient data for statistical analysis."""
    def __init__(self, required: int, actual: int):
        super().__init__(
            status_code=422,
            detail=f"Insufficient data for analysis. Required: {required}, Found: {actual}"
        )
```

---

**Next:** [04-ui-templates.md](04-ui-templates.md) - HTMX/Alpine.js template designs
