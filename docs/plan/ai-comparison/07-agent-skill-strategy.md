# AI-Powered Test Comparison - Cortex Agent & CoCo Skill Strategy

**Part of:** [AI-Powered Test Comparison Feature](00-overview.md)

---

## 19. Cortex Agent & CoCo Skill Strategy

### 19.1 Executive Summary

**Recommendation: Hybrid Approach** — Use **both** technologies, each for what it does best:

| Capability | Best Fit | Why |
|------------|----------|-----|
| Query/analyze existing test results | **Cortex Agent** | Natural language → SQL over test data |
| Deep compare & statistical analysis | **Cortex Agent** | Multi-hop queries, can use multiple semantic views |
| Create new benchmarks (interactive) | **CoCo Skill** | Rich multi-step workflows, gather user input |
| Run benchmarks | **CoCo Skill** | Local execution, progress monitoring, error handling |
| Complex analysis ("10 medium vs 20 small WH") | **Hybrid** | Skill orchestrates, Agent analyzes results |

### 19.2 Technology Comparison

#### Architecture Differences

| Aspect | Snowflake Cortex Agent | CoCo Skill |
|--------|----------------------|------------|
| **Execution Location** | Server-side (Snowflake) | Client-side (CLI) |
| **State** | Stateless per query | Stateful conversation context |
| **Tools Available** | Semantic Views, Cortex Search, Stored Procedures | All CoCo tools (bash, SQL, file ops, subagents) |
| **User Interaction** | Single prompt → response | Multi-step workflows with choices |
| **Sharing** | SQL GRANT to roles/users | Local skill files or git |
| **Invocation** | REST API, SQL, or via CoCo | `/skill-name` or automatic from triggers |

#### Capability Matrix

| Use Case | Cortex Agent | CoCo Skill | Best Fit |
|----------|--------------|------------|----------|
| "How did test X perform?" | ✅ Direct semantic view query | ✅ Can query via SQL tool | **Agent** |
| "Compare test X to baseline" | ✅ Multi-tool orchestration | ✅ Can orchestrate queries | **Agent** |
| "Find similar tests" | ✅ SQL over test metadata | ✅ Can query | **Agent** |
| "Why did this test regress?" | ✅ Agentic investigation | ⚠️ Manual exploration | **Agent** |
| "Help me benchmark table X" | ❌ No interactive workflow | ✅ Multi-step Q&A | **Skill** |
| "Create a benchmark config" | ⚠️ Could use stored proc | ✅ File creation, validation | **Skill** |
| "Run benchmark and monitor" | ❌ No long-running execution | ✅ Background jobs, monitoring | **Skill** |
| "10 medium vs 20 small WH cost/perf" | ✅ Analysis after data exists | ✅ Orchestrate + analyze | **Hybrid** |

### 19.3 Hybrid Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    USER REQUEST                                      │
│  "Benchmark my postgres tables and compare warehouse configurations" │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   CoCo SKILL: benchmark-wizard                       │
│  ──────────────────────────────────────────────────────────────────  │
│                                                                      │
│  Phase 1: Requirements Gathering (Interactive)                       │
│  ├─ Which tables? → User selects                                     │
│  ├─ What SQL patterns? → User provides or auto-detect                │
│  ├─ What's important? (latency, throughput, cost) → User ranks       │
│  ├─ SLOs? → User defines thresholds                                  │
│  └─ Warehouse configs to compare? → User specifies                   │
│                                                                      │
│  Phase 2: Configuration Generation                                   │
│  ├─ Create test templates (JSON/YAML)                                │
│  ├─ Validate configurations                                          │
│  └─ Show user what will be created                                   │
│                                                                      │
│  Phase 3: Execution                                                  │
│  ├─ Submit benchmarks via backend API                                │
│  ├─ Monitor progress (background)                                    │
│  └─ Handle failures, retries                                         │
│                                                                      │
│  Phase 4: Analysis Handoff                                           │
│  └─ Invoke Cortex Agent for results analysis                         │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│            CORTEX AGENT: benchmark-analyst                           │
│  ──────────────────────────────────────────────────────────────────  │
│                                                                      │
│  Tools:                                                              │
│  ├─ test_results_analytics (Semantic View)                           │
│  │   → Query TEST_RESULTS, aggregations, comparisons                 │
│  ├─ statistical_analysis (Stored Procedure)                          │
│  │   → Mann-Whitney, confidence intervals, trend detection           │
│  ├─ cost_calculator (Stored Procedure)                               │
│  │   → Credit consumption, $/query calculations                      │
│  └─ documentation_search (Cortex Search)                             │
│      → Best practices, optimization guides                           │
│                                                                      │
│  Capabilities:                                                       │
│  ├─ "Compare test 123 vs test 456"                                   │
│  ├─ "Is 5% latency regression significant?"                          │
│  ├─ "What's the cost per 1000 queries for each config?"              │
│  └─ "Recommend optimal warehouse size for this workload"             │
└─────────────────────────────────────────────────────────────────────┘
```

### 19.4 Cortex Agent Implementation Details

#### Semantic View Design

The Semantic View should expose test results with clear dimensions and facts:

**Dimensions:**
- `template_id`, `template_name` - Test template identification
- `load_mode` - CONCURRENCY, QPS, FIND_MAX_CONCURRENCY
- `table_type` - STANDARD, HYBRID, INTERACTIVE, DYNAMIC, POSTGRES
- `warehouse_size` - XS through 6XL
- `scale_mode` - FIXED, AUTO, BOUNDED
- `test_date` - Temporal dimension

**Facts:**
- `qps` - Queries per second achieved
- `p50_latency_ms`, `p95_latency_ms`, `p99_latency_ms` - Latency metrics
- `error_rate` - Error percentage
- `duration_seconds` - Test duration
- `best_stable_concurrency` - FIND_MAX ceiling (when applicable)
- `credit_consumption` - Cost metric

**Metrics (Calculated):**
- `baseline_delta_pct` - Delta vs rolling median
- `trend_direction` - IMPROVING, STABLE, REGRESSING
- `qps_per_credit` - Cost efficiency metric

#### Agent Configuration

```json
{
  "models": {
    "orchestration": "auto"
  },
  "instructions": {
    "orchestration": "You are a performance benchmarking analyst. Help users understand test results, compare configurations, and identify regressions or improvements. When comparing tests, always check if differences are statistically significant using the statistical_analysis tool. For cost questions, use the cost_calculator tool.",
    "response": "Be concise and data-driven. Lead with the key finding, then provide supporting evidence. Use tables for multi-row comparisons. Flag any caveats about comparison confidence."
  },
  "tools": [
    {
      "tool_spec": {
        "type": "cortex_analyst_text_to_sql",
        "name": "test_results_analytics",
        "description": "Query performance test results including QPS, latency, error rates, and FIND_MAX capacity metrics. Use for questions about test performance, comparisons between tests, filtering by template/load_mode/table_type, and trend analysis. Data includes all completed tests with metrics aggregated at test level."
      }
    },
    {
      "tool_spec": {
        "type": "generic",
        "name": "statistical_analysis",
        "description": "Calculate statistical significance of performance differences using Mann-Whitney U test. Use when comparing two tests or test groups to determine if differences are real or within normal variance. Returns p-value and confidence assessment.",
        "input_schema": {
          "type": "object",
          "properties": {
            "test_id_a": {"type": "string", "description": "First test ID"},
            "test_id_b": {"type": "string", "description": "Second test ID"},
            "metric": {"type": "string", "enum": ["qps", "p95_latency", "p99_latency"]}
          },
          "required": ["test_id_a", "test_id_b", "metric"]
        }
      }
    },
    {
      "tool_spec": {
        "type": "generic",
        "name": "cost_calculator",
        "description": "Calculate cost metrics for tests including credit consumption, $/query, and cost comparisons between warehouse configurations. Use for cost-benefit analysis and optimization recommendations.",
        "input_schema": {
          "type": "object",
          "properties": {
            "test_ids": {"type": "array", "items": {"type": "string"}},
            "comparison_type": {"type": "string", "enum": ["absolute", "per_query", "per_qps"]}
          },
          "required": ["test_ids"]
        }
      }
    }
  ],
  "tool_resources": {
    "test_results_analytics": {
      "semantic_view": "BENCHMARK_DB.ANALYTICS.TEST_RESULTS_SEMANTIC_VIEW",
      "execution_environment": {"type": "warehouse", "warehouse": "COMPUTE_WH"}
    },
    "statistical_analysis": {
      "type": "procedure",
      "identifier": "BENCHMARK_DB.ANALYTICS.STATISTICAL_ANALYSIS_PROC"
    },
    "cost_calculator": {
      "type": "procedure", 
      "identifier": "BENCHMARK_DB.ANALYTICS.COST_CALCULATOR_PROC"
    }
  }
}
```

### 19.5 CoCo Skill Implementation Details

#### Skill YAML Frontmatter

```yaml
---
name: benchmark-wizard
description: Interactive wizard for creating, running, and analyzing performance benchmarks. Guides users through table selection, SQL pattern configuration, SLO definition, warehouse sizing, and results analysis. Triggers on "benchmark", "performance test", "compare warehouses", "help me test".
version: 1.0.0
---
```

#### Workflow Phases

**Phase 1: Requirements Gathering**
```markdown
## Phase 1: Requirements Gathering

### Questions to Ask

1. **Target Selection**
   - What table type? (HYBRID/STANDARD/POSTGRES/multiple)
   - Specific table names or patterns?
   - Database and schema?

2. **Workload Definition**
   - What SQL operations? (point lookups, range scans, inserts, updates)
   - Custom SQL queries or auto-generated?
   - Read/write ratio?

3. **Performance Goals**
   - What matters most? (latency, throughput, cost)
   - Any SLOs to meet? (e.g., P95 < 100ms)
   - Target QPS or concurrency?

4. **Test Configuration**
   - Load mode? (CONCURRENCY, QPS, FIND_MAX)
   - Duration? (recommended: 5-15 minutes)
   - Warm-up period?

5. **Comparison Dimensions**
   - Warehouse sizes to compare?
   - Multiple configurations?
   - Cost budget constraints?
```

**Phase 2: Configuration Generation**
```markdown
## Phase 2: Configuration Generation

### Actions
1. Generate test template JSON based on gathered requirements
2. Validate configuration against schema
3. Estimate test duration and credit consumption
4. Present summary for user approval

### Output
- Test template file (saved locally)
- Estimated duration and cost
- Comparison matrix if multiple configs
```

**Phase 3: Execution**
```markdown
## Phase 3: Execution

### Actions
1. Submit test(s) via backend API
2. Monitor progress using background task
3. Handle failures with retry logic
4. Collect test IDs for analysis phase

### Commands
- `POST /api/tests` - Submit new test
- `GET /api/tests/{id}` - Check status
- Background monitoring via bash_output
```

**Phase 4: Analysis Handoff**
```markdown
## Phase 4: Analysis Handoff

### Integration with Cortex Agent
Once tests complete, invoke the benchmark-analyst agent:

```bash
cortex analyst query "Compare TEST_A vs TEST_B. 
Which warehouse configuration gives better cost/performance?" \
  --agent=BENCHMARK_DB.ANALYTICS.BENCHMARK_ANALYST
```

### Fallback (if agent not available)
Use the existing compare-context API and AI_COMPLETE flow from Phases 1-5.
```

### 19.6 Implementation Roadmap

| Phase | Technology | Deliverables | Dependencies |
|-------|------------|--------------|--------------|
| 7a | Cortex Agent | Semantic View over test results | Phases 1-5 |
| 7b | Cortex Agent | Statistical analysis stored procedure | Phase 7a |
| 7c | Cortex Agent | Cost calculator stored procedure | Phase 7a |
| 7d | Cortex Agent | Agent definition and testing | Phases 7a-c |
| 8a | CoCo Skill | SKILL.md and workflow structure | None |
| 8b | CoCo Skill | Requirements gathering workflow | Phase 8a |
| 8c | CoCo Skill | Configuration generation | Phase 8b |
| 8d | CoCo Skill | Execution and monitoring | Phase 8c |
| 8e | CoCo Skill | Agent handoff integration | Phases 7d, 8d |

### 19.7 Benefits of Hybrid Approach

1. **Best of Both Worlds**
   - Agent handles complex data analysis (what it's designed for)
   - Skill handles interactive workflows (what it's designed for)

2. **Separation of Concerns**
   - Agent: "Analyze this data" (stateless, shareable, server-side)
   - Skill: "Guide me through creating this" (stateful, interactive, client-side)

3. **Incremental Adoption**
   - Phase 7 (Agent) can be used independently for analysis
   - Phase 8 (Skill) adds guided workflows on top
   - Either can be used without the other

4. **Scalability**
   - Agent runs in Snowflake (scalable compute)
   - Skill runs locally (no server load for interactive flows)

5. **User Experience**
   - Natural language queries → Agent
   - Step-by-step guidance → Skill
   - Complex orchestration → Skill invokes Agent

---

**Previous:** [06-implementation.md](06-implementation.md) - Implementation phases, testing, success metrics  
**Next:** [08-appendix.md](08-appendix.md) - Future considerations, glossary, reference SQL
