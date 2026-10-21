/* ==========================================================================
   REAL-TIME CANVAS TELEMETRY CHARTS ENGINE (CPU & RAM)
   YouTube API Hub - Cloud Control Center
   Smooth Spline Curves, Live Sonar Ripple, Hover Tooltips & Auto-Resize
   ========================================================================== */

const TelemetryCharts = (function () {
    const MAX_POINTS = 26;

    // سجل البيانات الزمنية الحية
    let cpuHistory = [];
    let ramHistory = [];
    let labelsHistory = [];
    let isInitialized = false;

    // حالة التفاعل والفأرة (Hover Tooltip)
    let hoveredCanvasId = null;
    let hoverIndex = -1;

    // حلقة الحركة والنبض اللحظي (Continuous Pulse Beacon)
    let animFrameId = null;
    let pulsePhase = 0;

    function formatTime(date) {
        return `${date.getHours().toString().padStart(2, '0')}:${date.getMinutes().toString().padStart(2, '0')}:${date.getSeconds().toString().padStart(2, '0')}`;
    }

    // تهيئة البيانات الأولية الافتراضية
    function seedInitialHistory(initialCpu, initialRam) {
        cpuHistory = [];
        ramHistory = [];
        labelsHistory = [];

        const now = Date.now();
        const baseCpu = Math.min(100, Math.max(0, initialCpu));
        const baseRam = Math.min(100, Math.max(0, initialRam));

        for (let i = MAX_POINTS - 1; i >= 0; i--) {
            const t = new Date(now - i * 4000);
            labelsHistory.push(formatTime(t));

            // تباين طبيعي خفيف جداً (Micro-jitter) لتكون البداية حية وطبيعية وليست خطاً صفرياً ميتاً
            const jitterCpu = i === 0 ? baseCpu : Math.max(0.5, Math.min(100, baseCpu + (Math.sin(i * 1.3) * 0.4)));
            const jitterRam = i === 0 ? baseRam : Math.max(0.5, Math.min(100, baseRam + (Math.cos(i * 0.9) * 0.3)));

            cpuHistory.push(parseFloat(jitterCpu.toFixed(1)));
            ramHistory.push(parseFloat(jitterRam.toFixed(1)));
        }
        isInitialized = true;
    }

    function pushData(cpuVal, ramVal) {
        const cleanCpu = parseFloat(cpuVal);
        const cleanRam = parseFloat(ramVal);

        const validCpu = !isNaN(cleanCpu) ? Math.min(100, Math.max(0, cleanCpu)) : 0;
        const validRam = !isNaN(cleanRam) ? Math.min(100, Math.max(0, cleanRam)) : 0;

        // إذا كانت هذه أول قراءة حقيقية، نقوم بتهيئة الذاكرة التاريخية حول هذه القيمة
        if (!isInitialized || (cpuHistory.length === 0)) {
            seedInitialHistory(validCpu, validRam);
        } else {
            const now = new Date();
            cpuHistory.push(validCpu);
            ramHistory.push(validRam);
            labelsHistory.push(formatTime(now));

            if (cpuHistory.length > MAX_POINTS) {
                cpuHistory.shift();
                ramHistory.shift();
                labelsHistory.shift();
            }
        }

        renderAll();
    }

    function renderSplineChart(canvasId, data, lineColor, gradStart, gradStop, labelPrefix = '') {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        // التحقق من أن الكانفاس ظاهر ومتاح في الصفحة
        const rect = canvas.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;

        // دعم دقة الشاشات العالية (Retina/High-DPI)
        const dpr = window.devicePixelRatio || 1;
        if (canvas.width !== Math.round(rect.width * dpr) || canvas.height !== Math.round(rect.height * dpr)) {
            canvas.width = Math.round(rect.width * dpr);
            canvas.height = Math.round(rect.height * dpr);
        }

        const ctx = canvas.getContext('2d');
        ctx.save();
        ctx.scale(dpr, dpr);

        const w = rect.width;
        const h = rect.height;
        const isDark = document.documentElement.getAttribute('data-theme') !== 'light';

        ctx.clearRect(0, 0, w, h);

        const padTop = 18;
        const padBottom = 26;
        const padLeft = 44;
        const padRight = 20;
        const plotW = w - padLeft - padRight;
        const plotH = h - padTop - padBottom;

        // 1. رسم خطوط الشبكة والمحاور الأفقية (Grid Lines)
        const gridColor = isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.06)';
        const textColor = isDark ? '#64748b' : '#94a3b8';

        ctx.font = '10px JetBrains Mono, monospace';
        ctx.fillStyle = textColor;
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';

        [0, 25, 50, 75, 100].forEach(level => {
            const y = padTop + plotH - (level / 100) * plotH;
            ctx.beginPath();
            ctx.strokeStyle = gridColor;
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 4]);
            ctx.moveTo(padLeft, y);
            ctx.lineTo(w - padRight, y);
            ctx.stroke();
            ctx.setLineDash([]);

            ctx.fillText(`${level}%`, padLeft - 8, y);
        });

        if (!data || data.length < 2) {
            ctx.restore();
            return;
        }

        // 2. حساب إحداثيات النقاط
        const stepX = plotW / (data.length - 1);
        const points = data.map((val, idx) => {
            const x = padLeft + idx * stepX;
            const y = padTop + plotH - (val / 100) * plotH;
            return { x, y, val };
        });

        // 3. رسم المساحة المظللة المتدرجة (Gradient Area)
        const grad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
        grad.addColorStop(0, gradStart);
        grad.addColorStop(1, gradStop);

        ctx.beginPath();
        ctx.moveTo(points[0].x, padTop + plotH);
        ctx.lineTo(points[0].x, points[0].y);

        for (let i = 0; i < points.length - 1; i++) {
            const cpX = (points[i].x + points[i + 1].x) / 2;
            ctx.bezierCurveTo(cpX, points[i].y, cpX, points[i + 1].y, points[i + 1].x, points[i + 1].y);
        }

        ctx.lineTo(points[points.length - 1].x, padTop + plotH);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();

        // 4. رسم المنحنى السلس الرئيسي (Smooth Line)
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);

        for (let i = 0; i < points.length - 1; i++) {
            const cpX = (points[i].x + points[i + 1].x) / 2;
            ctx.bezierCurveTo(cpX, points[i].y, cpX, points[i + 1].y, points[i + 1].x, points[i + 1].y);
        }

        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 2.6;
        ctx.stroke();

        // 5. رسم حلقة النبض اللحظية المتوسعة (Sonar Pulse Ripple) على آخر نقطة نشطة
        const lastP = points[points.length - 1];
        const rippleRadius = 7 + (pulsePhase * 8);
        const rippleAlpha = Math.max(0, 0.65 - (pulsePhase * 0.65));

        ctx.beginPath();
        ctx.arc(lastP.x, lastP.y, rippleRadius, 0, Math.PI * 2);
        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 1.8;
        ctx.globalAlpha = rippleAlpha;
        ctx.stroke();
        ctx.globalAlpha = 1.0;

        // النقطة المشعة الأساسية
        ctx.beginPath();
        ctx.arc(lastP.x, lastP.y, 5.5, 0, Math.PI * 2);
        ctx.fillStyle = lineColor;
        ctx.shadowColor = lineColor;
        ctx.shadowBlur = 12;
        ctx.fill();
        ctx.shadowBlur = 0;

        // مركز أبيض ساطع في المنتصف
        ctx.beginPath();
        ctx.arc(lastP.x, lastP.y, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();

        // 6. رسم خط المؤشر العمودي وبطاقة التول تيب عند تحريك الفأرة (Hover Tooltip)
        if (hoveredCanvasId === canvasId && hoverIndex >= 0 && hoverIndex < points.length) {
            const hp = points[hoverIndex];
            const hTime = labelsHistory[hoverIndex] || '';

            // خط عمودي إرشادي
            ctx.beginPath();
            ctx.strokeStyle = isDark ? 'rgba(255, 255, 255, 0.25)' : 'rgba(0, 0, 0, 0.2)';
            ctx.lineWidth = 1;
            ctx.setLineDash([3, 3]);
            ctx.moveTo(hp.x, padTop);
            ctx.lineTo(hp.x, padTop + plotH);
            ctx.stroke();
            ctx.setLineDash([]);

            // نقطة التحديد
            ctx.beginPath();
            ctx.arc(hp.x, hp.y, 5, 0, Math.PI * 2);
            ctx.fillStyle = '#ffffff';
            ctx.strokeStyle = lineColor;
            ctx.lineWidth = 2.5;
            ctx.fill();
            ctx.stroke();

            // رسم التول تيب
            const tipText = `${hp.val.toFixed(1)}% (${hTime})`;
            ctx.font = '11px JetBrains Mono, monospace';
            const textWidth = ctx.measureText(tipText).width;
            const tipBoxW = textWidth + 16;
            const tipBoxH = 22;
            let tipX = hp.x - (tipBoxW / 2);
            let tipY = hp.y - 32;

            if (tipX < padLeft) tipX = padLeft;
            if (tipX + tipBoxW > w - padRight) tipX = w - padRight - tipBoxW;
            if (tipY < 4) tipY = hp.y + 12;

            ctx.fillStyle = isDark ? '#1e293b' : '#ffffff';
            ctx.strokeStyle = lineColor;
            ctx.lineWidth = 1;
            ctx.beginPath();
            ctx.roundRect ? ctx.roundRect(tipX, tipY, tipBoxW, tipBoxH, 4) : ctx.rect(tipX, tipY, tipBoxW, tipBoxH);
            ctx.fill();
            ctx.stroke();

            ctx.fillStyle = isDark ? '#ffffff' : '#0f172a';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(tipText, tipX + (tipBoxW / 2), tipY + (tipBoxH / 2));
        }

        // 7. تواريخ وتوقيت المحور السيني
        ctx.fillStyle = textColor;
        ctx.font = '10px JetBrains Mono, monospace';
        ctx.textBaseline = 'top';

        // بداية المخطط
        ctx.textAlign = 'left';
        ctx.fillText(labelsHistory[0] || '', padLeft, padTop + plotH + 8);

        // منتصف المخطط
        const midIdx = Math.floor(labelsHistory.length / 2);
        if (midIdx > 0 && midIdx < labelsHistory.length - 1) {
            ctx.textAlign = 'center';
            ctx.fillText(labelsHistory[midIdx] || '', padLeft + (plotW / 2), padTop + plotH + 8);
        }

        // الآن (الطرف الأيمن)
        ctx.textAlign = 'right';
        ctx.fillStyle = lineColor;
        ctx.font = 'bold 10px JetBrains Mono, monospace';
        ctx.fillText(`الآن • ${labelsHistory[labelsHistory.length - 1] || ''}`, w - padRight, padTop + plotH + 8);

        ctx.restore();
    }

    function renderCpuChart() {
        renderSplineChart(
            'cpuChartCanvas',
            cpuHistory,
            '#5D87FF',
            'rgba(93, 135, 255, 0.35)',
            'rgba(93, 135, 255, 0.01)',
            'CPU'
        );
    }

    function renderRamChart() {
        renderSplineChart(
            'ramChartCanvas',
            ramHistory,
            '#49BEFF',
            'rgba(73, 190, 255, 0.35)',
            'rgba(73, 190, 255, 0.01)',
            'RAM'
        );
    }

    function renderAll() {
        renderCpuChart();
        renderRamChart();
    }

    // إدارة تفاعل الفأرة للتول تيب
    function bindCanvasEvents(canvasId, historyData) {
        const canvas = document.getElementById(canvasId);
        if (!canvas || canvas._hasEvents) return;
        canvas._hasEvents = true;

        canvas.addEventListener('mousemove', (e) => {
            const rect = canvas.getBoundingClientRect();
            const padLeft = 44;
            const padRight = 20;
            const plotW = rect.width - padLeft - padRight;
            const mouseX = e.clientX - rect.left;

            if (mouseX >= padLeft && mouseX <= rect.width - padRight && historyData.length > 1) {
                const stepX = plotW / (historyData.length - 1);
                const idx = Math.round((mouseX - padLeft) / stepX);
                hoveredCanvasId = canvasId;
                hoverIndex = Math.max(0, Math.min(historyData.length - 1, idx));
            } else {
                hoveredCanvasId = null;
                hoverIndex = -1;
            }
            renderAll();
        });

        canvas.addEventListener('mouseleave', () => {
            hoveredCanvasId = null;
            hoverIndex = -1;
            renderAll();
        });
    }

    // تشغيل حلقة النبض الحي المستمرة (Live Pulse Beacon)
    function startPulseLoop() {
        if (animFrameId) cancelAnimationFrame(animFrameId);

        let lastTime = performance.now();
        function loop(now) {
            const delta = (now - lastTime) / 1000;
            lastTime = now;

            // تحديث طور النبضة (دورة كاملة كل 1.4 ثانية)
            pulsePhase = (pulsePhase + (delta * 0.72)) % 1.0;

            // إعادة رسم خفيفة لنبضة النقطة المشعة فقط إذا كان الكانفاس ظاهراً
            const cpuCanvas = document.getElementById('cpuChartCanvas');
            if (cpuCanvas && cpuCanvas.offsetParent !== null) {
                renderAll();
            }

            animFrameId = requestAnimationFrame(loop);
        }

        animFrameId = requestAnimationFrame(loop);
    }

    // ربط مستمعات تغيير الحجم وتغيير الثيم
    function init() {
        window.addEventListener('resize', () => {
            renderAll();
        });

        // مراقبة ظهور التبويب عبر ResizeObserver
        const cpuWrap = document.querySelector('.chart-canvas-wrap');
        if (cpuWrap && window.ResizeObserver) {
            const ro = new ResizeObserver(() => {
                renderAll();
            });
            ro.observe(cpuWrap);
        }

        setTimeout(() => {
            bindCanvasEvents('cpuChartCanvas', cpuHistory);
            bindCanvasEvents('ramChartCanvas', ramHistory);
            startPulseLoop();
        }, 100);
    }

    if (document.readyState === 'loading') {
        window.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    window.onThemeChanged = function () {
        renderAll();
    };

    return {
        pushData: pushData,
        redraw: function () {
            bindCanvasEvents('cpuChartCanvas', cpuHistory);
            bindCanvasEvents('ramChartCanvas', ramHistory);
            renderAll();
        },
        reset: function () {
            isInitialized = false;
            cpuHistory = [];
            ramHistory = [];
            labelsHistory = [];
            renderAll();
        }
    };
})();

window.TelemetryCharts = TelemetryCharts;
