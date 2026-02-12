# Cortex Agent + Semantic View Implementation Plan

**Document Version:** 1.0  
**Created:** 2026-02-12  
**Last Updated:** 2026-02-12  
**Status:** Planning Complete, Ready for Implementation  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Current State Analysis](#3-current-state-analysis)
4. [Architecture Decision Records](#4-architecture-decision-records)
5. [Semantic View Design](#5-semantic-view-design)
6. [Stored Procedures Design](#6-stored-procedures-design)
7. [Cortex Agent Design](#7-cortex-agent-design)
8. [Python Backend Migration](#8-python-backend-migration)
9. [Implementation Phases](#9-implementation-phases)
10. [File Deliverables](#10-file-deliverables)
11. [Testing Strategy](#11-testing-strategy)
12. [Deployment Strategy](#12-deployment-strategy)
13. [Future Phases](#13-future-phases)

---

## 1. Executive Summary

### Goal

Build a standalone Cortex Agent with Snowflake Intelligence on top of the benchmark analytics data, replacing the current `AI_COMPLETE` view approach with a governed, queryable interface.

### Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Semantic Model Format | SQL `CREATE SEMANTIC VIEW` DDL | User requirement; transportable to other accounts |
| Storage Location | Local SQL files in repo | Version control, replicability, CI/CD friendly |
| Chart Data Approach | Stored Procedures returning JSON | Complex SQL (window functions, GENERATOR) not supported in semantic views |
| Python SQL Migration | Replace inline SQL with SP calls | Single source of truth; reduce code duplication |
| Phase 1 Focus | AI_COMPLETE comparison analysis | Matches current functionality; iterative enhancement |

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  CORTEX AGENT: BENCHMARK_ANALYST                                │
│  (Orchestrates tools + provides natural language interface)     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Tool 1: query_benchmarks                                       │
│  └─ SEMANTIC VIEW: BENCHMARK_ANALYTICS                          │
│     ├─ Analytical queries (aggregations, comparisons, trends)   │
│     └─ Natural language → SQL translation                       │
│                                                                 │
│  Tool 2: get_metrics_timeseries                                 │
│  └─ STORED PROCEDURE: GET_METRICS_TIMESERIES(test_id)           │
│     └─ Complex time-series with window functions                │
│                                                                 │
│  Tool 3: get_error_timeline                                     │
│  └─ STORED PROCEDURE: GET_ERROR_TIMELINE(test_id)               │
│     └─ Error bucketing for visualization                        │
│                                                                 │
│  Tool 4: analyze_benchmark                                      │
│  └─ STORED PROCEDURE: ANALYZE_BENCHMARK(test_id, mode)          │
│     └─ AI_COMPLETE with mode-specific prompts                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Problem Statement

### Current State

The benchmark application uses direct `AI_COMPLETE` function calls embedded in Python code:

```python
# Current approach (test_results.py:7789)
ai_resp = await pool.execute_query(
    "SELECT AI_COMPLETE(model => ?, prompt => ?, ...) AS RESP",
    params=["claude-4-sonnet", prompt, json.dumps(model_params)],
)
```

**Limitations:**
1. **No governance** - Prompts scattered across Python code
2. **No discoverability** - Users can't explore data schema naturally
3. **No semantic layer** - Raw SQL knowledge required for custom queries
4. **Tight coupling** - Business logic mixed with presentation layer
5. **Not self-service** - Users can't ask their own questions

### Desired State

1. **Governed semantic layer** - Business terms mapped to physical columns
2. **Natural language interface** - Ask questions in plain English
3. **Self-service analytics** - Users can explore without SQL knowledge
4. **Centralized prompts** - AI instructions in one place (semantic view + agent)
5. **Chart-ready data** - Stored procedures return visualization-ready JSON
6. **Replicable** - SQL DDL files can deploy to any Snowflake account

---

## 3. Current State Analysis

### 3.1 Database Schema

**Location:** `FLAKEBENCH.TEST_RESULTS`

| Object | Type | Purpose |
|--------|------|---------|
| `TEST_RESULTS` | Table | Individual test execution results |
| `METRICS_SNAPSHOTS` | Table | Time-series metrics per test |
| `WORKER_METRICS_SNAPSHOTS` | Table | Per-worker metrics (multi-worker runs) |
| `QUERY_EXECUTIONS` | Table | Individual query execution records |
| `WAREHOUSE_POLL_SNAPSHOTS` | Table | Controller-side warehouse metrics |
| `CONTROLLER_STEP_HISTORY` | Table | Step history for FIND_MAX/QPS modes |
| `V_LATEST_TEST_RESULTS` | View | Recent tests summary |
| `V_METRICS_BY_MINUTE` | View | Minute-bucketed metrics |
| `V_WAREHOUSE_METRICS` | View | Test-level warehouse aggregations |
| `V_CLUSTER_BREAKDOWN` | View | Per-cluster latency breakdown |
| `V_WAREHOUSE_TIMESERIES` | View | Per-second warehouse metrics |

### 3.2 AI Analysis Implementation

**Location:** `backend/api/routes/test_results.py`

| Endpoint | Lines | Function |
|----------|-------|----------|
| `/{test_id}/ai-analysis` | 7127-7826 | Single-test AI analysis |
| `/{test_id}/ai-chat` | 7829-7910 | Interactive chat follow-up |
| `/compare/ai-analysis` | 7915-8142 | Side-by-side comparison |

**Prompt Builders:**

| Function | Lines | Mode |
|----------|-------|------|
| `_build_concurrency_prompt()` | 6251-6498 | CONCURRENCY mode |
| `_build_qps_prompt()` | 6500-6759 | QPS mode |
| `_build_find_max_prompt()` | 6761-7061 | FIND_MAX_CONCURRENCY mode |

**Model:** `claude-4-sonnet` with `temperature: 0.3-0.5`, `max_tokens: 1500-2500`

### 3.3 Chart SQL Patterns

**Location:** `backend/api/routes/test_results.py` and `test_results_modules/`

| Chart | Lines | SQL Complexity |
|-------|-------|----------------|
| Metrics timeseries | 4424-4900 | Window functions, JSON aggregation, multi-worker bucketing |
| Warehouse timeseries | 5134-5373 | GENERATOR, LAST_VALUE forward-fill, MCW logic |
| Overhead timeseries | 5376-5635 | LAG/LEAD interpolation |
| Error timeline | 8367-8497 | Time bucketing, conditional aggregation |
| Latency breakdown | 8500-8693 | Multiple percentiles, operation grouping |

---

## 4. Architecture Decision Records

### ADR-001: Semantic View vs YAML Semantic Model

**Context:** Snowflake offers two approaches for semantic layers:
1. **YAML semantic model files** - Staged files referenced by Cortex Analyst
2. **SQL SEMANTIC VIEW** - DDL-based semantic definition

**Decision:** Use SQL `CREATE SEMANTIC VIEW` DDL

**Rationale:**
- User requirement: "Create this is the SQL SEMANTIC VIEW not a YAML file"
- DDL is version-controllable in SQL files
- Transportable to other accounts via standard SQL execution
- No stage management required
- Matches existing schema management pattern (`sql/schema/*.sql`)

**Consequences:**
- Must use CREATE SEMANTIC VIEW syntax (not YAML structure)
- AI_SQL_GENERATION replaces custom_instructions
- Relationships defined inline (not separate specification)

---

### ADR-002: Chart Data Implementation - Stored Procedures

**Context:** Chart endpoints require complex SQL:
- Window functions (LAG, LEAD, LAST_VALUE)
- Table generators (GENERATOR)
- Forward-fill interpolation
- Multi-worker aggregation

**Decision:** Migrate chart SQL to Stored Procedures returning VARIANT (JSON)

**Alternatives Considered:**

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| Keep in Python | No migration effort | Duplicated logic, no reuse | Rejected |
| SQL Views | Simpler | Can't parameterize by test_id, no complex logic | Rejected |
| UDFs | Functional | Less flexible for complex multi-statement logic | Rejected |
| **Stored Procedures** | Full SQL power, parameterized, JSON output | Requires migration | **Selected** |

**Rationale:**
- User requirement: "I strongly prefer to migrate the existing Python to SP and not have both"
- Stored procedures support all SQL features (window functions, generators)
- Can return structured JSON directly usable by frontend
- Single source of truth for chart logic
- Reusable by both Python backend and Cortex Agent

**Consequences:**
- Must migrate 5 chart query patterns to SPs
- Python endpoints become thin wrappers calling SPs
- Chart logic centralized in Snowflake

---

### ADR-003: Semantic View Scope - What Can/Cannot Be Modeled

**Context:** Semantic views have limitations on what SQL constructs they support.

**Analysis:**

| SQL Pattern | Semantic View Support | Alternative |
|-------------|----------------------|-------------|
| Simple aggregations (SUM, AVG, COUNT) | ✅ Native metrics | - |
| Percentiles (PERCENTILE_CONT) | ✅ Metric expressions | - |
| GROUP BY dimensions | ✅ Native dimensions | - |
| JOINs between tables | ✅ RELATIONSHIPS clause | - |
| Time-bucketing (DATE_TRUNC) | ⚠️ Limited | Define as dimension |
| Window functions (LAG, LEAD) | ❌ Not supported | Stored Procedure |
| GENERATOR for time-series | ❌ Not supported | Stored Procedure |
| Forward-fill (LAST_VALUE IGNORE NULLS) | ❌ Not supported | Stored Procedure |
| VARIANT/JSON extraction | ⚠️ Limited | Flatten in base view |

**Decision:** Hybrid architecture
- Semantic view for analytical queries (comparisons, aggregations, filtering)
- Stored procedures for chart data (complex time-series transformations)

---

### ADR-004: Agent Tool Configuration

**Context:** Cortex Agent can use multiple tool types.

**Decision:** Configure agent with three tool types:

| Tool Type | Tool Name | Resource | Purpose |
|-----------|-----------|----------|---------|
| `cortex_analyst_text_to_sql` | `query_benchmarks` | Semantic View | Analytical queries |
| `generic` (procedure) | `get_chart_data` | Stored Procedure | Chart JSON generation |
| `generic` (procedure) | `analyze_benchmark` | Stored Procedure | AI analysis wrapper |

**Rationale:**
- Semantic view handles "What is the average QPS for hybrid tables?"
- Stored procedures handle "Show me the metrics timeseries for test X"
- Combined capabilities cover all current functionality

---

### ADR-005: Python Migration Strategy

**Context:** Chart endpoints currently contain inline SQL in Python.

**Decision:** Replace inline SQL with stored procedure calls

**Before:**
```python
# test_results.py (current)
query = f"""
    SELECT TIMESTAMP, QPS, P50_LATENCY_MS, ...
    FROM WORKER_METRICS_SNAPSHOTS
    WHERE RUN_ID = '{run_id}'
    ORDER BY TIMESTAMP
"""
result = await pool.execute_query(query)
# ... 100+ lines of Python post-processing
```

**After:**
```python
# test_results.py (migrated)
result = await pool.execute_query(
    "CALL GET_METRICS_TIMESERIES(?)",
    params=[test_id]
)
return result[0]["DATA"]  # JSON already formatted
```

**Consequences:**
- Dramatic reduction in Python SQL code
- All chart logic in SQL (testable, versionable)
- Python becomes thin API layer

---

## 5. Semantic View Design

### 5.1 CREATE SEMANTIC VIEW DDL

```sql
CREATE OR REPLACE SEMANTIC VIEW BENCHMARK_ANALYTICS

-- Logical Tables
TABLES (
    tests AS TEST_RESULTS
        PRIMARY KEY (test_id)
        WITH SYNONYMS = ('benchmark', 'run', 'execution')
        COMMENT = 'Individual benchmark test executions',
    
    metrics AS METRICS_SNAPSHOTS
        PRIMARY KEY (snapshot_id)
        COMMENT = 'Time-series metrics snapshots during test execution',
    
    queries AS QUERY_EXECUTIONS
        PRIMARY KEY (execution_id)
        COMMENT = 'Individual query execution records'
)

-- Relationships
RELATIONSHIPS (
    metrics(test_id) REFERENCES tests,
    queries(test_id) REFERENCES tests
)

-- Facts (numeric columns that can be aggregated)
FACTS (
    tests.qps AS qps
        WITH SYNONYMS = ('queries per second', 'throughput')
        COMMENT = 'Queries per second achieved during test',
    
    tests.p50_latency_ms AS p50_latency
        WITH SYNONYMS = ('median latency', 'p50')
        COMMENT = 'Median (50th percentile) latency in milliseconds',
    
    tests.p95_latency_ms AS p95_latency
        WITH SYNONYMS = ('p95', '95th percentile latency')
        COMMENT = '95th percentile latency in milliseconds',
    
    tests.p99_latency_ms AS p99_latency
        WITH SYNONYMS = ('p99', '99th percentile latency')
        COMMENT = '99th percentile latency in milliseconds',
    
    tests.error_rate AS error_rate
        WITH SYNONYMS = ('failure rate', 'error percentage')
        COMMENT = 'Percentage of failed operations',
    
    tests.total_operations AS total_operations
        WITH SYNONYMS = ('total queries', 'operation count')
        COMMENT = 'Total number of operations executed',
    
    tests.warehouse_credits_used AS credits_used
        WITH SYNONYMS = ('credits', 'cost')
        COMMENT = 'Snowflake credits consumed during test',
    
    tests.concurrent_connections AS concurrency
        WITH SYNONYMS = ('workers', 'connections', 'threads')
        COMMENT = 'Number of concurrent connections/workers',
    
    tests.duration_seconds AS duration
        WITH SYNONYMS = ('runtime', 'execution time')
        COMMENT = 'Total test duration in seconds'
)

-- Dimensions (categorical columns for filtering/grouping)
DIMENSIONS (
    tests.test_id AS test_id
        COMMENT = 'Unique identifier for the test',
    
    tests.test_name AS test_name
        WITH SYNONYMS = ('name', 'title')
        COMMENT = 'Human-readable test name',
    
    tests.table_type AS table_type
        WITH SYNONYMS = ('storage type', 'table kind')
        COMMENT = 'Type of table: STANDARD, HYBRID, INTERACTIVE, DYNAMIC, POSTGRES',
    
    tests.warehouse AS warehouse_name
        WITH SYNONYMS = ('warehouse')
        COMMENT = 'Snowflake warehouse used for test',
    
    tests.warehouse_size AS warehouse_size
        WITH SYNONYMS = ('size', 'compute size')
        COMMENT = 'Warehouse size: X-Small through 6X-Large',
    
    tests.status AS status
        WITH SYNONYMS = ('state', 'outcome')
        COMMENT = 'Test status: COMPLETED, FAILED, CANCELLED, RUNNING',
    
    tests.start_time AS start_time
        WITH SYNONYMS = ('started', 'begin time')
        COMMENT = 'When the test started',
    
    tests.scenario_name AS scenario
        WITH SYNONYMS = ('test scenario', 'workload')
        COMMENT = 'Scenario/workload type',
    
    -- Derived dimension from VARIANT
    PUBLIC tests.load_mode AS 
        COALESCE(
            test_config:template_config:load_mode::VARCHAR,
            test_config:scenario:load_mode::VARCHAR,
            'CONCURRENCY'
        )
        WITH SYNONYMS = ('mode', 'test mode')
        COMMENT = 'Load mode: CONCURRENCY, QPS, FIND_MAX_CONCURRENCY'
)

-- Metrics (computed aggregations)
METRICS (
    tests.avg_qps AS AVG(qps)
        WITH SYNONYMS = ('average throughput')
        COMMENT = 'Average queries per second across tests',
    
    tests.avg_p95 AS AVG(p95_latency)
        WITH SYNONYMS = ('average p95')
        COMMENT = 'Average P95 latency across tests',
    
    tests.total_ops AS SUM(total_operations)
        COMMENT = 'Sum of all operations across tests',
    
    tests.test_count AS COUNT(test_id)
        WITH SYNONYMS = ('number of tests', 'count')
        COMMENT = 'Number of tests'
)

COMMENT = 'Semantic view for benchmark performance analytics. Supports queries about test results, latency, throughput, and resource usage.'

AI_SQL_GENERATION '
You are analyzing Snowflake benchmark performance data. Key concepts:

LOAD MODES:
- CONCURRENCY: Fixed worker count, measures steady-state performance
- QPS: Auto-scales workers to achieve target queries per second  
- FIND_MAX_CONCURRENCY: Step-load test to find maximum sustainable concurrency

TABLE TYPES:
- STANDARD: Traditional Snowflake tables (analytics-optimized)
- HYBRID: Transactional tables with row-level locking
- INTERACTIVE: Low-latency query service tables
- POSTGRES: PostgreSQL comparison baseline

METRICS INTERPRETATION:
- QPS (queries per second): Higher is better
- P50/P95/P99 latency: Lower is better, measured in milliseconds
- Error rate: Should be < 1% for healthy tests
- Credits: Cost in Snowflake compute credits

COMMON QUERIES:
- Compare performance across table types or warehouse sizes
- Find tests with highest/lowest latency or throughput
- Analyze trends over time
- Identify failed or problematic tests
';
```

### 5.2 Semantic View Validation Rules

Per Snowflake docs, the semantic view must comply with:
1. At least one dimension or metric must be defined
2. All referenced columns must exist in base tables
3. Relationships must reference valid table aliases
4. PRIMARY KEY columns should be unique

---

## 6. Stored Procedures Design

### 6.1 GET_METRICS_TIMESERIES

**Purpose:** Return time-series metrics for dashboard charts

**Signature:**
```sql
CREATE OR REPLACE PROCEDURE GET_METRICS_TIMESERIES(
    p_test_id VARCHAR,
    p_bucket_seconds INTEGER DEFAULT 1
)
RETURNS VARIANT
LANGUAGE SQL
```

**Returns:** JSON array of time-bucketed metrics:
```json
{
  "data": [
    {
      "timestamp": "2026-02-12T10:00:00Z",
      "elapsed_seconds": 0,
      "qps": 1250.5,
      "p50_latency_ms": 12.3,
      "p95_latency_ms": 45.6,
      "p99_latency_ms": 89.2,
      "active_connections": 100,
      "phase": "MEASUREMENT"
    }
  ],
  "metadata": {
    "test_id": "abc-123",
    "bucket_seconds": 1,
    "total_points": 300
  }
}
```

**SQL Logic:**
- Query WORKER_METRICS_SNAPSHOTS for the test
- Bucket to requested interval (default 1 second)
- Aggregate across workers (for multi-worker runs)
- Include phase information for filtering

---

### 6.2 GET_ERROR_TIMELINE

**Purpose:** Return error counts bucketed by time interval

**Signature:**
```sql
CREATE OR REPLACE PROCEDURE GET_ERROR_TIMELINE(
    p_test_id VARCHAR,
    p_bucket_seconds INTEGER DEFAULT 5
)
RETURNS VARIANT
LANGUAGE SQL
```

**Returns:** JSON array of error buckets:
```json
{
  "data": [
    {
      "bucket_start": "2026-02-12T10:00:00Z",
      "bucket_seconds": 0,
      "total_queries": 500,
      "error_count": 3,
      "error_rate": 0.006
    }
  ]
}
```

---

### 6.3 GET_LATENCY_BREAKDOWN

**Purpose:** Return latency percentiles grouped by operation type

**Signature:**
```sql
CREATE OR REPLACE PROCEDURE GET_LATENCY_BREAKDOWN(
    p_test_id VARCHAR
)
RETURNS VARIANT
LANGUAGE SQL
```

**Returns:** JSON with read/write breakdown:
```json
{
  "reads": {
    "count": 45000,
    "p50_ms": 8.2,
    "p95_ms": 25.4,
    "p99_ms": 67.8,
    "min_ms": 1.2,
    "max_ms": 234.5
  },
  "writes": {
    "count": 5000,
    "p50_ms": 15.3,
    "p95_ms": 45.2,
    "p99_ms": 112.4,
    "min_ms": 5.1,
    "max_ms": 456.7
  },
  "by_query_kind": {
    "POINT_LOOKUP": {...},
    "RANGE_SCAN": {...},
    "INSERT": {...},
    "UPDATE": {...}
  }
}
```

---

### 6.4 ANALYZE_BENCHMARK

**Purpose:** Wrapper for AI_COMPLETE with mode-specific prompts

**Signature:**
```sql
CREATE OR REPLACE PROCEDURE ANALYZE_BENCHMARK(
    p_test_id VARCHAR,
    p_mode VARCHAR DEFAULT NULL  -- Auto-detect from test_config if NULL
)
RETURNS VARIANT
LANGUAGE SQL
```

**Returns:** JSON with AI analysis:
```json
{
  "summary": "This FIND_MAX_CONCURRENCY test achieved...",
  "grade": "B+",
  "key_findings": [...],
  "recommendations": [...],
  "model": "claude-4-sonnet",
  "tokens_used": 1847
}
```

**Logic:**
1. Fetch test configuration and results
2. Determine load mode (CONCURRENCY, QPS, FIND_MAX_CONCURRENCY)
3. Build mode-specific prompt (mirroring Python prompt builders)
4. Call AI_COMPLETE
5. Return structured response

---

## 7. Cortex Agent Design

### 7.1 Agent Specification

```sql
-- Note: Agent creation via REST API, but spec documented here for reference
-- File: sql/schema/cortex_agent.sql

/*
Agent: BENCHMARK_ANALYST
Database: FLAKEBENCH
Schema: TEST_RESULTS

Tools:
1. query_benchmarks - Semantic view for analytical queries
2. get_metrics_timeseries - Stored procedure for chart data
3. get_error_timeline - Stored procedure for error visualization
4. get_latency_breakdown - Stored procedure for latency analysis
5. analyze_benchmark - Stored procedure for AI-powered analysis
*/
```

### 7.2 Agent Configuration JSON

```json
{
  "models": {
    "orchestration": "auto"
  },
  "orchestration": {
    "budget": {
      "seconds": 300,
      "tokens": 100000
    }
  },
  "instructions": {
    "orchestration": "You are a benchmark performance analyst. Help users understand their Snowflake and PostgreSQL benchmark results.\n\nAvailable tools:\n- query_benchmarks: Use for analytical questions about test results (comparisons, aggregations, filtering)\n- get_metrics_timeseries: Use when user asks for time-series data or charts\n- get_error_timeline: Use when investigating errors or failures\n- get_latency_breakdown: Use when analyzing latency by operation type\n- analyze_benchmark: Use for comprehensive AI-powered analysis of a specific test\n\nAlways start with query_benchmarks to understand context before diving into specific test details.",
    "response": "Provide clear, actionable insights. Include specific numbers and percentages. Suggest next steps for investigation when appropriate."
  },
  "tools": [
    {
      "tool_spec": {
        "type": "cortex_analyst_text_to_sql",
        "name": "query_benchmarks",
        "description": "Query benchmark test results using natural language. Use for questions about test performance, comparisons across table types or warehouse sizes, finding tests by criteria, and aggregate statistics."
      }
    },
    {
      "tool_spec": {
        "type": "generic",
        "name": "get_metrics_timeseries",
        "description": "Get time-series metrics data for a specific test. Returns JSON with QPS, latency percentiles, and connection counts over time. Use when user asks for charts or time-series visualization.",
        "input_schema": {
          "type": "object",
          "properties": {
            "test_id": {
              "type": "string",
              "description": "The test_id to get metrics for"
            },
            "bucket_seconds": {
              "type": "integer",
              "description": "Time bucket size in seconds (default: 1)"
            }
          },
          "required": ["test_id"]
        }
      }
    },
    {
      "tool_spec": {
        "type": "generic",
        "name": "get_error_timeline",
        "description": "Get error counts over time for a specific test. Use when investigating test failures or error patterns.",
        "input_schema": {
          "type": "object",
          "properties": {
            "test_id": {
              "type": "string",
              "description": "The test_id to analyze errors for"
            }
          },
          "required": ["test_id"]
        }
      }
    },
    {
      "tool_spec": {
        "type": "generic",
        "name": "get_latency_breakdown",
        "description": "Get latency breakdown by operation type (reads vs writes, point lookups vs range scans). Use for detailed latency analysis.",
        "input_schema": {
          "type": "object",
          "properties": {
            "test_id": {
              "type": "string",
              "description": "The test_id to analyze latency for"
            }
          },
          "required": ["test_id"]
        }
      }
    },
    {
      "tool_spec": {
        "type": "generic",
        "name": "analyze_benchmark",
        "description": "Get comprehensive AI-powered analysis of a benchmark test. Provides grading, key findings, and recommendations based on test mode (CONCURRENCY, QPS, or FIND_MAX).",
        "input_schema": {
          "type": "object",
          "properties": {
            "test_id": {
              "type": "string",
              "description": "The test_id to analyze"
            }
          },
          "required": ["test_id"]
        }
      }
    }
  ],
  "tool_resources": {
    "query_benchmarks": {
      "execution_environment": {
        "query_timeout": 120,
        "type": "warehouse",
        "warehouse": ""
      },
      "semantic_view": "FLAKEBENCH.TEST_RESULTS.BENCHMARK_ANALYTICS"
    },
    "get_metrics_timeseries": {
      "type": "procedure",
      "identifier": "FLAKEBENCH.TEST_RESULTS.GET_METRICS_TIMESERIES",
      "execution_environment": {
        "type": "warehouse",
        "warehouse": "",
        "query_timeout": 60
      }
    },
    "get_error_timeline": {
      "type": "procedure",
      "identifier": "FLAKEBENCH.TEST_RESULTS.GET_ERROR_TIMELINE",
      "execution_environment": {
        "type": "warehouse",
        "warehouse": "",
        "query_timeout": 60
      }
    },
    "get_latency_breakdown": {
      "type": "procedure",
      "identifier": "FLAKEBENCH.TEST_RESULTS.GET_LATENCY_BREAKDOWN",
      "execution_environment": {
        "type": "warehouse",
        "warehouse": "",
        "query_timeout": 60
      }
    },
    "analyze_benchmark": {
      "type": "procedure",
      "identifier": "FLAKEBENCH.TEST_RESULTS.ANALYZE_BENCHMARK",
      "execution_environment": {
        "type": "warehouse",
        "warehouse": "",
        "query_timeout": 180
      }
    }
  }
}
```

---

## 8. Python Backend Migration

### 8.1 Files to Modify

| File | Current State | Target State |
|------|---------------|--------------|
| `backend/api/routes/test_results.py` | ~8,300 lines with inline SQL | Thin wrapper calling SPs |
| `backend/api/routes/test_results_modules/queries.py` | SQL query functions | Remove or simplify |

### 8.2 Migration Pattern

**Before (inline SQL):**
```python
@router.get("/{test_id}/metrics")
async def get_metrics(test_id: str):
    query = f"""
        SELECT TIMESTAMP, ELAPSED_SECONDS, QPS, P50_LATENCY_MS, ...
        FROM WORKER_METRICS_SNAPSHOTS
        WHERE RUN_ID = (SELECT RUN_ID FROM TEST_RESULTS WHERE TEST_ID = '{test_id}')
        ORDER BY TIMESTAMP ASC
    """
    result = await pool.execute_query(query)
    
    # 100+ lines of Python post-processing...
    data = []
    for row in result:
        # bucketing, aggregation, smoothing...
    
    return {"data": data}
```

**After (SP call):**
```python
@router.get("/{test_id}/metrics")
async def get_metrics(test_id: str, bucket_seconds: int = 1):
    result = await pool.execute_query(
        "CALL GET_METRICS_TIMESERIES(?, ?)",
        params=[test_id, bucket_seconds]
    )
    return result[0]["GET_METRICS_TIMESERIES"]
```

### 8.3 Endpoints to Migrate

| Endpoint | Lines | SP Target |
|----------|-------|-----------|
| `GET /{test_id}/metrics` | 4424-4900 | `GET_METRICS_TIMESERIES` |
| `GET /{test_id}/warehouse-timeseries` | 5134-5373 | `GET_WAREHOUSE_TIMESERIES` |
| `GET /{test_id}/overhead-timeseries` | 5376-5635 | `GET_OVERHEAD_TIMESERIES` |
| `GET /{test_id}/error-timeline` | 8367-8497 | `GET_ERROR_TIMELINE` |
| `GET /{test_id}/latency-breakdown` | 8500-8693 | `GET_LATENCY_BREAKDOWN` |
| `GET /{test_id}/ai-analysis` | 7127-7826 | `ANALYZE_BENCHMARK` |

---

## 9. Implementation Phases

### Phase 1: Core Infrastructure (This Phase)

**Scope:** AI_COMPLETE comparison analysis + core chart procedures

**Deliverables:**
1. `sql/schema/semantic_view.sql` - CREATE SEMANTIC VIEW DDL
2. `sql/schema/chart_procedures.sql` - Core chart stored procedures
3. `sql/schema/analysis_procedure.sql` - AI analysis stored procedure
4. `sql/schema/cortex_agent.json` - Agent specification for REST API deployment

**Success Criteria:**
- Semantic view deployable via `snowsql -f semantic_view.sql`
- Stored procedures return correct JSON matching current Python output
- Agent responds to natural language queries about benchmarks

### Phase 2: Extended Capabilities (Future)

**Scope:** Historical comparison, anomaly detection, trend analysis

**Deliverables:**
- Additional stored procedures for comparison logic
- Enhanced semantic view with time-based dimensions
- Agent instructions for comparative analysis

### Phase 3: Python Migration (Future)

**Scope:** Replace inline SQL with SP calls in backend

**Deliverables:**
- Updated `test_results.py` with SP calls
- Removed duplicate SQL logic from Python
- Performance validation

---

## 10. File Deliverables

### Directory Structure

```
sql/
├── schema/
│   ├── results_tables.sql          # Existing - tables and views
│   ├── control_tables.sql          # Existing - hybrid tables
│   ├── semantic_view.sql           # NEW - CREATE SEMANTIC VIEW
│   ├── chart_procedures.sql        # NEW - Chart data SPs
│   ├── analysis_procedure.sql      # NEW - AI analysis SP
│   └── cortex_agent.json           # NEW - Agent spec for REST API
```

### File Purposes

| File | Purpose | Depends On |
|------|---------|------------|
| `semantic_view.sql` | Semantic layer for analytical queries | `results_tables.sql` |
| `chart_procedures.sql` | JSON-returning SPs for visualizations | `results_tables.sql` |
| `analysis_procedure.sql` | AI_COMPLETE wrapper with prompts | `results_tables.sql` |
| `cortex_agent.json` | Agent configuration for REST API | All above |

---

## 11. Testing Strategy

### 11.1 Semantic View Testing

```sql
-- Test 1: Basic query through semantic view
SELECT * FROM TABLE(
    SNOWFLAKE.CORTEX.COMPLETE(
        'llama3.1-70b',
        'Using semantic view BENCHMARK_ANALYTICS, what is the average QPS for HYBRID table tests?'
    )
);

-- Test 2: Verify dimensions are discoverable
SHOW SEMANTIC DIMENSIONS IN SEMANTIC VIEW BENCHMARK_ANALYTICS;

-- Test 3: Verify metrics are discoverable
SHOW SEMANTIC METRICS IN SEMANTIC VIEW BENCHMARK_ANALYTICS;
```

### 11.2 Stored Procedure Testing

```sql
-- Test 1: Metrics timeseries returns valid JSON
CALL GET_METRICS_TIMESERIES('test-id-here');

-- Test 2: Output matches expected schema
SELECT 
    data.value:timestamp::TIMESTAMP AS ts,
    data.value:qps::FLOAT AS qps
FROM TABLE(FLATTEN(GET_METRICS_TIMESERIES('test-id-here'):data)) data;
```

### 11.3 Agent Testing

```sql
-- Test 1: Agent responds to capability query
SELECT SNOWFLAKE.CORTEX.AGENT(
    'FLAKEBENCH.TEST_RESULTS.BENCHMARK_ANALYST',
    'What can you help me with?'
);

-- Test 2: Agent uses semantic view
SELECT SNOWFLAKE.CORTEX.AGENT(
    'FLAKEBENCH.TEST_RESULTS.BENCHMARK_ANALYST',
    'What is the average P95 latency for HYBRID table tests?'
);

-- Test 3: Agent uses stored procedure
SELECT SNOWFLAKE.CORTEX.AGENT(
    'FLAKEBENCH.TEST_RESULTS.BENCHMARK_ANALYST',
    'Show me the metrics timeseries for test abc-123'
);
```

---

## 12. Deployment Strategy

### 12.1 Prerequisites

```sql
-- Required privileges
GRANT CREATE SEMANTIC VIEW ON SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE <role>;
GRANT CREATE PROCEDURE ON SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE <role>;
GRANT CREATE AGENT ON SCHEMA FLAKEBENCH.TEST_RESULTS TO ROLE <role>;
```

### 12.2 Deployment Order

```bash
# 1. Deploy semantic view
snowsql -f sql/schema/semantic_view.sql

# 2. Deploy stored procedures
snowsql -f sql/schema/chart_procedures.sql
snowsql -f sql/schema/analysis_procedure.sql

# 3. Deploy agent via REST API (requires script)
# The agent spec is in cortex_agent.json
python scripts/deploy_agent.py --config sql/schema/cortex_agent.json
```

### 12.3 Replication to Other Accounts

All SQL files are account-agnostic. To deploy to another account:

```bash
# Set connection to target account
export SNOWSQL_ACCOUNT=target_account
export SNOWSQL_USER=deploy_user

# Run deployment scripts in order
snowsql -f sql/schema/results_tables.sql
snowsql -f sql/schema/semantic_view.sql
snowsql -f sql/schema/chart_procedures.sql
snowsql -f sql/schema/analysis_procedure.sql
# Deploy agent via REST API
```

---

## 13. Future Phases

### Phase 2: Historical Comparison

- Rolling median calculations
- Baseline detection
- Regression identification
- Trend analysis with statistical significance

### Phase 3: Anomaly Detection

- Automated outlier detection
- Alert integration
- Performance degradation notifications

### Phase 4: Multi-Test Analysis

- Cross-test comparisons
- A/B test analysis
- Configuration impact analysis

---

## Appendix A: Prompt Migration Reference

The following Python prompt builders will be migrated to the `ANALYZE_BENCHMARK` stored procedure:

| Python Function | Mode | Lines | Key Sections |
|-----------------|------|-------|--------------|
| `_build_concurrency_prompt()` | CONCURRENCY | 6251-6498 | Steady-state analysis, QPS interpretation, latency grading |
| `_build_qps_prompt()` | QPS | 6500-6759 | Target achievement, scaling behavior, stability |
| `_build_find_max_prompt()` | FIND_MAX | 6761-7061 | Step progression, saturation detection, recommendations |

---

## Appendix B: SQL Complexity Reference

### Window Functions in Chart SQL

```sql
-- Example from warehouse timeseries (Python)
LAST_VALUE(started_clusters IGNORE NULLS) OVER (
    PARTITION BY run_id 
    ORDER BY second 
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
) AS filled_clusters
```

This pattern is NOT supported in semantic views but IS supported in stored procedures.

### Generator Pattern

```sql
-- Example from timeseries gap-fill (Python)
SELECT 
    DATEADD('second', seq, start_time) AS second
FROM (SELECT MIN(start_time) AS start_time FROM test_results WHERE test_id = ?)
CROSS JOIN TABLE(GENERATOR(ROWCOUNT => 86400))
```

This pattern requires stored procedures.

---

## Appendix C: Related Documents

- [AI Comparison Plan](ai-comparison-plan.md) - Detailed comparison feature design
- [Snowflake CREATE SEMANTIC VIEW](https://docs.snowflake.com/en/sql-reference/sql/create-semantic-view) - DDL reference
- [Cortex Agent Documentation](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agent) - Agent creation guide
