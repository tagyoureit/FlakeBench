# Phase 2: Search Existing Coverage

Search existing rules to determine if coverage already exists and decide between enhancement vs creation.

## Inputs from Phase 1

- Domain: Rule domain range (100-series, 200-series, etc.)
- Keywords: 5-10 extracted keywords
- Severity: CRITICAL/HIGH/MEDIUM/LOW

## Steps

### 1. Search RULES_INDEX.md

```bash
# Search index for each keyword
grep -i "keyword1" RULES_INDEX.md
grep -i "keyword2" RULES_INDEX.md
grep -i "keyword3" RULES_INDEX.md
```

**Collect matching rules:**
- Note rule filenames
- Count keyword matches per rule
- Rank by relevance (most matches = highest relevance)

**Example:**
```bash
grep -i "postgres" RULES_INDEX.md
grep -i "SQLAlchemy" RULES_INDEX.md
grep -i "connection" RULES_INDEX.md

Results:
- rules/200-python-core.md (3 matches)
- rules/100-snowflake-core.md (1 match)
```

### 2. Grep Rules Directory

Search rule files directly for content matches:

```bash
# Search all rules for keywords (case-insensitive)
grep -l -i "keyword1\|keyword2\|keyword3" rules/*.md
```

**Combine results:**
- Merge RULES_INDEX.md matches with grep results
- Rank by: (keyword matches) + (domain relevance)
- Select top 3 candidates

**Domain Relevance Scoring:**
```
Same domain as Phase 1 determination: +10 points
Adjacent domain (e.g., 100 when looking at Snowflake+Python): +5 points
Different domain: +0 points
```

**Example:**
```bash
grep -l -i "postgres\|sqlalchemy\|connection" rules/*.md

Combined Results (ranked):
1. rules/200-python-core.md (4 keywords, +10 domain match) = Score: 14
2. rules/100-snowflake-core.md (2 keywords, +5 adjacent) = Score: 7
3. rules/203-python-project-setup.md (1 keyword, +10 domain) = Score: 11
```

### 3. Read Top Candidates

Read the top 3 matching rules to assess coverage.

**For each rule:**
1. Read full file contents
2. Note existing sections
3. Check if lesson learned is covered
4. Assess coverage depth

**Coverage Levels:**

**COMPLETE:**
- Topic has dedicated section with examples
- Best practices documented
- Error handling covered
- Nothing substantive to add

**PARTIAL:**
- Topic mentioned in 1-2 places
- Basic guidance exists but lacks detail
- Missing examples or specific patterns
- Could be significantly expanded

**MINIMAL:**
- 1-2 keyword matches only
- Topic tangentially related
- Brief mention, no detailed guidance
- Room for new section

**NONE:**
- Keywords present but different context
- Unrelated content
- False match

**Example Assessment:**
```
rules/200-python-core.md:
- Sections: 12 total
- Section 4: "Database Connections" exists
  - Content: Generic database patterns, no SQLAlchemy specifics
  - Examples: sqlite3 only, no postgres/psycopg2
  - Connection pooling: Not mentioned
- Assessment: PARTIAL coverage
- Opportunity: Expand Section 4 with SQLAlchemy + pooling patterns
```

### 4. Apply Placement Hierarchy

Determine where new content should go using placement hierarchy.

**Priority Order (most specific wins):**

```
1. Topic-Specific Rule
   ├─ Examples: 118 REST API, 206 pytest, 115 Cortex Agents
   └─ Use if: Exact topic match exists

2. Domain Rule  
   ├─ Examples: 100 Snowflake, 200 Python, 400 JavaScript
   └─ Use if: Topic-specific doesn't exist

3. Global Rule
   ├─ Examples: 000 Core, 001 Memory Bank
   └─ Use if: Applies to ALL domains

4. Create New Rule
   └─ Use if: No match + substantial content (>1000 tokens)
```

**Decision Tree:**

```
Lesson learned: "SQLAlchemy connection pooling for Snowflake"

Check topic-specific:
  → 206-python-pytest? No (testing-specific)
  → 210-python-fastapi? No (web framework-specific)
  → Topic-specific match: NONE

Check domain:
  → 200-python-core? Yes (Python domain)
  → Has database section? Yes (Section 4)
  → Coverage: PARTIAL
  → Decision: ENHANCE 200-python-core.md

Rationale: SQLAlchemy is Python-specific, not Snowflake-specific. 
Connection pooling is core database pattern, not framework-specific.
```

### 5. Make Coverage Decision

Based on assessment, decide path forward.

**Decision Matrix:**

| Coverage | Same Domain | Adjacent Domain | No Match | Decision |
|----------|-------------|-----------------|----------|----------|
| COMPLETE | N/A | N/A | N/A | **STOP** (already covered) |
| PARTIAL | **ENHANCE** | **ENHANCE** | **CREATE** | Most common path |
| MINIMAL | **ENHANCE** | Consider both | **CREATE** | Judgment call |
| NONE | **CREATE** | **CREATE** | **CREATE** | New rule needed |

**STOP (Complete Coverage):**
```
Output: "✓ Coverage already exists in [rule-file]
         Section: [section name]
         No action needed. Rule already has comprehensive guidance on this topic."
Report to user with reference
```

**ENHANCE (Partial/Minimal Coverage):**
```
Output: "✓ Found partial coverage in [rule-file]
         ✓ Decision: ENHANCE existing rule
         ✓ Target: [rule-file] Section [N or NEW]
         ✓ Rationale: [Why this rule, not others]"
Proceed to Phase 3A: Enhance Existing Rule
```

**CREATE (No Coverage):**
```
Output: "✓ No existing coverage found
         ✓ Decision: CREATE new rule
         ✓ Domain: [NNN-series]
         ✓ Rule number: [next available]
         ✓ Rationale: [Why new rule needed]"
Proceed to Phase 3B: Create New Rule
```

## Outputs

**Search Results Summary:**
```markdown
Search Results:
✓ Scanned: 121 rules
✓ RULES_INDEX.md matches: [N] rules
✓ Content grep matches: [N] rules
✓ Top candidates:
  1. rules/[file].md ([N] keywords, [coverage level])
  2. rules/[file].md ([N] keywords, [coverage level])
  3. rules/[file].md ([N] keywords, [coverage level])

✓ Coverage assessment: [COMPLETE/PARTIAL/MINIMAL/NONE]
✓ Decision: [STOP/ENHANCE/CREATE]
✓ Target: [rule-file or new rule number]
✓ Rationale: [Why this decision]
```

## Example Walkthroughs

### Example 1: ENHANCE (Partial Coverage)

**Input from Phase 1:**
```
Domain: 200-Python
Keywords: postgres, SQLAlchemy, connection pooling, Snowflake, psycopg2
Severity: HIGH
```

**Search:**
```bash
grep -i "sqlalchemy\|postgres\|connection" RULES_INDEX.md
→ rules/200-python-core.md (3 matches)

grep -l -i "sqlalchemy\|postgres\|connection" rules/*.md  
→ rules/200-python-core.md
→ rules/100-snowflake-core.md
```

**Read Candidates:**
```
rules/200-python-core.md:
- Section 4: "Database Connections" exists
- Content: Generic patterns, no SQLAlchemy specifics
- Coverage: PARTIAL

rules/100-snowflake-core.md:
- Mentions connections in Streamlit context
- Coverage: MINIMAL
```

**Placement Hierarchy:**
```
Topic-specific? No
Domain match? Yes (200-python-core.md)
Coverage: PARTIAL
Decision: ENHANCE 200-python-core.md
```

**Output:**
```
✓ Found partial coverage in rules/200-python-core.md
✓ Decision: ENHANCE existing rule  
✓ Target: Section 4 (expand with SQLAlchemy patterns)
✓ Rationale: Python-specific patterns, domain rule has database section
```

**Next:** → Phase 3A: Enhance

### Example 2: CREATE (No Coverage)

**Input from Phase 1:**
```
Domain: 400-Frontend
Keywords: DaisyUI, Tailwind, components, themes, JavaScript
Severity: MEDIUM
```

**Search:**
```bash
grep -i "daisyui\|tailwind" RULES_INDEX.md
→ No matches

grep -l -i "daisyui\|tailwind" rules/*.md
→ No matches
```

**Read Candidates:**
```
rules/420-javascript-core.md:
- No mention of UI frameworks
- Coverage: NONE

rules/430-typescript-core.md:
- No mention of CSS frameworks
- Coverage: NONE
```

**Placement Hierarchy:**
```
Topic-specific? No (no UI framework rules exist)
Domain match? 400-series (Frontend/Containers)
Coverage: NONE
Substantial content? Yes (>1000 tokens of DaisyUI patterns)
Decision: CREATE new rule
```

**Output:**
```
✓ No existing coverage found
✓ Decision: CREATE new rule
✓ Domain: 400-series (Frontend)
✓ Rule number: 445 (next available)
✓ Rationale: New technology, substantial content, fits frontend domain
```

**Next:** → Phase 3B: Create

### Example 3: STOP (Complete Coverage)

**Input from Phase 1:**
```
Domain: 200-Python
Keywords: pytest, async, decorator, mark
Severity: LOW
```

**Search:**
```bash
grep -i "pytest\|async" RULES_INDEX.md
→ rules/206-python-pytest.md (4 matches)
```

**Read Candidates:**
```
rules/206-python-pytest.md:
- Section 5: "Async Testing" exists
- Content: @pytest.mark.asyncio decorator documented
- Examples: Multiple async test examples with httpx.AsyncClient
- Best practices: Covered comprehensively
- Coverage: COMPLETE
```

**Output:**
```
✓ Coverage already exists in rules/206-python-pytest.md
✓ Section: 5 "Async Testing"  
✓ Content: @pytest.mark.asyncio decorator and patterns documented
✓ Decision: STOP (no action needed)
```

**Report to user:**
```
This topic is already covered in rules/206-python-pytest.md, 
Section 5 "Async Testing". The rule includes examples with 
@pytest.mark.asyncio and httpx.AsyncClient patterns.

No new rule needed.
```

## Error Handling

**No Matches Found:**
```
If both RULES_INDEX.md and grep return 0 matches:
  → Decision: CREATE (likely new technology)
  → Verify domain determination is correct
  → Proceed to Phase 3B
```

**Too Many Matches:**
```
If >10 rules match keywords:
  → Filter by domain relevance
  → Take top 3 by combined score
  → If still ambiguous, prefer domain-level rules over topic-specific
```

**Ambiguous Coverage:**
```
If multiple rules have similar coverage levels:
  → Apply placement hierarchy
  → Prefer: Topic-specific > Domain > Global
  → Document: "Multiple candidates, chose [X] because [reason]"
```

## Next Phase

**If Decision = STOP:**
- Report complete coverage to user
- End workflow

**If Decision = ENHANCE:**
- **Proceed to:** `workflows/03a-enhance.md`
- **Carry forward:** Target rule file, section, coverage assessment

**If Decision = CREATE:**
- **Proceed to:** `workflows/03b-create.md`
- **Carry forward:** Domain, rule number, keywords
