# استخدام صورة بايثون رسمية خفيفة
FROM python:3.11-slim

# منع بايثون من كتابة ملفات pyc وضمان إخراج السجلات فوراً
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# تثبيت الأدوات الأساسية ومكتبة ffmpeg وخادم الشاشة الافتراضية ومكتبات Chromium (Playwright)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    ca-certificates \
    gnupg \
    xvfb \
    # مكتبات Chromium المطلوبة لـ Playwright
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
    && rm -rf /var/lib/apt/lists/*

# تثبيت Node.js 20 LTS الحديث (اللازم لـ yt-dlp لدعم --permission وحل تحديات n-challenge)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# تثبيت Deno (المحرك الافتراضي والمفضل رسمياً من yt-dlp لحل تحديات التشفير والبوت)
COPY --from=denoland/deno:bin /deno /usr/local/bin/deno

WORKDIR /app

# تثبيت مكتبات بايثون أولاً للاستفادة من Docker Cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# تثبيت متصفح Chromium لـ Playwright (لميزة استخراج الكوكيز تلقائياً)
RUN playwright install chromium --with-deps || true

# نسخ وتجهيز كاش مكتبة فك التحديات (challenge-solver) لضمان عمل Deno فورياً دون الحاجة لتنزيلها من GitHub
RUN mkdir -p /root/.cache/yt-dlp/challenge-solver
COPY challenge_solver_cache.json /root/.cache/yt-dlp/challenge-solver/lib.json

# نسخ كود المشروع بالكامل
COPY . .

# منفذ التشغيل الافتراضي (Railway يقوم بتمرير متغير PORT تلقائياً)
ENV PORT=8000
EXPOSE ${PORT}

# تشغيل خادم Uvicorn وربطه بالمنفذ المخصص مع دعم البروكسي العكسي لـ Railway
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
