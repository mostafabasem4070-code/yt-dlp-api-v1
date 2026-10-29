/* ==========================================================================
   TELEMETRY & SERVER LIVE RESOURCES
   YouTube API Hub - Cloud Control Center
   ========================================================================== */

let resourceTimer = null;

async function fetchServerResources(isManual = false) {
    if (isManual) {
        showToast('جاري تحديث بيانات الموارد الحية...');
    }

    try {
        const res = await apiFetch('/api/monitor/resources');
        if (!res.ok) return;
        const data = await res.json();

        updateResourcesUI(data);

        // تغذية محرك الرسوم البيانية الحية (Charts)
        if (window.TelemetryCharts) {
            window.TelemetryCharts.pushData(data.cpu_percent || 0, data.ram_percent || 0);
        }

        if (isManual) {
            showToast('تم تحديث قراءات الموارد بنجاح!');
        }
    } catch (err) {
        console.error('Failed to fetch resources:', err);
    }
}

function updateResourcesUI(res) {
    if (!res) return;

    const cpuPct = res.cpu ? res.cpu.percent : (res.cpu_percent || 0);
    const cpuEl = document.getElementById('cpuPercentVal');
    const cpuSideEl = document.getElementById('sideCpuBadge');
    const cpuOverviewEl = document.getElementById('overviewCpuVal');

    if (cpuEl) cpuEl.textContent = `${cpuPct.toFixed(1)}%`;
    if (cpuOverviewEl) cpuOverviewEl.textContent = `${cpuPct.toFixed(1)}%`;
    if (cpuSideEl) cpuSideEl.textContent = `${cpuPct.toFixed(1)}%`;

    const cpuBar = document.getElementById('cpuBarFill');
    if (cpuBar) {
        cpuBar.style.width = `${Math.min(100, cpuPct)}%`;
        cpuBar.className = `res-progress-fill ${cpuPct > 85 ? 'amber' : 'cyan'}`;
    }

    const cpuCoresEl = document.getElementById('cpuCoresVal');
    if (cpuCoresEl) cpuCoresEl.textContent = res.cpu ? res.cpu.cores : (res.cores || 1);

    const cpuBadge = document.getElementById('cpuBadge');
    if (cpuBadge) {
        if (cpuPct > 85) {
            cpuBadge.className = 'comp-badge critical';
            cpuBadge.textContent = 'ضغط مرتفع';
        } else if (cpuPct > 60) {
            cpuBadge.className = 'comp-badge warning';
            cpuBadge.textContent = 'نشاط متوسط';
        } else {
            cpuBadge.className = 'comp-badge healthy';
            cpuBadge.textContent = 'مستقر وطبيعي';
        }
    }

    // 2. RAM
    const ramPct = res.ram ? res.ram.percent : (res.ram_percent || 0);
    const ramEl = document.getElementById('ramPercentVal');
    const ramOverviewEl = document.getElementById('overviewRamVal');

    if (ramEl) ramEl.textContent = `${ramPct.toFixed(1)}%`;
    if (ramOverviewEl) ramOverviewEl.textContent = `${ramPct.toFixed(1)}%`;

    const ramBar = document.getElementById('ramBarFill');
    if (ramBar) {
        ramBar.style.width = `${Math.min(100, ramPct)}%`;
        ramBar.className = `res-progress-fill ${ramPct > 90 ? 'amber' : 'purple'}`;
    }

    const ramUsedEl = document.getElementById('ramUsedVal');
    if (ramUsedEl) ramUsedEl.textContent = `${res.ram ? res.ram.used_mb : (res.ram_used_mb || 0)} MB`;

    const ramTotalEl = document.getElementById('ramTotalVal');
    if (ramTotalEl) ramTotalEl.textContent = `${res.ram ? res.ram.total_mb : (res.ram_total_mb || 0)} MB`;

    const ramProcEl = document.getElementById('ramProcessVal');
    if (ramProcEl) ramProcEl.textContent = `${res.ram ? res.ram.process_mb : (res.process_ram_mb || 0)} MB`;

    const ramBadge = document.getElementById('ramBadge');
    if (ramBadge) {
        if (ramPct > 90) {
            ramBadge.className = 'comp-badge critical';
            ramBadge.textContent = 'شبه ممتلئة';
        } else if (ramPct > 75) {
            ramBadge.className = 'comp-badge warning';
            ramBadge.textContent = 'استهلاك مرتفع';
        } else {
            ramBadge.className = 'comp-badge healthy';
            ramBadge.textContent = 'متاح بكفاءة';
        }
    }

    // 3. Disk
    const diskPct = res.disk ? res.disk.percent : (res.disk_percent || 0);
    const diskEl = document.getElementById('diskPercentVal');
    const diskOverviewEl = document.getElementById('overviewDiskVal');

    if (diskEl) diskEl.textContent = `${diskPct.toFixed(1)}%`;
    if (diskOverviewEl) diskOverviewEl.textContent = `${diskPct.toFixed(1)}%`;

    const diskBar = document.getElementById('diskBarFill');
    if (diskBar) {
        diskBar.style.width = `${Math.min(100, diskPct)}%`;
        diskBar.className = `res-progress-fill ${diskPct > 90 ? 'amber' : 'emerald'}`;
    }

    const diskUsedEl = document.getElementById('diskUsedVal');
    if (diskUsedEl) diskUsedEl.textContent = `${res.disk ? res.disk.used_gb : (res.disk_used_gb || 0)} GB`;

    const diskTotalEl = document.getElementById('diskTotalVal');
    if (diskTotalEl) diskTotalEl.textContent = `${res.disk ? res.disk.total_gb : (res.disk_total_gb || 0)} GB`;

    const diskFreeEl = document.getElementById('diskFreeVal');
    if (diskFreeEl) diskFreeEl.textContent = `${res.disk ? res.disk.free_gb : (res.disk_free_gb || 0)} GB`;

    // 4. Network & Uptime
    const netSentEl = document.getElementById('netSentVal');
    if (netSentEl) netSentEl.textContent = `${res.network ? res.network.sent_mb : (res.net_sent_mb || 0)} MB`;

    const netRecvEl = document.getElementById('netRecvVal');
    if (netRecvEl) netRecvEl.textContent = `${res.network ? res.network.recv_mb : (res.net_recv_mb || 0)} MB`;

    const uptimeEl = document.getElementById('uptimeVal');
    const uptimeOverviewEl = document.getElementById('overviewUptimeVal');
    const uptimeSideEl = document.getElementById('sideUptimeText');

    const uptimeStr = res.uptime ? res.uptime.formatted : (res.uptime_human || '--');
    if (uptimeEl) uptimeEl.textContent = uptimeStr;
    if (uptimeOverviewEl) uptimeOverviewEl.textContent = uptimeStr;
    if (uptimeSideEl) uptimeSideEl.textContent = uptimeStr;
}

function toggleResourceAutoRefresh(enabled) {
    if (resourceTimer) {
        clearInterval(resourceTimer);
        resourceTimer = null;
    }
    if (enabled) {
        resourceTimer = setInterval(() => {
            fetchServerResources(false);
        }, 4000);
        showToast('تم تفعيل التحديث التلقائي للموارد.');
    } else {
        showToast('تم إيقاف التحديث التلقائي مؤقتاً.');
    }
}

function startTelemetryPolling() {
    fetchServerResources(false);
    if (resourceTimer) clearInterval(resourceTimer);
    resourceTimer = setInterval(() => {
        const chk = document.getElementById('autoRefreshResources');
        if (!chk || chk.checked) {
            fetchServerResources(false);
        }
    }, 4000);
}

function stopTelemetryPolling() {
    if (resourceTimer) {
        clearInterval(resourceTimer);
        resourceTimer = null;
    }
}

window.fetchServerResources = fetchServerResources;
window.updateResourcesUI = updateResourcesUI;
window.toggleResourceAutoRefresh = toggleResourceAutoRefresh;
window.startTelemetryPolling = startTelemetryPolling;
window.stopTelemetryPolling = stopTelemetryPolling;
