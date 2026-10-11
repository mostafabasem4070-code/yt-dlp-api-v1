import os
import sys
import shutil
import logging
import asyncio
import re
import random
from typing import Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Query, Request, status, Response, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from cachetools import TTLCache

limiter = Limiter(key_func=get_remote_address)
extraction_cache = TTLCache(maxsize=500, ttl=3600)  # 1 hour cache

from log_manager import get_recent_logs, clear_logs, setup_logging_capture
from youtube_service import extract_youtube_info, get_cookie_file_path, test_cookie_health_live, check_ipv6_support
from stream_service import (
    get_stream_metadata,
    parse_range_header,
    stream_chunked_response,
    build_proxy_url,
    DEFAULT_CHUNK_SIZE
)
from cookie_manager import (
    read_active_cookies,
    analyze_cookies_health,
    save_cookies_content,
    clear_cookies_file,
    get_active_cookie_path
)
from updater_service import (
    get_updater_status,
    run_ytdlp_upgrade,
    background_auto_updater
)
from health_monitor import get_full_monitoring_report
from security_manager import (
    verify_admin_password,
    change_admin_password,
    create_session_token,
    validate_session_token,
    revoke_session_token,
    get_security_settings,
    add_allowed_domain,
    remove_allowed_domain,
    update_security_preferences,
    regenerate_api_key,
    test_domain_authorization,
    is_request_authorized,
    add_worker_url,
    remove_worker_url,
    clear_all_worker_urls
)
from google_auth_service import (
    start_google_login_session,
    cancel_auth_session,
    get_auth_session_status,
    get_playwright_status,
    capture_browser_screenshot,
    browser_mouse_click,
    browser_keyboard_type,
    browser_keyboard_key,
    browser_reload_page,
    browser_navigate_to,
    browser_manual_extract
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DASHBOARD_FILE = os.path.join(STATIC_DIR, "dashboard.html")

# تفعيل التقاط السجلات مباشرة
setup_logging_capture()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """إدارة دورة حياة التطبيق وتشغيل مهام التحديث التلقائي الدوري في الخلفية."""
    logger.info("Initializing YouTube Extractor API & Monitoring Center...")
    # بدء مهمة التحديث التلقائي كل 12 ساعة
    updater_task = asyncio.create_task(background_auto_updater(interval_seconds=43200))
    yield
    updater_task.cancel()
    logger.info("Server shutting down.")


app = FastAPI(
    title="YouTube Direct Links Extractor & Cookie Hub API",
    description="API متطور لاستخراج الروابط المباشرة المؤقتة لجميع جودات فيديو اليوتيوب مع إدارة شاملة لكوكيز الدخول، مركز مراقبة حي، وتحديثات تلقائية لمكتبة yt-dlp وحماية أمنية للدومينات ولوحة التحكم.",
    version="1.5.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Can be tightened based on allowed_domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ربط مجلد الملفات الثابتة (CSS, JS, Assets)
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ===================== AUTHENTICATION & SECURITY HELPERS =====================

def get_auth_token_from_request(request: Request) -> Optional[str]:
    """استخراج توكن المصادقة من ترويسة Authorization أو X-Admin-Token أو X-Session-Token أو ملف الكوكي"""
    auth_header = request.headers.get("authorization") or ""
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    x_token = request.headers.get("x-admin-token") or request.headers.get("x-session-token")
    if x_token:
        return x_token.strip()
    return request.cookies.get("admin_session")


def require_admin(request: Request):
    """التحقق الإجباري من جلسة المشرف قبل تنفيذ العمليات الحساسة"""
    token = get_auth_token_from_request(request)
    if not validate_session_token(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="غير مصرح: يلزم تسجيل الدخول للوحة التحكم."
        )
    return True


def verify_extraction_access(request: Request):
    """التحقق من تصريح الدومين ومفتاح الـ API لطلبات الاستخراج"""
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    host = request.headers.get("host")
    api_key = request.headers.get("x-api-key") or request.query_params.get("api_key")
    auth_token = get_auth_token_from_request(request)

    is_allowed, reason = is_request_authorized(
        origin=origin,
        referer=referer,
        host=host,
        api_key_header=api_key,
        auth_token=auth_token
    )
    if not is_allowed:
        logger.warning(f"Unauthorized extraction rejected: origin={origin}, referer={referer}, reason={reason}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=reason
        )


# ===================== REQUEST MODELS =====================

class ExtractRequest(BaseModel):
    url: str = Field(..., description="رابط فيديو اليوتيوب")
    proxy_streams: Optional[bool] = Field(True, description="تفعيل روابط البث التلقائي السريعة المتجاوزة لخنق السرعة (Chunked Range Proxy)")


class CookieUpdateRequest(BaseModel):
    cookies_text: str = Field(..., description="نص الكوكيز بأي صيغة (JSON أو Netscape أو Header)")
    test_immediately: Optional[bool] = Field(False, description="إجراء فحص حي فوري بعد الحفظ")


class CookieTestRequest(BaseModel):
    url: Optional[str] = Field("https://www.youtube.com/watch?v=dQw4w9WgXcQ", description="رابط فيديو للاختبار")


class LoginRequest(BaseModel):
    password: str = Field(..., description="كلمة مرور الإدارة")


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., description="كلمة المرور الحالية")
    new_password: str = Field(..., description="كلمة المرور الجديدة")


class DomainRequest(BaseModel):
    domain: str = Field(..., description="اسم الدومين أو رابطه (مثال: my-academy.com أو http://localhost)")


class WorkerRequest(BaseModel):
    url: str = Field(..., description="رابط الـ Cloudflare Worker (مثال: https://my-worker.workers.dev)")


class SecuritySettingsUpdateRequest(BaseModel):
    strict_mode: bool = Field(..., description="تفعيل وضع التحقق الصارم من الدومينات")
    generate_new_api_key: Optional[bool] = Field(False, description="توليد مفتاح API جديد")
    force_ipv6: Optional[bool] = Field(None, description="إجبار استخدام IPv6")
    use_oauth2: Optional[bool] = Field(None, description="تفعيل OAuth2")
    po_token: Optional[str] = Field(None, description="PO Token")
    visitor_data: Optional[str] = Field(None, description="Visitor Data")



@app.get("/", tags=["Dashboard & Health"])
def root_endpoint(request: Request):
    """عرض لوحة التحكم عند الفتح في المتصفح، أو إرجاع معلومات الـ API لطلبات JSON."""
    accept = request.headers.get("accept", "")
    if "text/html" in accept and os.path.exists(DASHBOARD_FILE):
        return FileResponse(DASHBOARD_FILE, media_type="text/html")

    return {
        "status": "online",
        "service": "YouTube Direct Links Extractor & Chunked Range Streaming API",
        "version": "1.4.0",
        "dashboard": "/dashboard",
        "documentation": "/docs",
        "endpoints": {
            "GET /dashboard": "لوحة التحكم التفاعلية ومركز المراقبة الشامل",
            "GET /api/monitor/health": "مركز مراقبة صحة كافة المكونات (Deno, Node, yt-dlp, FFmpeg, Cookies)",
            "POST /api/monitor/probe": "إجراء فحص تشخيصي حي لكافة المكونات وشبكة يوتيوب",
            "GET /api/system/version": "تقرير إصدارات yt-dlp وحالة التحديث التلقائي",
            "POST /api/system/update": "تحديث فوري لـ yt-dlp إلى أحدث إصدار على PyPI",
            "GET /api/cookies/status": "فحص حالة وصلاحية الكوكيز المسجلة",
            "POST /api/cookies/update": "تحديث الكوكيز بأي صيغة (JSON أو Netscape)",
            "POST /api/cookies/test": "فحص حي للكوكيز الحالية",
            "DELETE /api/cookies": "مسح الكوكيز والتحويل لوضع الزائر",
            "POST /api/extract": "استخراج الروابط المباشرة (JSON body)",
            "GET /api/extract": "استخراج الروابط المباشرة (Query param)",
            "GET /api/stream": "بث الفيديو والصوت مع تقطيع 10MB لتجاوز خنق السرعة ودعم Range والـ Seeking السلس",
            "GET /api/logs": "سجل العمليات والأخطاء الحية",
            "GET /api/debug": "فحص بيئة السيرفر والأدوات"
        }
    }


@app.get("/dashboard", response_class=HTMLResponse, tags=["Dashboard & Health"])
def get_dashboard():
    """عرض لوحة التحكم التفاعلية المباشرة لإدارة الكوكيز واستخراج الروابط ومركز المراقبة"""
    if os.path.exists(DASHBOARD_FILE):
        return FileResponse(DASHBOARD_FILE, media_type="text/html")
    raise HTTPException(status_code=404, detail="Dashboard file not found.")


# ===================== AUTHENTICATION & SECURITY ENDPOINTS =====================

@app.post("/api/auth/login", tags=["Security & Auth"])
def login(payload: LoginRequest, response: Response):
    """تسجيل الدخول إلى لوحة التحكم والتحقق من كلمة مرور المشرف"""
    if not verify_admin_password(payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="كلمة المرور غير صحيحة."
        )
    token = create_session_token()
    response.set_cookie(
        key="admin_session",
        value=token,
        httponly=True,
        max_age=7 * 24 * 3600,
        samesite="lax"
    )
    return {
        "success": True,
        "token": token,
        "message": "تم تسجيل الدخول بنجاح."
    }


@app.get("/api/auth/status", tags=["Security & Auth"])
def check_auth_status(request: Request):
    """التحقق من حالة جلسة تسجيل الدخول الحالية"""
    token = get_auth_token_from_request(request)
    is_auth = validate_session_token(token)
    return {"authenticated": is_auth}


@app.post("/api/auth/logout", tags=["Security & Auth"])
def logout(request: Request, response: Response):
    """تسجيل الخروج وإلغاء جلسة المسؤول"""
    token = get_auth_token_from_request(request)
    if token:
        revoke_session_token(token)
    response.delete_cookie("admin_session")
    return {"success": True, "message": "تم تسجيل الخروج بنجاح."}


@app.get("/api/security/settings", tags=["Security & Auth"])
def get_sec_settings(request: Request, admin: bool = Depends(require_admin)):
    """استرجاع إعدادات الأمان والدومينات المصرح لها ومفتاح الـ API"""
    return get_security_settings()


@app.post("/api/security/domains/add", tags=["Security & Auth"])
def add_domain_endpoint(payload: DomainRequest, request: Request, admin: bool = Depends(require_admin)):
    """إضافة دومين جديد إلى قائمة الدومينات المسموح لها باستخراج الروابط"""
    ok, msg, domains = add_allowed_domain(payload.domain)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "allowed_domains": domains}


@app.post("/api/security/domains/remove", tags=["Security & Auth"])
def remove_domain_endpoint(payload: DomainRequest, request: Request, admin: bool = Depends(require_admin)):
    """حذف دومين من قائمة الدومينات المسموح لها"""
    ok, msg, domains = remove_allowed_domain(payload.domain)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "allowed_domains": domains}


@app.post("/api/security/settings", tags=["Security & Auth"])
def update_sec_settings(payload: SecuritySettingsUpdateRequest, request: Request, admin: bool = Depends(require_admin)):
    """تحديث خيارات الأمان (وضع الفحص الصارم وتوليد مفتاح API جديد)"""
    res = update_security_preferences(
        strict_mode=payload.strict_mode,
        generate_new_api_key=payload.generate_new_api_key or False,
        force_ipv6=payload.force_ipv6,
        use_oauth2=payload.use_oauth2,
        po_token=payload.po_token,
        visitor_data=payload.visitor_data
    )
    return {"success": True, "settings": res}


@app.post("/api/security/workers/add", tags=["Security & Auth"])
def add_worker_endpoint(payload: WorkerRequest, request: Request, admin: bool = Depends(require_admin)):
    """إضافة Cloudflare Worker جديد إلى القائمة"""
    ok, msg, pool = add_worker_url(payload.url)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "worker_pool": pool}


@app.post("/api/security/workers/remove", tags=["Security & Auth"])
def remove_worker_endpoint(payload: WorkerRequest, request: Request, admin: bool = Depends(require_admin)):
    """حذف Cloudflare Worker من القائمة"""
    ok, msg, pool = remove_worker_url(payload.url)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg, "worker_pool": pool}


@app.post("/api/security/workers/clear", tags=["Security & Auth"])
def clear_workers_endpoint(request: Request, admin: bool = Depends(require_admin)):
    """حذف جميع روابط Cloudflare Workers دفعة واحدة"""
    ok, msg, pool = clear_all_worker_urls()
    return {"success": True, "message": msg, "worker_pool": pool}


@app.post("/api/security/change-password", tags=["Security & Auth"])
def change_pwd_endpoint(payload: ChangePasswordRequest, request: Request, admin: bool = Depends(require_admin)):
    """تغيير كلمة مرور لوحة التحكم"""
    ok, msg = change_admin_password(payload.old_password, payload.new_password)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}


@app.post("/api/security/api-key/regenerate", tags=["Security & Auth"])
def regenerate_api_key_endpoint(request: Request, admin: bool = Depends(require_admin)):
    """توليد مفتاح API جديد فورياً لربطه مع منصة Laravel في .env"""
    new_key = regenerate_api_key()
    return {
        "success": True,
        "api_key": new_key,
        "message": "تم توليد مفتاح API جديد بنجاح. يرجى تحديث متغير YTDLP_API_KEY في ملف .env لمنصة Laravel."
    }


@app.post("/api/security/domains/test", tags=["Security & Auth"])
def test_domain_endpoint(payload: DomainRequest, request: Request, admin: bool = Depends(require_admin)):
    """فحص واختبار دومين أو رابط للتحقق مما إذا كان مصرحاً له أم محظوراً"""
    return test_domain_authorization(payload.domain)




# ===================== MONITORING & AUTO-UPDATER ENDPOINTS =====================

@app.get("/api/monitor/health", tags=["Monitoring Center"])
def get_health_monitoring():
    """تقرير مراقبة شامل وفوري لكافة مكونات النظام (Deno, Node, yt-dlp, Cookies, FFmpeg, Network, Resources)"""
    return get_full_monitoring_report()


@app.get("/api/monitor/resources", tags=["Monitoring Center"])
def get_live_resources():
    """فحص حي سريع لموارد الخادم (CPU, RAM, Disk, Bandwidth, Uptime) للتحديث التلقائي الفوري"""
    from health_monitor import check_system_resources
    return check_system_resources()


@app.post("/api/monitor/probe", tags=["Monitoring Center"])
def run_system_probe(payload: Optional[CookieTestRequest] = None):
    """إجراء فحص حي فوري وتجربة اتصال مع يوتيوب لقياس زمن الاستجابة والتأكد من عمل كافة المكونات"""
    target_url = (payload.url if payload and payload.url else "https://www.youtube.com/watch?v=dQw4w9WgXcQ").strip()
    probe_result = test_cookie_health_live(target_url)
    health = get_full_monitoring_report()
    return {
        "probe": probe_result,
        "health": health
    }


@app.get("/api/system/version", tags=["Auto-Updater"])
def get_system_version_info():
    """تقرير إصدار yt-dlp الحالي والإصدار المتاح على PyPI وحالة التحديث التلقائي"""
    return get_updater_status()


@app.post("/api/system/update", tags=["Auto-Updater"])
def trigger_system_update(request: Request, force: bool = Query(False, description="إجبار التحديث حتى لو كان الإصدار متطابقاً"), admin: bool = Depends(require_admin)):
    """تحديث مكتبة yt-dlp فورياً إلى أحدث إصدار متاح عبر pip دون الحاجة لإعادة تشغيل الحاوية"""
    res = run_ytdlp_upgrade(force=force)
    return res


# ===================== COOKIES MANAGEMENT ENDPOINTS =====================

@app.get("/api/cookies/status", tags=["Cookie Hub"])
def get_cookie_status():
    """فحص حالة الكوكيز المسجلة على السيرفر وتواريخ انتهائها ومفاتيح المصادقة"""
    cookies, cookie_path = read_active_cookies()
    health = analyze_cookies_health(cookies)
    file_size = os.path.getsize(cookie_path) if cookie_path and os.path.exists(cookie_path) else 0

    return {
        **health,
        "is_valid_file": bool(cookie_path and os.path.exists(cookie_path) and file_size > 10 and len(cookies) > 0),
        "file_path": cookie_path,
        "file_size_bytes": file_size,
    }


@app.post("/api/cookies/update", tags=["Cookie Hub"])
def update_cookies(payload: CookieUpdateRequest, request: Request, admin: bool = Depends(require_admin)):
    """
    تحديث الكوكيز على السيرفر بقبول أي صيغة:
    - مصفوفة JSON من Cookie-Editor أو EditThisCookie
    - أسطر Netscape (ملف cookies.txt)
    - نص ترويسة HTTP (Cookie: ...)
    """
    try:
        result = save_cookies_content(payload.cookies_text)
        test_result = None

        if payload.test_immediately:
            test_result = test_cookie_health_live()

        return {
            "status": "success",
            "message": f"تم حفظ {result['cookies_count']} كوكيز بنجاح وتفعيلها في السيرفر.",
            "detected_format": result["detected_format"],
            "cookies_count": result["cookies_count"],
            "file_path": result["file_path"],
            "file_size_bytes": result["file_size_bytes"],
            "health": result["health"],
            "test_result": test_result
        }
    except Exception as e:
        logger.error(f"Failed to update cookies: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"فشل معالجة وحفظ الكوكيز: {str(e)}"
        )


@app.post("/api/cookies/test", tags=["Cookie Hub"])
def test_cookies_live(payload: Optional[CookieTestRequest] = None):
    """إجراء فحص حي فوري للكوكيز الحالية على فيديو يوتيوب لقياس زمن الاستجابة وصلاحية الجلسة"""
    target_url = (payload.url if payload and payload.url else "https://www.youtube.com/watch?v=dQw4w9WgXcQ").strip()
    return test_cookie_health_live(target_url)


@app.delete("/api/cookies", tags=["Cookie Hub"])
def delete_cookies(request: Request, admin: bool = Depends(require_admin)):
    """مسح ملف الكوكيز الحالي والتحويل الفوري لوضع الزائر (Guest Mode)"""
    success = clear_cookies_file()
    if success:
        return {"status": "success", "message": "تم تفريغ ملف الكوكيز بنجاح والتحويل لوضع الزائر."}
    raise HTTPException(status_code=500, detail="فشل مسح ملف الكوكيز.")


# ===================== GOOGLE AUTH (BROWSER-BASED COOKIE EXTRACTION) =====================

class GoogleLoginRequest(BaseModel):
    timeout_minutes: int = Field(15, ge=2, le=30, description="الحد الأقصى للانتظار (دقائق)")
    headless: Optional[bool] = Field(None, description="وضع التشغيل (تلقائي/يدوي)")


class GoogleClickRequest(BaseModel):
    x: int = Field(..., description="إحداثي X للنقر")
    y: int = Field(..., description="إحداثي Y للنقر")


class GoogleTypeRequest(BaseModel):
    text: str = Field(..., description="النص المراد كتابته")
    enter: bool = Field(False, description="الضغط على Enter بعد الكتابة")


class GoogleKeyRequest(BaseModel):
    key: str = Field(..., description="اسم المفتاح (Enter, Backspace, Tab...)")


@app.get("/api/auth/google/status", tags=["Cookie Hub"])
def google_auth_status(request: Request, admin: bool = Depends(require_admin)):
    """الحصول على حالة جلسة تسجيل الدخول الجارية وتوفّر Playwright وخادم Xvfb"""
    return get_playwright_status()


@app.post("/api/auth/google/start", tags=["Cookie Hub"])
async def google_auth_start(payload: GoogleLoginRequest, request: Request, admin: bool = Depends(require_admin)):
    """
    بدء جلسة تسجيل دخول Google/YouTube تفاعلية.
    يُشغّل متصفح Chromium على السيرفر مع انتظار إتمام تسجيل الدخول،
    ثم يستخرج الكوكيز ويحفظها تلقائياً من نفس الـ IP.
    """
    result = await start_google_login_session(
        timeout_minutes=payload.timeout_minutes,
        headless=payload.headless,
        target_url="https://accounts.google.com/ServiceLogin?service=youtube&hl=ar"
    )
    return result


@app.post("/api/auth/google/cancel", tags=["Cookie Hub"])
async def google_auth_cancel(request: Request, admin: bool = Depends(require_admin)):
    """إلغاء جلسة تسجيل الدخول الجارية وإغلاق المتصفح"""
    return await cancel_auth_session()


@app.get("/api/auth/google/poll", tags=["Cookie Hub"])
def google_auth_poll(request: Request, admin: bool = Depends(require_admin)):
    """استطلاع حالة جلسة تسجيل الدخول الجارية (للـ polling من الـ frontend)"""
    session = get_auth_session_status()
    extra = {}
    if session["status"] == "done":
        try:
            from cookie_manager import read_active_cookies, analyze_cookies_health
            cookies, _ = read_active_cookies()
            health = analyze_cookies_health(cookies)
            extra["cookie_health"] = health
        except Exception:
            pass
    return {"session": session, **extra}


@app.get("/api/auth/google/screenshot", tags=["Cookie Hub"])
async def google_auth_screenshot(request: Request, admin: bool = Depends(require_admin)):
    """التقاط لقطة شاشة حية من متصفح السيرفر للبث التفاعلي"""
    return await capture_browser_screenshot()


@app.post("/api/auth/google/click", tags=["Cookie Hub"])
async def google_auth_click(payload: GoogleClickRequest, request: Request, admin: bool = Depends(require_admin)):
    """إرسال نقرة ماوس إلى صفحة المتصفح في السيرفر وتحديث لقطة الشاشة فوراً"""
    return await browser_mouse_click(payload.x, payload.y)


@app.post("/api/auth/google/type", tags=["Cookie Hub"])
async def google_auth_type(payload: GoogleTypeRequest, request: Request, admin: bool = Depends(require_admin)):
    """كتابة نص في الحقل النشط بمتصفح السيرفر"""
    return await browser_keyboard_type(payload.text, payload.enter)


@app.post("/api/auth/google/key", tags=["Cookie Hub"])
async def google_auth_key(payload: GoogleKeyRequest, request: Request, admin: bool = Depends(require_admin)):
    """إرسال ضغطة مفتاح خاصة للمتصفح (Enter, Tab, Backspace...)"""
    return await browser_keyboard_key(payload.key)


@app.post("/api/auth/google/reload", tags=["Cookie Hub"])
async def google_auth_reload(request: Request, admin: bool = Depends(require_admin)):
    """إعادة تحميل الصفحة في متصفح السيرفر"""
    return await browser_reload_page()


class GoogleNavigateRequest(BaseModel):
    url: str = Field(..., description="الرابط المراد الانتقال إليه")


@app.post("/api/auth/google/navigate", tags=["Cookie Hub"])
async def google_auth_navigate(payload: GoogleNavigateRequest, request: Request, admin: bool = Depends(require_admin)):
    """الانتقال لعنوان URL محدد في متصفح السيرفر (مثل YouTube أو تسجيل دخول بديل)"""
    return await browser_navigate_to(payload.url)


@app.post("/api/auth/google/extract", tags=["Cookie Hub"])
async def google_auth_extract_now(request: Request, admin: bool = Depends(require_admin)):
    """استخراج الكوكيز وحفظها يدوياً فوراً دون انتظار"""
    return await browser_manual_extract()




# ===================== DIAGNOSTICS & LOGS ENDPOINTS =====================

@app.get("/api/debug", tags=["Diagnostics"])
def debug_info():
    """فحص تشخيصي شامل للنظام وبيئة التشغيل دون أي انهيار"""
    try:
        import yt_dlp.version
        ytdlp_ver = yt_dlp.version.__version__
    except Exception:
        ytdlp_ver = "unknown"

    try:
        cookie_path = get_cookie_file_path()
        return {
            "status": "ok",
            "yt_dlp_version": ytdlp_ver,
            "python_version": sys.version,
            "cookies_found": cookie_path is not None,
            "cookies_path": cookie_path,
            "cookies_size_bytes": os.path.getsize(cookie_path) if cookie_path and os.path.exists(cookie_path) else 0,
            "deno_installed": shutil.which("deno") is not None,
            "deno_path": shutil.which("deno"),
            "node_installed": shutil.which("node") is not None,
            "node_path": shutil.which("node"),
            "ffmpeg_installed": shutil.which("ffmpeg") is not None,
            "ffmpeg_path": shutil.which("ffmpeg"),
            "current_directory": os.getcwd(),
            "environment_cookies_set": bool(os.getenv("YOUTUBE_COOKIES")),
            "force_ipv6_enabled": get_security_settings().get("force_ipv6", True),
            "ipv6_available_on_host": check_ipv6_support()[0],
            "files_in_current_dir": [f for f in os.listdir(os.getcwd()) if not f.startswith('.')]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/logs", tags=["Diagnostics"])
def view_logs(
    limit: int = Query(120, description="الحد الأقصى لعدد السجلات"),
    level: Optional[str] = Query(None, description="مستوى السجل (ALL, INFO, WARNING, ERROR, DEBUG)"),
    search: Optional[str] = Query(None, description="بحث نصي في رسائل السجل"),
    raw: bool = Query(False, description="عرض كـ نص خام للنسخ المباشر")
):
    """عرض سجلات العمليات والأخطاء الحية المسجلة أثناء فحص الروابط مع دعم الفلترة"""
    logs = get_recent_logs(limit=limit, level=level, search=search)
    if raw:
        text_lines = [f"[{l['timestamp']}] [{l['level']}] [{l['logger']}] {l['message']}" for l in logs]
        return Response(content="\n".join(text_lines), media_type="text/plain; charset=utf-8")
    return {
        "total_records": len(logs),
        "logs": logs
    }


@app.delete("/api/logs", tags=["Diagnostics"])
def delete_logs(request: Request, admin: bool = Depends(require_admin)):
    """مسح سجل العمليات الحية"""
    clear_logs()
    return {"status": "logs cleared"}


# ===================== VIDEO EXTRACTION & STREAMING PROXY ENDPOINTS =====================

def get_public_base_url(request: Request) -> str:
    """
    تحديد الرابط الأساسي العام للخدمة على Railway مع دعم النطاقات المخصصة وتوجيهات البروكسي العكسي،
    مع توزيع الأحمال عشوائياً بين البروكسيات في حال وجود أكثر من رابط في STREAM_PROXY_URL.
    """
    cf_worker = os.getenv("STREAM_PROXY_URL") or os.getenv("CLOUDFLARE_WORKER_URL")
    if cf_worker:
        proxies = [p.strip().rstrip("/") for p in re.split(r'[\s,;]+', cf_worker) if p.strip()]
        if proxies:
            return random.choice(proxies)

    env_base = os.getenv("API_BASE_URL") or os.getenv("BASE_URL")
    if env_base:
        return env_base.rstrip("/")

    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if railway_domain:
        return f"https://{railway_domain}".rstrip("/")

    # قراءة ترويسات البروكسي العكسي القياسية (Reverse Proxy)
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def extract_canonical_cache_key(url: str, proxy_streams: bool) -> str:
    """استخراج المعرف الفريد للفيديو (Video ID) لتوحيد مفتاح الكاش حتى لو اختلفت صيغ الروابط (youtu.be أو shorts أو watch?v=)."""
    m = re.search(r'(?:v=|\/|youtu\.be\/|embed\/|shorts\/)([0-9A-Za-z_-]{11})', url)
    if m:
        return f"vid_{m.group(1)}_{proxy_streams}"
    return f"{url.strip()}_{proxy_streams}"


async def handle_extraction(url: str, request: Optional[Request] = None, proxy_streams: bool = True):
    url = url.strip()
    if not url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="رابط الفيديو مطلوب.")

    # التحقق من صلاحية الدومين ومفتاح الـ API
    if request:
        verify_extraction_access(request)

    cache_key = extract_canonical_cache_key(url, proxy_streams)
    if cache_key in extraction_cache:
        logger.info(f"Returning cached extraction for {url} [Cache Hit: {cache_key}]")
        cached_data = dict(extraction_cache[cache_key])
        cached_data["cached"] = True
        return cached_data

    try:
        logger.info(f"Received extraction request for URL: {url} (proxy_streams={proxy_streams})")
        data = await asyncio.to_thread(extract_youtube_info, url)

        # إضافة الـ Worker Pool للرد عشان لارافل يستلم القائمة ويدير التوزيع العشوائي
        sec_settings = get_security_settings()
        data["worker_pool"] = sec_settings.get("worker_pool", [])

        # التأكد من توفر direct_url لجميع الجودات
        streams_obj = data.get("streams", {})
        for cat_name in ("video_with_audio", "video_only", "audio_only"):
            format_list = streams_obj.get(cat_name, [])
            for fmt in format_list:
                raw_url = fmt.get("url")
                if raw_url and raw_url.startswith("http"):
                    fmt["direct_url"] = raw_url

        data["cached"] = False
        extraction_cache[cache_key] = data
        return data
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Extraction failed: {error_msg}")

        detail_msg = f"فشل استخراج الروابط: {error_msg} (يمكنك فحص مركز المراقبة عبر /dashboard أو مراجعة /api/logs)"
        if "The page needs to be reloaded" in error_msg:
            detail_msg = "يوتيوب يطلب تحديث الكوكيز (انتهت الجلسة). يرجى لصق كوكيز جديدة عبر لوحة التحكم /dashboard."
        elif "Sign in to confirm" in error_msg or "Please sign in" in error_msg:
            detail_msg = "يوتيوب يطلب تسجيل الدخول لتأكيد عدم وجود روبوت. يرجى تجديد الكوكيز عبر لوحة التحكم /dashboard."

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail_msg
        )


@app.post("/api/extract", tags=["Extractor"])
@limiter.limit("20/minute")
async def extract_post(request_data: ExtractRequest, request: Request):
    """استخراج الروابط المباشرة المؤقتة لجميع الجودات عبر طلب POST مع دعم البث السريع التلقائي."""
    use_proxy = True if request_data.proxy_streams is None else request_data.proxy_streams
    return await handle_extraction(request_data.url, request=request, proxy_streams=use_proxy)


@app.get("/api/extract", tags=["Extractor"])
@limiter.limit("20/minute")
async def extract_get(
    request: Request,
    url: str = Query(..., description="رابط فيديو اليوتيوب"),
    proxy_streams: bool = Query(True, description="تفعيل روابط البث السريع المقسمة (Proxy Streams)")
):
    """استخراج الروابط المباشرة المؤقتة لجميع الجودات عبر طلب GET."""
    return await handle_extraction(url, request=request, proxy_streams=proxy_streams)


@app.options("/api/stream", tags=["Streaming Proxy"])
def options_stream():
    """الاستجابة لطلبات Preflight CORS لضمان تشغيل الفيديو دون حظر في كافة المتصفحات"""
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Range, Content-Type, Accept, Origin, User-Agent",
            "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Content-Type",
            "Access-Control-Max-Age": "86400"
        }
    )


@app.get("/api/stream", tags=["Streaming Proxy"])
@app.head("/api/stream", tags=["Streaming Proxy"])
async def stream_media(
    request: Request,
    url: str = Query(..., description="رابط googlevideo المباشر المراد بثه بتقطيع ذكي لتجاوز خنق السرعة"),
    size: Optional[int] = Query(None, description="إجمالي حجم الملف بالبايت إن توفر مسبقاً"),
    mime: Optional[str] = Query(None, description="نوع الميديا اختياري (مثل video/mp4 أو audio/mp4)")
):
    """
    بث الفيديو أو الصوت عبر تقنية Bounded Range Chunks (10MB):
    - يتجاوز خنق السرعة (Throttling) الذي يفرضه يوتيوب على المتصفحات (~32KB/s).
    - يدعم الـ Seeking الفوري بدون إعادة تحميل الملف بالكامل.
    - يدعم استجابات HTTP 206 Partial Content القياسية.
    - استهلاك رام منعدم (Zero Memory Buffer) وسرعة فائقة.
    """
    url = url.strip()
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="رابط الفيديو المباشر غير صالح.")

    try:
        total_size, content_type = await get_stream_metadata(url, hint_size=size, hint_mime=mime)
    except Exception as e:
        logger.error(f"Failed to probe metadata for stream: {e}")
        raise HTTPException(status_code=502, detail=f"فشل الاتصال بمصدر الفيديو: {str(e)}")

    base_headers = {
        "Content-Type": content_type,
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
        "Access-Control-Allow-Headers": "Range, Content-Type, Accept, Origin, User-Agent",
        "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges, Content-Type",
        "Cache-Control": "public, max-age=3600"
    }

    # التعامل مع طلبات HEAD (فحص مسبق من المشغل)
    if request.method == "HEAD":
        if total_size > 0:
            base_headers["Content-Length"] = str(total_size)
        return Response(status_code=200, headers=base_headers)

    range_header = request.headers.get("range")
    if range_header:
        start, end = parse_range_header(range_header, total_size)
        if start is None:
            start = 0
            end = (total_size - 1) if total_size > 0 else None

        if total_size > 0 and start >= total_size:
            err_headers = {
                "Content-Range": f"bytes */{total_size}",
                "Accept-Ranges": "bytes",
                "Access-Control-Allow-Origin": "*"
            }
            return Response(status_code=416, headers=err_headers)

        if end is None and total_size > 0:
            end = total_size - 1

        if end is None:
            end = start + DEFAULT_CHUNK_SIZE - 1

        content_length = end - start + 1
        content_range = f"bytes {start}-{end}/{total_size if total_size > 0 else '*'}"

        resp_headers = {
            **base_headers,
            "Content-Range": content_range,
            "Content-Length": str(content_length),
        }

        return StreamingResponse(
            stream_chunked_response(url, start_byte=start, end_byte=end),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            headers=resp_headers,
            media_type=content_type
        )
    else:
        # طلب بدون Range (GET كامل)
        end = (total_size - 1) if total_size > 0 else (DEFAULT_CHUNK_SIZE * 50)
        resp_headers = {**base_headers}
        if total_size > 0:
            resp_headers["Content-Length"] = str(total_size)

        return StreamingResponse(
            stream_chunked_response(url, start_byte=0, end_byte=end),
            status_code=status.HTTP_200_OK,
            headers=resp_headers,
            media_type=content_type
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
