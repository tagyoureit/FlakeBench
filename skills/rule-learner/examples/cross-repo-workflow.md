# Example: Cross-Repository Workflow

This example shows how rule-learner works when you're in a different project directory than ai_coding_rules.

## Scenario

You're working on a Snowflake data pipeline project. You discover that Dynamic Tables require explicit `REFRESH_MODE` configuration, which the agent didn't know. You want to capture this lesson in the ai_coding_rules repository.

## Current State

```bash
# You're working in your project
$ pwd
/Users/rgoldin/projects/snowflake-data-pipeline

# ai_coding_rules is elsewhere (at a common location)
$ ls ~/Programming/ai_coding_rules
AGENTS.md  CLAUDE.md  rules/  scripts/  skills/  ...
```

## Input

```markdown
# From your project directory
Use rule-learner skill.

conversation_summary: "Snowflake Dynamic Tables failed to refresh automatically. 
Agent created table without REFRESH_MODE parameter. Had to manually add 
REFRESH_MODE = AUTO to table definition. Agent didn't know this was required. 
Took 20 minutes to debug why data wasn't updating."

severity: HIGH
```

## Execution

### Phase 0: Locate Repository

```
════════════════════════════════════════════════════════════════════════
Phase 0: Locate ai_coding_rules Repository
════════════════════════════════════════════════════════════════════════

Checking current directory... not ai_coding_rules
Searching common locations...
✓ Found: /Users/rgoldin/Programming/ai_coding_rules

Verifying repository structure...
✓ rules/ directory exists
✓ AGENTS.md exists
✓ rules/RULES_INDEX.md exists
✓ scripts/ directory exists

════════════════════════════════════════════════════════════════════════
Repository Located
════════════════════════════════════════════════════════════════════════
Path: /Users/rgoldin/Programming/ai_coding_rules
Current directory: /Users/rgoldin/projects/snowflake-data-pipeline

All changes will be made in: /Users/rgoldin/Programming/ai_coding_rules
Your current project directory remains unchanged.
════════════════════════════════════════════════════════════════════════
```

### Phase 1: Analyze

```
Analysis Results:
✓ Domain: 100-Snowflake
✓ Keywords: snowflake, Dynamic Tables, REFRESH_MODE, AUTO, refresh, 
            data pipeline, configuration, debugging
✓ Severity: HIGH
✓ Rule-worthy: Yes
✓ Reason: Generic Dynamic Tables pattern applicable to all Snowflake projects
✓ Project context: snowflake-data-pipeline (for commit message)
```

### Phase 2: Search

```bash
# Searching in AI_CODING_RULES_REPO
$ grep -i "dynamic table\|REFRESH_MODE" /Users/rgoldin/Programming/ai_coding_rules/rules/*.md
→ /Users/rgoldin/Programming/ai_coding_rules/rules/112-snowflake-dynamic-tables.md

$ cat /Users/rgoldin/Programming/ai_coding_rules/RULES_INDEX.md | grep -i "dynamic"
→ 112-snowflake-dynamic-tables.md
```

```
Search Results:
✓ Scanned: 121 rules in /Users/rgoldin/Programming/ai_coding_rules/rules/
✓ Top candidate: rules/112-snowflake-dynamic-tables.md
  - Keywords: 4/8 match
  - Domain: 100-series (exact match)
  - Coverage: MINIMAL (mentions Dynamic Tables but no REFRESH_MODE details)

✓ Decision: ENHANCE rules/112-snowflake-dynamic-tables.md
✓ Target: Add new section on REFRESH_MODE configuration
✓ Rationale: Snowflake-specific patterns, topic-specific rule exists
```

### Phase 3A: Enhance

```
Enhancement Plan:
- Repository: /Users/rgoldin/Programming/ai_coding_rules
- Target: rules/112-snowflake-dynamic-tables.md
- Action: Add Section 4 "REFRESH_MODE Configuration"
- Content:
  * REFRESH_MODE parameter (AUTO, INCREMENTAL, FULL)
  * When each mode is appropriate
  * Code examples with proper syntax
  * Common pitfall: Omitting REFRESH_MODE
- Metadata updates:
  * Keywords: +3 (REFRESH_MODE, AUTO, refresh)
  * TokenBudget: ~2800 → ~3200 (+14%)
```

**File being modified:**
```bash
# Opening file in ai_coding_rules repo, not current project
vim /Users/rgoldin/Programming/ai_coding_rules/rules/112-snowflake-dynamic-tables.md
```

**Content Added:**

```markdown
## REFRESH_MODE Configuration

Dynamic Tables require explicit `REFRESH_MODE` parameter to control refresh behavior.

**Refresh Modes:**

```sql
-- AUTO: Snowflake decides when to refresh based on query patterns
CREATE OR REPLACE DYNAMIC TABLE my_table
REFRESH_MODE = AUTO
TARGET_LAG = '1 hour'
AS SELECT * FROM source_table;

-- INCREMENTAL: Refresh only changed data
CREATE OR REPLACE DYNAMIC TABLE my_table
REFRESH_MODE = INCREMENTAL
TARGET_LAG = '5 minutes'
AS SELECT * FROM source_table WHERE updated_at > ...;

-- FULL: Complete refresh every time
CREATE OR REPLACE DYNAMIC TABLE my_table
REFRESH_MODE = FULL
TARGET_LAG = '1 day'
AS SELECT * FROM source_table;
```

**When to Use:**
- **AUTO:** Most common, let Snowflake optimize
- **INCREMENTAL:** Large tables with time-based filtering
- **FULL:** Small tables or complex transformations

**Common Mistake:**
```sql
-- BAD: Missing REFRESH_MODE (will fail)
CREATE DYNAMIC TABLE my_table
TARGET_LAG = '1 hour'
AS SELECT ...;

-- GOOD: Explicit REFRESH_MODE
CREATE DYNAMIC TABLE my_table
REFRESH_MODE = AUTO
TARGET_LAG = '1 hour'
AS SELECT ...;
```
```

### Phase 4: Validate

```bash
# Validation runs in ai_coding_rules repo
$ cd /Users/rgoldin/Programming/ai_coding_rules
$ uv run python scripts/schema_validator.py rules/112-snowflake-dynamic-tables.md --verbose
```

```
Validation Attempt 1:
[FAIL] CRITICAL errors: 2
  - Line 8: Keywords count is 9 (expected 5-20, OK but could add more)
  - Line 10: TokenBudget ~2800 differs from actual 3245 by 16%

Auto-fixes applied:
  - Keywords: Added 3 new terms (REFRESH_MODE, AUTO, refresh) → 12 total
  - TokenBudget: Updated ~2800 → ~3200

Validation Attempt 2:
[PASS] Passed: 458 checks
[PASS] RESULT: PASSED
```

```
Validation Complete:
✓ Repository: /Users/rgoldin/Programming/ai_coding_rules
✓ Schema compliance: PASSED
✓ CRITICAL errors: 0
✓ Fixes applied: 2 (keywords, token budget)
```

### Phase 5: Finalize

```bash
# Index regeneration runs in ai_coding_rules repo
$ cd /Users/rgoldin/Programming/ai_coding_rules
$ uv run python scripts/index_generator.py
```

```
Index Regenerated:
✓ File: /Users/rgoldin/Programming/ai_coding_rules/RULES_INDEX.md
✓ Rules: 121 (unchanged count, rule enhanced)
✓ Updated entry: 112-snowflake-dynamic-tables.md
  - Keywords: 9 → 12 (+3 new terms)
  - TokenBudget: ~2800 → ~3200
✓ Keyword index: +3 new searchable terms
  - "REFRESH_MODE" → 112-snowflake-dynamic-tables.md
  - "AUTO" → 112-snowflake-dynamic-tables.md
  - "refresh" → 112-snowflake-dynamic-tables.md
```

### Phase 6: Review & Commit

**Repository context:**
```bash
# Git operations happen in ai_coding_rules repo
$ cd /Users/rgoldin/Programming/ai_coding_rules
$ git diff rules/112-snowflake-dynamic-tables.md
```

**Diff:**

```diff
diff --git a/rules/112-snowflake-dynamic-tables.md b/rules/112-snowflake-dynamic-tables.md
@@ -8,7 +8,7 @@
-**Keywords:** snowflake, Dynamic Tables, streaming, incremental, pipelines, TARGET_LAG, warehouse, automation, data engineering
+**Keywords:** snowflake, Dynamic Tables, streaming, incremental, pipelines, TARGET_LAG, warehouse, automation, data engineering, REFRESH_MODE, AUTO, refresh
-**TokenBudget:** ~2800
+**TokenBudget:** ~3200

@@ -87,6 +87,58 @@ WHERE condition
 [... existing content ...]
 
+## REFRESH_MODE Configuration
+
+Dynamic Tables require explicit `REFRESH_MODE` parameter to control refresh behavior.
+[... new content 58 lines ...]
```

**Summary:**

```
Changes Made:
✓ Enhanced: /Users/rgoldin/Programming/ai_coding_rules/rules/112-snowflake-dynamic-tables.md
✓ Section: NEW Section 4 "REFRESH_MODE Configuration"
✓ Added: Configuration patterns, code examples, best practices (58 lines)
✓ Metadata: +3 keywords, TokenBudget +14%
✓ Index: RULES_INDEX.md updated

Repository: /Users/rgoldin/Programming/ai_coding_rules
Current directory: /Users/rgoldin/projects/snowflake-data-pipeline (unchanged)

Files changed: 2
- rules/112-snowflake-dynamic-tables.md (+58 lines)
- RULES_INDEX.md (+3 keyword entries)
```

**Prompt:**

```
Commit these changes? (Y/n): Y
```

**Commit:**

```bash
$ cd /Users/rgoldin/Programming/ai_coding_rules
$ git add rules/112-snowflake-dynamic-tables.md RULES_INDEX.md
$ git commit -m "$(cat <<'EOF'
feat(snowflake): add REFRESH_MODE configuration for Dynamic Tables

Enhanced rules/112-snowflake-dynamic-tables.md with REFRESH_MODE patterns.

Discovered during work on snowflake-data-pipeline project - agent created 
Dynamic Table without REFRESH_MODE parameter causing refresh failures.

- Added Section 4: REFRESH_MODE Configuration
- Documented three modes: AUTO, INCREMENTAL, FULL
- Code examples for each mode with use cases
- Common mistake: Omitting REFRESH_MODE (causes failures)
- Updated metadata: +3 keywords, TokenBudget ~2800 → ~3200
- Updated RULES_INDEX.md

Project context: snowflake-data-pipeline
EOF
)"
```

```
Commit: def5678
Message: feat(snowflake): add REFRESH_MODE configuration for Dynamic Tables
```

## Output

```
════════════════════════════════════════════════════════════════════════
WORKFLOW COMPLETE
════════════════════════════════════════════════════════════════════════

✓ Changes made in: /Users/rgoldin/Programming/ai_coding_rules
✓ Current directory: /Users/rgoldin/projects/snowflake-data-pipeline (unchanged)
✓ Rule enhanced: rules/112-snowflake-dynamic-tables.md
✓ Committed: def5678

Summary:
- Enhanced: rules/112-snowflake-dynamic-tables.md Section 4
- Added: REFRESH_MODE configuration patterns (58 lines)
- Keywords: 9 → 12 terms
- TokenBudget: ~2800 → ~3200
- Project: snowflake-data-pipeline
- Lesson: REFRESH_MODE required for Dynamic Tables

Next steps:
1. cd /Users/rgoldin/Programming/ai_coding_rules
2. git push origin main
3. (Optional) Use rule-pr skill to create MR
4. Deploy rules to other projects: task deploy DEST=~/other-project

Your project directory (/Users/rgoldin/projects/snowflake-data-pipeline) 
remains unchanged. Continue working normally.
════════════════════════════════════════════════════════════════════════
```

## Key Takeaways

### Cross-Repository Operation

**Before (without Phase 0):**
```bash
# WRONG - Would try to create rules/ in current project
cd ~/projects/snowflake-data-pipeline
Use rule-learner
→ Creates snowflake-data-pipeline/rules/ ❌
```

**After (with Phase 0):**
```bash
# CORRECT - Operates on ai_coding_rules repo
cd ~/projects/snowflake-data-pipeline
Use rule-learner
→ Modifies ~/Programming/ai_coding_rules/rules/ ✅
```

### Workflow Benefits

1. **Work from anywhere** - Use skill regardless of current directory
2. **Current project protected** - Never touches your project files
3. **Centralized rules** - All lessons go to one repository
4. **Context preserved** - Commit message includes project context
5. **No manual navigation** - No need to cd back and forth

### Directory States

**During execution:**
```
Working directory: /Users/rgoldin/projects/snowflake-data-pipeline
Repository: /Users/rgoldin/Programming/ai_coding_rules
Operations target: Repository (not working directory)
```

**After completion:**
```
Working directory: /Users/rgoldin/projects/snowflake-data-pipeline (unchanged)
Repository: /Users/rgoldin/Programming/ai_coding_rules (modified and committed)
```

### Multi-Project Benefits

```
Project A (data-pipeline): Learns Dynamic Tables → Updates ai_coding_rules
Project B (ml-pipeline): Learns Cortex ML → Updates ai_coding_rules  
Project C (api-service): Learns REST API → Updates ai_coding_rules

Deploy: task deploy DEST=~/project-d
→ Project D gets all lessons from A, B, C
```

All projects contribute to the same rule repository, creating a continuously improving knowledge base.
