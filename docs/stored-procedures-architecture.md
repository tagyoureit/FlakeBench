# Stored Procedures and Semantic View Architecture

Last updated: 2026-02-12

## Overview

FlakeBench uses a hybrid architecture combining:
1. **Stored Procedures (SPs)** - For complex chart data and API endpoints
2. **Semantic View** - For natural language queries via Cortex Agent
3. **Python API** - Thin wrapper layer calling SPs or implementing complex business logic

This architecture provides:
- **Single source of truth** for SQL logic (in Snowflake)
- **Reusability** between API and Cortex Agent
- **Maintainability** through centralized SQL definitions
- **Natural language access** via semantic view

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           USER INTERFACES                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐  │
│  │   Dashboard UI   │    │    REST API      │    │  Cortex Agent    │  │
│  │  (Chart.js)      │    │   (FastAPI)      │    │  (Natural Lang)  │  │
│  └────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘  │
│           │                       │                       │            │
└───────────┼───────────────────────┼───────────────────────┼────────────┘
            │                       │                       │
            ▼                       ▼                       ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                        SNOWFLAKE DATABASE                                │
│                   UNISTORE_BENCHMARK.TEST_RESULTS                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    STORED PROCEDURES                            │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │   │
│  │  │ LIST_RECENT_    │  │ GET_TEST_       │  │ GET_LATENCY_    │  │   │
│  │  │ TESTS           │  │ SUMMARY         │  │ BREAKDOWN       │  │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘  │   │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │   │
│  │  │ GET_ERROR_      │  │ GET_METRICS_    │  │ GET_STEP_       │  │   │
│  │  │ TIMELINE        │  │ TIMESERIES      │  │ HISTORY         │  │   │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘  │   │
│  │  ┌─────────────────┐  ┌─────────────────┐                       │   │
│  │  │ GET_WAREHOUSE_  │  │ ANALYZE_        │                       │   │
│  │  │ TIMESERIES      │  │ BENCHMARK       │                       │   │
│  │  └─────────────────┘  └─────────────────┘                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    SEMANTIC VIEW                                │   │
│  │                 BENCHMARK_ANALYTICS                             │   │
│  │  - Dimensions (table_type, warehouse_size, status, etc.)        │   │
│  │  - Facts (qps, p50/p95/p99 latency, error_rate, etc.)          │   │
│  │  - Metrics (AVG_QPS, TEST_COUNT, TOTAL_OPS, etc.)              │   │
│  │  - VQRs (22 pre-verified queries)                              │   │
│  │  - Filters (completed_tests_only, exclude_warmup, etc.)        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    BASE TABLES                                  │   │
│  │  - TEST_RESULTS (main test data)                               │   │
│  │  - QUERY_EXECUTIONS (individual query records)                 │   │
│  │  - WORKER_METRICS_SNAPSHOTS (time-series per worker)           │   │
│  │  - CONTROLLER_STEP_HISTORY (FIND_MAX progression)              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

## Stored Procedures

All stored procedures return `VARIANT` (JSON) for easy consumption by Python and Cortex Agent.

### LIST_RECENT_TESTS(p_limit)
- **Purpose**: List recent benchmark tests (parent runs only)
- **Parameters**: `p_limit` (default 20, max 50)
- **Returns**: JSON with `results` array and `total_pages`
- **Features**: 
  - Only returns parent runs (RUN_ID = TEST_ID) or single tests
  - Includes scaling config, load mode, workload mix from TEST_CONFIG

### GET_TEST_SUMMARY(p_test_id)
- **Purpose**: Comprehensive test details
- **Parameters**: `p_test_id` (UUID string)
- **Returns**: Full test configuration, results, and per-operation latencies
- **Features**:
  - All latency percentiles (overall, read, write, point_lookup, range_scan, insert, update)
  - Load mode and scaling configuration
  - Parent run detection
  - Latency spread ratio warning (P95/P50 > 5x)

### GET_LATENCY_BREAKDOWN(p_test_id)
- **Purpose**: Detailed latency breakdown by operation type
- **Parameters**: `p_test_id` (UUID string)
- **Returns**: Read/write aggregates + per-query-type breakdown
- **Features**:
  - Parent run aggregation (combines data from all child workers)
  - Warmup detection (excludes WARMUP = TRUE queries)
  - Duration and ops_per_second calculations
  - Per-query-type: POINT_LOOKUP, RANGE_SCAN, INSERT, UPDATE

### GET_ERROR_TIMELINE(p_test_id)
- **Purpose**: Error distribution over time for visualization
- **Parameters**: `p_test_id` (UUID string)
- **Returns**: Error counts per 5-second bucket
- **Features**:
  - Per-operation-type error breakdown
  - Warmup phase detection
  - Parent run aggregation
  - Overall error rate calculation

### GET_METRICS_TIMESERIES(p_test_id)
- **Purpose**: Time-series metrics for dashboard charts
- **Parameters**: `p_test_id` (UUID string)
- **Returns**: Array of snapshots with QPS, latencies, connections
- **Features**:
  - Multi-worker aggregation by second bucket
  - Warmup end detection
  - Snowflake metrics (sf_running, sf_queued, sf_blocked)
  - Per-operation ops/sec breakdown
  - CPU and memory metrics

### GET_STEP_HISTORY(p_test_id)
- **Purpose**: FIND_MAX step progression data
- **Parameters**: `p_test_id` (UUID string)
- **Returns**: Step-by-step concurrency scaling history
- **Features**:
  - Metadata (total steps, best step, final outcome)
  - Per-step metrics (QPS, latency, error rate)
  - QPS vs prior step percentage
  - Queue detection flag

### GET_WAREHOUSE_TIMESERIES(p_test_id, p_bucket_seconds)
- **Purpose**: Multi-cluster warehouse scaling metrics
- **Parameters**: `p_test_id`, `p_bucket_seconds` (default 1)
- **Returns**: Cluster counts and queue metrics over time
- **Features**:
  - Supports WAREHOUSE_POLL_SNAPSHOTS or derives from QUERY_EXECUTIONS
  - Active cluster tracking
  - Queue overload metrics

### ANALYZE_BENCHMARK(p_test_id)
- **Purpose**: Comprehensive benchmark analysis
- **Parameters**: `p_test_id` (UUID string)
- **Returns**: Combined summary and latency breakdown
- **Features**:
  - Calls GET_TEST_SUMMARY and GET_LATENCY_BREAKDOWN
  - Suitable for AI analysis workflows

## Semantic View: BENCHMARK_ANALYTICS

### Purpose
Enables natural language queries about benchmark data via Cortex Agent or Cortex Analyst.

### Table Types (Database Systems)
| Value | Description |
|-------|-------------|
| `POSTGRES` | PostgreSQL database |
| `HYBRID` | Snowflake Unistore/Hybrid tables (row-level locking) |
| `STANDARD` | Snowflake standard tables (analytics-optimized) |
| `ICEBERG` | Snowflake Iceberg tables |
| `INTERACTIVE` | Snowflake Interactive tables (low-latency) |

**IMPORTANT**: "interactive" means `table_type = 'INTERACTIVE'`, NOT `'HYBRID'`

### Key Dimensions
- `table_type` - Database system being benchmarked
- `warehouse_size` - Compute size (XSMALL, SMALL, MEDIUM, etc.)
- `status` - Test status (COMPLETED, FAILED, CANCELLED)
- `query_kind` - Operation type (POINT_LOOKUP, RANGE_SCAN, INSERT, UPDATE)
- `warmup` - Whether query was during warmup phase

### Key Facts
- `qps` - Queries per second (throughput)
- `p50_latency_ms`, `p95_latency_ms`, `p99_latency_ms` - Latency percentiles
- `error_rate` - Percentage of failed operations
- `total_operations`, `read_operations`, `write_operations`

### Key Metrics (Aggregations)
- `AVG_QPS`, `MAX_QPS`, `MIN_QPS` - Throughput aggregates
- `AVG_P50`, `AVG_P95`, `AVG_P99` - Latency aggregates
- `TEST_COUNT` - Count of tests
- `TOTAL_OPS`, `TOTAL_ERRORS` - Sum aggregates

### Pre-defined Filters
- `completed_tests_only` - `status = 'COMPLETED'`
- `exclude_warmup_queries` - `warmup = FALSE`
- `postgresql_tests_only` - `table_type = 'POSTGRES'`
- `interactive_tests_only` - `table_type = 'INTERACTIVE'`
- `snowflake_hybrid_tests_only` - `table_type = 'HYBRID'`

### Verified Queries (VQRs)
22 pre-verified queries for common questions:
- "Compare PostgreSQL vs Snowflake performance"
- "Show recent benchmark tests"
- "What are my recent postgres tests?"
- "Tell me about my latest interactive table test"
- "Compare Interactive vs Hybrid tables"
- etc.

## Python API Integration

### Helper Function
```python
async def _call_sp(pool: Any, sp_name: str, *args: Any) -> dict[str, Any]:
    """Call a stored procedure and return parsed JSON result."""
    prefix = _prefix()  # UNISTORE_BENCHMARK.TEST_RESULTS
    placeholders = ", ".join(["?" for _ in args]) if args else ""
    query = f"CALL {prefix}.{sp_name}({placeholders})"
    
    rows = await pool.execute_query(query, params=list(args) if args else [])
    
    if not rows or not rows[0] or not rows[0][0]:
        return {}
    
    result = rows[0][0]
    if isinstance(result, str):
        return json.loads(result)
    return dict(result) if result else {}
```

### Converted Endpoints
| Endpoint | Stored Procedure |
|----------|------------------|
| `GET /{test_id}/latency-breakdown` | `GET_LATENCY_BREAKDOWN` |
| `GET /{test_id}/error-timeline` | `GET_ERROR_TIMELINE` |

### Endpoints Remaining in Python
Complex endpoints with extensive business logic remain in Python:
- `/tests` (list with pagination, filtering)
- `/{test_id}` (test details with enrichment)
- `/{test_id}/metrics` (time-series with post-processing)

## File Locations

### SQL Files
- `sql/schema/chart_procedures.sql` - All 8 stored procedure definitions
- `sql/schema/semantic_view.sql` - Semantic view with VQRs and filters

### Python Files
- `backend/api/routes/test_results.py` - API routes with `_call_sp()` helper

## Deployment

### Deploy Stored Procedures
```bash
# Execute in Snowflake
USE DATABASE UNISTORE_BENCHMARK;
USE SCHEMA TEST_RESULTS;

-- Run the entire chart_procedures.sql file
```

### Deploy Semantic View
```bash
# Execute in Snowflake
USE DATABASE UNISTORE_BENCHMARK;
USE SCHEMA TEST_RESULTS;

-- Run the semantic_view.sql file
```

### Verify Deployment
```sql
-- Check procedures
SHOW PROCEDURES LIKE 'GET_%' IN SCHEMA UNISTORE_BENCHMARK.TEST_RESULTS;
SHOW PROCEDURES LIKE 'LIST_%' IN SCHEMA UNISTORE_BENCHMARK.TEST_RESULTS;

-- Check semantic view
SHOW SEMANTIC VIEWS LIKE 'BENCHMARK_ANALYTICS';
SELECT GET_DDL('SEMANTIC VIEW', 'UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_ANALYTICS');
```

## Testing

### Test Stored Procedures
```sql
-- Test with known test_id
CALL UNISTORE_BENCHMARK.TEST_RESULTS.GET_TEST_SUMMARY('353187bd-ca11-492c-ad2d-404ffebf4793');
CALL UNISTORE_BENCHMARK.TEST_RESULTS.GET_LATENCY_BREAKDOWN('353187bd-ca11-492c-ad2d-404ffebf4793');
CALL UNISTORE_BENCHMARK.TEST_RESULTS.LIST_RECENT_TESTS(10);
```

### Test API Endpoints
```bash
# Start backend
cd backend && uvicorn main:app --reload

# Test endpoints
curl http://localhost:8000/api/test-results/353187bd-ca11-492c-ad2d-404ffebf4793/latency-breakdown
curl http://localhost:8000/api/test-results/353187bd-ca11-492c-ad2d-404ffebf4793/error-timeline
```
