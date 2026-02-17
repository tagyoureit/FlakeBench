/**
 * Template Analysis Dashboard - Alpine.js component
 * Simplified: List view only - detail view now on configure page
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
            
            await this.loadTemplates();
        },
        
        cleanup() {
            // Mark as destroyed
            this._destroyed = true;
            // Clear global instance reference
            if (_templateAnalysisInstance === this) {
                _templateAnalysisInstance = null;
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

        formatDate(val) {
            if (!val) return 'N/A';
            return new Date(val).toLocaleDateString();
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

        getStabilityLabel(badge) {
            const labels = {
                'very_stable': 'Very Stable',
                'stable': 'Stable',
                'moderate': 'Moderate',
                'volatile': 'Volatile',
                'unknown': 'Unknown'
            };
            return labels[badge] || badge || 'Unknown';
        }
    };
}
