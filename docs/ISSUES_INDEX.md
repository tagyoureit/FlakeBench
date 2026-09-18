# Issues Index
**Last updated:** 2026-09-17

## Open Issues

| ID | Severity | Component | Title | Date | File |
|---|---|---|---|---|---|
| ISSUE-002 | Low | history_compare.html | Debug alignment text visible in Deep Compare UI | 2026-03-20 | ISSUES.md |
| ISSUE-003 | Medium | test_results.py / chart_procedures.sql | Detailed Latency Breakdown shows empty data | 2026-03-20 | ISSUES.md |
| ISSUE-005 | Medium | snowflake_pool.py | Pool returns empty list on network error, masking failures | 2026-09-01 | ISSUES.md |

## Completed Issues

| ID | Severity | Component | Title | Resolved | File |
|---|---|---|---|---|---|
| ISSUE-001 | Medium | dashboard.html | Worker Details chart empty during live runs | 2026-03-13 | ISSUES_COMPLETED.md |
| ISSUE-004 | Medium | table_managers/ + test_executor.py | Table setup failure reports generic message, hiding real cause | 2026-09-01 | ISSUES_COMPLETED.md |
| ISSUE-006 | Medium | css/input.css (toast) | Toast close button barely visible, pushed outside card on long messages | 2026-09-01 | ISSUES_COMPLETED.md |
| ISSUE-007 | High | templates_modules/config_normalizer.py | Template save accepts SQL whose shape does not match its query kind | 2026-09-15 | ISSUES_COMPLETED.md |
| ISSUE-008 | High | templates.py / error_handling.py | Config validation errors surface as a generic 500, losing the message | 2026-09-15 | ISSUES_COMPLETED.md |
| ISSUE-009 | Medium | templates.py (create_template) | create_template re-wraps deliberate HTTPExceptions as 500 | 2026-09-15 | ISSUES_COMPLETED.md |
| ISSUE-010 | High | templates.py (_extract_placeholder_columns) | Quoted identifiers break GENERIC_SQL placeholder column extraction | 2026-09-15 | ISSUES_COMPLETED-2.md |
| ISSUE-011 | Medium | templates.py (prepare_ai_template) | prepare reports success when placeholders yield no parameters | 2026-09-15 | ISSUES_COMPLETED-2.md |
| ISSUE-012 | High | warehouses.py / display.js / configure.html | Interactive warehouses displayed a fabricated "Gen 1" generation | 2026-09-16 | ISSUES_COMPLETED-2.md |
| ISSUE-013 | Medium | warehouses.py / display.js / configure.html | Standard warehouses with unset generation were reported as Gen1 | 2026-09-16 | ISSUES_COMPLETED-2.md |
| ISSUE-014 | Low | warehouses.py | Authoritative `generation` column from SHOW WAREHOUSES was never read | 2026-09-16 | ISSUES_COMPLETED-2.md |
| ISSUE-015 | Low | display.js (formatWarehouseOption) | Adaptive warehouses rendered as "Gen1" in dashboard warehouse label | 2026-09-16 | ISSUES_COMPLETED-2.md |
| ISSUE-016 | High | configure.html (reloadTemplate / _saveTemplate) | Run reports "unsaved changes" immediately after a successful Update | 2026-09-17 | ISSUES_COMPLETED-2.md |
| ISSUE-017 | Medium | configure.html (reloadTemplate) | Undefined `templateId` threw a swallowed ReferenceError, aborting reload | 2026-09-17 | ISSUES_COMPLETED-2.md |
