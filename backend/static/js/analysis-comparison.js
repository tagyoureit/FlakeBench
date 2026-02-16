/**
 * Table Type Comparison Dashboard - Alpine.js component
 */
let _tableTypeComparisonInstance = null;

function tableTypeComparison() {
    return {
        loading: false,
        error: null,
        lastRefresh: null,
        kpiCards: [],
        comparisonTable: { columns: [], rows: [] },
        totals: null,
        qpsChart: null,
        latencyChart: null,
        qpsChartType: 'bar',
        latencyChartType: 'bar',
        scatterData: { qps: null, latency: null },
        _cleanupHandler: null,
        _destroyed: false,
        _renderingCharts: false,

        async init() {
            // Prevent double initialization (HTMX + Alpine MutationObserver can both trigger)
            if (_tableTypeComparisonInstance && !_tableTypeComparisonInstance._destroyed) {
                return;
            }
            _tableTypeComparisonInstance = this;
            // Register cleanup handler for HTMX navigation
            this._cleanupHandler = () => this.cleanup();
            document.body.addEventListener('htmx:beforeSwap', this._cleanupHandler);
            
            await this.loadData();
        },

        cleanup() {
            // Mark as destroyed to prevent any pending operations
            this._destroyed = true;
            // Clear global instance reference
            if (_tableTypeComparisonInstance === this) {
                _tableTypeComparisonInstance = null;
            }
            // Destroy charts to prevent errors during HTMX navigation
            if (this.qpsChart) {
                this.qpsChart.destroy();
                this.qpsChart = null;
            }
            if (this.latencyChart) {
                this.latencyChart.destroy();
                this.latencyChart = null;
            }
            // Remove event listener
            if (this._cleanupHandler) {
                document.body.removeEventListener('htmx:beforeSwap', this._cleanupHandler);
            }
        },

        async loadData() {
            this.loading = true;
            this.error = null;
            
            try {
                // Fetch summary data
                const summaryRes = await fetch('/api/dashboard/table-types/summary');
                if (!summaryRes.ok) throw new Error(`Failed to load summary: ${summaryRes.statusText}`);
                const summary = await summaryRes.json();
                
                this.kpiCards = summary.kpi_cards || [];
                this.comparisonTable = summary.comparison_table || { columns: [], rows: [] };
                this.totals = summary.totals;
                this.lastRefresh = new Date(summary.generated_at).toLocaleTimeString();
                
                // Render charts after data is loaded - use setTimeout to ensure DOM is ready
                this.$nextTick(() => {
                    setTimeout(() => this.renderCharts(), 50);
                });
                
            } catch (err) {
                this.error = err.message;
                console.error('Dashboard load error:', err);
            } finally {
                this.loading = false;
            }
        },

        async refresh() {
            await this.loadData();
        },

        async toggleQpsChartType() {
            this.qpsChartType = this.qpsChartType === 'bar' ? 'scatter' : 'bar';
            await this.renderQpsChart();
        },

        async toggleLatencyChartType() {
            this.latencyChartType = this.latencyChartType === 'bar' ? 'scatter' : 'bar';
            await this.renderLatencyChart();
        },

        async fetchScatterData(metric) {
            if (this.scatterData[metric]) return this.scatterData[metric];
            
            try {
                const res = await fetch(`/api/dashboard/table-types/scatter/${metric === 'qps' ? 'qps' : 'p95_latency'}`);
                if (!res.ok) throw new Error(`Failed to fetch scatter data: ${res.statusText}`);
                const data = await res.json();
                this.scatterData[metric] = data;
                return data;
            } catch (err) {
                console.error('Scatter data fetch error:', err);
                return null;
            }
        },

        renderCharts() {
            // Guard against rendering after cleanup
            if (this._destroyed) return;
            if (!this.kpiCards.length) return;
            // Prevent re-entrant calls
            if (this._renderingCharts) return;
            this._renderingCharts = true;
            
            try {
                // Check if canvas elements exist yet (DOM may not be ready)
                const qpsCtx = document.getElementById('qps-chart');
                const latencyCtx = document.getElementById('latency-chart');
                
                if (!qpsCtx || !latencyCtx) {
                    // DOM not ready yet, retry after a short delay (unless destroyed)
                    if (!this._destroyed) {
                        this._renderingCharts = false;
                        setTimeout(() => this.renderCharts(), 100);
                    }
                    return;
                }
            
                this.renderQpsChart();
                this.renderLatencyChart();
            } finally {
                this._renderingCharts = false;
            }
        },

        async renderQpsChart() {
            if (this._destroyed) return;
            const qpsCtx = document.getElementById('qps-chart');
            if (!qpsCtx || !qpsCtx.getContext) return;

            if (this.qpsChart) {
                this.qpsChart.destroy();
                this.qpsChart = null;
            }

            if (this.qpsChartType === 'bar') {
                const labels = this.kpiCards.map(k => k.table_type);
                const qpsData = this.kpiCards.map(k => k.avg_qps || 0);
                const colors = this.kpiCards.map(k => this.getChartColor(k.table_type));
                
                this.qpsChart = new Chart(qpsCtx, {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Average QPS',
                            data: qpsData,
                            backgroundColor: colors.map(c => c.bg),
                            borderColor: colors.map(c => c.border),
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false }
                        },
                        scales: {
                            y: { beginAtZero: true, title: { display: true, text: 'QPS' } }
                        }
                    }
                });
            } else {
                const scatterData = await this.fetchScatterData('qps');
                if (!scatterData) return;
                
                this.qpsChart = this.createScatterChart(qpsCtx, scatterData, 'QPS');
            }
        },

        async renderLatencyChart() {
            if (this._destroyed) return;
            const latencyCtx = document.getElementById('latency-chart');
            if (!latencyCtx || !latencyCtx.getContext) return;

            if (this.latencyChart) {
                this.latencyChart.destroy();
                this.latencyChart = null;
            }

            if (this.latencyChartType === 'bar') {
                const labels = this.kpiCards.map(k => k.table_type);
                const latencyData = this.kpiCards.map(k => k.avg_p95_ms || 0);
                const colors = this.kpiCards.map(k => this.getChartColor(k.table_type));
                
                this.latencyChart = new Chart(latencyCtx, {
                    type: 'bar',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'P95 Latency (ms)',
                            data: latencyData,
                            backgroundColor: colors.map(c => c.bg),
                            borderColor: colors.map(c => c.border),
                            borderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false }
                        },
                        scales: {
                            y: { beginAtZero: true, title: { display: true, text: 'Latency (ms)' } }
                        }
                    }
                });
            } else {
                const scatterData = await this.fetchScatterData('latency');
                if (!scatterData) return;
                
                this.latencyChart = this.createScatterChart(latencyCtx, scatterData, 'Latency (ms)');
            }
        },

        createScatterChart(ctx, data, yAxisLabel) {
            const tableTypes = data.table_types || [];
            const datasets = (data.datasets || []).map((ds, idx) => {
                const category = String(ds.label || '');
                const categoryIndex = tableTypes.indexOf(category);
                const baseX = categoryIndex >= 0 ? categoryIndex : idx;
                return {
                    label: ds.label,
                    data: ds.data.map((pt, ptIdx) => {
                        const jitter = (Math.random() - 0.5) * 0.5;
                        return {
                            x: baseX + jitter,
                            y: pt.y,
                            category,
                            test_id: pt.test_id,
                            start_time: pt.start_time,
                            _ptIdx: ptIdx,
                        };
                    }),
                    backgroundColor: ds.backgroundColor,
                    borderColor: ds.borderColor,
                    pointRadius: 5,
                    pointHoverRadius: 7,
                };
            });

            return new Chart(ctx, {
                type: 'scatter',
                data: {
                    labels: tableTypes,
                    datasets: datasets
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (context) => {
                                    const pt = context.raw;
                                    const categoryLabel = pt.category || context.dataset.label || 'UNKNOWN';
                                    return `${categoryLabel}: ${pt.y.toLocaleString(undefined, {maximumFractionDigits: 1})}`;
                                }
                            }
                        }
                    },
                    scales: {
                        x: {
                            type: 'linear',
                            min: -0.5,
                            max: Math.max(tableTypes.length - 0.5, 0.5),
                            afterBuildTicks: (axis) => {
                                axis.ticks = tableTypes.map((_, index) => ({ value: index }));
                            },
                            ticks: {
                                autoSkip: false,
                                callback: (value) => {
                                    const index = Math.round(Number(value));
                                    if (!Number.isInteger(index) || index < 0 || index >= tableTypes.length) {
                                        return '';
                                    }
                                    return tableTypes[index];
                                }
                            }
                        },
                        y: { 
                            beginAtZero: true, 
                            title: { display: true, text: yAxisLabel }
                        }
                    }
                }
            });
        },

        getChartColor(tableType) {
            const colors = {
                'STANDARD': { bg: 'rgba(59, 130, 246, 0.7)', border: 'rgb(59, 130, 246)' },
                'HYBRID': { bg: 'rgba(16, 185, 129, 0.7)', border: 'rgb(16, 185, 129)' },
                'INTERACTIVE': { bg: 'rgba(249, 115, 22, 0.7)', border: 'rgb(249, 115, 22)' },
                'DYNAMIC': { bg: 'rgba(139, 92, 246, 0.7)', border: 'rgb(139, 92, 246)' },
                'POSTGRES': { bg: 'rgba(236, 72, 153, 0.7)', border: 'rgb(236, 72, 153)' },
            };
            return colors[tableType] || { bg: 'rgba(107, 114, 128, 0.7)', border: 'rgb(107, 114, 128)' };
        },

        getCardClass(kpi) {
            if (kpi.badges?.includes('highest_qps') || kpi.badges?.includes('lowest_latency')) {
                return 'border-green-300 bg-green-50';
            }
            if (kpi.badges?.includes('most_cost_efficient')) {
                return 'border-orange-300 bg-orange-50';
            }
            return '';
        },

        getBadgeStyle(badge) {
            const styles = {
                'highest_qps': 'background-color:#d1fae5;color:#047857',
                'lowest_latency': 'background-color:#e0f2fe;color:#0369a1',
                'lowest_p95': 'background-color:#e0f2fe;color:#0369a1',
                'lowest_cost': 'background-color:#ccfbf1;color:#0f766e',
                'most_tests': 'background-color:#e0e7ff;color:#4338ca',
                'most_consistent': 'background-color:#ede9fe;color:#6d28d9',
                'most_cost_efficient': 'background-color:#ccfbf1;color:#0f766e',
                'most_reliable': 'background-color:#d1fae5;color:#047857',
                'zero_errors': 'background-color:#d1fae5;color:#047857',
                'high_confidence': 'background-color:#f1f5f9;color:#334155',
                'low_sample': 'background-color:#fef3c7;color:#b45309',
                'highest_errors': 'background-color:#ffe4e6;color:#be123c',
            };
            return styles[badge] || 'background-color:#f3f4f6;color:#374151';
        },

        getBadgeClass(badge) {
            return '';
        },

        getBadgeLabel(badge) {
            const labels = {
                'highest_qps': 'Highest QPS',
                'lowest_latency': 'Lowest Latency',
                'lowest_p95': 'Lowest P95',
                'lowest_cost': 'Lowest Cost',
                'most_tests': 'Most Tests',
                'most_consistent': 'Most Consistent',
                'most_cost_efficient': 'Cost Efficient',
                'most_reliable': 'Most Reliable',
                'zero_errors': 'Zero Errors',
                'high_confidence': 'High Confidence',
                'low_sample': 'Low Sample',
                'highest_errors': 'High Errors',
            };
            return labels[badge] || badge;
        },

        getBadgeIcon(badge) {
            const icons = {
                'highest_qps': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6"/></svg>',
                'lowest_latency': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
                'lowest_p95': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
                'lowest_cost': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
                'most_tests': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/></svg>',
                'most_reliable': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/></svg>',
                'most_consistent': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16"/></svg>',
                'most_cost_efficient': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
                'high_confidence': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
                'zero_errors': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
                'low_sample': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>',
                'highest_errors': '<svg style="width:0.75rem;height:0.75rem;flex-shrink:0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"/></svg>',
            };
            return icons[badge] || '';
        },

        formatNumber(val, decimals = 0) {
            if (val === null || val === undefined) return 'N/A';
            return Number(val).toLocaleString(undefined, { 
                minimumFractionDigits: decimals, 
                maximumFractionDigits: decimals 
            });
        },

        formatLatency(val) {
            if (val === null || val === undefined) return 'N/A';
            if (val < 1) return val.toFixed(2) + ' ms';
            if (val < 1000) return val.toFixed(1) + ' ms';
            return (val / 1000).toFixed(2) + ' s';
        },

        formatPercent(val) {
            if (val === null || val === undefined) return 'N/A';
            return (val * 100).toFixed(2) + '%';
        },

        formatCellValue(val, formatType) {
            if (val === null || val === undefined) return 'N/A';
            switch (formatType) {
                case 'latency':
                    return this.formatLatency(val);
                case 'percent':
                    return this.formatPercent(val);
                case 'cost':
                    return '$' + this.formatNumber(val, 4);
                default:
                    return this.formatNumber(val, 1);
            }
        },

        getTableTypeIcon(tableType) {
            const t = String(tableType || '').trim().toUpperCase();
            if (t === 'POSTGRES') return '/static/img/postgres_elephant.svg';
            if (t === 'HYBRID') return '/static/img/table_hybrid.svg';
            if (t === 'STANDARD') return '/static/img/table_standard.svg';
            if (t === 'INTERACTIVE') return '/static/img/table_interactive.svg';
            if (t === 'VIEW') return '/static/img/table_view.svg';
            return '';
        }
    };
}
