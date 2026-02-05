# Rule Learner Skill

**Version:** 1.0.0  
**Status:** Active  
**Type:** Internal-Only (ai_coding_rules maintenance)

## Overview

The **rule-learner** skill provides intelligent, automated rule creation and enhancement from conversation lessons. It combines conversation analysis, intelligent search, coverage assessment, and validated implementation into a single workflow - eliminating the need for manual orchestration of multiple skills.

**Critical Feature:** Works from any directory - detects and operates on your ai_coding_rules repository automatically, leaving your current project untouched.

## Purpose

Traditional workflow required 3 manual steps:
1. `/rule-improvement-analysis` - Analyze conversation
2. `/rule-governance` - Search and apply changes
3. Manual commit

**rule-learner** automates everything in one invocation:
```
/rule-learner 
conversation_summary: "learned something..."

→ Analyzes → Searches → Decides → Implements → Validates → Commits
```

## Quick Start

### Usage - Two Modes

**Mode A: Manual Summary** (You write what was learned)

```markdown
cd ~/projects/my-data-pipeline

Use rule-learner skill.
→ Choice: A (manual summary)
→ Provide: "Snowflake REST API auth failed with 401..."
```

**Mode B: Auto-Analyze** (Skill scans conversation)

```markdown
cd ~/projects/my-data-pipeline

Use rule-learner skill.
→ Choice: B (auto-analyze)
→ Skill scans full conversation
→ Presents findings for confirmation
→ You approve or edit
```

**What happens automatically:**
1. ✓ **Mode prompt:** Choose manual or auto-analyze
2. ✓ **Phase 0:** Locates ai_coding_rules repository
3. ✓ **Phase 1:** Analyzes conversation (scans if auto-analyze)
4. ✓ **Phase 2:** Searches 121 rules for coverage
5. ✓ **Phase 3:** Enhances or creates rule
6. ✓ **Phase 4:** Validates (auto-fixes errors)
7. ✓ **Phase 5:** Regenerates RULES_INDEX.md
8. ✓ **Phase 6:** Shows diff, commits if approved

**Result:**
```
✓ Changes made in: /Users/rgoldin/Programming/ai_coding_rules
✓ Current directory: /Users/rgoldin/projects/my-data-pipeline (unchanged)
✓ Rule updated: rules/118-snowflake-rest-api-cortex-agents.md
```

## Key Features

### 1. Intelligent Decision-Making

- **Searches first**: Won't create duplicates
- **Assesses coverage**: Complete / Partial / Minimal / None
- **Placement hierarchy**: Topic-specific > Domain > Global
- **Auto-fixes**: Schema errors corrected automatically

### 2. Single Invocation

No manual orchestration:
```
Old way: 3 separate skill calls + manual commit
New way: 1 skill call → done
```

### 3. Safe by Default

- Preserves existing content
- Shows diff before commit
- Validates against v3.2 schema
- Prompts for approval (unless `auto_commit: true`)

### 4. Comprehensive

Handles complete workflow:
- Phase 1: Analyze conversation
- Phase 2: Search existing rules
- Phase 3: Enhance or Create
- Phase 4: Validate changes
- Phase 5: Regenerate index
- Phase 6: Review & commit

## When to Use

✅ **Use when:**
- Just completed a project where agent learned new patterns
- Finished debugging and want to capture what was learned
- Had multiple failed attempts visible in conversation (auto-analyze)
- Discovered missing rule coverage during work
- Authentication/setup issue blocked progress
- Agent didn't know technology-specific best practices
- Want to capture lessons without manual workflow

**Auto-analyze works best when:**
- Clear pattern in recent conversation (errors, fixes, solution)
- Technologies visible (file extensions, commands, imports)
- User corrections or manual interventions present
- Failed attempts followed by working solution

**Manual summary better when:**
- Synthesizing across multiple conversations
- Adding context not visible in current thread
- Very long conversation (>200 messages)
- Pattern spans multiple sessions

❌ **Don't use when:**
- Issue is project-specific (database name typos)
- Bug in existing rule content (use `rule-reviewer` instead)
- Bulk rule audits needed (use `bulk-rule-reviewer`)
- Pure quality assessment (use `rule-reviewer`)

## Inputs

### Required

**conversation_summary:** `string` (100-500 words)

What did the agent learn that it should have known?

Examples:
- "FastAPI async testing required @pytest.mark.asyncio decorator..."
- "Docker container needed --user flag for write permissions..."
- "Snowflake REST API authentication checks $SNOWFLAKE_PAT env var..."

### Optional

**severity:** `CRITICAL` | `HIGH` | `MEDIUM` | `LOW` (default: `MEDIUM`)
- Guides placement priority
- CRITICAL: Complete blockers
- HIGH: Required 3+ attempts
- MEDIUM: Suboptimal path
- LOW: Nice-to-have

**preferred_rule:** `string` (e.g., `rules/200-python-core.md`)
- Suggest specific rule to enhance
- Still validates coverage before proceeding

**create_new:** `boolean` (default: `false`)
- Force new rule creation
- Still searches to avoid duplicates

**auto_commit:** `boolean` (default: `false`)
- Automatically commit after validation
- Recommended: Keep false for review

**timing_enabled:** `boolean` (default: `false`)
- Enable execution timing

## Outputs

### If Enhancing

- Modified rule file: `rules/NNN-existing.md`
- Updated metadata (Keywords, TokenBudget)
- Regenerated: `RULES_INDEX.md`
- Git commit (if approved)

### If Creating

- New rule file: `rules/NNN-new.md`
- Complete v3.2 schema structure
- Entry in `RULES_INDEX.md`
- Validated: 0 CRITICAL errors
- Git commit (if approved)

### If Already Covered

- Report: "Coverage already exists in [rule-file]"
- No changes made
- Reference to existing rule

## Workflow Phases

### Phase 0: Locate Repository

**See:** `workflows/00-locate-repo.md`

**CRITICAL FIRST STEP:** Detects ai_coding_rules repository location.

- Check if current directory is ai_coding_rules repo
- Search common locations: `~/Programming/ai_coding_rules`, `~/projects/ai_coding_rules`, etc.
- Prompt user if not found
- Verify repository structure (rules/, AGENTS.md, scripts/)
- Set `$AI_CODING_RULES_REPO` for all operations

**Why:** Ensures changes are made in ai_coding_rules repository, NOT your current project.

**Decision:** If found → Continue. If not found → Prompt for path and continue.

### Phase 1: Analyze

**See:** `workflows/01-analyze.md`

- Parse conversation summary
- Extract 5-10 keywords
- Identify domain (Python/Snowflake/JavaScript/etc.)
- Assess rule-worthiness
- Determine severity

**Decision:** Proceed if rule-worthy, stop if project-specific.

### Phase 2: Search

**See:** `workflows/02-search.md`

- Search RULES_INDEX.md by keywords
- Grep rules/*.md for content
- Read top 3 candidates
- Assess coverage: Complete / Partial / Minimal / None
- Apply placement hierarchy

**Decision:** STOP (complete), ENHANCE (partial/minimal), CREATE (none).

### Phase 3A: Enhance (if partial coverage)

**See:** `workflows/03a-enhance.md`

- Read target rule structure
- Determine section placement
- Draft new content following rule's style
- Update metadata (Keywords, TokenBudget)
- Make surgical edits

### Phase 3B: Create (if no coverage)

**See:** `workflows/03b-create.md`

- Determine rule number
- Generate v3.2 template
- Populate all required sections
- Research best practices (if online)
- Update token budget

### Phase 4: Validate

**See:** `workflows/04-validate.md`

- Run schema_validator.py
- Check for CRITICAL errors
- Auto-fix if possible (TokenBudget format, Keywords count)
- Loop until 0 CRITICAL errors
- Verify metadata accuracy

### Phase 5: Finalize

**See:** `workflows/05-finalize.md`

- Run index_generator.py
- Verify new/updated entry in RULES_INDEX.md
- Check numeric order
- Verify keyword propagation

### Phase 6: Review & Commit

**See:** `workflows/06-commit.md`

- Generate diff
- Format changes summary
- Prompt user (unless auto_commit=true)
- Stage files
- Commit with descriptive message
- Report completion

## Examples

### Example 1: Enhance Existing Rule (Manual Summary)

**See:** `examples/enhance-existing.md`

**Scenario:** SQLAlchemy connection pooling missing from Python rules

**Mode:** Manual summary provided

**Result:** Enhanced `rules/200-python-core.md` with new subsection

### Example 2: Auto-Analyze Conversation

**See:** `examples/auto-analyze.md`

**Scenario:** FastAPI async testing failures visible in conversation

**Mode:** Auto-analyze scans 87 messages, detects pattern

**Result:** Enhanced `rules/210-python-fastapi.md` with async testing patterns

### Example 3: Cross-Repository Workflow

**See:** `examples/cross-repo-workflow.md`

**Scenario:** Working in data pipeline, updating ai_coding_rules repo

**Mode:** Manual summary with explicit severity

**Result:** Enhanced Snowflake rule, current project untouched

## Comparison to Other Skills

### vs rule-improvement-analysis (Cortex)

**rule-improvement-analysis:**
- Analyzes conversation → Creates finding file
- Manual step 1 of 3

**rule-learner:**
- Analyzes conversation → Implements changes → Commits
- Complete automation

### vs rule-governance (Cortex)

**rule-governance:**
- Reads finding files → Applies to rules
- Manual step 2 of 3
- Requires retrospectives/ directory

**rule-learner:**
- Takes conversation summary directly
- No intermediate files
- Handles search → decision → implementation

### vs rule-creator (Local)

**rule-creator:**
- Creates new rules only
- No search for existing coverage
- Manual process

**rule-learner:**
- Searches first (prevents duplicates)
- Enhances OR creates as needed
- Fully automated workflow

### vs rule-reviewer (Local)

**rule-reviewer:**
- Reviews existing rules (quality assessment)
- Scores 0-100 on 6 dimensions
- No changes made

**rule-learner:**
- Creates/enhances rules from lessons
- Implements changes
- Complementary tool

## Integration with Other Skills

### Recommended Workflow

```bash
# 1. Capture lesson and create/enhance rule
/rule-learner
conversation_summary: "..."

# 2. Review quality of changes
/rule-reviewer
target_file: rules/NNN-rule.md

# 3. Create merge request (if using GitLab)
/rule-pr
```

### Skill Ecosystem

```
rule-learner (this skill)
├─ Replaces: rule-improvement-analysis + rule-governance workflow
├─ Complements: rule-reviewer (quality assessment)
├─ Complements: bulk-rule-reviewer (bulk audits)
└─ Complements: rule-pr (GitLab MR creation)
```

## Troubleshooting

### "Not rule-worthy"

**Issue:** Skill reports issue is project-specific

**Fix:** Provide more context about why it's a generic pattern

### "Complete coverage found"

**Issue:** Rule already documents this

**Fix:** Review suggested rule to confirm coverage is adequate

### "Schema validation failed"

**Issue:** CRITICAL errors after auto-fixes

**Fix:** Manually correct reported errors, skill will provide guidance

### "Cannot determine domain"

**Issue:** Conversation summary too vague

**Fix:** Specify technology explicitly: "Python + PostgreSQL", "Snowflake REST API", etc.

## Technical Details

### Schema Compliance

All rules must comply with v3.2 schema:
- Required metadata: SchemaVersion, RuleVersion, Keywords (5-20), TokenBudget (~NUMBER), ContextTier, Depends
- Required sections: Metadata, Scope, References, Contract
- Contract subsections: Markdown ### headers (not XML)
- No numbered section headings

### Dependencies

**Scripts:**
- `scripts/template_generator.py` - Generate v3.2 templates
- `scripts/schema_validator.py` - Validate compliance
- `scripts/index_generator.py` - Regenerate RULES_INDEX.md
- `scripts/token_validator.py` - Calculate token budgets

**Foundation Rules:**
- `rules/000-global-core.md` - Always loaded
- `rules/002-rule-governance.md` - Schema standards
- `rules/002a-rule-creation.md` - Authoring principles

### Safety Constraints

- Write only to `rules/` and `RULES_INDEX.md`
- Never modify validation scripts
- Preserve existing content
- Show diffs before committing
- Validate before committing

## Development

### Testing

See `tests/` directory for validation tests.

### Related Documentation

- `SKILL.md` - Full skill specification
- `workflows/` - Phase-by-phase workflow guides
- `examples/` - Complete walkthroughs
- `tests/` - Validation tests

## Changelog

### v1.0.0 (2026-01-21)

- Initial release
- Combines rule-improvement-analysis + rule-governance workflows
- Single-invocation automation
- Intelligent search and coverage assessment
- Auto-fixes for schema errors
- Complete validation and index regeneration
