/* ==========================================================================
   REAL-TIME CANVAS TELEMETRY CHARTS ENGINE (CPU & RAM)
   YouTube API Hub - Cloud Control Center
   ========================================================================== */

const TelemetryCharts = (function () {
    const MAX_POINTS = 24;

    // سجل البيانات الزمنية الحية
    const cpuHistory = [];
    const ramHistory = [];
    const labelsHistory = [];

    // تهيئة البيانات الأولية الافتراضية
    for (let i = 0; i < MAX_POINTS; i++) {
        cpuHistory.push(0);
        ramHistory.push(0);
        labelsHistory.push('');
    }

    function pushData(cpuVal, ramVal) {
        const now = new Date();
        const timeStr = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}:${now.getSeconds().toString().padStart(2, '0')}`;

        cpuHistory.push(Math.min(100, Math.max(0, cpuVal)));
        ramHistory.push(Math.min(100, Math.max(0, ramVal)));
        labelsHistory.push(timeStr);

        if (cpuHistory.length > MAX_POINTS) {
            cpuHistory.shift();
            ramHistory.shift();
            labelsHistory.shift();
        }

        renderCpuChart();
        renderRamChart();
    }

    function renderSplineChart(canvasId, data, lineColor, gradStart, gradStop) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;

        // دعم دقة الشاشات العالية (Retina/High-DPI)
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

        const padTop = 15;
        const padBottom = 25;
        const padLeft = 40;
        const padRight = 15;
        const plotW = w - padLeft - padRight;
        const plotH = h - padTop - padBottom;

        // 1. رسم خطوط الشبكة والمحاور (Grid Lines)
        const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)';
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

        if (data.length < 2) return;

        // 2. حساب إحداثيات النقاط
        const stepX = plotW / (data.length - 1);
        const points = data.map((val, idx) => {
            const x = padLeft + idx * stepX;
            const y = padTop + plotH - (val / 100) * plotH;
            return { x, y };
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

        // 4. رسم المنحنى السلس (Smooth Line)
        ctx.beginPath();
        ctx.moveTo(points[0].x, points[0].y);

        for (let i = 0; i < points.length - 1; i++) {
            const cpX = (points[i].x + points[i + 1].x) / 2;
            ctx.bezierCurveTo(cpX, points[i].y, cpX, points[i + 1].y, points[i + 1].x, points[i + 1].y);
        }

        ctx.strokeStyle = lineColor;
        ctx.lineWidth = 2.5;
        ctx.stroke();

        // 5. نقطة التوهج اللحظية على آخر قيمة (Pulse Glow Point)
        const lastP = points[points.length - 1];
        ctx.beginPath();
        ctx.arc(lastP.x, lastP.y, 6, 0, Math.PI * 2);
        ctx.fillStyle = lineColor;
        ctx.shadowColor = lineColor;
        ctx.shadowBlur = 10;
        ctx.fill();
        ctx.shadowBlur = 0;

        ctx.beginPath();
        ctx.arc(lastP.x, lastP.y, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = '#ffffff';
        ctx.fill();

        // رسم التوقيت على أول وآخر نقطة
        ctx.fillStyle = textColor;
        ctx.textAlign = 'center';
        ctx.fillText(labelsHistory[0] || '', padLeft + 15, h - 8);
        ctx.fillText(labelsHistory[labelsHistory.length - 1] || 'الآن', w - padRight - 15, h - 8);
    }

    function renderCpuChart() {
        renderSplineChart(
            'cpuChartCanvas',
            cpuHistory,
            '#5D87FF',
            'rgba(93, 135, 255, 0.32)',
            'rgba(93, 135, 255, 0.0)'
        );
    }

    function renderRamChart() {
        renderSplineChart(
            'ramChartCanvas',
            ramHistory,
            '#49BEFF',
            'rgba(73, 190, 255, 0.32)',
            'rgba(73, 190, 255, 0.0)'
        );
    }

    function handleResize() {
        renderCpuChart();
        renderRamChart();
    }

    window.addEventListener('resize', handleResize);
    window.onThemeChanged = function () {
        renderCpuChart();
        renderRamChart();
    };

    return {
        pushData: pushData,
        redraw: function () {
            renderCpuChart();
            renderRamChart();
        }
    };
})();

window.TelemetryCharts = TelemetryCharts;
