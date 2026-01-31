/**
 * Dashboard Historical Metrics Module
 * Methods for loading and populating historical metrics into charts.
 */
window.DashboardMixins = window.DashboardMixins || {};

window.DashboardMixins.historicalMetrics = {
  async loadHistoricalMetrics() {
    if (!this.testId) return;
    try {
      const resp = await fetch(`/api/tests/${this.testId}/metrics`);
      if (!resp.ok) return;
      const data = await resp.json();
      
      if (!data.snapshots || data.snapshots.length === 0) {
        console.log("No historical metrics snapshots found for test");
        return;
      }

      if (this.debug) {
        this._debugCharts("loadHistoricalMetrics: start", {
          snapshots: data.snapshots.length,
        });
      }
      
      // Populate charts with historical data
      let throughputCanvas = document.getElementById("throughputChart");
      let concurrencyCanvas = document.getElementById("concurrencyChart");
      let latencyCanvas = document.getElementById("latencyChart");
      let sfRunningCanvas = document.getElementById("sfRunningChart");
      let opsSecCanvas = document.getElementById("opsSecChart");
      let resourcesCpuCanvas = document.getElementById("resourcesCpuSparkline");
      let resourcesMemCanvas = document.getElementById("resourcesMemSparkline");
      let resourcesHistoryCanvas = document.getElementById("resourcesHistoryChart");
      let throughputChart = throughputCanvas && (throughputCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(throughputCanvas) : null));
      let concurrencyChart = concurrencyCanvas && (concurrencyCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(concurrencyCanvas) : null));
      let latencyChart = latencyCanvas && (latencyCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(latencyCanvas) : null));
      let sfRunningChart = sfRunningCanvas && (sfRunningCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(sfRunningCanvas) : null));
      let opsSecChart = opsSecCanvas && (opsSecCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(opsSecCanvas) : null));
      let resourcesCpuChart = resourcesCpuCanvas && (resourcesCpuCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(resourcesCpuCanvas) : null));
      let resourcesMemChart = resourcesMemCanvas && (resourcesMemCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(resourcesMemCanvas) : null));
      let resourcesHistoryChart = resourcesHistoryCanvas && (resourcesHistoryCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(resourcesHistoryCanvas) : null));
      
      // If charts don't exist yet, initialize them
      if (!throughputChart || !latencyChart || (concurrencyCanvas && !concurrencyChart) || (sfRunningCanvas && !sfRunningChart) || (opsSecCanvas && !opsSecChart) || (resourcesCpuCanvas && !resourcesCpuChart) || (resourcesMemCanvas && !resourcesMemChart) || (resourcesHistoryCanvas && !resourcesHistoryChart)) {
        this.initCharts();
      }
      
      // Re-query DOM after potential init (canvas refs may have been null initially)
      throughputCanvas = document.getElementById("throughputChart");
      concurrencyCanvas = document.getElementById("concurrencyChart");
      latencyCanvas = document.getElementById("latencyChart");
      sfRunningCanvas = document.getElementById("sfRunningChart");
      opsSecCanvas = document.getElementById("opsSecChart");
      resourcesCpuCanvas = document.getElementById("resourcesCpuSparkline");
      resourcesMemCanvas = document.getElementById("resourcesMemSparkline");
      resourcesHistoryCanvas = document.getElementById("resourcesHistoryChart");
      const throughputChart2 = throughputCanvas && (throughputCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(throughputCanvas) : null));
      const concurrencyChart2 = concurrencyCanvas && (concurrencyCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(concurrencyCanvas) : null));
      const latencyChart2 = latencyCanvas && (latencyCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(latencyCanvas) : null));
      const sfRunningChart2 = sfRunningCanvas && (sfRunningCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(sfRunningCanvas) : null));
      const opsSecChart2 = opsSecCanvas && (opsSecCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(opsSecCanvas) : null));
      const resourcesCpuChart2 = resourcesCpuCanvas && (resourcesCpuCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(resourcesCpuCanvas) : null));
      const resourcesMemChart2 = resourcesMemCanvas && (resourcesMemCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(resourcesMemCanvas) : null));
      const resourcesHistoryChart2 = resourcesHistoryCanvas && (resourcesHistoryCanvas.__chart || (window.Chart && Chart.getChart ? Chart.getChart(resourcesHistoryCanvas) : null));
      
      // Clear existing data
      if (throughputChart2) {
        throughputChart2.data.labels = [];
        throughputChart2.data.datasets[0].data = [];
        if (throughputChart2.data.datasets[1]) {
          throughputChart2.data.datasets[1].data = [];
        }
      }
      if (concurrencyChart2) {
        concurrencyChart2.data.labels = [];
        concurrencyChart2.data.datasets.forEach((ds) => {
          ds.data = [];
        });
      }
      if (latencyChart2) {
        latencyChart2.data.labels = [];
        latencyChart2.data.datasets[0].data = [];
        latencyChart2.data.datasets[1].data = [];
        latencyChart2.data.datasets[2].data = [];
      }
      if (sfRunningChart2) {
        sfRunningChart2.data.labels = [];
        sfRunningChart2.data.datasets.forEach((ds) => {
          ds.data = [];
        });
      }
      if (opsSecChart2) {
        opsSecChart2.data.labels = [];
        opsSecChart2.data.datasets.forEach((ds) => {
          ds.data = [];
        });
      }
      if (resourcesCpuChart2) {
        resourcesCpuChart2.data.labels = [];
        resourcesCpuChart2.data.datasets[0].data = [];
      }
      if (resourcesMemChart2) {
        resourcesMemChart2.data.labels = [];
        resourcesMemChart2.data.datasets[0].data = [];
      }
      if (resourcesHistoryChart2) {
        resourcesHistoryChart2.data.labels = [];
        resourcesHistoryChart2.data.datasets.forEach((ds) => {
          ds.data = [];
        });
      }

      const tableType = (this.templateInfo?.table_type || "").toLowerCase();
      const isPostgres = ["postgres", "snowflake_postgres"].includes(tableType);
      
      // Populate with historical data
      let resourcesSeen = false;
      for (const snapshot of data.snapshots) {
        const secs = Number(snapshot.elapsed_seconds || 0);
        const ts = `${this.formatSecondsTenths(secs)}s`;
        
        if (throughputChart2) {
          throughputChart2.data.labels.push(ts);
          throughputChart2.data.datasets[0].data.push(snapshot.ops_per_sec);
          if (throughputChart2.data.datasets[1]) {
            const errRate = Number(snapshot.error_rate || 0) * 100.0;
            throughputChart2.data.datasets[1].data.push(errRate);
          }
        }

        if (concurrencyChart2) {
          concurrencyChart2.data.labels.push(ts);
          const target = Number(snapshot.target_workers || 0);
          const inFlight = Number(snapshot.active_connections || 0);
          const sfQueuedBench = Number(snapshot.sf_queued_bench || 0);
          const sfQueued = sfQueuedBench > 0 ? sfQueuedBench : Number(snapshot.sf_queued || 0);

          if (isPostgres) {
            if (concurrencyChart2.data.datasets[0]) {
              concurrencyChart2.data.datasets[0].data.push(target);
            }
            if (concurrencyChart2.data.datasets[1]) {
              concurrencyChart2.data.datasets[1].data.push(inFlight);
            }
          } else {
            if (concurrencyChart2.data.datasets[0]) {
              concurrencyChart2.data.datasets[0].data.push(target);
            }
            if (concurrencyChart2.data.datasets[1]) {
              concurrencyChart2.data.datasets[1].data.push(inFlight);
            }
            if (concurrencyChart2.data.datasets[2]) {
              concurrencyChart2.data.datasets[2].data.push(sfQueued);
            }
          }
        }
        
        if (latencyChart2) {
          latencyChart2.data.labels.push(ts);
          latencyChart2.data.datasets[0].data.push(snapshot.p50_latency);
          latencyChart2.data.datasets[1].data.push(snapshot.p95_latency);
          latencyChart2.data.datasets[2].data.push(snapshot.p99_latency);
        }

        if (sfRunningChart2) {
          sfRunningChart2.data.labels.push(ts);
          const totalTagged = Number(snapshot.sf_running_tagged || 0);
          const totalRaw = Number(snapshot.sf_running || 0);
          const total = totalTagged > 0 ? totalTagged : totalRaw;
          sfRunningChart2.data.datasets[0].data.push(total);
          sfRunningChart2.data.datasets[1].data.push(Number(snapshot.sf_running_read || 0));
          sfRunningChart2.data.datasets[2].data.push(Number(snapshot.sf_running_point_lookup || 0));
          sfRunningChart2.data.datasets[3].data.push(Number(snapshot.sf_running_range_scan || 0));
          sfRunningChart2.data.datasets[4].data.push(Number(snapshot.sf_running_write || 0));
          sfRunningChart2.data.datasets[5].data.push(Number(snapshot.sf_running_insert || 0));
          sfRunningChart2.data.datasets[6].data.push(Number(snapshot.sf_running_update || 0));
          sfRunningChart2.data.datasets[7].data.push(Number(snapshot.sf_blocked || 0));
        }

        if (opsSecChart2) {
          opsSecChart2.data.labels.push(ts);
          const totalOps = Number(snapshot.ops_per_sec || 0);
          const readOps = Number(snapshot.app_read_ops_sec || 0);
          const writeOps = Number(snapshot.app_write_ops_sec || 0);
          const plOps = Number(snapshot.app_point_lookup_ops_sec || 0);
          const rsOps = Number(snapshot.app_range_scan_ops_sec || 0);
          const insOps = Number(snapshot.app_insert_ops_sec || 0);
          const updOps = Number(snapshot.app_update_ops_sec || 0);
          opsSecChart2.data.datasets[0].data.push(totalOps);
          opsSecChart2.data.datasets[1].data.push(readOps);
          opsSecChart2.data.datasets[2].data.push(plOps);
          opsSecChart2.data.datasets[3].data.push(rsOps);
          opsSecChart2.data.datasets[4].data.push(writeOps);
          opsSecChart2.data.datasets[5].data.push(insOps);
          opsSecChart2.data.datasets[6].data.push(updOps);
        }

        const cpu = Number(snapshot.resources_host_cpu_percent ?? snapshot.resources_cpu_percent);
        const mem = Number(snapshot.resources_host_memory_mb ?? snapshot.resources_memory_mb);
        if (Number.isFinite(cpu) || Number.isFinite(mem)) {
          resourcesSeen = true;
        }
        if (resourcesCpuChart2) {
          resourcesCpuChart2.data.labels.push(ts);
          resourcesCpuChart2.data.datasets[0].data.push(Number.isFinite(cpu) ? cpu : 0);
        }
        if (resourcesMemChart2) {
          resourcesMemChart2.data.labels.push(ts);
          resourcesMemChart2.data.datasets[0].data.push(Number.isFinite(mem) ? mem : 0);
        }
        if (resourcesHistoryChart2) {
          resourcesHistoryChart2.data.labels.push(ts);
          resourcesHistoryChart2.data.datasets[0].data.push(Number.isFinite(cpu) ? cpu : 0);
          resourcesHistoryChart2.data.datasets[1].data.push(Number.isFinite(mem) ? mem : 0);
        }
      }
      
      // Update charts
      if (throughputChart2) throughputChart2.update();
      if (concurrencyChart2) concurrencyChart2.update();
      if (latencyChart2) latencyChart2.update();
      if (sfRunningChart2) {
        this.applySfRunningBreakdownToChart({ skipUpdate: true });
        sfRunningChart2.update();
      }
      if (opsSecChart2) {
        this.applyOpsSecBreakdownToChart({ skipUpdate: true });
        opsSecChart2.update();
      }
      if (resourcesCpuChart2) resourcesCpuChart2.update();
      if (resourcesMemChart2) resourcesMemChart2.update();
      if (resourcesHistoryChart2) resourcesHistoryChart2.update();

      const lastSnapshot = data.snapshots && data.snapshots.length ? data.snapshots[data.snapshots.length - 1] : null;
      if (lastSnapshot) {
        const hostCpu = Number(lastSnapshot.resources_host_cpu_percent);
        const cpu = Number(Number.isFinite(hostCpu) ? hostCpu : lastSnapshot.resources_cpu_percent);
        const hostMem = Number(lastSnapshot.resources_host_memory_mb);
        const mem = Number(Number.isFinite(hostMem) ? hostMem : lastSnapshot.resources_memory_mb);
        const hostTotal = Number(lastSnapshot.resources_host_memory_total_mb);
        const hostAvail = Number(lastSnapshot.resources_host_memory_available_mb);
        const hostPct = Number(lastSnapshot.resources_host_memory_percent);
        const hostCores = Number(lastSnapshot.resources_host_cpu_cores);
        const cgroupCpu = Number(lastSnapshot.resources_cgroup_cpu_percent);
        const cgroupCores = Number(lastSnapshot.resources_cgroup_cpu_quota_cores);
        const cgroupMem = Number(lastSnapshot.resources_cgroup_memory_mb);
        const cgroupMemLimit = Number(lastSnapshot.resources_cgroup_memory_limit_mb);
        const cgroupMemPct = Number(lastSnapshot.resources_cgroup_memory_percent);
        this.metrics.resources_available = resourcesSeen || Number.isFinite(cpu) || Number.isFinite(mem);
        if (Number.isFinite(cpu)) this.metrics.cpu_percent = cpu;
        if (Number.isFinite(mem)) this.metrics.memory_mb = mem;
        if (Number.isFinite(hostCpu)) this.metrics.host_cpu_percent = hostCpu;
        if (Number.isFinite(hostMem)) this.metrics.host_memory_mb = hostMem;
        if (Number.isFinite(hostTotal)) this.metrics.host_memory_total_mb = hostTotal;
        if (Number.isFinite(hostAvail)) this.metrics.host_memory_available_mb = hostAvail;
        if (Number.isFinite(hostPct)) this.metrics.host_memory_percent = hostPct;
        if (Number.isFinite(hostCores)) this.metrics.host_cpu_cores = hostCores;
        if (Number.isFinite(cgroupCpu)) this.metrics.cgroup_cpu_percent = cgroupCpu;
        if (Number.isFinite(cgroupCores)) this.metrics.cgroup_cpu_quota_cores = cgroupCores;
        if (Number.isFinite(cgroupMem)) this.metrics.cgroup_memory_mb = cgroupMem;
        if (Number.isFinite(cgroupMemLimit)) this.metrics.cgroup_memory_limit_mb = cgroupMemLimit;
        if (Number.isFinite(cgroupMemPct)) this.metrics.cgroup_memory_percent = cgroupMemPct;
      } else {
        this.metrics.resources_available = resourcesSeen;
      }

      if (this.debug) {
        this._debugCharts("loadHistoricalMetrics: after render", { snapshots: data.snapshots.length });
      }
      
      console.log(`Loaded ${data.snapshots.length} historical metrics snapshots`);
    } catch (e) {
      console.error("Failed to load historical metrics:", e);
      try {
        if (window.toast && typeof window.toast.error === "function") {
          window.toast.error(`Failed to render charts: ${e && e.message ? e.message : String(e)}`);
        }
      } catch (_) {}
    }
  },
};
