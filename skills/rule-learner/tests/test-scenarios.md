# Rule Learner Tests

Test cases for rule-learner skill validation.

## Test 1: Input Validation

**Purpose:** Verify input validation catches invalid or missing inputs.

### Test 1.1: Missing conversation_summary

**Input:**
```markdown
Use rule-learner skill.

severity: HIGH
```

**Expected:**
- ERROR: "conversation_summary is required"
- Prompt: "Please provide a summary of what was learned (100-500 words)"

### Test 1.2: Conversation_summary too short

**Input:**
```markdown
Use rule-learner skill.

conversation_summary: "auth failed"
```

**Expected:**
- WARNING: "Summary is very brief (10 characters). Provide more detail?"
- Proceed with limited analysis OR ask for more detail

### Test 1.3: Invalid severity

**Input:**
```markdown
Use rule-learner skill.

conversation_summary: "..."
severity: URGENT
```

**Expected:**
- WARNING: "Invalid severity 'URGENT'. Using default: MEDIUM"
- Continue with MEDIUM severity

## Test 2: Keyword Extraction

**Purpose:** Verify Phase 1 correctly extracts keywords from conversation.

### Test 2.1: Python + Database

**Input:**
```
conversation_summary: "SQLAlchemy connection pooling for PostgreSQL. Agent 
created new engine per request causing connection exhaustion. Needed pool_size=5 
and max_overflow=10."
```

**Expected Keywords:**
- python, SQLAlchemy, postgres, postgresql, connection pooling, database, engine, configuration

### Test 2.2: Snowflake + Authentication

**Input:**
```
conversation_summary: "Snowflake REST API authentication failed with 401. 
Agent didn't check $SNOWFLAKE_PAT environment variable. Blocked pytest execution."
```

**Expected Keywords:**
- snowflake, REST API, authentication, environment variables, SNOWFLAKE_PAT, pytest, 401

## Test 3: Rule-Worthiness Assessment

**Purpose:** Verify Phase 1 correctly filters project-specific vs generic issues.

### Test 3.1: Generic Pattern (Rule-worthy)

**Input:**
```
conversation_summary: "FastAPI async testing required @pytest.mark.asyncio 
decorator. Agent used regular sync tests which failed. All FastAPI async endpoints 
need this pattern."
```

**Expected:**
- Rule-worthy: YES
- Reason: "Generic FastAPI async testing pattern"
- Proceed to Phase 2

### Test 3.2: Project-Specific (Not rule-worthy)

**Input:**
```
conversation_summary: "Database MY_PROJECT_DB not found. Typo in connection 
string, should have been MY_PROJECT_DATABASE."
```

**Expected:**
- Rule-worthy: NO
- Reason: "Project-specific database name typo"
- STOP with message

### Test 3.3: Cannot Be Ruled (Agent persistence)

**Input:**
```
conversation_summary: "Agent gave up after 2 attempts. Should have tried harder 
and explored more alternatives."
```

**Expected:**
- Rule-worthy: NO
- Reason: "Agent persistence cannot be codified - contextual judgment"
- STOP with message

## Test 4: Search and Coverage Assessment

**Purpose:** Verify Phase 2 correctly searches and assesses coverage.

### Test 4.1: Partial Coverage Found (Enhance)

**Setup:**
```
rules/200-python-core.md exists with Section 4 "Database Connections"
Keywords match: python, database, connection
Coverage: Mentions databases but no SQLAlchemy specifics
```

**Input:**
```
conversation_summary: "SQLAlchemy connection pooling configuration..."
```

**Expected:**
- Search finds: rules/200-python-core.md
- Coverage: PARTIAL
- Decision: ENHANCE rules/200-python-core.md
- Rationale: "Domain rule has database section, expand with SQLAlchemy"

### Test 4.2: No Coverage Found (Create)

**Setup:**
```
No existing rules mention "DaisyUI"
```

**Input:**
```
conversation_summary: "DaisyUI component library patterns for Tailwind CSS..."
```

**Expected:**
- Search finds: No matches
- Coverage: NONE
- Decision: CREATE new rule
- Domain: 400-series (JavaScript/Frontend)
- Rule number: 445 (next available)

### Test 4.3: Complete Coverage (Stop)

**Setup:**
```
rules/206-python-pytest.md exists with Section 5 "Async Testing"
Includes @pytest.mark.asyncio decorator and httpx.AsyncClient examples
```

**Input:**
```
conversation_summary: "pytest async testing with @pytest.mark.asyncio..."
```

**Expected:**
- Search finds: rules/206-python-pytest.md Section 5
- Coverage: COMPLETE
- Decision: STOP
- Message: "Coverage already exists in rules/206-python-pytest.md Section 5"

## Test 5: Validation Loop

**Purpose:** Verify Phase 4 correctly fixes validation errors.

### Test 5.1: Auto-Fixable Errors

**Setup:**
```
Rule modified with:
- Keywords count: 3 (need 5-20)
- TokenBudget: 5800 (missing ~)
```

**Expected:**
- Validation Attempt 1: 2 CRITICAL errors
- Auto-fix 1: Add keywords → 12 total
- Auto-fix 2: Add tilde → ~5800
- Validation Attempt 2: PASS
- Report: "2 auto-fixes applied"

### Test 5.2: Manual Fix Required

**Setup:**
```
Rule created missing "Contract" section entirely
```

**Expected:**
- Validation Attempt 1: CRITICAL error "Contract section missing"
- Cannot auto-fix (requires full section)
- Report: "Manual fix required: Add Contract section"
- Provide: Template for Contract section
- Stop and await user intervention

## Test 6: Index Regeneration

**Purpose:** Verify Phase 5 correctly updates RULES_INDEX.md.

### Test 6.1: New Rule Entry

**Setup:**
```
Created: rules/207-python-postgres.md
```

**Expected:**
- Run index_generator.py
- RULES_INDEX.md updated
- New entry appears in numeric order (after 206, before 210)
- Keywords propagated to keyword index
- Total rule count: 121 → 122

### Test 6.2: Enhanced Rule Entry

**Setup:**
```
Enhanced: rules/200-python-core.md
Added: +5 keywords
Updated: TokenBudget ~5200 → ~5800
```

**Expected:**
- Run index_generator.py
- RULES_INDEX.md updated
- Entry shows new keywords (7 → 12)
- Entry shows new TokenBudget (~5800)
- Total rule count: 121 (unchanged)

## Test 7: Commit Workflow

**Purpose:** Verify Phase 6 correctly commits changes.

### Test 7.1: User Approves Commit

**Setup:**
```
auto_commit: false
Changes: rules/207-python-postgres.md (NEW), RULES_INDEX.md (UPDATED)
```

**User Input:** `Y`

**Expected:**
- Show diff
- Prompt: "Commit? (Y/n):"
- User: Y
- git add files
- git commit with descriptive message
- Report: Commit hash and message

### Test 7.2: User Declines Commit

**Setup:**
```
auto_commit: false
```

**User Input:** `n`

**Expected:**
- Show diff
- Prompt: "Commit? (Y/n):"
- User: n
- Skip commit
- Report: "Changes remain unstaged. Commit manually when ready."

### Test 7.3: Auto-Commit Enabled

**Setup:**
```
auto_commit: true
```

**Expected:**
- Show diff
- Skip user prompt
- git add files
- git commit automatically
- Report: Commit hash and message

## Test 8: Error Handling

**Purpose:** Verify error handling for common failure scenarios.

### Test 8.1: Schema Validator Not Found

**Setup:**
```
scripts/schema_validator.py missing
```

**Expected:**
- ERROR: "Schema validator not found at scripts/schema_validator.py"
- Fallback: Manual validation instructions
- STOP or continue with manual validation flag

### Test 8.2: Git Not Available

**Setup:**
```
Git command not in PATH
```

**Expected:**
- Complete Phases 1-5 successfully
- Phase 6: ERROR "Git not available"
- Report: "Changes complete but not committed. Install git to enable commits."
- Do not fail workflow

### Test 8.3: Template Generator Fails

**Setup:**
```
scripts/template_generator.py crashes
```

**Expected:**
- ERROR: "Template generator failed: [error message]"
- Fallback: "Creating template manually from rules/002-rule-governance.md structure"
- Continue with manual template creation

## Test 9: Integration Tests

**Purpose:** Verify complete end-to-end workflows.

### Test 9.1: Full Enhancement Workflow

**Input:**
```
conversation_summary: "SQLAlchemy connection pooling..."
severity: HIGH
auto_commit: false
```

**Expected Flow:**
1. Phase 1: Analyze → Rule-worthy
2. Phase 2: Search → Partial coverage in 200-python-core.md
3. Phase 3A: Enhance → Add subsection
4. Phase 4: Validate → Auto-fix 2 errors → PASS
5. Phase 5: Regenerate → Index updated
6. Phase 6: Show diff → User approves → Commit

**Expected Result:**
- rules/200-python-core.md enhanced
- RULES_INDEX.md updated
- Git commit created
- Success message with commit hash

### Test 9.2: Full Creation Workflow

**Input:**
```
conversation_summary: "DaisyUI component patterns..."
severity: MEDIUM
auto_commit: true
```

**Expected Flow:**
1. Phase 1: Analyze → Rule-worthy
2. Phase 2: Search → No coverage
3. Phase 3B: Create → rules/445-daisyui-core.md
4. Phase 4: Validate → PASS (0 errors)
5. Phase 5: Regenerate → Index updated with new entry
6. Phase 6: Skip prompt → Auto-commit

**Expected Result:**
- rules/445-daisyui-core.md created
- RULES_INDEX.md updated (121 → 122 rules)
- Git commit created automatically
- Success message

### Test 9.3: Stop on Complete Coverage

**Input:**
```
conversation_summary: "pytest async testing with @pytest.mark.asyncio..."
```

**Expected Flow:**
1. Phase 1: Analyze → Rule-worthy
2. Phase 2: Search → Complete coverage in 206-python-pytest.md
3. STOP

**Expected Result:**
- No changes made
- Message: "Coverage already exists in rules/206-python-pytest.md Section 5"
- Reference to existing rule provided

## Running Tests

### Manual Testing

```bash
# Test each scenario manually with rule-learner skill
# Verify output matches expected results
```

### Automated Testing

```bash
# TODO: Create automated test harness
# - Mock conversation summaries
# - Verify phase transitions
# - Check file outputs
# - Validate commits
```

## Test Coverage Goals

- [ ] Input validation: 100%
- [ ] Keyword extraction: 100%
- [ ] Rule-worthiness: 100%
- [ ] Search logic: 100%
- [ ] Coverage assessment: 100%
- [ ] Validation loop: 100%
- [ ] Index regeneration: 100%
- [ ] Commit workflow: 100%
- [ ] Error handling: 100%
- [ ] End-to-end: 3 scenarios minimum
