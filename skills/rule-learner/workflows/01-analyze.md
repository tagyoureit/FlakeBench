# Phase 1: Analyze Conversation

Parse conversation to extract lessons learned and assess rule-worthiness.

## Inputs

- `conversation_summary`: User-provided description (100-500 words) OR
- `auto_analyze`: true (scan conversation automatically)
- `severity`: Optional severity level

## Mode Selection

**FIRST: Prompt user for input mode**

```
════════════════════════════════════════════════════════════════════════
Rule Learner - Input Mode
════════════════════════════════════════════════════════════════════════

How would you like to provide the lesson learned?

A) Provide manual summary
   → You write a brief description of what was learned
   → Best for: Synthesizing multiple sessions, adding external context

B) Auto-analyze conversation
   → Skill scans full conversation history automatically
   → Best for: Just finished debugging, pattern is clear in thread

Choice (A/B): _
════════════════════════════════════════════════════════════════════════
```

**If A (Manual):** 
- Prompt: "Please provide conversation_summary (100-500 words):"
- Wait for user input
- Continue to Step 1 (Parse Summary)

**If B (Auto-Analyze):**
- Continue to Step 1A (Auto-Analyze)

## Steps

### 1A. Auto-Analyze Conversation (If auto_analyze = true)

Scan full conversation history to identify patterns.

**Scan Parameters:**
- Scope: Full conversation (all messages in context window)
- Look back: From beginning of conversation to current message
- Focus: Last 100 messages if conversation is very long

**Pattern Detection:**

**A. Identify Problem Indicators**
```markdown
Scan for:
- Error messages (401, 403, 500, exceptions, stack traces)
- Failed commands (exit codes, "command not found", "permission denied")
- Repeated attempts (same command tried 2+ times with modifications)
- User corrections ("actually try this", "no, do it this way")
- Manual fixes ("I had to manually...", "I fixed it by...")
- Frustration signals ("why didn't you", "this should have worked")
```

**B. Extract Technologies**
```markdown
From messages, identify:
- Languages: File extensions (.py, .sql, .js, .go, .sh)
- Frameworks: Import statements, package names (FastAPI, pytest, SQLAlchemy)
- Tools: Commands run (docker, git, npm, uv, pip)
- Platforms: Mentioned explicitly (Snowflake, AWS, PostgreSQL)
```

**C. Extract Keywords**
```markdown
From problem and solution:
- Technical terms (authentication, pooling, async, configuration)
- Specific features (REFRESH_MODE, pool_size, @pytest.mark.asyncio)
- Actions taken (environment variable, config file, parameter)
```

**D. Identify Solution**
```markdown
What worked:
- Successful commands (exit code 0 after failures)
- Configuration changes that resolved issue
- Environment variables set
- Code changes that fixed problem
```

**E. Generate Summary**
```markdown
Template:
"[Technology] [problem] occurred. Agent [what agent did wrong]. 
User [manual intervention]. Solution: [what fixed it]. 
This blocked progress for [time estimate]."

Example:
"Snowflake REST API authentication failed with 401. Agent tried OAuth 
token validation but never checked $SNOWFLAKE_PAT environment variable. 
User manually exported SNOWFLAKE_PAT. Solution: Check for SNOWFLAKE_PAT 
env var before other auth methods. This blocked pytest execution for 15 minutes."
```

**F. Determine Severity**
```markdown
Auto-detect severity:
- CRITICAL: Complete blocker, couldn't proceed (>10 min delay)
- HIGH: Required 3+ attempts or 5+ minutes
- MEDIUM: 1-2 attempts, suboptimal path
- LOW: Works but could be improved

Indicators:
- Number of failed attempts
- User frustration signals
- Time spent (if mentioned)
- Whether user had to manually intervene
```

**G. Present Findings to User**
```markdown
════════════════════════════════════════════════════════════════════════
Auto-Analysis Results
════════════════════════════════════════════════════════════════════════

I scanned the conversation and found this pattern:

Summary:
"[Generated summary]"

Technologies: [python, pytest, async, FastAPI]
Keywords: [@pytest.mark.asyncio, httpx.AsyncClient, async testing]
Severity: HIGH

Problem: [What went wrong]
Solution: [What fixed it]
Agent gap: [What agent should have known]

════════════════════════════════════════════════════════════════════════

Is this accurate?

A) Yes, proceed with this summary
B) Edit summary before proceeding
C) Provide different summary manually
D) Not rule-worthy, skip

Choice (A/B/C/D): _
════════════════════════════════════════════════════════════════════════
```

**User Response Handling:**

**A (Proceed):**
- Use generated summary
- Continue to Step 2 (Extract Keywords)

**B (Edit):**
- Display generated summary in editable format
- Prompt: "Edit summary:"
- Wait for user input
- Use edited summary
- Continue to Step 2

**C (Manual):**
- Discard generated summary
- Prompt: "Please provide conversation_summary:"
- Wait for user input
- Continue to Step 1 (Parse Summary)

**D (Skip):**
- Stop workflow
- Report: "Skipped rule creation per user request"

### 1. Parse Summary for Key Concepts

**(If manual summary provided OR auto-analyze confirmed)**

Extract the following from conversation_summary:

**Technology Stack:**
- Languages: Python, JavaScript, SQL, Shell, Go
- Frameworks: FastAPI, Flask, React, Streamlit
- Tools: Docker, pytest, SQLAlchemy, psycopg2
- Platforms: Snowflake, PostgreSQL, AWS

**Problem Indicators:**
- Authentication failures (401, 403, "access denied")
- Configuration issues ("missing", "not found", "undefined")
- Best practice gaps ("should have", "didn't know", "tried X but needed Y")
- Repeated attempts ("multiple tries", "eventually", "after several attempts")
- Manual intervention required ("had to manually", "workaround")

**Solution Patterns:**
- Environment variables used
- Configuration changes made
- Commands that worked
- Patterns discovered

### 2. Extract Keywords (5-10 terms)

Generate semantic keywords for rule discovery:

**Technology Keywords:**
- Core technology (python, snowflake, javascript)
- Framework/tool (fastapi, pytest, docker)
- Specific feature (async, connection pooling, authentication)

**Action Keywords:**
- What was being done (testing, deployment, authentication)
- What failed (connection, permissions, import)

**Pattern Keywords:**
- Type of solution (environment variables, configuration, best practices)

**Example:**
```
Summary: "psycopg2 connection pooling for Snowflake. Had to set 
pool_size=5 and max_overflow=10. Agent didn't know SQLAlchemy patterns."

Keywords extracted:
- python (language)
- postgres, psycopg2 (database)
- SQLAlchemy (ORM)
- connection pooling (pattern)
- Snowflake (platform)
- configuration (action)
```

### 3. Identify Domain

Map technology to rule domain range:

**Domain Mapping:**
- **000-099:** Core Foundation (if applies to ALL domains)
- **100-199:** Snowflake (SQL, Streamlit, Cortex, REST API)
- **200-299:** Python (core, FastAPI, Flask, pytest, SQLAlchemy)
- **300-399:** Shell (bash, zsh, scripts)
- **400-499:** Frontend/Containers (Docker, JavaScript, TypeScript, React)
- **500-599:** Frontend Core (HTMX, browser)
- **600-699:** Go/Golang
- **800-899:** Project Management (git, changelog, README)
- **900-999:** Analytics & Governance

**Decision Logic:**
1. Primary technology determines domain
2. If multiple technologies, choose most specific
3. If cross-domain pattern, check for topic-specific rule first

**Example:**
```
Keywords: python, postgres, SQLAlchemy, Snowflake
Primary: Python (200-series)
Secondary: Snowflake (100-series)
Decision: 200-series (Python is where SQLAlchemy guidance belongs)
```

### 4. Assess Rule-Worthiness

Determine if this should become a rule or not.

**RULE-WORTHY (Proceed):**
- ✅ Applies across multiple projects
- ✅ Technology-specific guidance missing
- ✅ Repeated pattern (happened 2+ times in conversation)
- ✅ Process improvement (validation gates, pre-checks)
- ✅ Authentication/setup blockers
- ✅ Best practices agent didn't know

**NOT RULE-WORTHY (Stop):**
- ❌ Project-specific (database "MY_SPECIFIC_DB" not found)
- ❌ User typo or incorrect command
- ❌ Network failure, API rate limit, one-off environmental issue
- ❌ "Agent should have tried harder" (persistence cannot be codified)
- ❌ Already in existing rules (will be caught in Phase 2)

**CANNOT BE RULED:**
- ❌ Agent persistence/determination
- ❌ When to give up vs keep trying
- ❌ How much context to consider
(These are contextual judgment calls that vary by situation)

**Decision Gate:**
```
IF NOT rule-worthy:
  OUTPUT: "This appears to be [project-specific|one-off|cannot be ruled]. 
          Not creating a rule. Reason: [explanation]"
  STOP
ELSE:
  CONTINUE to Phase 2
```

### 5. Determine Severity Level

If not provided by user, infer from conversation:

**CRITICAL:**
- Complete blocker (couldn't proceed)
- Authentication failure
- Missing critical dependency
- Agent gave up

**HIGH:**
- Required 3+ attempts
- 5+ minutes of troubleshooting
- Multiple strategies tried
- User had to intervene

**MEDIUM:**
- Suboptimal path taken
- Could be smoother
- 1-2 attempts needed

**LOW:**
- Nice-to-have enhancement
- Works but could be better
- Edge case handling

## Outputs

**Analysis Summary:**
```markdown
Analysis Results:
✓ Domain: [200-Python / 100-Snowflake / etc.]
✓ Keywords: [keyword1, keyword2, keyword3, ...]
✓ Severity: [CRITICAL / HIGH / MEDIUM / LOW]
✓ Rule-worthy: [Yes / No]
✓ Reason: [Brief explanation]
```

**If Rule-worthy = Yes:**
- Continue to Phase 2: Search Existing Coverage

**If Rule-worthy = No:**
- Stop and report reason to user
- No rule created
- Suggest alternatives if applicable

## Example Walkthroughs

### Example 1: Rule-Worthy (Proceed)

**Input:**
```
conversation_summary: "Snowflake REST API authentication failed with 401. 
Agent tried OAuth token check but never looked for $SNOWFLAKE_PAT environment 
variable. Had to manually export it. Blocked pytest for 15 minutes."

severity: CRITICAL
```

**Analysis:**
```
Domain: 100-Snowflake (REST API)
Keywords: snowflake, REST API, authentication, environment variables, 
         SNOWFLAKE_PAT, OAuth, pytest
Severity: CRITICAL
Rule-worthy: Yes
Reason: Generic authentication pattern for Snowflake REST APIs. Applies 
        to all projects using REST API. Agent should check common env vars 
        before failing.
```

**Decision:** → Continue to Phase 2

### Example 2: Not Rule-Worthy (Stop)

**Input:**
```
conversation_summary: "Database MY_PROJECT_DB not found. Typo in connection 
string, should have been MY_PROJECT_DATABASE. Fixed typo, worked fine."

severity: LOW
```

**Analysis:**
```
Domain: Unclear (project-specific)
Keywords: database, connection, typo
Severity: LOW
Rule-worthy: No
Reason: Project-specific typo. Not a generic pattern. No rule can prevent 
        user typos in database names.
```

**Decision:** → Stop, report "Project-specific issue, not rule-worthy"

### Example 3: Cannot Be Ruled (Stop)

**Input:**
```
conversation_summary: "Agent gave up after 2 attempts to fix linting errors. 
Should have kept trying different approaches. Eventually worked when I said 
'try harder'."

severity: MEDIUM
```

**Analysis:**
```
Domain: N/A
Keywords: persistence, attempts, linting
Severity: MEDIUM
Rule-worthy: No
Reason: Agent persistence and determination cannot be codified. How hard to 
        try and when to give up is contextual judgment that varies by situation. 
        No rule can systematize "try harder."
```

**Decision:** → Stop, report "Cannot be ruled - persistence is contextual"

## Error Handling

**Vague Summary:**
```
If conversation_summary is too vague to extract keywords:
  ASK USER: "Can you provide more details:
   - What technology/framework were you using?
   - What specific error or issue occurred?
   - What configuration or command fixed it?"
```

**Ambiguous Domain:**
```
If multiple domains equally applicable:
  DOCUMENT: "Multiple domains detected: [list]"
  USE: Most specific domain (topic-specific > domain > global)
  CONTINUE to Phase 2 (search will disambiguate)
```

**Unclear Rule-Worthiness:**
```
If borderline case:
  ASK USER: "Is this issue:
   A) Generic (happens on most [technology] projects)
   B) Project-specific (unique to your setup)
   C) One-time environmental issue"
```

## Next Phase

If analysis shows rule-worthy = Yes:
- **Proceed to:** `workflows/02-search.md`
- **Carry forward:** Domain, Keywords, Severity

If analysis shows rule-worthy = No:
- **Stop execution**
- **Report to user:** Reason and alternative suggestions
