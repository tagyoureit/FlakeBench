# Phase 3A: Enhance Existing Rule

Expand an existing rule with new content while preserving structure and style.

## Inputs from Phase 2

- Target rule file: `rules/NNN-technology-aspect.md`
- Coverage assessment: PARTIAL or MINIMAL
- Section to enhance: Existing section number or NEW
- Lesson learned: From Phase 1 conversation analysis

## Steps

### 1. Read Target Rule Thoroughly

```bash
# Read complete rule file
cat rules/NNN-target-rule.md
```

**Analyze:**
- Current structure (sections, subsections)
- Writing style (tone, format, examples)
- Metadata (Keywords, TokenBudget, ContextTier)
- Existing patterns (code blocks, lists, tables)
- Section numbering (if any) and naming conventions

**Example:**
```
rules/200-python-core.md analysis:
- Total sections: 12
- Style: Concise, imperative commands
- Examples: Code blocks with bash/python
- Lists: Bulleted with • for main, - for sub-items
- Token budget: ~5200
- Section 4: "Database Connections" (125 lines)
  - Current content: Generic database patterns
  - Subsections: Connection management, Error handling
  - Missing: SQLAlchemy patterns, connection pooling
```

### 2. Determine Content Placement

**Decision Logic:**

**Option A: Expand Existing Section**
- Use if: Section already exists and is related
- Example: Section 4 "Database Connections" exists, add SQLAlchemy patterns

**Option B: Create New Section**
- Use if: No existing section covers this topic
- Place after: Most related existing section
- Numbering: Continue existing sequence OR use descriptive heading

**Option C: Add Subsection**
- Use if: Section exists but topic is distinct
- Format: Follow existing subsection pattern (##, ###, or ####)

**Example Decision:**
```
Target: rules/200-python-core.md
Existing: Section 4 "Database Connections" (125 lines)
Content: Generic patterns, no SQLAlchemy
Decision: Expand Section 4 with new subsection
Placement: After "Error Handling" subsection
New subsection: "### SQLAlchemy Connection Pooling"
```

### 3. Draft New Content

**Follow Rule's Style:**
- Match tone (concise vs detailed, imperative vs explanatory)
- Match format (code block style, list format, headers)
- Match patterns (validation gates, anti-patterns, examples)

**Required Elements:**

**A. Core Guidance (2-4 paragraphs)**
```markdown
### SQLAlchemy Connection Pooling

When connecting to databases like PostgreSQL or Snowflake via SQLAlchemy, 
configure connection pooling explicitly to prevent connection exhaustion 
and improve performance.

**Required Configuration:**
- `pool_size`: Number of persistent connections (default: 5)
- `max_overflow`: Additional connections under load (default: 10)
- `pool_pre_ping`: Health check before using connection (recommended: True)
```

**B. Code Examples (1-3 blocks)**
```python
from sqlalchemy import create_engine

# Snowflake with psycopg2
engine = create_engine(
    "postgresql+psycopg2://user:pass@host/db",
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True
)
```

**C. Best Practices (3-5 bullets)**
```markdown
**Best Practices:**
- Always set `pool_pre_ping=True` for cloud databases
- Use `pool_recycle=3600` to prevent stale connections
- Monitor active connections with `engine.pool.status()`
- Close connections explicitly in teardown
```

**D. Anti-Patterns (2-3 bullets, if applicable)**
```markdown
**Avoid:**
- Creating new engine per request (use singleton pattern)
- Setting `pool_size` too high (causes connection exhaustion)
- Omitting `pool_pre_ping` for unstable networks
```

**E. Validation Gates (if applicable)**
```markdown
**Pre-Connection Validation:**
1. Check environment variables: DATABASE_URL, DB_PASSWORD
2. Verify network connectivity: `ping database_host`
3. Confirm SSL certificates if required
```

### 4. Update Metadata

Review if metadata needs updating after content addition.

**Keywords:**
- Add new search terms from lesson learned
- Keep total: 5-20 keywords
- Remove: Outdated or redundant keywords

**TokenBudget:**
- Update if change >20%
- Format: `~NUMBER` (e.g., ~5800)
- Calculate: Use token_validator.py or estimate (1 token ≈ 4 characters)

**ContextTier:**
- Adjust if importance changed significantly
- CRITICAL: Bootstrap rules, always-loaded foundations
- HIGH: Domain cores, frequently referenced
- MEDIUM: Specialized rules, loaded as needed
- LOW: Nice-to-have, rarely loaded

**Example:**
```markdown
Current metadata:
**Keywords:** python, core patterns, async, exceptions, typing, imports, testing
**TokenBudget:** ~5200
**ContextTier:** High

After enhancement:
**Keywords:** python, core patterns, async, exceptions, typing, imports, testing, 
              SQLAlchemy, postgres, psycopg2, connection pooling, database
**TokenBudget:** ~5800
**ContextTier:** High (unchanged)

Changes:
- Added: SQLAlchemy, postgres, psycopg2, connection pooling, database (+5 keywords)
- Total keywords: 7 → 12 (within 5-20 range)
- Token budget: ~5200 → ~5800 (+11%, update recommended)
```

### 5. Preserve Existing Patterns

**Critical Preservation Rules:**

**DO preserve:**
- Section numbering (if used)
- Header hierarchy (##, ###, ####)
- Code fence style (```python, ```bash, etc.)
- List markers (•, -, 1., a.)
- Existing validation gates
- Anti-pattern sections
- Example formatting

**DO NOT:**
- Rewrite existing content unless fixing errors
- Change numbering of other sections
- Alter code blocks in unrelated sections
- Modify metadata fields unrelated to your changes

**Example Preservation:**
```markdown
# BEFORE (existing Section 4)
## Database Connections

### Connection Management
[Existing content...]

### Error Handling  
[Existing content...]

# AFTER (with enhancement)
## Database Connections

### Connection Management
[Existing content preserved...]

### Error Handling
[Existing content preserved...]

### SQLAlchemy Connection Pooling
[NEW content added here...]
```

### 6. Make Changes

Execute the enhancement using StrReplace tool.

**Surgical Edit Pattern:**
```markdown
old_string: [Exact text from section where insertion happens]
new_string: [Same text + NEW content appended]
```

**Example:**
```python
# Surgical edit to add subsection
old_string: """### Error Handling

Always wrap database operations in try/except blocks.

[... existing content ...]

---"""

new_string: """### Error Handling

Always wrap database operations in try/except blocks.

[... existing content preserved ...]

### SQLAlchemy Connection Pooling

When connecting to databases like PostgreSQL or Snowflake via SQLAlchemy, 
configure connection pooling explicitly.

[... new content ...]

---"""
```

**Update Metadata:**
```python
# Update Keywords
old_string: """**Keywords:** python, core patterns, async, exceptions, typing, imports, testing"""

new_string: """**Keywords:** python, core patterns, async, exceptions, typing, imports, testing, SQLAlchemy, postgres, psycopg2, connection pooling, database"""

# Update TokenBudget
old_string: """**TokenBudget:** ~5200"""
new_string: """**TokenBudget:** ~5800"""
```

## Outputs

**Enhancement Summary:**
```markdown
Enhancement Complete:
✓ Target: rules/200-python-core.md
✓ Section: 4 "Database Connections"
✓ Added: Subsection "SQLAlchemy Connection Pooling" (47 lines)
✓ Content: Configuration, examples, best practices, anti-patterns
✓ Metadata updates:
  - Keywords: +5 (SQLAlchemy, postgres, psycopg2, connection pooling, database)
  - TokenBudget: ~5200 → ~5800 (+11%)
  - ContextTier: High (unchanged)
```

## Example Walkthrough

### Full Enhancement Example

**Target:** rules/200-python-core.md  
**Lesson:** SQLAlchemy connection pooling for Snowflake/Postgres

**Step 1: Read Target**
```bash
cat rules/200-python-core.md
# Analyze: 12 sections, Section 4 is "Database Connections"
```

**Step 2: Determine Placement**
```
Decision: Expand Section 4 with new subsection
Placement: After "Error Handling" subsection
Rationale: Database-related, fits naturally in existing section
```

**Step 3: Draft Content**
```markdown
### SQLAlchemy Connection Pooling

When connecting to databases like PostgreSQL or Snowflake via SQLAlchemy, 
configure connection pooling explicitly to prevent connection exhaustion.

**Required Configuration:**
```python
from sqlalchemy import create_engine

engine = create_engine(
    "postgresql+psycopg2://user:pass@host/db",
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600
)
```

**Best Practices:**
- Set `pool_pre_ping=True` for cloud databases (health check)
- Use `pool_recycle=3600` to prevent stale connections  
- Monitor: `engine.pool.status()` shows active connections
- Close explicitly in teardown: `engine.dispose()`

**Avoid:**
- Creating new engine per request (use singleton)
- Setting `pool_size` too high (causes exhaustion)
```

**Step 4: Update Metadata**
```markdown
Keywords: +5 new terms
TokenBudget: ~5200 → ~5800
ContextTier: High (no change)
```

**Step 5: Make Changes**
```python
# Use StrReplace tool
StrReplace(
    path="rules/200-python-core.md",
    old_string="""### Error Handling

[... exact existing content ...]""",
    new_string="""### Error Handling

[... exact existing content ...]

### SQLAlchemy Connection Pooling

[... new content ...]"""
)
```

**Step 6: Verify**
```bash
# Check file looks correct
cat rules/200-python-core.md | grep -A 5 "SQLAlchemy"
```

## Error Handling

**Section Not Found:**
```
If target section doesn't exist in rule:
  → Create new section instead
  → Document: "Added new Section [N]: [Name]"
  → Continue to validation
```

**Content Too Large:**
```
If new content >30% of rule size:
  → Warning: "Large addition, consider splitting into new rule"
  → ASK USER: "Proceed with enhancement or create new rule instead?"
  → Adjust based on response
```

**Metadata Update Failed:**
```
If TokenBudget or Keywords update fails:
  → Document attempted changes
  → Note: "Manual metadata verification needed"
  → Continue to validation (validator will catch errors)
```

**File Read Failed:**
```
If cannot read target rule file:
  → ERROR: "Cannot read rules/NNN-file.md"
  → Verify file exists: ls rules/
  → Ask user if file path correct
  → STOP if file doesn't exist
```

## Next Phase

**Proceed to:** `workflows/04-validate.md`

**Carry forward:**
- Modified rule file path
- Summary of changes
- Metadata updates
