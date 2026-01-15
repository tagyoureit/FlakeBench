-- ============================================================================
-- TEMPLATES TABLE
-- Stores test configuration templates for reuse
-- ============================================================================

CREATE TABLE IF NOT EXISTS TEST_TEMPLATES (
    -- Identity
    TEMPLATE_ID VARCHAR(36) PRIMARY KEY,
    TEMPLATE_NAME VARCHAR(255) NOT NULL,
    DESCRIPTION VARCHAR(1000),
    
    -- Configuration (stored as VARIANT JSON)
    CONFIG VARIANT NOT NULL,
    
    -- Metadata
    CREATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    UPDATED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
    CREATED_BY VARCHAR(255),
    
    -- Tags for categorization
    TAGS VARIANT,
    
    -- Usage tracking
    USAGE_COUNT INTEGER DEFAULT 0,
    LAST_USED_AT TIMESTAMP_NTZ
);

COMMENT ON TABLE TEST_TEMPLATES IS 'Stores test configuration templates for reuse and modification';
COMMENT ON COLUMN TEST_TEMPLATES.TEMPLATE_ID IS 'Unique identifier (UUID)';
COMMENT ON COLUMN TEST_TEMPLATES.TEMPLATE_NAME IS 'Human-readable template name';
COMMENT ON COLUMN TEST_TEMPLATES.CONFIG IS 'Full test configuration as JSON (matches TestScenario model)';
COMMENT ON COLUMN TEST_TEMPLATES.TAGS IS 'Optional tags for categorization (JSON object)';
COMMENT ON COLUMN TEST_TEMPLATES.USAGE_COUNT IS 'Number of times this template has been used';
COMMENT ON COLUMN TEST_TEMPLATES.LAST_USED_AT IS 'Last time this template was used to run a test';

-- ============================================================================
-- Template normalization (rerunnable)
--
-- NOTE: This project intentionally does NOT use a migrations system. This
-- update is idempotent and only rewrites rows that are NOT already CUSTOM.
-- ============================================================================

UPDATE TEST_TEMPLATES
SET
  CONFIG =
    OBJECT_INSERT(
      OBJECT_INSERT(
        OBJECT_INSERT(
          OBJECT_INSERT(
            OBJECT_INSERT(
              OBJECT_INSERT(
                OBJECT_INSERT(
                  OBJECT_INSERT(
                    OBJECT_INSERT(
                      CONFIG,
                      'workload_type', 'CUSTOM',
                      TRUE
                    ),
                    'custom_point_lookup_query', 'SELECT * FROM {table} WHERE id = ?',
                    TRUE
                  ),
                  'custom_range_scan_query', 'SELECT * FROM {table} WHERE id BETWEEN ? AND ? + 100 ORDER BY id LIMIT 100',
                  TRUE
                ),
                'custom_insert_query', 'INSERT INTO {table} (id, data, timestamp) VALUES (?, ?, CURRENT_TIMESTAMP)',
                TRUE
              ),
              'custom_update_query', 'UPDATE {table} SET data = ?, timestamp = CURRENT_TIMESTAMP WHERE id = ?',
              TRUE
            ),
            'custom_point_lookup_pct',
              CASE UPPER(COALESCE(CONFIG:workload_type::STRING, 'MIXED'))
                WHEN 'READ_ONLY' THEN 50
                WHEN 'WRITE_ONLY' THEN 0
                WHEN 'READ_HEAVY' THEN 40
                WHEN 'WRITE_HEAVY' THEN 10
                WHEN 'MIXED' THEN 25
                ELSE 25
              END,
            TRUE
          ),
          'custom_range_scan_pct',
            CASE UPPER(COALESCE(CONFIG:workload_type::STRING, 'MIXED'))
              WHEN 'READ_ONLY' THEN 50
              WHEN 'WRITE_ONLY' THEN 0
              WHEN 'READ_HEAVY' THEN 40
              WHEN 'WRITE_HEAVY' THEN 10
              WHEN 'MIXED' THEN 25
              ELSE 25
            END,
          TRUE
        ),
        'custom_insert_pct',
          CASE UPPER(COALESCE(CONFIG:workload_type::STRING, 'MIXED'))
            WHEN 'READ_ONLY' THEN 0
            WHEN 'WRITE_ONLY' THEN 70
            WHEN 'READ_HEAVY' THEN 15
            WHEN 'WRITE_HEAVY' THEN 60
            WHEN 'MIXED' THEN 35
            ELSE 35
          END,
        TRUE
      ),
      'custom_update_pct',
        CASE UPPER(COALESCE(CONFIG:workload_type::STRING, 'MIXED'))
          WHEN 'READ_ONLY' THEN 0
          WHEN 'WRITE_ONLY' THEN 30
          WHEN 'READ_HEAVY' THEN 5
          WHEN 'WRITE_HEAVY' THEN 20
          WHEN 'MIXED' THEN 15
          ELSE 15
        END,
      TRUE
    ),
  UPDATED_AT = CURRENT_TIMESTAMP()
WHERE UPPER(COALESCE(CONFIG:workload_type::STRING, 'MIXED')) <> 'CUSTOM';
