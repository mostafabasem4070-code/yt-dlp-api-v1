/* ==========================================================================
   GOOGLE AUTH & INTERACTIVE REMOTE BROWSER CONTROLLER
   YouTube API Hub - Cloud Control Center
   ========================================================================== */

let _remoteStreamTimer = null;
let _isActionPending = false;

// ===== التحقق من حالة Playwright وخدمة المصادقة =====
async function loadGoogleAuthStatus() {
    try {
        const res = await apiFetch('/api/auth/google/status');
        if (!res.ok) return;
        const data = await res.json();
        renderGoogleAuthPanel(data);

        // إذا كانت هناك جلسة نشطة بالفعل في الخلفية، نفتح نافذة المتصفح ونستأنف البث
        const status = data.session ? data.session.status : 'idle';
        if (['running', 'waiting_login', 'extracting'].includes(status)) {
            openRemoteBrowserModal();
            startRemoteBrowserStream();
        }
    } catch (err) {
        console.error('Failed to load Google Auth status:', err);
    }
}

function renderGoogleAuthPanel(data) {
    const panel = document.getElementById('googleAuthStatusPanel');
    if (!panel) return;

    const session = data.session || {};
    const playwrightOk = data.playwright_installed;
    const status = session.status || 'idle';

    const statusMap = {
        idle:          { label: 'جاهز للبدء',            color: 'var(--text-muted)',    icon: '⏳' },
        running:       { label: 'يُشغّل المتصفح...',     color: 'var(--warning)',       icon: '🔄' },
        waiting_login: { label: 'في انتظار تسجيل الدخول', color: 'var(--accent-cyan)', icon: '🔐' },
        extracting:    { label: 'يستخرج الكوكيز...',     color: 'var(--accent-purple)', icon: '📦' },
        done:          { label: 'تم بنجاح!',              color: 'var(--success)',       icon: '✅' },
        error:         { label: 'خطأ',                    color: 'var(--danger)',        icon: '❌' },
        timeout:       { label: 'انتهت المهلة',           color: 'var(--warning)',       icon: '⌛' },
    };

    const s = statusMap[status] || statusMap['idle'];
    const isActive = ['running', 'waiting_login', 'extracting'].includes(status);
    const isDone = status === 'done';
    const isError = ['error', 'timeout'].includes(status);

    panel.innerHTML = `
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px;">
            <span style="font-size:1.4rem;">${s.icon}</span>
            <div>
                <div style="font-size:0.88rem; font-weight:700; color:${s.color};">${s.label}</div>
                <div style="font-size:0.82rem; color:var(--text-muted); margin-top:2px;">${session.message || ''}</div>
            </div>
            ${isActive ? `<div class="spinner" style="margin-right:auto;"></div>` : ''}
        </div>

        ${isDone ? `
        <div style="background:rgba(16,185,129,0.12); border:1px solid rgba(16,185,129,0.3); border-radius:8px; padding:12px; margin-bottom:12px; font-size:0.85rem; color:var(--success);">
            <strong>✅ تم استخراج وحفظ الكوكيز بنجاح!</strong><br>
            عدد الكوكيز المحفوظة: <strong>${session.cookies_count}</strong> كوكي (تعمل من نفس عنوان IP الخادم لتجنب الحظر).
        </div>
        ` : ''}

        ${isError ? `
        <div style="background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); border-radius:8px; padding:10px; margin-bottom:12px; font-size:0.82rem; color:var(--danger);">
            ${session.error || 'حدث خطأ غير متوقع أثناء تشغيل المتصفح'}
        </div>
        ` : ''}

        ${!playwrightOk ? `
        <div style="background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.3); border-radius:8px; padding:10px; margin-bottom:12px; font-size:0.82rem; color:var(--warning);">
            ⚠️ مكتبة Playwright غير مثبتة. شغّل على السيرفر:<br>
            <code style="font-family:var(--font-mono); font-size:0.78rem; display:block; margin-top:6px; background:rgba(0,0,0,0.3); padding:6px; border-radius:4px;">pip install playwright && playwright install chromium</code>
        </div>
        ` : ''}

        <div style="display:flex; gap:10px; flex-wrap:wrap; align-items:center;">
            ${!isActive ? `
            <button id="btnGoogleLogin" class="btn-action primary" onclick="startGoogleLogin()" ${!playwrightOk ? 'disabled' : ''} style="padding:10px 18px; font-weight:700;">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none"><path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/><path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/><path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/><path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/></svg>
                <span>فتح متصفح تسجيل الدخول التفاعلي</span>
            </button>
            ` : `
            <button class="btn-action primary" onclick="openRemoteBrowserModal()" style="padding:8px 16px;">
                🖥️ <span>عرض نافذة المتصفح المباشرة</span>
            </button>
            <button class="btn-action danger" onclick="cancelGoogleLogin()" style="padding:8px 16px;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                <span>إلغاء الجلسة</span>
            </button>
            `}
            ${isDone ? `
            <button class="btn-action cyan" onclick="loadCookieStatus(); loadGoogleAuthStatus();" style="padding:8px 16px;">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>
                <span>فحص وتحديث الكوكيز</span>
            </button>
            ` : ''}
        </div>
    `;
}

// ===== بدء الجلسة وفتح النافذة التفاعلية =====
async function startGoogleLogin() {
    const btn = document.getElementById('btnGoogleLogin');
    if (btn) btn.disabled = true;

    try {
        showToast('جاري تشغيل المتصفح على السيرفر...', 'info');

        const res = await apiFetch('/api/auth/google/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ timeout_minutes: 15, headless: null })
        });
        const data = await res.json();

        if (res.ok && data.success) {
            openRemoteBrowserModal();
            startRemoteBrowserStream();
            showToast('تم فتح المتصفح. يمكنك تسجيل الدخول الآن عبر النافذة.', 'success');
        } else {
            showToast(data.message || 'فشل بدء الجلسة', 'error');
            loadGoogleAuthStatus();
        }
    } catch (e) {
        showToast('تعذر الاتصال بالخادم', 'error');
        if (btn) btn.disabled = false;
    }
}

// ===== إدارة نافذة المتصفح التفاعلية (Modal) =====
function openRemoteBrowserModal() {
    const modal = document.getElementById('remoteBrowserModal');
    if (modal) {
        modal.style.display = 'flex';
        setBrowserSpinner(true, 'جاري تحميل شاشة المتصفح...');
        setTimeout(() => {
            const input = document.getElementById('browserTypeInput');
            if (input) input.focus();
        }, 400);
    }
}

function closeRemoteBrowserModal() {
    const modal = document.getElementById('remoteBrowserModal');
    if (modal) modal.style.display = 'none';
    stopRemoteBrowserStream();
    cancelGoogleLogin();
}

function setBrowserSpinner(visible, text = 'جاري المعالجة...') {
    const sp = document.getElementById('remoteBrowserSpinner');
    if (sp) {
        sp.style.display = visible ? 'flex' : 'none';
        const span = sp.querySelector('span');
        if (span) span.textContent = text;
    }
}

// ===== نظام البث الحي وتحديث لقطة الشاشة =====
function startRemoteBrowserStream() {
    stopRemoteBrowserStream();
    // التقاط فوري
    fetchRemoteScreenshot();
    // تكرار البث كل 900 ملي ثانية
    _remoteStreamTimer = setInterval(fetchRemoteScreenshot, 900);
}

function stopRemoteBrowserStream() {
    if (_remoteStreamTimer) {
        clearInterval(_remoteStreamTimer);
        _remoteStreamTimer = null;
    }
}

async function fetchRemoteScreenshot() {
    if (_isActionPending) return;

    try {
        const res = await apiFetch('/api/auth/google/screenshot');
        if (!res.ok) return;
        const data = await res.json();

        if (!data.success) {
            if (data.status === 'done') {
                handleLoginSuccessful();
                return;
            }
            return;
        }

        updateRemoteBrowserView(data);

        // التحقق من حالة الجلسة
        if (data.status === 'done') {
            handleLoginSuccessful();
        }
    } catch (e) {
        console.debug('Screenshot fetch error:', e);
    }
}

function updateRemoteBrowserView(data) {
    const img = document.getElementById('remoteBrowserImg');
    if (img && data.image) {
        img.src = data.image;
        setBrowserSpinner(false);
    }

    const urlBar = document.getElementById('remoteBrowserUrlBar');
    if (urlBar && data.url) {
        urlBar.textContent = data.url;
        urlBar.title = data.url;
    }

    const statusBadge = document.getElementById('remoteBrowserStatusBadge');
    if (statusBadge && data.status) {
        const map = {
            waiting_login: 'بانتظار تسجيل الدخول 🔐',
            extracting: 'جاري استخراج الكوكيز... 📦',
            running: 'المتصفح يعمل 🔄',
            done: 'تم تسجيل الدخول بنجاح! ✅'
        };
        statusBadge.textContent = map[data.status] || data.status;
    }

    const countdown = document.getElementById('remoteBrowserCountdown');
    if (countdown && data.message) {
        countdown.textContent = data.message;
    }
}

function handleLoginSuccessful() {
    stopRemoteBrowserStream();
    setBrowserSpinner(false);
    showToast('🎉 تم تسجيل الدخول واستخراج الكوكيز وحفظها بنجاح!', 'success');

    const statusBadge = document.getElementById('remoteBrowserStatusBadge');
    if (statusBadge) {
        statusBadge.textContent = 'تم استخراج الكوكيز بنجاح! ✅';
        statusBadge.className = 'comp-badge green';
    }

    // إغلاق النافذة تلقائياً بعد ثانيتين وتحديث حالة الكوكيز
    setTimeout(() => {
        const modal = document.getElementById('remoteBrowserModal');
        if (modal) modal.style.display = 'none';
        if (window.loadCookieStatus) loadCookieStatus();
        loadGoogleAuthStatus();
    }, 2000);
}

// ===== النقر والتفاعل بالماوس =====
async function handleBrowserScreenClick(e) {
    const img = document.getElementById('remoteBrowserImg');
    if (!img) return;

    const rect = img.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    // حساب الإحداثيات بالنسبة لحجم الصفحة الافتراضي (1280x800)
    const scaleX = 1280 / rect.width;
    const scaleY = 800 / rect.height;
    const x = Math.round((e.clientX - rect.left) * scaleX);
    const y = Math.round((e.clientY - rect.top) * scaleY);

    _isActionPending = true;
    setBrowserSpinner(true, 'جاري النقر...');

    try {
        const res = await apiFetch('/api/auth/google/click', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ x, y })
        });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
        }
    } catch (err) {
        console.error('Click error:', err);
    } finally {
        _isActionPending = false;
        setBrowserSpinner(false);
    }
}

// ===== الكتابة وإرسال المفاتيح =====
async function sendBrowserTypedText(pressEnter = false) {
    const input = document.getElementById('browserTypeInput');
    if (!input) return;
    const text = input.value;
    if (!text && !pressEnter) return;

    _isActionPending = true;
    setBrowserSpinner(true, 'جاري الكتابة...');

    try {
        const res = await apiFetch('/api/auth/google/type', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, enter: pressEnter })
        });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
            input.value = '';
        }
    } catch (err) {
        console.error('Type error:', err);
    } finally {
        _isActionPending = false;
        setBrowserSpinner(false);
    }
}

async function sendBrowserKey(key) {
    _isActionPending = true;
    setBrowserSpinner(true, `ضغط ${key}...`);

    try {
        const res = await apiFetch('/api/auth/google/key', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ key })
        });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
        }
    } catch (err) {
        console.error('Key error:', err);
    } finally {
        _isActionPending = false;
        setBrowserSpinner(false);
    }
}

async function reloadRemoteBrowser() {
    _isActionPending = true;
    setBrowserSpinner(true, 'إعادة تحميل الصفحة...');

    try {
        const res = await apiFetch('/api/auth/google/reload', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
        }
    } catch (err) {
        console.error('Reload error:', err);
    } finally {
        _isActionPending = false;
        setBrowserSpinner(false);
    }
}

// ===== استخراج الكوكيز فورياً يدوياً =====
async function extractCookiesNow() {
    setBrowserSpinner(true, 'جاري استخراج وحفظ الكوكيز الآن...');
    try {
        const res = await apiFetch('/api/auth/google/extract', { method: 'POST' });
        const data = await res.json();
        if (res.ok && data.success) {
            handleLoginSuccessful();
        } else {
            showToast(data.message || 'لم تكتمل الجلسة بعد أو لم تتوفر كوكيز', 'warning');
            setBrowserSpinner(false);
        }
    } catch (err) {
        showToast('تعذر استخراج الكوكيز', 'error');
        setBrowserSpinner(false);
    }
}

// ===== إلغاء الجلسة =====
async function cancelGoogleLogin() {
    try {
        const res = await apiFetch('/api/auth/google/cancel', { method: 'POST' });
        const data = await res.json();
        showToast(data.message || 'تم الإلغاء', 'warning');
        stopRemoteBrowserStream();
        loadGoogleAuthStatus();
    } catch (e) {
        console.error('Cancel error:', e);
    }
}

async function navigateRemoteBrowser(url) {
    _isActionPending = true;
    setBrowserSpinner(true, 'جاري الانتقال للرابط...');

    try {
        const res = await apiFetch('/api/auth/google/navigate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
        }
    } catch (err) {
        console.error('Navigate error:', err);
    } finally {
        _isActionPending = false;
        setBrowserSpinner(false);
    }
}

// تصدير الدوال للنطاق العام
window.loadGoogleAuthStatus = loadGoogleAuthStatus;
window.startGoogleLogin = startGoogleLogin;
window.cancelGoogleLogin = cancelGoogleLogin;
window.openRemoteBrowserModal = openRemoteBrowserModal;
window.closeRemoteBrowserModal = closeRemoteBrowserModal;
window.handleBrowserScreenClick = handleBrowserScreenClick;
window.sendBrowserTypedText = sendBrowserTypedText;
window.sendBrowserKey = sendBrowserKey;
window.reloadRemoteBrowser = reloadRemoteBrowser;
window.navigateRemoteBrowser = navigateRemoteBrowser;
window.extractCookiesNow = extractCookiesNow;
