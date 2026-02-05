# Phase 4: Validate Changes

Validate rule file against v3.2 schema standards and fix any errors.

## Inputs from Phase 3

- Modified or new rule file: `rules/NNN-rule.md`
- Changes summary (for enhanced rules)
- Expected metadata (Keywords, TokenBudget)

## Steps

### 1. Run Schema Validator

Execute schema_validator.py to check compliance.

```bash
cd /Users/rgoldin/Programming/ai_coding_rules

# Validate single file
uv run python scripts/schema_validator.py rules/NNN-rule.md --verbose
```

**What it checks:**
- Metadata fields present and correctly ordered
- Required sections exist (Metadata, Scope, References, Contract)
- Contract subsections use Markdown ### headers (not XML)
- Keywords count (5-20 terms)
- TokenBudget format (~NUMBER)
- Section structure and placement

### 2. Check Exit Code

**Exit Code 0 (Success):**
```
[PASS] Passed: 458 checks
[PASS] RESULT: PASSED
```
→ Continue to Phase 5

**Exit Code >0 (Errors Found):**
```
[FAIL] CRITICAL errors: 2
[WARN] HIGH errors: 1
[FAIL] RESULT: FAILED
```
→ Proceed to Step 3 (Fix Errors)

### 3. Analyze Errors

Parse validator output to identify issues.

**Error Severity Levels:**

**CRITICAL (Must Fix):**
- Missing required metadata field
- SchemaVersion not v3.2
- Required section missing
- Contract subsection using XML tags
- Keywords count <5 or >20
- TokenBudget missing tilde (~)

**HIGH (Should Fix):**
- Section order incorrect
- Metadata field order wrong
- Contract section after line 160
- Numbered section headings (## 1., ## 2.)

**MEDIUM/LOW (Optional):**
- TokenBudget accuracy (±10% acceptable)
- Minor formatting issues
- Style inconsistencies

**Example Output:**
```
================================================================================
VALIDATION REPORT: rules/207-python-postgres.md
================================================================================
[FAIL] Line 8: CRITICAL - Keywords field missing
[FAIL] Line 12: CRITICAL - TokenBudget format incorrect (missing ~)
[WARN] Line 45: HIGH - Section order: Contract should come before line 40
[INFO] Line 200: MEDIUM - TokenBudget ~1500 vs actual 4234 (difference: 182%)

[FAIL] CRITICAL errors: 2
[WARN] HIGH errors: 1
[INFO] MEDIUM errors: 1

[FAIL] RESULT: FAILED
================================================================================
```

### 4. Fix Errors Automatically (If Possible)

**Auto-Fixable Errors:**

**A. Missing Tilde in TokenBudget**
```python
# Fix
old_string: "**TokenBudget:** 4200"
new_string: "**TokenBudget:** ~4200"
```

**B. Keywords Count Wrong**
```python
# Add more keywords or trim to 5-20 range
old_string: "**Keywords:** python, postgres"
new_string: "**Keywords:** python, postgres, SQLAlchemy, psycopg2, connection pooling, database, async, best practices"
```

**C. Metadata Field Order**
```python
# Reorder to: SchemaVersion, RuleVersion, LastUpdated, Keywords, TokenBudget, ContextTier, Depends
# Use StrReplace to swap lines
```

**D. TokenBudget Accuracy**
```bash
# Re-run token validator to get accurate count
uv run python scripts/token_validator.py rules/NNN-rule.md

# Update field
old_string: "**TokenBudget:** ~1500"
new_string: "**TokenBudget:** ~4200"
```

### 5. Fix Errors Manually (If Auto-Fix Fails)

**Manual Fix Required:**

**A. Missing Required Section**
```
Error: "Required section 'Scope' not found"

Fix:
1. Read rule structure
2. Identify where Scope should be (after Metadata)
3. Insert section with proper content
4. Re-validate
```

**B. Contract Using XML Tags**
```
Error: "Contract section uses XML tags instead of Markdown headers"

Fix:
1. Find Contract section
2. Replace <inputs_and_prerequisites> with ### Inputs and Prerequisites
3. Replace all XML subsection tags with ### Markdown headers
4. Re-validate
```

**C. Section Order Wrong**
```
Error: "Section order incorrect: expected Scope, References, Contract"

Fix:
1. Identify current order
2. Move sections to correct positions using StrReplace
3. Preserve content exactly
4. Re-validate
```

### 6. Validation Loop

Repeat validation until exit code 0.

**Loop Protocol:**
```
LOOP:
  1. Run schema_validator.py
  2. IF exit_code == 0: BREAK
  3. Parse errors
  4. Fix errors (auto or manual)
  5. REPEAT (max 5 attempts)

IF attempts > 5:
  ERROR: "Validation failed after 5 attempts"
  Report remaining errors to user
  ASK: "Continue with manual fixes or abort?"
```

**Example Loop:**
```
Attempt 1: 2 CRITICAL, 1 HIGH → Auto-fix TokenBudget, Keywords
Attempt 2: 1 HIGH → Fix section order
Attempt 3: 0 CRITICAL, 0 HIGH → SUCCESS
```

### 7. Verify Metadata Accuracy

Double-check metadata reflects actual content.

**Keywords Verification:**
```bash
# Extract keywords from rule
grep "**Keywords:**" rules/NNN-rule.md

# Count keywords
# Should be: 5-20 comma-separated terms

# Verify they match content
# Check if key terms from lesson learned are present
```

**TokenBudget Verification:**
```bash
# Run token validator
uv run python scripts/token_validator.py rules/NNN-rule.md --dry-run

# Check difference
# If >20% off, update TokenBudget field
```

**ContextTier Verification:**
```
Check if tier matches usage:
- CRITICAL: Bootstrap rules (000-global-core.md, AGENTS.md)
- HIGH: Domain cores, frequently loaded
- MEDIUM: Specialized rules, loaded as needed
- LOW: Rare use cases, edge scenarios
```

## Outputs

**Validation Success:**
```markdown
Validation Complete:
✓ Schema compliance: PASSED
✓ CRITICAL errors: 0
✓ HIGH errors: 0
✓ Metadata verified: Keywords (12), TokenBudget (~4200)
✓ Ready for index generation
```

**Validation with Fixes:**
```markdown
Validation Complete (After Fixes):
✓ Schema compliance: PASSED
✓ Fixes applied:
  - TokenBudget format corrected (~)
  - Keywords added (8 → 12)
  - Section order fixed
✓ CRITICAL errors: 0
✓ Ready for index generation
```

**Validation Failed:**
```markdown
Validation Failed:
✗ CRITICAL errors: 1
✗ Error: Required section 'Contract' not found at line 40
✗ Attempts: 5/5
✗ Manual intervention required

Options:
A) Fix manually and continue
B) Abort and report issue
```

## Error Handling

**Schema Validator Not Found:**
```
If scripts/schema_validator.py doesn't exist:
  ERROR: "Schema validator not found"
  CHECK: scripts/ directory exists
  FALLBACK: Manual validation against schemas/rule-schema.yml
  DOCUMENT: "Manual validation used"
```

**Validator Crashes:**
```
If validator exits with error (not validation failure):
  LOG: Full error output
  CHECK: Rule file is valid Markdown (no corruption)
  CHECK: Python environment (uv) working
  FALLBACK: Try direct python: python scripts/schema_validator.py
```

**Cannot Auto-Fix:**
```
If error cannot be automatically fixed:
  DOCUMENT: "Manual fix required for [error]"
  PROVIDE: Exact fix instructions
  ASK USER: "Can you fix manually, or should I attempt alternative?"
```

**Infinite Loop Prevention:**
```
If validation loop exceeds 5 attempts:
  STOP: "Max validation attempts reached"
  REPORT: Remaining errors
  ASK: "Continue with manual fixes?"
```

## Validation Examples

### Example 1: Success (No Fixes Needed)

**Input:** rules/207-python-postgres.md (newly created)

**Validation:**
```bash
uv run python scripts/schema_validator.py rules/207-python-postgres.md --verbose

Output:
================================================================================
VALIDATION REPORT: rules/207-python-postgres.md
================================================================================
[PASS] Passed: 458 checks

[PASS] RESULT: PASSED
================================================================================
```

**Result:** ✓ Continue to Phase 5

### Example 2: Auto-Fixes Applied

**Input:** rules/200-python-core.md (enhanced)

**Validation Attempt 1:**
```
[FAIL] CRITICAL errors: 2
  - Line 8: Keywords count is 3 (expected 5-20)
  - Line 10: TokenBudget format incorrect (missing ~)
```

**Auto-Fix:**
```python
# Fix 1: Add keywords
old_string: "**Keywords:** python, core, patterns"
new_string: "**Keywords:** python, core, patterns, SQLAlchemy, postgres, psycopg2, connection pooling, database"

# Fix 2: Add tilde
old_string: "**TokenBudget:** 5800"
new_string: "**TokenBudget:** ~5800"
```

**Validation Attempt 2:**
```
[PASS] Passed: 458 checks
[PASS] RESULT: PASSED
```

**Result:** ✓ Fixes applied, validation passed

### Example 3: Manual Fix Required

**Input:** rules/207-python-postgres.md

**Validation Attempt 1:**
```
[FAIL] CRITICAL errors: 1
  - Line 40: Required section 'Contract' not found
```

**Manual Fix:**
```markdown
# Section missing entirely
# Must add full Contract section with all subsections

## Contract

### Inputs and Prerequisites
[content]

### Mandatory
[content]

[... all required subsections ...]
```

**Validation Attempt 2:**
```
[PASS] Passed: 458 checks
[PASS] RESULT: PASSED
```

**Result:** ✓ Manual fix applied, validation passed

## Validation Checklist

**Pre-Validation:**
- [ ] Rule file exists and is readable
- [ ] schema_validator.py accessible
- [ ] uv environment active

**During Validation:**
- [ ] Validator runs without crashes
- [ ] Exit code captured
- [ ] Error output parsed correctly

**Post-Validation:**
- [ ] Exit code == 0 (success)
- [ ] CRITICAL errors == 0
- [ ] HIGH errors == 0 or acknowledged
- [ ] Metadata accuracy verified

**If Fixes Applied:**
- [ ] Auto-fixes documented
- [ ] Manual fixes documented
- [ ] Re-validation completed
- [ ] Final exit code == 0

## Next Phase

**If Validation = SUCCESS:**
- **Proceed to:** `workflows/05-finalize.md`
- **Carry forward:** Validated rule file path

**If Validation = FAILED after 5 attempts:**
- **Stop execution**
- **Report:** Remaining errors to user
- **Request:** Manual intervention
