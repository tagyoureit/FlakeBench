---
name: rule-learner
description: Intelligent rule creation and enhancement from conversation lessons. Analyzes what was learned, searches existing rules for coverage, decides whether to enhance existing or create new rule, then implements changes with validation. Single-invocation workflow eliminates manual orchestration. Use when capturing lessons learned from projects or discovering missing rule coverage.
version: 1.0.0
---

# Rule Learner

Intelligent rule creation and enhancement that automates the complete workflow from conversation analysis to validated rule changes.

## Overview

This skill combines conversation analysis, intelligent search, coverage assessment, and automated implementation into a single workflow. No manual orchestration required - just describe what was learned, and the skill handles the rest.

## Quick Start

### Usage (From Any Directory)

```
# You can be in ANY project directory
cd ~/projects/my-data-pipeline

Use rule-learner skill.

conversation_summary: "Struggled with psycopg2 connection pooling for Snowflake. 
Had to manually set pool_size=5 and max_overflow=10. Agent didn't know these 
SQLAlchemy best practices."
```

**Output:**
```
Phase 0: Locate Repository
✓ Found: /Users/rgoldin/Programming/ai_coding_rules
✓ Verified: Repository structure valid
✓ Context set: Changes will be made in repository
  Current directory: /Users/rgoldin/projects/my-data-pipeline (unchanged)

Phase 1-6: [Complete workflow...]
✓ Analyzed: postgres, SQLAlchemy, connection pooling, Snowflake
✓ Searched: 121 rules in /Users/rgoldin/Programming/ai_coding_rules/rules/
✓ Found: Partial coverage in rules/200-python-core.md
✓ Enhanced: Added Section 8 "Database Connection Pooling"
✓ Validated: 0 CRITICAL errors
✓ Updated: RULES_INDEX.md

Changes ready in: /Users/rgoldin/Programming/ai_coding_rules
Your project directory: /Users/rgoldin/projects/my-data-pipeline (unchanged)
```

## What This Skill Does

**Single invocation handles:**
1. **Analyzes** conversation or summary for lessons learned
2. **Searches** existing rules for coverage (prevents duplicates)
3. **Decides** whether to enhance existing rule or create new one
4. **Implements** changes following schema v3.2 standards
5. **Validates** with schema_validator.py
6. **Regenerates** RULES_INDEX.md
7. **Shows** diff for review

## When to Use

- After completing a project where agent learned new patterns
- When discovering missing rule coverage during work
- To capture authentication/setup issues that blocked progress
- To document technology-specific best practices agent didn't know
- When you want to improve the rule system without manual orchestration

## When NOT to Use

- For project-specific issues (database name typos, one-off network failures)
- For bugs in existing rule content (use rule-reviewer skill instead)
- For bulk rule audits (use bulk-rule-reviewer skill instead)
- For pure quality assessment (use rule-reviewer skill instead)

## Inputs

### Mode Selection (Choose One)

**When invoked, the skill will prompt:**
```
How would you like to provide the lesson learned?

A) Provide manual summary (you write what was learned)
B) Auto-analyze conversation (skill scans thread history)

Choice: _
```

**Option A: Manual Summary**

**conversation_summary**: `string` (100-500 words)
- What was learned during the project?
- What patterns emerged?
- What did the agent not know that it should have?
- What caused friction or repeated attempts?

**Examples:**
```markdown
"Snowflake REST API authentication failed with 401. Agent tried OAuth 
but never checked $SNOWFLAKE_PAT environment variable. This blocked 
pytest for 15 minutes."

"FastAPI async testing required @pytest.mark.asyncio decorator and 
httpx.AsyncClient. Agent used regular requests.get() which failed."

"Docker container didn't have sufficient permissions to write logs. 
Needed --user flag in docker run. Agent didn't check permissions first."
```

**Option B: Auto-Analyze**

**auto_analyze**: `true`
- Skill scans full conversation history
- Identifies patterns, failures, repeated attempts
- Extracts technologies and keywords
- Generates summary automatically
- Presents findings for your confirmation

**When to use auto-analyze:**
- Just finished debugging a problem
- Had multiple failed attempts visible in conversation
- Want to capture what happened without writing summary
- Conversation shows clear pattern of what agent learned

**Manual summary advantages:**
- More control over what's captured
- Can synthesize across multiple conversations
- Can add context not visible in current thread

### Optional Parameters

**severity**: `CRITICAL` | `HIGH` | `MEDIUM` | `LOW` (default: `MEDIUM`)
- Guides placement priority and urgency
- CRITICAL: Complete blockers
- HIGH: Required 3+ attempts or 5+ minutes
- MEDIUM: Suboptimal path, could be smoother
- LOW: Nice-to-have enhancements

**preferred_rule**: `string` (e.g., `rules/200-python-core.md`)
- Suggest specific rule to enhance (overrides search)
- Skill still validates coverage before proceeding
- Use when you know exactly where it should go

**create_new**: `boolean` (default: `false`)
- Force new rule creation (skip enhancement check)
- Use for entirely new technologies
- Still searches to avoid duplicates

**auto_commit**: `boolean` (default: `false`)
- Automatically commit changes after validation
- If false, shows diff and prompts user
- Recommended: Keep false for review

**timing_enabled**: `boolean` (default: `false`)
- Enable execution timing with skill-timing
- Tracks workflow phase durations

## Outputs

**If Enhancing Existing Rule:**
- Modified rule file: `rules/NNN-existing-rule.md`
- Updated metadata (Keywords, TokenBudget if >20% change)
- Regenerated: `RULES_INDEX.md`
- Diff showing changes

**If Creating New Rule:**
- New rule file: `rules/NNN-new-technology.md`
- Complete v3.2 schema-compliant structure
- Entry in: `RULES_INDEX.md` (correct numeric position)
- Validation: 0 CRITICAL errors

**No Overwrites:**
- Existing content preserved
- Sections added, not replaced
- Metadata updated incrementally

## Workflow

### Phase 0: Locate ai_coding_rules Repository

**See:** `workflows/00-locate-repo.md`

**What happens:**
1. Check environment variable: `$AI_CODING_RULES_REPO` (highest priority)
2. Check if current directory is ai_coding_rules repo
3. Search common locations: `~/Programming/ai_coding_rules`, `~/projects/ai_coding_rules`, etc.
4. Prompt user if not found (suggests setting environment variable)
5. Verify repository structure (rules/, AGENTS.md, scripts/)
6. Set `$AI_CODING_RULES_REPO` for all subsequent operations

**Critical:** This ensures changes are made in the ai_coding_rules repository, NOT your current project directory.

**Decision Gate:**
- If found and verified: Continue to Phase 1
- If not found: Prompt user for path, suggest setting environment variable, then continue
- If verification fails: Report error, provide options

**Example Output:**
```
Phase 0: Locate Repository
✓ Found $AI_CODING_RULES_REPO environment variable
✓ Repository: /Users/rgoldin/Programming/ai_coding_rules
✓ Verified: All required directories present
✓ Context set: Changes will be made in repository

Current directory: /Users/rgoldin/projects/my-app (unchanged)
```

### Phase 1: Analyze Conversation

**See:** `workflows/01-analyze.md`

**What happens:**
1. Parse conversation_summary for key concepts
2. Extract 5-10 keywords (technology, action, problem)
3. Identify domain (Python/Snowflake/JavaScript/Shell/etc.)
4. Assess rule-worthiness (generic vs project-specific)
5. Determine severity level

**Decision Gate:**
- If NOT rule-worthy (project-specific): STOP and report
- If rule-worthy: Continue to Phase 2

**Example Output:**
```
Analysis:
- Domain: Python
- Keywords: postgres, SQLAlchemy, connection pooling, Snowflake, psycopg2
- Severity: HIGH
- Rule-worthy: Yes (applies to all Python+Snowflake+Postgres projects)
```

### Phase 2: Search Existing Coverage

**See:** `workflows/02-search.md`

**What happens:**
1. Search `RULES_INDEX.md` by extracted keywords
2. Grep `rules/*.md` for matching content
3. Read top 3 matching rules
4. Assess coverage: Complete / Partial / Minimal / None
5. Apply placement hierarchy (topic-specific > domain > global)

**Decision Gate:**
- **Complete**: Rule already covers this → STOP and report
- **Partial/Minimal**: Path = Enhance existing rule → Phase 3A
- **None**: Path = Create new rule → Phase 3B

**Example Output:**
```
Search Results:
✓ Scanned: 121 rules
✓ Keyword matches: 
  - rules/200-python-core.md (4/5 keywords)
  - rules/100-snowflake-core.md (2/5 keywords)
✓ Coverage assessment: Partial in 200-python-core.md
✓ Decision: ENHANCE rules/200-python-core.md
✓ Rationale: Python-specific, SQLAlchemy belongs in Python domain
```

### Phase 3A: Enhance Existing Rule

**See:** `workflows/03a-enhance.md`

**What happens:**
1. Read target rule file
2. Analyze structure (sections, patterns)
3. Determine appropriate section (existing or new)
4. Draft content following rule's style
5. Update metadata if significant change:
   - Keywords: Add new search terms
   - TokenBudget: Update if >20% change
   - ContextTier: Adjust if importance changed
6. Preserve existing patterns and structure

**Example Output:**
```
Enhancement Plan:
- Target: rules/200-python-core.md
- Action: Add new Section 8 "Database Connection Pooling"
- Content: SQLAlchemy + psycopg2 patterns for Snowflake
- Metadata: +3 keywords (postgres, SQLAlchemy, pooling)
- TokenBudget: ~5200 → ~5800 (+11%)
```

### Phase 3B: Create New Rule

**See:** `workflows/03b-create.md`

**What happens:**
1. Determine rule number (domain + next available)
2. Run `template_generator.py` for structure
3. Research best practices (if online access)
4. Populate all sections (no placeholders):
   - Purpose / Scope
   - Quick Start TL;DR
   - Contract (Inputs, Mandatory, Forbidden, Execution Steps)
   - Key Principles
   - Anti-Patterns
   - Output Format Examples
5. Follow domain conventions

**Example Output:**
```
Creation Plan:
- Rule number: 445 (JavaScript domain, next available)
- Technology: DaisyUI
- Aspect: core
- Template: Generated via template_generator.py
- Research: Official docs + npm package info
- Sections: All 9 required sections populated
```

### Phase 4: Validate Changes

**See:** `workflows/04-validate.md`

**What happens:**
1. Run `uv run python scripts/schema_validator.py rules/NNN-rule.md`
2. Check for CRITICAL errors
3. If errors found: Fix automatically (if possible) or report
4. Loop until 0 CRITICAL errors
5. Verify metadata accuracy

**Success Criteria:**
- Exit code: 0
- CRITICAL errors: 0
- HIGH errors: Acceptable if intentional
- Metadata: Complete and accurate

### Phase 5: Regenerate Index

**See:** `workflows/05-finalize.md`

**What happens:**
1. Run `uv run python scripts/index_generator.py`
2. Verify new entry appears in correct numeric order
3. Check keywords propagated correctly
4. Generate diff for user review

### Phase 6: Review & Commit

**See:** `workflows/06-commit.md`

**What happens:**
1. Show complete diff (rule file + RULES_INDEX.md)
2. If `auto_commit: false`: Prompt "Commit changes? (Y/n)"
3. If `auto_commit: true` OR user confirms:
   - Stage changes: `git add rules/NNN-rule.md RULES_INDEX.md`
   - Generate commit message from changes
   - Commit: `git commit -m "feat: ..."`
4. Report completion with file locations

## Decision Logic

### Coverage Assessment

**Complete (No Action):**
- Rule already has comprehensive guidance
- Includes examples and best practices
- No gaps in coverage

**Partial (Enhance):**
- Rule mentions topic but lacks details
- Missing examples or specific patterns
- Has section but content sparse

**Minimal (Enhance):**
- Rule has 1-2 keyword matches only
- Topic tangentially related
- Opportunity to expand scope

**None (Create New):**
- Zero matches in existing rules
- Entirely new technology
- New domain or aspect

### Placement Hierarchy

**Priority Order (most specific wins):**

1. **Topic-Specific** (e.g., 118 REST API, 206 pytest)
   - Use if exact topic match exists
   - Example: SSE patterns → 118 REST API (not 100 Snowflake)

2. **Domain** (e.g., 200 Python, 100 Snowflake)
   - Use if topic-specific doesn't exist
   - Example: General SQLAlchemy → 200 Python

3. **Global** (e.g., 000 Core)
   - Use only if applies to ALL domains
   - Example: Investigation-first protocol

4. **New Rule** (only if no match + substantial content)
   - Use if entirely new technology
   - Require >1000 tokens of unique content

**Examples:**

```
Postgres connection pooling in Python:
├─ Topic-specific exists? → No
├─ Domain exists? → Yes (200 Python)
└─ Decision: Enhance 200-python-core.md

SSE parsing in Snowflake REST API:
├─ Topic-specific exists? → Yes (118 REST API)
├─ Is SSE REST-specific? → Yes
└─ Decision: Enhance 118-snowflake-rest-api-cortex-agents.md

DaisyUI component library:
├─ Topic-specific exists? → No
├─ Domain exists? → Yes (JavaScript)
├─ Substantial content? → Yes (>1000 tokens)
└─ Decision: Create 445-daisyui-core.md
```

## Important Notes

### Repository Detection

**The skill operates on the ai_coding_rules repository, not your current project.**

**Behavior:**
- Detects repo location automatically (Phase 0)
- Searches common locations (`~/Programming/ai_coding_rules`, etc.)
- Prompts for path if not found automatically
- Makes changes in ai_coding_rules, NOT current directory
- Your current project directory remains untouched

**Example:**
```bash
cd ~/projects/snowflake-pipeline  # Working here
Use rule-learner  # Changes ai_coding_rules repo, not snowflake-pipeline
```

### Rule-Worthiness Filters

**CREATE RULE FOR:**
- Generic patterns (applies across projects)
- Technology-specific guidance missing
- Repeated patterns (happened 2+ times)
- Authentication/environment setup blockers
- Best practices agent didn't know

**DO NOT CREATE RULE FOR:**
- Project-specific database/table names
- User typos or incorrect commands
- Network failures, API rate limits
- Environmental one-off issues
- "Agent should have tried harder" (persistence cannot be codified)

### Schema Compliance

All rules MUST comply with v3.2 schema:
- Required metadata fields (6)
- Required sections (Metadata, Scope, References, Contract)
- Contract subsections (Markdown ### headers)
- Keywords: 5-20 terms
- TokenBudget: ~NUMBER format
- No numbered section headings

**See:** `rules/002-rule-governance.md` for complete schema requirements

### Safety Constraints

- **Write only to:** `rules/` directory and `RULES_INDEX.md`
- **Never modify:** Schema files, validation scripts, core infrastructure
- **Preserve content:** Enhance, don't replace existing sections
- **Validate first:** Always run schema_validator.py before committing
- **Show diffs:** User reviews changes before commit

### Integration with Other Skills

**Replaces manual workflow:**
- Old: `/rule-improvement-analysis` → `/rule-governance` → manual commit
- New: `/rule-learner` (single invocation)

**Complements other skills:**
- **rule-reviewer**: Quality assessment of rules (score 0-100)
- **bulk-rule-reviewer**: Audit all rules at once
- **rule-pr**: Create GitLab MR (run after rule-learner commits)

**Use together:**
```bash
# Create/enhance rule
/rule-learner 
conversation_summary: "..."

# Review quality
/rule-reviewer
target_file: rules/200-python-core.md

# Create MR
/rule-pr
```

## Examples

See `examples/` directory for complete walkthroughs:
- `examples/enhance-existing.md` - Python+Postgres → Enhanced 200-python-core.md
- `examples/create-new.md` - DaisyUI → Created 445-daisyui-core.md
- `examples/complete-coverage.md` - Already covered → No action
- `examples/multiple-matches.md` - Multiple partial matches → Placement decision

## Testing

See `tests/` directory for validation tests:
- Input validation
- Keyword extraction
- Coverage assessment
- Enhancement logic
- Creation logic
- Schema validation loop

## Troubleshooting

**"Not rule-worthy":**
- Issue is project-specific, not generic
- Provide more context about why it's repeatable

**"Complete coverage found":**
- Rule already has this guidance
- Review suggested rule to confirm

**"Schema validation failed":**
- CRITICAL errors must be fixed
- Check metadata format, section order

**"Cannot determine domain":**
- Conversation summary too vague
- Specify technology explicitly

## References

**Dependencies:**
- `rules/000-global-core.md` - Foundation patterns
- `rules/002-rule-governance.md` - Schema v3.2 standards
- `rules/002a-rule-creation.md` - Rule authoring principles

**Scripts:**
- `scripts/template_generator.py` - Generate v3.2 templates
- `scripts/schema_validator.py` - Validate compliance
- `scripts/index_generator.py` - Regenerate RULES_INDEX.md

**Related Skills:**
- `rule-creator` - Manual rule creation (legacy)
- `rule-reviewer` - Quality assessment
- `bulk-rule-reviewer` - Bulk audits
- `rule-pr` - GitLab MR creation
