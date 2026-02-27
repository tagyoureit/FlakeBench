Start with `docs/index.md` for a human overview or `docs/SKILL.md` for the
agent-focused index, then follow the referenced docs as needed.

For any 'best practices' or 'how to' questions always consult the GLEAN MCP.

**Debugging metrics/UI issues?** See `docs/metrics-streaming-debug.md` for the
complete phase transition flow (PREPARING → WARMUP → MEASUREMENT) and why QPS
may show 0 during certain phases.

## Agent Behavior: Mandatory Subagent Usage

**CRITICAL: Context preservation is a high priority for this project.**

### Subagent Usage Requirements

**ALWAYS use subagents for:**
1. **Codebase exploration** - Any search, analysis, or investigation of existing code
2. **File discovery** - Finding patterns, implementations, or references across the codebase
3. **Architecture analysis** - Understanding system design, data flow, or component relationships
4. **Long research tasks** - Any investigation requiring reading 3+ files
5. **Documentation exploration** - Searching through docs/ for information

**Use the Explore subagent proactively:**
- When asked "how does X work?"
- When asked "where is Y implemented?"
- When asked "find all instances of Z"
- Before answering questions about code structure or patterns
- When investigating bugs or unexpected behavior

**Use the /investigate custom subagent for:**
- Project-specific code analysis requiring domain knowledge
- Multi-step investigations combining code + docs
- Summarizing implementation patterns specific to this project

EXCEPTION: If subagents are not available (ie in Cursor), notify user they are not available but do not prompt to continue without them, just proceed.

### Context Management Goals

- Main conversation should focus on decisions, direction, and implementation
- Exploration work should happen in isolated subagent contexts
- Subagent responses should be concise summaries (≤500 tokens)
- Never pollute main context with raw search results or verbose file exploration

### How to Invoke

**Automatic (preferred):** Simply ask questions; agent should delegate automatically

**Explicit (if automatic fails):**
- `/explore [task]` - Use built-in Explore subagent
- `/investigate [task]` - Use custom investigation subagent
- Mention "use subagent" or "delegate to subagent" in requests

## Code Organization: File Size Limits & Modularization

**CRITICAL: Large monolithic files cause problems for AI agents and humans alike.**

### File Size Guidelines

| File Size | Classification | Action Required |
|-----------|---------------|-----------------|
| < 500 lines | Healthy | No action needed |
| 500-1000 lines | Growing | Consider splitting if adding significant code |
| 1000-2000 lines | Large | Split before adding new features |
| > 2000 lines | Monolith | **MUST refactor before adding code** |

### When Implementing New Features

**Before adding code to any file:**
1. Check file size: `wc -l <file>`
2. If file > 1000 lines AND new feature > 100 lines:
   - Create a new module instead of adding to the monolith
   - Use existing module patterns in the codebase
   - Import from the new module in the original file

### Modularization Patterns

**For API routes (e.g., `backend/api/routes/`):**
```
routes/
├── feature.py              # Main routes file (keep slim)
├── feature_modules/
│   ├── __init__.py         # Export public interfaces
│   ├── queries.py          # Database queries
│   ├── utils.py            # Helper functions
│   ├── business_logic.py   # Core logic
│   └── prompts.py          # AI/LLM prompts
```

**For core modules (e.g., `backend/core/`):**
```
core/
├── feature/
│   ├── __init__.py
│   ├── types.py            # Pydantic models, dataclasses
│   ├── service.py          # Main service class
│   └── helpers.py          # Pure functions
```

### Known Large Files (Refactor Candidates)

| File | Lines | Status |
|------|-------|--------|
| `backend/api/routes/test_results.py` | ~8,300 | Uses `test_results_modules/` - follow this pattern |
| `backend/core/orchestrator.py` | ~4,000 | Consider splitting by responsibility |
| `backend/core/test_executor.py` | ~2,600 | Consider splitting by load mode |

### Benefits of Modularization

1. **AI agents work more effectively** - Smaller files fit in context windows
2. **Faster code navigation** - Find relevant code quickly
3. **Parallel development** - Multiple agents/developers can work simultaneously
4. **Better testing** - Test modules in isolation
5. **Clearer ownership** - Each module has single responsibility

## SPCS Deployment Quick Reference

**Full documentation:** See `spcs/README.md` for complete setup, networking, and troubleshooting.

### Push Latest Image to SPCS

```bash
# Build, tag, login, and push (replace TAG with date-version like 20260227-v1)
TAG=20260227-v1
docker build --platform linux/amd64 -t flakebench:$TAG -f Dockerfile .
docker tag flakebench:$TAG sfsenorthamerica-rgoldin-aws1.registry.snowflakecomputing.com/sandbox/spcs/flakebench_repo/flakebench:$TAG
snow spcs image-registry login --connection default
docker push sfsenorthamerica-rgoldin-aws1.registry.snowflakecomputing.com/sandbox/spcs/flakebench_repo/flakebench:$TAG
```

### Update SPCS Service

```sql
ALTER SERVICE SANDBOX.SPCS.FLAKEBENCH_SERVICE FROM SPECIFICATION $$
spec:
  containers:
  - name: flakebench
    image: /SANDBOX/SPCS/FLAKEBENCH_REPO/flakebench:<TAG>
    env:
      APP_HOST: "0.0.0.0"
      APP_PORT: "8080"
      APP_DEBUG: "false"
      APP_RELOAD: "false"
      SNOWFLAKE_WAREHOUSE: "COMPUTE_WH"
      SNOWFLAKE_DATABASE: "FLAKEBENCH"
      SNOWFLAKE_SCHEMA: "PUBLIC"
      SNOWFLAKE_ROLE: "FLAKEBENCH_ROLE"
      RESULTS_DATABASE: "FLAKEBENCH"
      RESULTS_SCHEMA: "TEST_RESULTS"
      LOG_LEVEL: "INFO"
    resources:
      requests:
        memory: 2Gi
        cpu: 1000m
      limits:
        memory: 4Gi
        cpu: 2000m
    readinessProbe:
      port: 8080
      path: /health
  endpoints:
  - name: flakebench-ui
    port: 8080
    public: true
$$;
```

### Check Service Status

```sql
SELECT SYSTEM$GET_SERVICE_STATUS('SANDBOX.SPCS.FLAKEBENCH_SERVICE');
```

### View Service Logs

```sql
SELECT SYSTEM$GET_SERVICE_LOGS('SANDBOX.SPCS.FLAKEBENCH_SERVICE', 0, 'flakebench', 100);
```