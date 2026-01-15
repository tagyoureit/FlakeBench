-- ============================================================================
-- TEMPLATE VALUE POOLS
-- Stores large sampled value pools or sampled rows for a TEST_TEMPLATE.
--
-- Goal: keep TEST_TEMPLATES.CONFIG small while supporting massive scale
-- (large sample pools for high concurrency test execution).
--
-- Notes:
-- - No PK/FK constraints (Snowflake doesn't enforce them unless Hybrid tables).
-- - Row-per-item design scales to millions+ of pooled values/rows.
-- - Intended to be generated once during template creation and reused on runs.
-- ============================================================================

CREATE TABLE IF NOT EXISTS TEMPLATE_VALUE_POOLS (
    POOL_ID VARCHAR(36) NOT NULL,          -- UUID for a generated pool set
    TEMPLATE_ID VARCHAR(36) NOT NULL,      -- TEST_TEMPLATES.TEMPLATE_ID (no FK)

    POOL_KIND VARCHAR(50) NOT NULL,        -- e.g. KEY, RANGE, ROW, COLUMN
    COLUMN_NAME VARCHAR(255),              -- for column-specific pools; else NULL
    SEQ INTEGER NOT NULL,                  -- stable ordering within a pool

    VALUE VARIANT,                         -- scalar or object (row payload)
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
)
CLUSTER BY (TEMPLATE_ID, POOL_ID, POOL_KIND);

COMMENT ON TABLE TEMPLATE_VALUE_POOLS IS 'Large sampled value pools or sampled rows for templates (separate from TEST_TEMPLATES.CONFIG).';
COMMENT ON COLUMN TEMPLATE_VALUE_POOLS.POOL_ID IS 'Pool set UUID (supports regenerating pools without overwrite).';
COMMENT ON COLUMN TEMPLATE_VALUE_POOLS.POOL_KIND IS 'Pool type (KEY/RANGE/ROW/COLUMN).';
COMMENT ON COLUMN TEMPLATE_VALUE_POOLS.VALUE IS 'Scalar value or row payload stored as VARIANT.';




