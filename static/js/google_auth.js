/* ==========================================================================
   GOOGLE AUTH & INTERACTIVE REMOTE BROWSER CONTROLLER (ENHANCED UX)
   YouTube API Hub - Cloud Control Center
   ========================================================================== */

let _remoteStreamTimer = null;
let _isActionPending = false;
let _isScreenshotFetching = false;
let _isBrowserFullscreen = false;
let _directTypeBuffer = '';
let _directTypeFlushTimer = null;
let _wheelThrottleTimer = null;
let _pendingWheelDeltaY = 0;

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
            showToast('تم فتح المتصفح. يمكنك التحكم المباشر بالماوس والكيبورد الآن!', 'success');
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
        const img = document.getElementById('remoteBrowserImg');
        if (!img || !img.getAttribute('src')) {
            setBrowserSpinner(true, 'جاري تحميل شاشة المتصفح...');
        }
        bindDirectBrowserEvents();
        setTimeout(() => {
            const input = document.getElementById('browserTypeInput');
            if (input) input.focus();
        }, 300);
    }
}

function closeRemoteBrowserModal() {
    const modal = document.getElementById('remoteBrowserModal');
    if (modal) modal.style.display = 'none';
    stopRemoteBrowserStream();
    cancelGoogleLogin();
}

function toggleRemoteBrowserFullscreen() {
    const container = document.getElementById('remoteBrowserContainer');
    const wrapper = document.getElementById('remoteBrowserScreenWrapper');
    const btn = document.getElementById('btnToggleBrowserFullscreen');
    if (!container || !wrapper) return;

    _isBrowserFullscreen = !_isBrowserFullscreen;
    if (_isBrowserFullscreen) {
        container.style.maxWidth = '98vw';
        container.style.maxHeight = '98vh';
        wrapper.style.maxHeight = '78vh';
        if (btn) btn.innerHTML = '🗗 <span>تصغير</span>';
    } else {
        container.style.maxWidth = '1180px';
        container.style.maxHeight = '96vh';
        wrapper.style.maxHeight = '66vh';
        if (btn) btn.innerHTML = '⛶ <span>تكبير</span>';
    }
}

function setBrowserSpinner(visible, text = 'جاري المعالجة...') {
    const sp = document.getElementById('remoteBrowserSpinner');
    if (sp) {
        sp.style.display = visible ? 'flex' : 'none';
        const span = sp.querySelector('span');
        if (span) span.textContent = text;
    }
}

function setBrowserActionBusy(busy, text = '⚡ جاري التنفيذ...') {
    const ind = document.getElementById('remoteBrowserActionIndicator');
    if (!ind) return;
    if (busy) {
        ind.textContent = text;
        ind.style.display = 'inline-block';
    } else {
        ind.style.display = 'none';
    }
}

// ===== نظام البث الحي السريع وتحديث لقطة الشاشة =====
function startRemoteBrowserStream() {
    stopRemoteBrowserStream();
    fetchRemoteScreenshot();
    // بث سلس كل 500 ملي ثانية مع منع تداخل الطلبات
    _remoteStreamTimer = setInterval(fetchRemoteScreenshot, 500);
}

function stopRemoteBrowserStream() {
    if (_remoteStreamTimer) {
        clearInterval(_remoteStreamTimer);
        _remoteStreamTimer = null;
    }
}

async function fetchRemoteScreenshot() {
    if (_isActionPending || _isScreenshotFetching) return;
    _isScreenshotFetching = true;

    try {
        const res = await apiFetch('/api/auth/google/screenshot');
        if (!res.ok) return;
        const data = await res.json();

        if (!data.success) {
            if (data.status === 'done') {
                handleLoginSuccessful();
                return;
            }
            if (data.status === 'error' || data.status === 'timeout') {
                stopRemoteBrowserStream();
                const errMsg = data.error || data.message || 'حدث خطأ أثناء تشغيل المتصفح.';
                setBrowserSpinner(true, `❌ ${errMsg}`);
                if (typeof showToast === 'function') showToast(errMsg, 'error');
                loadGoogleAuthStatus();
                return;
            }
            if (data.message && (data.status === 'running' || data.status === 'waiting_login')) {
                setBrowserSpinner(true, data.message);
            }
            return;
        }

        updateRemoteBrowserView(data);

        if (data.status === 'done') {
            handleLoginSuccessful();
        }
    } catch (e) {
        console.debug('Screenshot fetch error:', e);
    } finally {
        _isScreenshotFetching = false;
    }
}

function updateRemoteBrowserView(data) {
    const img = document.getElementById('remoteBrowserImg');
    if (img && data.image) {
        img.src = data.image;
        setBrowserSpinner(false);
    }

    const urlBar = document.getElementById('remoteBrowserUrlBar');
    if (urlBar && data.url && document.activeElement !== urlBar) {
        urlBar.value = data.url;
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
    setBrowserActionBusy(false);
    showToast('🎉 تم تسجيل الدخول واستخراج الكوكيز وحفظها بنجاح!', 'success');

    const statusBadge = document.getElementById('remoteBrowserStatusBadge');
    if (statusBadge) {
        statusBadge.textContent = 'تم استخراج الكوكيز بنجاح! ✅';
        statusBadge.className = 'comp-badge green';
    }

    setTimeout(() => {
        const modal = document.getElementById('remoteBrowserModal');
        if (modal) modal.style.display = 'none';
        if (window.loadCookieStatus) loadCookieStatus();
        if (window.loadOverview) loadOverview();
        loadGoogleAuthStatus();
    }, 1800);
}

// ===== تفعيل التركيز والكتابة المباشرة من الكيبورد والماوس على الشاشة =====
function focusBrowserScreen() {
    const wrapper = document.getElementById('remoteBrowserScreenWrapper');
    if (wrapper) wrapper.focus();
}

function onBrowserScreenFocus(focused) {
    const badge = document.getElementById('directKeyboardBadge');
    const wrapper = document.getElementById('remoteBrowserScreenWrapper');
    if (!badge || !wrapper) return;
    if (focused) {
        badge.innerHTML = '🟢 <strong>الكتابة المباشرة مفعّلة:</strong> اكتب من الكيبورد الآن أو الصق بـ Ctrl+V';
        badge.style.background = 'rgba(16,185,129,0.88)';
        badge.style.color = '#ffffff';
        badge.style.borderColor = 'rgba(255,255,255,0.35)';
        wrapper.style.boxShadow = 'inset 0 0 0 2px #10b981';
    } else {
        badge.innerHTML = '🖱️ انقر داخل الشاشة للكتابة المباشرة من الكيبورد أو التمرير بعجلة الماوس';
        badge.style.background = 'rgba(15,23,42,0.78)';
        badge.style.color = '#cbd5e1';
        badge.style.borderColor = 'rgba(255,255,255,0.15)';
        wrapper.style.boxShadow = 'none';
    }
}

let _eventsBound = false;
function bindDirectBrowserEvents() {
    if (_eventsBound) return;
    const wrapper = document.getElementById('remoteBrowserScreenWrapper');
    if (!wrapper) return;
    _eventsBound = true;

    // 1. الكتابة المباشرة من الكيبورد عند التركيز على شاشة المتصفح
    wrapper.addEventListener('keydown', (e) => {
        // السماح باختصار اللصق Ctrl+V ليتم التقاطه في حدث paste
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'v') {
            return;
        }
        // اختصار تحديد الكل Ctrl+A
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'a') {
            e.preventDefault();
            sendBrowserKey('Control+a');
            return;
        }

        const specialKeys = {
            Enter: 'Enter',
            Backspace: 'Backspace',
            Tab: 'Tab',
            Escape: 'Escape',
            Delete: 'Delete',
            ArrowUp: 'ArrowUp',
            ArrowDown: 'ArrowDown',
            ArrowLeft: 'ArrowLeft',
            ArrowRight: 'ArrowRight'
        };

        if (specialKeys[e.key]) {
            e.preventDefault();
            flushDirectTypeBuffer().then(() => sendBrowserKey(specialKeys[e.key]));
            return;
        }

        // حرف قابل للطباعة (إنجليزي/عربي/رموز/أرقام)
        if (e.key && e.key.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
            e.preventDefault();
            queueDirectTypedChar(e.key);
        }
    });

    // 2. دعم اللصق المباشر Ctrl+V داخل شاشة المتصفح
    wrapper.addEventListener('paste', (e) => {
        const pasted = (e.clipboardData || window.clipboardData).getData('text');
        if (pasted) {
            e.preventDefault();
            sendDirectTextChunk(pasted, false);
        }
    });

    // 3. دعم التمرير بعجلة الماوس (Mouse Wheel)
    wrapper.addEventListener('wheel', (e) => {
        e.preventDefault();
        _pendingWheelDeltaY += Math.round(e.deltaY);
        if (_wheelThrottleTimer) return;
        _wheelThrottleTimer = setTimeout(() => {
            const dy = _pendingWheelDeltaY;
            _pendingWheelDeltaY = 0;
            _wheelThrottleTimer = null;
            if (Math.abs(dy) > 5) {
                scrollRemoteBrowser(dy);
            }
        }, 140);
    }, { passive: false });
}

function queueDirectTypedChar(ch) {
    _directTypeBuffer += ch;
    if (_directTypeFlushTimer) clearTimeout(_directTypeFlushTimer);
    _directTypeFlushTimer = setTimeout(() => {
        flushDirectTypeBuffer();
    }, 110);
}

async function flushDirectTypeBuffer() {
    if (_directTypeFlushTimer) {
        clearTimeout(_directTypeFlushTimer);
        _directTypeFlushTimer = null;
    }
    if (!_directTypeBuffer) return;
    const chunk = _directTypeBuffer;
    _directTypeBuffer = '';
    await sendDirectTextChunk(chunk, false);
}

async function sendDirectTextChunk(text, pressEnter = false) {
    if (!text && !pressEnter) return;
    _isActionPending = true;
    setBrowserActionBusy(true, '⌨️ جاري الكتابة...');
    try {
        const res = await apiFetch('/api/auth/google/type', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text, enter: pressEnter, clear_first: false, smart_focus: false })
        });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
        }
    } catch (err) {
        console.error('Direct type error:', err);
    } finally {
        _isActionPending = false;
        setBrowserActionBusy(false);
    }
}

// ===== النقر بالماوس مع مؤشر نبضي مرئي بدون تجميد الشاشة =====
function showClickRipple(offsetX, offsetY) {
    const ripple = document.getElementById('remoteBrowserClickRipple');
    if (!ripple) return;
    ripple.style.left = `${offsetX}px`;
    ripple.style.top = `${offsetY}px`;
    ripple.style.display = 'block';
    ripple.style.opacity = '1';
    ripple.style.transform = 'scale(0.5)';
    requestAnimationFrame(() => {
        ripple.style.transform = 'scale(1.6)';
        ripple.style.opacity = '0';
    });
    setTimeout(() => {
        ripple.style.display = 'none';
    }, 360);
}

async function handleBrowserScreenClick(e) {
    const img = document.getElementById('remoteBrowserImg');
    if (!img) return;

    focusBrowserScreen();

    const rect = img.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return;

    const clickOffsetX = e.clientX - rect.left;
    const clickOffsetY = e.clientY - rect.top;
    showClickRipple(clickOffsetX, clickOffsetY);

    // حساب الإحداثيات بالنسبة لحجم الصفحة الافتراضي (1280x800)
    const scaleX = 1280 / rect.width;
    const scaleY = 800 / rect.height;
    const x = Math.round(clickOffsetX * scaleX);
    const y = Math.round(clickOffsetY * scaleY);

    _isActionPending = true;
    setBrowserActionBusy(true, '🖱️ نقر...');

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
        setBrowserActionBusy(false);
    }
}

// ===== التمرير لأعلى ولأسفل =====
async function scrollRemoteBrowser(deltaY = 300) {
    _isActionPending = true;
    setBrowserActionBusy(true, '↕️ تمرير...');
    try {
        const res = await apiFetch('/api/auth/google/scroll', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ delta_x: 0, delta_y: deltaY })
        });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
        }
    } catch (err) {
        console.error('Scroll error:', err);
    } finally {
        _isActionPending = false;
        setBrowserActionBusy(false);
    }
}

// ===== التعبئة الذكية وإرسال النص من الشريط السفلي =====
async function sendBrowserTypedText(pressEnter = false, smartFocus = true) {
    const input = document.getElementById('browserTypeInput');
    if (!input) return;
    const text = input.value;
    if (!text && !pressEnter) return;

    _isActionPending = true;
    setBrowserActionBusy(true, '⚡ جاري التعبئة والإرسال...');

    try {
        const res = await apiFetch('/api/auth/google/type', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                text,
                enter: pressEnter,
                clear_first: false,
                smart_focus: smartFocus
            })
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
        setBrowserActionBusy(false);
    }
}

function toggleBrowserInputSecret() {
    const input = document.getElementById('browserTypeInput');
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
}

async function clearRemoteBrowserInput() {
    _isActionPending = true;
    setBrowserActionBusy(true, '🧹 جاري مسح الحقل...');
    try {
        const res = await apiFetch('/api/auth/google/clear-input', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
        }
    } catch (err) {
        console.error('Clear input error:', err);
    } finally {
        _isActionPending = false;
        setBrowserActionBusy(false);
    }
}

async function sendBrowserKey(key) {
    _isActionPending = true;
    setBrowserActionBusy(true, `⌨️ ${key}...`);

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
        setBrowserActionBusy(false);
    }
}

async function browserHistoryNav(direction = 'back') {
    _isActionPending = true;
    setBrowserActionBusy(true, direction === 'back' ? '← رجوع...' : '→ تقدم...');
    try {
        const res = await apiFetch('/api/auth/google/history', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ direction })
        });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
        }
    } catch (err) {
        console.error('History nav error:', err);
    } finally {
        _isActionPending = false;
        setBrowserActionBusy(false);
    }
}

async function reloadRemoteBrowser() {
    _isActionPending = true;
    setBrowserActionBusy(true, '🔄 تحديث الصفحة...');

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
        setBrowserActionBusy(false);
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
    if (!url) return;
    let targetUrl = url.trim();
    if (!/^https?:\/\//i.test(targetUrl)) {
        targetUrl = 'https://' + targetUrl;
    }

    _isActionPending = true;
    setBrowserActionBusy(true, '🌐 جاري الانتقال للرابط...');

    try {
        const res = await apiFetch('/api/auth/google/navigate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: targetUrl })
        });
        const data = await res.json();
        if (data.success) {
            updateRemoteBrowserView(data);
        }
    } catch (err) {
        console.error('Navigate error:', err);
    } finally {
        _isActionPending = false;
        setBrowserActionBusy(false);
    }
}

// تصدير الدوال للنطاق العام
window.loadGoogleAuthStatus = loadGoogleAuthStatus;
window.startGoogleLogin = startGoogleLogin;
window.cancelGoogleLogin = cancelGoogleLogin;
window.openRemoteBrowserModal = openRemoteBrowserModal;
window.closeRemoteBrowserModal = closeRemoteBrowserModal;
window.toggleRemoteBrowserFullscreen = toggleRemoteBrowserFullscreen;
window.focusBrowserScreen = focusBrowserScreen;
window.onBrowserScreenFocus = onBrowserScreenFocus;
window.handleBrowserScreenClick = handleBrowserScreenClick;
window.scrollRemoteBrowser = scrollRemoteBrowser;
window.sendBrowserTypedText = sendBrowserTypedText;
window.toggleBrowserInputSecret = toggleBrowserInputSecret;
window.clearRemoteBrowserInput = clearRemoteBrowserInput;
window.sendBrowserKey = sendBrowserKey;
window.browserHistoryNav = browserHistoryNav;
window.reloadRemoteBrowser = reloadRemoteBrowser;
window.navigateRemoteBrowser = navigateRemoteBrowser;
window.extractCookiesNow = extractCookiesNow;
