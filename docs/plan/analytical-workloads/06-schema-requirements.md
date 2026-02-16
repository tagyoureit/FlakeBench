# Schema Requirements for Analytical Benchmarks

Table design recommendations for meaningful columnar vs row-store comparisons.

## Current Test Tables

| Table | Columns | Rows | Best For |
|-------|---------|------|----------|
| `stress_test` | 4 | Small | Basic OLTP |
| `oltp_test` | 7 | Medium | OLTP workloads |
| `olap_test` | 8 | Large (10M) | Basic analytics |
| `mixed_test` | 10 | Medium | Mixed workloads |
| `sape_events_*` | 11 | Various | Event analytics |

## Recommended Analytical Schema

### Wide Fact Table (100+ columns)

Tests columnar projection efficiency - Snowflake scans only needed columns.

```sql
CREATE OR REPLACE TABLE analytics_fact_wide (
    -- Keys
    fact_id NUMBER PRIMARY KEY,
    date_key NUMBER,
    product_key NUMBER,
    customer_key NUMBER,
    geo_key NUMBER,
    
    -- Timestamps
    created_at TIMESTAMP_NTZ,
    updated_at TIMESTAMP_NTZ,
    
    -- Categorical (for GROUP BY)
    region VARCHAR(50),
    country VARCHAR(50),
    state VARCHAR(50),
    city VARCHAR(100),
    product_category VARCHAR(50),
    product_subcategory VARCHAR(50),
    customer_segment VARCHAR(50),
    sales_channel VARCHAR(50),
    payment_method VARCHAR(50),
    
    -- Metrics (for aggregations)
    quantity NUMBER,
    unit_price NUMBER(12,2),
    discount_pct NUMBER(5,2),
    revenue NUMBER(12,2),
    cost NUMBER(12,2),
    profit NUMBER(12,2),
    tax NUMBER(12,2),
    shipping NUMBER(12,2),
    
    -- Additional columns for "wide" testing
    metric_01 NUMBER, metric_02 NUMBER, metric_03 NUMBER, metric_04 NUMBER, metric_05 NUMBER,
    metric_06 NUMBER, metric_07 NUMBER, metric_08 NUMBER, metric_09 NUMBER, metric_10 NUMBER,
    metric_11 NUMBER, metric_12 NUMBER, metric_13 NUMBER, metric_14 NUMBER, metric_15 NUMBER,
    metric_16 NUMBER, metric_17 NUMBER, metric_18 NUMBER, metric_19 NUMBER, metric_20 NUMBER,
    
    attr_01 VARCHAR(100), attr_02 VARCHAR(100), attr_03 VARCHAR(100), attr_04 VARCHAR(100), attr_05 VARCHAR(100),
    attr_06 VARCHAR(100), attr_07 VARCHAR(100), attr_08 VARCHAR(100), attr_09 VARCHAR(100), attr_10 VARCHAR(100),
    attr_11 VARCHAR(100), attr_12 VARCHAR(100), attr_13 VARCHAR(100), attr_14 VARCHAR(100), attr_15 VARCHAR(100),
    attr_16 VARCHAR(100), attr_17 VARCHAR(100), attr_18 VARCHAR(100), attr_19 VARCHAR(100), attr_20 VARCHAR(100),
    
    -- JSON payload for flexibility
    extra_data VARIANT
) 
CLUSTER BY (created_at, region);
```

**Column count:** ~65 defined + expandable
**Target rows:** 50-100M for meaningful analytics

### Dimension Tables

```sql
-- Date dimension
CREATE TABLE dim_date (
    date_key NUMBER PRIMARY KEY,
    full_date DATE,
    calendar_year NUMBER,
    calendar_quarter NUMBER,
    calendar_month NUMBER,
    calendar_week NUMBER,
    day_of_week NUMBER,
    day_name VARCHAR(10),
    month_name VARCHAR(10),
    is_weekend BOOLEAN,
    is_holiday BOOLEAN
);

-- Product dimension
CREATE TABLE dim_product (
    product_key NUMBER PRIMARY KEY,
    product_id VARCHAR(50),
    product_name VARCHAR(200),
    product_category VARCHAR(50),
    product_subcategory VARCHAR(50),
    brand VARCHAR(100),
    supplier VARCHAR(100),
    unit_cost NUMBER(12,2)
);

-- Customer dimension
CREATE TABLE dim_customer (
    customer_key NUMBER PRIMARY KEY,
    customer_id VARCHAR(50),
    customer_name VARCHAR(200),
    customer_segment VARCHAR(50),
    customer_tier VARCHAR(20),
    signup_date DATE,
    email VARCHAR(200),
    region VARCHAR(50)
);

-- Geography dimension
CREATE TABLE dim_geography (
    geo_key NUMBER PRIMARY KEY,
    region VARCHAR(50),
    country VARCHAR(50),
    state VARCHAR(50),
    city VARCHAR(100),
    postal_code VARCHAR(20),
    latitude NUMBER(10,6),
    longitude NUMBER(10,6)
);
```

### High-Cardinality Table (for APPROX_COUNT_DISTINCT)

```sql
CREATE TABLE user_events (
    event_id NUMBER PRIMARY KEY,
    user_id NUMBER,            -- High cardinality: millions of unique values
    session_id VARCHAR(50),
    event_type VARCHAR(50),
    event_date TIMESTAMP_NTZ,
    page_url VARCHAR(500),
    referrer VARCHAR(500),
    device_type VARCHAR(20),
    browser VARCHAR(50),
    country VARCHAR(50)
)
CLUSTER BY (event_date, event_type);
```

**Target:** 10M+ unique user_ids for meaningful HLL testing.

## Data Generation

### Row Counts by Table Type

| Table Type | Minimum Rows | Recommended | Notes |
|------------|-------------|-------------|-------|
| Fact (wide) | 10M | 50-100M | More rows = bigger columnar advantage |
| Fact (narrow) | 5M | 20-50M | Still meaningful |
| Dimension | 100 - 100K | Varies | Based on cardinality |
| Events | 10M | 100M+ | High cardinality for HLL |

### Cardinality Guidelines

| Column Type | Target Cardinality | Purpose |
|-------------|-------------------|---------|
| region | 5-10 | Low cardinality GROUP BY |
| product_category | 20-50 | Medium cardinality |
| customer_id | 1M+ | High cardinality for COUNT DISTINCT |
| date (day) | 365+ | Time-series partitioning |

### Data Distribution

For meaningful benchmarks, ensure:

1. **Uniform date distribution** - Data spread across date range, not clustered
2. **Skewed categorical data** - Some regions/products have more data (realistic)
3. **Null handling** - Include NULL values in optional columns
4. **Outliers** - Include extreme values for robust testing

```sql
-- Example: Generate synthetic data with realistic distribution
INSERT INTO analytics_fact_wide
SELECT 
    SEQ8() AS fact_id,
    MOD(SEQ8(), 1000) + 1 AS date_key,  -- 1000 dates
    MOD(SEQ8(), 500) + 1 AS product_key, -- 500 products
    UNIFORM(1, 1000000, RANDOM()) AS customer_key, -- 1M customers
    MOD(SEQ8(), 100) + 1 AS geo_key,    -- 100 geos
    DATEADD(day, -UNIFORM(0, 365, RANDOM()), CURRENT_DATE()) AS created_at,
    CURRENT_TIMESTAMP() AS updated_at,
    CASE MOD(SEQ8(), 5) WHEN 0 THEN 'WEST' WHEN 1 THEN 'EAST' WHEN 2 THEN 'CENTRAL' WHEN 3 THEN 'SOUTH' ELSE 'NORTH' END AS region,
    -- ... additional columns
    UNIFORM(1, 100, RANDOM()) AS quantity,
    UNIFORM(1.00, 999.99, RANDOM())::NUMBER(12,2) AS unit_price,
    UNIFORM(0, 30, RANDOM()) AS discount_pct,
    (quantity * unit_price * (1 - discount_pct/100))::NUMBER(12,2) AS revenue
FROM TABLE(GENERATOR(ROWCOUNT => 50000000));  -- 50M rows
```

## Clustering Strategy

### For Columnar (STANDARD) Tables

```sql
-- Cluster by most common filter columns
ALTER TABLE analytics_fact_wide CLUSTER BY (created_at, region);
```

**Best for:**
- Date-range filters (WHERE date BETWEEN)
- Regional aggregations (GROUP BY region)
- Combined date + region queries

### For Hybrid Tables

```sql
-- Primary key for OLTP + secondary indexes
CREATE HYBRID TABLE analytics_fact_hybrid (
    fact_id NUMBER PRIMARY KEY,
    created_at TIMESTAMP_NTZ,
    region VARCHAR(50),
    -- ... other columns
    INDEX idx_date_region (created_at, region)
);
```

## Verification Queries

After data generation, verify schema readiness:

```sql
-- Check row counts
SELECT COUNT(*) FROM analytics_fact_wide;  -- Target: 50M+

-- Check cardinality
SELECT 
    COUNT(DISTINCT customer_key) AS unique_customers,
    COUNT(DISTINCT product_key) AS unique_products,
    COUNT(DISTINCT region) AS unique_regions,
    COUNT(DISTINCT DATE_TRUNC('day', created_at)) AS unique_days
FROM analytics_fact_wide;

-- Check clustering efficiency
SELECT SYSTEM$CLUSTERING_INFORMATION('analytics_fact_wide', '(created_at, region)');

-- Check table size
SELECT 
    TABLE_NAME,
    ROW_COUNT,
    BYTES / (1024*1024*1024) AS SIZE_GB
FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_NAME = 'ANALYTICS_FACT_WIDE';
```

## Migration Path

For existing FlakeBench installations:

1. Create new analytical tables alongside existing OLTP tables
2. Use separate database/schema for analytical workloads
3. Update YAML templates to reference new tables
4. No changes to existing OLTP scenarios

```
BENCHMARK_DB/
├── OLTP_SCHEMA/
│   ├── stress_test
│   ├── oltp_test
│   └── hybrid_test
└── ANALYTICS_SCHEMA/
    ├── analytics_fact_wide
    ├── dim_date
    ├── dim_product
    ├── dim_customer
    ├── dim_geography
    └── user_events
```
