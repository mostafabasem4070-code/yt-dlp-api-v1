import os
import json
import time
import hmac
import hashlib
import secrets
import logging
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse
import bcrypt

logger = logging.getLogger("security_manager")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "security_config.json")
SESSIONS_FILE = os.path.join(BASE_DIR, "sessions.json")

# Session store loaded from file
_ACTIVE_SESSIONS: Dict[str, Dict[str, Any]] = {}
SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days

def _load_sessions():
    global _ACTIVE_SESSIONS
    if os.path.exists(SESSIONS_FILE):
        try:
            with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
                _ACTIVE_SESSIONS = json.load(f)
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
    """تحميل إعدادات الأمان والدومينات من الملف أو إنشاء الإعدادات الافتراضية"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                # ضمان وجود الحقول الضرورية
                if "api_key" not in cfg or not cfg["api_key"]:
                    cfg["api_key"] = os.getenv("API_KEY") or f"sec_{secrets.token_hex(16)}"
                    _save_config(cfg)
                if "worker_pool" not in cfg:
                    cfg["worker_pool"] = []
                    _save_config(cfg)
                return cfg
        except Exception as e:
            logger.error(f"Failed to load security config: {e}")

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
        "updated_at": int(time.time())
    }
    _save_config(cfg)
    return cfg


def _save_config(config: Dict[str, Any]) -> bool:
    """حفظ إعدادات الأمان في ملف JSON دائم"""
    try:
        config["updated_at"] = int(time.time())
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
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
    if env_pwd and password == env_pwd:
        return True

    # التوافقية مع الهاش القديم SHA256 (مؤقتاً) إذا كان لا يبدأ بصيغة bcrypt
    if stored_hash and not stored_hash.startswith("$2"):
        salt = cfg.get("salt", "")
        test_hash = hashlib.sha256((salt + password).encode("utf-8")).hexdigest()
        if hmac.compare_digest(stored_hash, test_hash):
            # تحديث الهاش للصيغة الجديدة فوراً
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
    استخراج النطاق الصافي بدقة بدون بروتوكول، منافذ، مسارات، أو لاحقات:
    يدعم:
    - https://domain.com/path -> domain.com
    - http://sub.domain.com:8000 -> sub.domain.com
    - *.domain.com -> *.domain.com
    - //localhost/ -> localhost
    """
    raw = domain_str.strip().lower()
    if not raw:
        return ""
    if raw == "*":
        return "*"
    
    # إزالة أي مسار لاحق إذا لم يكن يحتوي بروتوكول
    if "://" not in raw:
        # إذا بدأ بـ //
        if raw.startswith("//"):
            raw = "http:" + raw
        else:
            raw = "http://" + raw

    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower().strip()
        # إذا كان الدومين يحتوي على علامة النجمة للـ wildcard الفرعي
        if not host and "*" in raw:
            host = raw.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
        return host
    except Exception:
        # Fallback يدوي نظيف
        clean = raw.replace("http://", "").replace("https://", "").split("/")[0].split(":")[0]
        return clean.strip()


def check_domain_matches(caller: str, pattern: str) -> bool:
    """
    مطابقة ذكية مرنة بين الدومين الطالب والنمط المصرح به:
    - النمط '*' يطابق أي دومين.
    - النمط '*.example.com' يطابق 'example.com' و 'sub.example.com'.
    - النمط 'example.com' يطابق 'example.com' و 'www.example.com' و 'lms.example.com'.
    - النمط 'localhost' يطابق 'localhost' و '127.0.0.1'.
    """
    caller = caller.lower().strip()
    pattern = pattern.lower().strip()

    if not caller or not pattern:
        return False

    if pattern == "*":
        return True

    # دعم الدومينات المحلية
    if pattern in ("localhost", "127.0.0.1") and caller in ("localhost", "127.0.0.1"):
        return True

    # إذا كان النمط يبدأ بنجمة فرعية
    if pattern.startswith("*."):
        root = pattern[2:]
        return caller == root or caller.endswith("." + root)

    # تطابق تام
    if caller == pattern:
        return True

    # تطابق كنطاق فرعي
    if caller.endswith("." + pattern):
        return True

    # تطابق إذا كان النمط يحتوي www والطلب بدونها أو العكس
    if pattern.startswith("www.") and caller == pattern[4:]:
        return True
    if caller.startswith("www.") and caller[4:] == pattern:
        return True

    return False


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
        "worker_pool": cfg.get("worker_pool", []),
        "updated_at": cfg.get("updated_at", 0),
        "active_sessions_count": len(_ACTIVE_SESSIONS),
        "force_ipv6": cfg.get("force_ipv6", False),
        "use_oauth2": cfg.get("use_oauth2", False),
        "po_token": cfg.get("po_token", ""),
        "visitor_data": cfg.get("visitor_data", "")
    }


def add_allowed_domain(domain: str) -> Tuple[bool, str, List[str]]:
    """إضافة دومين جديد إلى قائمة الدومينات المصرح لها"""
    clean = normalize_domain(domain)
    if not clean:
        return False, "اسم الدومين المدخل غير صالح.", []

    cfg = _load_config()
    domains = cfg.get("allowed_domains", [])

    # إذا كانت القائمة تحتوي فقط على '*' وأضاف دومين حقيقي، نزيل '*' لجعل الحماية فعالة
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
    domains = cfg.get("allowed_domains", [])

    if clean not in domains and domain not in domains:
        return False, "الدومين غير موجود في القائمة.", domains

    domains = [d for d in domains if d != clean and d != domain]
    # إذا فرغت القائمة تماماً، نعيدها للوضع الآمن المفتوح الافتراضي لتجنب شلل النظام
    if not domains:
        domains = ["*"]

    cfg["allowed_domains"] = domains
    _save_config(cfg)
    return True, f"تم حذف الدومين بنجاح.", domains


def update_security_preferences(
    strict_mode: bool, 
    allowed_domains: Optional[List[str]] = None, 
    generate_new_api_key: bool = False,
    force_ipv6: Optional[bool] = None,
    use_oauth2: Optional[bool] = None,
    po_token: Optional[str] = None,
    visitor_data: Optional[str] = None
) -> Dict[str, Any]:
    """تحديث خيارات الأمان ووضع الفحص الصارم ومفتاح الـ API"""
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

    _save_config(cfg)
    return get_security_settings()

# ===================== WORKER POOL MANAGEMENT =====================

def add_worker_url(url: str) -> Tuple[bool, str, List[str]]:
    """إضافة رابط Cloudflare Worker جديد للقائمة"""
    clean = url.strip().rstrip("/")
    if not clean or not clean.startswith("http"):
        return False, "الرابط غير صالح. يجب أن يبدأ بـ http أو https.", []

    cfg = _load_config()
    pool = cfg.get("worker_pool", [])

    if clean in pool:
        return True, "الرابط موجود بالفعل في القائمة.", pool

    pool.append(clean)
    cfg["worker_pool"] = pool
    _save_config(cfg)
    return True, f"تمت إضافة الرابط ({clean}) بنجاح.", pool

def remove_worker_url(url: str) -> Tuple[bool, str, List[str]]:
    """حذف رابط Cloudflare Worker من القائمة"""
    clean = url.strip().rstrip("/")
    cfg = _load_config()
    pool = cfg.get("worker_pool", [])

    if clean not in pool:
        return False, "الرابط غير موجود في القائمة.", pool

    pool = [w for w in pool if w != clean]
    cfg["worker_pool"] = pool
    _save_config(cfg)
    return True, "تم حذف الرابط بنجاح.", pool


def clear_all_worker_urls() -> Tuple[bool, str, List[str]]:
    """حذف جميع روابط Cloudflare Workers من القائمة دفعة واحدة"""
    cfg = _load_config()
    cfg["worker_pool"] = []
    _save_config(cfg)
    return True, "تم حذف جميع روابط البروكسي بنجاح.", []


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

    # إذا كان مسموح للجميع
    if "*" in domains and not strict:
        return {
            "authorized": True,
            "domain": test_input,
            "normalized": clean,
            "reason": "مصرح به تلقائياً (الوضع مفتوح للجميع مع تعطيل الوضع الصارم)."
        }

    # فحص التطابق مع القائمة
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
    التحقق الصارم والموثوق من تصريح الطلب:
    1. المشرف المصادق عليه (Dashboard Session) -> مصرح دائماً.
    2. مفتاح الـ API المعتمد (X-API-Key من Laravel أو الخوادم الشريكة) -> مصرح دائماً.
    3. إذا لم يكن الوضع الصارم مفعلاً وتوجد النجمة '*' -> مصرح.
    4. فحص Origin و Referer ومطابقتهما ذكياً مع قائمة الدومينات المسموحة.
    5. طلبات الخادم المحلية (Localhost).
    """
    # 1. فحص توكن جلسة المشرف
    if auth_token and validate_session_token(auth_token):
        return True, "Authorized via Admin Session"

    cfg = _load_config()
    expected_api_key = cfg.get("api_key", "").strip()

    # 2. فحص مفتاح الـ API المرسل من Laravel (عبر X-API-Key أو Query Param)
    if expected_api_key and api_key_header:
        clean_header = api_key_header.strip()
        if hmac.compare_digest(expected_api_key, clean_header):
            return True, "Authorized via API Key"

    allowed_domains = cfg.get("allowed_domains", ["*"])
    strict_mode = cfg.get("strict_mode", False)

    # 3. الوضع المفتوح للجميع
    if "*" in allowed_domains and not strict_mode:
        return True, "Open access (Wildcard allowed)"

    # استخراج وتوحيد الدومين الطالب من Origin أو Referer
    caller_domains_to_test = []
    if origin:
        c_orig = normalize_domain(origin)
        if c_orig:
            caller_domains_to_test.append(c_orig)
    if referer:
        c_ref = normalize_domain(referer)
        if c_ref and c_ref not in caller_domains_to_test:
            caller_domains_to_test.append(c_ref)

    # 4. فحص التطابق مع القائمة
    for caller in caller_domains_to_test:
        for pattern in allowed_domains:
            if check_domain_matches(caller, pattern):
                return True, f"Domain allowed: {caller} (matched {pattern})"

    # 5. إذا كان الطلب من السيرفر المحلي نفسه
    if host:
        host_clean = normalize_domain(host)
        if host_clean in ("localhost", "127.0.0.1"):
            return True, "Localhost host allowed"

    for caller in caller_domains_to_test:
        if caller in ("localhost", "127.0.0.1"):
            return True, "Localhost caller allowed"

    # في حال فشل التطابق
    if not caller_domains_to_test:
        return False, "طلب غير مصرح به: لم يتم إرسال ترويسة Origin أو Referer مطابقة، ولم يتم تقديم مفتاح API صالح."

    tested_str = ", ".join(caller_domains_to_test)
    return False, f"طلب مرفوض: الدومين الطالب ({tested_str}) غير مدرج في قائمة الدومينات المصرح لها."
