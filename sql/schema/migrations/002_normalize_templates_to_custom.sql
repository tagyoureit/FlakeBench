-- ============================================================================
-- 002_normalize_templates_to_custom.sql
--
-- Goal:
-- Normalize existing TEST_TEMPLATES.CONFIG rows so that workload definitions are
-- authoritative and idempotent:
-- - Persist workload_type = CUSTOM
-- - Persist canonical custom_*_query SQL templates (with {table} placeholder)
-- - Persist custom_*_pct weights derived from the prior workload_type preset
--
-- Notes:
-- - This is intentionally rerunnable.
-- - This only rewrites rows that are NOT already CUSTOM.
-- ============================================================================

USE DATABASE UNISTORE_BENCHMARK;
USE SCHEMA TEST_RESULTS;

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


