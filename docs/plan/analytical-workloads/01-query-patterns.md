# Analytical Query Patterns

SQL patterns that demonstrate columnar storage advantages over row-based systems.

## Why Columnar Excels

| Factor | Columnar (Snowflake) | Row-Based (Postgres) |
|--------|---------------------|----------------------|
| Column projection | Scans only needed columns | Scans entire rows |
| Compression | Per-column encoding (10-100x) | Row-level compression |
| Vectorized execution | SIMD on column batches | Row-at-a-time |
| Parallel aggregation | Partition across nodes | Limited parallelism |

## Pattern 1: Full-Table Aggregation

**Best for:** Revenue reports, KPI dashboards, summary statistics

```sql
-- Snowflake scans only 3 columns from 100+ column table
SELECT 
    DATE_TRUNC('month', order_date) AS month,
    region,
    SUM(amount) AS total_revenue,
    COUNT(*) AS order_count,
    AVG(quantity) AS avg_quantity
FROM {table}
WHERE order_date >= ?
GROUP BY 1, 2
ORDER BY 1, 2;
```

**Parameters:**
- `?` = date cutoff (e.g., 30/90/365 days ago)

**Columnar advantage:** Only aggregated columns scanned; row-store reads entire rows.

## Pattern 2: Multi-Level Aggregation (ROLLUP/CUBE)

**Best for:** Hierarchical reports, drill-down analytics

```sql
-- ROLLUP: Region > Product > Grand Total
SELECT 
    region,
    product_category,
    SUM(revenue) AS total_revenue,
    COUNT(*) AS transactions,
    GROUPING_ID(region, product_category) AS agg_level
FROM {table}
WHERE order_date BETWEEN ? AND ?
GROUP BY ROLLUP(region, product_category)
ORDER BY agg_level, region NULLS LAST, product_category NULLS LAST;
```

**Parameters:**
- `?` = start_date
- `?` = end_date

**Columnar advantage:** Single-pass hierarchical aggregation; row-store needs multiple queries.

## Pattern 3: Window Functions

**Best for:** Running totals, rankings, time-series analysis

```sql
-- Running total + rolling average
SELECT 
    order_date,
    customer_id,
    amount,
    SUM(amount) OVER (
        PARTITION BY customer_id 
        ORDER BY order_date
        ROWS UNBOUNDED PRECEDING
    ) AS cumulative_spend,
    AVG(amount) OVER (
        PARTITION BY customer_id 
        ORDER BY order_date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) AS rolling_7day_avg
FROM {table}
WHERE order_date BETWEEN ? AND ?
ORDER BY customer_id, order_date;
```

**Parameters:**
- `?` = start_date
- `?` = end_date

**Columnar advantage:** Efficient partition-based processing with columnar caching.

## Pattern 4: Ranking with QUALIFY

**Best for:** Top-N per group, deduplication

```sql
-- Top 10 orders per customer (Snowflake-native)
SELECT 
    customer_id,
    order_id,
    amount,
    order_date,
    ROW_NUMBER() OVER (
        PARTITION BY customer_id 
        ORDER BY amount DESC
    ) AS rank
FROM {table}
WHERE order_date >= ?
QUALIFY rank <= 10;
```

**Parameters:**
- `?` = date cutoff

**Columnar advantage:** QUALIFY eliminates subquery; vectorized ranking.

## Pattern 5: Approximate Count Distinct

**Best for:** Unique user counts, cardinality estimation

```sql
-- HyperLogLog: ~100x faster than exact, ~1.6% error
SELECT 
    DATE_TRUNC('day', event_date) AS day,
    event_type,
    APPROX_COUNT_DISTINCT(user_id) AS unique_users,
    COUNT(*) AS total_events
FROM {table}
WHERE event_date BETWEEN ? AND ?
GROUP BY 1, 2
ORDER BY 1, 2;
```

**Parameters:**
- `?` = start_date
- `?` = end_date

**Columnar advantage:** Snowflake's HLL is highly optimized; Postgres lacks native HLL.

## Pattern 6: Star-Schema Join

**Best for:** Fact-dimension analytics, data warehousing

```sql
-- Fact table uses {table}, dimensions use fully-qualified names
SELECT 
    d.calendar_year,
    d.calendar_quarter,
    p.product_category,
    g.region,
    SUM(f.quantity) AS total_qty,
    SUM(f.revenue) AS total_revenue
FROM {table} f
JOIN DIM_DATE d ON f.date_key = d.date_key
JOIN DIM_PRODUCT p ON f.product_key = p.product_key  
JOIN DIM_GEOGRAPHY g ON f.geo_key = g.geo_key
WHERE d.calendar_year = ?
GROUP BY 1, 2, 3, 4;
```

**Parameters:**
- `?` = year (e.g., 2024)

**Columnar advantage:** Broadcast joins for small dimensions; predicate pushdown.

## Pattern 7: Wide Column Scan

**Best for:** Testing columnar projection efficiency

```sql
-- Select many columns, test column pruning
SELECT 
    col1, col2, col3, col4, col5,
    col6, col7, col8, col9, col10,
    SUM(metric1) AS sum1,
    SUM(metric2) AS sum2,
    AVG(metric3) AS avg3
FROM {table}
WHERE created_at BETWEEN ? AND ?
GROUP BY 1, 2, 3, 4, 5, 6, 7, 8, 9, 10;
```

**Parameters:**
- `?` = start_date
- `?` = end_date

**Columnar advantage:** Even with 10 GROUP BY columns, only scans 13 columns total.

## Postgres Equivalents

For fair comparison, create Postgres versions:
- Replace `QUALIFY` with subquery + `WHERE rank <= N`
- Replace `APPROX_COUNT_DISTINCT` with `COUNT(DISTINCT ...)` or pg_hll extension
- Use `$1, $2, $3` parameter placeholders instead of `?`

## Parameter Requirements

| Pattern | Parameters Needed | Pool Type |
|---------|------------------|-----------|
| Aggregation | date_cutoff | RANGE |
| ROLLUP/CUBE | start_date, end_date | RANGE |
| Window | start_date, end_date | RANGE |
| Ranking | date_cutoff | RANGE |
| Approx Distinct | start_date, end_date | RANGE |
| Star-Schema | year or date_range | RANGE/SCALAR |
| Wide Scan | start_date, end_date | RANGE |

**Key insight:** Analytical queries primarily need **date range** parameters, not key IDs.
