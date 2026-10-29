import os
import time
import math
import json
import uuid
import shutil
import socket
import logging
import tempfile
from typing import Dict, Any, List, Optional, Tuple
import yt_dlp
from log_manager import YtDlpLogger
from cookie_manager import (
    get_active_cookie_path,
    save_cookies_content,
    analyze_cookies_health,
    read_active_cookies,
    get_rotated_cookie_content,
    report_cookie_usage
)
from security_manager import get_security_settings, send_system_alert, get_writable_data_dir

logger = logging.getLogger("youtube_service")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = get_writable_data_dir()
DEFAULT_COOKIES_FILE = os.path.join(DATA_DIR, "cookies.txt")
COOKIES_FILE = os.getenv("COOKIES_FILE", DEFAULT_COOKIES_FILE)

# إذا تم تمرير الكوكيز كنص عبر متغير البيئة YOUTUBE_COOKIES (بأي صيغة: JSON أو Netscape)
env_cookies = os.getenv("YOUTUBE_COOKIES")
if env_cookies:
    try:
        res = save_cookies_content(env_cookies, label="Env Variable Cookie")
        logger.info(f"Successfully loaded and parsed YOUTUBE_COOKIES environment variable (Format: {res.get('detected_format')})")
    except Exception as e:
        logger.warning(f"Could not parse YOUTUBE_COOKIES environment variable: {e}")


# كاش لفحص توفر IPv6 على المضيف لتجنب المحاولات الفاشلة المتكررة
_IPV6_STATUS_CACHE: Dict[str, Any] = {
    "checked_at": 0.0,
    "supported": False,
    "detail": "Not checked"
}
_IPV6_CACHE_TTL = 600.0  # 10 دقائق


def _ensure_challenge_solver_cached():
    """
    التأكد من تهيئة كاش مكتبة فك التحديات (challenge-solver/lib) محلياً.
    هذا يضمن أن Deno يحل تحديات n-challenge فوراً دون الحاجة للاتصال بـ GitHub عبر IPv6.
    """
    try:
        bundled_cache = os.path.join(BASE_DIR, "challenge_solver_cache.json")
        if os.path.exists(bundled_cache):
            with yt_dlp.YoutubeDL() as ydl:
                cached = ydl.cache.load("challenge-solver", "lib")
                if not cached or not isinstance(cached, dict) or not cached.get("code"):
                    with open(bundled_cache, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    ydl.cache.store("challenge-solver", "lib", data)
                    logger.info("Successfully populated yt-dlp challenge-solver cache from bundled asset.")
    except Exception as e:
        logger.warning(f"Could not initialize challenge-solver cache: {e}")


# تهيئة الكاش مسبقاً
_ensure_challenge_solver_cached()


def get_cookie_file_path() -> Optional[str]:
    """العثور على مسار ملف الكوكيز المؤكد مع التحقق من وجود أسطر كوكيز فعلية."""
    return get_active_cookie_path()


def format_bytes(size_bytes: Optional[int]) -> Optional[str]:
    """تحويل حجم الملف بالبايت إلى صيغة مقروءة (MB, GB, إلخ)."""
    if size_bytes is None or size_bytes <= 0:
        return None
    units = ["B", "KB", "MB", "GB", "TB"]
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {units[i]}"


def format_duration(seconds: Optional[int]) -> Optional[str]:
    """تحويل مدة الفيديو بالثواني إلى صيغة دقيقة:ثانية أو ساعة:دقيقة:ثانية."""
    if seconds is None:
        return None
    seconds = int(seconds)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _get_js_runtime_config() -> Dict[str, Any]:
    """اكتشاف محركات جافاسكريبت المتاحة (Deno أو Node.js) لحل تحديات البوت والتوقيع في يوتيوب."""
    runtimes = {}
    if shutil.which("deno"):
        runtimes['deno'] = {}
    if shutil.which("node"):
        runtimes['node'] = {}
    return runtimes


def check_ipv6_support(force_refresh: bool = False) -> Tuple[bool, str]:
    """فحص سريع (مع كاش 10 دقائق) لوجود مسار واتصال IPv6 فعّال بالإنترنت."""
    now = time.time()
    if not force_refresh and (now - _IPV6_STATUS_CACHE["checked_at"]) < _IPV6_CACHE_TTL:
        return _IPV6_STATUS_CACHE["supported"], _IPV6_STATUS_CACHE["detail"]

    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        s.settimeout(1.5)
        s.connect(('2001:4860:4860::8888', 53))
        local_ip = s.getsockname()[0]
        s.close()
        _IPV6_STATUS_CACHE.update({"checked_at": now, "supported": True, "detail": local_ip})
        return True, local_ip
    except Exception as e:
        err_str = str(e)
        _IPV6_STATUS_CACHE.update({"checked_at": now, "supported": False, "detail": err_str})
        return False, err_str


def _build_ipv6_opts(sec_cfg: Dict[str, Any], has_cookies: bool) -> Dict[str, Any]:
    """
    بناء خيارات IPv6 لـ yt-dlp بذكاء:
    يتم تفعيل ربط source_address='::' فقط إذا كان الخيار مفعلاً وكان المضيف يدعم توجيه IPv6 فعلياً،
    لتجنب إضاعة الوقت في محاولات اتصال فاشلة على بيئات IPv4 فقط.
    """
    opts = {}
    if not sec_cfg.get("force_ipv6", True):
        return opts

    ipv6_ok, _ = check_ipv6_support()
    if not ipv6_ok:
        return opts

    opts['source_address'] = '::'
    opts['force_ipv6'] = True

    if has_cookies:
        logger.info("IPv6 source binding ('::') active with cookies for YouTube extraction.")
    else:
        logger.info("IPv6 source binding ('::') active in guest mode for YouTube extraction.")

    return opts


def _run_yt_dlp(url: str, use_cookies: bool = True, custom_clients: Optional[List[str]] = None) -> Dict[str, Any]:
    """تنفيذ استخراج yt-dlp بأعلى سرعة ودون أي تأخير مصطنع مع دعم تدوير الكوكيز."""
    ydl_opts: Dict[str, Any] = {
        'quiet': False,
        'no_warnings': False,
        'skip_download': True,
        'extract_flat': False,
        'noplaylist': True,
        'logger': YtDlpLogger(),
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
        'format_sort': ['lang:orig', 'lang', 'quality', 'res', 'fps'],
        'remote_components': {'ejs:github'},
        'socket_timeout': 15,
    }

    runtime_cookie = None
    pool_entry_id = None

    sec_cfg = get_security_settings()

    cookie_content = None
    if use_cookies:
        cookie_content, pool_entry_id = get_rotated_cookie_content()

    will_use_cookies = bool(use_cookies and cookie_content and len(cookie_content.strip()) > 20)

    # تطبيق خيارات IPv6 الانتقائية الذكية
    ipv6_opts = _build_ipv6_opts(sec_cfg, has_cookies=will_use_cookies)
    ydl_opts.update(ipv6_opts)

    if sec_cfg.get("use_oauth2"):
        ydl_opts['username'] = 'oauth2'
        ydl_opts['password'] = ''
        logger.info("Using OAuth2 authentication.")

    js_conf = _get_js_runtime_config()
    if js_conf:
        ydl_opts['js_runtimes'] = js_conf

    if use_cookies:
        if will_use_cookies:
            runtime_cookie = os.path.join(tempfile.gettempdir(), f"yt_cookies_{uuid.uuid4().hex}.txt")
            with open(runtime_cookie, "w", encoding="utf-8") as cf:
                cf.write(cookie_content)
            ydl_opts['cookiefile'] = runtime_cookie
            logger.info(f"Using active cookie session (pool_id={pool_entry_id or 'disk'})")
        else:
            logger.info("Cookie requested but no valid cookies found; proceeding as guest.")
    else:
        logger.info("Explicitly attempting extraction without cookies (guest mode).")

    extractor_args_youtube = {}

    if custom_clients:
        extractor_args_youtube['player_client'] = custom_clients
        logger.info(f"Using custom player_clients: {custom_clients}")

    po_token = sec_cfg.get("po_token")
    visitor_data = sec_cfg.get("visitor_data")
    # لا نحقن visitor_data الخاص بالزائر عند استخدام كوكيز حساب مسجل حتى لا يتعارض مع جلسة الحساب (DATASYNC_ID)
    if not will_use_cookies:
        if po_token and visitor_data:
            extractor_args_youtube['po_token'] = [f"web+{po_token}", f"mweb+{po_token}"]
            extractor_args_youtube['visitor_data'] = [visitor_data]
            logger.info("Injected PO Token and Visitor Data (Guest mode).")
        elif visitor_data:
            extractor_args_youtube['visitor_data'] = [visitor_data]
    elif po_token:
        extractor_args_youtube['po_token'] = [f"web+{po_token}", f"mweb+{po_token}"]
        logger.info("Injected PO Token with active cookies.")

    if extractor_args_youtube:
        ydl_opts['extractor_args'] = {
            'youtube': extractor_args_youtube
        }

    proxy = os.getenv("YOUTUBE_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        ydl_opts['proxy'] = proxy
        logger.info("Using configured proxy.")

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("No video data returned by yt-dlp.")
            if pool_entry_id:
                report_cookie_usage(pool_entry_id, success=True)
            return info
    except Exception as e:
        err_msg = str(e)
        err_lower = err_msg.lower()

        if pool_entry_id and any(k in err_lower for k in ["sign in", "reloaded", "bot", "cookies"]):
            report_cookie_usage(pool_entry_id, success=False, error_msg=err_msg)

        if ydl_opts.get('source_address') == '::' and any(kw in err_lower for kw in [
            'no remote ipv6', 'network is unreachable', 'winerror 10051',
            'cant use "::"', "can't use \"::\"", 'address family not supported'
        ]):
            logger.warning("IPv6 failed on host; invalidating IPv6 cache and retrying with IPv4 immediately...")
            _IPV6_STATUS_CACHE.update({"checked_at": time.time(), "supported": False, "detail": err_msg})
            fallback_opts = dict(ydl_opts)
            fallback_opts.pop('source_address', None)
            fallback_opts.pop('force_ipv6', None)
            with yt_dlp.YoutubeDL(fallback_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if not info:
                    raise ValueError("No video data returned by yt-dlp on IPv4 fallback.")
                return info
        raise e
    finally:
        if runtime_cookie and os.path.exists(runtime_cookie):
            try:
                os.remove(runtime_cookie)
            except Exception:
                pass


def extract_youtube_info(url: str) -> Dict[str, Any]:
    """
    استخراج تفاصيل الفيديو والروابط المباشرة المؤقتة مع آلية متطورة متعددة المراحل
    لتجاوز أخطاء البوت أو انتهاء الكوكيز بأفضل أداء ممكن عبر مشغلات بديلة.
    """
    info = None
    last_error = None
    strategy_used = "unknown"

    # التحقق الفعلي من توفر كوكيز صالحة (في المسبح أو على القرص)
    cookie_content, _ = get_rotated_cookie_content()
    has_cookies = bool(cookie_content and len(cookie_content.strip()) > 20)

    # مرحلة 1: المحاولة باستخدام الكوكيز النشطة إذا كانت متوفرة
    if has_cookies:
        try:
            logger.info(f"Strategy 1A (Cookies Standard): Full extraction with cookies for URL: {url}")
            info = _run_yt_dlp(url, use_cookies=True)
            strategy_used = "cookies_standard"
        except Exception as e:
            last_error = e
            logger.warning(f"Strategy 1A (Cookies Standard) failed: {e}")

        if not info:
            try:
                logger.info(f"Strategy 1B (Cookies Multi-Client): Retrying with cookies + tv_downgraded/web_creator/mweb for URL: {url}")
                info = _run_yt_dlp(
                    url,
                    use_cookies=True,
                    custom_clients=['tv_downgraded', 'web_creator', 'mweb', 'web_safari']
                )
                strategy_used = "cookies_multi_client"
            except Exception as e:
                last_error = e
                logger.warning(f"Strategy 1B (Cookies Multi-Client) failed: {e}")

    # مرحلة 2: تجربة مشغل tv_downgraded و web_creator بدون كوكيز
    if not info:
        try:
            logger.info("Strategy 2 (TV Downgraded Guest): Retrying with tv_downgraded without cookies...")
            info = _run_yt_dlp(url, use_cookies=False, custom_clients=['tv_downgraded'])
            strategy_used = "tv_downgraded_guest"
        except Exception as e:
            last_error = e
            logger.warning(f"Strategy 2 (TV Downgraded) failed: {e}")

    # مرحلة 3: تجربة مشغلات الهاتف والواقع الافتراضي android_vr و ios بدون كوكيز
    if not info:
        try:
            logger.info("Strategy 3 (Android VR / iOS Guest): Retrying with android_vr, ios without cookies...")
            info = _run_yt_dlp(url, use_cookies=False, custom_clients=['android_vr', 'ios', 'android'])
            strategy_used = "android_vr_guest"
        except Exception as e:
            last_error = e
            logger.warning(f"Strategy 3 (Android VR) failed: {e}")

    # مرحلة 4: تجربة مشغل web_embedded و mweb بدون كوكيز
    if not info:
        try:
            logger.info("Strategy 4 (Web Embedded Guest): Retrying with web_embedded, mweb without cookies...")
            info = _run_yt_dlp(url, use_cookies=False, custom_clients=['web_embedded', 'mweb'])
            strategy_used = "web_embedded_guest"
        except Exception as e:
            last_error = e
            logger.warning(f"Strategy 4 (Web Embedded) failed: {e}")

    # مرحلة 5: المحاولة كزائر افتراضي (Pure Guest fallback)
    if not info:
        try:
            logger.info("Strategy 5 (Generic Guest): Retrying as standard guest...")
            info = _run_yt_dlp(url, use_cookies=False)
            strategy_used = "guest_default"
        except Exception as e:
            last_error = e
            logger.error(f"Strategy 5 (Generic Guest) failed: {e}")

    if not info:
        err_str = str(last_error) if last_error else "Unknown error"
        if any(k in err_str.lower() for k in ["sign in", "bot", "reloaded"]):
            try:
                send_system_alert(
                    title="فشل جميع استراتيجيات الاستخراج (حظر بوت / انتهاء الكوكيز)",
                    message=f"تعذر استخراج الفيديو `{url}` عبر جميع المراحل الخمس.\nرسالة يوتيوب: `{err_str[:180]}`",
                    level="critical"
                )
            except Exception:
                pass
        raise last_error or RuntimeError("Failed to extract video information across all fallback strategies.")

    # معالجة وتنظيم بيانات الفيديو والجودات
    video_id = info.get("id")
    title = info.get("title")
    duration = info.get("duration")
    thumbnail = info.get("thumbnail")
    uploader = info.get("uploader")
    channel_url = info.get("channel_url")
    view_count = info.get("view_count")
    description = info.get("description", "")
    short_description = (description[:300] + "...") if description and len(description) > 300 else description

    raw_formats: List[Dict[str, Any]] = info.get("formats", [])
    video_with_audio: List[Dict[str, Any]] = []
    video_only: List[Dict[str, Any]] = []
    audio_only: List[Dict[str, Any]] = []

    for f in raw_formats:
        direct_url = f.get("url")
        if not direct_url:
            continue

        vcodec = f.get("vcodec") or "none"
        acodec = f.get("acodec") or "none"
        has_video = vcodec != "none"
        has_audio = acodec != "none"

        filesize = f.get("filesize") or f.get("filesize_approx")
        filesize_str = format_bytes(filesize)

        format_note_str = str(f.get("format_note") or "")
        lang = f.get("language")
        lang_pref = f.get("language_preference") or 0
        
        is_original = bool(
            lang_pref > 0 or 
            "original" in format_note_str.lower() or 
            f.get("is_original") is True
        )
        is_dubbed = bool(
            "dubbed" in format_note_str.lower() or 
            lang_pref < 0
        )

        format_data = {
            "format_id": f.get("format_id"),
            "ext": f.get("ext"),
            "quality_note": f.get("format_note"),
            "resolution": f.get("resolution"),
            "width": f.get("width"),
            "height": f.get("height"),
            "fps": f.get("fps"),
            "filesize_bytes": filesize,
            "filesize_readable": filesize_str,
            "vcodec": vcodec,
            "acodec": acodec,
            "abr_kbps": f.get("abr"),
            "vbr_kbps": f.get("vbr"),
            "container": f.get("container"),
            "protocol": f.get("protocol"),
            "language": lang,
            "language_preference": lang_pref,
            "is_original": is_original and not is_dubbed,
            "audio_channels": f.get("audio_channels"),
            "url": direct_url,
            "direct_url": direct_url,
        }

        if has_video and has_audio:
            video_with_audio.append(format_data)
        elif has_video and not has_audio:
            video_only.append(format_data)
        elif has_audio and not has_video:
            audio_only.append(format_data)

    def sort_by_height(item):
        return (item.get("height") or 0, item.get("fps") or 0, item.get("vbr_kbps") or 0)

    def sort_audio_priority(item):
        is_orig_val = 1 if item.get("is_original") else 0
        lang_pref_val = item.get("language_preference") or 0
        abr_val = item.get("abr_kbps") or 0
        return (is_orig_val, lang_pref_val, abr_val)

    video_with_audio.sort(key=sort_by_height, reverse=True)
    video_only.sort(key=sort_by_height, reverse=True)
    audio_only.sort(key=sort_audio_priority, reverse=True)

    return {
        "status": "success",
        "strategy_used": strategy_used,
        "video_info": {
            "id": video_id,
            "title": title,
            "duration_seconds": duration,
            "duration_readable": format_duration(duration),
            "thumbnail": thumbnail,
            "uploader": uploader,
            "channel_url": channel_url,
            "view_count": view_count,
            "description_preview": short_description,
            "original_url": url,
        },
        "stats": {
            "total_formats": len(raw_formats),
            "video_with_audio_count": len(video_with_audio),
            "video_only_count": len(video_only),
            "audio_only_count": len(audio_only),
        },
        "streams": {
            "video_with_audio": video_with_audio,
            "video_only": video_only,
            "audio_only": audio_only,
        }
    }


def test_cookie_health_live(test_url: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ") -> Dict[str, Any]:
    """
    إجراء فحص حي فوري للكوكيز المسجلة عبر طلب تجريبي وحساب وقت الاستجابة
    """
    start_time = time.time()
    try:
        data = extract_youtube_info(test_url)
        elapsed_sec = round(time.time() - start_time, 2)
        return {
            "success": True,
            "elapsed_seconds": elapsed_sec,
            "video_title": data["video_info"]["title"],
            "uploader": data["video_info"]["uploader"],
            "total_formats": data["stats"]["total_formats"],
            "strategy": data.get("strategy_used"),
            "message": f"تم الاتصال وفحص الروابط بنجاح في {elapsed_sec} ثانية! (عدد الجودات: {data['stats']['total_formats']})"
        }
    except Exception as e:
        elapsed_sec = round(time.time() - start_time, 2)
        return {
            "success": False,
            "elapsed_seconds": elapsed_sec,
            "error": str(e),
            "message": f"فشل الفحص الحي: {str(e)}"
        }
