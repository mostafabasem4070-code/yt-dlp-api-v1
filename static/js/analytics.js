/* ==========================================================================
   EXTRACTION STATISTICS & ANALYTICS CONTROLLER
   YouTube API Hub - Cloud Control Center
   ========================================================================== */

let analyticsDataCache = null;
let currentChartMode = 'daily'; // 'daily' or 'hourly'
let analyticsAutoRefreshTimer = null;

async function loadAnalyticsData(isSilent = false) {
    const refreshBtn = document.getElementById('btnRefreshAnalytics');
    if (refreshBtn && !isSilent) {
        refreshBtn.disabled = true;
        refreshBtn.innerHTML = `
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="animation: spin 1s linear infinite;"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg>
            <span>جاري التحديث...</span>
        `;
    }

    try {
        const res = await apiFetch('/api/stats/summary?top_limit=25&recent_limit=35');
        if (!res.ok) return;
        const data = await res.json();
        analyticsDataCache = data;

        // 1. تحديث بطاقات الـ KPIs الرئيسية
        updateAnalyticsKPIs(data.kpis || {});

        // 2. تحديث الشارات في القائمة الجانبية وصفحة النظرة العامة
        updateBadgesAndOverview(data.kpis || {}, data.top_videos || []);

        // 3. رسم الرسم البياني لنشاط الاستخراج
        renderAnalyticsChart(data);

        // 4. بناء جدول أكثر الروابط استخراجاً
        renderTopVideosTable(data.top_videos || []);

        // 5. بناء جدول أحدث عمليات الاستخراج المباشرة
        renderRecentExtractionsTable(data.recent_extractions || []);

        // 6. بناء قائمة المنصات والدومينات الأكثر طلباً
        renderTopReferrers(data.top_referrers || [], data.kpis?.total_extractions || 0);

    } catch (err) {
        console.error('Failed to load extraction stats:', err);
    } finally {
        if (refreshBtn && !isSilent) {
            refreshBtn.disabled = false;
            refreshBtn.innerHTML = `
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"></path></svg>
                <span>تحديث الإحصائيات</span>
            `;
        }
    }
}

function updateAnalyticsKPIs(kpis) {
    const totalEl = document.getElementById('statAnalyticsTotal');
    const todayEl = document.getElementById('statAnalyticsToday');
    const successRateEl = document.getElementById('statAnalyticsSuccessRate');
    const cacheHitsEl = document.getElementById('statAnalyticsCacheHits');
    const avgTimeEl = document.getElementById('statAnalyticsAvgTime');
    const uniqueEl = document.getElementById('statAnalyticsUnique');

    if (totalEl) totalEl.textContent = (kpis.total_extractions || 0).toLocaleString();
    if (todayEl) todayEl.textContent = `+${(kpis.today_extractions || 0).toLocaleString()} اليوم`;
    if (successRateEl) successRateEl.textContent = `${kpis.success_rate ?? 100}%`;
    if (cacheHitsEl) {
        cacheHitsEl.textContent = `${(kpis.cache_hits || 0).toLocaleString()} (${kpis.cache_hit_rate ?? 0}%)`;
    }
    if (avgTimeEl) avgTimeEl.textContent = `${Math.round(kpis.avg_response_time_ms || 0)} ms`;
    if (uniqueEl) uniqueEl.textContent = (kpis.unique_videos || 0).toLocaleString();

    // تحديث تفاصيل إضافية
    const successSub = document.getElementById('statAnalyticsSuccessSub');
    if (successSub) {
        successSub.textContent = `${kpis.success_count || 0} ناجح • ${kpis.failed_count || 0} فاشل`;
    }

    const cacheSub = document.getElementById('statAnalyticsCacheSub');
    if (cacheSub) {
        cacheSub.textContent = `توفير فوري عبر الذاكرة لتجنب خنق يوتيوب`;
    }

    const timeSub = document.getElementById('statAnalyticsTimeSub');
    if (timeSub) {
        timeSub.textContent = `الكاش: ~5ms • الاستخراج الجديد: ~${Math.round(kpis.avg_fresh_response_time_ms || 0)}ms`;
    }
}

function updateBadgesAndOverview(kpis, topVideos) {
    // شارة القائمة الجانبية
    const sideBadge = document.getElementById('sideExtractionsBadge');
    if (sideBadge) {
        const total = kpis.total_extractions || 0;
        sideBadge.textContent = `${total.toLocaleString()} طلب`;
    }

    // بطاقات النظرة العامة (Overview Page)
    const ovTotal = document.getElementById('overviewStatExtractionsTotal');
    const ovToday = document.getElementById('overviewStatExtractionsToday');
    const ovSuccess = document.getElementById('overviewStatExtractionsSuccess');
    const ovCache = document.getElementById('overviewStatExtractionsCache');
    const ovTopTitle = document.getElementById('overviewStatTopVideoTitle');

    if (ovTotal) ovTotal.textContent = (kpis.total_extractions || 0).toLocaleString();
    if (ovToday) ovToday.textContent = `+${(kpis.today_extractions || 0).toLocaleString()} اليوم`;
    if (ovSuccess) ovSuccess.textContent = `${kpis.success_rate ?? 100}%`;
    if (ovCache) ovCache.textContent = `${(kpis.cache_hits || 0).toLocaleString()} من الكاش`;

    if (ovTopTitle) {
        if (topVideos && topVideos.length > 0) {
            const topV = topVideos[0];
            ovTopTitle.textContent = `${topV.title} (${topV.count} مرة)`;
            ovTopTitle.title = topV.title;
        } else {
            ovTopTitle.textContent = 'لا توجد بيانات استخراج بعد';
        }
    }
}

/* ==================== TOP EXTRACTED VIDEOS TABLE ==================== */
function renderTopVideosTable(videos) {
    const tbody = document.getElementById('topVideosTableBody');
    if (!tbody) return;

    if (!videos || videos.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align:center; padding:36px; color:var(--text-muted);">
                    <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="margin:0 auto 10px; opacity:0.5; display:block;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>
                    لم يتم تسجيل أي عمليات استخراج حتى الآن. بمجرد إرسال طلبات للـ API ستظهر أكثر الفيديوهات طلباً هنا تلقائياً.
                </td>
            </tr>
        `;
        return;
    }

    const maxCount = videos[0]?.count || 1;

    let html = '';
    videos.forEach((v, index) => {
        const rank = index + 1;
        const rankBadgeClass = rank === 1 ? 'rank-1' : (rank === 2 ? 'rank-2' : (rank === 3 ? 'rank-3' : 'rank-other'));
        const thumbUrl = v.thumbnail || `https://i.ytimg.com/vi/${v.video_id}/hqdefault.jpg`;
        const percentage = Math.round((v.count / maxCount) * 100);
        const videoUrl = v.url || `https://www.youtube.com/watch?v=${v.video_id}`;

        html += `
            <tr>
                <!-- الترتيب -->
                <td style="width: 50px; text-align: center;">
                    <span class="rank-badge ${rankBadgeClass}">${rank}</span>
                </td>

                <!-- الفيديو -->
                <td>
                    <div style="display:flex; align-items:center; gap:12px; min-width:240px;">
                        <div style="position:relative; width:80px; height:45px; border-radius:var(--radius-sm); overflow:hidden; background:#000; flex-shrink:0; border:1px solid var(--border-subtle);">
                            <img src="${thumbUrl}" alt="Thumbnail" loading="lazy" onerror="this.src='/static/images/favicon.svg'" style="width:100%; height:100%; object-fit:cover;">
                        </div>
                        <div style="min-width:0; flex:1;">
                            <a href="${videoUrl}" target="_blank" rel="noopener noreferrer" style="font-weight:700; color:var(--text-main); text-decoration:none; display:-webkit-box; -webkit-line-clamp:1; -webkit-box-orient:vertical; overflow:hidden; font-size:0.92rem;" title="${escapeHtml(v.title)}">
                                ${escapeHtml(v.title)}
                            </a>
                            <div style="font-size:0.78rem; color:var(--text-muted); display:flex; align-items:center; gap:8px; margin-top:3px;">
                                <span>${escapeHtml(v.channel || 'يوتيوب')}</span>
                                ${v.video_id ? `<code style="font-family:var(--font-mono); color:var(--primary); font-size:0.75rem;">${v.video_id}</code>` : ''}
                            </div>
                        </div>
                    </div>
                </td>

                <!-- عدد مرات الاستخراج والشريط التوضيحي -->
                <td style="min-width: 160px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;">
                        <strong style="font-family:var(--font-mono); color:var(--primary); font-size:1.05rem;">
                            ${v.count.toLocaleString()}
                        </strong>
                        <span style="font-size:0.76rem; color:var(--text-muted); font-family:var(--font-mono);">
                            ${v.percentage_of_total}% من الكل
                        </span>
                    </div>
                    <div class="res-progress-wrap" style="height:6px;">
                        <div class="res-progress-fill cyan" style="width:${percentage}%;"></div>
                    </div>
                </td>

                <!-- التوفير عبر الكاش -->
                <td style="text-align: center;">
                    <span class="comp-badge ${v.cache_hits > 0 ? 'healthy' : 'cyan'}" style="font-family:var(--font-mono); font-size:0.8rem;">
                        ⚡ ${v.cache_hits.toLocaleString()} كاش
                    </span>
                </td>

                <!-- آخر طلب -->
                <td style="font-family:var(--font-mono); font-size:0.82rem; color:var(--text-muted); white-space:nowrap;">
                    ${formatRelativeTime(v.last_extracted_at)}
                </td>

                <!-- إجراءات سريعة -->
                <td style="text-align: left; white-space:nowrap;">
                    <div style="display:flex; gap:6px; justify-content:flex-end;">
                        <button class="btn-action light-primary" style="padding:5px 10px; font-size:0.78rem;" onclick="copyDirectText('${escapeHtml(videoUrl)}', 'تم نسخ رابط الفيديو')" title="نسخ رابط الفيديو">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
                            <span>نسخ</span>
                        </button>
                        <button class="btn-action primary" style="padding:5px 12px; font-size:0.78rem;" onclick="handleQuickExtractVideo('${escapeHtml(videoUrl)}')" title="استخراج الروابط المباشرة الآن في صفحة المستخرج">
                            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
                            <span>استخراج</span>
                        </button>
                    </div>
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = html;
}

/* ==================== RECENT EXTRACTIONS TABLE ==================== */
function renderRecentExtractionsTable(extractions) {
    const tbody = document.getElementById('recentExtractionsTableBody');
    if (!tbody) return;

    if (!extractions || extractions.length === 0) {
        tbody.innerHTML = `
            <tr>
                <td colspan="6" style="text-align:center; padding:30px; color:var(--text-muted);">
                    لا توجد عمليات استخراج حديثة مسجلة بعد.
                </td>
            </tr>
        `;
        return;
    }

    let html = '';
    extractions.forEach(item => {
        let badgeHtml = '';
        if (item.status === 'failed') {
            badgeHtml = `<span class="comp-badge critical" title="${escapeHtml(item.error_message || 'فشل')}">❌ فشل</span>`;
        } else if (item.is_cached) {
            badgeHtml = `<span class="comp-badge healthy" title="تم تقديمه من ذاكرة الـ TTLCache فورياً">⚡ كاش Hit</span>`;
        } else {
            badgeHtml = `<span class="comp-badge cyan" title="استخراج فريش جديد من يوتيوب">✓ مباشر</span>`;
        }

        const thumb = item.thumbnail || (item.video_id ? `https://i.ytimg.com/vi/${item.video_id}/default.jpg` : '');
        const timeMs = item.response_time_ms < 1000 ? `${item.response_time_ms}ms` : `${(item.response_time_ms / 1000).toFixed(2)}s`;

        html += `
            <tr>
                <!-- الحالة -->
                <td style="width: 100px; text-align: center;">${badgeHtml}</td>

                <!-- الفيديو والرابط -->
                <td>
                    <div style="display:flex; align-items:center; gap:10px;">
                        ${thumb ? `<img src="${thumb}" alt="" onerror="this.style.display='none'" style="width:40px; height:24px; border-radius:4px; object-fit:cover; background:#000;">` : ''}
                        <div style="min-width:0;">
                            <a href="${item.url}" target="_blank" rel="noopener noreferrer" style="font-weight:600; font-size:0.86rem; color:var(--text-main); text-decoration:none; display:-webkit-box; -webkit-line-clamp:1; -webkit-box-orient:vertical; overflow:hidden;" title="${escapeHtml(item.title)}">
                                ${escapeHtml(item.title)}
                            </a>
                            <div style="font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono); overflow:hidden; text-overflow:ellipsis; white-space:nowrap; max-width:320px;">
                                ${escapeHtml(item.url)}
                            </div>
                        </div>
                    </div>
                </td>

                <!-- المنصة / الدومين الطالب -->
                <td>
                    <span style="font-size:0.82rem; color:var(--text-main); font-family:var(--font-mono); background:var(--bg-surface); padding:3px 8px; border-radius:var(--radius-sm); border:1px solid var(--border-subtle);">
                        ${escapeHtml(item.referer || 'Direct API')}
                    </span>
                </td>

                <!-- زمن المعالجة -->
                <td style="font-family:var(--font-mono); font-size:0.84rem; color:var(--primary); font-weight:600;">
                    ${timeMs}
                </td>

                <!-- الآي بي -->
                <td style="font-family:var(--font-mono); font-size:0.8rem; color:var(--text-muted);">
                    ${escapeHtml(item.client_ip || '--')}
                </td>

                <!-- التوقيت -->
                <td style="font-family:var(--font-mono); font-size:0.8rem; color:var(--text-muted); white-space:nowrap;">
                    ${escapeHtml(item.created_at)}
                </td>
            </tr>
        `;
    });

    tbody.innerHTML = html;
}

/* ==================== TOP REFERRERS / DOMAINS BREAKDOWN ==================== */
function renderTopReferrers(referrers, totalExtractions) {
    const container = document.getElementById('topReferrersContainer');
    if (!container) return;

    if (!referrers || referrers.length === 0) {
        container.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; padding:12px;">لا توجد مصادر مسجلة بعد.</div>`;
        return;
    }

    const maxCount = referrers[0]?.count || 1;
    let html = '';

    referrers.forEach(ref => {
        const pct = Math.round((ref.count / maxCount) * 100);
        const shareOfTotal = totalExtractions > 0 ? Math.round((ref.count / totalExtractions) * 100) : 0;

        html += `
            <div style="margin-bottom:14px;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:5px;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--primary);"><circle cx="12" cy="12" r="10"></circle><line x1="2" y1="12" x2="22" y2="12"></line><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"></path></svg>
                        <span style="font-family:var(--font-mono); font-size:0.88rem; font-weight:700; color:var(--text-main);">${escapeHtml(ref.domain)}</span>
                    </div>
                    <div style="font-family:var(--font-mono); font-size:0.84rem; color:var(--text-muted);">
                        <strong style="color:var(--primary);">${ref.count.toLocaleString()}</strong> طلب (${shareOfTotal}%)
                    </div>
                </div>
                <div class="res-progress-wrap" style="height:6px;">
                    <div class="res-progress-fill purple" style="width:${pct}%;"></div>
                </div>
            </div>
        `;
    });

    container.innerHTML = html;
}

/* ==================== CANVAS ACTIVITY CHART ==================== */
function renderAnalyticsChart(data) {
    const canvas = document.getElementById('analyticsTrendCanvas');
    if (!canvas) return;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;
    const isDark = document.documentElement.getAttribute('data-theme') !== 'light';

    ctx.clearRect(0, 0, w, h);

    const padTop = 20;
    const padBottom = 30;
    const padLeft = 45;
    const padRight = 20;
    const plotW = w - padLeft - padRight;
    const plotH = h - padTop - padBottom;

    // تجهيز البيانات بحسب الوضع
    let chartPoints = [];
    if (currentChartMode === 'daily') {
        const trends = data?.daily_trends || [];
        if (trends.length === 0) {
            // بيانات افتراضية فارغة إذا لم تتوفر بعد
            const todayStr = new Date().toISOString().substring(5, 10);
            chartPoints = [{ label: todayStr, total: 0, cached: 0 }];
        } else {
            chartPoints = trends.map(t => ({
                label: t.date ? t.date.substring(5) : '',
                total: t.total || 0,
                cached: t.cached || 0
            }));
        }
    }

    if (chartPoints.length < 2) {
        // إضافة نقاط فارغة للحفاظ على جمالية المخطط
        const curLabel = chartPoints[0]?.label || 'اليوم';
        chartPoints = [
            { label: 'سابقاً', total: 0, cached: 0 },
            { label: curLabel, total: chartPoints[0]?.total || 0, cached: chartPoints[0]?.cached || 0 }
        ];
    }

    // حساب الحد الأقصى للمحور الرأسي
    const maxVal = Math.max(5, ...chartPoints.map(p => p.total));
    const niceMax = Math.ceil(maxVal * 1.25);

    // 1. رسم خطوط الشبكة
    const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
    const textColor = isDark ? '#94a3b8' : '#64748b';

    ctx.font = '11px JetBrains Mono, monospace';
    ctx.fillStyle = textColor;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';

    const steps = 4;
    for (let i = 0; i <= steps; i++) {
        const val = Math.round((niceMax / steps) * i);
        const y = padTop + plotH - (val / niceMax) * plotH;

        ctx.beginPath();
        ctx.strokeStyle = gridColor;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.moveTo(padLeft, y);
        ctx.lineTo(w - padRight, y);
        ctx.stroke();
        ctx.setLineDash([]);

        ctx.fillText(val.toString(), padLeft - 8, y);
    }

    // 2. حساب إحداثيات النقاط
    const stepX = plotW / (chartPoints.length - 1);
    const coords = chartPoints.map((pt, idx) => {
        const x = padLeft + idx * stepX;
        const y = padTop + plotH - (pt.total / niceMax) * plotH;
        return { x, y, ...pt };
    });

    // 3. مساحة متدرجة
    const grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
    grad.addColorStop(0, 'rgba(93, 135, 255, 0.35)');
    grad.addColorStop(1, 'rgba(93, 135, 255, 0.0)');

    ctx.beginPath();
    ctx.moveTo(coords[0].x, padTop + plotH);
    ctx.lineTo(coords[0].x, coords[0].y);

    for (let i = 0; i < coords.length - 1; i++) {
        const cpX = (coords[i].x + coords[i + 1].x) / 2;
        ctx.bezierCurveTo(cpX, coords[i].y, cpX, coords[i + 1].y, coords[i + 1].x, coords[i + 1].y);
    }

    ctx.lineTo(coords[coords.length - 1].x, padTop + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // 4. خط المنحنى
    ctx.beginPath();
    ctx.moveTo(coords[0].x, coords[0].y);

    for (let i = 0; i < coords.length - 1; i++) {
        const cpX = (coords[i].x + coords[i + 1].x) / 2;
        ctx.bezierCurveTo(cpX, coords[i].y, cpX, coords[i + 1].y, coords[i + 1].x, coords[i + 1].y);
    }

    ctx.strokeStyle = '#5D87FF';
    ctx.lineWidth = 2.8;
    ctx.stroke();

    // 5. رسم نقاط البيانات مع التسميات
    coords.forEach(pt => {
        // نقطة دائرية
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = '#5D87FF';
        ctx.fill();

        ctx.beginPath();
        ctx.arc(pt.x, pt.y, 2, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();

        // التسمية على المحور السيني
        ctx.fillStyle = textColor;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.fillText(pt.label, pt.x, padTop + plotH + 8);
    });
}

function setAnalyticsChartMode(mode) {
    currentChartMode = mode;
    document.querySelectorAll('.btn-chart-mode').forEach(b => {
        b.classList.remove('active');
        if (b.getAttribute('data-mode') === mode) b.classList.add('active');
    });
    if (analyticsDataCache) {
        renderAnalyticsChart(analyticsDataCache);
    }
}

/* ==================== ACTION HANDLERS ==================== */
function handleQuickExtractVideo(url) {
    if (!url) return;
    if (window.switchNavTab) {
        switchNavTab('tab-extractor', 'مستخرج الروابط الذكي والبث المقسم');
    }
    const input = document.getElementById('extractUrlInput');
    if (input) {
        input.value = url;
    }
    setTimeout(() => {
        if (window.handleExtractVideo) {
            window.handleExtractVideo();
        }
    }, 200);
}

function copyDirectText(text, message = 'تم النسخ بنجاح') {
    if (!text) return;
    navigator.clipboard.writeText(text).then(() => {
        showToast(message);
    }).catch(() => {
        const temp = document.createElement('textarea');
        temp.value = text;
        document.body.appendChild(temp);
        temp.select();
        document.execCommand('copy');
        document.body.removeChild(temp);
        showToast(message);
    });
}

async function handleClearAllStatsConfirm() {
    if (!confirm('هل أنت متأكد من رغبتك في تصفير ومسح كافة إحصائيات وسجلات الاستخراج؟ لا يمكن التراجع عن هذا الإجراء.')) {
        return;
    }

    try {
        const res = await apiFetch('/api/stats/clear', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
            showToast('تم تصفير كافة إحصائيات الاستخراج بنجاح.');
            loadAnalyticsData(false);
            if (window.loadOverview) loadOverview();
        } else {
            showToast(data.detail || 'فشل مسح الإحصائيات.', 'error');
        }
    } catch (e) {
        showToast('تعذر الاتصال بالخادم.', 'error');
    }
}

function startAnalyticsAutoRefresh() {
    if (analyticsAutoRefreshTimer) clearInterval(analyticsAutoRefreshTimer);
    analyticsAutoRefreshTimer = setInterval(() => {
        const activeTab = document.querySelector('.tab-panel.active');
        if (activeTab && activeTab.id === 'tab-analytics') {
            loadAnalyticsData(true);
        }
    }, 8000);
}

function stopAnalyticsAutoRefresh() {
    if (analyticsAutoRefreshTimer) {
        clearInterval(analyticsAutoRefreshTimer);
        analyticsAutoRefreshTimer = null;
    }
}

/* Helper Utilities */
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function formatRelativeTime(dateStr) {
    if (!dateStr) return '--';
    try {
        const date = new Date(dateStr.replace(' ', 'T'));
        const now = new Date();
        const diffSec = Math.floor((now - date) / 1000);

        if (diffSec < 60) return 'منذ لحظات';
        if (diffSec < 3600) return `منذ ${Math.floor(diffSec / 60)} دقيقة`;
        if (diffSec < 86400) return `منذ ${Math.floor(diffSec / 3600)} ساعة`;
        return dateStr.substring(5, 16);
    } catch (e) {
        return dateStr;
    }
}

window.addEventListener('resize', () => {
    if (analyticsDataCache) {
        renderAnalyticsChart(analyticsDataCache);
    }
});

// Export to window
window.loadAnalyticsData = loadAnalyticsData;
window.handleQuickExtractVideo = handleQuickExtractVideo;
window.copyDirectText = copyDirectText;
window.handleClearAllStatsConfirm = handleClearAllStatsConfirm;
window.setAnalyticsChartMode = setAnalyticsChartMode;
window.startAnalyticsAutoRefresh = startAnalyticsAutoRefresh;
window.stopAnalyticsAutoRefresh = stopAnalyticsAutoRefresh;

// بدء التحديث التلقائي
startAnalyticsAutoRefresh();
