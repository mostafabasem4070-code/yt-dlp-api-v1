# استخدام صورة بايثون رسمية مستقرة (Debian 12 Bookworm LTS) لضمان توافق كافة مكتبات النظام
FROM python:3.11-slim-bookworm

# منع بايثون من كتابة ملفات pyc، وضمان إخراج السجلات فوراً، وتوحيد مسار متصفح Playwright لجميع المستخدمين
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    XDG_CACHE_HOME=/app/.cache

# تثبيت الأدوات الأساسية ومكتبة ffmpeg وخادم الشاشة الافتراضية Xvfb والخطوط العربية ومكتبات Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    ca-certificates \
    gnupg \
    xvfb \
    fonts-liberation \
    fonts-dejavu-core \
    fonts-freefont-ttf \
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    libpango-1.0-0 \
    libcairo2 \
    libdbus-1-3 \
    libatspi2.0-0 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# تثبيت Node.js 20 LTS الحديث (اللازم لـ yt-dlp لدعم --permission وحل تحديات n-challenge)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# تثبيت Deno (المحرك الافتراضي والمفضل رسمياً من yt-dlp لحل تحديات التشفير والبوت)
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno
RUN chmod 755 /usr/local/bin/deno

WORKDIR /app

# تثبيت مكتبات بايثون أولاً للاستفادة من Docker Cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت Google Chrome الرسمي المستقر (لمعمارية amd64 المعتمدة لدى Google) مع احتياطي Chromium لغيرها
RUN if [ "$(dpkg --print-architecture)" = "amd64" ]; then \
        curl -fsSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o /tmp/chrome.deb \
        && apt-get update && apt-get install -y --no-install-recommends /tmp/chrome.deb \
        && rm -f /tmp/chrome.deb \
        && rm -rf /var/lib/apt/lists/*; \
    else \
        mkdir -p /ms-playwright && playwright install chromium && chmod -R 777 /ms-playwright; \
    fi

# نسخ وتجهيز كاش مكتبة فك التحديات (challenge-solver) لضمان عمل Deno فورياً سواء عملت الحاوية كـ root أو مستخدم عادي
RUN mkdir -p /root/.cache/yt-dlp/challenge-solver /app/.cache/yt-dlp/challenge-solver
COPY challenge_solver_cache.json /root/.cache/yt-dlp/challenge-solver/lib.json
COPY challenge_solver_cache.json /app/.cache/yt-dlp/challenge-solver/lib.json

# نسخ كود المشروع بالكامل وضبط الصلاحيات لدعم بيئات Hostless.cloud / Railway / Docker
COPY . .
RUN chmod -R 777 /app

# منفذ التشغيل الافتراضي (المنصات السحابية تمرر متغير PORT تلقائياً)
ENV PORT=8000
EXPOSE ${PORT}

# تشغيل خادم Uvicorn وربطه بالمنفذ المخصص مع دعم البروكسي العكسي
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
