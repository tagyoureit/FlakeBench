# Analytical Workloads Implementation Plan

**Created:** 2026-02-16
**Status:** Draft
**Goal:** Add columnar-optimized workloads to demonstrate Snowflake's analytical advantages

## Problem Statement

The current FlakeBench implementation focuses on OLTP workloads:
- Point lookups (`SELECT * FROM t WHERE id = ?`)
- Range scans (`SELECT * FROM t WHERE id BETWEEN ? AND ?`)
- Single-row INSERT/UPDATE

These patterns favor **row-based storage** (Postgres, Hybrid Tables) because they:
- Access specific rows by primary key
- Benefit from index-based random access
- Require low-latency single-row operations

**Result:** Postgres consistently outperforms Snowflake Standard Tables, which is expected
but doesn't showcase Snowflake's columnar strengths.

## Solution Overview

Add **analytical workload types** that demonstrate columnar storage advantages:

| Workload Type | Description | Why Columnar Wins |
|---------------|-------------|-------------------|
| `AGGREGATION` | GROUP BY with SUM/COUNT/AVG | Scans only aggregated columns |
| `WINDOWED` | Window functions (ROW_NUMBER, SUM OVER) | Efficient partition processing |
| `ANALYTICAL_JOIN` | Star-schema fact-dimension joins | Broadcast joins, predicate pushdown |
| `WIDE_SCAN` | Scanning many columns | Columnar projection, compression |
| `APPROX_DISTINCT` | HyperLogLog cardinality | ~100x faster than exact COUNT |

### Key Design: Explicit Parameter Specifications

Unlike OLTP queries (where params are inferred from query_kind), analytical queries use
**explicit parameter specs** to enable:

- Multiple parameters per query (date range + dimension filters)
- Arbitrary granularity (hour/day/week/month/year)
- Combinatorial variety (e.g., 4 granularities × 365 dates × 5 regions = 7,300 unique combinations)
- Dependent parameters (end_date derived from start_date)

```yaml
# Example: Explicit parameter specification
parameters:
  - name: "granularity"
    type: "choice"
    values: ["day", "week", "month"]
  - name: "start_date"
    type: "date"
    strategy: "random_in_range"
    column: "order_date"
  - name: "region"
    type: "categorical"
    strategy: "sample_from_table"
    column: "region"
```

## Expected Outcomes

1. **Snowflake Standard Tables**: Should significantly outperform Postgres on analytical queries
2. **Hybrid Tables**: Should show balanced performance (row-optimized + columnar cache)
3. **Interactive Tables**: Test HTAP performance with mixed OLTP+OLAP

## Plan Structure

| File | Content |
|------|---------|
| `01-query-patterns.md` | SQL patterns that favor columnar storage |
| `02-architecture-changes.md` | High-level architecture with explicit parameter specs |
| `03-new-query-kinds.md` | Detailed executor implementation |
| `04-value-pools.md` | Parameter generation strategies & ColumnProfile |
| `05-yaml-config.md` | Template configuration with explicit parameters |
| `06-schema-requirements.md` | Table design for benchmarks |
| `07-metrics-tracking.md` | Analytics-specific metrics |
| `08-implementation-steps.md` | 4-phase execution plan (~5 days) |

## Success Criteria

- [ ] Explicit parameter specification system implemented (ParameterSpec, ColumnProfile, ParameterGenerator)
- [ ] 5+ new query kinds implemented (AGGREGATION, WINDOWED, etc.)
- [ ] YAML templates support explicit parameter specs for combinatorial variety
- [ ] Metrics track rows/sec, bytes/sec for analytical workloads
- [ ] Demo scenario shows 10x+ Snowflake advantage over Postgres
- [ ] Backward compatible with existing OLTP templates

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Column profiling slow | Cache profiles during setup, not per-query |
| Too many distinct values | Cap sample_values at configurable limit |
| Dependent param cycles | Validate DAG at parse time |
| Legacy compatibility | Implicit specs for existing query kinds |
| Long query times | Appropriate SLO definitions for OLAP |

## Related Documentation

- [Snowflake: Micro-partitions & Clustering](https://docs.snowflake.com/en/user-guide/tables-clustering-micropartitions)
- [Snowflake: Hybrid Tables](https://docs.snowflake.com/en/user-guide/tables-hybrid)
- [FlakeBench: Test Executor](../../../backend/core/test_executor.py)
