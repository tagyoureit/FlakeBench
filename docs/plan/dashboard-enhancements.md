# Dashboard Enhancements Plan

Implementation-level specification for dashboard metric improvements and UI polish.

**Status**: ⬜ Not Started  
**Priority**: Medium  
**Dependencies**: 2.17 (API Performance Optimization) ✅

---

## 1. Executive Summary

### Problem Statement

The current dashboard comparison views are missing critical metrics needed for informed decision-making:
- No queue time visibility (impacts latency interpretation)
- No cache hit rate display (affects throughput understanding)
- No cluster utilization in comparisons (MCW efficiency)
- No statistical summaries (avg/min/max/stddev)
- No cost/credit tracking (ROI analysis)

### Impact

Without these metrics, users cannot:
- Distinguish client-side latency from server-side queue delays
- Understand how cache efficiency affects observed performance
- Evaluate MCW scaling effectiveness
- Identify variance and outliers in workload behavior
- Calculate cost-effectiveness of different configurations

---

## 2. Current State Analysis

### Existing Dashboard Structure

| View | Purpose | Current Metrics |
|------|---------|-----------------|
| **History** | Time-series analysis | Throughput, latency (P50/P95/P99), concurrency, errors |
| **Short Compare** | Quick 2-run comparison | Summary cards, side-by-side charts |
| **Deep Compare** | Detailed metric analysis | All charts, query breakdown, configuration diff |

### Available API Data (Not Displayed)

The following data is already available via API but not surfaced in UI:

| Metric | Source | API Field |
|--------|--------|-----------|
| Queue time | QUERY_EXECUTIONS | `QUEUED_OVERLOAD_TIME`, `QUEUED_PROVISIONING_TIME` |
| Cache hit rate | QUERY_EXECUTIONS | `BYTES_SCANNED`, `BYTES_SCANNED_FROM_CACHE` |
| Clusters used | WORKER_METRICS_SNAPSHOTS | Available via warehouse poller |
| Error breakdown | QUERY_EXECUTIONS | `EXECUTION_STATUS`, `ERROR_CODE` |

### Data Model Strengths

- **QUERY_EXECUTIONS**: Comprehensive per-query data with timing breakdown
- **Pre-computed views**: TEST_SUMMARY_VIEW for aggregated metrics
- **Real-time snapshots**: WORKER_METRICS_SNAPSHOTS for live data

---

## 3. Feature Gap Analysis

| Feature | Current State | Data Available | Files Affected | Complexity |
|---------|---------------|----------------|----------------|------------|
| Statistical summary panel | ❌ None | ✅ Yes (QUERY_EXECUTIONS) | API, UI | Medium |
| Queue time comparison | ❌ None | ✅ Yes | API, UI | Low |
| Cache hit rate | ❌ None | ✅ Yes | API, UI | Low |
| Clusters used | ❌ Not in comparison | ✅ Yes | UI only | Low |
| Percentage deltas | ❌ None | ✅ Calculated | UI only | Low |
| Error rate timeline | ❌ Static only | ✅ Yes | API, UI | Medium |
| Queue time overlay | ❌ None | ✅ Yes | API, UI | Medium |
| Cost/credits | ❌ None | ⚠️ Partial | API, UI, enrichment | High |
| Latency histogram | ❌ None | ✅ Yes | API, UI | Medium |

---

## 4. Implementation Phases

### Phase A: Summary Statistics & Core Metrics (High Impact)

**Objective**: Add statistical visibility to comparison views.

#### A.1: Statistical Summary Panel

Add a collapsible panel showing aggregate statistics for key metrics.

**Metrics to include**:
- Total operations (count)
- Avg/Min/Max/StdDev for latency
- Avg/Min/Max/StdDev for QPS
- Total errors / error rate

**Files**:
- `backend/api/tests.py`: Add `/api/tests/{id}/statistics` endpoint
- `frontend/static/js/comparison.js`: Render summary panel

**API Response Shape**:
```json
{
  "latency": {
    "avg_ms": 45.2,
    "min_ms": 12.0,
    "max_ms": 1250.0,
    "stddev_ms": 38.5,
    "p50_ms": 42.0,
    "p95_ms": 120.0,
    "p99_ms": 250.0
  },
  "throughput": {
    "total_ops": 125000,
    "avg_qps": 2083.3,
    "min_qps": 1200.0,
    "max_qps": 2800.0,
    "stddev_qps": 320.5
  },
  "errors": {
    "total": 15,
    "rate_pct": 0.012
  }
}
```

#### A.2: Queue Time Comparison

Display queue time metrics in comparison views.

**Metrics**:
- Total queue time (sum)
- Average queue time per query
- Queue time as percentage of total latency

**Implementation**:
- Query `QUEUED_OVERLOAD_TIME + QUEUED_PROVISIONING_TIME` from QUERY_EXECUTIONS
- Add to comparison summary cards
- Include in detailed metrics table

**Files**:
- `backend/api/tests.py`: Extend comparison query
- `frontend/static/js/comparison.js`: Add queue time cards

#### A.3: Cache Hit Rate Display

Show cache efficiency in comparison views.

**Calculation**:
```sql
SUM(BYTES_SCANNED_FROM_CACHE) / NULLIF(SUM(BYTES_SCANNED), 0) * 100 AS cache_hit_rate_pct
```

**Display**:
- Percentage badge on comparison cards
- Color coding: Green (>80%), Yellow (50-80%), Red (<50%)

**Files**:
- `backend/api/tests.py`: Add cache metrics to query
- `frontend/static/js/comparison.js`: Render cache indicators

#### A.4: Clusters Used Indicator

Display cluster count in comparison views for MCW warehouses.

**Source**: WAREHOUSE_POLL_SNAPSHOTS or direct warehouse query

**Display**:
- "Clusters: N of M" badge
- Only shown for MCW warehouses

**Files**:
- `frontend/static/js/comparison.js`: Add cluster display

#### A.5: Percentage Delta Indicators

Add relative change indicators between runs.

**Display**:
- Green up/down arrows for improvements
- Red up/down arrows for regressions
- Percentage change value

**Rules**:
- Lower latency = improvement (green down)
- Higher throughput = improvement (green up)
- Lower error rate = improvement (green down)

**Files**:
- `frontend/static/js/comparison.js`: Delta calculation and display

---

### Phase B: Chart Enhancements

**Objective**: Improve chart informativeness and clarity.

#### B.1: Error Rate Over Time Chart

Add new chart showing error rate trends.

**Implementation**:
- New API endpoint: `/api/tests/{id}/error-timeline`
- Query error counts per time bucket from QUERY_EXECUTIONS
- Line chart with error rate on Y-axis

**Files**:
- `backend/api/tests.py`: Add error timeline endpoint
- `frontend/static/js/charts.js`: Error rate chart component
- `frontend/templates/comparison.html`: Chart container

#### B.2: Queue Time Timeline Overlay

Add queue time as overlay on latency charts.

**Implementation**:
- Secondary Y-axis for queue time
- Different line style (dashed) to distinguish
- Toggle to show/hide overlay

**Files**:
- `frontend/static/js/charts.js`: Overlay support
- `frontend/static/js/comparison.js`: Toggle control

#### B.3: Concurrency Chart Label Improvements

Improve labels on MCW Active Clusters chart.

**Changes**:
- Add "Target: N clusters" reference line
- Show utilization percentage
- Add legend explaining metrics

**Files**:
- `frontend/static/js/charts.js`: Label improvements

#### B.4: Read/Write Breakdown in Comparisons

Show read vs write operation breakdown.

**Display**:
- Stacked bar or pie chart
- Percentage breakdown
- Count values on hover

**Files**:
- `backend/api/tests.py`: Add operation type breakdown
- `frontend/static/js/comparison.js`: Breakdown visualization

---

### Phase C: History Dashboard Polish

**Objective**: Enhance the history view with additional insights.

#### C.1: Error Rate Overlay on Throughput

Add error rate as secondary overlay on throughput chart.

**Implementation**:
- Optional toggle to show error rate
- Uses same time buckets as throughput
- Different color and scale

**Files**:
- `frontend/templates/history.html`: Toggle control
- `frontend/static/js/history.js`: Overlay logic

#### C.2: Latency Histogram/Distribution View

Add histogram showing latency distribution.

**Implementation**:
- New API endpoint: `/api/tests/{id}/latency-histogram`
- Bucket latencies into configurable ranges
- Bar chart visualization

**API Response**:
```json
{
  "buckets": [
    {"range": "0-10ms", "count": 5000},
    {"range": "10-50ms", "count": 15000},
    {"range": "50-100ms", "count": 8000},
    {"range": "100-500ms", "count": 2000},
    {"range": ">500ms", "count": 100}
  ]
}
```

**Files**:
- `backend/api/tests.py`: Histogram endpoint
- `frontend/static/js/history.js`: Histogram chart

#### C.3: Efficiency Metric (QPS/Credit)

Show cost efficiency metric.

**Calculation**:
```
efficiency = total_operations / total_credits
```

**Display**:
- "Operations per credit" badge
- Comparison delta when multiple runs

**Dependency**: Requires Phase D credit tracking

---

### Phase D: Cost/Credits Implementation

**Objective**: Add credit/cost visibility across all views.

#### D.1: Credit Tracking Enrichment

Enrich test results with credit consumption data.

**Data Source**: WAREHOUSE_METERING_HISTORY

**Challenges**:
- Metering data has ~3 hour latency
- Must attribute credits to specific test runs
- Concurrent tests on same warehouse complicate attribution

**Implementation Options**:
1. **Post-hoc enrichment**: Background job updates TEST_RESULTS with credits
2. **Estimation**: Calculate based on warehouse size and duration
3. **Real-time polling**: Query metering during test (limited accuracy)

**Recommended**: Option 1 (post-hoc) with Option 2 (estimation) as fallback

**Files**:
- `backend/services/credit_tracker.py`: New service for credit enrichment
- `sql/schema/results_tables.sql`: Add credit columns
- `backend/api/tests.py`: Include credits in responses

#### D.2: Cost Display Across All Views

Surface credit data in UI.

**Locations**:
- History view: Credit column in results table
- Comparison view: Credit comparison cards
- Detail view: Credit breakdown panel

**Files**:
- `frontend/static/js/history.js`: Credit column
- `frontend/static/js/comparison.js`: Credit cards
- `frontend/static/js/detail.js`: Credit panel

#### D.3: Cost per 1000 Operations

Calculate and display cost efficiency.

**Calculation**:
```
cost_per_1k = (credits * credit_cost_usd / total_operations) * 1000
```

**Display**:
- "Cost per 1K ops: $X.XX" badge
- Requires credit pricing configuration

**Files**:
- `backend/config.py`: Credit pricing setting
- `frontend/static/js/comparison.js`: Cost calculation

---

### Phase E: UI/UX Polish

**Objective**: Improve consistency and usability.

#### E.1: Chart Title Consistency

Standardize chart titles across views.

**Pattern**: "{Metric} - {Context}"
- "Throughput - Operations per Second"
- "Latency - P95 Response Time"
- "Concurrency - Active Connections"

**Files**:
- `frontend/static/js/charts.js`: Title constants
- All chart rendering locations

#### E.2: Zero-Write Handling

Gracefully handle read-only workloads.

**Current Issue**: Write charts show empty/broken state

**Solution**:
- Detect zero writes
- Show "Read-only workload" message
- Hide or disable write-specific charts

**Files**:
- `frontend/static/js/comparison.js`: Zero-write detection
- `frontend/static/js/charts.js`: Empty state handling

#### E.3: Duration Mismatch Explanations

Explain when comparing runs of different durations.

**Display**:
- Warning banner when durations differ >10%
- Tooltip explaining comparison implications
- Option to normalize metrics to per-minute rates

**Files**:
- `frontend/static/js/comparison.js`: Duration check
- `frontend/templates/comparison.html`: Warning banner

---

## 5. Technical Details

### API Endpoints Summary

| Endpoint | Method | Purpose | Phase |
|----------|--------|---------|-------|
| `/api/tests/{id}/statistics` | GET | Statistical summary | A.1 |
| `/api/tests/{id}/error-timeline` | GET | Error rate over time | B.1 |
| `/api/tests/{id}/latency-histogram` | GET | Latency distribution | C.2 |
| `/api/tests/{id}/credits` | GET | Credit consumption | D.1 |

### Database Queries

**Statistical Summary (A.1)**:
```sql
SELECT
    COUNT(*) as total_ops,
    AVG(TOTAL_ELAPSED_TIME) as avg_latency_ms,
    MIN(TOTAL_ELAPSED_TIME) as min_latency_ms,
    MAX(TOTAL_ELAPSED_TIME) as max_latency_ms,
    STDDEV(TOTAL_ELAPSED_TIME) as stddev_latency_ms,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) as p50_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) as p95_latency_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY TOTAL_ELAPSED_TIME) as p99_latency_ms,
    SUM(CASE WHEN EXECUTION_STATUS != 'SUCCESS' THEN 1 ELSE 0 END) as error_count,
    SUM(QUEUED_OVERLOAD_TIME + QUEUED_PROVISIONING_TIME) as total_queue_time_ms,
    AVG(QUEUED_OVERLOAD_TIME + QUEUED_PROVISIONING_TIME) as avg_queue_time_ms,
    CASE 
        WHEN SUM(BYTES_SCANNED) > 0 
        THEN SUM(BYTES_SCANNED_FROM_CACHE) / SUM(BYTES_SCANNED) * 100 
        ELSE NULL 
    END as cache_hit_rate_pct
FROM QUERY_EXECUTIONS
WHERE TEST_ID = :test_id
```

**Error Timeline (B.1)**:
```sql
SELECT
    TIME_SLICE(QUERY_START_TIME, 10, 'SECOND') as time_bucket,
    COUNT(*) as total_ops,
    SUM(CASE WHEN EXECUTION_STATUS != 'SUCCESS' THEN 1 ELSE 0 END) as errors,
    errors / NULLIF(total_ops, 0) * 100 as error_rate_pct
FROM QUERY_EXECUTIONS
WHERE TEST_ID = :test_id
GROUP BY time_bucket
ORDER BY time_bucket
```

### Frontend Components

**New Components**:
- `StatisticalSummaryPanel`: Collapsible panel with aggregate stats
- `DeltaIndicator`: Percentage change with directional arrow
- `CacheHitBadge`: Color-coded cache efficiency indicator
- `ErrorTimelineChart`: Line chart for error trends
- `LatencyHistogram`: Bar chart for latency distribution

**Component Location**: `frontend/static/js/components/`

---

## 6. Unknowns & Risks

### Credit Data Accuracy

**Issue**: WAREHOUSE_METERING_HISTORY has ~3 hour latency

**Risk**: Credits won't be available for recently completed tests

**Mitigation**:
- Show "Credits pending" status for recent tests
- Provide estimation based on warehouse size and duration
- Background job to backfill credit data

### StdDev Calculation Approach

**Options**:
1. **Streaming**: Calculate incrementally during test (complex)
2. **Post-hoc**: Query all data after completion (accurate, slower)
3. **Sample-based**: Calculate from time-series samples (fast, approximate)

**Recommendation**: Option 2 (post-hoc) for accuracy; data volumes are manageable

### Chart Performance with Overlays

**Risk**: Multiple overlays may degrade rendering performance

**Mitigation**:
- Lazy-load overlay data
- Limit data points via aggregation
- Provide toggle to disable overlays

### Multi-Run Comparison (Ties to 2.15)

**Issue**: Current design assumes 2-run comparison; Phase 2.15 plans for 2-5 runs

**Impact**: Phase A-E features must be designed for N-run extensibility

**Approach**:
- Build components to accept array of runs
- Design summary panels with flexible layout
- Defer complex N-run charts to 2.15

---

## 7. Testing Strategy

### Unit Tests

**API Endpoints**:
- Test statistical calculations with known data
- Verify error handling for missing data
- Check response shape matches specification

**Components**:
- Test delta calculation logic
- Verify color coding thresholds
- Test zero-value edge cases

### Manual Testing Scenarios

| Scenario | Expected Behavior |
|----------|-------------------|
| Compare two identical runs | Deltas should be ~0% |
| Compare read-only vs mixed workload | Write charts handled gracefully |
| View test with no errors | Error rate shows 0%, chart empty state |
| View test with 100% cache hits | Cache badge shows green 100% |
| View recent test (no credits yet) | Shows "Credits pending" |

### Edge Cases

| Case | Handling |
|------|----------|
| Zero operations | Show "No data" instead of divide-by-zero |
| Single operation | StdDev = 0, note "single sample" |
| Missing queue time data | Show "N/A" instead of null |
| Very long duration (>1hr) | Aggregate time buckets to prevent chart overload |
| Concurrent tests on warehouse | Note credit attribution uncertainty |

---

## 8. Implementation Order Recommendation

**Recommended sequence** (based on impact and dependencies):

1. **A.1 Statistical Summary** - Foundation for other features
2. **A.5 Percentage Deltas** - Quick win, high visibility
3. **A.2-A.4 Queue/Cache/Clusters** - Core metric visibility
4. **B.1 Error Timeline** - Important diagnostic tool
5. **E.2-E.3 Zero-Write/Duration** - Polish existing experience
6. **B.2-B.4 Chart Overlays** - Enhanced analysis
7. **C.1-C.3 History Polish** - Secondary view improvements
8. **D.1-D.3 Cost/Credits** - Complex, depends on data availability
9. **E.1 Title Consistency** - Low priority polish

---

## Related Documents

- [comparison-feature.md](comparison-feature.md) - Multi-run comparison (2.15)
- [soft-guardrails.md](soft-guardrails.md) - Resource guardrails (2.16)
- [timer-fixes.md](timer-fixes.md) - Elapsed time fixes (2.19)
