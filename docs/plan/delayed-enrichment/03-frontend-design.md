# Delayed Enrichment - Frontend Design

**Document Version:** 0.2 (Review Pass 1)  
**Parent:** [00-overview.md](00-overview.md)

---

## 1. Design Principles

### 1.1 Progressive Disclosure
Users should see immediately available metrics first, with clear indication that more data is coming. Don't hide existing data while waiting for delayed enrichment.

### 1.2 Clear Status Communication
Users must understand:
- What data is available NOW
- What data is COMING and WHEN
- What data is available ONLY after delayed enrichment

### 1.3 No False Precision
Don't show "0" or "N/A" for metrics that are simply not yet available. Distinguish between "no data" and "data pending".

### 1.4 Timing Display Standards
<!-- v0.2: Standardized timing format conventions -->
All timing values should be displayed consistently across the UI:
- Values < 1ms: show as "< 1ms"
- Values 1-999ms: show with 1 decimal place (e.g., "45.2ms")
- Values 1000-59999ms: show as seconds with 1 decimal (e.g., "1.2s")
- Values >= 60000ms: show as minutes:seconds (e.g., "2:15")

### 1.5 Section Hierarchy
<!-- v0.2: Document heading structure -->
The page's main title should use `<h1>`. Section cards should use `<h2>` for their titles, with subsections using `<h3>`. This ensures consistent accessibility and document outline.

---

## 2. Status Indicator Component

### 2.1 Enrichment Status Badge

<!-- v0.2: Unified status indicator replacing separate immediate/delayed badges -->
<!-- Badge color semantics:
     - badge-success = completed/positive (green)
     - badge-info = pending/informational (blue)
     - badge-warning = needs attention/partial failure (yellow/amber)
     - badge-error = failed/critical (red)
-->

Display a unified badge on the test detail page showing overall enrichment status:

```html
<!-- backend/templates/components/enrichment_status_badge.html -->
<!-- v0.2: Using DaisyUI semantic tokens for theme consistency -->
{% macro enrichment_status_badge(test_info) %}
<div class="enrichment-status-container" 
     x-data="{ showDetails: false }"
     x-init="$watch('templateInfo', () => checkDelayedEnrichment())"
     aria-live="polite">
    
    <!-- Unified Enrichment Status Badge -->
    <!-- v0.2: Single composite badge showing overall state -->
    {% if test_info.enrichment_status == 'PENDING' %}
    <span class="badge badge-warning" role="status" aria-label="Immediate enrichment in progress">
        <svg class="animate-spin h-3 w-3 inline mr-1" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        Enriching...
    </span>
    {% elif test_info.enrichment_status == 'FAILED' %}
    <span class="badge badge-error" role="status" aria-label="Enrichment failed">
        ✗ Enrichment Failed
    </span>
    {% elif test_info.enrichment_status == 'COMPLETED' and test_info.delayed_enrichment_status == 'COMPLETED' %}
    <span class="badge badge-success cursor-pointer" 
          role="status" 
          aria-label="Full metrics available"
          @click="showDetails = !showDetails"
          title="Click for details">
        ✓ Full Metrics
    </span>
    {% elif test_info.enrichment_status == 'COMPLETED' and test_info.delayed_enrichment_status == 'PENDING' %}
    <span class="badge badge-info cursor-pointer" 
          role="status"
          aria-label="Partial metrics available, full metrics in approximately {{ test_info.delayed_minutes_remaining | default(180) }} minutes"
          @click="showDetails = !showDetails"
          title="Click for details">
        <svg class="h-3 w-3 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
        </svg>
        Partial - full in ~{{ test_info.delayed_minutes_remaining | default(180) }}min
    </span>
    {% elif test_info.enrichment_status == 'COMPLETED' and test_info.delayed_enrichment_status == 'IN_PROGRESS' %}
    <span class="badge badge-info" role="status" aria-label="Loading full metrics">
        <svg class="animate-spin h-3 w-3 inline mr-1" viewBox="0 0 24 24" aria-hidden="true">
            <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
            <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        Loading full metrics...
    </span>
    {% elif test_info.enrichment_status == 'COMPLETED' and test_info.delayed_enrichment_status == 'FAILED' %}
    <!-- v0.2: Retry button surfaced directly next to badge, not hidden in dropdown -->
    <span class="inline-flex items-center gap-2">
        <span class="badge badge-warning" role="status" aria-label="Partial metrics available, delayed enrichment failed">
            ⚠ Partial - enrichment failed
        </span>
        <button @click="retryDelayedEnrichment()" 
                class="btn btn-xs btn-outline btn-warning"
                aria-label="Retry delayed enrichment">
            ↻ Retry
        </button>
    </span>
    {% endif %}
    
    <!-- Details Dropdown -->
    <div x-show="showDetails" 
         x-cloak
         class="absolute z-10 mt-2 p-4 bg-base-100 rounded-lg shadow-lg border"
         @click.outside="showDetails = false">
        
        <h4 class="font-semibold mb-2">Enrichment Details</h4>
        
        <div class="space-y-2 text-sm">
            <!-- Immediate Enrichment -->
            <div class="flex justify-between">
                <span>Immediate (QUERY_HISTORY)</span>
                <span x-text="templateInfo?.enrichment_status || 'Unknown'" 
                      :class="{
                          'text-success': templateInfo?.enrichment_status === 'COMPLETED',
                          'text-warning': templateInfo?.enrichment_status === 'PENDING',
                          'text-error': templateInfo?.enrichment_status === 'FAILED'
                      }"></span>
            </div>
            
            <!-- Delayed Enrichment -->
            <div class="flex justify-between">
                <span>Delayed (ACCOUNT_USAGE)</span>
                <span x-text="templateInfo?.delayed_enrichment_status || 'Pending'" 
                      :class="{
                          'text-success': templateInfo?.delayed_enrichment_status === 'COMPLETED',
                          'text-info': templateInfo?.delayed_enrichment_status === 'PENDING',
                          'text-error': templateInfo?.delayed_enrichment_status === 'FAILED'
                      }"></span>
            </div>
            
            <!-- Time remaining -->
            <div x-show="templateInfo?.delayed_enrichment_status === 'PENDING'" class="text-base-content/50">
                Available in approximately 
                <span x-text="Math.round(templateInfo?.delayed_minutes_remaining || 180)"></span> minutes
            </div>
            
            <!-- What's included -->
            <div class="mt-3 pt-2 border-t">
                <p class="font-medium text-xs text-base-content/50 mb-1">DELAYED METRICS INCLUDE:</p>
                <ul class="text-xs text-base-content/60 space-y-1">
                    <li x-show="templateInfo?.table_type === 'HYBRID'">• Server-side percentiles (p50, p90, p95, p99)</li>
                    <li x-show="templateInfo?.table_type === 'HYBRID'">• Lock contention events</li>
                    <li x-show="templateInfo?.table_type === 'HYBRID'">• Hybrid table credits</li>
                    <li>• Partition scan statistics</li>
                    <li>• Spill-to-disk metrics</li>
                    <li>• Query optimization insights</li>
                </ul>
            </div>
            
            <!-- Error details for failed -->
            <div x-show="templateInfo?.delayed_enrichment_status === 'FAILED'" class="mt-3">
                <p x-show="templateInfo?.delayed_enrichment_error" 
                   class="text-xs text-error"
                   x-text="templateInfo?.delayed_enrichment_error"></p>
            </div>
        </div>
    </div>
</div>
{% endmacro %}
```

### 2.2 JavaScript for Status Updates

```javascript
// backend/static/js/dashboard/delayed_enrichment.js

/**
 * Delayed Enrichment Status Handler
 * 
 * Polls for delayed enrichment status and updates UI when complete.
 */

const DELAYED_POLL_INTERVAL = 60000; // 1 minute

let delayedEnrichmentPollTimer = null;

async function checkDelayedEnrichment() {
    const testId = this.templateInfo?.test_id;
    if (!testId) return;
    
    const status = this.templateInfo?.delayed_enrichment_status;
    
    // Start polling if pending and not already polling
    if (status === 'PENDING' && !delayedEnrichmentPollTimer) {
        startDelayedEnrichmentPolling(testId);
    }
    
    // Stop polling if completed or failed
    if (status === 'COMPLETED' || status === 'FAILED') {
        stopDelayedEnrichmentPolling();
    }
}

function startDelayedEnrichmentPolling(testId) {
    console.log('Starting delayed enrichment polling for', testId);
    
    delayedEnrichmentPollTimer = setInterval(async () => {
        try {
            const response = await fetch(`/api/tests/${testId}/delayed-enrichment-status`);
            if (!response.ok) return;
            
            const data = await response.json();
            
            // Update templateInfo with new status
            if (this.templateInfo) {
                this.templateInfo.delayed_enrichment_status = data.status;
                this.templateInfo.delayed_minutes_remaining = data.minutes_remaining;
                this.templateInfo.delayed_enrichment_error = data.last_error;
            }
            
            // If completed, reload sections that use delayed data
            if (data.status === 'COMPLETED') {
                stopDelayedEnrichmentPolling();
                reloadDelayedMetricsSections();
            }
            
        } catch (error) {
            console.error('Error polling delayed enrichment status:', error);
        }
    }, DELAYED_POLL_INTERVAL);
}

function stopDelayedEnrichmentPolling() {
    if (delayedEnrichmentPollTimer) {
        clearInterval(delayedEnrichmentPollTimer);
        delayedEnrichmentPollTimer = null;
        console.log('Stopped delayed enrichment polling');
    }
}

async function retryDelayedEnrichment() {
    const testId = this.templateInfo?.test_id;
    if (!testId) return;
    
    try {
        const response = await fetch(`/api/tests/${testId}/retry-delayed-enrichment`, {
            method: 'POST',
        });
        
        if (!response.ok) {
            const error = await response.json();
            alert(`Retry failed: ${error.detail || 'Unknown error'}`);
            return;
        }
        
        const data = await response.json();
        
        // Update status
        if (this.templateInfo) {
            this.templateInfo.delayed_enrichment_status = 'PENDING';
            this.templateInfo.delayed_enrichment_error = null;
        }
        
        // Start polling
        startDelayedEnrichmentPolling(testId);
        
    } catch (error) {
        console.error('Error retrying delayed enrichment:', error);
        alert('Failed to retry delayed enrichment');
    }
}

function reloadDelayedMetricsSections() {
    // Trigger HTMX reload for sections that depend on delayed data
    const sections = [
        '#snowflake-execution-section',
        '#lock-contention-section',
        '#hybrid-credits-section',
        '#query-insights-section',
    ];
    
    sections.forEach(selector => {
        const element = document.querySelector(selector);
        if (element) {
            htmx.trigger(element, 'reload');
        }
    });
}
```

---

## 3. Snowflake Execution Details Section

### 3.1 New Section for Aggregate Metrics

Add a new section to the test detail page showing server-side percentiles from AGGREGATE_QUERY_HISTORY:

```html
<!-- backend/templates/partials/snowflake_execution_section.html -->
<!-- v0.2: Grid layout is already responsive (grid-cols-1 on mobile, scales up) -->
<div id="snowflake-execution-section" 
     class="card bg-base-100 shadow-xl mb-4"
     hx-get="/api/tests/{{ test_id }}/server-metrics"
     hx-trigger="load, reload"
     hx-swap="innerHTML">
    
    <div class="card-body">
        <h2 class="card-title flex items-center gap-2">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
            </svg>
            Snowflake Execution Details
            
            <!-- Status indicator -->
            <span x-show="templateInfo?.aggregate_enrichment_status !== 'COMPLETED'"
                  class="badge badge-info badge-sm"
                  role="status"
                  aria-label="Available after approximately 3 hours">
                <svg class="h-3 w-3 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                Available after ~3 hours
            </span>
        </h2>
        
        <!-- v0.2: Fixed skeleton state logic - info alert shows when NOT completed -->
        <div x-show="templateInfo?.aggregate_enrichment_status !== 'COMPLETED'"
             class="alert alert-info">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            <div>
                <p class="font-semibold">Snowflake execution details are collected from AGGREGATE_QUERY_HISTORY</p>
                <p class="text-sm">These metrics will be available approximately 3 hours after test completion. 
                   They include server-side execution percentiles that are more accurate than client-measured latencies,
                   especially for hybrid tables.</p>
            </div>
        </div>
        
        <!-- Skeleton loader - shows when actively loading (IN_PROGRESS) -->
        <div x-show="templateInfo?.aggregate_enrichment_status === 'IN_PROGRESS'"
             class="animate-pulse"
             role="status"
             aria-label="Loading Snowflake execution details">
            <div class="h-4 bg-base-300 rounded w-3/4 mb-2"></div>
            <div class="h-4 bg-base-300 rounded w-1/2"></div>
        </div>
        
        <!-- Actual metrics content - shows when COMPLETED -->
        <div x-show="templateInfo?.aggregate_enrichment_status === 'COMPLETED'"
             id="snowflake-execution-content">
            <!-- Will be populated by HTMX response -->
        </div>
    </div>
</div>
```

### 3.2 Snowflake Execution Details Content

```html
<!-- backend/templates/partials/snowflake_execution_content.html -->
<!-- v0.2: Using DaisyUI semantic tokens for theme consistency -->
{% if aggregate_metrics %}
<!-- Grid layout is already responsive: 1 col on mobile, 2 on md, 4 on lg -->
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
    
    <!-- Execution Time Card -->
    <div class="stat bg-base-200 rounded-lg">
        <div class="stat-title">Server Execution Time</div>
        <div class="stat-value text-lg">{{ aggregate_metrics.exec_p95_ms | round(1) }}ms</div>
        <div class="stat-desc">P95 across {{ aggregate_metrics.unique_query_patterns }} patterns</div>
        
        <div class="mt-2 text-xs space-y-1">
            <div class="flex justify-between">
                <span>p50</span>
                <span>{{ aggregate_metrics.exec_median_ms | round(1) }}ms</span>
            </div>
            <div class="flex justify-between">
                <span>p90</span>
                <span>{{ aggregate_metrics.exec_p90_ms | round(1) }}ms</span>
            </div>
            <div class="flex justify-between">
                <span>p99</span>
                <span>{{ aggregate_metrics.exec_p99_ms | round(1) }}ms</span>
            </div>
            <div class="flex justify-between">
                <span>max</span>
                <span>{{ aggregate_metrics.exec_max_ms | round(1) }}ms</span>
            </div>
        </div>
    </div>
    
    <!-- Compilation Time Card -->
    <div class="stat bg-base-200 rounded-lg">
        <div class="stat-title">Compilation Time</div>
        <div class="stat-value text-lg">{{ aggregate_metrics.compile_avg_ms | round(1) }}ms</div>
        <div class="stat-desc">Average compilation overhead</div>
        
        <div class="mt-2 text-xs space-y-1">
            <div class="flex justify-between">
                <span>min</span>
                <span>{{ aggregate_metrics.compile_min_ms | round(1) }}ms</span>
            </div>
            <div class="flex justify-between">
                <span>max</span>
                <span>{{ aggregate_metrics.compile_max_ms | round(1) }}ms</span>
            </div>
        </div>
    </div>
    
    <!-- Queue Time Card -->
    <div class="stat bg-base-200 rounded-lg">
        <div class="stat-title">Queue Time</div>
        <div class="stat-value text-lg">{{ aggregate_metrics.queued_overload_avg_ms | round(1) }}ms</div>
        <div class="stat-desc">Average time waiting for resources</div>
        
        <div class="mt-2 text-xs space-y-1">
            <div class="flex justify-between">
                <span>max overload</span>
                <span>{{ aggregate_metrics.queued_overload_max_ms | round(1) }}ms</span>
            </div>
            <div class="flex justify-between">
                <span>max provisioning</span>
                <span>{{ aggregate_metrics.queued_provisioning_max_ms | round(1) }}ms</span>
            </div>
        </div>
    </div>
    
    <!-- Throttling Card (Hybrid only) -->
    {% if aggregate_metrics.total_throttled_requests > 0 %}
    <div class="stat bg-warning/20 rounded-lg">
        <div class="stat-title">Throttled Requests</div>
        <div class="stat-value text-lg text-warning">{{ aggregate_metrics.total_throttled_requests }}</div>
        <div class="stat-desc">Hybrid table requests that were throttled</div>
        
        <div class="mt-2 text-xs text-warning-content">
            ⚠ High throttling may indicate capacity limits
        </div>
    </div>
    {% else %}
    <div class="stat bg-base-200 rounded-lg">
        <div class="stat-title">Throttled Requests</div>
        <div class="stat-value text-lg text-success">0</div>
        <div class="stat-desc">No throttling detected</div>
    </div>
    {% endif %}
</div>

<!-- Query Pattern Breakdown -->
<div class="mt-4">
    <h3 class="font-semibold mb-2">Query Pattern Breakdown</h3>
    <!-- overflow-x-auto wrapper for mobile responsiveness -->
    <div class="overflow-x-auto">
        <table class="table table-compact w-full">
            <thead>
                <tr>
                    <th>Pattern Hash</th>
                    <th class="text-right">Count</th>
                    <th class="text-right">Avg Exec (ms)</th>
                    <th class="text-right">P95 Exec (ms)</th>
                    <th class="text-right">Max Exec (ms)</th>
                    <th class="text-right">Errors</th>
                </tr>
            </thead>
            <tbody>
                {% for pattern in aggregate_metrics.patterns[:10] %}
                <tr>
                    <td class="font-mono text-xs">{{ pattern.hash[:16] }}...</td>
                    <td class="text-right">{{ pattern.query_count | format_number }}</td>
                    <td class="text-right">{{ pattern.exec_avg_ms | round(1) }}</td>
                    <td class="text-right">{{ pattern.exec_p95_ms | round(1) }}</td>
                    <td class="text-right">{{ pattern.exec_max_ms | round(1) }}</td>
                    <td class="text-right {% if pattern.errors_count > 0 %}text-error{% endif %}">
                        {{ pattern.errors_count }}
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>
{% else %}
<div class="text-center py-8 text-base-content/50">
    <p>Snowflake execution details not yet available.</p>
    <p class="text-sm">Check back after delayed enrichment completes.</p>
</div>
{% endif %}
```

---

## 4. Lock Contention Section

### 4.1 Lock Contention Timeline

For hybrid tables, show lock contention events in a timeline:

```html
<!-- backend/templates/partials/lock_contention_section.html -->
<div id="lock-contention-section" 
     class="card bg-base-100 shadow-xl mb-4"
     x-show="templateInfo?.table_type === 'HYBRID'"
     hx-get="/api/tests/{{ test_id }}/lock-contention"
     hx-trigger="load, reload"
     hx-swap="innerHTML">
    
    <div class="card-body">
        <h2 class="card-title flex items-center gap-2">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z"></path>
            </svg>
            Row-Level Lock Contention
            
            <span x-show="templateInfo?.delayed_enrichment_status !== 'COMPLETED'"
                  class="badge badge-info badge-sm"
                  role="status"
                  aria-label="Available after approximately 3 hours">
                Available after ~3 hours
            </span>
        </h2>
        
        <!-- Content loaded via HTMX -->
    </div>
</div>
```

### 4.2 Lock Contention Content

```html
<!-- backend/templates/partials/lock_contention_content.html -->
{% if lock_events %}
<div class="space-y-4">
    
    <!-- Summary Stats -->
    <div class="stats stats-horizontal shadow">
        <div class="stat">
            <div class="stat-title">Lock Wait Events</div>
            <div class="stat-value">{{ lock_summary.count }}</div>
        </div>
        <div class="stat">
            <div class="stat-title">Total Wait Time</div>
            <div class="stat-value">{{ lock_summary.total_ms | round(0) }}ms</div>
        </div>
        <div class="stat">
            <div class="stat-title">Max Wait</div>
            <div class="stat-value">{{ lock_summary.max_ms | round(0) }}ms</div>
        </div>
        <div class="stat">
            <div class="stat-title">Avg Wait</div>
            <div class="stat-value">{{ lock_summary.avg_ms | round(1) }}ms</div>
        </div>
    </div>
    
    <!-- Timeline Chart -->
    <div class="h-64">
        <canvas id="lock-contention-timeline"></canvas>
    </div>
    
    <!-- Event Table -->
    <!-- overflow-x-auto wrapper for mobile responsiveness -->
    <div class="overflow-x-auto">
        <table class="table table-compact w-full">
            <thead>
                <tr>
                    <th>Time</th>
                    <th class="text-right">Wait (ms)</th>
                    <th>Blocking Query</th>
                </tr>
            </thead>
            <tbody>
                {% for event in lock_events[:20] %}
                <tr>
                    <td class="text-xs">{{ event.requested_at | format_time }}</td>
                    <td class="text-right {% if event.wait_duration_ms > 100 %}text-warning{% endif %}">
                        {{ event.wait_duration_ms | round(1) }}
                    </td>
                    <td class="font-mono text-xs truncate max-w-xs" title="{{ event.blocking_query_id }}">
                        {{ event.blocking_query_id[:20] }}...
                    </td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
    
    {% if lock_events | length > 20 %}
    <div class="text-center text-sm text-base-content/50">
        Showing 20 of {{ lock_events | length }} events
    </div>
    {% endif %}
</div>

{% elif templateInfo.delayed_enrichment_status == 'COMPLETED' %}
<div class="text-center py-8">
    <div class="text-success text-4xl mb-2">✓</div>
    <p class="font-semibold">No Lock Contention Detected</p>
    <p class="text-sm text-base-content/50">No row-level lock waits were recorded during this test.</p>
</div>

{% else %}
<div class="alert alert-info">
    <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
    </svg>
    <span>Lock contention data will be available approximately 3 hours after test completion.</span>
</div>
{% endif %}
```

---

## 5. Hybrid Table Credits Section

### 5.1 Credit Cost Card

```html
<!-- backend/templates/partials/hybrid_credits_section.html -->
<div id="hybrid-credits-section" 
     class="card bg-base-100 shadow-xl mb-4"
     x-show="templateInfo?.table_type === 'HYBRID'"
     hx-get="/api/tests/{{ test_id }}/hybrid-credits"
     hx-trigger="load, reload"
     hx-swap="innerHTML">
    
    <div class="card-body">
        <h2 class="card-title flex items-center gap-2">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            Hybrid Table Credits
            
            <span x-show="templateInfo?.delayed_enrichment_status !== 'COMPLETED'"
                  class="badge badge-info badge-sm"
                  role="status"
                  aria-label="Available after approximately 3 hours">
                Available after ~3 hours
            </span>
        </h2>
        
        <!-- Content loaded via HTMX -->
    </div>
</div>
```

### 5.2 Credits Content

```html
<!-- backend/templates/partials/hybrid_credits_content.html -->
{% if credits %}
<div class="stats stats-horizontal shadow w-full">
    <div class="stat">
        <div class="stat-figure text-primary">
            <svg class="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
        </div>
        <div class="stat-title">Credits Used</div>
        <div class="stat-value text-primary">{{ credits.total_credits | round(4) }}</div>
        <div class="stat-desc">Serverless compute credits</div>
    </div>
    
    <div class="stat">
        <div class="stat-title">Requests</div>
        <div class="stat-value">{{ credits.total_requests | format_number }}</div>
        <div class="stat-desc">Total hybrid table requests</div>
    </div>
    
    <div class="stat">
        <div class="stat-title">Cost per 1K Requests</div>
        <div class="stat-value text-sm">
            {{ (credits.total_credits / credits.total_requests * 1000) | round(6) }}
        </div>
        <div class="stat-desc">Credits</div>
    </div>
    
    <div class="stat">
        <div class="stat-title">Estimated Cost</div>
        <div class="stat-value text-sm">
            ${{ (credits.total_credits * 3.00) | round(4) }}
        </div>
        <div class="stat-desc">@ $3/credit (estimate)</div>
    </div>
</div>

{% elif templateInfo.delayed_enrichment_status == 'COMPLETED' %}
<div class="alert">
    <span>No hybrid table credit data found for this test.</span>
</div>

{% else %}
<div class="alert alert-info">
    <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
    </svg>
    <span>Credit consumption data will be available approximately 3 hours after test completion.</span>
</div>
{% endif %}
```

---

## 6. Query Insights Section

### 6.1 Optimization Suggestions

```html
<!-- backend/templates/partials/query_insights_section.html -->
<div id="query-insights-section" 
     class="card bg-base-100 shadow-xl mb-4"
     hx-get="/api/tests/{{ test_id }}/query-insights"
     hx-trigger="load, reload"
     hx-swap="innerHTML">
    
    <div class="card-body">
        <h2 class="card-title flex items-center gap-2">
            <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
            </svg>
            Query Optimization Insights
            
            <span x-show="templateInfo?.delayed_enrichment_status !== 'COMPLETED'"
                  class="badge badge-info badge-sm"
                  role="status"
                  aria-label="Available after approximately 90 minutes">
                Available after ~90 minutes
            </span>
        </h2>
        
        <!-- Content loaded via HTMX -->
    </div>
</div>
```

### 6.2 Insights Content

```html
<!-- backend/templates/partials/query_insights_content.html -->
{% if insights %}
<div class="space-y-3">
    {% for insight in insights %}
    <div class="alert {% if insight.severity == 'HIGH' %}alert-warning{% else %}alert-info{% endif %}">
        <div class="flex-1">
            <div class="flex items-center gap-2">
                {% if insight.severity == 'HIGH' %}
                <svg class="h-5 w-5 text-warning" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"></path>
                </svg>
                {% else %}
                <svg class="h-5 w-5 text-info" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
                {% endif %}
                <span class="font-semibold">{{ insight.insight_type }}</span>
                <span class="badge badge-sm" role="status" aria-label="{{ insight.affected_query_count }} queries affected">{{ insight.affected_query_count }} queries</span>
            </div>
            <p class="mt-1">{{ insight.recommendation }}</p>
        </div>
    </div>
    {% endfor %}
</div>

{% elif templateInfo.delayed_enrichment_status == 'COMPLETED' %}
<div class="text-center py-8">
    <div class="text-success text-4xl mb-2">✓</div>
    <p class="font-semibold">No Optimization Issues Found</p>
    <p class="text-sm text-base-content/50">Snowflake's query optimizer found no significant improvement opportunities.</p>
</div>

{% else %}
<div class="alert alert-info">
    <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"></path>
    </svg>
    <span>Query insights will be available approximately 90 minutes after test completion.</span>
</div>
{% endif %}
```

---

## 7. Latency Section Updates

### 7.1 Show Enrichment Coverage

Update the existing latency section to show enrichment coverage and clarify when data is from AGGREGATE_QUERY_HISTORY:

```html
<!-- Add to existing latency section -->
<div class="mb-4" x-show="templateInfo?.table_type === 'HYBRID'">
    <div class="alert alert-info">
        <svg class="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
        </svg>
        <div>
            <p class="font-semibold">Hybrid Table Latency Note</p>
            <p class="text-sm">
                For hybrid tables, client-measured latencies shown below capture the full round-trip time.
                Server-side execution percentiles are available in the 
                <a href="#snowflake-execution-section" class="link">Snowflake Execution Details</a> section
                after delayed enrichment completes (~3 hours).
            </p>
        </div>
    </div>
</div>
```

---

## 8. API Endpoints for Frontend

### 8.1 Snowflake Execution Details Endpoint

```python
# backend/api/routes/test_results.py

@router.get("/{test_id}/server-metrics")
async def get_server_metrics(test_id: str, request: Request):
    """
    Get server-side metrics from AGGREGATE_QUERY_METRICS.
    
    Returns HTML partial for HTMX or JSON based on Accept header.
    """
    pool = snowflake_pool.get_default_pool()
    prefix = _results_prefix()
    
    # Get aggregate stats
    rows = await pool.execute_query(
        f"""
        SELECT
            COUNT(DISTINCT QUERY_PARAMETERIZED_HASH) AS unique_query_patterns,
            SUM(QUERY_COUNT) AS total_queries,
            SUM(EXEC_SUM_MS) AS total_exec_ms,
            AVG(EXEC_AVG_MS) AS exec_avg_ms,
            AVG(EXEC_MEDIAN_MS) AS exec_median_ms,
            MAX(EXEC_P90_MS) AS exec_p90_ms,
            MAX(EXEC_P95_MS) AS exec_p95_ms,
            MAX(EXEC_P99_MS) AS exec_p99_ms,
            MAX(EXEC_MAX_MS) AS exec_max_ms,
            AVG(COMPILE_AVG_MS) AS compile_avg_ms,
            MIN(COMPILE_MIN_MS) AS compile_min_ms,
            MAX(COMPILE_MAX_MS) AS compile_max_ms,
            AVG(QUEUED_OVERLOAD_AVG_MS) AS queued_overload_avg_ms,
            MAX(QUEUED_OVERLOAD_MAX_MS) AS queued_overload_max_ms,
            MAX(QUEUED_PROVISIONING_MAX_MS) AS queued_provisioning_max_ms,
            SUM(HYBRID_REQUESTS_THROTTLED_COUNT) AS total_throttled_requests,
            SUM(ERRORS_COUNT) AS total_errors
        FROM {prefix}.AGGREGATE_QUERY_METRICS
        WHERE TEST_ID = ?
        """,
        params=[test_id],
    )
    
    if not rows or not rows[0][0]:
        # No aggregate metrics yet
        if "text/html" in request.headers.get("accept", ""):
            return templates.TemplateResponse(
                "partials/snowflake_execution_content.html",
                {"request": request, "aggregate_metrics": None, "templateInfo": {}},
            )
        return {"aggregate_metrics": None}
    
    # Parse results
    row = rows[0]
    aggregate_metrics = {
        "unique_query_patterns": row[0],
        "total_queries": row[1],
        "total_exec_ms": row[2],
        "exec_avg_ms": row[3],
        "exec_median_ms": row[4],
        "exec_p90_ms": row[5],
        "exec_p95_ms": row[6],
        "exec_p99_ms": row[7],
        "exec_max_ms": row[8],
        "compile_avg_ms": row[9],
        "compile_min_ms": row[10],
        "compile_max_ms": row[11],
        "queued_overload_avg_ms": row[12],
        "queued_overload_max_ms": row[13],
        "queued_provisioning_max_ms": row[14],
        "total_throttled_requests": row[15] or 0,
        "total_errors": row[16] or 0,
    }
    
    # Get pattern breakdown
    pattern_rows = await pool.execute_query(
        f"""
        SELECT
            QUERY_PARAMETERIZED_HASH,
            QUERY_COUNT,
            EXEC_AVG_MS,
            EXEC_P95_MS,
            EXEC_MAX_MS,
            ERRORS_COUNT
        FROM {prefix}.AGGREGATE_QUERY_METRICS
        WHERE TEST_ID = ?
        ORDER BY QUERY_COUNT DESC
        LIMIT 10
        """,
        params=[test_id],
    )
    
    aggregate_metrics["patterns"] = [
        {
            "hash": row[0],
            "query_count": row[1],
            "exec_avg_ms": row[2],
            "exec_p95_ms": row[3],
            "exec_max_ms": row[4],
            "errors_count": row[5] or 0,
        }
        for row in pattern_rows
    ]
    
    if "text/html" in request.headers.get("accept", ""):
        return templates.TemplateResponse(
            "partials/snowflake_execution_content.html",
            {"request": request, "aggregate_metrics": aggregate_metrics},
        )
    
    return {"aggregate_metrics": aggregate_metrics}
```

---

**Next:** [04-implementation-phases.md](04-implementation-phases.md) - Phased rollout with acceptance criteria
