# Phase 3: Test Execution

## Purpose

Submit the test configuration to the backend API, monitor execution progress, and collect run IDs for analysis.

## CRITICAL: Pre-Execution Confirmation Required

**Before starting ANY test, the agent MUST ask for explicit user confirmation.**

```markdown
## Ready to start test

**Test:** {template_name}
**Target:** {database}.{schema}.{table_name} ({table_type})
**Mode:** {load_mode}
**Configuration:**
- Starting threads: {start_concurrency}
- Increment: +{concurrency_increment} every {step_duration_seconds}s
- Duration: {duration_seconds}s
- Workload: {point_lookup_pct}% point lookups, {range_scan_pct}% range scans

**Estimated cost:** ~{credits} credits

---

Start this test? [Yes / No / Modify]
```

**Wait for explicit "yes" before calling `/api/runs/{id}/start`**

**DO NOT:**
- Auto-start tests after creating the run
- Start the next test without asking (for comparison tests)
- Assume "yes" from silence - require explicit confirmation

## Multiple Test Execution Mode

**When running multiple tests (e.g., Postgres vs Interactive Tables comparison):**

Before starting the **first** test, ask the user how they want to proceed:

```markdown
You have {N} tests to run:
1. {test1_name} - {table1} on {warehouse1}
2. {test2_name} - {table2} on {warehouse2}

How would you like to proceed?
A) Run all tests sequentially (I'll start the next test automatically after each completes)
B) Pause after each test (I'll prompt you before starting the next one)
```

**Based on their choice:**

### Option A: Sequential Execution
- Start test 1
- Wait for completion
- Automatically start test 2 (no prompt)
- Continue until all tests complete
- Then present combined analysis

### Option B: Pause After Each
- Start test 1
- Wait for completion
- Show results summary
- Ask: "Ready to start the next test ({test2_name})? [Yes / No / Modify]"
- Repeat for each test

**Default behavior if user doesn't specify:** Assume Option B (pause after each) - it's safer and gives user more control.

## Input

From Phase 2:

```json
{
  "template_id": "abc123-def456",
  "config": { ... },
  "estimated_credits": 0.35
}
```

## Execution Workflow

### Step 1: Create Run from Template

```bash
POST /api/runs
Content-Type: application/json

{
  "template_id": "abc123-def456"
}
```

**Response:**
```json
{
  "run_id": "run-789xyz",
  "status": "PREPARED",
  "dashboard_url": "/dashboard/run-789xyz"
}
```

**Store:** `run_id` for subsequent operations

### Step 2: Pre-flight Checks

Before starting, check for potential issues:

```bash
GET /api/runs/{run_id}/preflight
```

**Response:**
```json
{
  "run_id": "run-789xyz",
  "warnings": [
    {
      "severity": "medium",
      "title": "High Write Concurrency on Standard Table",
      "message": "25 concurrent INSERT/UPDATE operations on a STANDARD table may cause lock contention.",
      "recommendations": [
        "Consider using a HYBRID table for write-heavy workloads",
        "Reduce concurrent_connections to 10 or less",
        "Use batch inserts instead of single-row inserts"
      ],
      "details": {
        "write_percentage": 30,
        "concurrent_connections": 25,
        "table_type": "STANDARD"
      }
    }
  ],
  "can_proceed": true
}
```

**Present warnings to user:**

```markdown
## Pre-flight Warnings

⚠️ **Medium: High Write Concurrency on Standard Table**

25 concurrent INSERT/UPDATE operations on a STANDARD table may cause lock contention.

**Recommendations:**
- Consider using a HYBRID table for write-heavy workloads
- Reduce concurrent_connections to 10 or less
- Use batch inserts instead of single-row inserts

---

Proceed with test? [Y/n]
```

**If `can_proceed: false`:** 
- Show high-severity warnings
- Require user confirmation to proceed anyway
- Or return to configuration phase

### Step 3: Start Test Execution

```bash
POST /api/runs/{run_id}/start
```

**Response:**
```json
{
  "run_id": "run-789xyz",
  "status": "RUNNING",
  "warnings": []
}
```

**Inform user:**

```markdown
## Test Started

**Run ID:** run-789xyz
**Status:** RUNNING

**Dashboard:** http://localhost:8088/dashboard/run-789xyz

The test is now running. You can:
- Open the dashboard URL to view real-time metrics
- Wait here for completion (I'll notify you)
- Ask me to check status at any time
```

### Step 4: Monitor Progress

**IMPORTANT: Use trailing slashes on all API endpoints.**

Poll status periodically while test runs. For FIND_MAX_CONCURRENCY tests, the test creates multiple test steps that must be tracked individually.

#### Get Test ID from Run
```bash
curl -sL "http://127.0.0.1:8000/api/runs/{run_id}/"
```

Response includes `test_id` for detailed monitoring:
```json
{
  "run_id": "run-789xyz",
  "test_id": "test-abc123",
  "status": "RUNNING"
}
```

#### Monitor Test Progress
```bash
curl -sL "http://127.0.0.1:8000/api/tests/{test_id}/"
```

For FIND_MAX_CONCURRENCY tests, response includes step-by-step progress:
```json
{
  "test_id": "test-abc123",
  "status": "RUNNING",
  "current_step": 3,
  "total_steps": 10,
  "current_concurrency": 35,
  "metrics": {
    "qps": 1247,
    "p50_latency_ms": 12,
    "p95_latency_ms": 45,
    "error_rate": 0.0
  }
}
```

#### Background Monitoring with bash
For long-running tests, use background polling:

```bash
# Start background monitoring loop
while true; do
  curl -sL "http://127.0.0.1:8000/api/tests/{test_id}/" | jq '.status, .current_step, .metrics.qps'
  sleep 5
done
```

Use `run_in_background: true` with bash tool, then check with `bash_output` periodically.

#### Check for Errors
```bash
curl -sL "http://127.0.0.1:8000/api/tests/{test_id}/error-summary/"
```

**Status values:**
| Status | Meaning |
|--------|---------|
| PREPARED | Run created, not started |
| RUNNING | Test in progress |
| CANCELLING | Stop requested, winding down |
| COMPLETED | Test finished successfully |
| FAILED | Test encountered fatal error |
| CANCELLED | Test was stopped by user |
| STOPPED | Test stopped by guardrail or condition |

**Progress updates:**

```markdown
## Test Progress

**Run ID:** run-789xyz
**Status:** RUNNING
**Elapsed:** 2m 30s / 5m 00s (50%)

**Live Metrics:**
- Current QPS: 1,247
- P50 Latency: 12ms
- P95 Latency: 45ms
- P99 Latency: 89ms
- Error Rate: 0.0%
```

### Step 5: Handle Completion

When status changes to COMPLETED:

```markdown
## Test Completed

**Run ID:** run-789xyz
**Duration:** 5m 10s (including warmup)
**Status:** COMPLETED

**Final Metrics:**
- Total Queries: 374,100
- Average QPS: 1,247
- P50 Latency: 12ms
- P95 Latency: 45ms
- P99 Latency: 89ms
- Error Rate: 0.0%

**Estimated Cost:** 0.34 credits

---

Ready to analyze results?

A) Analyze with Cortex Agent (recommended)
B) View raw results in dashboard
C) Export results to CSV
D) Start another test
```

## Stopping a Test

If user requests stop:

```bash
POST /api/runs/{run_id}/stop
```

**Response:**
```json
{
  "run_id": "run-789xyz",
  "status": "CANCELLING"
}
```

**Inform user:**

```markdown
## Stop Requested

**Run ID:** run-789xyz
**Status:** CANCELLING

The test is being stopped. Current workers will complete their in-flight queries.
Partial results are available for analysis.
```

## Comparison Tests (Multiple Runs)

For side-by-side comparisons (e.g., warehouse sizes), execute multiple runs:

**CRITICAL: Run tests SEQUENTIALLY, not in parallel.**

Tests compete for the same resources (warehouse, Postgres instance, network). Running multiple tests simultaneously will:
- Cause resource contention and skew results
- Make comparisons invalid (tests affect each other)
- Potentially cause failures due to connection pool exhaustion

**Always wait for one test to complete before starting the next.**

### Sequential Execution

```python
run_ids = []
for variant in comparison_variants:
    # Update config with variant
    template_id = create_template(variant_config)
    
    # Create and start run
    run = create_run(template_id)
    start_run(run["run_id"])
    
    # IMPORTANT: Wait for completion before starting next test
    wait_for_completion(run["run_id"])
    
    run_ids.append(run["run_id"])
```

### Progress Display for Comparisons

```markdown
## Comparison Test Progress

| Variant | Status | QPS | P95 Latency |
|---------|--------|-----|-------------|
| X-Small | COMPLETED | 312 | 156ms |
| Small | COMPLETED | 589 | 84ms |
| Medium | RUNNING (75%) | 1,102 | 47ms |
| Large | PENDING | - | - |

**Estimated Time Remaining:** 8 minutes
```

## WebSocket Live Updates (Optional)

For real-time metrics without polling, connect to WebSocket:

```javascript
const ws = new WebSocket(`ws://localhost:8088/ws/runs/${runId}/metrics`);

ws.onmessage = (event) => {
  const metrics = JSON.parse(event.data);
  updateDisplay(metrics);
};
```

**Metrics payload:**
```json
{
  "timestamp": "2026-02-13T14:35:22Z",
  "qps": 1247,
  "latency_p50_ms": 12,
  "latency_p95_ms": 45,
  "latency_p99_ms": 89,
  "error_rate": 0.0,
  "active_connections": 25
}
```

## Error Handling

### Run Creation Failed

```markdown
❌ **Failed to create run**

Error: Template not found: abc123-def456

**Actions:**
A) Return to configuration and save template again
B) Check existing templates with `GET /api/templates`
C) Cancel wizard
```

### Test Failed During Execution

```markdown
❌ **Test Failed**

**Run ID:** run-789xyz
**Status:** FAILED
**Error:** Connection pool exhausted

**Possible causes:**
- Too many concurrent connections for warehouse size
- Network connectivity issues
- Snowflake service disruption

**Actions:**
A) View error details in logs
B) Retry with reduced concurrency
C) Check Snowflake status page
```

### Network/API Errors

```markdown
⚠️ **Connection Lost**

Unable to reach backend API at localhost:8088.

**Troubleshooting:**
1. Verify backend is running: `uv run python -m backend.main`
2. Check for port conflicts
3. Review backend logs for errors

**Actions:**
A) Retry connection
B) Cancel and troubleshoot
```

## Output

Pass to Phase 4 (Analysis) with:

```json
{
  "run_ids": ["run-789xyz"],
  "status": "COMPLETED",
  "summary_metrics": {
    "total_queries": 374100,
    "average_qps": 1247,
    "p50_latency_ms": 12,
    "p95_latency_ms": 45,
    "p99_latency_ms": 89,
    "error_rate": 0.0
  },
  "duration_seconds": 310,
  "estimated_cost": 0.34
}
```

For comparison tests:
```json
{
  "run_ids": ["run-xyz1", "run-xyz2", "run-xyz3"],
  "comparison_type": "warehouse_size",
  "variants": ["X-Small", "Small", "Medium"]
}
```

## CLI Commands Reference

**Note:** Always use trailing slashes on API endpoints. Backend runs on port 8000.

| Action | Command |
|--------|---------|
| Create run | `curl -sL -X POST "http://127.0.0.1:8000/api/runs/" -d '{"template_id":"..."}' -H 'Content-Type: application/json'` |
| Start run | `curl -sL -X POST "http://127.0.0.1:8000/api/runs/{id}/start"` |
| Check preflight | `curl -sL "http://127.0.0.1:8000/api/runs/{id}/preflight"` |
| Get test status | `curl -sL "http://127.0.0.1:8000/api/tests/{test_id}/"` |
| Get error summary | `curl -sL "http://127.0.0.1:8000/api/tests/{test_id}/error-summary/"` |
| Stop run | `curl -sL -X POST "http://127.0.0.1:8000/api/runs/{id}/stop"` |
| List templates | `curl -sL "http://127.0.0.1:8000/api/templates/"` |
| List connections | `curl -sL "http://127.0.0.1:8000/api/connections/"` |

## Next Phase

→ `workflows/04-analysis.md`
