# Phase 5: Finalize - Regenerate Index

Regenerate RULES_INDEX.md to include new/updated rule and verify entry is correct.

## Inputs from Phase 4

- Validated rule file: `rules/NNN-rule.md`
- Rule metadata (Keywords, TokenBudget, ContextTier)

## Steps

### 1. Regenerate RULES_INDEX.md

Execute index_generator.py to update master index.

```bash
cd /Users/rgoldin/Programming/ai_coding_rules

# Regenerate index
uv run python scripts/index_generator.py
```

**What it does:**
- Scans all files in `rules/` directory
- Extracts metadata from each rule
- Organizes rules by domain (000-099, 100-199, etc.)
- Generates searchable keyword index
- Writes updated `RULES_INDEX.md`

**Example Output:**
```
Scanning rules directory...
Found: 122 rule files
Generating index...
Writing RULES_INDEX.md...
Done. Index updated with 122 rules.
```

### 2. Verify New Entry

Check that new/updated rule appears in RULES_INDEX.md correctly.

```bash
# Search for rule in index
grep "NNN-rule-name" RULES_INDEX.md

# OR view section for domain
grep -A 20 "## 200-series" RULES_INDEX.md  # For Python domain
```

**Verify:**
- Rule appears in correct domain section
- Keywords listed accurately
- TokenBudget shown
- ContextTier correct
- Depends listed if specified

**Example Entry:**
```markdown
### 207-python-postgres.md

**Title:** Python PostgreSQL Best Practices
**Keywords:** python, postgres, postgresql, SQLAlchemy, psycopg2, connection pooling, database, async, best practices, environment setup, configuration
**TokenBudget:** ~4200
**ContextTier:** High
**Depends:** 000-global-core.md, 200-python-core.md
```

### 3. Check Numeric Order

Verify rule appears in correct numeric position.

```bash
# List rules in domain to check order
grep "^### [0-9]" RULES_INDEX.md | grep "20[0-9]"

# Should show:
# ### 200-python-core.md
# ### 201-python-async.md
# ### 203-python-project-setup.md
# ### 206-python-pytest.md
# ### 207-python-postgres.md  ← NEW ENTRY
```

**Verify:**
- New rule appears in numeric sequence
- No duplicates
- No gaps (unless intentional)

### 4. Verify Keywords Propagation

Check that keywords from rule metadata appear in searchable index.

```bash
# Search for specific keyword
grep -i "connection pooling" RULES_INDEX.md

# Should return:
# - Entry in rule keywords list
# - Entry in keyword-to-rule mapping section
```

**RULES_INDEX.md Keyword Section:**
```markdown
## Keyword Index

### A-C
...
**connection pooling:** 207-python-postgres.md, ...
...

### P-R  
**postgres:** 200-python-core.md, 207-python-postgres.md
**postgresql:** 207-python-postgres.md
**psycopg2:** 207-python-postgres.md
...
```

## Outputs

**Index Update Summary:**
```markdown
Index Regenerated:
✓ File: RULES_INDEX.md
✓ Total rules: 122 (was 121)
✓ New entry: 207-python-postgres.md
  - Domain: 200-series (Python)
  - Position: After 206, before 210
  - Keywords: 11 terms
  - TokenBudget: ~4200
✓ Keyword index updated: +11 new terms
✓ All checks passed
```

## Verification Examples

### Example 1: New Rule Added

**Before regeneration:**
```
Total rules in index: 121
Last Python rule: 206-python-pytest.md
```

**After regeneration:**
```bash
grep "^### 20[0-9]" RULES_INDEX.md
# Output:
# ### 200-python-core.md
# ### 201-python-async.md
# ### 203-python-project-setup.md
# ### 206-python-pytest.md
# ### 207-python-postgres.md  ← NEW

Total rules in index: 122
```

**Verification:** ✓ New rule appears in correct position

### Example 2: Enhanced Rule Updated

**Before regeneration:**
```
### 200-python-core.md
**Keywords:** python, core patterns, async, exceptions, typing, imports, testing
**TokenBudget:** ~5200
```

**After regeneration:**
```
### 200-python-core.md
**Keywords:** python, core patterns, async, exceptions, typing, imports, testing, SQLAlchemy, postgres, psycopg2, connection pooling, database
**TokenBudget:** ~5800
```

**Verification:** ✓ Keywords and TokenBudget updated correctly

### Example 3: Keyword Index Updated

**Search for new keyword:**
```bash
grep -i "connection pooling" RULES_INDEX.md
```

**Output:**
```
**connection pooling:** 200-python-core.md, 207-python-postgres.md
```

**Verification:** ✓ Keyword appears in index with correct rule references

## Error Handling

**Index Generator Not Found:**
```
If scripts/index_generator.py doesn't exist:
  ERROR: "Index generator not found"
  CHECK: scripts/ directory structure
  FALLBACK: Manual index update (not recommended)
  DOCUMENT: "Manual index update required"
```

**Generator Crashes:**
```
If index_generator.py fails:
  LOG: Full error output
  CHECK: All rule files have valid metadata
  CHECK: No corrupted .md files in rules/
  RETRY: Run validator on all rules first
  FALLBACK: Fix specific rule causing crash
```

**Entry Missing from Index:**
```
If new rule doesn't appear in regenerated index:
  CHECK: Rule file in rules/ directory
  CHECK: Rule has required metadata fields
  CHECK: Filename format correct (NNN-name.md)
  RE-RUN: index_generator.py with verbose flag
  MANUAL: Add entry if generator bug
```

**Keyword Mismatch:**
```
If keywords in index don't match rule file:
  CHECK: Rule file metadata (read it directly)
  CHECK: Index generation log for warnings
  RE-RUN: index_generator.py
  IF persists: Report bug in generator
```

## Next Phase

**Proceed to:** `workflows/06-commit.md`

**Carry forward:**
- Modified rule file path
- Updated RULES_INDEX.md
- Changes summary
