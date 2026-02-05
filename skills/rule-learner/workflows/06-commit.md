# Phase 6: Review & Commit

Show changes to user and optionally commit to git.

## Inputs from Phase 5

- Modified rule file: `rules/NNN-rule.md`
- Updated RULES_INDEX.md
- Changes summary
- auto_commit flag (from initial inputs)

## Steps

### 1. Generate Diff

Show what changed in rule file and RULES_INDEX.md.

```bash
# Rule file diff
git diff rules/NNN-rule.md

# Index diff
git diff RULES_INDEX.md
```

**Diff Format:**
```diff
diff --git a/rules/200-python-core.md b/rules/200-python-core.md
index abc123..def456 100644
--- a/rules/200-python-core.md
+++ b/rules/200-python-core.md
@@ -8,7 +8,7 @@
-**Keywords:** python, core patterns, async, exceptions
+**Keywords:** python, core patterns, async, exceptions, SQLAlchemy, postgres, connection pooling
-**TokenBudget:** ~5200
+**TokenBudget:** ~5800
 
 ... (section additions shown) ...
```

### 2. Format Changes Summary

Present human-readable summary of changes.

**For Enhanced Rules:**
```markdown
Changes Made:
✓ Enhanced: rules/200-python-core.md
✓ Section: 4 "Database Connections"
✓ Added: Subsection "SQLAlchemy Connection Pooling" (47 lines)
✓ Content:
  - Configuration patterns (pool_size, max_overflow, pool_pre_ping)
  - Code examples (3 blocks)
  - Best practices (5 items)
  - Anti-patterns (3 items)
✓ Metadata updates:
  - Keywords: +5 (SQLAlchemy, postgres, psycopg2, connection pooling, database)
  - TokenBudget: ~5200 → ~5800 (+11%)
✓ Index: RULES_INDEX.md updated

Files changed: 2
- rules/200-python-core.md (+47 lines)
- RULES_INDEX.md (+11 keyword entries)
```

**For New Rules:**
```markdown
Changes Made:
✓ Created: rules/207-python-postgres.md
✓ Domain: 200-series (Python)
✓ Content:
  - Complete v3.2 schema structure
  - All required sections (9)
  - Code examples (3 blocks)
  - TokenBudget: ~4200 tokens
✓ Metadata:
  - Keywords: 11 terms
  - ContextTier: High
  - Depends: 000-global-core.md, 200-python-core.md
✓ Index: RULES_INDEX.md updated

Files changed: 2
- rules/207-python-postgres.md (NEW, 312 lines)
- RULES_INDEX.md (+1 rule, +11 keyword entries)
```

### 3. User Review Decision

Check auto_commit flag and prompt user if needed.

**If auto_commit = true:**
- Skip user prompt
- Proceed to Step 4 (Commit)

**If auto_commit = false (default):**
- Show changes summary
- Show diff
- Prompt: "Commit these changes? (Y/n)"
- Wait for user response

**Prompt Format:**
```markdown
================================================================================
REVIEW CHANGES
================================================================================

[Changes summary above]

[Diff output]

================================================================================
READY TO COMMIT
================================================================================

These changes will be committed to git with an auto-generated message.

Commit? (Y/n): _
```

### 4. Handle User Response

**User Response: Y / y / yes / Yes (commit):**
- Proceed to Step 5

**User Response: n / no / No (abort):**
```markdown
Commit aborted.

Changes remain unstaged:
- rules/NNN-rule.md (modified)
- RULES_INDEX.md (modified)

You can:
- Review changes manually: git diff
- Commit later: git add [files] && git commit
- Discard changes: git checkout [files]
```
- Stop workflow
- No commit made

**User Response: v / view (view full diff):**
- Show complete file diffs
- Re-prompt: "Commit? (Y/n)"

**User Response: e / edit (manual edit before commit):**
```markdown
Opening files for manual edit.

After editing:
1. Save your changes
2. Run validation: uv run python scripts/schema_validator.py rules/NNN-rule.md
3. Commit manually: git add [files] && git commit -m "your message"

Aborting auto-commit.
```
- Stop workflow
- User commits manually

### 5. Generate Commit Message

Create descriptive commit message based on changes.

**Commit Message Format:**
```
feat|fix|docs: <brief description>

<detailed description>
- Change 1
- Change 2
- Change 3
```

**Type Selection:**
- **feat:** New rule created OR significant enhancement
- **fix:** Bug fix in existing rule
- **docs:** Documentation-only changes

**Example Messages:**

**New Rule:**
```
feat(python): add PostgreSQL connection pooling guidance

Created rules/207-python-postgres.md covering SQLAlchemy and psycopg2 
best practices for PostgreSQL connections.

- Connection pool configuration (pool_size, max_overflow, pool_pre_ping)
- Async patterns with asyncpg
- Environment-based credential management
- Anti-patterns (engine per request, default pool settings)
- Updated RULES_INDEX.md with 11 new keywords
```

**Enhanced Rule:**
```
feat(python): expand database guidance with SQLAlchemy patterns

Enhanced rules/200-python-core.md Section 4 with connection pooling 
patterns for SQLAlchemy and psycopg2.

- Added subsection "SQLAlchemy Connection Pooling"
- Configuration examples (pool_size, max_overflow, pool_pre_ping)
- Best practices for cloud databases
- Anti-patterns to avoid
- Updated metadata: +5 keywords, TokenBudget ~5200 → ~5800
- Updated RULES_INDEX.md
```

**Bug Fix:**
```
fix(python): correct SQLAlchemy connection pool parameters

Fixed incorrect pool configuration in rules/200-python-core.md.

- Changed pool_size from 20 to 5 (industry standard)
- Added missing pool_pre_ping parameter
- Updated example to show proper health checking
```

### 6. Stage Files

Add modified files to git staging area.

```bash
# Stage rule file
git add rules/NNN-rule.md

# Stage index
git add RULES_INDEX.md

# Verify staging
git status
```

**Expected Output:**
```
Changes to be committed:
  (use "git restore --staged <file>..." to unstage)
        modified:   RULES_INDEX.md
        modified:   rules/200-python-core.md

OR

        new file:   rules/207-python-postgres.md
        modified:   RULES_INDEX.md
```

### 7. Commit Changes

Execute git commit with generated message.

```bash
# Commit with message
git commit -m "$(cat <<'EOF'
feat(python): add PostgreSQL connection pooling guidance

Created rules/207-python-postgres.md covering SQLAlchemy and psycopg2 
best practices.

- Connection pool configuration
- Async patterns
- Environment-based credentials
- Updated RULES_INDEX.md
EOF
)"
```

**Verify Commit:**
```bash
# Show last commit
git log -1 --oneline

# Output:
# abc1234 feat(python): add PostgreSQL connection pooling guidance
```

### 8. Report Completion

Display summary of completed actions.

```markdown
================================================================================
COMMIT COMPLETE
================================================================================

✓ Changes committed successfully

Commit: abc1234
Message: feat(python): add PostgreSQL connection pooling guidance

Files committed:
- rules/207-python-postgres.md (NEW)
- RULES_INDEX.md (UPDATED)

Next steps:
1. Review commit: git show abc1234
2. Push to remote: git push origin main
3. (Optional) Create MR: Use rule-pr skill
================================================================================
```

## Outputs

**Commit Success:**
```markdown
Workflow Complete:
✓ Rule: rules/NNN-rule.md (created/enhanced)
✓ Validated: 0 CRITICAL errors
✓ Index: RULES_INDEX.md regenerated
✓ Committed: [commit-hash]
✓ Ready to push

Summary:
- [Enhanced/Created]: rules/NNN-rule.md
- Changes: [brief description]
- Keywords: [N terms]
- TokenBudget: ~[N]
```

**No Commit (User Declined):**
```markdown
Workflow Complete (Not Committed):
✓ Rule: rules/NNN-rule.md (created/enhanced)
✓ Validated: 0 CRITICAL errors
✓ Index: RULES_INDEX.md regenerated
✗ Not committed (user declined)

Unstaged changes:
- rules/NNN-rule.md
- RULES_INDEX.md

To commit manually:
git add rules/NNN-rule.md RULES_INDEX.md
git commit -m "your message"
```

## Examples

### Example 1: Auto-Commit Enabled

**Input:** auto_commit: true

**Execution:**
```
1. Generate diff ✓
2. Format summary ✓
3. Skip user prompt (auto_commit=true)
4. Generate commit message ✓
5. Stage files ✓
6. Commit ✓
7. Report completion ✓
```

**Output:**
```
✓ Changes committed: abc1234
✓ Files: rules/207-python-postgres.md, RULES_INDEX.md
```

### Example 2: User Review and Commit

**Input:** auto_commit: false

**Execution:**
```
1. Generate diff ✓
2. Format summary ✓
3. Prompt user:
   
   Commit? (Y/n): Y
   
4. User confirms ✓
5. Stage files ✓
6. Commit ✓
7. Report completion ✓
```

**Output:**
```
✓ Changes committed: def5678
✓ User approved commit
```

### Example 3: User Declines Commit

**Input:** auto_commit: false

**Execution:**
```
1. Generate diff ✓
2. Format summary ✓
3. Prompt user:
   
   Commit? (Y/n): n
   
4. User declines ✗
5. Report uncommitted changes
6. Stop workflow
```

**Output:**
```
Commit aborted by user.

Changes remain unstaged:
- rules/207-python-postgres.md
- RULES_INDEX.md

Commit manually when ready.
```

## Error Handling

**Git Not Available:**
```
If git command not found:
  ERROR: "Git not available"
  CHECK: Git installed and in PATH
  FALLBACK: Report success but skip commit
  DOCUMENT: "Manual commit required (git unavailable)"
```

**Staging Fails:**
```
If git add fails:
  LOG: Git error output
  CHECK: Files exist and are readable
  CHECK: Git repository initialized
  REPORT: Error to user
  STOP: Do not attempt commit
```

**Commit Fails:**
```
If git commit fails:
  LOG: Git error output
  COMMON CAUSES:
    - No user.name or user.email configured
    - Repository locked
    - Pre-commit hook failure
  REPORT: Error with fix suggestions
  LEAVE: Files staged (user can commit manually)
```

**Diff Generation Fails:**
```
If git diff fails or shows no changes:
  WARNING: "Cannot generate diff"
  CHECK: Files actually modified
  SHOW: File paths instead of diff
  CONTINUE: Ask user if commit needed
```

## Post-Commit Actions

**Optional Next Steps:**
```markdown
Workflow complete. Optional next actions:

1. Push to remote:
   git push origin main

2. Create merge request (if using GitLab):
   Use rule-pr skill

3. Review quality:
   Use rule-reviewer skill on newly created/enhanced rule

4. Test rule:
   Load rule in a test project and verify it works
```

## Next Steps

**Workflow Complete**
- All phases finished
- Rule created or enhanced
- Index updated
- Changes committed (if approved)
- Ready for push/MR (optional)
