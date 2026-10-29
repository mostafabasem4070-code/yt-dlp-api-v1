import os
import re
import json
import time
import hmac
import shutil
import hashlib
import secrets
import logging
import tempfile
import urllib.request
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
import bcrypt

logger = logging.getLogger("security_manager")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_RESOLVED_DATA_DIR: Optional[str] = None


def get_writable_data_dir() -> str:
    """
    تحديد مجلد البيانات القابل للكتابة:
    - يجرب أولاً DATA_DIR أو BASE_DIR (/app).
    - إذا كان نظام الملفات للقراءة فقط (Read-only file system كما في hostless.cloud / Kubernetes)،
      ينتقل تلقائياً إلى /tmp/ytdlp_data وينسخ الملفات المبدئية وكاش التحديات إليه.
    """
    global _RESOLVED_DATA_DIR
    if _RESOLVED_DATA_DIR is not None:
        return _RESOLVED_DATA_DIR

    candidate = os.getenv("DATA_DIR", BASE_DIR)
    writable = False
    try:
        os.makedirs(candidate, exist_ok=True)
        probe_file = os.path.join(candidate, f".write_probe_{os.getpid()}")
        with open(probe_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe_file)
        writable = True
    except Exception:
        writable = False

    if not writable:
        candidate = os.path.join(tempfile.gettempdir(), "ytdlp_data")
        os.makedirs(candidate, exist_ok=True)
        os.environ["DATA_DIR"] = candidate
        # توجيه كاش XDG و Config إلى /tmp لضمان قدرة Deno و yt-dlp و Chromium على الكتابة
        tmp_cache = os.path.join(tempfile.gettempdir(), ".cache")
        tmp_config = os.path.join(tempfile.gettempdir(), ".config")
        os.makedirs(tmp_cache, exist_ok=True)
        os.makedirs(tmp_config, exist_ok=True)
        os.environ["XDG_CACHE_HOME"] = tmp_cache
        os.environ["XDG_CONFIG_HOME"] = tmp_config
        solver_src = os.path.join(BASE_DIR, "challenge_solver_cache.json")
        if os.path.exists(solver_src):
            solver_dst_dir = os.path.join(tmp_cache, "yt-dlp", "challenge-solver")
            os.makedirs(solver_dst_dir, exist_ok=True)
            solver_dst = os.path.join(solver_dst_dir, "lib.json")
            if not os.path.exists(solver_dst):
                try:
                    shutil.copy2(solver_src, solver_dst)
                except Exception:
                    pass
        logger.info(f"Root directory is read-only; switched writable DATA_DIR to {candidate}")

    # نسخ الملفات الأولية من BASE_DIR إلى DATA_DIR إن لم تكن موجودة بعد
    if os.path.abspath(candidate) != os.path.abspath(BASE_DIR):
        for fname in ("security_config.json", "sessions.json", "cookies.txt", "cookies_pool.json", "extraction_stats.db"):
            src_p = os.path.join(BASE_DIR, fname)
            dst_p = os.path.join(candidate, fname)
            if os.path.exists(src_p) and not os.path.exists(dst_p):
                try:
                    shutil.copy2(src_p, dst_p)
                except Exception:
                    pass

    _RESOLVED_DATA_DIR = candidate
    return candidate


DATA_DIR = get_writable_data_dir()
CONFIG_FILE = os.path.join(DATA_DIR, "security_config.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "sessions.json")

# Session store loaded from file
_ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days

# In-memory cache for security_config.json to avoid disk I/O on every request
_CONFIG_CACHE: Optional[Dict[str, Any]] = None
_CONFIG_MTIME: float = 0.0

# Alert cooldown tracker (key -> timestamp) to avoid spamming Telegram/Webhook
_ALERT_COOLDOWNS: Dict[str, float] = {}
ALERT_COOLDOWN_SECONDS = 900  # 15 minutes


def _load_sessions():
    global _ACTIVE_SESSIONS
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            now = time.time()
            # تنظيف الجلسات المنتهية تلقائياً عند التحميل
            _ACTIVE_SESSIONS = {
                k: v for k, v in raw.items()
                if isinstance(v, dict) and v.get("expires_at", 0) > now
            }
            if len(_ACTIVE_SESSIONS) != len(raw):
                _save_sessions()
        except Exception as e:
            logger.error(f"Failed to load sessions: {e}")


def _save_sessions():
    try:
        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(_ACTIVE_SESSIONS, f)
    except Exception as e:
        logger.error(f"Failed to save sessions: {e}")


_load_sessions()


def _load_config() -> Dict[str, Any]:
    """تحميل إعدادات الأمان والدومينات مع التخزين المؤقت في الذاكرة (In-Memory Cache)"""
    global _CONFIG_CACHE, _CONFIG_MTIME

    if os.path.exists(CONFIG_FILE):
        try:
            mtime = os.path.getmtime(CONFIG_FILE)
            if _CONFIG_CACHE is not None and mtime == _CONFIG_MTIME:
                return _CONFIG_CACHE

            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                needs_save = False
                if "api_key" not in cfg or not cfg["api_key"]:
                    cfg["api_key"] = os.getenv("API_KEY") or f"sec_{secrets.token_hex(16)}"
                    needs_save = True
                if "worker_pool" not in cfg:
                    cfg["worker_pool"] = []
                    needs_save = True
                if "telegram_bot_token" not in cfg:
                    cfg["telegram_bot_token"] = os.getenv("TELEGRAM_BOT_TOKEN", "")
                    cfg["telegram_chat_id"] = os.getenv("TELEGRAM_CHAT_ID", "")
                    cfg["webhook_url"] = os.getenv("ALERT_WEBHOOK_URL", "")
                    cfg["alerts_enabled"] = bool(cfg["telegram_bot_token"] or cfg["webhook_url"])
                    needs_save = True

                _CONFIG_CACHE = cfg
                _CONFIG_MTIME = mtime
                if needs_save:
                    _save_config(cfg)
                return cfg
        except Exception as e:
            logger.error(f"Failed to load security config: {e}")
            if _CONFIG_CACHE is not None:
                return _CONFIG_CACHE

    if _CONFIG_CACHE is not None:
        return _CONFIG_CACHE

    # القيم الافتراضية مع قراءة متغيرات البيئة إن وجدت
    env_password = os.getenv("ADMIN_PASSWORD") or os.getenv("DASHBOARD_PASSWORD") or "97351294m"
    hashed_pwd = bcrypt.hashpw(env_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    env_domains_raw = os.getenv("ALLOWED_DOMAINS", "*")
    allowed_domains = [d.strip() for d in env_domains_raw.split(",") if d.strip()]
    if not allowed_domains:
        allowed_domains = ["*"]

    env_strict = os.getenv("STRICT_DOMAIN_CHECK", "false").lower() in ("true", "1", "yes")
    default_api_key = os.getenv("API_KEY") or f"sec_{secrets.token_hex(16)}"

    cfg = {
        "admin_password_hash": hashed_pwd,
        "allowed_domains": allowed_domains,
        "strict_mode": env_strict,
        "api_key": default_api_key,
        "worker_pool": [],
        "force_ipv6": True,
        "use_oauth2": False,
        "po_token": "",
        "visitor_data": "",
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "webhook_url": os.getenv("ALERT_WEBHOOK_URL", ""),
        "alerts_enabled": False,
        "updated_at": int(time.time())
    }
    _save_config(cfg)
    return cfg


def _save_config(config: Dict[str, Any]) -> bool:
    """حفظ إعدادات الأمان في ملف JSON دائم وتحديث الكاش الفوري"""
    global _CONFIG_CACHE, _CONFIG_MTIME
    config["updated_at"] = int(time.time())
    _CONFIG_CACHE = config
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        _CONFIG_MTIME = os.path.getmtime(CONFIG_FILE)
        return True
    except Exception as e:
        logger.error(f"Failed to save security config: {e}")
        return False


# ===================== AUTHENTICATION =====================

def verify_admin_password(password: str) -> bool:
    """التحقق من صحة كلمة مرور الإدارة"""
    cfg = _load_config()
    stored_hash = cfg.get("admin_password_hash", "")

    # فحص أيضاً كلمة المرور من متغير البيئة مباشرة إن تغيرت في Railway
    env_pwd = os.getenv("ADMIN_PASSWORD") or os.getenv("DASHBOARD_PASSWORD")
    if env_pwd and hmac.compare_digest(password, env_pwd):
        return True

    # التوافقية مع الهاش القديم SHA256 (مؤقتاً) إذا كان لا يبدأ بصيغة bcrypt
    if stored_hash and not stored_hash.startswith("$2"):
        salt = cfg.get("salt", "")
        test_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        if hmac.compare_digest(stored_hash, test_hash):
            cfg["admin_password_hash"] = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            _save_config(cfg)
            return True
        return False

    try:
        return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
    except Exception:
        return False


def change_admin_password(old_password: str, new_password: str) -> Tuple[bool, str]:
    """تغيير كلمة مرور الإدارة بعد التحقق من القديمة"""
    if not verify_admin_password(old_password):
        return False, "كلمة المرور الحالية غير صحيحة."
    
    if len(new_password) < 6:
        return False, "كلمة المرور الجديدة يجب أن تتكون من 6 أحرف على الأقل."

    cfg = _load_config()
    hashed_pwd = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    cfg["admin_password_hash"] = hashed_pwd
    _save_config(cfg)
    
    # تفريغ الجلسات الحالية لإجبار إعادة تسجيل الدخول
    _ACTIVE_SESSIONS.clear()
    _save_sessions()
    return True, "تم تغيير كلمة المرور بنجاح."


def create_session_token() -> str:
    """إنشاء جلسة دخول مشفرة صالحة لمدة 7 أيام"""
    token = secrets.token_urlsafe(36)
    now = time.time()
    _ACTIVE_SESSIONS[token] = {
        "created_at": now,
        "expires_at": now + SESSION_TTL_SECONDS
    }
    _save_sessions()
    return token


def validate_session_token(token: Optional[str]) -> bool:
    """التحقق من صحة وصلاحية جلسة الدخول"""
    if not token:
        return False

    session = _ACTIVE_SESSIONS.get(token)
    if not session:
        return False

    if time.time() > session.get("expires_at", 0):
        _ACTIVE_SESSIONS.pop(token, None)
        _save_sessions()
        return False

    return True


def revoke_session_token(token: str) -> None:
    """تسجيل الخروج وإلغاء الجلسة"""
    if _ACTIVE_SESSIONS.pop(token, None):
        _save_sessions()


# ===================== DOMAIN WHITELIST & ORIGIN VALIDATION =====================

def normalize_domain(domain_str: str) -> str:
    """
    استخراج النطاق الصافي بدقة بدون بروتوكول، منافذ، مسارات، أو لاحقات.
    """
    raw = domain_str.strip().lower()
    if not raw:
        return ""
    if raw == "*":
        return "*"
    
    if "://" not in raw:
        if raw.startswith("//"):
            raw = "http:" + raw
        else:
            raw = "http://" + raw

    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower().strip()
        if not host and "*" in raw:
            host = raw.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
        return host
    except Exception:
        clean = raw.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
        return clean.strip()


def check_domain_matches(caller: str, pattern: str) -> bool:
    """
    مطابقة ذكية مرنة بين الدومين الطالب والنمط المصرح به.
    """
    caller = caller.lower().strip()
    pattern = pattern.lower().strip()

    if not caller or not pattern:
        return False

    if pattern == "*":
        return True

    if pattern in ("localhost", "127.0.0.1") and caller in ("localhost", "127.0.0.1"):
        return True

    if pattern.startswith("*."):
        root = pattern[2:]
        return caller == root or caller.endswith("." + root)

    if caller == pattern:
        return True

    if caller.endswith("." + pattern):
        return True

    if pattern.startswith("www.") and caller == pattern[4:]:
        return True
    if caller.startswith("www.") and caller[4:] == pattern:
        return True

    return False


def get_all_worker_urls() -> List[str]:
    """
    إرجاع القائمة الموحدة لجميع روابط Cloudflare Workers:
    تجمع بين القائمة المحفوظة في لوحة التحكم (worker_pool) ومتغيرات البيئة (STREAM_PROXY_URL).
    """
    cfg = _load_config()
    pool = list(cfg.get("worker_pool", []))
    env_workers = os.getenv("STREAM_PROXY_URL") or os.getenv("CLOUDFLARE_WORKER_URL") or ""
    if env_workers:
        for w in re.split(r'[\s,;]+', env_workers):
            clean = w.strip().rstrip("/")
            if clean and clean.startswith("http") and clean not in pool:
                pool.append(clean)
    return pool


def get_security_settings() -> Dict[str, Any]:
    """الحصول على كافة إعدادات الأمان والدومينات المصرح لها ومفتاح الـ API"""
    cfg = _load_config()
    domains = cfg.get("allowed_domains", ["*"])
    if not domains:
        domains = ["*"]
    return {
        "allowed_domains": domains,
        "strict_mode": cfg.get("strict_mode", False),
        "api_key": cfg.get("api_key", ""),
        "worker_pool": get_all_worker_urls(),
        "updated_at": cfg.get("updated_at", 0),
        "active_sessions_count": len(_ACTIVE_SESSIONS),
        "force_ipv6": cfg.get("force_ipv6", False),
        "use_oauth2": cfg.get("use_oauth2", False),
        "po_token": cfg.get("po_token", ""),
        "visitor_data": cfg.get("visitor_data", ""),
        "telegram_bot_token": cfg.get("telegram_bot_token", ""),
        "telegram_chat_id": cfg.get("telegram_chat_id", ""),
        "webhook_url": cfg.get("webhook_url", ""),
        "alerts_enabled": cfg.get("alerts_enabled", False)
    }


def add_allowed_domain(domain: str) -> Tuple[bool, str, List[str]]:
    """إضافة دومين جديد إلى قائمة الدومينات المصرح لها"""
    clean = normalize_domain(domain)
    if not clean:
        return False, "اسم الدومين المدخل غير صالح.", []

    cfg = _load_config()
    domains = list(cfg.get("allowed_domains", []))

    if clean != "*" and "*" in domains and len(domains) == 1:
        domains = []

    if clean in domains:
        return True, "الدومين موجود بالفعل في قائمة المصرح لهم.", domains

    domains.append(clean)
    cfg["allowed_domains"] = domains
    _save_config(cfg)
    return True, f"تمت إضافة الدومين ({clean}) بنجاح.", domains


def remove_allowed_domain(domain: str) -> Tuple[bool, str, List[str]]:
    """حذف دومين من قائمة الدومينات المصرح لها"""
    clean = normalize_domain(domain)
    cfg = _load_config()
    domains = list(cfg.get("allowed_domains", []))

    if clean not in domains and domain not in domains:
        return False, "الدومين غير موجود في القائمة.", domains

    domains = [d for d in domains if d != clean and d != domain]
    if not domains:
        domains = ["*"]

    cfg["allowed_domains"] = domains
    _save_config(cfg)
    return True, "تم حذف الدومين بنجاح.", domains


def update_security_preferences(
    strict_mode: bool, 
    allowed_domains: Optional[List[str]] = None, 
    generate_new_api_key: bool = False,
    force_ipv6: Optional[bool] = None,
    use_oauth2: Optional[bool] = None,
    po_token: Optional[str] = None,
    visitor_data: Optional[str] = None,
    telegram_bot_token: Optional[str] = None,
    telegram_chat_id: Optional[str] = None,
    webhook_url: Optional[str] = None,
    alerts_enabled: Optional[bool] = None
) -> Dict[str, Any]:
    """تحديث خيارات الأمان ووضع الفحص الصارم ومفتاح الـ API والتنبيهات"""
    cfg = _load_config()
    cfg["strict_mode"] = bool(strict_mode)

    if allowed_domains is not None:
        cleaned = [normalize_domain(d) for d in allowed_domains if normalize_domain(d)]
        if not cleaned:
            cleaned = ["*"]
        cfg["allowed_domains"] = cleaned

    if generate_new_api_key:
        cfg["api_key"] = f"sec_{secrets.token_hex(16)}"

    if force_ipv6 is not None:
        cfg["force_ipv6"] = force_ipv6
    if use_oauth2 is not None:
        cfg["use_oauth2"] = use_oauth2
    if po_token is not None:
        cfg["po_token"] = po_token.strip()
    if visitor_data is not None:
        cfg["visitor_data"] = visitor_data.strip()
    if telegram_bot_token is not None:
        cfg["telegram_bot_token"] = telegram_bot_token.strip()
    if telegram_chat_id is not None:
        cfg["telegram_chat_id"] = telegram_chat_id.strip()
    if webhook_url is not None:
        cfg["webhook_url"] = webhook_url.strip()
    if alerts_enabled is not None:
        cfg["alerts_enabled"] = bool(alerts_enabled)

    _save_config(cfg)
    return get_security_settings()


# ===================== WORKER POOL MANAGEMENT =====================

def add_worker_url(url: str) -> Tuple[bool, str, List[str]]:
    """إضافة رابط Cloudflare Worker جديد للقائمة"""
    clean = url.strip().rstrip("/")
    if not clean or not clean.startswith("http"):
        return False, "الرابط غير صالح. يجب أن يبدأ بـ http أو https.", []

    cfg = _load_config()
    pool = list(cfg.get("worker_pool", []))

    if clean in pool:
        return True, "الرابط موجود بالفعل في القائمة.", get_all_worker_urls()

    pool.append(clean)
    cfg["worker_pool"] = pool
    _save_config(cfg)
    return True, f"تمت إضافة الرابط ({clean}) بنجاح.", get_all_worker_urls()


def remove_worker_url(url: str) -> Tuple[bool, str, List[str]]:
    """حذف رابط Cloudflare Worker من القائمة"""
    clean = url.strip().rstrip("/")
    cfg = _load_config()
    pool = list(cfg.get("worker_pool", []))

    if clean not in pool:
        return False, "الرابط غير موجود في القائمة.", get_all_worker_urls()

    pool = [w for w in pool if w != clean]
    cfg["worker_pool"] = pool
    _save_config(cfg)
    return True, "تم حذف الرابط بنجاح.", get_all_worker_urls()


def clear_all_worker_urls() -> Tuple[bool, str, List[str]]:
    """حذف جميع روابط Cloudflare Workers من القائمة دفعة واحدة"""
    cfg = _load_config()
    cfg["worker_pool"] = []
    _save_config(cfg)
    return True, "تم حذف جميع روابط البروكسي بنجاح.", get_all_worker_urls()


def regenerate_api_key() -> str:
    """توليد مفتاح API جديد وحفظه فورياً"""
    cfg = _load_config()
    new_key = f"sec_{secrets.token_hex(16)}"
    cfg["api_key"] = new_key
    _save_config(cfg)
    return new_key


def test_domain_authorization(test_input: str) -> Dict[str, Any]:
    """أداة فحص واختبار حية للتحقق مما إذا كان الدومين أو الرابط مصرحاً له أم محظوراً"""
    clean = normalize_domain(test_input)
    cfg = _load_config()
    domains = cfg.get("allowed_domains", ["*"])
    strict = cfg.get("strict_mode", False)

    if not clean:
        return {
            "authorized": False,
            "domain": test_input,
            "normalized": "",
            "reason": "صيغة الدومين أو الرابط غير صالحة."
        }

    if "*" in domains and not strict:
        return {
            "authorized": True,
            "domain": test_input,
            "normalized": clean,
            "reason": "مصرح به تلقائياً (الوضع مفتوح للجميع مع تعطيل الوضع الصارم)."
        }

    for pat in domains:
        if check_domain_matches(clean, pat):
            return {
                "authorized": True,
                "domain": test_input,
                "normalized": clean,
                "reason": f"مصرح به بنجاح (مطابق للقاعدة: {pat})."
            }

    if clean in ("localhost", "127.0.0.1"):
        return {
            "authorized": True,
            "domain": test_input,
            "normalized": clean,
            "reason": "مصرح به (طلب محلي Localhost)."
        }

    return {
        "authorized": False,
        "domain": test_input,
        "normalized": clean,
        "reason": f"مرفوض: الدومين '{clean}' غير مطابق لأي دومين في قائمة المصرح لهم والوضع الصارم مفعل."
    }


def is_request_authorized(
    origin: Optional[str] = None,
    referer: Optional[str] = None,
    host: Optional[str] = None,
    api_key_header: Optional[str] = None,
    auth_token: Optional[str] = None
) -> Tuple[bool, str]:
    """
    التحقق الصارم والموثوق من تصريح الطلب.
    """
    if auth_token and validate_session_token(auth_token):
        return True, "Authorized via Admin Session"

    cfg = _load_config()
    expected_api_key = cfg.get("api_key", "").strip()

    if expected_api_key and api_key_header:
        clean_header = api_key_header.strip()
        if hmac.compare_digest(expected_api_key, clean_header):
            return True, "Authorized via API Key"

    allowed_domains = cfg.get("allowed_domains", ["*"])
    strict_mode = cfg.get("strict_mode", False)

    if "*" in allowed_domains and not strict_mode:
        return True, "Open access (Wildcard allowed)"

    caller_domains_to_test = []
    if origin:
        c_orig = normalize_domain(origin)
        if c_orig:
            caller_domains_to_test.append(c_orig)
    if referer:
        c_ref = normalize_domain(referer)
        if c_ref and c_ref not in caller_domains_to_test:
            caller_domains_to_test.append(c_ref)

    for caller in caller_domains_to_test:
        for pattern in allowed_domains:
            if check_domain_matches(caller, pattern):
                return True, f"Domain allowed: {caller} (matched {pattern})"

    if host:
        host_clean = normalize_domain(host)
        if host_clean in ("localhost", "127.0.0.1"):
            return True, "Localhost host allowed"

    for caller in caller_domains_to_test:
        if caller in ("localhost", "127.0.0.1"):
            return True, "Localhost caller allowed"

    if not caller_domains_to_test:
        return False, "طلب غير مصرح به: لم يتم إرسال ترويسة Origin أو Referer مطابقة، ولم يتم تقديم مفتاح API صالح."

    tested_str = ", ".join(caller_domains_to_test)
    return False, f"طلب مرفوض: الدومين الطالب ({tested_str}) غير مدرج في قائمة الدومينات المصرح لها."


# ===================== TELEGRAM & WEBHOOK ALERTS =====================

def send_system_alert(title: str, message: str, level: str = "warning", force: bool = False) -> Tuple[bool, str]:
    """
    إرسال تنبيه فوري للمشرف عبر Telegram Bot أو Webhook (Discord/Slack/Custom)
    عند انتهاء الكوكيز أو حدوث أخطاء حرجة في الاستخراج.
    """
    cfg = _load_config()
    if not force and not cfg.get("alerts_enabled", False):
        return False, "التنبيهات غير مفعلة."

    now = time.time()
    cooldown_key = f"{level}:{title}"
    if not force:
        last_sent = _ALERT_COOLDOWNS.get(cooldown_key, 0)
        if (now - last_sent) < ALERT_COOLDOWN_SECONDS:
            return False, "تم تخطي التنبيه لمنع التكرار (Cooldown)."

    bot_token = cfg.get("telegram_bot_token", "").strip()
    chat_id = cfg.get("telegram_chat_id", "").strip()
    webhook_url = cfg.get("webhook_url", "").strip()

    if not bot_token and not webhook_url:
        return False, "لم يتم إعداد رمز بوت تيليجرام (Bot Token) أو رابط Webhook."

    icon = "⚠️" if level == "warning" else ("🚨" if level == "critical" else "✅")
    full_text = f"{icon} *{title}*\n\n{message}\n\n🕒 `{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}`"

    sent_any = False
    errors = []

    if bot_token and chat_id:
        try:
            tg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = json.dumps({
                "chat_id": chat_id,
                "text": full_text,
                "parse_mode": "Markdown"
            }).encode("utf-8")
            req = urllib.request.Request(tg_url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.getcode() in (200, 201):
                    sent_any = True
        except Exception as e:
            errors.append(f"Telegram: {e}")

    if webhook_url:
        try:
            payload = json.dumps({
                "content": full_text,
                "text": full_text,
                "title": title,
                "level": level,
                "message": message
            }).encode("utf-8")
            req = urllib.request.Request(
                webhook_url,
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "YouTube-API-Hub/1.6"}
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if 200 <= resp.getcode() < 300:
                    sent_any = True
        except Exception as e:
            errors.append(f"Webhook: {e}")

    if sent_any:
        _ALERT_COOLDOWNS[cooldown_key] = now
        return True, "تم إرسال التنبيه بنجاح."

    return False, f"فشل إرسال التنبيه: {'; '.join(errors)}"
