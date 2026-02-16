/**
 * Template Analysis Dashboard - Alpine.js component
 */
let _templateAnalysisInstance = null;

function templateAnalysis() {
    return {
        // List view state
        templates: [],
        totalCount: 0,
        loadingList: false,
        filters: {
            tableType: '',
            sortBy: 'last_run'
        },
        listPage: 0,
        listPageSize: 50,
        
        // Detail view state
        selectedTemplate: null,
        templateStats: null,
        loadingDetail: false,
        
        // Distribution chart
        distributionMetric: 'p95_latency_ms',
        distributionChart: null,
        
        // Scatter plot
        scatterX: 'duration_seconds',
        scatterY: 'qps',
        scatterChart: null,
        scatterCorrelation: null,
        
        // Runs table
        runs: [],
        runsTotal: 0,
        runsPage: 1,
        runsPageSize: 20,
        runsSortBy: 'start_time',
        runsSortOrder: 'desc',
        
        // Cleanup handler
        _cleanupHandler: null,

        async init() {
            // Prevent double initialization (HTMX + Alpine MutationObserver can both trigger)
            if (_templateAnalysisInstance && !_templateAnalysisInstance._destroyed) {
                return;
            }
            _templateAnalysisInstance = this;
            
            // Register cleanup handler for HTMX navigation
            this._cleanupHandler = () => this.cleanup();
            document.body.addEventListener('htmx:beforeSwap', this._cleanupHandler);
            
            // Check for template_id in URL
            const params = new URLSearchParams(window.location.search);
            const templateId = params.get('template_id');
            if (templateId) {
                await this.selectTemplate(templateId);
            } else {
                await this.loadTemplates();
            }
        },
        
        cleanup() {
            // Mark as destroyed
            this._destroyed = true;
            // Clear global instance reference
            if (_templateAnalysisInstance === this) {
                _templateAnalysisInstance = null;
            }
            // Destroy charts to prevent errors during HTMX navigation
            if (this.distributionChart) {
                this.distributionChart.destroy();
                this.distributionChart = null;
            }
            if (this.scatterChart) {
                this.scatterChart.destroy();
                this.scatterChart = null;
            }
            // Remove event listener
            if (this._cleanupHandler) {
                document.body.removeEventListener('htmx:beforeSwap', this._cleanupHandler);
            }
        },

        async loadTemplates() {
            this.loadingList = true;
            try {
                const params = new URLSearchParams({
                    sort_by: this.filters.sortBy,
                    limit: this.listPageSize,
                    offset: this.listPage * this.listPageSize
                });
                if (this.filters.tableType) {
                    params.set('table_type', this.filters.tableType);
                }
                
                const res = await fetch(`/api/dashboard/templates?${params}`);
                if (!res.ok) throw new Error(res.statusText);
                const data = await res.json();
                
                if (this.listPage === 0) {
                    this.templates = data.templates;
                } else {
                    this.templates = [...this.templates, ...data.templates];
                }
                this.totalCount = data.total_count;
            } catch (err) {
                console.error('Failed to load templates:', err);
            } finally {
                this.loadingList = false;
            }
        },

        async loadMore() {
            this.listPage++;
            await this.loadTemplates();
        },

        async selectTemplate(templateId) {
            this.selectedTemplate = templateId;
            this.loadingDetail = true;
            
            try {
                // Load stats
                const statsRes = await fetch(`/api/dashboard/templates/${templateId}`);
                if (!statsRes.ok) throw new Error(statsRes.statusText);
                this.templateStats = await statsRes.json();
                
                // Load runs
                await this.loadRuns();
                
                // Load charts after DOM update
                this.$nextTick(() => {
                    this.loadDistribution();
                    this.loadScatter();
                });
                
            } catch (err) {
                console.error('Failed to load template details:', err);
            } finally {
                this.loadingDetail = false;
            }
        },

        clearSelection() {
            this.selectedTemplate = null;
            this.templateStats = null;
            this.runs = [];
            if (this.distributionChart) {
                this.distributionChart.destroy();
                this.distributionChart = null;
            }
            if (this.scatterChart) {
                this.scatterChart.destroy();
                this.scatterChart = null;
            }
            // Update URL
            history.pushState({}, '', '/analysis/templates');
        },

        async loadRuns() {
            const params = new URLSearchParams({
                limit: this.runsPageSize,
                offset: (this.runsPage - 1) * this.runsPageSize,
                sort_by: this.runsSortBy,
                sort_order: this.runsSortOrder
            });
            
            const res = await fetch(`/api/dashboard/templates/${this.selectedTemplate}/runs?${params}`);
            if (!res.ok) throw new Error(res.statusText);
            const data = await res.json();
            
            this.runs = data.runs;
            this.runsTotal = data.total_count;
        },

        sortRuns(field) {
            if (this.runsSortBy === field) {
                this.runsSortOrder = this.runsSortOrder === 'desc' ? 'asc' : 'desc';
            } else {
                this.runsSortBy = field;
                this.runsSortOrder = 'desc';
            }
            this.runsPage = 1;
            this.loadRuns();
        },

        prevRunsPage() {
            if (this.runsPage > 1) {
                this.runsPage--;
                this.loadRuns();
            }
        },

        nextRunsPage() {
            if (this.runsPage < Math.ceil(this.runsTotal / this.runsPageSize)) {
                this.runsPage++;
                this.loadRuns();
            }
        },

        async loadDistribution() {
            if (!this.selectedTemplate) return;
            
            try {
                const res = await fetch(`/api/dashboard/templates/${this.selectedTemplate}/distribution?metric=${this.distributionMetric}`);
                if (!res.ok) throw new Error(res.statusText);
                const data = await res.json();
                
                this.renderDistributionChart(data);
            } catch (err) {
                console.error('Failed to load distribution:', err);
            }
        },

        renderDistributionChart(data) {
            const ctx = document.getElementById('distribution-chart');
            if (!ctx) return;
            
            if (this.distributionChart) {
                this.distributionChart.destroy();
            }
            
            // Create bin labels
            const labels = [];
            for (let i = 0; i < data.counts.length; i++) {
                if (i < data.bins.length - 1) {
                    labels.push(`${data.bins[i].toFixed(0)}-${data.bins[i+1].toFixed(0)}`);
                }
            }
            
            this.distributionChart = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Count',
                        data: data.counts,
                        backgroundColor: 'rgba(59, 130, 246, 0.7)',
                        borderColor: 'rgb(59, 130, 246)',
                        borderWidth: 1
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        y: { beginAtZero: true, title: { display: true, text: 'Count' } }
                    }
                }
            });
        },

        async loadScatter() {
            if (!this.selectedTemplate) return;
            
            try {
                const res = await fetch(`/api/dashboard/templates/${this.selectedTemplate}/scatter?x_metric=${this.scatterX}&y_metric=${this.scatterY}`);
                if (!res.ok) throw new Error(res.statusText);
                const data = await res.json();
                
                this.scatterCorrelation = data.correlation;
                this.renderScatterChart(data);
            } catch (err) {
                console.error('Failed to load scatter:', err);
            }
        },

        renderScatterChart(data) {
            const ctx = document.getElementById('scatter-chart');
            if (!ctx) return;
            
            if (this.scatterChart) {
                this.scatterChart.destroy();
            }
            
            const points = data.data.map(p => ({ x: p.x, y: p.y }));
            
            this.scatterChart = new Chart(ctx, {
                type: 'scatter',
                data: {
                    datasets: [{
                        label: `${data.y_label} vs ${data.x_label}`,
                        data: points,
                        backgroundColor: 'rgba(59, 130, 246, 0.7)',
                        borderColor: 'rgb(59, 130, 246)',
                        pointRadius: 6,
                        pointHoverRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: { display: false }
                    },
                    scales: {
                        x: { title: { display: true, text: data.x_label } },
                        y: { title: { display: true, text: data.y_label } }
                    }
                }
            });
        },

        // Formatting helpers
        formatNumber(val, decimals = 0) {
            if (val === null || val === undefined) return 'N/A';
            return Number(val).toLocaleString(undefined, { 
                minimumFractionDigits: decimals, 
                maximumFractionDigits: decimals 
            });
        },

        formatLatency(val) {
            if (val === null || val === undefined) return 'N/A';
            if (val < 1) return val.toFixed(2) + 'ms';
            if (val < 1000) return val.toFixed(1) + 'ms';
            return (val / 1000).toFixed(2) + 's';
        },

        formatPercent(val) {
            if (val === null || val === undefined) return 'N/A';
            return (val * 100).toFixed(2) + '%';
        },

        formatDate(val) {
            if (!val) return 'N/A';
            return new Date(val).toLocaleDateString();
        },

        formatDateTime(val) {
            if (!val) return 'N/A';
            return new Date(val).toLocaleString();
        },

        formatDuration(seconds) {
            if (!seconds) return '-';
            if (seconds < 60) return seconds.toFixed(0) + 's';
            if (seconds < 3600) return (seconds / 60).toFixed(1) + 'm';
            return (seconds / 3600).toFixed(1) + 'h';
        },

        getStabilityClass(badge) {
            const classes = {
                'very_stable': 'bg-emerald-100 text-emerald-700',
                'stable': 'bg-blue-100 text-blue-700',
                'moderate': 'bg-amber-100 text-amber-700',
                'volatile': 'bg-red-100 text-red-700',
            };
            return classes[badge] || 'bg-gray-100 text-gray-600';
        },

        getStabilityTextClass(badge) {
            const classes = {
                'very_stable': 'text-emerald-600',
                'stable': 'text-blue-600',
                'moderate': 'text-amber-600',
                'volatile': 'text-red-600',
            };
            return classes[badge] || 'text-gray-600';
        },

        getStabilityLabel(badge) {
            const labels = {
                'very_stable': 'Very Stable',
                'stable': 'Stable',
                'moderate': 'Moderate',
                'volatile': 'Volatile',
                'unknown': 'Unknown'
            };
            return labels[badge] || badge || 'Unknown';
        },

        getBadgeClass(badge) {
            const classes = {
                'highest_qps': 'bg-emerald-100 text-emerald-700',
                'lowest_latency': 'bg-sky-100 text-sky-700',
                'improving': 'bg-teal-100 text-teal-700',
                'degrading': 'bg-rose-100 text-rose-700',
                'high_confidence': 'bg-slate-100 text-slate-700',
                'low_sample': 'bg-amber-100 text-amber-700',
                'zero_errors': 'bg-emerald-100 text-emerald-700',
            };
            return classes[badge] || 'bg-gray-100 text-gray-600';
        },

        getBadgeLabel(badge) {
            const labels = {
                'highest_qps': 'Highest QPS',
                'lowest_latency': 'Lowest Latency',
                'improving': 'Improving',
                'degrading': 'Degrading',
                'high_confidence': 'High Confidence',
                'low_sample': 'Low Sample',
                'zero_errors': 'Zero Errors',
            };
            return labels[badge] || badge;
        }
    };
}
