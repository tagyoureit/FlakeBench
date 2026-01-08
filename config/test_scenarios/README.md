# Test Scenario Templates

This directory contains YAML templates for predefined test scenarios.

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

### Key Sections:
1. **Template Metadata** (at top) - name, description, version, category
2. **Table configurations** - Schema, indexes, clustering
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

Load templates via the UI or API:
- UI: Configure Test page → Load Template dropdown
- API: `POST /api/test/from-template` with template name
