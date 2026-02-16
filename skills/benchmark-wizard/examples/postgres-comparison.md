# Example: Postgres Table Warehouse Comparison

## Scenario

Compare Postgres table performance across different warehouse sizes to determine optimal cost/performance tradeoff.

## Prerequisites

- Backend running: `uv run python -m backend.main`
- Postgres connection stored via `/api/connections`
- Target table exists: `BENCHMARK_DB.PUBLIC.ORDERS`

## Step 1: Requirements Gathering

**User prompt:**
```
Help me benchmark my Postgres table to find the best warehouse size
```

**Wizard interaction:**

```markdown
Q: What type of table do you want to benchmark?
A: C) POSTGRES table

Q: What is the fully qualified table name?
A: BENCHMARK_DB.PUBLIC.ORDERS

Q: What's your primary goal?
A: A) Measure latency at a specific load level (CONCURRENCY mode)
   (Selected because we want fair comparison across warehouse sizes)

Q: What type of queries will you run?
A: A) Point lookups only (SELECT by primary key)

Q: How many concurrent connections?
A: B) Medium load (25 connections)

Q: How long should the test run?
A: B) Standard test (5 minutes)

Q: Which warehouse size?
A: E) Compare multiple sizes
   → Selected: X-Small, Small, Medium
```

**Gathered requirements:**
```json
{
  "table_type": "POSTGRES",
  "target_table": "BENCHMARK_DB.PUBLIC.ORDERS",
  "load_mode": "CONCURRENCY",
  "workload_mix": {
    "point_lookup_pct": 100,
    "range_scan_pct": 0,
    "insert_pct": 0,
    "update_pct": 0
  },
  "concurrent_connections": 25,
  "duration_seconds": 300,
  "warmup_seconds": 10,
  "warehouse_sizes": ["X-Small", "Small", "Medium"],
  "comparison_mode": true
}
```

## Step 2: Configuration Generation

**Wizard generates 3 configurations:**

### X-Small Configuration
```json
{
  "template_name": "postgres-orders-xsmall-20260213",
  "config": {
    "table_type": "POSTGRES",
    "database": "BENCHMARK_DB",
    "schema": "PUBLIC",
    "table_name": "ORDERS",
    "connection_id": "pg-orders-conn",
    
    "load_mode": "CONCURRENCY",
    "concurrent_connections": 25,
    "duration_seconds": 300,
    "warmup_seconds": 10,
    
    "workload_type": "CUSTOM",
    "custom_point_lookup_pct": 100,
    "custom_range_scan_pct": 0,
    "custom_insert_pct": 0,
    "custom_update_pct": 0,
    
    "custom_point_lookup_sql": "SELECT * FROM {table} WHERE order_id = $1",
    
    "warehouse_name": "COMPUTE_WH_XS",
    "warehouse_size": "X-Small"
  },
  "tags": {
    "source": "benchmark-wizard",
    "comparison": "warehouse-size",
    "variant": "X-Small"
  }
}
```

### Small Configuration
```json
{
  "template_name": "postgres-orders-small-20260213",
  "config": {
    "warehouse_name": "COMPUTE_WH_S",
    "warehouse_size": "Small"
    // ... other fields same as above
  }
}
```

### Medium Configuration
```json
{
  "template_name": "postgres-orders-medium-20260213",
  "config": {
    "warehouse_name": "COMPUTE_WH_M",
    "warehouse_size": "Medium"
    // ... other fields same as above
  }
}
```

**Wizard summary:**
```markdown
## Comparison Test Configuration

**Target:** BENCHMARK_DB.PUBLIC.ORDERS (POSTGRES)
**Mode:** CONCURRENCY (25 connections)
**Duration:** 5 minutes each
**Workload:** 100% point lookups

| Variant | Warehouse | Est. Cost |
|---------|-----------|-----------|
| 1 | X-Small (1 cr/hr) | 0.08 cr |
| 2 | Small (2 cr/hr) | 0.17 cr |
| 3 | Medium (4 cr/hr) | 0.33 cr |

**Total Estimated Cost:** 0.58 credits
**Total Duration:** ~15 minutes (sequential execution)

Proceed? [Y/n]
```

## Step 3: Execution

**User:** `Y`

**Wizard creates and executes tests sequentially:**

```markdown
## Comparison Test Execution

### Test 1/3: X-Small Warehouse

Creating template... ✓
Creating run... ✓
Running preflight checks... ✓ (no warnings)
Starting test... ✓

**Run ID:** run-xs-789
**Dashboard:** http://localhost:8088/dashboard/run-xs-789

Progress: [████████████████████] 100%
Status: COMPLETED

Results:
- Avg QPS: 312
- P95 Latency: 156ms

---

### Test 2/3: Small Warehouse

Creating template... ✓
Creating run... ✓
Starting test... ✓

**Run ID:** run-s-790
**Dashboard:** http://localhost:8088/dashboard/run-s-790

Progress: [████████████████████] 100%
Status: COMPLETED

Results:
- Avg QPS: 589
- P95 Latency: 84ms

---

### Test 3/3: Medium Warehouse

**Run ID:** run-m-791
Progress: [████████████████████] 100%
Status: COMPLETED

Results:
- Avg QPS: 1,102
- P95 Latency: 47ms

---

## All Tests Completed

| Warehouse | QPS | P95 Latency | Cost/hr | QPS/Credit |
|-----------|-----|-------------|---------|------------|
| X-Small | 312 | 156ms | 1 cr | 312 |
| Small | 589 | 84ms | 2 cr | 295 |
| Medium | 1,102 | 47ms | 4 cr | 276 |

Ready to analyze results?
```

## Step 4: Analysis

**User:** `A) Analyze with Cortex Agent`

**Wizard connects to agent:**
```markdown
## AI Analysis Session

Connected to: UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_ANALYST

Run IDs: run-xs-789, run-s-790, run-m-791
```

**User:** "Which warehouse gives the best cost/performance ratio?"

**Agent response:**
```markdown
## Cost/Performance Analysis

Based on your comparison tests, here's the analysis:

### QPS per Credit (Higher is Better)

| Warehouse | QPS | Credits/hr | QPS per Credit |
|-----------|-----|------------|----------------|
| X-Small | 312 | 1 | **312** |
| Small | 589 | 2 | 295 |
| Medium | 1,102 | 4 | 276 |

### Latency Analysis

| Warehouse | P50 | P95 | P99 |
|-----------|-----|-----|-----|
| X-Small | 78ms | 156ms | 234ms |
| Small | 42ms | 84ms | 126ms |
| Medium | 23ms | 47ms | 72ms |

### Recommendation

**Best Cost Efficiency:** X-Small (312 QPS/credit)
- Best for: Budget-conscious workloads, dev/test
- Caveat: P95 latency of 156ms may exceed some SLAs

**Best for Production:** Small
- Good balance of cost (295 QPS/credit) and latency (84ms P95)
- Recommended for: Most production workloads with <100ms P95 SLA

**Best for Low Latency:** Medium
- Required if: P95 SLA < 50ms
- 47ms P95 provides headroom for variance

### Break-Even Analysis

- Small becomes more cost-effective than X-Small when you need > ~400 QPS
- Medium becomes more cost-effective than Small when you need > ~800 QPS
```

**User:** "What if I need to handle 1000 QPS with P95 < 100ms?"

**Agent response:**
```markdown
## Recommendation for 1000 QPS @ P95 < 100ms

Based on your tests:

| Warehouse | Can Achieve 1000 QPS? | P95 @ 1000 QPS (estimated) |
|-----------|----------------------|---------------------------|
| X-Small | ❌ No (max 312 QPS) | N/A |
| Small | ❌ Marginal (589 QPS) | ~140ms (exceeds SLA) |
| Medium | ✅ Yes (1102 QPS) | **~47ms** |

### Recommendation: Medium Warehouse

- Achieved 1,102 QPS in testing (10% headroom above target)
- P95 latency of 47ms well within 100ms SLA
- Cost: 4 credits/hour = $0.33/hour at standard pricing

### Alternative: Multi-Cluster

If cost is a concern, consider:
- Small warehouse with 2 clusters (Standard scaling policy)
- Estimated: ~1,000 QPS at 3-4 credits/hour
- May have slightly higher latency variance

Would you like me to run a test with multi-cluster configuration?
```

## Final Summary

```markdown
## Benchmark Complete

### Test Summary
- Table: BENCHMARK_DB.PUBLIC.ORDERS (POSTGRES)
- Tests Run: 3 (X-Small, Small, Medium)
- Total Duration: 15m 30s
- Total Cost: 0.58 credits

### Key Findings
1. X-Small: Best QPS/credit but high latency (156ms P95)
2. Small: Best balance for most production workloads
3. Medium: Required for <50ms P95 or >800 QPS

### Recommended Configuration
For 1000 QPS @ P95 < 100ms: **Medium warehouse**

### Run IDs for Reference
- X-Small: run-xs-789
- Small: run-s-790
- Medium: run-m-791

### Next Steps
A) Export full report
B) Run additional tests (Large warehouse, multi-cluster)
C) Apply recommendation to production
D) Exit wizard
```

## Commands Used

```bash
# Create templates
curl -X POST localhost:8088/api/templates \
  -H 'Content-Type: application/json' \
  -d '{"template_name": "postgres-orders-xsmall-20260213", ...}'

# Create runs
curl -X POST localhost:8088/api/runs \
  -H 'Content-Type: application/json' \
  -d '{"template_id": "tmpl-xs-123"}'

# Start runs
curl -X POST localhost:8088/api/runs/run-xs-789/start

# Check status
curl localhost:8088/api/runs/run-xs-789

# Query results
cortex analyst query "Compare warehouse performance" \
  --agent=UNISTORE_BENCHMARK.TEST_RESULTS.BENCHMARK_ANALYST
```

## Troubleshooting

| Issue | Resolution |
|-------|------------|
| Postgres connection failed | Verify connection_id in `/api/connections` |
| Low QPS on X-Small | Expected - small warehouse has limited compute |
| High latency variance | Check for cold start, increase warmup time |
| Test failed mid-run | Check warehouse auto-suspend settings |
