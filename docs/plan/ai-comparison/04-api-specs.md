# AI-Powered Test Comparison - API Specifications

**Part of:** [AI-Powered Test Comparison Feature](00-overview.md)

---

## 11. API Specifications

### 11.1 GET /api/tests/{test_id}/compare-context

**Purpose:** Return all comparison data needed for AI analysis

**Query Parameters:**
| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `baseline_count` | int | 5 | Number of baseline runs to consider |
| `comparable_limit` | int | 5 | Max comparable candidates to return |
| `min_similarity` | float | 0.55 | Minimum similarity score |
| `include_excluded` | bool | false | Include excluded candidates with reasons |

**Response Schema:**
```json
{
  "test_id": "string (UUID)",
  "template_id": "string (UUID)",
  "load_mode": "string (CONCURRENCY|QPS|FIND_MAX_CONCURRENCY)",
  
  "baseline": {
    "available": "boolean",
    "candidate_count": "integer",
    "used_count": "integer",
    "rolling_median": {
      "qps": "number",
      "p50_latency_ms": "number",
      "p95_latency_ms": "number",
      "p99_latency_ms": "number",
      "error_rate_pct": "number"
    },
    "confidence_band": {
      "qps_p10": "number",
      "qps_p90": "number",
      "latency_p10": "number",
      "latency_p90": "number"
    },
    "quality_filter_applied": "boolean",
    "quality_threshold": "number"
  },
  
  "vs_previous": {
    "test_id": "string (UUID)",
    "test_date": "string (ISO 8601)",
    "similarity_score": "number (0-1)",
    "confidence": "string (HIGH|MEDIUM|LOW)",
    "deltas": {
      "qps_delta_pct": "number",
      "p50_delta_pct": "number",
      "p95_delta_pct": "number",
      "p99_delta_pct": "number",
      "error_rate_delta_pct": "number"
    },
    "differences": ["string"]
  },
  
  "vs_median": {
    "qps_delta_pct": "number",
    "p95_delta_pct": "number",
    "verdict": "string (IMPROVED|REGRESSED|STABLE|INCONCLUSIVE)",
    "verdict_reasons": ["string"]
  },
  
  "trend": {
    "direction": "string (IMPROVING|REGRESSING|STABLE|INSUFFICIENT_DATA)",
    "qps_slope_per_run": "number",
    "p95_slope_per_run": "number",
    "sample_size": "integer",
    "r_squared": "number (goodness of fit)"
  },
  
  "comparable_runs": [
    {
      "test_id": "string (UUID)",
      "test_date": "string (ISO 8601)",
      "test_name": "string",
      "similarity_score": "number (0-1)",
      "confidence": "string (HIGH|MEDIUM|LOW)",
      "score_breakdown": {
        "scale_mode": "number",
        "concurrency": "number",
        "duration": "number",
        "warehouse": "number",
        "workload": "number",
        "cache": "number"
      },
      "match_reasons": ["string"],
      "differences": ["string"],
      "metrics": {
        "qps": "number",
        "p95_latency_ms": "number",
        "error_rate_pct": "number"
      }
    }
  ],
  
  "exclusions": [
    {
      "test_id": "string (UUID)",
      "score": "number",
      "reasons": ["string"]
    }
  ],
  
  "metadata": {
    "computed_at": "string (ISO 8601)",
    "computation_time_ms": "integer",
    "data_freshness": "string (ISO 8601)"
  }
}
```

**Example Response:**
```json
{
  "test_id": "382f1163-f01e-4e7b-9c9b-ff31f1894476",
  "template_id": "afd4d1b6-b9a1-46b1-baab-2fc82b6e9b4b",
  "load_mode": "FIND_MAX_CONCURRENCY",
  
  "baseline": {
    "available": true,
    "candidate_count": 8,
    "used_count": 5,
    "rolling_median": {
      "qps": 45.4,
      "p95_latency_ms": 961.4,
      "error_rate_pct": 0.0
    },
    "confidence_band": {
      "qps_p10": 19.5,
      "qps_p90": 49.1
    }
  },
  
  "vs_previous": {
    "test_id": "3b296cf0-1409-450a-b49a-d3793524961d",
    "test_date": "2026-02-10T04:14:17Z",
    "similarity_score": 0.92,
    "confidence": "HIGH",
    "deltas": {
      "qps_delta_pct": 281.4,
      "p95_delta_pct": 16.8
    }
  },
  
  "vs_median": {
    "qps_delta_pct": 135.2,
    "p95_delta_pct": -0.6,
    "verdict": "IMPROVED"
  },
  
  "trend": {
    "direction": "IMPROVING",
    "qps_slope_per_run": 12.3,
    "sample_size": 5
  },
  
  "comparable_runs": [
    {
      "test_id": "de220197-8df8-4842-ae7a-99768974c219",
      "similarity_score": 0.88,
      "confidence": "HIGH",
      "match_reasons": [
        "Same template and load mode",
        "Same warehouse size (MEDIUM)",
        "Same workload mix (100% reads)"
      ],
      "differences": [
        "Duration: 267s vs 300s"
      ],
      "metrics": {
        "qps": 43.9,
        "p95_latency_ms": 953.3
      }
    }
  ]
}
```

**Error Responses:**
| Status | Condition | Response |
|--------|-----------|----------|
| 404 | Test not found | `{"error": "Test not found", "test_id": "..."}` |
| 400 | Invalid parameters | `{"error": "Invalid parameter", "details": "..."}` |

### 11.2 Enhanced POST /api/tests/{test_id}/ai-analysis

**Changes:** Add optional `include_comparison` request-body field

**New Request Field (JSON body):**
| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `include_comparison` | bool | true | Include comparison context in AI analysis |

**Response Changes:**
Add `comparison_summary` field to response:
```json
{
  "analysis": "...",
  "comparison_summary": {
    "baseline_available": true,
    "vs_median_verdict": "IMPROVED",
    "qps_delta_pct": 135.2,
    "trend_direction": "IMPROVING",
    "confidence": "HIGH"
  }
}
```

---

**Previous:** [03-derived-metrics.md](03-derived-metrics.md) - Metric calculations and definitions  
**Next:** [05-ai-prompts-ui.md](05-ai-prompts-ui.md) - AI prompt enhancements and UI changes
