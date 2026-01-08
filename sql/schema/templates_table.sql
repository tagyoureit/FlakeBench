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
