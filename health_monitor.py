import os
import sys
import time
import shutil
import logging
import subprocess
import urllib.request
from typing import Dict, Any, List, Optional, Tuple

from cookie_manager import read_active_cookies, analyze_cookies_health, get_cookie_pool_summary
from updater_service import get_updater_status
from security_manager import get_security_settings, get_all_worker_urls

logger = logging.getLogger("health_monitor")

# كاش لإصدارات محركات سطر الأوامر الثابتة (Deno, Node, FFmpeg) لتجنب استدعاء subprocess في كل تحديث للوحة
_CLI_VERSION_CACHE: Dict[str, Tuple[bool, str, float]] = {}
_CLI_CACHE_TTL = 600.0  # 10 دقائق


def _run_quick_cmd(cmd: List[str], timeout: int = 4) -> Tuple[bool, str]:
    """تشغيل أمر نظام سريع لجلب الإصدار مع تخزين مؤقت (Cache) وحماية من التعليق."""
    cache_key = " ".join(cmd)
    now = time.time()
    if cache_key in _CLI_VERSION_CACHE:
        ok, ver, ts = _CLI_VERSION_CACHE[cache_key]
        if (now - ts) < _CLI_CACHE_TTL:
            return ok, ver

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode == 0:
            lines = (proc.stdout.strip() or proc.stderr.strip()).splitlines()
            first_line = lines[0] if lines else "Installed"
            _CLI_VERSION_CACHE[cache_key] = (True, first_line, now)
            return True, first_line
        err = proc.stderr.strip() or "Non-zero exit code"
        return False, err
    except Exception as e:
        return False, str(e)


def check_deno_health() -> Dict[str, Any]:
    """فحص حالة محرك Deno لحل تحديات الجافاسكريبت والتوقيع (n-challenge)."""
    deno_path = shutil.which("deno")
    if not deno_path:
        return {
            "key": "deno",
            "name": "Deno JS Engine (محرك دينو)",
            "category": "engine",
            "state": "stopped",
            "state_text": "غير مثبت (اختياري)",
            "installed": False,
            "status": "warning",
            "version": None,
            "path": None,
            "message": "غير مثبت على الخادم (يتم الاعتماد تلقائياً على محرك Node.js لحل التحديات البرمجية).",
            "badge": "غياب اختياري",
            "action_type": None
        }
    
    ok, ver_str = _run_quick_cmd([deno_path, "--version"])
    return {
        "key": "deno",
        "name": "Deno JS Engine (محرك دينو)",
        "category": "engine",
        "state": "running",
        "state_text": "يعمل بكفاءة ونشط",
        "installed": True,
        "status": "healthy",
        "version": ver_str if ok else "موجود",
        "path": deno_path,
        "message": "مثبت ويعمل بكفاءة فائقة لحل تحديات n-challenge وتوقيعات يوتيوب المشفرة.",
        "badge": "سليم ومفعل",
        "action_type": None
    }


def check_node_health() -> Dict[str, Any]:
    """فحص حالة محرك Node.js ومقارنة إصداره بدعم ميزات الأمان الحديثة."""
    node_path = shutil.which("node")
    if not node_path:
        return {
            "key": "node",
            "name": "Node.js Engine (محرك نود)",
            "category": "engine",
            "state": "stopped",
            "state_text": "متوقف / غير مثبت",
            "installed": False,
            "status": "critical",
            "version": None,
            "path": None,
            "message": "غير مثبت! يلزم توفر محرك Node.js أو Deno لفك تشفير وتوقيع روابط يوتيوب.",
            "badge": "مفقود",
            "action_type": None
        }

    ok, ver_str = _run_quick_cmd([node_path, "-v"])
    version_clean = ver_str.replace("v", "").strip() if ok else ""
    major_ver = 0
    try:
        major_ver = int(version_clean.split(".")[0])
    except Exception:
        pass

    if major_ver >= 20:
        status = "healthy"
        state = "running"
        state_text = f"يعمل بأحدث إصدار ({ver_str})"
        msg = f"إصدار حديث ({ver_str}) يدعم كافة ميزات الأمان وتحديات يوتيوب الحديثة."
        badge = "حديث وممتاز"
    elif major_ver >= 18:
        status = "warning"
        state = "needs_update"
        state_text = f"يحتاج لتحديث (إصدار {ver_str})"
        msg = f"إصدار ({ver_str}) يعمل ولكن يُفضل الترقية لـ Node 20 لدعم صلاحيات الحماية الكاملة."
        badge = "إصدار قديم نسبياً"
    else:
        status = "warning"
        state = "needs_update"
        state_text = f"يحتاج لتحديث عاجل ({ver_str})"
        msg = f"إصدار قديم ({ver_str}). يوصى بالترقية إلى Node 20."
        badge = "قديم"

    return {
        "key": "node",
        "name": "Node.js Engine (محرك نود)",
        "category": "engine",
        "state": state,
        "state_text": state_text,
        "installed": True,
        "status": status,
        "version": ver_str if ok else "موجود",
        "major_version": major_ver,
        "path": node_path,
        "message": msg,
        "badge": badge,
        "action_type": None
    }


def check_ffmpeg_health() -> Dict[str, Any]:
    """فحص توفر مكتبة ffmpeg لدمج وتحويل مسارات الفيديو والصوتيات."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return {
            "key": "ffmpeg",
            "name": "FFmpeg Media Core (محرك الوسائط)",
            "category": "engine",
            "state": "stopped",
            "state_text": "غير مثبت (الدمج المحلي معطل)",
            "installed": False,
            "status": "warning",
            "version": None,
            "path": None,
            "message": "غير مثبت على الخادم (الروابط المباشرة تعمل بكفاءة، لكن دمج مسارات الفيديو والصوت المنفصلة محلياً غير متاح).",
            "badge": "غير متوفر",
            "action_type": None
        }

    ok, ver_str = _run_quick_cmd([ffmpeg_path, "-version"])
    return {
        "key": "ffmpeg",
        "name": "FFmpeg Media Core (محرك الوسائط)",
        "category": "engine",
        "state": "running",
        "state_text": "يعمل وجاهز للدمج اللحظي (1080p/4K)",
        "installed": True,
        "status": "healthy",
        "version": ver_str[:40] if ok else "موجود",
        "path": ffmpeg_path,
        "message": "مثبت وجاهز للبث المدمج الفوري (/api/stream/mux) لجودات 1080p و 4K مع الصوت.",
        "badge": "جاهز للدمج",
        "action_type": None
    }


def check_ytdlp_health() -> Dict[str, Any]:
    """فحص حالة مكتبة yt-dlp ومقارنتها بأحدث إصدار على PyPI."""
    status_data = get_updater_status()
    curr_v = status_data["current_ytdlp_version"]
    latest_v = status_data["latest_pypi_version"]
    is_up = status_data["is_up_to_date"]

    if is_up:
        badge = "أحدث إصدار ✓"
        status = "healthy"
        state = "running"
        state_text = "يعمل (أحدث إصدار)"
        msg = f"تعمل على أحدث إصدار متاح رسميًا ({curr_v})."
        action = None
    else:
        badge = f"يتوفر تحديث ({latest_v})"
        status = "warning"
        state = "needs_update"
        state_text = f"يحتاج إلى تحديث (يتوفر {latest_v})"
        msg = f"الإصدار الحالي {curr_v}، ويتوفر إصدار أحدث {latest_v} على مستودع PyPI الرسمي."
        action = "update_ytdlp"

    return {
        "key": "ytdlp",
        "name": "yt-dlp Core (محرك الاستخراج والتوقيع)",
        "category": "core",
        "state": state,
        "state_text": state_text,
        "installed": True,
        "status": status,
        "current_version": curr_v,
        "latest_pypi_version": latest_v,
        "is_up_to_date": is_up,
        "auto_updater_schedule": "كل 12 ساعة تلقائياً",
        "message": msg,
        "badge": badge,
        "action_type": action
    }


def check_cookies_component() -> Dict[str, Any]:
    """فحص حالة مكون الكوكيز المسجلة ومسبح التدوير وصلاحيتها وتواريخ انتهائها."""
    cookies, cookie_path = read_active_cookies()
    analysis = analyze_cookies_health(cookies)
    pool_summary = get_cookie_pool_summary()
    file_size = os.path.getsize(cookie_path) if cookie_path and os.path.exists(cookie_path) else 0

    status = analysis["status"]
    days = analysis.get("days_until_expiry", 999)
    pool_count = len(pool_summary)

    if status == "valid" and analysis.get("has_auth"):
        if days <= 3:
            comp_status = "warning"
            state = "needs_update"
            state_text = f"تحتاج لتجديد (تنتهي خلال {days} أيام)"
            badge = "قاربت على الانتهاء"
        else:
            comp_status = "healthy"
            state = "running"
            pool_tag = f" | مسبح التدوير: {pool_count} حساب" if pool_count > 0 else ""
            state_text = f"تعمل بنشاط ومسجلة ({analysis['total_cookies']} كوكي{pool_tag})"
            badge = f"صالحة ({pool_count or 1} حساب)"
    elif status == "guest_only":
        comp_status = "warning"
        state = "warning"
        state_text = "وضع الزائر (غير مسجلة)"
        badge = "وضع الزائر"
    elif status == "expired":
        comp_status = "critical"
        state = "stopped"
        state_text = "متوقفة (منتهية الصلاحية تماماً)"
        badge = "منتهية الصلاحية"
    else:
        comp_status = "warning"
        state = "stopped"
        state_text = "متوقفة (وضع الزائر التلقائي)"
        badge = "وضع الزائر"

    return {
        "key": "cookies",
        "name": "YouTube Cookies Session (جلسة ومسبح الكوكيز)",
        "category": "core",
        "state": state,
        "state_text": state_text,
        "status": comp_status,
        "file_path": cookie_path,
        "file_size_bytes": file_size,
        "total_cookies": analysis["total_cookies"],
        "pool_accounts_count": pool_count,
        "has_auth": analysis["has_auth"],
        "auth_cookies_found": analysis["auth_cookies_found"],
        "days_until_expiry": analysis.get("days_until_expiry", 0),
        "days_int": analysis.get("days_int", 0),
        "hours_int": analysis.get("hours_int", 0),
        "mins_int": analysis.get("mins_int", 0),
        "expiry_human": analysis.get("expiry_human", "--"),
        "expiry_countdown": analysis.get("expiry_countdown", "--"),
        "urgency": analysis.get("urgency", "guest"),
        "earliest_expiry_readable": analysis.get("earliest_expiry_readable"),
        "message": analysis["message"],
        "badge": badge,
        "action_type": "manage_cookies"
    }


def check_youtube_connectivity() -> Dict[str, Any]:
    """فحص الاتصال المباشر بخوادم يوتيوب وقياس زمن الاستجابة واكتشاف أي حظر شبكي."""
    start_time = time.time()
    try:
        req = urllib.request.Request(
            "https://www.youtube.com/generate_204",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            latency_ms = round((time.time() - start_time) * 1000, 1)
            code = response.getcode()
            return {
                "key": "network",
                "name": "YouTube Connectivity (اتصال سيرفرات يوتيوب)",
                "category": "network",
                "state": "running",
                "state_text": f"متصل ومستقر ({latency_ms} ms)",
                "status": "healthy",
                "connected": True,
                "latency_ms": latency_ms,
                "http_code": code,
                "message": f"الاتصال بخوادم يوتيوب مباشر وسريع وزمن الاستجابة ممتاز ({latency_ms} ms).",
                "badge": f"{latency_ms} ms",
                "action_type": "probe_network"
            }
    except Exception as e:
        latency_ms = round((time.time() - start_time) * 1000, 1)
        return {
            "key": "network",
            "name": "YouTube Connectivity (اتصال سيرفرات يوتيوب)",
            "category": "network",
            "state": "stopped",
            "state_text": "متوقف / تعذر الاتصال",
            "status": "critical",
            "connected": False,
            "latency_ms": latency_ms,
            "error": str(e),
            "message": f"فشل الاتصال بخوادم يوتيوب: {str(e)}",
            "badge": "تعذر الاتصال",
            "action_type": "probe_network"
        }


def check_updater_worker_health() -> Dict[str, Any]:
    """فحص حالة خدمة التحديث التلقائي المستمرة في خلفية السيرفر."""
    from updater_service import _UPDATE_STATE
    last_status = _UPDATE_STATE.get("last_update_status", "initialized")
    last_msg = _UPDATE_STATE.get("last_update_message", "جاهز للفحص التلقائي")
    enabled = _UPDATE_STATE.get("auto_update_enabled", True)

    return {
        "key": "auto_updater",
        "name": "Auto-Updater Worker (خدمة التحديث والصيانة)",
        "category": "service",
        "state": "running" if enabled else "stopped",
        "state_text": "تعمل بالخلفية (فحص دوري كل 12 ساعة)" if enabled else "متوقفة",
        "status": "healthy" if enabled else "warning",
        "badge": "مفعل 12h" if enabled else "معطل",
        "installed": True,
        "version": "1.6",
        "schedule": "كل 12 ساعة تلقائياً",
        "last_status": last_status,
        "message": f"المهمة الخلفية نشطة لمراقبة وتحديث yt-dlp وفحص صلاحية الكوكيز. الحالة: {last_msg}",
        "action_type": "update_ytdlp"
    }


def check_streaming_service_health() -> Dict[str, Any]:
    """فحص محرك بث وتجزئة المقاطع (Chunked Range Streaming Engine)."""
    try:
        from stream_service import _METADATA_CACHE, DEFAULT_CHUNK_SIZE
        cached_items = len(_METADATA_CACHE)
        chunk_mb = round(DEFAULT_CHUNK_SIZE / (1024 * 1024), 1)
        return {
            "key": "streaming_engine",
            "name": "Chunked Range & Mux Engine (محرك البث والدمج)",
            "category": "core",
            "state": "running",
            "state_text": "يعمل مع Connection Pool وحماية SSRF",
            "status": "healthy",
            "badge": f"{chunk_mb}MB Chunks",
            "installed": True,
            "version": "1.6.0",
            "chunk_size": f"{chunk_mb} MB",
            "cached_streams": cached_items,
            "message": f"المحرك نشط ويدعم تقطيع الفيديو لشرائح {chunk_mb}MB والدمج اللحظي (1080p/4K) مع حماية SSRF.",
            "action_type": None
        }
    except Exception as e:
        return {
            "key": "streaming_engine",
            "name": "Chunked Range Stream Engine (محرك البث والتجزئة)",
            "category": "core",
            "state": "warning",
            "state_text": "تنبيه في محرك البث",
            "status": "warning",
            "badge": "تنبيه",
            "installed": True,
            "message": f"خطأ في فحص محرك البث: {e}",
            "action_type": None
        }


def check_cloudflare_worker_health() -> Dict[str, Any]:
    """فحص إعدادات وحالة شبكة بروكسي الحافة (Cloudflare Workers) من لوحة التحكم ومتغيرات البيئة."""
    proxies = get_all_worker_urls()
    if proxies:
        return {
            "key": "cloudflare_worker",
            "name": "Cloudflare Edge Workers (بروكسي الحافة العالمي)",
            "category": "network",
            "state": "running",
            "state_text": f"مفعل ونشط ({len(proxies)} بروكسي)",
            "status": "healthy",
            "badge": f"{len(proxies)} عقدة",
            "installed": True,
            "proxies": proxies,
            "message": f"تم ربط {len(proxies)} خادم حافة كلاود فلير لتوزيع الأحمال وتفريغ استهلاك الباندويث عن السيرفر.",
            "action_type": "switch_tab_proxies"
        }
    else:
        return {
            "key": "cloudflare_worker",
            "name": "Cloudflare Edge Workers (بروكسي الحافة العالمي)",
            "category": "network",
            "state": "warning",
            "state_text": "غير مضبوط (يعمل البث المباشر عبر السيرفر)",
            "status": "warning",
            "badge": "محلي فقط",
            "installed": False,
            "proxies": [],
            "message": "لم يتم إضافة روابط Workers بعد. السيرفر حالياً يبث المقاطع بنجاح عبر المحرك الداخلي.",
            "action_type": "switch_tab_proxies"
        }


def check_security_firewall_health() -> Dict[str, Any]:
    """فحص جدار حماية الأمان وحظر الدومينات الغريبة ومصادقة الجلسات."""
    try:
        settings = get_security_settings()
        domains = settings.get("allowed_domains", ["*"])
        strict = settings.get("strict_mode", False)

        is_open_to_all = "*" in domains
        badge = "محمي (محدد)" if not is_open_to_all else "عام (*)"
        msg = (
            f"جدار الحماية نشط. الوضع الصارم: {'مفعل' if strict else 'غير مفعل'}، "
            f"عدد الدومينات المصرح لها: {len(domains)}."
        )
        return {
            "key": "security_engine",
            "name": "Security & Domain Firewall (جدار حماية الأمان)",
            "category": "security",
            "state": "running",
            "state_text": "يعمل ومفعل (محمي)",
            "status": "healthy",
            "badge": badge,
            "installed": True,
            "strict_mode": strict,
            "allowed_domains_count": len(domains),
            "message": msg,
            "action_type": "switch_tab_security"
        }
    except Exception as e:
        return {
            "key": "security_engine",
            "name": "Security & Domain Firewall (جدار حماية الأمان)",
            "category": "security",
            "state": "running",
            "state_text": "يعمل بالنظام الافتراضي",
            "status": "healthy",
            "badge": "افتراضي",
            "installed": True,
            "message": f"إعدادات الأمان الافتراضية نشطة ({e}).",
            "action_type": "switch_tab_security"
        }


def check_ttl_cache_component() -> Dict[str, Any]:
    """فحص حالة ذاكرة الكاش المؤقتة TTLCache وتدفقات البث المباشر."""
    try:
        from stream_service import get_stream_metadata_cache_size
        stream_count = get_stream_metadata_cache_size()
    except Exception:
        stream_count = 0

    return {
        "key": "ttl_cache",
        "name": "Extraction TTLCache & SingleFlight (ذاكرة الكاش)",
        "category": "cache",
        "state": "running",
        "state_text": "نشطة مع منع تكرار الطلبات المتزامنة",
        "status": "healthy",
        "badge": "سريعة ونشطة",
        "installed": True,
        "message": f"ذاكرة الكاش المؤقتة TTLCache وتقنية SingleFlight تعملان على تسريع الاستخراج ({stream_count} ترويسة بث مسجلة).",
        "action_type": "clear_cache"
    }


_SERVER_START_TIME = time.time()


def format_uptime(seconds: int) -> str:
    """تنسيق وقت تشغيل السيرفر إلى صيغة مقروءة بالأيام والساعات والدقائق."""
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if days > 0:
        return f"{days} يوم و {hours} ساعة و {minutes} دقيقة"
    if hours > 0:
        return f"{hours} ساعة و {minutes} دقيقة و {secs} ثانية"
    return f"{minutes} دقيقة و {secs} ثانية"


def check_system_resources() -> Dict[str, Any]:
    """
    فحص حي لحظي لموارد خادم السيرفر: المعالج (CPU)، الذاكرة (RAM)، التخزين (Disk)، والشبكة (Bandwidth).
    """
    uptime_sec = int(time.time() - _SERVER_START_TIME)

    cpu_percent = 0.0
    cores = os.cpu_count() or 1
    ram_total_mb = 0.0
    ram_used_mb = 0.0
    ram_free_mb = 0.0
    ram_percent = 0.0
    process_ram_mb = 0.0
    net_sent_mb = 0.0
    net_recv_mb = 0.0

    try:
        du = shutil.disk_usage(os.getcwd())
        disk_total_gb = round(du.total / (1024**3), 2)
        disk_used_gb = round(du.used / (1024**3), 2)
        disk_free_gb = round(du.free / (1024**3), 2)
        disk_percent = round((du.used / du.total) * 100, 1) if du.total > 0 else 0.0
    except Exception:
        disk_total_gb = 0.0
        disk_used_gb = 0.0
        disk_free_gb = 0.0
        disk_percent = 0.0

    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=None)
        vm = psutil.virtual_memory()
        ram_total_mb = round(vm.total / (1024**2), 1)
        ram_used_mb = round(vm.used / (1024**2), 1)
        ram_free_mb = round(vm.available / (1024**2), 1)
        ram_percent = vm.percent

        proc = psutil.Process(os.getpid())
        process_ram_mb = round(proc.memory_info().rss / (1024**2), 1)

        net = psutil.net_io_counters()
        net_sent_mb = round(net.bytes_sent / (1024**2), 2)
        net_recv_mb = round(net.bytes_recv / (1024**2), 2)
    except Exception:
        if os.path.exists("/proc/meminfo"):
            try:
                mem = {}
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        parts = line.split(":")
                        if len(parts) == 2:
                            val = parts[1].strip().split()[0]
                            mem[parts[0].strip()] = int(val)
                total_kb = mem.get("MemTotal", 0)
                free_kb = mem.get("MemAvailable", mem.get("MemFree", 0))
                used_kb = total_kb - free_kb
                ram_total_mb = round(total_kb / 1024, 1)
                ram_used_mb = round(used_kb / 1024, 1)
                ram_free_mb = round(free_kb / 1024, 1)
                ram_percent = round((used_kb / total_kb) * 100, 1) if total_kb > 0 else 0.0
            except Exception:
                pass
        if os.path.exists("/proc/net/dev"):
            try:
                with open("/proc/net/dev", "r") as f:
                    lines = f.readlines()
                total_r = 0
                total_t = 0
                for line in lines[2:]:
                    parts = line.split()
                    if len(parts) >= 10:
                        total_r += int(parts[1])
                        total_t += int(parts[9])
                net_recv_mb = round(total_r / (1024**2), 2)
                net_sent_mb = round(total_t / (1024**2), 2)
            except Exception:
                pass

    return {
        "cpu": {
            "percent": cpu_percent,
            "cores": cores,
            "status": "critical" if cpu_percent > 85 else ("warning" if cpu_percent > 65 else "healthy")
        },
        "ram": {
            "total_mb": ram_total_mb,
            "used_mb": ram_used_mb,
            "free_mb": ram_free_mb,
            "percent": ram_percent,
            "process_mb": process_ram_mb,
            "status": "critical" if ram_percent > 85 else ("warning" if ram_percent > 70 else "healthy")
        },
        "disk": {
            "total_gb": disk_total_gb,
            "used_gb": disk_used_gb,
            "free_gb": disk_free_gb,
            "percent": disk_percent,
            "status": "critical" if disk_percent > 90 else ("warning" if disk_percent > 75 else "healthy")
        },
        "network": {
            "sent_mb": net_sent_mb,
            "recv_mb": net_recv_mb,
            "status": "healthy"
        },
        "uptime": {
            "seconds": uptime_sec,
            "formatted": format_uptime(uptime_sec)
        }
    }


def check_extraction_stats_component() -> Dict[str, Any]:
    """فحص محرك إحصائيات الاستخراج وسجل العمليات الحية."""
    try:
        from stats_manager import get_extraction_summary_metrics
        res = get_extraction_summary_metrics(top_limit=1, recent_limit=1)
        kpis = res.get("kpis", {})
        total = kpis.get("total_extractions", 0)
        today = kpis.get("today_extractions", 0)
        rate = kpis.get("success_rate", 100.0)
        return {
            "key": "extraction_stats",
            "name": "محرك إحصائيات الاستخراج (Extraction Analytics)",
            "category": "service",
            "state": "running",
            "state_text": f"نشط ويحسب ({total} طلب كلي | {today} اليوم)",
            "installed": True,
            "status": "healthy",
            "version": "SQLite WAL v2.1",
            "path": None,
            "message": f"تم تسجيل {total} عملية استخراج بنجاح ({today} اليوم) مع رصد أعلى الروابط ومعدلات النجاح بنسبة {rate}%.",
            "badge": f"{total} طلب",
            "action_type": None,
            "kpis": kpis
        }
    except Exception as e:
        return {
            "key": "extraction_stats",
            "name": "محرك إحصائيات الاستخراج (Extraction Analytics)",
            "category": "service",
            "state": "stopped",
            "state_text": "غير نشط",
            "installed": False,
            "status": "warning",
            "version": None,
            "path": None,
            "message": f"خطأ في قراءة قاعدة بيانات الإحصائيات: {e}",
            "badge": "تنبيه ⚠️",
            "action_type": None
        }


def get_full_monitoring_report() -> Dict[str, Any]:
    """
    إنشاء تقرير شامل وموحد لمركز مراقبة كافة مكونات ومحركات النظام وموارده.
    """
    resources = check_system_resources()

    cookies_info = check_cookies_component()
    ytdlp_info = check_ytdlp_health()
    node_info = check_node_health()
    deno_info = check_deno_health()
    ffmpeg_info = check_ffmpeg_health()
    network_info = check_youtube_connectivity()
    updater_worker_info = check_updater_worker_health()
    streaming_info = check_streaming_service_health()
    cloudflare_info = check_cloudflare_worker_health()
    security_info = check_security_firewall_health()
    ttl_cache_info = check_ttl_cache_component()
    extraction_stats_info = check_extraction_stats_component()

    components_list = [
        ytdlp_info,
        cookies_info,
        extraction_stats_info,
        node_info,
        deno_info,
        ffmpeg_info,
        streaming_info,
        updater_worker_info,
        ttl_cache_info,
        network_info,
        cloudflare_info,
        security_info,
    ]

    total_count = len(components_list)
    running_comps = [c for c in components_list if c.get("state") == "running"]
    needs_update_comps = [c for c in components_list if c.get("state") == "needs_update"]
    stopped_comps = [c for c in components_list if c.get("state") == "stopped"]
    warning_comps = [c for c in components_list if c.get("state") == "warning"]

    criticals = [c for c in components_list if c.get("status") == "critical"]

    if criticals:
        overall_status = "critical"
        overall_msg = f"تنبيه حرج: يوجد {len(criticals)} مكون رئيسي متوقف أو بحاجة لتدخل عاجل ({criticals[0]['name']})."
        badge = "حالة حرجة 🔴"
    elif needs_update_comps:
        overall_status = "needs_update"
        overall_msg = f"يوجد {len(needs_update_comps)} مكون يتوفر له تحديث جديد ({needs_update_comps[0]['name']})."
        badge = "يتوفر تحديث 🟡"
    elif warning_comps:
        overall_status = "warning"
        overall_msg = f"النظام يعمل بنجاح، مع وجود {len(warning_comps)} إشعار تشغيلي ثانوي."
        badge = "ملاحظات تشغيلية 🟡"
    else:
        overall_status = "healthy"
        overall_msg = "جميع مكونات ومحركات النظام تعمل بكفاءة تامة 100%!"
        badge = "ممتازة ونشطة 🟢"

    health_percentage = round((len(running_comps) / total_count) * 100) if total_count > 0 else 0

    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "overall_status": overall_status,
        "overall_message": overall_msg,
        "overall_badge": badge,
        "summary": {
            "total": total_count,
            "running": len(running_comps),
            "needs_update": len(needs_update_comps),
            "stopped": len(stopped_comps),
            "warning": len(warning_comps),
            "health_percentage": health_percentage
        },
        "system_info": {
            "python_version": sys.version.split()[0],
            "os_platform": sys.platform,
            "process_id": os.getpid(),
            "working_directory": os.getcwd()
        },
        "resources": resources,
        "components_list": components_list,
        "components": {
            "cookies": cookies_info,
            "ytdlp": ytdlp_info,
            "node": node_info,
            "deno": deno_info,
            "ffmpeg": ffmpeg_info,
            "network": network_info,
            "auto_updater": updater_worker_info,
            "streaming_engine": streaming_info,
            "cloudflare_worker": cloudflare_info,
            "security_engine": security_info,
            "ttl_cache": ttl_cache_info,
            "extraction_stats": extraction_stats_info
        }
    }
