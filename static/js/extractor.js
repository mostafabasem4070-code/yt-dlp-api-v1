/* ==========================================================================
   VIDEO EXTRACTOR & PROXY STREAMING TESTER
   YouTube API Hub - Cloud Control Center
   ========================================================================== */

async function handleExtractVideo() {
    const input = document.getElementById('extractUrlInput');
    const url = input.value.trim();
    const btn = document.getElementById('btnExtract');
    const proxy = document.getElementById('proxyStreamsCheck')?.checked ?? true;
    const container = document.getElementById('extractResultContainer');

    if (!url) {
        showToast('يرجى وضع رابط الفيديو أولاً.', 'error');
        return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span>جاري فحص واستخراج الجودات...</span>';
    if (container) container.style.display = 'none';

    try {
        const res = await apiFetch('/api/extract', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url: url, proxy_streams: proxy })
        });
        const data = await res.json();

        if (res.ok && data.status === 'success') {
            showToast('تم استخراج الروابط المباشرة بنجاح!');
            renderExtractResult(data);
        } else {
            showToast(data.detail || data.message || 'فشل استخراج الروابط.', 'error');
        }
    } catch (e) {
        showToast('تعذر الاتصال بالخادم.', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<span>استخراج الروابط فوراً</span>';
    }
}

function renderExtractResult(data) {
    const container = document.getElementById('extractResultContainer');
    if (!container) return;

    const info = data.video_info || {};
    const streams = data.streams || {};

    let streamListHtml = '';
    const categories = [
        { key: 'video_with_audio', title: 'فيديو مدمج بالصوت (جاهز للتشغيل والتحميل)', color: 'rgba(16,185,129,0.15)', border: 'rgba(16,185,129,0.3)', textColor: '#34d399' },
        { key: 'video_only', title: 'فيديو عالي الجودة فقط (1080p / 2K / 4K)', color: 'rgba(6,182,212,0.15)', border: 'rgba(6,182,212,0.3)', textColor: '#67e8f9' },
        { key: 'audio_only', title: 'مسارات صوتية فقط (Audio Tracks)', color: 'rgba(139,92,246,0.15)', border: 'rgba(139,92,246,0.3)', textColor: '#c084fc' }
    ];

    categories.forEach(cat => {
        const arr = streams[cat.key] || [];
        if (arr.length > 0) {
            streamListHtml += `
                <div style="margin-top:16px;">
                    <div style="font-size:0.92rem; font-weight:700; color:var(--text-main); margin-bottom:8px;">${cat.title} (${arr.length})</div>
                    <div style="display:flex; flex-wrap:wrap; gap:8px;">
            `;
            arr.forEach(s => {
                let label = s.quality_note || s.resolution || s.format_note || (s.abr_kbps ? `${s.abr_kbps} kbps` : 'stream');
                if (s.is_original) {
                    label = `★ أصلي: ${label}`;
                } else if (s.language) {
                    label = `[${s.language}] ${label}`;
                }
                const sizeText = s.filesize_readable ? ` • ${s.filesize_readable}` : '';
                streamListHtml += `
                    <a href="${s.url}" target="_blank" rel="noopener noreferrer" style="display:inline-flex; align-items:center; gap:6px; padding:7px 14px; background:${cat.color}; border:1px solid ${cat.border}; border-radius:var(--radius-md); color:${cat.textColor}; text-decoration:none; font-size:0.84rem; font-family:var(--font-mono); font-weight:600; transition:transform 0.15s ease;">
                        <span>▶ ${label} (${s.ext || 'mp4'}${sizeText})</span>
                    </a>
                `;
            });
            streamListHtml += `</div></div>`;
        }
    });

    container.innerHTML = `
        <div class="card" style="margin-top:20px; border-color:var(--accent-cyan);">
            <div style="display:flex; gap:20px; align-items:flex-start; flex-wrap:wrap;">
                ${info.thumbnail ? `<img src="${info.thumbnail}" alt="Thumbnail" style="width:190px; height:108px; object-fit:cover; border-radius:var(--radius-md); border:1px solid var(--border-subtle); flex-shrink:0;">` : ''}
                <div style="flex:1;">
                    <h3 style="color:var(--text-main); font-size:1.15rem; font-weight:800; margin-bottom:6px;">${info.title || 'فيديو يوتيوب'}</h3>
                    <div style="color:var(--text-muted); font-size:0.86rem; display:flex; gap:16px; flex-wrap:wrap; margin-top:8px;">
                        <span>المدة: <strong style="color:var(--text-main);">${info.duration_readable || '--'}</strong></span>
                        <span>القناة: <strong style="color:var(--text-main);">${info.uploader || '--'}</strong></span>
                        <span>المشاهدات: <strong style="color:var(--text-main);">${info.view_count ? info.view_count.toLocaleString() : '--'}</strong></span>
                    </div>
                </div>
            </div>
            ${streamListHtml}
        </div>
    `;
    container.style.display = 'block';
}

window.handleExtractVideo = handleExtractVideo;
window.renderExtractResult = renderExtractResult;
