# Example: Enhance Existing Rule

This example shows the complete workflow when conversation analysis leads to enhancing an existing rule.

## Scenario

You worked on a Python project using PostgreSQL and SQLAlchemy. The agent didn't know about connection pooling best practices, leading to connection exhaustion issues.

## Input

```markdown
Use rule-learner skill.

conversation_summary: "Struggled with psycopg2 connection pooling for 
Snowflake. Agent created new SQLAlchemy engine for every request, causing 
connection exhaustion after 10 requests. Had to manually configure pool_size=5, 
max_overflow=10, and pool_pre_ping=True. Agent didn't know these were required 
for production deployments. Took 30 minutes to debug and fix."

severity: HIGH
```

## Execution

### Phase 1: Analyze

```
Analysis Results:
✓ Domain: 200-Python
✓ Keywords: python, postgres, SQLAlchemy, psycopg2, connection pooling, 
            database, configuration, production, Snowflake
✓ Severity: HIGH
✓ Rule-worthy: Yes
✓ Reason: Generic SQLAlchemy pattern applicable to all Python+database projects
```

### Phase 2: Search

```bash
# Search RULES_INDEX.md
grep -i "sqlalchemy\|postgres\|connection" RULES_INDEX.md
→ rules/200-python-core.md (3 matches)

# Search rules directory
grep -l -i "sqlalchemy\|postgres" rules/*.md
→ rules/200-python-core.md
```

```
Search Results:
✓ Scanned: 121 rules
✓ Top candidate: rules/200-python-core.md
  - Keywords: 4/9 match
  - Domain: 200-series (exact match)
  - Coverage: PARTIAL (has "Database Connections" section but no SQLAlchemy details)

✓ Decision: ENHANCE rules/200-python-core.md
✓ Target: Section 4 "Database Connections"
✓ Rationale: Python-specific patterns, domain rule already has database section
```

### Phase 3A: Enhance

```
Enhancement Plan:
- Target: rules/200-python-core.md
- Section: 4 "Database Connections"  
- Action: Add subsection "SQLAlchemy Connection Pooling"
- Content:
  * Configuration parameters (pool_size, max_overflow, pool_pre_ping)
  * Code examples (sync and async patterns)
  * Best practices for cloud databases
  * Anti-pattern: Creating engine per request
- Metadata updates:
  * Keywords: +5 (SQLAlchemy, postgres, psycopg2, connection pooling, database)
  * TokenBudget: ~5200 → ~5800 (+11%)
```

**Content Added:**

```markdown
### SQLAlchemy Connection Pooling

When connecting to databases like PostgreSQL or Snowflake via SQLAlchemy, 
configure connection pooling explicitly to prevent connection exhaustion.

**Required Configuration:**

```python
from sqlalchemy import create_engine

engine = create_engine(
    "postgresql+psycopg2://user:pass@host/db",
    pool_size=5,              # Persistent connections
    max_overflow=10,          # Additional under load
    pool_pre_ping=True,       # Health check before use
    pool_recycle=3600         # Recycle after 1 hour
)
```

**Best Practices:**
- Always set `pool_pre_ping=True` for cloud databases (Snowflake, AWS RDS)
- Use `pool_recycle=3600` to prevent stale connections
- Monitor active connections: `engine.pool.status()`
- Use singleton pattern for engine (create once, reuse)

**Avoid:**
- Creating new engine per request (causes connection exhaustion)
- Using default pool settings in production
- Omitting `pool_pre_ping` for unstable networks
```

### Phase 4: Validate

```bash
uv run python scripts/schema_validator.py rules/200-python-core.md --verbose
```

```
Validation Attempt 1:
[FAIL] CRITICAL errors: 2
  - Line 8: Keywords count is 7 (expected 5-20)
  - Line 10: TokenBudget ~5200 differs from actual 5834 by 12%

Auto-fixes applied:
  - Keywords: Added 5 new terms → 12 total
  - TokenBudget: Updated ~5200 → ~5800

Validation Attempt 2:
[PASS] Passed: 458 checks
[PASS] RESULT: PASSED
```

```
Validation Complete:
✓ Schema compliance: PASSED
✓ CRITICAL errors: 0
✓ Fixes applied: 2 (keywords, token budget)
```

### Phase 5: Finalize

```bash
uv run python scripts/index_generator.py
```

```
Index Regenerated:
✓ File: RULES_INDEX.md
✓ Rules: 121 (unchanged count, rule enhanced)
✓ Updated entry: 200-python-core.md
  - Keywords: 7 → 12 (+5 new terms)
  - TokenBudget: ~5200 → ~5800
✓ Keyword index: +5 new searchable terms
  - "SQLAlchemy" → 200-python-core.md
  - "postgres" → 200-python-core.md
  - "connection pooling" → 200-python-core.md
```

### Phase 6: Review & Commit

**Diff:**

```diff
diff --git a/rules/200-python-core.md b/rules/200-python-core.md
@@ -8,7 +8,7 @@
-**Keywords:** python, core patterns, async, exceptions, typing, imports, testing
+**Keywords:** python, core patterns, async, exceptions, typing, imports, testing, SQLAlchemy, postgres, psycopg2, connection pooling, database
-**TokenBudget:** ~5200
+**TokenBudget:** ~5800

@@ -145,6 +145,47 @@ Database Connections
 Always wrap database operations in try/except blocks.
 [... existing content ...]
 
+### SQLAlchemy Connection Pooling
+
+When connecting to databases like PostgreSQL or Snowflake via SQLAlchemy, 
+configure connection pooling explicitly.
+[... new content 47 lines ...]
```

**Summary:**

```
Changes Made:
✓ Enhanced: rules/200-python-core.md
✓ Section: 4 "Database Connections"  
✓ Added: Subsection "SQLAlchemy Connection Pooling" (47 lines)
✓ Metadata: +5 keywords, TokenBudget +11%
✓ Index: RULES_INDEX.md updated

Files changed: 2
- rules/200-python-core.md (+47 lines)
- RULES_INDEX.md (+5 keyword entries)
```

**Prompt:**

```
Commit these changes? (Y/n): Y
```

**Commit:**

```bash
git add rules/200-python-core.md RULES_INDEX.md
git commit -m "$(cat <<'EOF'
feat(python): expand database guidance with SQLAlchemy connection pooling

Enhanced rules/200-python-core.md Section 4 with connection pooling 
patterns for SQLAlchemy and psycopg2.

- Added subsection "SQLAlchemy Connection Pooling"
- Configuration examples (pool_size, max_overflow, pool_pre_ping)
- Best practices for cloud databases (Snowflake, AWS RDS)
- Anti-pattern: Creating engine per request
- Updated metadata: +5 keywords, TokenBudget ~5200 → ~5800
- Updated RULES_INDEX.md with new keyword entries
EOF
)"
```

```
Commit: abc1234
Message: feat(python): expand database guidance with SQLAlchemy connection pooling
```

## Output

```
================================================================================
WORKFLOW COMPLETE
================================================================================

✓ Rule: rules/200-python-core.md (enhanced)
✓ Validated: 0 CRITICAL errors
✓ Index: RULES_INDEX.md regenerated
✓ Committed: abc1234

Summary:
- Enhanced: rules/200-python-core.md Section 4
- Added: SQLAlchemy connection pooling guidance (47 lines)
- Keywords: 7 → 12 terms
- TokenBudget: ~5200 → ~5800
- Lesson: Connection exhaustion prevention for cloud databases

Next steps:
1. Push to remote: git push origin main
2. (Optional) Create MR: Use rule-pr skill
3. (Optional) Review quality: Use rule-reviewer skill

================================================================================
```

## Key Takeaways

**Single Invocation:**
- One skill call handled entire workflow
- No manual orchestration needed

**Intelligent Search:**
- Searched existing rules before creating new
- Found partial coverage in domain rule
- Decided to enhance rather than create

**Safe Enhancement:**
- Preserved existing content
- Added subsection following rule's style
- Updated metadata accurately

**Validated:**
- Auto-fixed schema errors
- Regenerated index automatically
- Committed with descriptive message

**Result:**
- 30 minutes of debugging → Captured in rule
- Future agents will know connection pooling patterns
- Prevents same issue from recurring
