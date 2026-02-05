# Example: Auto-Analyze Conversation

This example shows how rule-learner's auto-analyze feature works when you want to capture a lesson without manually writing a summary.

## Scenario

You're working on a FastAPI application. The agent tried to write async tests but used regular synchronous patterns, causing test failures. After several attempts and manual fixes, the tests work. You want to capture this lesson.

## Current State

```bash
# Working in your FastAPI project
$ pwd
/Users/rgoldin/projects/fastapi-microservice

# ai_coding_rules repo exists at common location
$ ls ~/Programming/ai_coding_rules
AGENTS.md  rules/  scripts/  skills/  ...

# Recent conversation shows the debugging session
# (Last 50 messages show the pattern)
```

## Input

```markdown
# Simple invocation - no manual summary needed
Use rule-learner skill.
```

## Execution

### Initial Prompt

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

**Your response:** `B`

### Phase 0: Locate Repository

```
Phase 0: Locate ai_coding_rules Repository
✓ Checking current directory... not ai_coding_rules
✓ Searching common locations...
✓ Found: /Users/rgoldin/Programming/ai_coding_rules
✓ Verified: All required directories present
✓ Context set

Current directory: /Users/rgoldin/projects/fastapi-microservice (unchanged)
```

### Phase 1: Auto-Analyze (Detailed View)

**Step 1: Scan Conversation**

```
Scanning conversation history...
✓ Messages analyzed: 87
✓ Timespan: Last 45 minutes
✓ Focus: Last 30 messages (most relevant)
```

**Step 2: Pattern Detection**

```
Pattern Detection:

Errors Found:
- Line 15: "AssertionError: assert 401 == 200"
- Line 23: "TypeError: object Response can't be used in 'await' expression"
- Line 31: "FAILED tests/test_api.py::test_create_user - RuntimeError: no running event loop"

Failed Commands:
- pytest tests/test_api.py (exit: 1) - attempt 1
- pytest tests/test_api.py (exit: 1) - attempt 2  
- pytest tests/test_api.py (exit: 0) - attempt 3 (SUCCESS)

Technologies Detected:
- Python (.py files)
- FastAPI (import FastAPI detected)
- pytest (pytest commands)
- httpx (from final working solution)
- async/await (in code blocks)

User Corrections:
- Line 42: "You need to use httpx.AsyncClient, not requests"
- Line 56: "Add @pytest.mark.asyncio decorator"
- Line 68: "Install pytest-asyncio first"

Manual Fixes:
- "I had to add pytest-asyncio to requirements.txt"
- "Changed from requests.get() to httpx.AsyncClient"

Solution Pattern:
- Before: requests.get() + regular test functions
- After: httpx.AsyncClient + @pytest.mark.asyncio decorator
- Success: All tests passed after changes
```

**Step 3: Generate Summary**

```
Generated Summary:
"FastAPI async endpoint testing failed with RuntimeError about event loop. 
Agent wrote synchronous tests using requests.get() which don't work with 
async endpoints. User manually installed pytest-asyncio, changed to 
httpx.AsyncClient, and added @pytest.mark.asyncio decorator. This pattern 
is required for all FastAPI async endpoint tests. Debugging took 45 minutes 
across 3 test runs."

Technologies: python, FastAPI, pytest, async, httpx, testing
Keywords: FastAPI, async, testing, pytest, httpx.AsyncClient, @pytest.mark.asyncio, 
         pytest-asyncio, event loop, async endpoints
Severity: HIGH (3 attempts, 45 minutes, manual intervention required)
```

**Step 4: Present to User**

```
════════════════════════════════════════════════════════════════════════
Auto-Analysis Results
════════════════════════════════════════════════════════════════════════

I scanned the conversation and found this pattern:

Summary:
"FastAPI async endpoint testing failed with RuntimeError about event loop. 
Agent wrote synchronous tests using requests.get() which don't work with 
async endpoints. User manually installed pytest-asyncio, changed to 
httpx.AsyncClient, and added @pytest.mark.asyncio decorator. This pattern 
is required for all FastAPI async endpoint tests. Debugging took 45 minutes."

Technologies: python, FastAPI, pytest, async, httpx
Keywords: FastAPI, async, testing, pytest, httpx.AsyncClient, 
         @pytest.mark.asyncio, pytest-asyncio, event loop

Severity: HIGH

Problem: Agent used synchronous test patterns for async FastAPI endpoints
Solution: Use httpx.AsyncClient + @pytest.mark.asyncio decorator
Agent gap: Didn't know FastAPI async testing requires special setup

════════════════════════════════════════════════════════════════════════

Is this accurate?

A) Yes, proceed with this summary
B) Edit summary before proceeding
C) Provide different summary manually
D) Not rule-worthy, skip

Choice (A/B/C/D): _
════════════════════════════════════════════════════════════════════════
```

**Your response:** `A` (Yes, proceed)

### Phase 2: Search

```
Search Results:
✓ Scanned: 121 rules in /Users/rgoldin/Programming/ai_coding_rules/rules/
✓ Keywords: FastAPI, async, testing, pytest
✓ Top candidates:
  1. rules/210-python-fastapi.md (4/5 keywords match)
  2. rules/206-python-pytest.md (2/5 keywords match)

Reading rules/210-python-fastapi.md...
✓ Section 5: "API Testing" exists
✓ Content: Basic testing patterns, no async testing specifics
✓ Coverage: PARTIAL

✓ Decision: ENHANCE rules/210-python-fastapi.md
✓ Target: Section 5 (expand with async testing patterns)
✓ Rationale: FastAPI-specific testing, belongs in FastAPI rule not generic pytest
```

### Phase 3A: Enhance

```
Enhancement Plan:
- Repository: /Users/rgoldin/Programming/ai_coding_rules
- Target: rules/210-python-fastapi.md
- Action: Expand Section 5 "API Testing" with async subsection
- Content:
  * Dependencies (pytest-asyncio, httpx)
  * @pytest.mark.asyncio decorator requirement
  * httpx.AsyncClient usage
  * Complete test examples
  * Common mistake: using requests with async endpoints
- Metadata updates:
  * Keywords: +4 (async testing, httpx, pytest-asyncio, event loop)
  * TokenBudget: ~3500 → ~4100 (+17%)

Enhancing: /Users/rgoldin/Programming/ai_coding_rules/rules/210-python-fastapi.md
```

### Phase 4: Validate

```bash
cd /Users/rgoldin/Programming/ai_coding_rules
uv run python scripts/schema_validator.py rules/210-python-fastapi.md
```

```
Validation Attempt 1:
[FAIL] CRITICAL errors: 1
  - Line 10: TokenBudget ~3500 differs from actual 4132 by 18%

Auto-fix applied:
  - TokenBudget: Updated ~3500 → ~4100

Validation Attempt 2:
[PASS] Passed: 458 checks
[PASS] RESULT: PASSED

✓ Schema compliance: PASSED
✓ Repository: /Users/rgoldin/Programming/ai_coding_rules
```

### Phase 5: Finalize

```bash
cd /Users/rgoldin/Programming/ai_coding_rules
uv run python scripts/index_generator.py
```

```
Index Regenerated:
✓ File: RULES_INDEX.md
✓ Updated entry: 210-python-fastapi.md
  - Keywords: +4 new terms
  - TokenBudget: ~3500 → ~4100
✓ Keyword index updated
```

### Phase 6: Review & Commit

```
Changes Made:
✓ Enhanced: /Users/rgoldin/Programming/ai_coding_rules/rules/210-python-fastapi.md
✓ Section: 5 "API Testing" (expanded with async patterns)
✓ Added: Async testing subsection (62 lines)
✓ Metadata: +4 keywords, TokenBudget +17%
✓ Index: RULES_INDEX.md updated

Repository: /Users/rgoldin/Programming/ai_coding_rules
Current directory: /Users/rgoldin/projects/fastapi-microservice (unchanged)

Files changed: 2
- rules/210-python-fastapi.md (+62 lines)
- RULES_INDEX.md (+4 keyword entries)

Commit? (Y/n): Y
```

```bash
cd /Users/rgoldin/Programming/ai_coding_rules
git commit -m "feat(fastapi): add async endpoint testing patterns

Enhanced rules/210-python-fastapi.md Section 5 with async testing guidance.

Discovered during work on fastapi-microservice project - agent used 
synchronous test patterns which fail with async endpoints.

- Added async testing subsection with pytest-asyncio + httpx patterns
- Dependencies: pytest-asyncio, httpx
- Decorator requirement: @pytest.mark.asyncio
- AsyncClient usage examples
- Common mistake: using requests.get() with async endpoints
- Updated metadata: +4 keywords, TokenBudget ~3500 → ~4100

Project context: fastapi-microservice
Auto-analyzed from conversation history"
```

```
Commit: abc1234
```

## Output

```
════════════════════════════════════════════════════════════════════════
WORKFLOW COMPLETE
════════════════════════════════════════════════════════════════════════

✓ Mode: Auto-analyze (scanned 87 messages)
✓ Pattern detected automatically
✓ Changes made in: /Users/rgoldin/Programming/ai_coding_rules
✓ Current directory: /Users/rgoldin/projects/fastapi-microservice (unchanged)
✓ Rule enhanced: rules/210-python-fastapi.md
✓ Committed: abc1234

Summary:
- Auto-analyzed: 87 conversation messages
- Detected: FastAPI async testing pattern missing
- Enhanced: rules/210-python-fastapi.md Section 5
- Added: Async testing guidance (62 lines)
- Keywords: +4 terms (async testing, httpx, pytest-asyncio, event loop)
- TokenBudget: ~3500 → ~4100
- Project: fastapi-microservice

Next steps:
1. cd /Users/rgoldin/Programming/ai_coding_rules
2. git push origin main
3. Deploy to other projects: task deploy DEST=~/other-project

Future agents working on FastAPI projects will now know to use 
httpx.AsyncClient + @pytest.mark.asyncio for async endpoint testing.
════════════════════════════════════════════════════════════════════════
```

## Key Takeaways

### No Manual Summary Required

**Before (manual):**
```markdown
Use rule-learner skill.

conversation_summary: "FastAPI async testing failed. Agent used requests.get() 
instead of httpx.AsyncClient. Needed @pytest.mark.asyncio decorator and 
pytest-asyncio package. Took 45 minutes to debug."
```

**After (auto-analyze):**
```markdown
Use rule-learner skill.
→ Chooses: B (Auto-analyze)
→ Skill scans conversation automatically
→ Presents findings
→ You confirm: A (Yes, proceed)
→ Done
```

### Intelligent Pattern Detection

The skill detected:
- ✅ Failed commands and error messages
- ✅ Technologies used (FastAPI, pytest, httpx)
- ✅ User corrections and manual fixes
- ✅ Solution pattern (what worked)
- ✅ Severity (3 attempts, 45 minutes)
- ✅ Agent knowledge gap

### Conversation Analysis Details

**What it scanned:**
- 87 messages
- Last 45 minutes of conversation
- Focused on last 30 messages (most relevant)

**What it found:**
- 3 failed pytest runs
- Multiple error messages
- User corrections ("use httpx not requests")
- Manual installations
- Final working solution

**What it generated:**
- Complete conversation_summary
- Technology stack
- Keywords for discovery
- Severity assessment
- Problem/solution/gap analysis

### User Control Maintained

Even with auto-analyze, you have choices:
- **A (Proceed):** Use generated summary as-is
- **B (Edit):** Modify summary before proceeding
- **C (Manual):** Discard and provide your own
- **D (Skip):** Not rule-worthy, don't create

### Workflow Efficiency

**Time saved:**
- No need to write summary manually
- No need to remember what happened
- No need to extract keywords
- Pattern detected automatically from conversation

**User interaction:**
- Choose mode: B (auto-analyze)
- Confirm findings: A (yes, proceed)
- Approve commit: Y
- Total prompts: 3 (vs writing entire summary)
