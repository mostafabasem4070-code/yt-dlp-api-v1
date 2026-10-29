/* ==========================================================================
   COOKIE HUB & VALIDITY EXPIRATION MANAGEMENT
   YouTube API Hub - Cloud Control Center
   ========================================================================== */

async function loadCookieStatus() {
    try {
        const res = await apiFetch('/api/cookies/status');
        if (!res.ok) return;
        const data = await res.json();

        // تحديث الشارات في الشريط العلوي والجانبي
        const countBadge = document.getElementById('cookieCountBadge');
        const sideBadge = document.getElementById('sideCookieBadge');
        if (countBadge) countBadge.textContent = `${data.total_cookies || 0} كوكي`;
        if (sideBadge) sideBadge.textContent = `${data.total_cookies || 0} كوكي`;

        // مسار الملف
        const pathEl = document.getElementById('cookiePathLabel');
        if (pathEl) pathEl.textContent = data.file_path || 'غير محدد';

        // كارت مدة الصلاحية والعد التنازلي الجديد (NEW EXPIRATION HERO CARD!)
        renderCookieExpirationCard(data);

        // جدول الكوكيز التفصيلي
        renderCookiesTable(data.items || []);

    } catch (err) {
        console.error('Failed to load cookie status:', err);
    }
}

function renderCookieExpirationCard(data) {
    const heroCard = document.getElementById('cookieExpiryHeroCard');
    if (!heroCard) return;

    const isAuth = data.has_auth;
    const isExpired = data.is_expired;
    const urgency = data.urgency || 'guest';
    const countdown = data.expiry_countdown || data.expiry_human || 'غير محدد';
    const readableDate = data.earliest_expiry_readable || 'غير متوفرة (جلسة مؤقتة)';

    let badgeText = 'صالحة ومسجلة';
    let badgeClass = 'healthy';
    let iconColor = 'var(--success)';

    if (isExpired) {
        badgeText = 'منتهية الصلاحية';
        badgeClass = 'critical';
        iconColor = 'var(--danger)';
    } else if (urgency === 'critical') {
        badgeText = 'قاربت على الانتهاء عاجلاً';
        badgeClass = 'critical';
        iconColor = 'var(--danger)';
    } else if (urgency === 'warning') {
        badgeText = 'تنتهي قريباً';
        badgeClass = 'warning';
        iconColor = 'var(--warning)';
    } else if (!isAuth) {
        badgeText = 'وضع الزائر (Guest)';
        badgeClass = 'cyan';
        iconColor = 'var(--accent-cyan)';
    }

    heroCard.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:16px;">
            <div style="display:flex; align-items:center; gap:16px;">
                <div style="width:56px; height:56px; border-radius:var(--radius-md); background:rgba(16,185,129,0.12); display:flex; align-items:center; justify-content:center; color:${iconColor}; flex-shrink:0;">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12 6 12 12 14 14"></polyline>
                    </svg>
                </div>
                <div>
                    <div style="font-size:0.82rem; color:var(--text-muted); font-weight:700;">مدة صلاحية الكوكيز المتبقية (Session Validity)</div>
                    <div style="font-size:1.6rem; font-weight:900; color:var(--text-main); font-family:var(--font-mono); margin-top:4px;">
                        ${countdown}
                    </div>
                    <div style="font-size:0.82rem; color:var(--text-muted); margin-top:4px;">
                        تاريخ ووقت الانتهاء: <strong style="color:var(--text-main); font-family:var(--font-mono);">${readableDate}</strong>
                    </div>
                </div>
            </div>
            <div style="display:flex; flex-direction:column; align-items:flex-end; gap:8px;">
                <span class="comp-badge ${badgeClass}" style="font-size:0.85rem; padding:6px 14px;">${badgeText}</span>
                <span style="font-size:0.78rem; color:var(--text-muted); font-family:var(--font-mono);">
                    حجم الملف: ${((data.file_size_bytes || 0) / 1024).toFixed(1)} KB • عدد الكوكيز: ${data.total_cookies || 0}
                </span>
            </div>
        </div>
    `;
}

function renderCookiesTable(items) {
    const tableBody = document.getElementById('cookiesTableBody');
    if (!tableBody) return;
    tableBody.innerHTML = '';

    if (!items || items.length === 0) {
        tableBody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:24px; color:var(--text-muted);">لا توجد كوكيز مسجلة حالياً.</td></tr>';
        return;
    }

    items.forEach(c => {
        const tr = document.createElement('tr');
        
        let statusBadge = '<span class="comp-badge healthy">نشط</span>';
        if (c.status === 'expired') {
            statusBadge = '<span class="comp-badge critical">منتهي</span>';
        } else if (c.status === 'session') {
            statusBadge = '<span class="comp-badge cyan">جلسة متصفح</span>';
        }

        const typeBadge = c.is_auth 
            ? '<span class="comp-badge healthy" style="font-family:var(--font-mono);">Auth (مصادقة)</span>'
            : `<span style="font-size:0.78rem; color:var(--text-muted);">${c.category || 'عام'}</span>`;

        tr.innerHTML = `
            <td><strong style="color:var(--text-main); font-family:var(--font-mono);">${c.name}</strong></td>
            <td>${typeBadge}</td>
            <td style="font-family:var(--font-mono); font-size:0.82rem; color:var(--text-muted);">${c.domain}</td>
            <td style="font-family:var(--font-mono); font-size:0.82rem;">${c.expiration_readable}</td>
            <td style="font-family:var(--font-mono); font-size:0.85rem; font-weight:700;">${c.remaining_human || '--'}</td>
            <td>${statusBadge}</td>
        `;
        tableBody.appendChild(tr);
    });
}

async function handleSaveCookies() {
    const input = document.getElementById('cookiesTextInput');
    const text = input.value.trim();
    const testImm = document.getElementById('testImmediatelyCheck')?.checked || false;
    const btn = document.getElementById('btnSaveCookies');

    if (!text) {
        showToast('يرجى لصق نص الكوكيز أولاً.', 'error');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span>جاري المعالجة والفحص...</span>';

    try {
        const res = await apiFetch('/api/cookies/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cookies_text: text, test_immediately: testImm })
        });
        const data = await res.json();

        if (res.ok && data.status === 'success') {
            showToast(data.message);
            input.value = '';
            loadCookieStatus();
            if (window.loadOverview) loadOverview();

            if (data.test_result) {
                if (data.test_result.success) {
                    showToast(`نجح فحص الكوكيز الحي! زمن الاستجابة: ${data.test_result.elapsed_seconds} ثانية`);
                } else {
                    showToast(`تنبيه فحص الكوكيز: ${data.test_result.error || 'غير صالحة'}`, 'warning');
                }
            }
        } else {
            showToast(data.detail || 'فشل حفظ وتحديث الكوكيز.', 'error');
        }
    } catch (e) {
        showToast('تعذر الاتصال بالخادم.', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = `
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>
            <span>حفظ وتفعيل الكوكيز فوراً</span>
        `;
    }
}

async function clearCookiesConfirm() {
    if (!confirm('هل تريد بالتأكيد تفريغ ملف الكوكيز والعودة لوضع الزائر (Guest Mode)؟')) return;

    try {
        const res = await apiFetch('/api/cookies', { method: 'DELETE' });
        const data = await res.json();
        if (res.ok) {
            showToast(data.message || 'تم تفريغ الكوكيز.');
            loadCookieStatus();
            if (window.loadOverview) loadOverview();
        } else {
            showToast(data.detail || 'فشل مسح الكوكيز.', 'error');
        }
    } catch (e) {
        showToast('تعذر الاتصال بالخادم.', 'error');
    }
}

window.loadCookieStatus = loadCookieStatus;
window.handleSaveCookies = handleSaveCookies;
window.clearCookiesConfirm = clearCookiesConfirm;
