# Cost Metrics Enhancement Plan

Comprehensive cost analysis and comparison features for architect decision-making.

**Status**: ✅ Implemented

## Current State Analysis

### What Exists

**Backend (`backend/core/cost_calculator.py`)**:
- Full pricing tables for all Snowflake compute types:
  - Standard warehouses (Table 1a): XSMALL=1 cr/hr, MEDIUM=4 cr/hr, etc.
  - Interactive warehouses (Table 1d): 60% of standard rates
  - Postgres compute (Table 1i): STANDARD_M=0.0356 cr/hr, BURST_XS=0.0068 cr/hr
- Functions: `calculate_estimated_cost()`, `calculate_cost_efficiency()`, `get_table_type_category()`
- Configurable `dollars_per_credit` (default $4.00)
- Ensure calculations use max # of warehouses during snowflake benchmarks per run

**Frontend (`backend/static/js/cost-utils.js`)**:
- Mirrors backend pricing tables
- User-configurable settings in localStorage
- Formatting utilities: `formatCost()`, `formatCredits()`, `formatCostWithCredits()`
- Tooltip generation with detailed breakdowns

**API (`backend/api/routes/test_results.py`)**:
- `_build_cost_fields()` enriches responses with:
  - `credits_used`, `estimated_cost_usd`, `cost_per_hour`
  - `credits_per_hour`, `cost_calculation_method`
  - `cost_per_1000_ops`, `cost_per_1k_ops`

### Gap Analysis by Page

| Page | Current State | Gap |
|------|--------------|-----|
| History List | ✅ Estimated Cost, Cost/1K Ops with tooltips | Minor: No credits column |
| History Compare Sidebar | ✅ Full cost comparison | None |
| Single Run Detail | ⚠️ Minimal cost display | Missing: Cost Summary card |
| **Deep Compare** | ❌ **Zero cost information** | Critical: No cost section despite available utilities |

### Unused Code (Deep Compare)

`backend/static/js/compare_detail.js` has these **unused** functions:
```javascript
calcCostDelta(valA, valB)      // Lines 497-501
formatCostDelta(delta)          // Lines 507-512
```

These exist but are never called in the Statistics Comparison table.

## Implementation Tasks

### Task 1: Add Cost Rows to Deep Compare Statistics Table

**File**: `backend/templates/pages/history_compare.html`
**Location**: Lines 186-227 (Statistics Comparison tbody)

Add rows after Error Rate row:

```html
<!-- Cost Comparison Section -->
<tr class="border-b border-t-2 border-gray-300">
    <td class="py-2 px-3 font-semibold text-gray-700" colspan="4">Cost Analysis</td>
</tr>
<tr class="border-b">
    <td class="py-2 px-3 font-medium">Estimated Cost</td>
    <td class="text-right py-2 px-3" x-text="testA?.estimated_cost_usd != null ? '$' + testA.estimated_cost_usd.toFixed(4) : '—'"></td>
    <td class="text-right py-2 px-3" x-text="testB?.estimated_cost_usd != null ? '$' + testB.estimated_cost_usd.toFixed(4) : '—'"></td>
    <td class="text-right py-2 px-3" :class="getDeltaClass(calcCostDelta(testA?.estimated_cost_usd, testB?.estimated_cost_usd), true)" x-text="formatCostDelta(calcCostDelta(testA?.estimated_cost_usd, testB?.estimated_cost_usd))"></td>
</tr>
<tr class="border-b">
    <td class="py-2 px-3 font-medium">Cost per 1K Ops</td>
    <td class="text-right py-2 px-3" x-text="testA?.cost_per_1k_ops != null ? '$' + testA.cost_per_1k_ops.toFixed(4) : '—'"></td>
    <td class="text-right py-2 px-3" x-text="testB?.cost_per_1k_ops != null ? '$' + testB.cost_per_1k_ops.toFixed(4) : '—'"></td>
    <td class="text-right py-2 px-3" :class="getDeltaClass(calcCostDelta(testA?.cost_per_1k_ops, testB?.cost_per_1k_ops), true)" x-text="formatCostDelta(calcCostDelta(testA?.cost_per_1k_ops, testB?.cost_per_1k_ops))"></td>
</tr>
<tr class="border-b">
    <td class="py-2 px-3 font-medium">Credits Used</td>
    <td class="text-right py-2 px-3" x-text="testA?.credits_used != null ? testA.credits_used.toFixed(4) : '—'"></td>
    <td class="text-right py-2 px-3" x-text="testB?.credits_used != null ? testB.credits_used.toFixed(4) : '—'"></td>
    <td class="text-right py-2 px-3 text-gray-500">—</td>
</tr>
<tr>
    <td class="py-2 px-3 font-medium">Credit Rate (cr/hr)</td>
    <td class="text-right py-2 px-3" x-text="testA?.credits_per_hour != null ? testA.credits_per_hour.toFixed(4) : '—'"></td>
    <td class="text-right py-2 px-3" x-text="testB?.credits_per_hour != null ? testB.credits_per_hour.toFixed(4) : '—'"></td>
    <td class="text-right py-2 px-3 text-gray-500">—</td>
</tr>
```

### Task 2: Add Cost Efficiency Card to Deep Compare

**File**: `backend/templates/pages/history_compare.html`
**Location**: After Statistics Comparison card (around line 235)

New card showing architect-focused metrics:

```html
<!-- Cost Efficiency Analysis Card -->
<div class="card" x-show="testA && testB">
    <div class="card-title">Cost Efficiency Analysis</div>
    <div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem;">
        <!-- Value Score: QPS per Dollar -->
        <div style="background: linear-gradient(135deg, #dcfce7 0%, #f0fdf4 100%); border-radius: 0.5rem; padding: 1rem; border: 1px solid #bbf7d0;">
            <div style="font-weight: 600; color: #166534; margin-bottom: 0.5rem;">Value Score (QPS/$)</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; font-size: 0.875rem;">
                <div>
                    <span style="color: #6b7280;">Primary:</span>
                    <span style="font-weight: 600;" x-text="testA?.estimated_cost_usd > 0 ? ((testA?.qps || 0) / testA.estimated_cost_usd).toFixed(0) : '—'"></span>
                </div>
                <div>
                    <span style="color: #6b7280;">Secondary:</span>
                    <span style="font-weight: 600;" x-text="testB?.estimated_cost_usd > 0 ? ((testB?.qps || 0) / testB.estimated_cost_usd).toFixed(0) : '—'"></span>
                </div>
            </div>
            <div style="font-size: 0.75rem; color: #6b7280; margin-top: 0.5rem;">Higher is better (more throughput per dollar)</div>
        </div>
        <!-- Break-even Analysis -->
        <div style="background: linear-gradient(135deg, #fef3c7 0%, #fffbeb 100%); border-radius: 0.5rem; padding: 1rem; border: 1px solid #fde68a;">
            <div style="font-weight: 600; color: #92400e; margin-bottom: 0.5rem;">Hourly Cost Difference</div>
            <div style="font-size: 1.25rem; font-weight: 700;" 
                 :style="{ color: (testA?.cost_per_hour || 0) < (testB?.cost_per_hour || 0) ? '#166534' : '#dc2626' }"
                 x-text="'$' + Math.abs((testA?.cost_per_hour || 0) - (testB?.cost_per_hour || 0)).toFixed(2) + '/hr ' + ((testA?.cost_per_hour || 0) < (testB?.cost_per_hour || 0) ? 'savings' : 'more')">
            </div>
            <div style="font-size: 0.75rem; color: #6b7280; margin-top: 0.5rem;">
                Primary: $<span x-text="(testA?.cost_per_hour || 0).toFixed(2)"></span>/hr |
                Secondary: $<span x-text="(testB?.cost_per_hour || 0).toFixed(2)"></span>/hr
            </div>
        </div>
    </div>
</div>
```

### Task 3: Add Cost Summary Card to Single Run Detail

**File**: `backend/templates/pages/dashboard_history.html`
**Location**: After the existing info cards (around line 100)

```html
<!-- Cost Summary Card -->
<div class="card" x-show="templateInfo">
    <div class="card-title">Cost Summary</div>
    <div class="text-sm text-gray-600">
        <div class="mt-1">
            <strong>Estimated Cost:</strong>
            <span x-text="templateInfo?.estimated_cost_usd != null ? '$' + templateInfo.estimated_cost_usd.toFixed(4) : '—'"></span>
        </div>
        <div class="mt-1">
            <strong>Credits Used:</strong>
            <span x-text="templateInfo?.credits_used != null ? templateInfo.credits_used.toFixed(4) + ' credits' : '—'"></span>
        </div>
        <div class="mt-1">
            <strong>Credit Rate:</strong>
            <span x-text="templateInfo?.credits_per_hour != null ? templateInfo.credits_per_hour.toFixed(4) + ' cr/hr' : '—'"></span>
        </div>
        <div class="mt-1">
            <strong>Cost per 1K Ops:</strong>
            <span x-text="templateInfo?.cost_per_1k_ops != null ? '$' + templateInfo.cost_per_1k_ops.toFixed(4) : '—'"></span>
        </div>
        <div class="mt-1 text-xs text-gray-400">
            <span x-text="'Method: ' + (templateInfo?.cost_calculation_method || 'estimated')"></span>
        </div>
    </div>
</div>
```

### Task 4: Verify API Cost Fields

**File**: `backend/api/routes/test_results.py`

Ensure `_build_cost_fields()` includes all required fields in API responses:
- `credits_used`
- `estimated_cost_usd`
- `cost_per_hour`
- `credits_per_hour`
- `cost_calculation_method`
- `cost_per_1000_ops`
- `cost_per_1k_ops`

No changes expected - just verification.

### Task 5: Optional - Add Credits Column to History List

**File**: `backend/templates/pages/history.html`
**Priority**: Low

Add optional "Credits" column to the history table for users who prefer credit-based analysis.

## Architect Decision Metrics

The enhanced cost display enables architects to evaluate:

1. **Total Cost of Ownership (TCO)**
   - Estimated cost per test run
   - Extrapolation to production workloads

2. **Cost Efficiency**
   - Cost per 1K operations (lower is better)
   - QPS per dollar (higher is better)

3. **Technology Comparison**
   - Hybrid Tables vs Postgres: Fair comparison using same credit-based pricing
   - Warehouse size impact on cost/performance ratio

4. **Break-even Analysis**
   - Hourly cost difference between configurations
   - ROI calculation for architecture decisions

## File Reference

| File | Purpose |
|------|---------|
| `backend/core/cost_calculator.py` | Cost calculation logic |
| `backend/static/js/cost-utils.js` | Frontend cost utilities |
| `backend/api/routes/test_results.py` | API cost field builder |
| `backend/templates/pages/history_compare.html` | Deep Compare page |
| `backend/templates/pages/dashboard_history.html` | Single run detail page |
| `backend/templates/pages/history.html` | History list page |
| `backend/static/js/compare_detail.js` | Compare page JS (has unused cost functions) |

## Acceptance Criteria

- [ ] Deep Compare page shows Estimated Cost, Cost/1K Ops, Credits Used, Credit Rate
- [ ] Deep Compare shows delta calculations (% savings/increase)
- [ ] Cost Efficiency Analysis card displays QPS/$ and hourly cost difference
- [ ] Single Run Detail page shows Cost Summary card
- [ ] All cost values use consistent formatting (4 decimal places for small values)
- [ ] Lower cost shows green, higher cost shows red in delta columns
