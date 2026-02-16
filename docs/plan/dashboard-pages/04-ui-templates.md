# Dashboard Pages - UI Templates

**Parent:** [00-overview.md](00-overview.md)

---

## 1. Page Routes

| URL | Template | Description |
|-----|----------|-------------|
| `/dashboard/table-types` | `dashboard_table_types.html` | Table type comparison |
| `/dashboard/templates` | `dashboard_templates.html` | Template list |
| `/dashboard/templates/{id}` | `dashboard_template_analysis.html` | Template deep-dive |

---

## 2. Table Type Comparison Page

### 2.1 Layout Structure

```html
<!-- dashboard_table_types.html -->
{% extends "base.html" %}
{% block title %}Table Type Comparison{% endblock %}

{% block content %}
<div x-data="tableTypesDashboard()" x-init="init()">
    
    <!-- Header -->
    <div class="flex justify-between items-center mb-6">
        <h1 class="text-2xl font-bold">Table Type Comparison</h1>
        <div class="text-sm text-gray-500">
            Last updated: <span x-text="formatDate(data?.generated_at)"></span>
        </div>
    </div>

    <!-- KPI Cards Row -->
    <div class="grid grid-cols-5 gap-4 mb-6">
        <template x-for="kpi in data?.kpi_cards || []" :key="kpi.table_type">
            <div class="card" :class="{'ring-2 ring-green-500': kpi.badges.includes('winner_qps')}">
                <!-- KPI Card Content -->
            </div>
        </template>
    </div>

    <!-- Recommendations Panel -->
    <div class="grid grid-cols-3 gap-4 mb-6">
        <!-- Recommendation Cards -->
    </div>

    <!-- Comparison Table -->
    <div class="card mb-6">
        <div class="card-title">Performance Comparison</div>
        <!-- Comparison Table -->
    </div>

    <!-- Charts Row -->
    <div class="grid grid-cols-2 gap-4 mb-6">
        <div class="card">
            <div class="card-title">Performance by Table Type</div>
            <canvas id="performanceChart"></canvas>
        </div>
        <div class="card">
            <div class="card-title">Cost Efficiency</div>
            <canvas id="costChart"></canvas>
        </div>
    </div>

    <!-- Recent Tests Table -->
    <div class="card">
        <div class="card-title">Recent Tests</div>
        <!-- Tests Table -->
    </div>

</div>
{% endblock %}
```

### 2.2 KPI Card Component

```html
<!-- KPI Card for each table type -->
<div class="card relative p-4" 
     :class="{
         'ring-2 ring-green-500': kpi.badges.includes('winner_qps'),
         'bg-gray-50': kpi.table_type === 'DYNAMIC'
     }">
    
    <!-- Winner Badge -->
    <div x-show="kpi.badges.includes('winner_qps')" 
         class="absolute -top-2 -right-2 bg-green-500 text-white text-xs px-2 py-1 rounded-full">
        🏆 Best QPS
    </div>
    
    <!-- Table Type Header -->
    <div class="flex items-center gap-2 mb-3">
        <div class="w-3 h-3 rounded-full" :style="{ backgroundColor: getTableTypeColor(kpi.table_type) }"></div>
        <span class="font-semibold text-lg" x-text="kpi.table_type"></span>
    </div>
    
    <!-- Test Count -->
    <div class="text-3xl font-bold mb-1" x-text="kpi.test_count"></div>
    <div class="text-sm text-gray-500 mb-3">tests run</div>
    
    <!-- Key Metrics -->
    <div class="space-y-2 text-sm">
        <div class="flex justify-between">
            <span class="text-gray-600">Avg QPS</span>
            <span class="font-medium" x-text="formatNumber(kpi.avg_qps)"></span>
        </div>
        <div class="flex justify-between">
            <span class="text-gray-600">Avg p95</span>
            <span class="font-medium" x-text="formatLatency(kpi.avg_p95_ms)"></span>
        </div>
        <div class="flex justify-between">
            <span class="text-gray-600">Cost/1K ops</span>
            <span class="font-medium" x-text="formatCost(kpi.cost_per_1k_ops_usd)"></span>
        </div>
    </div>
    
    <!-- Stability Badge -->
    <div class="mt-3 pt-3 border-t">
        <span class="inline-flex items-center px-2 py-1 rounded-full text-xs"
              :class="getStabilityBadgeClass(kpi.stability_badge)">
            <span x-text="kpi.stability_badge"></span>
        </span>
    </div>
</div>
```

### 2.3 Recommendation Card Component

```html
<!-- Recommendation Card -->
<div class="card p-4" 
     :style="{ borderLeftColor: getWorkloadColor(rec.workload_type), borderLeftWidth: '4px' }">
    
    <!-- Workload Type Header -->
    <div class="flex items-center justify-between mb-2">
        <span class="font-semibold" x-text="rec.workload_type + ' Workloads'"></span>
        <span class="text-xs px-2 py-1 bg-green-100 text-green-800 rounded-full"
              x-text="Math.round(rec.confidence * 100) + '% confident'"></span>
    </div>
    
    <!-- Recommendation -->
    <div class="flex items-center gap-2 mb-2">
        <span class="text-gray-600">Recommended:</span>
        <span class="font-bold text-lg" 
              :style="{ color: getTableTypeColor(rec.recommended_table_type) }"
              x-text="rec.recommended_table_type"></span>
    </div>
    
    <!-- Rationale -->
    <p class="text-sm text-gray-600 mb-2" x-text="rec.rationale"></p>
    
    <!-- Runner Up -->
    <div class="text-xs text-gray-500" x-show="rec.runner_up">
        Runner-up: <span x-text="rec.runner_up"></span>
    </div>
</div>
```

### 2.4 Comparison Table Component

```html
<!-- Comparison Table -->
<table class="w-full text-sm">
    <thead>
        <tr class="border-b">
            <th class="text-left py-2 px-3">Metric</th>
            <template x-for="col in ['STANDARD', 'HYBRID', 'INTERACTIVE', 'DYNAMIC', 'POSTGRES']">
                <th class="text-right py-2 px-3" x-text="col"></th>
            </template>
        </tr>
    </thead>
    <tbody>
        <template x-for="row in data?.comparison_table?.rows || []" :key="row.metric">
            <tr class="border-b hover:bg-gray-50">
                <td class="py-2 px-3 font-medium" x-text="row.metric"></td>
                <template x-for="type in ['STANDARD', 'HYBRID', 'INTERACTIVE', 'DYNAMIC', 'POSTGRES']">
                    <td class="text-right py-2 px-3"
                        :class="{
                            'bg-green-100 font-semibold': row.winner === type,
                            'text-gray-400': row.values[type] === null
                        }">
                        <span x-text="formatMetricValue(row.metric, row.values[type])"></span>
                        <span x-show="row.winner === type" class="ml-1 text-green-600">✓</span>
                    </td>
                </template>
            </tr>
        </template>
    </tbody>
</table>
```

---

## 3. Template Analysis Page

### 3.1 Layout Structure

```html
<!-- dashboard_template_analysis.html -->
{% extends "base.html" %}
{% block title %}Template Analysis{% endblock %}

{% block content %}
<div x-data="templateAnalysis('{{ template_id }}')" x-init="init()">
    
    <!-- Header with Template Info -->
    <div class="flex justify-between items-start mb-6">
        <div>
            <h1 class="text-2xl font-bold" x-text="stats?.template_name || 'Loading...'"></h1>
            <div class="flex items-center gap-4 mt-2 text-sm text-gray-600">
                <span class="flex items-center gap-1">
                    <div class="w-2 h-2 rounded-full" :style="{ backgroundColor: getTableTypeColor(stats?.table_type) }"></div>
                    <span x-text="stats?.table_type"></span>
                </span>
                <span x-text="stats?.load_mode"></span>
                <span x-text="stats?.total_runs + ' runs'"></span>
            </div>
        </div>
        <div class="flex gap-2">
            <template x-for="badge in stats?.badges || []">
                <span class="px-2 py-1 rounded-full text-xs" 
                      :class="getBadgeClass(badge)"
                      x-text="formatBadge(badge)"></span>
            </template>
        </div>
    </div>

    <!-- Summary Cards Row -->
    <div class="grid grid-cols-4 gap-4 mb-6">
        <!-- Avg QPS Card -->
        <div class="card p-4">
            <div class="text-sm text-gray-600 mb-1">Avg QPS</div>
            <div class="text-2xl font-bold" x-text="formatNumber(stats?.qps_stats?.avg)"></div>
            <div class="text-xs text-gray-500">
                CV: <span x-text="formatPercent(stats?.stability?.cv_qps)"></span>
            </div>
        </div>
        
        <!-- Avg p95 Card -->
        <div class="card p-4">
            <div class="text-sm text-gray-600 mb-1">Avg p95</div>
            <div class="text-2xl font-bold" x-text="formatLatency(stats?.p95_stats?.avg)"></div>
            <div class="text-xs text-gray-500">
                Range: <span x-text="formatLatency(stats?.p95_stats?.min)"></span> - 
                <span x-text="formatLatency(stats?.p95_stats?.max)"></span>
            </div>
        </div>
        
        <!-- Avg Cost Card -->
        <div class="card p-4">
            <div class="text-sm text-gray-600 mb-1">Avg Cost/Run</div>
            <div class="text-2xl font-bold" x-text="formatCost(stats?.cost_stats?.avg_cost_per_run_usd)"></div>
            <div class="text-xs text-gray-500">
                <span x-text="formatCost(stats?.cost_stats?.cost_per_1k_ops_usd)"></span>/1K ops
            </div>
        </div>
        
        <!-- Stability Card -->
        <div class="card p-4">
            <div class="text-sm text-gray-600 mb-1">Stability</div>
            <div class="text-2xl font-bold" x-text="stats?.stability?.badge"></div>
            <div class="text-xs" :class="getTrendClass(stats?.stability?.trend_direction)">
                <span x-text="getTrendArrow(stats?.stability?.trend_direction)"></span>
                <span x-text="formatPercent(stats?.stability?.trend_pct)"></span> recent
            </div>
        </div>
    </div>

    <!-- Scatter Plots Section -->
    <div class="card mb-6">
        <div class="card-title flex justify-between items-center">
            <span>Scatter Analysis</span>
            <select x-model="selectedScatter" class="text-sm border rounded px-2 py-1">
                <option value="duration_vs_qps">Duration vs QPS</option>
                <option value="concurrency_vs_p95">Concurrency vs p95</option>
                <option value="qps_vs_cost">QPS vs Cost</option>
            </select>
        </div>
        <div class="grid grid-cols-2 gap-4">
            <div>
                <canvas id="scatterChart"></canvas>
            </div>
            <div class="p-4 bg-gray-50 rounded">
                <h4 class="font-medium mb-2">Correlation Analysis</h4>
                <div class="text-sm space-y-2">
                    <div>
                        <span class="text-gray-600">Correlation (r):</span>
                        <span class="font-medium" x-text="scatter?.correlation?.toFixed(3) || '—'"></span>
                    </div>
                    <div x-show="scatter?.trend_line">
                        <span class="text-gray-600">R²:</span>
                        <span class="font-medium" x-text="scatter?.trend_line?.r_squared?.toFixed(3)"></span>
                    </div>
                    <div class="text-gray-500 text-xs mt-2" x-text="getCorrelationInterpretation(scatter?.correlation)"></div>
                </div>
            </div>
        </div>
    </div>

    <!-- Distribution Section -->
    <div class="grid grid-cols-2 gap-4 mb-6">
        <!-- Latency Distribution -->
        <div class="card">
            <div class="card-title flex justify-between items-center">
                <span>Latency Distribution</span>
                <select x-model="selectedDistMetric" class="text-sm border rounded px-2 py-1">
                    <option value="p50_latency_ms">p50</option>
                    <option value="p95_latency_ms">p95</option>
                    <option value="p99_latency_ms">p99</option>
                </select>
            </div>
            <canvas id="histogramChart"></canvas>
            <div class="mt-2 text-sm text-gray-600 text-center">
                Distribution: <span class="font-medium" x-text="distribution?.distribution_type"></span>
                (μ=<span x-text="distribution?.mean?.toFixed(1)"></span>, 
                σ=<span x-text="distribution?.std_dev?.toFixed(1)"></span>)
            </div>
        </div>

        <!-- Box Plot -->
        <div class="card">
            <div class="card-title">Percentile Analysis</div>
            <canvas id="boxPlotChart"></canvas>
            <div class="mt-2 text-sm text-gray-500 text-center">
                Box shows p25-p75 range, whiskers show min-max
            </div>
        </div>
    </div>

    <!-- Statistical Health Section -->
    <div class="card mb-6">
        <div class="card-title">Statistical Health</div>
        <div class="grid grid-cols-3 gap-4">
            <div class="p-3 bg-gray-50 rounded">
                <div class="text-sm text-gray-600">Coefficient of Variation (QPS)</div>
                <div class="text-xl font-bold" x-text="formatPercent(stats?.stability?.cv_qps)"></div>
                <div class="text-xs" :class="getCVClass(stats?.stability?.cv_qps)">
                    <span x-text="getCVInterpretation(stats?.stability?.cv_qps)"></span>
                </div>
            </div>
            <div class="p-3 bg-gray-50 rounded">
                <div class="text-sm text-gray-600">KL Divergence (vs baseline)</div>
                <div class="text-xl font-bold" x-text="stats?.kl_divergence?.toFixed(3) || '—'"></div>
                <div class="text-xs text-gray-500">Lower is more consistent</div>
            </div>
            <div class="p-3 bg-gray-50 rounded">
                <div class="text-sm text-gray-600">Trend Direction</div>
                <div class="text-xl font-bold flex items-center gap-2">
                    <span x-text="getTrendArrow(stats?.stability?.trend_direction)"></span>
                    <span x-text="stats?.stability?.trend_direction"></span>
                </div>
                <div class="text-xs text-gray-500">
                    R² = <span x-text="trend?.qps_trend?.r_squared?.toFixed(2)"></span>
                </div>
            </div>
        </div>
        
        <!-- Outliers -->
        <div x-show="stats?.outliers?.length > 0" class="mt-4 p-3 bg-yellow-50 rounded border border-yellow-200">
            <div class="font-medium text-yellow-800 mb-2">
                ⚠️ Outliers Detected (<span x-text="stats?.outliers?.length"></span>)
            </div>
            <div class="space-y-1 text-sm">
                <template x-for="outlier in stats?.outliers || []">
                    <div class="flex justify-between">
                        <span>Test <span x-text="outlier.test_id.slice(0, 8)"></span></span>
                        <span class="text-gray-600" x-text="outlier.reason"></span>
                    </div>
                </template>
            </div>
        </div>
    </div>

    <!-- All Runs Table -->
    <div class="card">
        <div class="card-title flex justify-between items-center">
            <span>All Runs (<span x-text="runs?.total_count"></span>)</span>
            <button class="text-sm text-blue-600 hover:underline">Export CSV</button>
        </div>
        <table class="w-full text-sm">
            <thead>
                <tr class="border-b bg-gray-50">
                    <th class="text-left py-2 px-3">Date</th>
                    <th class="text-right py-2 px-3">QPS</th>
                    <th class="text-right py-2 px-3">p50</th>
                    <th class="text-right py-2 px-3">p95</th>
                    <th class="text-right py-2 px-3">p99</th>
                    <th class="text-right py-2 px-3">Errors</th>
                    <th class="text-right py-2 px-3">Cost</th>
                    <th class="text-center py-2 px-3">Status</th>
                </tr>
            </thead>
            <tbody>
                <template x-for="run in runs?.runs || []" :key="run.test_id">
                    <tr class="border-b hover:bg-gray-50" 
                        :class="{ 'bg-yellow-50': run.is_outlier }">
                        <td class="py-2 px-3">
                            <a :href="'/history/' + run.test_id" 
                               class="text-blue-600 hover:underline"
                               x-text="formatDate(run.start_time)"></a>
                        </td>
                        <td class="text-right py-2 px-3" x-text="formatNumber(run.qps)"></td>
                        <td class="text-right py-2 px-3" x-text="formatLatency(run.p50_ms)"></td>
                        <td class="text-right py-2 px-3" x-text="formatLatency(run.p95_ms)"></td>
                        <td class="text-right py-2 px-3" x-text="formatLatency(run.p99_ms)"></td>
                        <td class="text-right py-2 px-3" x-text="formatPercent(run.error_rate)"></td>
                        <td class="text-right py-2 px-3" x-text="formatCost(run.cost_per_1k_ops_usd)"></td>
                        <td class="text-center py-2 px-3">
                            <span x-show="run.is_outlier" 
                                  class="text-yellow-600" 
                                  :title="run.outlier_reason">⚠️</span>
                            <span x-show="!run.is_outlier" class="text-green-600">✓</span>
                        </td>
                    </tr>
                </template>
            </tbody>
        </table>
        
        <!-- Pagination -->
        <div class="flex justify-between items-center mt-4 text-sm">
            <span class="text-gray-600">
                Showing <span x-text="runs?.page * runs?.page_size + 1"></span> - 
                <span x-text="Math.min((runs?.page + 1) * runs?.page_size, runs?.total_count)"></span>
                of <span x-text="runs?.total_count"></span>
            </span>
            <div class="flex gap-2">
                <button @click="prevPage()" 
                        :disabled="runs?.page === 0"
                        class="px-3 py-1 border rounded disabled:opacity-50">
                    Previous
                </button>
                <button @click="nextPage()" 
                        :disabled="(runs?.page + 1) * runs?.page_size >= runs?.total_count"
                        class="px-3 py-1 border rounded disabled:opacity-50">
                    Next
                </button>
            </div>
        </div>
    </div>

</div>
{% endblock %}
```

---

## 4. JavaScript Functions

### 4.1 Table Types Dashboard

```javascript
// static/js/dashboard_table_types.js

function tableTypesDashboard() {
    return {
        data: null,
        loading: true,
        error: null,
        
        performanceChart: null,
        costChart: null,
        
        async init() {
            await this.fetchData();
            this.initCharts();
        },
        
        async fetchData() {
            try {
                this.loading = true;
                const response = await fetch('/api/dashboard/table-types/summary');
                this.data = await response.json();
            } catch (e) {
                this.error = e.message;
            } finally {
                this.loading = false;
            }
        },
        
        initCharts() {
            this.initPerformanceChart();
            this.initCostChart();
        },
        
        initPerformanceChart() {
            const ctx = document.getElementById('performanceChart');
            this.performanceChart = new Chart(ctx, {
                type: 'bar',
                data: this.buildPerformanceChartData(),
                options: {
                    responsive: true,
                    plugins: {
                        legend: { position: 'top' }
                    },
                    scales: {
                        y: { beginAtZero: true }
                    }
                }
            });
        },
        
        buildPerformanceChartData() {
            const colors = {
                'STANDARD': '#2563EB',
                'HYBRID': '#16A34A',
                'INTERACTIVE': '#9333EA',
                'DYNAMIC': '#EA580C',
                'POSTGRES': '#6B7280'
            };
            
            return {
                labels: ['QPS', 'p50 (ms)', 'p95 (ms)', 'p99 (ms)'],
                datasets: this.data.kpi_cards.map(kpi => ({
                    label: kpi.table_type,
                    data: [kpi.avg_qps, kpi.avg_p50_ms, kpi.avg_p95_ms, kpi.avg_p99_ms],
                    backgroundColor: colors[kpi.table_type]
                }))
            };
        },
        
        getTableTypeColor(type) {
            const colors = {
                'STANDARD': '#2563EB',
                'HYBRID': '#16A34A', 
                'INTERACTIVE': '#9333EA',
                'DYNAMIC': '#EA580C',
                'POSTGRES': '#6B7280'
            };
            return colors[type] || '#6B7280';
        },
        
        getStabilityBadgeClass(badge) {
            const classes = {
                'very_stable': 'bg-green-100 text-green-800',
                'stable': 'bg-blue-100 text-blue-800',
                'moderate': 'bg-yellow-100 text-yellow-800',
                'volatile': 'bg-red-100 text-red-800'
            };
            return classes[badge] || 'bg-gray-100 text-gray-800';
        },
        
        formatNumber(val) {
            if (val === null || val === undefined) return '—';
            return val.toLocaleString(undefined, { maximumFractionDigits: 1 });
        },
        
        formatLatency(val) {
            if (val === null || val === undefined) return '—';
            return val.toFixed(1) + ' ms';
        },
        
        formatCost(val) {
            if (val === null || val === undefined) return '—';
            return '$' + val.toFixed(4);
        },
        
        formatDate(val) {
            if (!val) return '—';
            return new Date(val).toLocaleString();
        }
    };
}
```

### 4.2 Template Analysis

```javascript
// static/js/dashboard_template_analysis.js

function templateAnalysis(templateId) {
    return {
        templateId: templateId,
        stats: null,
        distribution: null,
        scatter: null,
        trend: null,
        runs: null,
        
        selectedScatter: 'duration_vs_qps',
        selectedDistMetric: 'p95_latency_ms',
        page: 0,
        pageSize: 50,
        
        histogramChart: null,
        scatterChart: null,
        boxPlotChart: null,
        
        async init() {
            await Promise.all([
                this.fetchStats(),
                this.fetchDistribution(),
                this.fetchScatter(),
                this.fetchTrend(),
                this.fetchRuns()
            ]);
            this.initCharts();
        },
        
        async fetchStats() {
            const r = await fetch(`/api/dashboard/templates/${this.templateId}/statistics`);
            this.stats = await r.json();
        },
        
        async fetchDistribution() {
            const r = await fetch(`/api/dashboard/templates/${this.templateId}/distribution?metric=${this.selectedDistMetric}`);
            this.distribution = await r.json();
        },
        
        async fetchScatter() {
            const [x, y] = this.selectedScatter.split('_vs_');
            const r = await fetch(`/api/dashboard/templates/${this.templateId}/scatter?x_metric=${x}&y_metric=${y}`);
            this.scatter = await r.json();
        },
        
        async fetchRuns() {
            const r = await fetch(`/api/dashboard/templates/${this.templateId}/runs?limit=${this.pageSize}&offset=${this.page * this.pageSize}`);
            this.runs = await r.json();
        },
        
        initCharts() {
            this.initHistogramChart();
            this.initScatterChart();
            this.initBoxPlotChart();
        },
        
        initHistogramChart() {
            const ctx = document.getElementById('histogramChart');
            this.histogramChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: this.distribution.bins.slice(0, -1).map((b, i) => 
                        `${b.toFixed(0)}-${this.distribution.bins[i+1].toFixed(0)}`
                    ),
                    datasets: [{
                        label: 'Count',
                        data: this.distribution.counts,
                        backgroundColor: 'rgba(22, 163, 74, 0.6)',
                        borderColor: '#16A34A',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: { title: { display: true, text: this.selectedDistMetric } },
                        y: { title: { display: true, text: 'Count' } }
                    }
                }
            });
        },
        
        initScatterChart() {
            const ctx = document.getElementById('scatterChart');
            this.scatterChart = new Chart(ctx, {
                type: 'scatter',
                data: {
                    datasets: [{
                        label: 'Runs',
                        data: this.scatter.data.map(d => ({ x: d.x, y: d.y })),
                        backgroundColor: 'rgba(37, 99, 235, 0.6)'
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        x: { title: { display: true, text: this.scatter.x_label } },
                        y: { title: { display: true, text: this.scatter.y_label } }
                    },
                    plugins: {
                        tooltip: {
                            callbacks: {
                                label: (ctx) => `(${ctx.raw.x.toFixed(1)}, ${ctx.raw.y.toFixed(1)})`
                            }
                        }
                    }
                }
            });
        },
        
        getCorrelationInterpretation(r) {
            if (r === null) return 'Insufficient data';
            const abs = Math.abs(r);
            if (abs < 0.3) return 'Weak or no correlation';
            if (abs < 0.7) return 'Moderate correlation';
            return 'Strong correlation';
        },
        
        getCVInterpretation(cv) {
            if (cv === null) return 'Unknown';
            if (cv < 0.10) return 'Very stable (< 10%)';
            if (cv < 0.15) return 'Stable (10-15%)';
            if (cv < 0.25) return 'Moderate variability (15-25%)';
            return 'High variability (> 25%)';
        },
        
        getTrendArrow(direction) {
            const arrows = {
                'improving': '↑',
                'degrading': '↓',
                'stable': '→'
            };
            return arrows[direction] || '—';
        },
        
        nextPage() {
            this.page++;
            this.fetchRuns();
        },
        
        prevPage() {
            if (this.page > 0) {
                this.page--;
                this.fetchRuns();
            }
        }
    };
}
```

---

## 5. Color Palette

Consistent colors across all dashboard visualizations:

```javascript
const TABLE_TYPE_COLORS = {
    'STANDARD': '#2563EB',      // Blue
    'HYBRID': '#16A34A',        // Green
    'INTERACTIVE': '#9333EA',   // Purple
    'DYNAMIC': '#EA580C',       // Orange
    'POSTGRES': '#6B7280'       // Gray
};

const BADGE_COLORS = {
    'winner': 'bg-green-100 text-green-800 border-green-200',
    'stable': 'bg-blue-100 text-blue-800 border-blue-200',
    'volatile': 'bg-red-100 text-red-800 border-red-200',
    'improving': 'bg-green-100 text-green-800',
    'degrading': 'bg-red-100 text-red-800'
};
```

---

**Next:** [05-implementation.md](05-implementation.md) - Implementation phases
