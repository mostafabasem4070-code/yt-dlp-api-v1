import os
import json
import time
import base64
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("cookie_manager")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")
COOKIES_FILE = os.getenv("COOKIES_FILE", DEFAULT_COOKIES_FILE)

# قائمة كوكيز المصادقة والتعريف الأساسية ليوتيوب
CRITICAL_AUTH_COOKIES = [
    "LOGIN_INFO",
    "__Secure-3PSID",
    "__Secure-1PSID",
    "__Secure-3PSIDTS",
    "__Secure-1PSIDTS",
    "SID",
    "HSID",
    "SSID",
    "SAPISID",
    "APISID",
    "__Secure-3PAPISID",
    "__Secure-1PAPISID",
]

IMPORTANT_SESSION_COOKIES = [
    "VISITOR_INFO1_LIVE",
    "PREF",
    "YSC",
    "SIDCC",
    "__Secure-3PSIDCC",
    "__Secure-1PSIDCC",
    "__Secure-YENID",
]

# كوكيز مؤقتة أو تتبعية لحظية لا تعبر عن مدة جلسة الحساب ويجب استثناؤها من حساب تاريخ انتهاء الجلسة
EPHEMERAL_COOKIES = {
    "GPS",  # كوكي موقع جغرافي مدته 30 دقيقة فقط وتحدثه يوتيوب تلقائياً
    "YSC",  # كوكي جلسة متصفح لحظي
}


def parse_raw_cookie_input(raw_text: str) -> Tuple[List[Dict[str, Any]], str]:
    """
    تحليل الإدخال النصي لأي صيغة كوكيز معروفة:
    - JSON (من إضافات المتصفح Cookie-Editor / EditThisCookie)
    - Netscape format (ملف cookies.txt القياسي حتى لو تم نسخه بمسافات بدل tabs)
    - Header Format (Cookie: SID=...; LOGIN_INFO=...)
    - Base64 encoded Netscape / JSON
    
    يعيد: (قائمة قواميس الكوكيز الموحدة, اسم الصيغة المكتشفة)
    """
    text = raw_text.strip()
    if not text:
        return [], "empty"

    # 1. فحص إذا كان النص مشفر بـ Base64
    if not text.startswith("[") and not text.startswith("{") and not "\n" in text and len(text) > 40:
        try:
            decoded = base64.b64decode(text).decode("utf-8", errors="ignore").strip()
            if decoded.startswith("[") or "# Netscape" in decoded or "\t" in decoded:
                parsed, fmt = parse_raw_cookie_input(decoded)
                if parsed:
                    return parsed, f"base64_{fmt}"
        except Exception:
            pass

    # 2. فحص صيغة JSON
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                # أحياناً يكون كائن يحتوي على مفتاح 'cookies'
                if "cookies" in data and isinstance(data["cookies"], list):
                    data = data["cookies"]
                else:
                    data = [data]
            if isinstance(data, list):
                cookies = []
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name") or "").strip()
                    val = str(item.get("value") or "").strip()
                    if not name:
                        continue

                    # استخراج وتوحيد الحقول
                    domain = str(item.get("domain") or ".youtube.com").strip()
                    path = str(item.get("path") or "/").strip()
                    secure = bool(item.get("secure", True))
                    http_only = bool(item.get("httpOnly") or item.get("httponly", False))

                    # معالجة تاريخ الانتهاء
                    exp_val = item.get("expirationDate") or item.get("expires") or item.get("expiry") or 0
                    try:
                        exp = int(float(exp_val))
                    except (ValueError, TypeError):
                        exp = 0

                    cookies.append({
                        "domain": domain,
                        "flag": domain.startswith("."),
                        "path": path,
                        "secure": secure,
                        "expiration": exp,
                        "name": name,
                        "value": val,
                        "http_only": http_only
                    })
                if cookies:
                    return cookies, "json"
        except Exception as e:
            logger.debug(f"JSON parse attempt failed: {e}")

    # 3. فحص صيغة Netscape (تبدأ بـ # أو تحتوي على سطور tab-separated أو space-separated)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    netscape_cookies = []
    is_netscape = False

    for line in lines:
        if line.startswith("# Netscape") or line.startswith("# HTTP Cookie"):
            is_netscape = True
            continue
        
        http_only = False
        clean_line = line
        if clean_line.startswith("#HttpOnly_"):
            http_only = True
            clean_line = clean_line[len("#HttpOnly_"):]
        elif clean_line.startswith("#"):
            # تعليق عادي
            continue

        # محاولة الفصل بـ tab أولاً ثم بمسافات متعددة إذا تم استبدال الـ tab بمسافات أثناء النسخ
        parts = clean_line.split("\t")
        if len(parts) < 7:
            # تجربة التقسيم بالمسافات
            parts = clean_line.split()

        if len(parts) >= 7:
            is_netscape = True
            domain = parts[0]
            flag_str = parts[1].upper()
            flag = flag_str == "TRUE"
            path = parts[2]
            secure = parts[3].upper() == "TRUE"
            try:
                expiration = int(float(parts[4]))
            except ValueError:
                expiration = 0
            name = parts[5]
            value = parts[6] if len(parts) == 7 else " ".join(parts[6:])

            netscape_cookies.append({
                "domain": domain,
                "flag": flag,
                "path": path,
                "secure": secure,
                "expiration": expiration,
                "name": name,
                "value": value,
                "http_only": http_only
            })

    if netscape_cookies:
        return netscape_cookies, "netscape"

    # 4. فحص صيغة HTTP Header (Cookie: name=val; name2=val2)
    header_text = text
    if header_text.lower().startswith("cookie:"):
        header_text = header_text[7:].strip()
    
    if "=" in header_text and (";" in header_text or len(header_text.splitlines()) > 1):
        pairs = []
        for chunk in header_text.replace("\n", ";").split(";"):
            chunk = chunk.strip()
            if "=" in chunk:
                k, v = chunk.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k:
                    pairs.append((k, v))
        if pairs:
            cookies = []
            default_exp = int(time.time()) + 180 * 86400  # 6 months ahead
            for name, val in pairs:
                cookies.append({
                    "domain": ".youtube.com",
                    "flag": True,
                    "path": "/",
                    "secure": True,
                    "expiration": default_exp,
                    "name": name,
                    "value": val,
                    "http_only": name in ["LOGIN_INFO", "HSID", "SSID", "__Secure-3PSID", "__Secure-1PSIDTS", "__Secure-3PSIDTS"]
                })
            return cookies, "header_string"

    return [], "unknown"


def convert_cookies_to_netscape(cookies: List[Dict[str, Any]]) -> str:
    """
    تحويل قائمة الكوكيز الموحدة إلى نص بتنسيق Netscape HTTP Cookie File القياسي المعتمد من yt-dlp.
    """
    lines = [
        "# Netscape HTTP Cookie File",
        "# http://curl.haxx.se/rfc/cookie_spec.html",
        "# Processed and verified by YouTube Direct Links Extractor",
        ""
    ]

    for c in cookies:
        prefix = "#HttpOnly_" if c.get("http_only") else ""
        domain = c.get("domain", ".youtube.com")
        flag = "TRUE" if (c.get("flag") or domain.startswith(".")) else "FALSE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure", True) else "FALSE"
        expiration = int(c.get("expiration", 0))
        name = c.get("name", "")
        value = c.get("value", "")

        line = f"{prefix}{domain}\t{flag}\t{path}\t{secure}\t{expiration}\t{name}\t{value}"
        lines.append(line)

    lines.append("")
    return "\n".join(lines)


def get_active_cookie_path() -> Optional[str]:
    """العثور على مسار ملف الكوكيز الحالي النشط إذا كان موجوداً."""
    candidates = [
        COOKIES_FILE,
        os.path.join(BASE_DIR, "cookies.txt"),
        os.path.join(os.getcwd(), "cookies.txt"),
    ]
    for path in candidates:
        if path and os.path.exists(path) and os.path.getsize(path) > 10:
            return os.path.abspath(path)
    return None


def read_active_cookies() -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """قراءة وتحليل الكوكيز النشطة الحالية من الملف على القرص."""
    cookie_path = get_active_cookie_path()
    if not cookie_path:
        return [], None
    try:
        with open(cookie_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        cookies, _ = parse_raw_cookie_input(content)
        return cookies, cookie_path
    except Exception as e:
        logger.error(f"Error reading cookies from {cookie_path}: {e}")
        return [], cookie_path


def analyze_cookies_health(cookies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    فحص شامل لحالة وصلاحية الكوكيز وتواريخ انتهائها ومفاتيح المصادقة.
    يعتمد في احتساب تاريخ انتهاء الجلسة على كوكيز المصادقة الأساسية (Auth Cookies)،
    ويتجاهل الكوكيز اللحظية/المؤقتة مثل GPS و YSC لضمان دقة مدة الصلاحية.
    """
    if not cookies:
        return {
            "status": "missing",
            "message": "لا يوجد ملف كوكيز مسجل أو أنه فارغ.",
            "total_cookies": 0,
            "has_auth": False,
            "auth_cookies_found": [],
            "missing_critical_cookies": CRITICAL_AUTH_COOKIES,
            "earliest_expiry_readable": None,
            "is_expired": False,
            "days_until_expiry": 0.0,
            "expiry_human": "غير متوفرة",
            "items": []
        }

    now_ts = time.time()
    names_present = {c["name"] for c in cookies}
    auth_found = [c["name"] for c in cookies if c["name"] in CRITICAL_AUTH_COOKIES]
    missing_crit = [c for c in CRITICAL_AUTH_COOKIES if c not in names_present]

    # استخراج كوكيز المصادقة التي تملك تاريخ انتهاء محدد
    auth_cookies = [
        c for c in cookies 
        if c["name"] in CRITICAL_AUTH_COOKIES and c.get("expiration", 0) > 0
    ]
    
    # استخراج الكوكيز العامة الصالحة (مع استثناء الكوكيز اللحظية المؤقتة مثل GPS و YSC)
    general_cookies = [
        c for c in cookies 
        if c["name"] not in EPHEMERAL_COOKIES and c.get("expiration", 0) > 0
    ]
    # إذا كانت هناك كوكيز عامة مدتها أكثر من ساعة، نتجاهل أي كوكيز تتبع لحظية أخرى أقل من ساعة
    longer_general = [c for c in general_cookies if (c.get("expiration", 0) - now_ts) > 3600]
    if longer_general:
        general_cookies = longer_general

    # تحديد الكوكيز المستهدفة لحساب الصلاحية:
    # 1. الأولوية المطلقة لكوكيز المصادقة الأساسية إذا كانت متوفرة
    # 2. إذا لم تكن متوفرة (وضع الزائر Guest Mode)، نعتمد على الكوكيز العامة الصالحة
    target_pool = auth_cookies if auth_cookies else general_cookies

    future_exps = [c["expiration"] for c in target_pool if c["expiration"] > now_ts]
    all_target_exps = [c["expiration"] for c in target_pool]

    is_expired = False
    days_remaining = 0.0
    expiry_human = "غير محدد"
    earliest_readable = None

    if future_exps:
        min_target_exp = min(future_exps)
        max_target_exp = max(future_exps)
    elif all_target_exps:
        # الكوكيز المستهدفة منتهية الصلاحية جميعها
        min_target_exp = min(all_target_exps)
        max_target_exp = max(all_target_exps)
        is_expired = True
    else:
        # كوكيز جلسة مؤقتة (Session cookies) بدون تاريخ انتهاء بالأرقام
        min_target_exp = 0
        max_target_exp = 0

    expiry_countdown = "غير محدد"
    urgency_level = "guest"
    remaining_days_int = 0
    remaining_hours_int = 0
    remaining_mins_int = 0

    if min_target_exp > 0:
        dt = datetime.fromtimestamp(min_target_exp, tz=timezone.utc)
        earliest_readable = dt.strftime("%Y-%m-%d %H:%M:%S UTC")
        diff_sec = min_target_exp - now_ts
        
        if diff_sec <= 0:
            is_expired = True
            days_remaining = 0.0
            expiry_human = "منتهية الصلاحية"
            expiry_countdown = "منتهية منذ فترة"
            urgency_level = "critical"
        else:
            days_remaining = round(diff_sec / 86400, 1)
            remaining_days_int = int(diff_sec // 86400)
            remaining_hours_int = int((diff_sec % 86400) // 3600)
            remaining_mins_int = int((diff_sec % 3600) // 60)

            if remaining_days_int > 0:
                expiry_countdown = f"{remaining_days_int} يوم و {remaining_hours_int} ساعة"
            elif remaining_hours_int > 0:
                expiry_countdown = f"{remaining_hours_int} ساعة و {remaining_mins_int} دقيقة"
            else:
                expiry_countdown = f"{max(1, remaining_mins_int)} دقيقة"

            if diff_sec >= 86400 * 2:
                expiry_human = f"{int(days_remaining)} يوم"
            elif diff_sec >= 86400:
                expiry_human = f"{days_remaining} يوم"
            elif diff_sec >= 3600:
                hours = round(diff_sec / 3600, 1)
                expiry_human = f"{hours} ساعة"
            else:
                minutes = max(1, int(diff_sec / 60))
                expiry_human = f"{minutes} دقيقة"

            if remaining_days_int <= 3:
                urgency_level = "critical"
            elif remaining_days_int <= 14:
                urgency_level = "warning"
            else:
                urgency_level = "good"
    else:
        expiry_human = "جلسة مؤقتة (Session)"
        expiry_countdown = "جلسة مؤقتة لا تنتهي برقم"
        urgency_level = "guest"

    # تحديد الحالة العامة
    has_login_info = "LOGIN_INFO" in names_present
    has_sid = any(k in names_present for k in ["__Secure-3PSID", "__Secure-1PSID", "SID", "SSID", "HSID", "SAPISID", "APISID", "__Secure-3PSIDTS", "__Secure-1PSIDTS"])
    has_any_auth = has_login_info or has_sid or len(auth_found) > 0

    if is_expired:
        status_code = "expired"
        status_msg = "انتهت صلاحية كوكيز تسجيل الدخول الأساسية. يلزم تجديدها لضمان استمرار العمل بكفاءة."
    elif not has_any_auth:
        status_code = "guest_only"
        status_msg = f"الكوكيز تعمل في وضع الزائر (بدون تسجيل دخول حساب). صالحة لمدة {expiry_human}."
    elif len(auth_found) >= 2 or has_login_info or has_sid:
        status_code = "valid"
        status_msg = f"الكوكيز صالحة ومسجلة الدخول بنجاح! تنتهي جلسة الحساب بعد {expiry_countdown} ({earliest_readable})."
    else:
        status_code = "partial"
        status_msg = f"الكوكيز مسجلة جزئياً. تنتهي جلسة الحساب بعد {expiry_countdown}."

    # تفاصيل كل كوكي للعرض في لوحة التحكم
    items = []
    for c in cookies:
        c_exp = c.get("expiration", 0)
        c_name = c.get("name", "")
        c_is_ephemeral = c_name in EPHEMERAL_COOKIES
        c_status = "active"
        item_diff = c_exp - now_ts if c_exp > 0 else 0
        item_days_rem = round(item_diff / 86400, 1) if item_diff > 0 else 0.0

        if c_exp > 0 and c_exp < now_ts:
            c_status = "session" if c_is_ephemeral else "expired"
        elif c_exp == 0:
            c_status = "session"

        # تصنيف نوع الكوكي
        if c_name in CRITICAL_AUTH_COOKIES:
            category = "مصادقة أساسية (Auth)"
            category_badge = "primary"
        elif c_name in IMPORTANT_SESSION_COOKIES:
            category = "جلسة وأمان (Session)"
            category_badge = "cyan"
        elif c_is_ephemeral:
            category = "مؤقتة وتتبع (Tracking)"
            category_badge = "muted"
        else:
            category = "عامة (General)"
            category_badge = "default"

        items.append({
            "name": c_name,
            "domain": c["domain"],
            "http_only": c.get("http_only", False),
            "secure": c.get("secure", True),
            "expiration": c_exp,
            "expiration_readable": datetime.fromtimestamp(c_exp, tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if c_exp > 0 else "جلسة متصفح",
            "days_remaining": item_days_rem,
            "remaining_human": f"{int(item_days_rem)} يوم" if item_days_rem >= 2 else (f"{item_days_rem} يوم" if item_days_rem > 0 else ("منتهية" if c_exp > 0 else "مستمرة")),
            "is_auth": c_name in CRITICAL_AUTH_COOKIES,
            "is_ephemeral": c_is_ephemeral,
            "category": category,
            "category_badge": category_badge,
            "status": c_status
        })

    # ترتيب العناصر: كوكيز المصادقة أولاً
    items.sort(key=lambda x: (not x["is_auth"], x["name"]))

    return {
        "status": status_code,
        "message": status_msg,
        "total_cookies": len(cookies),
        "has_auth": has_login_info and has_sid,
        "auth_cookies_found": auth_found,
        "missing_critical_cookies": missing_crit,
        "earliest_expiry_readable": earliest_readable,
        "earliest_expiry_timestamp": min_target_exp,
        "latest_expiry_timestamp": max_target_exp,
        "is_expired": is_expired,
        "days_until_expiry": max(0.0, days_remaining),
        "days_int": remaining_days_int,
        "hours_int": remaining_hours_int,
        "mins_int": remaining_mins_int,
        "expiry_human": expiry_human,
        "expiry_countdown": expiry_countdown,
        "urgency": urgency_level,
        "items": items
    }


def save_cookies_content(raw_input: str) -> Dict[str, Any]:
    """
    معالجة النص الوارد بأي صيغة وتحويله وتخزينه في cookies.txt مباشرة.
    """
    cookies, detected_format = parse_raw_cookie_input(raw_input)
    if not cookies:
        raise ValueError(
            "لم يتم العثور على أي كوكيز صالحة في النص المدخل. "
            "تأكد من نسخ الكوكيز بصيغة JSON أو Netscape من إضافة Cookie-Editor أو EditThisCookie."
        )

    netscape_content = convert_cookies_to_netscape(cookies)

    # حفظ في المسار الافتراضي
    target_path = COOKIES_FILE or DEFAULT_COOKIES_FILE
    os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(netscape_content)

    logger.info(f"Updated {len(cookies)} cookies to {target_path} (Format detected: {detected_format})")

    # تحليل الحالة بعد الحفظ
    health = analyze_cookies_health(cookies)
    return {
        "status": "success",
        "detected_format": detected_format,
        "cookies_count": len(cookies),
        "file_path": target_path,
        "file_size_bytes": os.path.getsize(target_path),
        "health": health
    }


def clear_cookies_file() -> bool:
    """مسح ملف الكوكيز تماماً للعودة لوضع الزائر."""
    cookie_path = get_active_cookie_path()
    if cookie_path and os.path.exists(cookie_path):
        try:
            with open(cookie_path, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n# Cleared\n")
            logger.info(f"Cleared cookies file at {cookie_path}")
            return True
        except Exception as e:
            logger.error(f"Error clearing cookies file: {e}")
            return False
    return True
