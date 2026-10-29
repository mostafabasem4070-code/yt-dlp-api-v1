<<<<<<< HEAD
# 🚀 نظام استخراج الروابط المباشرة لليوتيوب (YouTube Direct Links API)

واجهة برمجية (RESTful API) سريعة ومبنية بلغة Python و FastAPI ومكتبة `yt-dlp` الشهيرة، صُممت خصيصاً ليتم تشغيلها ورفعها على منصة **Railway** مجاناً أو بأقل تكلفة، وتتيح لموقعك إرسال رابط فيديو يوتيوب والحصول على ملف `JSON` منظم يحتوي على تفاصيل الفيديو وروابط البث والتحميل المباشرة المؤقتة لجميع الجودات (بما في ذلك فصل الفيديو والصوت للجودات الفائقة 1080p و 4K).

---

## 📂 هيكل المشروع (Project Structure)

```text
├── main.py              # خادم FastAPI، نقاط النهاية، ولوحة التحكم
├── stream_service.py    # محرك البث المقسم 10MB Chunks لتجاوز خنق السرعة ودعم Range/Seeking
├── health_monitor.py    # مركز مراقبة صحة وتشخيص مكونات النظام الستة
├── updater_service.py   # خدمة التحديث التلقائي الدوري لـ yt-dlp كل 12 ساعة
├── youtube_service.py   # محرك الاستخراج yt-dlp وحل التحديات البرمجية
├── cookie_manager.py    # مدير الكوكيز الذكي والتحويل التلقائي لجميع الصيغ (JSON / Netscape)
├── static/
│   └── dashboard.html   # واجهة التحكم التفاعلية ومركز المراقبة الشامل
├── requirements.txt     # مكتبات بايثون المطلوبة (بما فيها httpx)
├── Dockerfile           # ملف تشغيل الحاوية لـ Railway (يشمل ffmpeg و Deno و Node 20 LTS)
├── Procfile             # خيار بديل للتشغيل عبر Buildpacks
├── railway.json         # إعدادات النشر على منصة Railway
├── test_client.py       # كود اختبار مباشر وسريع
└── cookies.txt          # ملف الكوكيز النشط على السيرفر
```

---

## 🛠️ كيف يعمل النظام؟

1. موقعك (الفرونت إند أو الباك إند) يرسل رابط الفيديو إلى الـ API عبر `POST` أو `GET`.
2. السيرفر على Railway يقوم بتشغيل مكتبة `yt-dlp` في وضع الفحص (`download=False`) دون تحميل الفيديو على السيرفر لتوفير الموارد واستهلاك البيانات.
3. يستخرج النظام روابط خوادم جوجل المباشرة المؤقتة (`googlevideo.com`) ويصنفها إلى 3 مجموعات:
   - **`video_with_audio`**: فيديوهات مدمجة بالصوت (غالباً 720p و 360p) جاهزة للتشغيل والتحميل المباشر.
   - **`video_only`**: فيديوهات فائقة الجودة بدون صوت (1080p, 1440p, 4K, 8K) لمن يريد أعلى دقة صورة.
   - **`audio_only`**: مسارات صوتية منفصلة بصيغ وجودات مختلفة (m4a, webm).
4. يرجع الـ API رد `JSON` متكامل يحتوي على تفاصيل الفيديو (العنوان، القناة، المدة، الصورة المصغرة) ومصفوفات الروابط.

---

## 💻 طريقة التشغيل والتجربة محلياً (Local Setup)

إذا أردت تجربة النظام على جهازك أولاً:

1. افتح موجه الأوامر (Terminal أو PowerShell) في مجلد المشروع:
   ```bash
   python -m venv .venv
   ```
2. تفعيل البيئة الافتراضية:
   - في ويندوز:
     ```powershell
     .\.venv\Scripts\activate
     ```
3. تثبيت المتطلبات:
   ```bash
   pip install -r requirements.txt
   ```
4. تشغيل السيرفر:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
5. افتح المتصفح على:
   - واجهة التجربة التفاعلية (Swagger UI): `http://127.0.0.1:8000/docs`
   - تجربة استخراج سريع: `http://127.0.0.1:8000/api/extract?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ`

---

## ☁️ خطوات الرفع والنشر على Railway من الصفر

### الخطوة 1: رفع المشروع إلى مستودع GitHub
1. تأكد من تثبيت Git على جهازك ثم نفذ الأوامر التالية في مجلد المشروع:
   ```bash
   git init
   git add .
   git commit -m "Initial commit for YouTube extractor API"
   ```
2. أنشئ مستودعاً جديداً (New Repository) على حسابك في [GitHub](https://github.com) (اجعله Public أو Private).
3. اربط المشروع وارفعه:
   ```bash
   git remote add origin https://github.com/USERNAME/REPO_NAME.git
   git branch -M main
   git push -u origin main
   ```

### الخطوة 2: النشر على Railway
1. ادخل إلى موقع [Railway.app](https://railway.app) وسجل الدخول بحساب GitHub الخاص بك.
2. اضغط على زر **"New Project"**.
3. اختر **"Deploy from GitHub repo"**.
4. حدد المستودع الذي أنشأته للتو.
5. سيتعرف Railway تلقائياً على ملف `Dockerfile` وسيبدأ عملية البناء والتشغيل فوراً.

### الخطوة 3: إنشاء رابط عام (Public Domain)
1. بعد اكتمال الـ Deployment، اضغط على الخدمة (Service) في لوحة تحكم Railway.
2. توجه إلى تبويب **"Settings"**.
3. انزل إلى قسم **"Networking"** واضغط على زر **"Generate Domain"**.
4. ستحصل على رابط مثل:
   ```text
   https://youtube-extractor-production.up.railway.app
   ```

---

## 📡 كيفية استخدام الـ API من موقعك

### 1. طلب POST (الموصى به)
- **الرابط**: `https://your-app.up.railway.app/api/extract`
- **الهيدر**: `Content-Type: application/json`
- **جسم الطلب (Body)**:
  ```json
  {
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  }
  ```

#### مثال كود JavaScript (Fetch من موقعك):
```javascript
async function getDirectLinks(youtubeUrl) {
  try {
    const response = await fetch("https://your-app.up.railway.app/api/extract", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ url: youtubeUrl })
    });
    
    const data = await response.json();
    console.log("بيانات الفيديو:", data.video_info);
    console.log("فيديوهات بصوت:", data.streams.video_with_audio);
    console.log("فيديوهات بدون صوت (جودة عالية):", data.streams.video_only);
    console.log("صوتيات فقط:", data.streams.audio_only);
    return data;
  } catch (error) {
    console.error("حدث خطأ:", error);
  }
}
```

### 2. طلب GET (مباشر عبر الرابط)
```text
https://your-app.up.railway.app/api/extract?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

### 3. نقطة البث السريع المتجاوز لخنق السرعة (Streaming Proxy)
- **الرابط**: `https://your-app.up.railway.app/api/stream?url=<ENCODED_DIRECT_URL>`
- **كيف يعمل؟**
  - يقوم تلقائياً بطلب الفيديو من خوادم `googlevideo.com` على هيئة أجزاء مغلقة الحجم (10MB Range Chunks) تماماً كتقنية `yt-dlp --http-chunk-size 10M`.
  - يتجاوز خنق السرعة (Throttling ~32KB/s) الذي يفرضه يوتيوب على المتصفحات في الطلبات المفتوحة.
  - يدعم معيار `HTTP 206 Partial Content` والقفز بالوقت (Seeking) والتشغيل السلس لأي جودة (1080p, 2K, 4K) واستهلاك الذاكرة يكاد ينعدم (Zero RAM Buffer).
  - الروابط المعادة في حقل `url` من `/api/extract` تكون تلقائياً مجهزة للاستخدام المباشر مع هذا المسار، مع بقاء الرابط الأصلي في `direct_url`.

---

## 📋 نموذج الرد (Response Format)

```json
{
  "status": "success",
  "video_info": {
    "id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
    "duration_seconds": 213,
    "duration_readable": "03:33",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "uploader": "Rick Astley",
    "channel_url": "https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw",
    "view_count": 1500000000,
    "description_preview": "The official video for...",
    "original_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  },
  "stats": {
    "total_formats": 25,
    "video_with_audio_count": 2,
    "video_only_count": 18,
    "audio_only_count": 5
  },
  "streams": {
    "video_with_audio": [
      {
        "format_id": "22",
        "ext": "mp4",
        "quality_note": "720p",
        "resolution": "1280x720",
        "filesize_readable": "32.45 MB",
        "url": "https://rr5---sn-4g5ednks.googlevideo.com/videoplayback?..."
      }
    ],
    "video_only": [
      {
        "format_id": "137",
        "ext": "mp4",
        "quality_note": "1080p",
        "resolution": "1920x1080",
        "filesize_readable": "85.20 MB",
        "url": "https://rr5---sn-4g5ednks.googlevideo.com/videoplayback?..."
      }
    ],
    "audio_only": [
      {
        "format_id": "140",
        "ext": "m4a",
        "abr_kbps": 128.0,
        "filesize_readable": "3.50 MB",
        "url": "https://rr5---sn-4g5ednks.googlevideo.com/videoplayback?..."
      }
    ]
  }
}
```

---

## 🎛️ واجهة التحكم ومركز المراقبة الشامل (Monitoring Center & Dashboard):
يمكنك فتح المتصفح على الرابط الرئيسي أو `/dashboard`:
- **الرابط**: `http://127.0.0.1:8000/dashboard` (أو رابط Railway الخاص بك: `https://your-app.up.railway.app/dashboard`)
- **المميزات**:
  1. **🖥️ مركز مراقبة المكونات (System Health Monitoring)**:
     - فحص فوري ومستمر لجميع مكونات النظام الستة:
       * **جلسة كوكيز يوتيوب**: فحص الصلاحية وعدد الأيام المتبقية وتواجد مفاتيح المصادقة الحيوية.
       * **محرك Deno**: التأكد من تثبيته لحل تحديات التشفير `n-challenge` بأعلى كفاءة.
       * **محرك Node.js**: التحقق من الإصدار (Node 20+) ودعم خاصية `--permission`.
       * **نواة yt-dlp**: فحص الإصدار الحالي ومطابقته بأحدث إصدار على PyPI مع زر تحديث فوري.
       * **محرك FFmpeg**: التأكد من جاهزية معالجة ودمج ملفات الوسائط.
       * **شبكة وخوادم يوتيوب**: قياس زمن الاستجابة (Latency بالملي ثانية) واكتشاف أي حظر شبكي.
     - زر **"فحص شامل لجميع المكونات (Run Full Probe)"**: يقوم باختبار استخراج فعلي مع يوتيوب وعرض تقرير الأداء.
  2. **🍪 إدارة وتحديث الكوكيز الذكية (Universal Cookie Hub)**:
     - قبول الكوكيز بأي صيغة (JSON مصفوفة من Cookie-Editor أو أسطر Netscape أو ترويسة HTTP Header).
     - فحص حي فوري للكوكيز في ثوانٍ مع قياس زمن الاستجابة.
  3. **⏰ التحديث التلقائي الدوري (Auto-Updater)**:
     - خدمة مجدولة في الخلفية تعمل كل 12 ساعة لفحص وتحديث `yt-dlp` تلقائياً لحل أي تغييرات مفاجئة من يوتيوب.
  4. **🎬 مستخرج الروابط وتجربة التشغيل المباشر**:
     - تجربة أي رابط فيديو وعرض جميع روابط الجودات مع مشغل مدمج وأزرار نسخ.
  5. **⚡ سجل العمليات والتشخيص الحي (Live Logs)**:
     - متابعة سجلات السيرفر الحية لحظة بلحظة مع زر لنسخ السجل بالكامل بنقرة واحدة.

---

## ⚠️ ملاحظات هامة وحلول قيود يوتيوب:
1. **مدة صلاحية الروابط (Expiration)**: الروابط المباشرة لـ `googlevideo.com` تكون صالحة عادة لمدة **6 ساعات** تقريباً من وقت استخراجها، وبعدها يجب طلب رابط جديد.
2. **تحديث الكوكيز واستمراريتها**: لتجنب انتهاء الكوكيز سريعاً، يُنصح بتسجيل الدخول بحساب جوجل مخصص (Burner Account) في بروفايل متصفح منفصل، وعدم الضغط على "Sign Out" أبداً، وتصدير الكوكيز عبر إضافة Cookie-Editor كـ JSON ولصقها في واجهة `/dashboard`. كما أن السيرفر يدعم وضع الزائر التلقائي (Guest Fallback) عند تعذر الكوكيز.
=======
# 🚀 نظام استخراج الروابط المباشرة لليوتيوب (YouTube Direct Links API)

واجهة برمجية (RESTful API) سريعة ومبنية بلغة Python و FastAPI ومكتبة `yt-dlp` الشهيرة، صُممت خصيصاً ليتم تشغيلها ورفعها على منصة **Railway** مجاناً أو بأقل تكلفة، وتتيح لموقعك إرسال رابط فيديو يوتيوب والحصول على ملف `JSON` منظم يحتوي على تفاصيل الفيديو وروابط البث والتحميل المباشرة المؤقتة لجميع الجودات (بما في ذلك فصل الفيديو والصوت للجودات الفائقة 1080p و 4K).

---

## 📂 هيكل المشروع (Project Structure)

```text
├── main.py              # خادم FastAPI، نقاط النهاية، ولوحة التحكم
├── stream_service.py    # محرك البث المقسم 10MB Chunks لتجاوز خنق السرعة ودعم Range/Seeking
├── health_monitor.py    # مركز مراقبة صحة وتشخيص مكونات النظام الستة
├── updater_service.py   # خدمة التحديث التلقائي الدوري لـ yt-dlp كل 12 ساعة
├── youtube_service.py   # محرك الاستخراج yt-dlp وحل التحديات البرمجية
├── cookie_manager.py    # مدير الكوكيز الذكي والتحويل التلقائي لجميع الصيغ (JSON / Netscape)
├── static/
│   └── dashboard.html   # واجهة التحكم التفاعلية ومركز المراقبة الشامل
├── requirements.txt     # مكتبات بايثون المطلوبة (بما فيها httpx)
├── Dockerfile           # ملف تشغيل الحاوية لـ Railway (يشمل ffmpeg و Deno و Node 20 LTS)
├── Procfile             # خيار بديل للتشغيل عبر Buildpacks
├── railway.json         # إعدادات النشر على منصة Railway
├── test_client.py       # كود اختبار مباشر وسريع
└── cookies.txt          # ملف الكوكيز النشط على السيرفر
```

---

## 🛠️ كيف يعمل النظام؟

1. موقعك (الفرونت إند أو الباك إند) يرسل رابط الفيديو إلى الـ API عبر `POST` أو `GET`.
2. السيرفر على Railway يقوم بتشغيل مكتبة `yt-dlp` في وضع الفحص (`download=False`) دون تحميل الفيديو على السيرفر لتوفير الموارد واستهلاك البيانات.
3. يستخرج النظام روابط خوادم جوجل المباشرة المؤقتة (`googlevideo.com`) ويصنفها إلى 3 مجموعات:
   - **`video_with_audio`**: فيديوهات مدمجة بالصوت (غالباً 720p و 360p) جاهزة للتشغيل والتحميل المباشر.
   - **`video_only`**: فيديوهات فائقة الجودة بدون صوت (1080p, 1440p, 4K, 8K) لمن يريد أعلى دقة صورة.
   - **`audio_only`**: مسارات صوتية منفصلة بصيغ وجودات مختلفة (m4a, webm).
4. يرجع الـ API رد `JSON` متكامل يحتوي على تفاصيل الفيديو (العنوان، القناة، المدة، الصورة المصغرة) ومصفوفات الروابط.

---

## 💻 طريقة التشغيل والتجربة محلياً (Local Setup)

إذا أردت تجربة النظام على جهازك أولاً:

1. افتح موجه الأوامر (Terminal أو PowerShell) في مجلد المشروع:
   ```bash
   python -m venv .venv
   ```
2. تفعيل البيئة الافتراضية:
   - في ويندوز:
     ```powershell
     .\.venv\Scripts\activate
     ```
3. تثبيت المتطلبات:
   ```bash
   pip install -r requirements.txt
   ```
4. تشغيل السيرفر:
   ```bash
   uvicorn main:app --reload --port 8000
   ```
5. افتح المتصفح على:
   - واجهة التجربة التفاعلية (Swagger UI): `http://127.0.0.1:8000/docs`
   - تجربة استخراج سريع: `http://127.0.0.1:8000/api/extract?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ`

---

## ☁️ خطوات الرفع والنشر على Railway من الصفر

### الخطوة 1: رفع المشروع إلى مستودع GitHub
1. تأكد من تثبيت Git على جهازك ثم نفذ الأوامر التالية في مجلد المشروع:
   ```bash
   git init
   git add .
   git commit -m "Initial commit for YouTube extractor API"
   ```
2. أنشئ مستودعاً جديداً (New Repository) على حسابك في [GitHub](https://github.com) (اجعله Public أو Private).
3. اربط المشروع وارفعه:
   ```bash
   git remote add origin https://github.com/USERNAME/REPO_NAME.git
   git branch -M main
   git push -u origin main
   ```

### الخطوة 2: النشر على Railway
1. ادخل إلى موقع [Railway.app](https://railway.app) وسجل الدخول بحساب GitHub الخاص بك.
2. اضغط على زر **"New Project"**.
3. اختر **"Deploy from GitHub repo"**.
4. حدد المستودع الذي أنشأته للتو.
5. سيتعرف Railway تلقائياً على ملف `Dockerfile` وسيبدأ عملية البناء والتشغيل فوراً.

### الخطوة 3: إنشاء رابط عام (Public Domain)
1. بعد اكتمال الـ Deployment، اضغط على الخدمة (Service) في لوحة تحكم Railway.
2. توجه إلى تبويب **"Settings"**.
3. انزل إلى قسم **"Networking"** واضغط على زر **"Generate Domain"**.
4. ستحصل على رابط مثل:
   ```text
   https://youtube-extractor-production.up.railway.app
   ```

---

## 📡 كيفية استخدام الـ API من موقعك

### 1. طلب POST (الموصى به)
- **الرابط**: `https://your-app.up.railway.app/api/extract`
- **الهيدر**: `Content-Type: application/json`
- **جسم الطلب (Body)**:
  ```json
  {
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  }
  ```

#### مثال كود JavaScript (Fetch من موقعك):
```javascript
async function getDirectLinks(youtubeUrl) {
  try {
    const response = await fetch("https://your-app.up.railway.app/api/extract", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ url: youtubeUrl })
    });
    
    const data = await response.json();
    console.log("بيانات الفيديو:", data.video_info);
    console.log("فيديوهات بصوت:", data.streams.video_with_audio);
    console.log("فيديوهات بدون صوت (جودة عالية):", data.streams.video_only);
    console.log("صوتيات فقط:", data.streams.audio_only);
    return data;
  } catch (error) {
    console.error("حدث خطأ:", error);
  }
}
```

### 2. طلب GET (مباشر عبر الرابط)
```text
https://your-app.up.railway.app/api/extract?url=https://www.youtube.com/watch?v=dQw4w9WgXcQ
```

### 3. نقطة البث السريع المتجاوز لخنق السرعة (Streaming Proxy)
- **الرابط**: `https://your-app.up.railway.app/api/stream?url=<ENCODED_DIRECT_URL>`
- **كيف يعمل؟**
  - يقوم تلقائياً بطلب الفيديو من خوادم `googlevideo.com` على هيئة أجزاء مغلقة الحجم (10MB Range Chunks) تماماً كتقنية `yt-dlp --http-chunk-size 10M`.
  - يتجاوز خنق السرعة (Throttling ~32KB/s) الذي يفرضه يوتيوب على المتصفحات في الطلبات المفتوحة.
  - يدعم معيار `HTTP 206 Partial Content` والقفز بالوقت (Seeking) والتشغيل السلس لأي جودة (1080p, 2K, 4K) واستهلاك الذاكرة يكاد ينعدم (Zero RAM Buffer).
  - الروابط المعادة في حقل `url` من `/api/extract` تكون تلقائياً مجهزة للاستخدام المباشر مع هذا المسار، مع بقاء الرابط الأصلي في `direct_url`.

---

## 📋 نموذج الرد (Response Format)

```json
{
  "status": "success",
  "video_info": {
    "id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
    "duration_seconds": 213,
    "duration_readable": "03:33",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    "uploader": "Rick Astley",
    "channel_url": "https://www.youtube.com/channel/UCuAXFkgsw1L7xaCfnd5JJOw",
    "view_count": 1500000000,
    "description_preview": "The official video for...",
    "original_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
  },
  "stats": {
    "total_formats": 25,
    "video_with_audio_count": 2,
    "video_only_count": 18,
    "audio_only_count": 5
  },
  "streams": {
    "video_with_audio": [
      {
        "format_id": "22",
        "ext": "mp4",
        "quality_note": "720p",
        "resolution": "1280x720",
        "filesize_readable": "32.45 MB",
        "url": "https://rr5---sn-4g5ednks.googlevideo.com/videoplayback?..."
      }
    ],
    "video_only": [
      {
        "format_id": "137",
        "ext": "mp4",
        "quality_note": "1080p",
        "resolution": "1920x1080",
        "filesize_readable": "85.20 MB",
        "url": "https://rr5---sn-4g5ednks.googlevideo.com/videoplayback?..."
      }
    ],
    "audio_only": [
      {
        "format_id": "140",
        "ext": "m4a",
        "abr_kbps": 128.0,
        "filesize_readable": "3.50 MB",
        "url": "https://rr5---sn-4g5ednks.googlevideo.com/videoplayback?..."
      }
    ]
  }
}
```

---

## 🎛️ واجهة التحكم ومركز المراقبة الشامل (Monitoring Center & Dashboard):
يمكنك فتح المتصفح على الرابط الرئيسي أو `/dashboard`:
- **الرابط**: `http://127.0.0.1:8000/dashboard` (أو رابط Railway الخاص بك: `https://your-app.up.railway.app/dashboard`)
- **المميزات**:
  1. **🖥️ مركز مراقبة المكونات (System Health Monitoring)**:
     - فحص فوري ومستمر لجميع مكونات النظام الستة:
       * **جلسة كوكيز يوتيوب**: فحص الصلاحية وعدد الأيام المتبقية وتواجد مفاتيح المصادقة الحيوية.
       * **محرك Deno**: التأكد من تثبيته لحل تحديات التشفير `n-challenge` بأعلى كفاءة.
       * **محرك Node.js**: التحقق من الإصدار (Node 20+) ودعم خاصية `--permission`.
       * **نواة yt-dlp**: فحص الإصدار الحالي ومطابقته بأحدث إصدار على PyPI مع زر تحديث فوري.
       * **محرك FFmpeg**: التأكد من جاهزية معالجة ودمج ملفات الوسائط.
       * **شبكة وخوادم يوتيوب**: قياس زمن الاستجابة (Latency بالملي ثانية) واكتشاف أي حظر شبكي.
     - زر **"فحص شامل لجميع المكونات (Run Full Probe)"**: يقوم باختبار استخراج فعلي مع يوتيوب وعرض تقرير الأداء.
  2. **🍪 إدارة وتحديث الكوكيز الذكية (Universal Cookie Hub)**:
     - قبول الكوكيز بأي صيغة (JSON مصفوفة من Cookie-Editor أو أسطر Netscape أو ترويسة HTTP Header).
     - فحص حي فوري للكوكيز في ثوانٍ مع قياس زمن الاستجابة.
  3. **⏰ التحديث التلقائي الدوري (Auto-Updater)**:
     - خدمة مجدولة في الخلفية تعمل كل 12 ساعة لفحص وتحديث `yt-dlp` تلقائياً لحل أي تغييرات مفاجئة من يوتيوب.
  4. **🎬 مستخرج الروابط وتجربة التشغيل المباشر**:
     - تجربة أي رابط فيديو وعرض جميع روابط الجودات مع مشغل مدمج وأزرار نسخ.
  5. **⚡ سجل العمليات والتشخيص الحي (Live Logs)**:
     - متابعة سجلات السيرفر الحية لحظة بلحظة مع زر لنسخ السجل بالكامل بنقرة واحدة.

---

## ⚠️ ملاحظات هامة وحلول قيود يوتيوب:
1. **مدة صلاحية الروابط (Expiration)**: الروابط المباشرة لـ `googlevideo.com` تكون صالحة عادة لمدة **6 ساعات** تقريباً من وقت استخراجها، وبعدها يجب طلب رابط جديد.
2. **تحديث الكوكيز واستمراريتها**: لتجنب انتهاء الكوكيز سريعاً، يُنصح بتسجيل الدخول بحساب جوجل مخصص (Burner Account) في بروفايل متصفح منفصل، وعدم الضغط على "Sign Out" أبداً، وتصدير الكوكيز عبر إضافة Cookie-Editor كـ JSON ولصقها في واجهة `/dashboard`. كما أن السيرفر يدعم وضع الزائر التلقائي (Guest Fallback) عند تعذر الكوكيز.
>>>>>>> 05e7a2f (Initial commit for YouTube extractor API)
