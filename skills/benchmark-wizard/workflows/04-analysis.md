# Phase 4: Result Analysis

## Purpose

Hand off completed test results to the Cortex Agent for AI-powered analysis, or provide direct SQL queries for manual analysis.

## CRITICAL: AI Analysis is MANDATORY

**The agent MUST use AI analysis for result interpretation.** Do NOT skip this step and manually create comparison tables.

After tests complete:
1. Call the AI analysis endpoint (see below)
2. Present the AI's insights to the user **in full**
3. You may ADD additional context or insights after the AI output
4. Offer additional analysis options if needed

**⚠️ CRITICAL: Present the COMPLETE output from the AI analysis endpoint.**

Specifically:
- ❌ Do NOT skip or omit any sections (even if they say "data not available")
- ❌ Do NOT summarize or condense the output
- ❌ Do NOT replace the AI analysis with your own comparison table
- ✅ Present ALL sections from the AI analysis
- ✅ You MAY ADD additional insights AFTER presenting the full AI output

**The AI analysis is the authoritative output.** You can augment it with additional context, but never reduce it.

**Why this matters:** 
- You may think your comparison table is "easier to read" - this is a trap
- You may think you're being "helpful" by condensing the output - this is a trap
- The AI analysis provides consistent methodology and catches patterns you might miss
- Your "improvements" may omit important context or introduce errors
- Adding insights is fine; removing or summarizing is not

## CRITICAL: Neutral Product Positioning

**When comparing Snowflake products (Postgres, Interactive Tables, Hybrid Tables, Standard Tables), use neutral, factual language.**

Each product is optimized for different use cases. Present differences as trade-offs, not as one being "better" or "worse."

| ❌ AVOID (Negative Framing) | ✅ USE (Neutral Framing) |
|----------------------------|-------------------------|
| "additional overhead" | "different architecture optimized for X" |
| "slower" / "worse" | "higher latency at this concurrency level" |
| "limited capacity" | "optimized for lower-concurrency, low-latency workloads" |
| "inferior performance" | "different performance characteristics" |
| "can't handle" | "designed for different workload patterns" |

**Example - WRONG:**
```
Interactive Tables have additional overhead compared to Postgres, making them slower.
```

**Example - CORRECT:**
```
Postgres achieved higher throughput (552 QPS vs 106 QPS) at this concurrency level.
Interactive Tables are optimized for ultra-low-latency point lookups at lower concurrency,
while Postgres excels at higher-concurrency OLTP workloads.
```

**Key principle:** State the facts (latency numbers, QPS, concurrency limits) and let users draw conclusions. Explain what each product is *optimized for* rather than what it's *bad at*.

## Input

From Phase 3:

```json
{
  "run_ids": ["run-789xyz"],
  "status": "COMPLETED",
  "summary_metrics": {
    "total_queries": 374100,
    "average_qps": 1247,
    "p50_latency_ms": 12,
    "p95_latency_ms": 45,
    "p99_latency_ms": 89,
    "error_rate": 0.0
  }
}
```

## Analysis Options

Present user with analysis choices:

```markdown
## Analysis Options

Your test has completed. How would you like to analyze results?

A) **AI Analysis** (recommended)
   Ask the Cortex Agent natural language questions about your results

B) **Dashboard View**
   Open the interactive dashboard with charts and metrics

C) **Direct SQL**
   Query the results tables directly

D) **Export Data**
   Export results to CSV for external analysis
```

## Option A: AI Analysis (MANDATORY)

### API Endpoints

**For comparing two tests:**
```bash
curl -sL -X POST "http://127.0.0.1:8000/api/tests/compare/ai-analysis" \
  -H "Content-Type: application/json" \
  -d '{
    "primary_id": "<run_id_1>",
    "secondary_id": "<run_id_2>",
    "question": "Compare performance. Which performed better?"
  }'
```

**For single test analysis:**
```bash
curl -sL -X POST "http://127.0.0.1:8000/api/tests/<run_id>/ai-analysis" \
  -H "Content-Type: application/json" \
  -d '{"question": "What was the max sustainable throughput?"}'
```

### Cortex Agent (Alternative)

```
UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_ANALYST
```

```bash
cortex analyst query "Compare latency across all tests from today" \
  --agent=UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_ANALYST
```

### Test Comparison Context API (Powerful)

**Use `get_test_comparison_context(test_id)` whenever a user asks about performance trends, regressions, stability, or optimization opportunities.**

This API aggregates complex, multi-step logic (SQL fingerprinting, statistical scoring, historical lookups) into a single JSON payload. It saves the agent from running 5+ SQL queries and doing math in context.

```bash
curl -sL "http://127.0.0.1:8000/api/tests/<test_id>/comparison-context?min_similarity=0.55"
```

**The API returns TWO distinct types of comparison. You must distinguish between them:**

#### 1. Direct Baselines (`comparable_candidates` & `vs_previous`)

**What they are:** Previous runs of the *exact same* Template and Load Mode.

**Use for:** Determining **Regressions** or **Stability**.

**Logic:**
- Check `vs_previous.verdict`. If `"REGRESSED"`, warn the user immediately.
- Check `vs_median`. If current QPS is significantly lower than median, it indicates an anomaly even if the previous run was also bad.

#### 2. Cross-Template Matches (`similar_candidates`)

**What they are:** Runs from *different* templates that execute the **exact same SQL** (matched via fingerprint).

**Use for:** Determining **Optimization Opportunities** and **Sizing**.

**Logic:**
- Look for candidates with higher QPS or lower Latency than the current test.
- **Sizing Analysis:** If a `similar_candidate` on a `MEDIUM` warehouse has 2x the QPS of the current `SMALL` warehouse, tell the user: *"Scaling to Medium yields linear gains for this workload."*
- **Config Analysis:** If a `similar_candidate` with `query_acceleration=true` performs better, suggest enabling that feature.

#### Response Strategy

1. **Always start by stating the context:** *"Compared to [N] baseline runs..."*
2. **If `vs_previous` shows regression:** Identify the specific metric (e.g., *"Latency regressed by 15%, likely due to increased spilling listed in the metrics"*).
3. **If `similar_candidates` exist:** Offer a "Pro Tip": *"I found a similar test (different template) running the same SQL that achieved 20% higher throughput using [Configuration X]."*

#### Why This is Powerful

The "art" of finding related tests is encoded in the `similar_candidates` field:

| Without this API | With this API |
|------------------|---------------|
| Agent sees Test A and thinks "I have no history for Test A" | Agent sees Test A, realizes it's just "Test B" with a new name, pulls up Test B's history |
| No context for new templates | Says "Hey, this is performing exactly like Test B usually does" |

#### API Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `test_id` | string | required | The UUID of the test to analyze |
| `min_similarity` | number | 0.55 | Threshold (0.0-1.0) for finding similar tests. Lower to 0.4 for broader cross-template matches |

### Suggested Analysis Prompts

For single test runs:

```markdown
## Suggested Questions

1. **Performance Summary**
   "Summarize the performance of run-789xyz"

2. **Latency Analysis**
   "What was the latency distribution? Were there any outliers?"

3. **Throughput Stability**
   "How stable was the QPS over the test duration?"

4. **Error Analysis**
   "Were there any errors? What caused them?"

5. **Resource Utilization**
   "How did warehouse utilization change during the test?"
```

For comparison tests:

```markdown
## Comparison Analysis Questions

1. **Side-by-Side Comparison**
   "Compare latency between X-Small and Medium warehouses"

2. **Cost-Performance Analysis**
   "Which warehouse size gives the best QPS per credit?"

3. **Scaling Behavior**
   "How does throughput scale with warehouse size?"

4. **Break-Even Analysis**
   "At what QPS does upgrading from Small to Medium become cost-effective?"

5. **Recommendation**
   "Based on these results, which configuration would you recommend for 1000 QPS?"
```

For FIND_MAX_CONCURRENCY tests:

```markdown
## FIND_MAX_CONCURRENCY Analysis Questions

1. **Maximum Throughput**
   "What was the maximum sustainable QPS before degradation?"

2. **Saturation Point**
   "At what concurrency level did latency start increasing significantly?"

3. **Error Threshold**
   "When did errors start appearing? What type of errors?"

4. **Capacity Recommendation**
   "For a P95 latency SLA of 100ms, what's the recommended max concurrency?"
```

## SLO-Based Result Interpretation

If the user provided SLO targets in Phase 1, incorporate them into the analysis:

### With SLO Targets

When `slo_targets` were collected (e.g., P50: 50ms, P95: 200ms, P99: 500ms):

```markdown
## SLO Analysis

**Your Targets vs. Actual Results:**

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| P50 Latency | 50ms | 12ms | ✅ **PASS** (76% headroom) |
| P95 Latency | 200ms | 45ms | ✅ **PASS** (78% headroom) |
| P99 Latency | 500ms | 89ms | ✅ **PASS** (82% headroom) |

**Assessment:**
Your workload is comfortably within SLO targets at {concurrency} concurrent connections.
Based on the headroom, you could likely increase concurrency by ~3x before approaching SLO limits.

**Recommendations:**
- Current configuration meets all SLO targets with significant margin
- Consider running FIND_MAX_CONCURRENCY to find the true ceiling
- Or reduce warehouse size to save costs while still meeting SLOs
```

### SLO Failure Scenarios

When results exceed SLO targets:

```markdown
## ⚠️ SLO Violations Detected

**Your Targets vs. Actual Results:**

| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| P50 Latency | 50ms | 45ms | ✅ PASS |
| P95 Latency | 100ms | 156ms | ❌ **FAIL** (56% over) |
| P99 Latency | 200ms | 412ms | ❌ **FAIL** (106% over) |

**Analysis:**
At {concurrency} connections, your P95 and P99 latency exceed SLO targets.

**Recommendations:**
1. **Reduce concurrency:** Try {concurrency * 0.6} connections to stay within SLOs
2. **Upgrade warehouse:** Move from {current_size} to {larger_size}
3. **Optimize queries:** P99 >> P95 suggests occasional slow queries
4. **Add caching:** If read-heavy, consider caching layer for hot keys
```

### For Interactive Table Tests

When testing interactive tables/warehouses, provide specific guidance:

```markdown
## Interactive Table Performance Notes

**Observed Behavior:**
- Max sustainable concurrency: {max_concurrency} threads
- Optimal operating range: {optimal_range} threads
- QPS at saturation: {max_qps}

**Interactive Warehouse Characteristics:**
Interactive warehouses are optimized for low-latency, lower-concurrency workloads.

**If latency climbed quickly:**
- Interactive warehouses have limited queuing capacity
- Consider using standard warehouse for high-concurrency workloads
- Or deploy multiple interactive warehouses with load balancing

**Scaling Recommendations:**
| Concurrency Need | Recommendation |
|------------------|----------------|
| < 50 threads | Current XS Interactive is appropriate |
| 50-100 threads | Consider Small Interactive or XS Standard |
| 100-200 threads | Small/Medium Standard warehouse |
| > 200 threads | Medium+ Standard with MCW |

**Cost-Performance Trade-off:**
Interactive tables excel at sub-10ms P50 latency for operational workloads.
For batch/analytical workloads with higher concurrency, standard tables 
with standard warehouses are more cost-effective.
```

### Interactive Analysis Session

Guide user through analysis:

```markdown
## AI Analysis Session

Connected to: UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_ANALYST

**Your recent test:**
- Run ID: run-789xyz
- Table: DATABASE.SCHEMA.TABLE_NAME (HYBRID)
- Duration: 5 minutes
- Avg QPS: 1,247

---

Ask me anything about your benchmark results!

Examples:
- "What was the P99 latency?"
- "How did latency change over time?"
- "Compare this to yesterday's test"

Your question: _
```

## Option B: Dashboard View

Provide dashboard URL:

```markdown
## Dashboard

Open the live dashboard to visualize your results:

**URL:** http://localhost:8088/dashboard/run-789xyz

**Available Charts:**
- Latency over time (P50, P95, P99)
- Throughput (QPS) timeline
- Error rate breakdown
- Connection pool utilization
- Query type distribution

**Comparison Mode:** For multiple runs, use:
http://localhost:8088/dashboard/compare?runs=run-xyz1,run-xyz2,run-xyz3
```

## Option C: Direct SQL Queries

### Results Schema

Test results are stored in Snowflake:

```sql
-- Main metrics table
SELECT * FROM UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_METRICS
WHERE RUN_ID = 'run-789xyz'
ORDER BY TIMESTAMP;

-- Run metadata
SELECT * FROM UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_RUNS
WHERE RUN_ID = 'run-789xyz';

-- Per-second metrics
SELECT * FROM UNISTORE_BENCHMARK.TEST_RESULTS.METRICS_TIMESERIES
WHERE RUN_ID = 'run-789xyz'
ORDER BY TIMESTAMP;
```

### Common Analysis Queries

**Latency Percentiles:**
```sql
SELECT 
    RUN_ID,
    PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY LATENCY_MS) AS P50,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY LATENCY_MS) AS P95,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY LATENCY_MS) AS P99,
    MAX(LATENCY_MS) AS MAX_LATENCY
FROM UNISTORE_BENCHMARK.TEST_RESULTS.QUERY_LATENCIES
WHERE RUN_ID = 'run-789xyz'
GROUP BY RUN_ID;
```

**Throughput Over Time:**
```sql
SELECT 
    DATE_TRUNC('minute', TIMESTAMP) AS MINUTE,
    COUNT(*) AS QUERIES,
    AVG(LATENCY_MS) AS AVG_LATENCY_MS
FROM UNISTORE_BENCHMARK.TEST_RESULTS.QUERY_LATENCIES
WHERE RUN_ID = 'run-789xyz'
GROUP BY 1
ORDER BY 1;
```

**Compare Multiple Runs:**
```sql
SELECT 
    r.RUN_ID,
    r.CONFIG:warehouse_size::STRING AS WAREHOUSE_SIZE,
    m.AVG_QPS,
    m.P50_LATENCY_MS,
    m.P95_LATENCY_MS,
    m.ERROR_RATE
FROM UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_RUNS r
JOIN UNISTORE_BENCHMARK.TEST_RESULTS.RUN_SUMMARY m ON r.RUN_ID = m.RUN_ID
WHERE r.RUN_ID IN ('run-xyz1', 'run-xyz2', 'run-xyz3')
ORDER BY m.AVG_QPS DESC;
```

**Error Analysis:**
```sql
SELECT 
    ERROR_TYPE,
    COUNT(*) AS ERROR_COUNT,
    MIN(TIMESTAMP) AS FIRST_OCCURRENCE,
    MAX(TIMESTAMP) AS LAST_OCCURRENCE
FROM UNISTORE_BENCHMARK.TEST_RESULTS.ERRORS
WHERE RUN_ID = 'run-789xyz'
GROUP BY ERROR_TYPE
ORDER BY ERROR_COUNT DESC;
```

## Option D: Export Data

### CSV Export

```sql
-- Export to stage
COPY INTO @UNISTORE_BENCHMARK.TEST_RESULTS.EXPORT_STAGE/run-789xyz.csv
FROM (
    SELECT *
    FROM UNISTORE_BENCHMARK.TEST_RESULTS.METRICS_TIMESERIES
    WHERE RUN_ID = 'run-789xyz'
)
FILE_FORMAT = (TYPE = CSV HEADER = TRUE);

-- Get download URL
SELECT GET_PRESIGNED_URL(
    @UNISTORE_BENCHMARK.TEST_RESULTS.EXPORT_STAGE,
    'run-789xyz.csv'
);
```

### JSON Export

```sql
SELECT OBJECT_CONSTRUCT(
    'run_id', RUN_ID,
    'config', CONFIG,
    'summary', OBJECT_CONSTRUCT(
        'avg_qps', AVG_QPS,
        'p50_latency', P50_LATENCY_MS,
        'p95_latency', P95_LATENCY_MS,
        'error_rate', ERROR_RATE
    ),
    'timeseries', (
        SELECT ARRAY_AGG(OBJECT_CONSTRUCT(
            'timestamp', TIMESTAMP,
            'qps', QPS,
            'latency_ms', LATENCY_MS
        ))
        FROM UNISTORE_BENCHMARK.TEST_RESULTS.METRICS_TIMESERIES
        WHERE RUN_ID = r.RUN_ID
    )
) AS RESULT_JSON
FROM UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_RUNS r
WHERE RUN_ID = 'run-789xyz';
```

## Analysis Report Generation

For formal reporting, generate a summary:

```markdown
## Benchmark Report

### Test Configuration
- **Run ID:** run-789xyz
- **Date:** 2026-02-13 14:30:22 UTC
- **Duration:** 5 minutes
- **Table:** DATABASE.SCHEMA.TABLE_NAME (HYBRID)
- **Warehouse:** COMPUTE_WH_M (Medium)

### Workload
- Point Lookups: 50%
- Range Scans: 50%
- Concurrent Connections: 25

### Results Summary

| Metric | Value |
|--------|-------|
| Total Queries | 374,100 |
| Average QPS | 1,247 |
| P50 Latency | 12ms |
| P95 Latency | 45ms |
| P99 Latency | 89ms |
| Max Latency | 234ms |
| Error Rate | 0.00% |

### Key Findings

1. **Latency Performance:** P95 latency of 45ms is well within typical SLA requirements (<100ms)

2. **Throughput Stability:** QPS remained stable throughout the test with <5% variance

3. **No Errors:** Zero errors during the entire test duration indicates stable configuration

### Recommendations

- Current configuration is suitable for production workloads up to ~1,200 QPS
- For higher throughput, consider upgrading to Large warehouse
- P99 latency (89ms) suggests occasional slower queries - consider query optimization

### Cost Analysis

- Test Duration: 5.17 minutes
- Warehouse Cost: 4 credits/hour
- **Estimated Cost:** 0.34 credits
- **Cost per 1M queries:** ~0.91 credits
```

## Fallback: Manual Analysis

If Cortex Agent is unavailable:

```markdown
## Manual Analysis Mode

The Cortex Agent is not available. Here are your options:

1. **Use the SQL queries above** to analyze results directly

2. **Open the dashboard** for visual analysis:
   http://localhost:8088/dashboard/run-789xyz

3. **Export data** for analysis in your preferred tool

**Common issues with Cortex Agent:**
- Agent not deployed: Run `snow sql -f sql/schema/cortex_agent.sql`
- Insufficient permissions: Grant USAGE on the agent
- Service unavailable: Check Snowflake status
```

## Workflow Complete

After analysis, present the final summary with **required identifiers**:

```markdown
## Benchmark Complete

### Test Results

**Test 1: postgres-tpch-findmax**
- **Run ID:** d1f890a0-2ac3-4115-8a95-20fc4345b43c
- **Dashboard:** http://127.0.0.1:8000/dashboard/d1f890a0-2ac3-4115-8a95-20fc4345b43c
- **Peak QPS:** 552.2
- **Max Concurrency:** 65 threads

**Test 2: interactive-orders-findmax**
- **Run ID:** 034894f4-9349-4761-81e6-4ab7ed4189ba
- **Dashboard:** http://127.0.0.1:8000/dashboard/034894f4-9349-4761-81e6-4ab7ed4189ba
- **Peak QPS:** 105.6
- **Max Concurrency:** 15 threads

### Summary
- ✅ Requirements gathered
- ✅ Configuration generated
- ✅ Test executed successfully
- ✅ Results analyzed

**Results Location:** UNISTORE_BENCHMARK.TEST_RESULTS

---

What would you like to do next?

A) Run another benchmark with different parameters
B) Compare this run with previous tests
C) Export a formal report
D) Exit wizard
```

**⛔ REQUIRED in every summary:**
1. **Test Name** - Descriptive name for each test
2. **Run ID** - UUID for each test
3. **Dashboard URL** - `http://127.0.0.1:8000/dashboard/{run_id}`
4. **Key Metrics** - Peak QPS, max concurrency, etc.

## Error Handling

| Error | Resolution |
|-------|------------|
| Agent not found | Deploy agent with SQL DDL, or use direct SQL |
| Permission denied | Grant USAGE on agent to current role |
| No results found | Verify run_id, check if test completed |
| Query timeout | Use smaller time windows, add filters |
