/* ==========================================================================
   APP CONTROLLER, ROUTING & LIFECYCLE
   YouTube API Hub - Cloud Control Center
   ========================================================================== */

function switchNavTab(tabId, tabTitle, navBtn) {
    // 1. تحديث زر القائمة النشط
    document.querySelectorAll('.nav-item').forEach(item => {
        item.classList.remove('active');
    });

    if (navBtn) {
        navBtn.classList.add('active');
    } else {
        const matchingBtn = document.querySelector(`.nav-item[onclick*="${tabId}"]`);
        if (matchingBtn) matchingBtn.classList.add('active');
    }

    // 2. إخفاء وإظهار التبويبات
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.remove('active');
    });

    const activePanel = document.getElementById(tabId);
    if (activePanel) {
        activePanel.classList.add('active');
    }

    // 3. تحديث عنوان الصفحة العلوي
    const titleEl = document.getElementById('pageTitleText');
    if (titleEl && tabTitle) {
        titleEl.textContent = tabTitle;
    }

    // 4. إغلاق القائمة الجانبية على الجوال بعد النقر
    closeMobileSidebar();

    // 5. تحميل بيانات التبويب المحدد
    if (tabId === 'tab-overview') {
        if (window.loadOverview) loadOverview();
    } else if (tabId === 'tab-resources') {
        if (window.fetchServerResources) fetchServerResources(false);
        if (window.TelemetryCharts) window.TelemetryCharts.redraw();
    } else if (tabId === 'tab-components') {
        if (window.loadOverview) loadOverview();
    } else if (tabId === 'tab-security') {
        if (window.loadSecuritySettings) loadSecuritySettings();
    } else if (tabId === 'tab-cookies') {
        if (window.loadCookieStatus) loadCookieStatus();
        if (window.loadGoogleAuthStatus) loadGoogleAuthStatus();
    } else if (tabId === 'tab-logs') {
        if (window.loadServerLogs) loadServerLogs();
    }
}

function toggleMobileSidebar() {
    const sidebar = document.getElementById('appSidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (sidebar) sidebar.classList.toggle('open');
    if (overlay) overlay.classList.toggle('active');
}

function closeMobileSidebar() {
    const sidebar = document.getElementById('appSidebar');
    const overlay = document.getElementById('sidebarOverlay');
    if (sidebar) sidebar.classList.remove('open');
    if (overlay) overlay.classList.remove('active');
}

function initDashboardData() {
    if (window.loadOverview) loadOverview();
    if (window.loadSecuritySettings) loadSecuritySettings();
    if (window.loadCookieStatus) loadCookieStatus();
    if (window.startTelemetryPolling) startTelemetryPolling();
    if (window.startLogsPolling) startLogsPolling();
}

function stopLiveTimers() {
    if (window.stopTelemetryPolling) stopTelemetryPolling();
    if (window.stopLogsPolling) stopLogsPolling();
}

window.switchNavTab = switchNavTab;
window.toggleMobileSidebar = toggleMobileSidebar;
window.closeMobileSidebar = closeMobileSidebar;
window.initDashboardData = initDashboardData;
window.stopLiveTimers = stopLiveTimers;

// تشغيل الفحص الأولي فور اكتمال تحميل المستند
window.addEventListener('DOMContentLoaded', () => {
    if (window.checkAuthOnStartup) {
        window.checkAuthOnStartup();
    }
});
