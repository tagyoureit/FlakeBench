function templatesManager() {
  // Use shared DisplayUtils (loaded from display-utils.js)
  const DU = window.DisplayUtils || {};

  return {
    templates: [],
    filteredTemplates: [],
    searchQuery: "",
    typeFilter: "",
    loading: true,
    error: null,
    preparingTemplateId: null,
    // Loading states for individual buttons
    editingTemplateId: null,
    viewingTemplateId: null,
    deletingTemplateId: null,
    copyingTemplateId: null,

    // Check if any action is in progress for a specific template
    isTemplateActionInProgress(templateId) {
      return (
        this.editingTemplateId === templateId ||
        this.viewingTemplateId === templateId ||
        this.deletingTemplateId === templateId ||
        this.copyingTemplateId === templateId ||
        this.preparingTemplateId === templateId
      );
    },

    async init() {
      await this.loadTemplates();
    },

    // Delegate to shared DisplayUtils
    tableTypeKey(template) {
      return DU.tableTypeKey ? DU.tableTypeKey(template) : "";
    },

    isPostgresType(template) {
      return DU.isPostgresType ? DU.isPostgresType(template) : false;
    },

    tableTypeLabel(template) {
      return DU.tableTypeLabel ? DU.tableTypeLabel(template) : "";
    },

    tableTypeIconSrc(template) {
      return DU.tableTypeIconSrc ? DU.tableTypeIconSrc(template) : "";
    },

    tableFqn(template) {
      return DU.tableFqn ? DU.tableFqn(template) : "";
    },

    tableFqnStacked(template) {
      return DU.tableFqnStacked ? DU.tableFqnStacked(template) : "";
    },

    async loadTemplates() {
      this.loading = true;
      this.error = null;
      try {
        const response = await fetch("/api/templates/");
        if (response.ok) {
          this.templates = await response.json();
          this.filteredTemplates = this.templates;
          return;
        } else {
          const payload = await response.json().catch(() => ({}));
          const detail = payload && payload.detail ? payload.detail : null;
          this.error =
            (detail && (detail.message || detail.detail || detail)) ||
            `Failed to load templates (HTTP ${response.status})`;
          console.error("Failed to load templates:", this.error);
        }
      } catch (error) {
        this.error = error?.message || String(error);
        console.error("Error loading templates:", error);
      } finally {
        this.loading = false;
      }
    },

    filterTemplates() {
      let filtered = this.templates;

      // Apply type filter first
      if (this.typeFilter) {
        filtered = filtered.filter((t) => {
          const label = this.tableTypeLabel(t);
          return label === this.typeFilter;
        });
      }

      // Then apply search query
      if (this.searchQuery) {
        const query = this.searchQuery.toLowerCase();
        filtered = filtered.filter(
          (t) =>
            t.template_name.toLowerCase().includes(query) ||
            (t.description && t.description.toLowerCase().includes(query)) ||
            this.deriveWorkloadLabel(t.config).toLowerCase().includes(query) ||
            this.tableFqn(t).toLowerCase().includes(query) ||
            this.tableTypeLabel(t).toLowerCase().includes(query),
        );
      }

      this.filteredTemplates = filtered;
    },

    // Delegate to shared DisplayUtils
    deriveWorkloadLabel(config) {
      return DU.deriveWorkloadLabel ? DU.deriveWorkloadLabel(config) : "MIXED";
    },

    workloadMixDisplay(config) {
      return DU.workloadMixDisplay ? DU.workloadMixDisplay(config) : "—";
    },

    durationDisplay(config) {
      return DU.durationDisplay ? DU.durationDisplay(config) : "—";
    },

    loadModeDisplay(config) {
      return DU.loadModeDisplay ? DU.loadModeDisplay(config) : "—";
    },

    scalingDisplay(config) {
      return DU.scalingDisplay ? DU.scalingDisplay(config) : "—";
    },

    warehouseDisplay(template) {
      return DU.warehouseDisplay ? DU.warehouseDisplay(template) : "—";
    },

    createNewTemplate() {
      window.location.href = "/configure?mode=new";
    },

    async prepareTest(template) {
      if (this.preparingTemplateId) return; // Already preparing
      
      const isPostgres = this.isPostgresType(template);

      this.preparingTemplateId = template.template_id;
      try {
        // For Snowflake-executed templates, enforce that the execution warehouse
        // isn't the same as the results warehouse (`SNOWFLAKE_WAREHOUSE`).
        if (!isPostgres) {
          const infoResp = await fetch("/api/info");
          const info = infoResp.ok ? await infoResp.json() : {};
          const resultsWarehouse = String(info.results_warehouse || "").toUpperCase();
          const execWarehouse = String(
            template?.config?.warehouse_name || "",
          ).toUpperCase();

          if (resultsWarehouse && execWarehouse && resultsWarehouse === execWarehouse) {
            window.toast.queueNext(
              "warning",
              `This template is configured to run on ${execWarehouse}, which is also your results warehouse (${resultsWarehouse}). Please edit the template and choose a different warehouse before running.`,
            );
            window.location.href = "/configure";
            return;
          }
        }

        // Use unified endpoint for all scaling modes (AUTO, BOUNDED, FIXED)
        const endpoint = `/api/tests/from-template/${template.template_id}`;
        const resp = await fetch(endpoint, { method: "POST" });
        if (!resp.ok) {
          const err = await resp.json().catch(() => ({}));
          throw new Error(err.detail || "Failed to prepare test");
        }
        const data = await resp.json();
        window.location.href = data.dashboard_url || `/dashboard/${data.test_id}`;
      } catch (e) {
        console.error("Failed to prepare template:", e);
        window.toast.error(`Failed to prepare test: ${e.message || e}`);
      } finally {
        this.preparingTemplateId = null;
      }
    },

    editTemplate(template) {
      this.editingTemplateId = template.template_id;
      const templateId = encodeURIComponent(String(template?.template_id || ""));
      window.location.href = templateId
        ? `/configure?template_id=${templateId}`
        : "/configure";
    },

    viewTemplateDetails(template) {
      // Route to the same /configure page, but force read-only mode.
      // (The configure page will also force read-only if usage_count > 0.)
      this.viewingTemplateId = template.template_id;
      const templateId = encodeURIComponent(String(template?.template_id || ""));
      window.location.href = templateId
        ? `/configure?template_id=${templateId}&mode=view`
        : "/configure?mode=view";
    },

    async duplicateTemplate(template) {
      if (this.copyingTemplateId) return;
      this.copyingTemplateId = template.template_id;

      const newTemplate = {
        ...template,
        template_name: `${template.template_name} (Copy)`,
        template_id: undefined,
        created_at: undefined,
        updated_at: undefined,
        usage_count: 0,
      };

      try {
        const response = await fetch("/api/templates/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(newTemplate),
        });

        if (response.ok) {
          await this.loadTemplates();
          window.toast.success("Template copied.");
        } else {
          window.toast.error("Failed to duplicate template");
        }
      } catch (error) {
        console.error("Error duplicating template:", error);
        window.toast.error("Error duplicating template");
      } finally {
        this.copyingTemplateId = null;
      }
    },

    async deleteTemplate(template) {
      const message =
        template.usage_count > 0
          ? `Delete template "${template.template_name}" and all ${template.usage_count} test results?`
          : `Delete template "${template.template_name}"?`;

      const confirmed = await window.toast.confirm(message, {
        confirmText: "Delete",
        confirmVariant: "danger",
        timeoutMs: 10_000,
      });
      if (!confirmed) {
        return;
      }

      this.deletingTemplateId = template.template_id;
      try {
        const response = await fetch(`/api/templates/${template.template_id}`, {
          method: "DELETE",
        });

        if (response.ok) {
          await this.loadTemplates();
          window.toast.success("Template deleted.");
        } else {
          window.toast.error("Failed to delete template");
        }
      } catch (error) {
        console.error("Error deleting template:", error);
        window.toast.error("Error deleting template");
      } finally {
        this.deletingTemplateId = null;
      }
    },
  }}
