# AI-Powered Test Comparison - Appendix

**Part of:** [AI-Powered Test Comparison Feature](00-overview.md)

---

## 18. Future Considerations

### 18.1 Cross-Template Similarity (Phase 2 Candidate)

**Concept:** Find tests with similar workloads across different templates

**Why Deferred from Phase 1:**
- Phase 1 is intentionally same-template for trust and determinism
- Cross-template comparability needs canonical workload signatures and tighter validation
- Higher false positive risk without tuned signature rules

**When to Reconsider (Phase 2):**
- Phase 1 baseline/comparable quality targets are met
- Canonical workload signatures are validated on real data
- Users request "find similar workloads across templates"

### 18.2 Automated Regression Alerts

**Concept:** Proactively notify users when tests regress

**Why Deferred:**
- Requires baseline to be established first
- Notification infrastructure not in place
- False positive risk must be minimized first

**When to Reconsider:**
- Phase 5 shows >95% regression detection accuracy
- User demand for proactive alerts
- Notification system available

### 18.3 ML-Based Similarity

**Concept:** Use embeddings for semantic similarity

**Why Deferred:**
- Deterministic scoring is interpretable and debuggable
- Embedding infrastructure not in place
- Current approach should be sufficient

**When to Reconsider:**
- Deterministic scoring proves insufficient
- Large scale (10K+ tests) makes exact matching impractical
- Embedding infrastructure available

### 18.4 Multi-Run Comparison

**Concept:** Compare runs of runs (aggregate analysis)

**Why Deferred:**
- Individual test comparison is prerequisite
- Adds significant complexity
- Lower priority user need

**When to Reconsider:**
- Phase 1-5 complete and stable
- User demand for batch comparison
- Run-level aggregation needed

---

## 20. Appendix

### 20.1 Glossary

| Term | Definition |
|------|------------|
| **Baseline** | Set of previous runs of the same template used for comparison |
| **Hard Gate** | Filter that must pass for any comparison (template, load mode, etc.) |
| **Soft Score** | Weighted similarity metric for ranking comparable tests |
| **Confidence** | Level of trust in comparison (HIGH/MEDIUM/LOW) |
| **Rolling Median** | Median of last N baseline runs |
| **Trend** | Direction of performance change over recent runs |
| **Compare Context** | Structured JSON with all comparison data |
| **Steady-State Quality** | Stability score for CONCURRENCY/QPS comparisons |
| **FIND_MAX Peak Quality** | Max-focused comparability using best-stable/degradation points |
| **SQL Fingerprint** | Hash of canonicalized SQL for pattern matching |
| **Workload Signature** | Hash of workload shape for quick comparison |

### 20.2 SQL Queries (Reference)

**Baseline Candidates Query:**
```sql
WITH current_test AS (
    SELECT 
        TEST_ID,
        TEST_CONFIG:template_id::STRING as template_id,
        COALESCE(TEST_CONFIG:template_config:load_mode::STRING, TEST_CONFIG:scenario:load_mode::STRING) as load_mode,
        TABLE_TYPE
    FROM {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_RESULTS
    WHERE TEST_ID = ?
)
SELECT 
    t.TEST_ID,
    t.QPS,
    t.P95_LATENCY_MS,
    t.ERROR_RATE,
    t.START_TIME,
    ROW_NUMBER() OVER (ORDER BY t.START_TIME DESC) as recency_rank
FROM {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_RESULTS t
JOIN current_test c ON 
    t.TEST_CONFIG:template_id::STRING = c.template_id
    AND COALESCE(t.TEST_CONFIG:template_config:load_mode::STRING, t.TEST_CONFIG:scenario:load_mode::STRING) = c.load_mode
    AND t.TABLE_TYPE = c.TABLE_TYPE
WHERE t.TEST_ID != c.TEST_ID
  AND t.STATUS = 'COMPLETED'
  AND (
      t.RUN_ID IS NULL
      OR t.TEST_ID = t.RUN_ID
  ) -- prefer parent rollups; exclude child worker rows
  AND t.START_TIME >= DATEADD(day, -30, CURRENT_TIMESTAMP())
ORDER BY t.START_TIME DESC
LIMIT 10;
```

**Rolling Statistics Query:**
```sql
SELECT 
    COUNT(*) as sample_count,
    MEDIAN(QPS) as median_qps,
    PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY QPS) as p10_qps,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY QPS) as p90_qps,
    MEDIAN(P95_LATENCY_MS) as median_p95,
    PERCENTILE_CONT(0.10) WITHIN GROUP (ORDER BY P95_LATENCY_MS) as p10_p95,
    PERCENTILE_CONT(0.90) WITHIN GROUP (ORDER BY P95_LATENCY_MS) as p90_p95
FROM baseline_candidates
WHERE recency_rank <= 5;
```

### 20.3 Snowflake-Native Materialization Pattern (Phase 6)

Apply only if compare-context latency exceeds configured SLA.

```sql
CREATE OR REPLACE DYNAMIC TABLE {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_COMPARISON_FEATURES
    TARGET_LAG = '1 hour'
    WAREHOUSE = '{COMPUTE_WAREHOUSE}'
AS
SELECT
    tr.TEST_ID,
    tr.RUN_ID,
    tr.TABLE_TYPE,
    tr.WAREHOUSE_SIZE,
    tr.STATUS,
    tr.START_TIME,
    tr.QPS,
    tr.P95_LATENCY_MS,
    tr.ERROR_RATE,
    tr.TEST_CONFIG:template_id::STRING AS TEMPLATE_ID,
    COALESCE(tr.TEST_CONFIG:template_config:load_mode::STRING, tr.TEST_CONFIG:scenario:load_mode::STRING) AS LOAD_MODE,
    tr.TEST_CONFIG:template_config:scaling:mode::STRING AS SCALE_MODE
FROM {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_RESULTS tr
WHERE tr.STATUS = 'COMPLETED'
  AND (tr.RUN_ID IS NULL OR tr.TEST_ID = tr.RUN_ID);

ALTER TABLE {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_COMPARISON_FEATURES
    CLUSTER BY (TEMPLATE_ID, LOAD_MODE, TABLE_TYPE, START_TIME);

ALTER TABLE {RESULTS_DATABASE}.{RESULTS_SCHEMA}.TEST_COMPARISON_FEATURES
    ADD SEARCH OPTIMIZATION ON EQUALITY(TEST_ID);
```

### 20.4 File Locations

| Component | File | Notes |
|-----------|------|-------|
| AI Analysis Endpoint | `backend/api/routes/test_results.py` | `POST /api/tests/{test_id}/ai-analysis` |
| Prompt Builders | `backend/api/routes/test_results.py` | Mode-specific prompt construction |
| AI_COMPLETE Call | `backend/api/routes/test_results.py` | Single-call narrative layer |
| Step History Fetch | `backend/api/routes/test_results.py` | FIND_MAX derivations |
| Deep Compare JS | `backend/static/js/compare_detail.js` | Existing comparison UI |
| History Page JS | `backend/static/js/history.js` | Compare selection workflow |
| Test Model | `backend/models/test_result.py` | Unused comparison fields noted |

### 20.5 Related Documents

- `docs/plan/comparison-feature.md` - Original feature roadmap
- Test data analysis queries in Snowflake worksheet

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.4 | 2026-02-12 | AI Assistant | Added Section 19: Cortex Agent & CoCo Skill Strategy with hybrid architecture recommendation; expanded Phase 7 with Cortex Agent implementation details; added Phase 8 for CoCo Skill benchmark wizard; updated Section 7.3 to clarify agent applicability; renumbered Appendix to Section 20 |
| 1.3 | 2026-02-11 | AI Assistant | Migrated remaining useful content from superseded design doc (design principle + Snowflake-native materialization pattern), corrected load-mode SQL example in appendix, and prepared plan as single source of truth |
| 1.1 | 2026-02-11 | AI Assistant | Aligned with implementation realities and user decisions: same-template Phase 1 scope, explicit target type from template, FIND_MAX max-focused quality, 30-day baseline window, parent-rollup preference, enrichment as confidence modifier, POST ai-analysis alignment, and configurable latency SLAs |
| 1.0 | 2026-02-11 | AI Assistant | Initial complete plan |

---

**Previous:** [07-agent-skill-strategy.md](07-agent-skill-strategy.md) - Cortex Agent & CoCo Skill hybrid strategy

---

**End of Document**
