# Test Scenario Templates

This directory contains YAML templates for predefined test scenarios.

**Important:** The app no longer creates tables. These templates assume the
referenced table/view already exists. Any schema/index/clustering sections
are informational only; runtime introspects the selected object schema from
the database.

## Template Structure

Each YAML file follows a standard structure with **template metadata at the top**:

```yaml
# ============================================================================
# TEMPLATE METADATA
# ============================================================================
name: "Template Name"
description: "Description of what this template tests"
version: "1.0"
category: "CATEGORY"

# ============================================================================
# Template Description
# Additional context and notes
# ============================================================================

# Table configurations
table:
  ...

# Workload specifications
workload:
  ...

# Load patterns
load_pattern:
  ...

# Performance targets
test:
  targets:
    ...
```

### Key Sections

1. **Template Metadata** (at top) - name, description, version, category
2. **Table selection** - Database/schema/table name (must already exist)
3. **Workload specifications** - Operation types and distributions
4. **Load patterns** - How load varies over time
5. **Performance targets** - Expected metrics and SLAs

## Available Templates

- `oltp_simple.yaml` - Basic transactional workload
- `olap_analytics.yaml` - Analytical query workload
- `mixed_workload.yaml` - Combined OLTP + OLAP
- `high_concurrency.yaml` - Stress test with many connections
- `bulk_loading.yaml` - Data ingestion performance test
- `r180_poc.yaml` - R180 POC scenario (SAPE events processing)

## Usage

These YAML files are **reference examples**. The current app UI uses templates
stored in Snowflake (`TEST_TEMPLATES`) via the `/templates` and `/configure`
pages.

If you want to programmatically load YAML templates, use `backend.core.template_loader.TemplateLoader`
directly in Python (note: it will still require the target table/view to exist).
