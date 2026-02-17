function createSettingsPage() {
    return {
        loading: true,
        error: null,
        connections: [],
        
        costSettings: {
            dollarsPerCredit: 4.0,
            showCredits: true,
            currency: 'USD',
            hoursPerDayWarehouse: 8,
            cloudProvider: 'AWS'
        },
        
        showModal: false,
        editingConnection: null,
        saving: false,
        formData: {
            connection_name: '',
            connection_type: '',
            host: '',
            port: null,
            pgbouncer_port: null,
            account: '',
            role: '',
            username: '',
            password: ''
        },
        
        showTestModal: false,
        testingConnection: null,
        testing: false,
        testResult: null,
        
        showDeleteModal: false,
        deletingConnection: null,
        deleting: false,
        
        async init() {
            this.loadCostSettings();
            await this.loadConnections();
        },
        
        async loadConnections() {
            this.loading = true;
            this.error = null;
            try {
                const response = await fetch('/api/connections/');
                if (!response.ok) {
                    throw new Error(await response.text());
                }
                const data = await response.json();
                this.connections = data.connections || [];
            } catch (e) {
                this.error = `Failed to load connections: ${e.message}`;
                console.error('Load connections error:', e);
            } finally {
                this.loading = false;
            }
        },
        
        formatConnectionType(type) {
            const labels = {
                'SNOWFLAKE': 'Snowflake',
                'POSTGRES': 'PostgreSQL'
            };
            return labels[type] || type;
        },
        
        openAddModal() {
            this.editingConnection = null;
            this.formData = {
                connection_name: '',
                connection_type: '',
                host: '',
                port: null,
                account: '',
                role: '',
                username: '',
                password: ''
            };
            this.showModal = true;
            this.checkSecurityWarnings();
        },
        
        async checkSecurityWarnings() {
            const WARNED_KEY = 'flakebench_encryption_warned';
            if (sessionStorage.getItem(WARNED_KEY)) return;
            
            try {
                const res = await fetch('/api/info');
                const data = await res.json();
                const warnings = data.security_warnings || [];
                const encryptionWarning = warnings.find(w => w.code === 'DEFAULT_ENCRYPTION_KEY');
                if (encryptionWarning) {
                    window.toast?.warning(encryptionWarning.message);
                    sessionStorage.setItem(WARNED_KEY, '1');
                }
            } catch (e) {
            }
        },
        
        openEditModal(conn) {
            this.editingConnection = conn;
            this.formData = {
                connection_name: conn.connection_name,
                connection_type: conn.connection_type,
                host: conn.host || '',
                port: conn.port,
                pgbouncer_port: conn.pgbouncer_port,
                account: conn.account || '',
                role: conn.role || '',
                username: '',
                password: ''
            };
            this.showModal = true;
        },
        
        closeModal() {
            this.showModal = false;
            this.editingConnection = null;
        },
        
        onTypeChange() {
            if (this.formData.connection_type === 'SNOWFLAKE') {
                this.formData.host = '';
                this.formData.port = null;
                this.formData.pgbouncer_port = null;
            } else {
                this.formData.account = '';
                this.formData.role = '';
                if (!this.formData.port) {
                    this.formData.port = 5432;
                }
            }
        },
        
        async saveConnection() {
            this.saving = true;
            try {
                const url = this.editingConnection 
                    ? `/api/connections/${this.editingConnection.connection_id}`
                    : '/api/connections/';
                const method = this.editingConnection ? 'PUT' : 'POST';
                
                const payload = {
                    connection_name: this.formData.connection_name,
                    connection_type: this.formData.connection_type,
                    host: this.formData.host || null,
                    port: this.formData.port || null,
                    pgbouncer_port: this.formData.pgbouncer_port || null,
                    account: this.formData.account || null,
                    role: this.formData.role || null
                };
                
                if (this.formData.username) {
                    payload.username = this.formData.username;
                }
                if (this.formData.password) {
                    payload.password = this.formData.password;
                }
                
                const response = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                
                if (!response.ok) {
                    const error = await response.json();
                    const detail = error.detail;
                    const message = typeof detail === 'string' 
                        ? detail 
                        : (detail?.message || JSON.stringify(detail) || 'Failed to save connection');
                    throw new Error(message);
                }
                
                window.toast.success(this.editingConnection ? 'Connection updated' : 'Connection created');
                this.closeModal();
                await this.loadConnections();
            } catch (e) {
                window.toast.error(e.message);
            } finally {
                this.saving = false;
            }
        },
        
        openTestModal(conn) {
            this.testingConnection = conn;
            this.testResult = null;
            this.showTestModal = true;
        },
        
        closeTestModal() {
            this.showTestModal = false;
            this.testingConnection = null;
            this.testResult = null;
        },
        
        async runTest() {
            if (!this.testingConnection) return;
            
            this.testing = true;
            this.testResult = null;
            
            try {
                const response = await fetch(`/api/connections/${this.testingConnection.connection_id}/test`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({})
                });
                
                this.testResult = await response.json();
                
                if (this.testResult.success) {
                    window.toast.success('Connection successful');
                }
            } catch (e) {
                this.testResult = {
                    success: false,
                    message: `Test failed: ${e.message}`
                };
            } finally {
                this.testing = false;
            }
        },
        
        confirmDelete(conn) {
            this.deletingConnection = conn;
            this.showDeleteModal = true;
        },
        
        async deleteConnection() {
            if (!this.deletingConnection) return;
            
            this.deleting = true;
            try {
                const response = await fetch(`/api/connections/${this.deletingConnection.connection_id}`, {
                    method: 'DELETE'
                });
                
                if (!response.ok && response.status !== 204) {
                    throw new Error('Failed to delete connection');
                }
                
                window.toast.success('Connection deleted');
                this.showDeleteModal = false;
                this.deletingConnection = null;
                await this.loadConnections();
            } catch (e) {
                window.toast.error(e.message);
            } finally {
                this.deleting = false;
            }
        },
        
        async setDefault(conn) {
            try {
                const response = await fetch(`/api/connections/${conn.connection_id}/set-default`, {
                    method: 'POST'
                });
                
                if (!response.ok) {
                    throw new Error('Failed to set default');
                }
                
                window.toast.success(`${conn.connection_name} set as default`);
                await this.loadConnections();
            } catch (e) {
                window.toast.error(e.message);
            }
        },
        
        loadCostSettings() {
            if (window.CostUtils) {
                this.costSettings = window.CostUtils.getCostSettings();
            }
        },
        
        saveCostSettings() {
            if (window.CostUtils) {
                window.CostUtils.saveCostSettings(this.costSettings);
                window.toast.success('Cost settings saved');
            }
        }
    };
}

function registerSettingsPageWithAlpine() {
    if (!window.Alpine || typeof window.Alpine.data !== 'function') {
        return false;
    }
    window.Alpine.data('settingsPage', createSettingsPage);
    return true;
}

if (typeof window !== 'undefined') {
    window.flakebench = window.flakebench || {};
    window.flakebench.settingsPage = createSettingsPage;
    // Backward-compat global alias for existing template usage.
    window.settingsPage = createSettingsPage;

    if (!registerSettingsPageWithAlpine()) {
        document.addEventListener('alpine:init', registerSettingsPageWithAlpine, { once: true });
    }
}
