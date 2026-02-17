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

Add analytical coverage with a **UI-based configuration experience** and a
**simplified runtime query model**:

| Query Kind | Role | Why it exists |
|------------|------|---------------|
| `POINT_LOOKUP` | OLTP shortcut | Existing fast path and baseline comparability |
| `RANGE_SCAN` | OLTP shortcut | Existing range-read baseline |
| `INSERT` | OLTP shortcut | Existing write shortcut |
| `UPDATE` | OLTP shortcut | Existing write shortcut |
| `GENERIC_SQL` | Arbitrary SQL (READ or WRITE) | Covers analytical SQL patterns without adding more runtime enums |

`GENERIC_SQL` can represent analytical patterns such as aggregation, windowing,
joins, rollups/cubes, and approximate cardinality directly in SQL text. Those
are SQL patterns, not dedicated runtime kinds.

### Key Design: SQL-First with AI Assistance

Users configure analytical queries through a UI workflow:

```
1. Select tables     → User picks tables to include (supports multi-table JOINs)
2. Describe intent   → Natural language: "Analyze sales by region and time"
3. AI generates SQL  → SQL with ? placeholders, user can edit/regenerate
4. Map parameters    → For each ?, select table.column and generation strategy
5. Prepare           → System profiles only the referenced columns
```

**Why SQL-first:**
- Supports multi-table JOINs naturally (dimensions + fact tables)
- Profiles only columns actually used
- User has full context when mapping parameters

### API and Storage Decisions (Locked)

- **No endpoint aliases:** use one canonical API contract and avoid duplicate route surfaces for the same behavior.
- **Catalog-first discovery:** table and schema metadata stay under existing `catalog` endpoints.
- **Template-scoped actions:** SQL generation, SQL validation, and column profiling stay under template/AI workflow endpoints.
- **Hybrid OLAP metrics storage:** keep stable first-class result columns for dashboards/SLOs, and store kind-specific/extensible metrics in a `VARIANT` payload.

### Inherited Benchmark Controls (Locked by Existing Runner)

This expansion inherits benchmark controls that already exist in the baseline app
and template model. They are not redesigned here, but are now explicitly part of
the OLAP contract:

- Cache policy controls (result cache behavior, reuse controls)
- Warmup and measurement phase controls (cold/warm execution modes)
- Repeat/trial controls (multiple runs with fixed/randomized seeds)
- Existing load modes and scheduler behavior (CONCURRENCY, QPS, FIND_MAX_CONCURRENCY)

Implementation note: this plan only adds OLAP-specific semantics on top of those
controls, and does not replace baseline runner behavior.

### Parameter Generation Strategies

| Strategy | Description | Use Case |
|----------|-------------|----------|
| `choice` | Pick from explicit list | Granularity (day/week/month) |
| `random_in_range` | Random in column min/max | Date filters |
| `sample_from_table` | Random from distinct values | Categorical dimensions |
| `weighted_sample` | Frequency-weighted random | Realistic distributions |
| `offset_from_previous` | Relative to prior param | Date range end |
| `sample_list` | Multiple values for IN clause | Multi-select filters |

**Combinatorial variety:** Multiple parameters create thousands of unique queries
(e.g., 4 granularities × 365 dates × 6 offsets × 5 regions = 43,800 combinations)

### Mix Precision Contract

Workload mixing remains percentage-based, but with two-decimal precision:

- `weight_pct` supports `0.00` to `100.00`
- Total weight across all configured queries must equal `100.00`
- Precision is `0.01%` (basis-point style scheduling)

This supports very skewed mixes such as roughly `10000:1` read:write while still
using percentage-based config.

## Expected Outcomes

1. **Snowflake Standard Tables**: Should significantly outperform Postgres on analytical queries
2. **Hybrid Tables**: Should show balanced performance (row-optimized + columnar cache)
3. **Interactive Tables**: Test HTAP performance with mixed OLTP+OLAP

## Plan Structure

| File | Content |
|------|---------|
| `01-query-patterns.md` | SQL patterns that favor columnar storage |
| `02-architecture-changes.md` | Architecture with UI flow and components |
| `03-new-query-kinds.md` | Query kind constants and executor changes |
| `04-value-pools.md` | Parameter generation and column profiling |
| `05-ui-config.md` | **UI workflow and component specifications** |
| `06-schema-requirements.md` | Table design for benchmarks |
| `07-metrics-tracking.md` | Metrics, **history storage, and comparison** |
| `08-implementation-steps.md` | 8-phase implementation plan |
| `09-methodology-and-realism.md` | Correctness gate, methodology contract, realism matrix |

## Success Criteria

- [ ] UI-based analytical query builder (no manual YAML)
- [ ] AI-assisted SQL generation from natural language
- [ ] Multi-table JOIN support with column profiling
- [ ] Runtime query model supports shortcuts + `GENERIC_SQL` with explicit `operation_type`
- [ ] Multiple `GENERIC_SQL` entries can be mixed with OLTP shortcuts in one test
- [ ] Combinatorial parameter variety (1000s of unique queries)
- [ ] **Compatible with all load modes (CONCURRENCY, QPS, FIND_MAX_CONCURRENCY)**
- [ ] **History storage with hybrid OLAP metrics (core columns + VARIANT details)**
- [ ] **Shallow and deep comparison for OLAP queries**
- [ ] **Pre-flight correctness gate for OLAP templates (including approximate-cardinality tolerance checks)**
- [ ] **Methodology metadata recorded for repeatability and confidence analysis**
- [ ] **Realism profiles supported (baseline, skew, NULL-heavy, late-arriving, selectivity bands)**
- [ ] Demonstrated and explainable performance deltas between engines under defined scenarios
- [ ] Backward compatible with existing OLTP templates

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| AI generates invalid SQL | Validate syntax before accepting, allow manual edit |
| Multi-table profiling slow | Profile only referenced columns |
| Complex UI | Progressive disclosure, sensible defaults |
| Legacy compatibility | Existing templates work unchanged |
| Invalid benchmark conclusions due to methodology drift | Persist inherited run controls + trial metadata in every test result |
| Fast but incorrect analytical query templates | Add pre-flight correctness gate before performance runs |

## Future Enhancements

The following capabilities are **out of scope** for the initial implementation but
should be considered for future iterations:

### Additional Query Patterns

| Pattern | Description | Use Case |
|---------|-------------|----------|
| `SESSIONIZATION` | User session windowing with gap detection | Funnel analysis, user journey analytics |
| `FUNNEL_ANALYSIS` | Sequential event matching (A → B → C) | Conversion tracking, drop-off analysis |
| `APPROX_PERCENTILE` | HyperLogLog-style approximate quantiles | P95/P99 latency from event streams |
| `VARIANT_QUERY` | Semi-structured JSON path extraction | Event payload filtering, feature flag queries |
| `LATERAL_FLATTEN` | Nested array expansion | JSON array analytics |

### Throughput-Based SLOs

The current SLO system evaluates **latency thresholds** (p95_ms, p99_ms). Future
enhancement could add **throughput-based SLOs** for analytical workloads:

```python
# Example: not yet implemented
"GENERIC_SQL:aggregation": {
    "p95_ms": 5000,
    "min_rows_per_sec": 100000,   # Throughput floor
    "min_bytes_per_sec": 10_000_000,  # I/O throughput floor
}
```

This would allow FIND_MAX_CONCURRENCY to stop scaling when throughput degrades,
not just when latency exceeds thresholds.

### Row-Limit Based Load Control

The current load system uses **percentage-based** query distribution with 2-decimal
precision (e.g., 70.00% POINT_LOOKUP, 29.99% GENERIC_SQL(READ), 0.01% UPDATE).
Future enhancement could add **row-limit** or
**operation-count** controls:

```yaml
# Example: not yet implemented
load_control:
  mode: ROW_LIMIT
  aggregation_max_rows_per_minute: 10_000_000
  point_lookup_target_ops_per_second: 500
```

This would enable more precise resource budgeting for mixed HTAP workloads.

## Related Documentation

- [Snowflake: Micro-partitions & Clustering](https://docs.snowflake.com/en/user-guide/tables-clustering-micropartitions)
- [Snowflake: Hybrid Tables](https://docs.snowflake.com/en/user-guide/tables-hybrid)
- [FlakeBench: Test Executor](../../../backend/core/test_executor.py)
