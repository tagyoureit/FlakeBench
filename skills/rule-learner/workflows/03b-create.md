# Phase 3B: Create New Rule

Generate a new rule file from scratch following v3.2 schema standards.

## Inputs from Phase 2

- Domain: Rule domain range (NNN-series)
- Rule number: Next available number in domain
- Keywords: 5-10 extracted keywords
- Lesson learned: From Phase 1 conversation analysis
- Severity: CRITICAL/HIGH/MEDIUM/LOW

## Steps

### 1. Determine Rule Number

Find next available number in target domain.

```bash
# List existing rules in domain
ls rules/[domain-prefix]*.md | sort

# Examples:
ls rules/200-*.md | sort  # Python domain
ls rules/445-*.md | sort  # JavaScript UI frameworks
```

**Numbering Strategy:**

**Sequential (preferred):**
- Next available integer in domain
- Example: 200, 201, 202, ... 206, 207 (next available)

**Split Pattern (if crowded):**
- Use letter suffix for subtopics
- Example: 115a, 115b, 115c (Cortex subtopics)
- Only use when: >50 rules in domain OR logical grouping

**Example:**
```bash
ls rules/200-*.md | sort
# Output:
# 200-python-core.md
# 201-python-async.md
# 203-python-project-setup.md
# 206-python-pytest.md

# Next available: 207
# New rule: 207-python-postgres.md
```

### 2. Generate Template

Use template_generator.py to create v3.2 compliant structure.

```bash
cd /Users/rgoldin/Programming/ai_coding_rules

# Generate template
uv run python scripts/template_generator.py \
  207-python-postgres \
  --tier High
```

**What template_generator.py creates:**
- All required metadata fields (SchemaVersion, RuleVersion, Keywords, etc.)
- Required sections (Metadata, Scope, References, Contract)
- Contract subsections (Inputs, Mandatory, Forbidden, Execution Steps, etc.)
- Placeholder content following v3.2 schema

**Template structure:**
```markdown
# Python PostgreSQL Best Practices

**SchemaVersion:** v3.2
**RuleVersion:** v1.0.0
**LastUpdated:** YYYY-MM-DD
**Keywords:** [PLACEHOLDER - ADD 5-20 KEYWORDS]
**TokenBudget:** ~1000
**ContextTier:** High
**Depends:** rules/000-global-core.md, rules/200-python-core.md

## Scope

[PLACEHOLDER - WHAT THIS RULE COVERS]

## References

### Dependencies
[...]

### External Documentation
[...]

## Contract

### Inputs and Prerequisites
[...]

### Mandatory
[...]

[... all other required sections ...]
```

### 3. Populate Metadata

Replace placeholders with accurate metadata.

**Keywords (5-20 terms):**
- Use keywords from Phase 1 extraction
- Add domain keyword (python, snowflake, javascript)
- Add technology keywords (postgres, sqlalchemy, psycopg2)
- Add pattern keywords (connection pooling, async, testing)

**TokenBudget:**
- Initial estimate: ~1500 for new rules
- Will be updated after content population
- Format: `~NUMBER`

**ContextTier:**
- Use severity from Phase 1 as guide:
  - CRITICAL severity → High tier
  - HIGH severity → High or Medium tier
  - MEDIUM/LOW severity → Medium or Low tier
- Consider: How often will this rule be loaded?

**Depends:**
- Always include: `rules/000-global-core.md`
- Include domain core: `rules/200-python-core.md` (for Python)
- Include related rules if applicable

**LastUpdated:**
- Use current date: YYYY-MM-DD format

**Example:**
```markdown
**SchemaVersion:** v3.2
**RuleVersion:** v1.0.0
**LastUpdated:** 2026-01-21
**Keywords:** python, postgres, postgresql, SQLAlchemy, psycopg2, connection pooling, database, async, best practices, environment setup, configuration
**TokenBudget:** ~1500
**ContextTier:** High
**Depends:** rules/000-global-core.md, rules/200-python-core.md
```

### 4. Write Scope Section

Define what the rule covers and when to load it.

**Format:**
```markdown
## Scope

**What This Rule Covers:**
[2-3 sentences defining the problem space and solutions]

**When to Load This Rule:**
- [Specific trigger 1]
- [Specific trigger 2]
- [Specific trigger 3]
```

**Example:**
```markdown
## Scope

**What This Rule Covers:**
PostgreSQL database integration patterns for Python applications using SQLAlchemy and psycopg2. Covers connection pooling configuration, async patterns, environment setup, and common pitfalls when connecting to cloud databases like Snowflake.

**When to Load This Rule:**
- Working with PostgreSQL databases in Python
- Configuring SQLAlchemy for production deployments
- Troubleshooting connection pool exhaustion
- Setting up async database operations
- Integrating psycopg2 with cloud platforms
```

### 5. Write References Section

Document dependencies and external resources.

**Format:**
```markdown
## References

### Dependencies

**Must Load First:**
- **000-global-core.md** - Foundation for all rules
- **200-python-core.md** - Python core patterns

**Related:**
- **206-python-pytest.md** - Testing database code
- **203-python-project-setup.md** - Environment configuration

### External Documentation

**Official Documentation:**
- [SQLAlchemy Engine Configuration](https://docs.sqlalchemy.org/en/latest/core/engines.html)
- [psycopg2 Documentation](https://www.psycopg.org/docs/)
- [PostgreSQL Connection Pooling](https://www.postgresql.org/docs/current/runtime-config-connection.html)

**Best Practices:**
- [12-Factor App: Backing Services](https://12factor.net/backing-services)
```

### 6. Write Contract Section

Define inputs, requirements, forbidden patterns, and execution steps.

**Critical subsections (all required):**

**A. Inputs and Prerequisites**
```markdown
### Inputs and Prerequisites

- Python environment with SQLAlchemy installed
- PostgreSQL database accessible (local or cloud)
- Database credentials (username, password, host, port, database name)
- Understanding of connection pooling concepts
```

**B. Mandatory**
```markdown
### Mandatory

- SQLAlchemy >= 1.4 or 2.0
- psycopg2 or psycopg2-binary driver
- Environment variables for sensitive credentials
- Connection pool configuration (pool_size, max_overflow)
```

**C. Forbidden**
```markdown
### Forbidden

- Hardcoding database credentials in source code
- Creating new engine instance per request
- Using default pool settings for production
- Omitting connection health checks (pool_pre_ping)
```

**D. Execution Steps**
```markdown
### Execution Steps

1. Install required packages: `pip install SQLAlchemy psycopg2-binary`
2. Configure environment variables: DATABASE_URL, DB_PASSWORD
3. Create engine with explicit pool configuration
4. Implement connection lifecycle management
5. Add health checks and monitoring
6. Test connection pooling under load
```

**E. Output Format**
```markdown
### Output Format

Configured SQLAlchemy engine with:
- Persistent connection pool (5-10 connections)
- Health checking enabled (pool_pre_ping=True)
- Stale connection recycling (pool_recycle=3600)
- Connection status monitoring available
```

**F. Validation**
```markdown
### Validation

**Pre-Task-Completion Checks:**
- [ ] Engine created successfully
- [ ] Pool configuration verified
- [ ] Test query executes without errors
- [ ] Connection pool status accessible

**Success Criteria:**
- Engine connects to database
- Pool maintains configured connection count
- Health checks detect stale connections
- No connection leaks under load
```

**G. Post-Execution Checklist**
```markdown
### Post-Execution Checklist

- [ ] Engine configured with explicit pool settings
- [ ] Environment variables used for credentials
- [ ] Health checking enabled (pool_pre_ping)
- [ ] Connection recycling configured
- [ ] Monitoring added for pool status
- [ ] Teardown/cleanup implemented
```

### 7. Write Key Principles Section

Document core concepts and patterns.

**Format:**
- 3-5 major principles
- Each principle: 2-4 paragraphs or code block
- Use descriptive headings (not numbered)

**Example:**
```markdown
## Key Principles

### Connection Pool Configuration

SQLAlchemy's connection pool prevents connection exhaustion by reusing 
persistent connections. Configure pool_size and max_overflow based on 
application load.

```python
from sqlalchemy import create_engine

engine = create_engine(
    f"postgresql+psycopg2://{user}:{password}@{host}/{database}",
    pool_size=5,           # Persistent connections
    max_overflow=10,       # Additional under load
    pool_pre_ping=True,    # Health check before use
    pool_recycle=3600      # Recycle after 1 hour
)
```

### Environment-Based Configuration

Never hardcode credentials. Use environment variables and configuration files.

```python
import os
from sqlalchemy import create_engine

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable not set")

engine = create_engine(DATABASE_URL, pool_size=5, max_overflow=10)
```

### Connection Health Monitoring

Monitor active connections to detect leaks and exhaustion.

```python
# Check pool status
status = engine.pool.status()
print(f"Active: {status}")

# Verify connection health
with engine.connect() as conn:
    result = conn.execute("SELECT 1")
```
```

### 8. Write Anti-Patterns Section

Document common mistakes and how to avoid them.

**Format:**
```markdown
## Anti-Patterns and Common Mistakes

### Anti-Pattern 1: Creating Engine Per Request

**Problem:** Creating new engine for each request causes connection exhaustion.

**Why It Fails:** Engine creation is expensive and bypasses connection pooling.

**Correct Pattern:**
```python
# BAD: New engine per request
def handler(request):
    engine = create_engine(DATABASE_URL)  # Don't do this
    # ...

# GOOD: Singleton engine
engine = create_engine(DATABASE_URL, pool_size=5)

def handler(request):
    with engine.connect() as conn:  # Reuses pooled connection
        # ...
```
```

### 9. Add Examples Section

Provide complete, working code examples.

**Format:**
- Full working code (not snippets)
- Show common use cases
- Include error handling
- Add comments explaining key points

**Example:**
```markdown
## Output Format Examples

### Basic Connection with Pooling

```python
from sqlalchemy import create_engine, text
import os

# Load from environment
DATABASE_URL = os.getenv("DATABASE_URL")

# Create engine with pooling
engine = create_engine(
    DATABASE_URL,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False  # Set True for SQL logging
)

# Test connection
with engine.connect() as conn:
    result = conn.execute(text("SELECT version()"))
    print(f"Database: {result.scalar()}")

# Check pool status
print(f"Pool status: {engine.pool.status()}")
```

### Async Connection Pattern

```python
from sqlalchemy.ext.asyncio import create_async_engine
import asyncio

async def main():
    engine = create_async_engine(
        "postgresql+asyncpg://user:pass@host/db",
        pool_size=5,
        max_overflow=10
    )
    
    async with engine.begin() as conn:
        result = await conn.execute(text("SELECT 1"))
        print(result.scalar())
    
    await engine.dispose()

asyncio.run(main())
```
```

### 10. Update Token Budget

After all content written, calculate accurate token budget.

```bash
# Use token validator
uv run python scripts/token_validator.py rules/207-python-postgres.md

# Output will show actual tokens
# Update TokenBudget field with ~NUMBER format
```

**Example:**
```
Token validator output: 4,234 tokens
Update metadata: **TokenBudget:** ~4200
```

## Outputs

**New Rule File:**
- Location: `rules/NNN-technology-aspect.md`
- Format: v3.2 schema compliant
- Status: Ready for validation
- Content: All sections populated (no placeholders)

**Creation Summary:**
```markdown
New Rule Created:
✓ File: rules/207-python-postgres.md
✓ Domain: 200-series (Python)
✓ Sections: 9 (all required sections complete)
✓ Metadata: Complete (Keywords, TokenBudget, ContextTier, Depends)
✓ Examples: 3 code blocks with full implementations
✓ TokenBudget: ~4200 tokens
```

## Example Walkthrough

### Full Creation Example

**Input:**
```
Domain: 200-Python
Rule number: 207
Technology: PostgreSQL + SQLAlchemy
Lesson: Connection pooling configuration for Snowflake
```

**Step 1: Determine Number**
```bash
ls rules/200-*.md | sort
# Shows: 200, 201, 203, 206
# Next available: 207
```

**Step 2: Generate Template**
```bash
uv run python scripts/template_generator.py 207-python-postgres --tier High
# Creates: rules/207-python-postgres.md with v3.2 structure
```

**Step 3-9: Populate All Sections**
[Follow steps above, populate metadata, scope, references, contract, 
key principles, anti-patterns, examples]

**Step 10: Update Token Budget**
```bash
uv run python scripts/token_validator.py rules/207-python-postgres.md
# Output: 4,234 tokens
# Update: **TokenBudget:** ~4200
```

**Result:**
```markdown
✓ New rule: rules/207-python-postgres.md
✓ All sections complete
✓ Ready for validation
```

## Error Handling

**Template Generator Failed:**
```
If template_generator.py fails:
  → Check if scripts/ directory accessible
  → Verify uv environment active
  → Manual fallback: Copy structure from similar rule
  → Document: "Manual template creation used"
```

**Rule Number Collision:**
```
If NNN-file.md already exists:
  → Find next available number
  → OR use split pattern (NNNa, NNNb)
  → Document: "Used [number] due to collision"
```

**Incomplete Content:**
```
If cannot populate all sections:
  → Document which sections incomplete
  → Mark with: [TODO: COMPLETE THIS SECTION]
  → Proceed to validation (will catch issues)
  → User can complete manually if needed
```

## Next Phase

**Proceed to:** `workflows/04-validate.md`

**Carry forward:**
- New rule file path
- Token budget (for verification)
- Metadata for index generation
