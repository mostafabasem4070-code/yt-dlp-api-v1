"""
google_auth_service.py
======================
خدمة تسجيل الدخول التفاعلي والتلقائي لحساب Google/YouTube عبر متصفح Google Chrome / Chromium،
باستخدام تحكم CDP مباشر ونظيف (Zero-Runtime.enable & Zero-Automation-Flags) لتجاوز فحص BotGuard،
إضافة إلى التوليد التلقائي لبيانات Visitor Data و PO Token.
"""

import os
import re
import sys
import json
import time
import socket
import random
import shutil
import base64
import asyncio
import logging
import subprocess
import urllib.request
from typing import Dict, Any, Optional, List, Tuple

from cookie_manager import save_cookies_content
from security_manager import get_security_settings, update_security_preferences, get_writable_data_dir

logger = logging.getLogger("google_auth_service")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = get_writable_data_dir()

COOKIES_FILE = os.path.join(DATA_DIR, "cookies.txt")
RUNTIME_COOKIES_FILE = os.path.join(DATA_DIR, "cookies_runtime.txt")
BROWSER_PROFILE_DIR = os.path.join(DATA_DIR, ".browser_profile")

# حالة الجلسة
_auth_session: Dict[str, Any] = {
    "status": "idle",          # idle | running | waiting_login | extracting | done | error | timeout
    "started_at": None,
    "finished_at": None,
    "message": "",
    "cookies_count": 0,
    "current_url": "",
    "page_title": "",
    "error": None,
}
_auth_lock = asyncio.Lock()

# مرجع جلسة المتصفح النظيف النشط
_active_chrome: Optional["_CleanChromeSession"] = None
_xvfb_process = None


def _ensure_x_server():
    """
    التأكد من توفر خادم X على أنظمة لينكس.
    إذا لم يكن DISPLAY مضبوطاً أو كانت عملية Xvfb السابقة متوقفة، يشغّل Xvfb في الخلفية على الشاشة :99.
    """
    global _xvfb_process
    if not sys.platform.startswith("linux"):
        return

    if _xvfb_process is not None and _xvfb_process.poll() is not None:
        logger.warning("Previous Xvfb process terminated unexpectedly. Resetting DISPLAY.")
        _xvfb_process = None
        if os.environ.get("DISPLAY") == ":99":
            os.environ.pop("DISPLAY", None)

    display = os.environ.get("DISPLAY")
    if display:
        return

    xvfb_path = shutil.which("Xvfb")
    if not xvfb_path:
        logger.warning("Xvfb binary not found in PATH. Browser will automatically use headless mode.")
        return

    try:
        for lock_file in ("/tmp/.X99-lock", "/tmp/.X11-unix/X99"):
            if os.path.exists(lock_file):
                try:
                    os.remove(lock_file)
                except Exception:
                    pass

        logger.info("Starting virtual X server (Xvfb) on display :99...")
        _xvfb_process = subprocess.Popen(
            ["Xvfb", ":99", "-screen", "0", "1280x800x24", "-ac", "-nolisten", "tcp"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(0.6)
        if _xvfb_process.poll() is None:
            os.environ["DISPLAY"] = ":99"
            logger.info("Xvfb started successfully on :99")
        else:
            logger.warning("Xvfb exited immediately after start; falling back to headless mode.")
            _xvfb_process = None
    except Exception as e:
        logger.warning(f"Failed to start Xvfb: {e}")
        _xvfb_process = None


def _cleanup_stale_profile_locks():
    """إزالة ملفات القفل اليتيمة من مجلد المتصفح لمنع فشل الإقلاع بعد إعادة تشغيل الحاوية."""
    if not os.path.exists(BROWSER_PROFILE_DIR):
        return
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lock_path = os.path.join(BROWSER_PROFILE_DIR, lock_name)
        if os.path.exists(lock_path) or os.path.islink(lock_path):
            try:
                os.unlink(lock_path)
                logger.info(f"Removed stale browser profile lock: {lock_name}")
            except Exception:
                pass


def _find_sync_system_browser() -> Optional[str]:
    """البحث عن متصفح Google Chrome الرسمي أو Chromium المثبت على النظام مباشرة."""
    if sys.platform == "win32":
        win_candidates = [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]
        for path in win_candidates:
            if path and os.path.exists(path):
                return path
    else:
        for cmd in ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser"):
            found = shutil.which(cmd)
            if found:
                return found
        for path in ("/usr/bin/google-chrome-stable", "/usr/bin/google-chrome", "/usr/bin/chromium"):
            if os.path.exists(path):
                return path
    return None


async def _find_browser_executable() -> Optional[str]:
    """
    إيجاد المسار التنفيذي للمتصفح:
    1. يفضل Google Chrome الرسمي المثبت على النظام (لأنه يمتلك بصمة Google الأصلية).
    2. يتراجع إلى Chromium الخاص بـ Playwright (ويثبته تلقائياً إن لم يكن موجوداً).
    """
    sys_browser = _find_sync_system_browser()
    if sys_browser:
        return sys_browser

    try:
        from playwright.async_api import async_playwright  # type: ignore
        async with async_playwright() as p:
            exec_path = p.chromium.executable_path
            if exec_path and os.path.exists(exec_path):
                return exec_path
    except Exception:
        pass

    logger.info("Browser binary not found. Attempting automatic installation via 'playwright install chromium'...")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "playwright", "install", "chromium",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await asyncio.wait_for(proc.communicate(), timeout=180)
        from playwright.async_api import async_playwright  # type: ignore
        async with async_playwright() as p:
            exec_path = p.chromium.executable_path
            if exec_path and os.path.exists(exec_path):
                return exec_path
    except Exception as e:
        logger.error(f"Auto-install of Playwright Chromium failed: {e}")

    return None


def _get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _CleanChromeSession:
    """
    مشغّل متصفح Chrome مباشر ونظيف (Zero-Automation-Flags & Zero-Runtime.enable):
    - يشغّل Google Chrome كعملية نظام طبيعية عبر subprocess.Popen دون أي من رايات Playwright الـ 35 المكشوفة.
    - يتخاطب مع المتصفح عبر أوامر Page / Input / Storage فقط دون تفعيل Runtime.enable نهائياً،
      وهو ما يمنع Google BotGuard من اكتشاف الأتمتة أثناء تسجيل الدخول.
    """

    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.port: int = 0
        self._ws = None
        self._ws_url: str = ""
        self._msg_id: int = 0
        self._lock = asyncio.Lock()
        self._mouse_x: int = 640
        self._mouse_y: int = 400
        self.current_url: str = ""
        self.current_title: str = ""

    async def start(self, exe_path: str, profile_dir: str, cache_dir: str, headless: bool, initial_url: str):
        self.port = _get_free_port()
        os.makedirs(profile_dir, exist_ok=True)
        os.makedirs(cache_dir, exist_ok=True)

        # ضبط تفضيلات المتصفح لمنع نوافذ حفظ كلمة المرور المزعجة وإظهار الإغلاق النظيف
        default_dir = os.path.join(profile_dir, "Default")
        os.makedirs(default_dir, exist_ok=True)
        prefs_file = os.path.join(default_dir, "Preferences")
        if not os.path.exists(prefs_file):
            try:
                prefs = {
                    "credentials_enable_service": False,
                    "profile": {
                        "password_manager_enabled": False,
                        "exit_type": "Normal",
                        "exited_cleanly": True,
                    },
                    "intl": {"accept_languages": "ar-EG,ar,en-US,en"},
                }
                with open(prefs_file, "w", encoding="utf-8") as f:
                    json.dump(prefs, f)
            except Exception:
                pass

        cmd = [
            exe_path,
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={self.port}",
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--disable-infobars",
            f"--disk-cache-dir={cache_dir}",
            "--window-size=1280,800",
            "--window-position=0,0",
            "--lang=ar",
        ]

        if sys.platform.startswith("linux"):
            cmd.extend([
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--password-store=basic",
            ])

        if headless:
            cmd.append("--headless=new")

        cmd.append(initial_url)

        logger.info(f"Launching clean browser process: {exe_path} on port {self.port} (headless={headless})")
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # انتظار جاهزية منفذ التصحيح وإنشاء التبويب الأول
        deadline = time.time() + 15.0
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Browser process exited prematurely with code {self.process.returncode}")
            target = await asyncio.to_thread(self._fetch_primary_page_target)
            if target and target.get("webSocketDebuggerUrl"):
                self.current_url = target.get("url", initial_url)
                self.current_title = target.get("title", "")
                return
            await asyncio.sleep(0.35)

        raise RuntimeError("Timed out waiting for Chrome DevTools endpoint to become ready.")

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def _fetch_primary_page_target(self) -> Optional[Dict[str, Any]]:
        try:
            url = f"http://127.0.0.1:{self.port}/json/list"
            with urllib.request.urlopen(url, timeout=2.5) as resp:
                items = json.loads(resp.read().decode("utf-8", errors="ignore"))
                if isinstance(items, list):
                    for item in items:
                        if item.get("type") == "page" and not str(item.get("url", "")).startswith("devtools://"):
                            return item
                    if items:
                        return items[0]
        except Exception:
            pass
        return None

    async def refresh_page_info(self) -> Tuple[str, str]:
        target = await asyncio.to_thread(self._fetch_primary_page_target)
        if target:
            self.current_url = target.get("url", self.current_url)
            self.current_title = target.get("title", self.current_title)
        return self.current_url, self.current_title

    async def _ensure_ws(self):
        import websockets  # type: ignore

        target = await asyncio.to_thread(self._fetch_primary_page_target)
        if not target or not target.get("webSocketDebuggerUrl"):
            raise RuntimeError("No active browser page target found.")

        self.current_url = target.get("url", self.current_url)
        self.current_title = target.get("title", self.current_title)
        ws_url = target["webSocketDebuggerUrl"]

        if self._ws is not None and self._ws_url == ws_url:
            try:
                # التحقق من أن الاتصال لا يزال مفتوحاً
                is_closed = getattr(self._ws, "closed", False)
                if not is_closed and getattr(self._ws, "close_code", None) is None:
                    return
            except Exception:
                pass

        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        self._ws = await websockets.connect(ws_url, max_size=16 * 1024 * 1024, ping_interval=None)
        self._ws_url = ws_url

    async def _send_cdp(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Dict[str, Any]:
        async with self._lock:
            await self._ensure_ws()
            self._msg_id += 1
            req_id = self._msg_id
            payload = json.dumps({"id": req_id, "method": method, "params": params or {}})
            try:
                await self._ws.send(payload)
                end_time = time.time() + timeout
                while time.time() < end_time:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=max(0.5, end_time - time.time()))
                    msg = json.loads(raw)
                    if msg.get("id") == req_id:
                        if "error" in msg:
                            raise RuntimeError(msg["error"].get("message", str(msg["error"])))
                        return msg.get("result", {})
            except Exception:
                try:
                    if self._ws:
                        await self._ws.close()
                except Exception:
                    pass
                self._ws = None
                raise
            raise TimeoutError(f"CDP command {method} timed out")

    async def screenshot_base64(self) -> str:
        res = await self._send_cdp("Page.captureScreenshot", {"format": "jpeg", "quality": 68}, timeout=6.0)
        return res.get("data", "")

    async def navigate(self, url: str):
        await self._send_cdp("Page.navigate", {"url": url}, timeout=15.0)

    async def reload(self):
        await self._send_cdp("Page.reload", {"ignoreCache": False}, timeout=15.0)

    async def get_cookies(self) -> List[Dict[str, Any]]:
        res = await self._send_cdp("Storage.getCookies", {}, timeout=6.0)
        return res.get("cookies", [])

    async def clear_cookies(self):
        try:
            await self._send_cdp("Network.clearBrowserCookies", {}, timeout=5.0)
        except Exception:
            pass

    async def click(self, x: int, y: int):
        target_x = max(1, min(1279, x + random.randint(-2, 2)))
        target_y = max(1, min(799, y + random.randint(-2, 2)))
        steps = random.randint(6, 12)
        start_x, start_y = self._mouse_x, self._mouse_y

        for i in range(1, steps + 1):
            cur_x = int(start_x + (target_x - start_x) * (i / steps))
            cur_y = int(start_y + (target_y - start_y) * (i / steps))
            await self._send_cdp("Input.dispatchMouseEvent", {
                "type": "mouseMoved",
                "x": cur_x,
                "y": cur_y,
                "button": "none",
                "buttons": 0,
            })
            await asyncio.sleep(random.uniform(0.008, 0.018))

        self._mouse_x, self._mouse_y = target_x, target_y
        await asyncio.sleep(random.uniform(0.04, 0.09))

        await self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mousePressed",
            "x": target_x,
            "y": target_y,
            "button": "left",
            "buttons": 1,
            "clickCount": 1,
        })
        await asyncio.sleep(random.uniform(0.045, 0.085))
        await self._send_cdp("Input.dispatchMouseEvent", {
            "type": "mouseReleased",
            "x": target_x,
            "y": target_y,
            "button": "left",
            "buttons": 0,
            "clickCount": 1,
        })

    async def type_text(self, text: str, press_enter: bool = False):
        for ch in text:
            vk = ord(ch.upper()) if ch.isalpha() else (ord(ch) if ord(ch) < 128 else 0)
            await self._send_cdp("Input.dispatchKeyEvent", {
                "type": "keyDown",
                "text": ch,
                "unmodifiedText": ch,
                "key": ch,
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
            })
            await asyncio.sleep(random.uniform(0.025, 0.055))
            await self._send_cdp("Input.dispatchKeyEvent", {
                "type": "keyUp",
                "key": ch,
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
            })
            await asyncio.sleep(random.uniform(0.035, 0.095))

        if press_enter:
            await asyncio.sleep(random.uniform(0.22, 0.40))
            await self.press_key("Enter")

    async def press_key(self, key: str):
        key_map = {
            "Enter": (13, "Enter", "\r"),
            "Tab": (9, "Tab", ""),
            "Backspace": (8, "Backspace", ""),
            "Escape": (27, "Escape", ""),
            "ArrowDown": (40, "ArrowDown", ""),
            "ArrowUp": (38, "ArrowUp", ""),
            "ArrowLeft": (37, "ArrowLeft", ""),
            "ArrowRight": (39, "ArrowRight", ""),
        }
        vk, code, text_char = key_map.get(key, (0, key, ""))
        down_params: Dict[str, Any] = {
            "type": "rawKeyDown" if text_char else "keyDown",
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": vk,
            "nativeVirtualKeyCode": vk,
        }
        await self._send_cdp("Input.dispatchKeyEvent", down_params)
        if text_char:
            await self._send_cdp("Input.dispatchKeyEvent", {
                "type": "char",
                "text": text_char,
                "unmodifiedText": text_char,
                "key": key,
                "code": code,
                "windowsVirtualKeyCode": vk,
                "nativeVirtualKeyCode": vk,
            })
        await asyncio.sleep(random.uniform(0.035, 0.065))
        await self._send_cdp("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": vk,
            "nativeVirtualKeyCode": vk,
        })

    async def stop(self):
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        if self.process is not None:
            try:
                if self.process.poll() is None:
                    self.process.terminate()
                    try:
                        await asyncio.to_thread(self.process.wait, 3)
                    except Exception:
                        self.process.kill()
            except Exception:
                pass
            self.process = None


def get_auth_session_status() -> Dict[str, Any]:
    """إرجاع حالة جلسة المصادقة الحالية."""
    return dict(_auth_session)


def _update_session(**kwargs):
    _auth_session.update(kwargs)


def _cookies_to_netscape(cookies: list) -> str:
    """تحويل كوكيز CDP / Playwright إلى صيغة Netscape HTTP Cookie File."""
    lines = ["# Netscape HTTP Cookie File", "# Generated by Google Auth Service", ""]
    for c in cookies:
        domain = c.get("domain", "")
        domain_flag = "FALSE" if domain and not domain.startswith(".") else "TRUE"
        path = c.get("path", "/")
        secure = "TRUE" if c.get("secure", False) else "FALSE"
        expires = int(c.get("expires", 0))
        if expires < 0:
            expires = 0
        name = c.get("name", "")
        value = c.get("value", "")
        lines.append(f"{domain}\t{domain_flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}")
    return "\n".join(lines) + "\n"


def _is_youtube_authenticated(cookies: list) -> bool:
    """التحقق من وجود كوكيز المصادقة الأساسية لحساب Google/YouTube."""
    auth_cookies = {"SID", "SSID", "HSID", "LOGIN_INFO", "SAPISID", "__Secure-1PSID", "__Secure-3PSID"}
    found = {c["name"] for c in cookies if c["name"] in auth_cookies}
    return len(found) >= 2


async def _save_extracted_cookies(cookies: list) -> int:
    """حفظ الكوكيز في ملف cookies.txt ومسبح الكوكيز (Cookie Pool) وتحديث الجلسة."""
    netscape_content = _cookies_to_netscape(cookies)
    save_cookies_content(netscape_content, label="متصفح Google التفاعلي")

    auth_cookie_names = [c["name"] for c in cookies if c["name"] in {"SID", "SSID", "HSID", "LOGIN_INFO", "SAPISID", "__Secure-1PSID", "__Secure-3PSID"}]
    _update_session(
        status="done",
        finished_at=time.time(),
        cookies_count=len(cookies),
        message=f"تم استخراج {len(cookies)} كوكي وحفظها في النظام ومسبح التدوير! المفاتيح: {', '.join(auth_cookie_names[:4])}",
        error=None,
    )
    logger.info(f"Cookies saved: {len(cookies)} cookies → {COOKIES_FILE}")
    return len(cookies)


async def start_google_login_session(
    timeout_minutes: int = 15,
    headless: Optional[bool] = None,
    target_url: str = "https://accounts.google.com/ServiceLogin?service=youtube&uilel=3&passive=true&continue=https%3A%2F%2Fwww.youtube.com%2Fsignin%3Faction_handle_signin%3Dtrue%26app%3Ddesktop%26hl%3Dar%26next%3Dhttps%253A%252F%252Fwww.youtube.com%252F&hl=ar"
) -> Dict[str, Any]:
    """بدء جلسة تسجيل الدخول التفاعلية لـ Google."""
    global _auth_session

    async with _auth_lock:
        if _auth_session["status"] in ("running", "waiting_login", "extracting"):
            return {
                "success": False,
                "message": "جلسة تسجيل دخول أخرى جارية بالفعل. يُرجى استخدامها أو إلغاؤها.",
                "session": get_auth_session_status()
            }

        _update_session(
            status="running",
            started_at=time.time(),
            finished_at=None,
            message="جاري تجهيز المتصفح الأصلي بدون بصمة أتمتة...",
            cookies_count=0,
            current_url="",
            page_title="",
            error=None,
        )

    asyncio.create_task(_run_login_session(timeout_minutes, headless, target_url))

    return {
        "success": True,
        "message": "تم بدء جلسة تسجيل الدخول. يمكنك التفاعل مع المتصفح من النافذة الآن.",
        "session": get_auth_session_status()
    }


async def _run_login_session(timeout_minutes: int, headless_override: Optional[bool], target_url: str):
    """تشغيل متصفح Chrome بنمط العملية المستقلة النظيفة (Zero-Runtime.enable) ومراقبة اكتمال الدخول."""
    global _active_chrome

    _ensure_x_server()
    _cleanup_stale_profile_locks()

    if headless_override is not None:
        use_headless = headless_override
    else:
        if sys.platform.startswith("linux") and not os.environ.get("DISPLAY"):
            use_headless = True
        else:
            use_headless = False

    try:
        _update_session(message="جاري البحث عن محرك متصفح Chrome / Chromium...")
        exe_path = await _find_browser_executable()
        if not exe_path:
            _update_session(
                status="error",
                finished_at=time.time(),
                error="تعذر العثور على متصفح Chrome أو Chromium على الخادم.",
                message="خطأ: متصفح Chrome / Chromium غير متوفر."
            )
            return

        # تنظيف البروفايل من أي كوكيز حظر سابقة (__Host-GAPS) لضمان بداية نظيفة
        try:
            shutil.rmtree(BROWSER_PROFILE_DIR, ignore_errors=True)
        except Exception:
            pass

        chromium_cache_dir = os.path.join(DATA_DIR, ".chromium_cache")
        chrome = _CleanChromeSession()
        _update_session(message="جاري فتح المتصفح النظيف وتجهيز الجلسة...")
        await chrome.start(
            exe_path=exe_path,
            profile_dir=BROWSER_PROFILE_DIR,
            cache_dir=chromium_cache_dir,
            headless=use_headless,
            initial_url="https://www.youtube.com/?hl=ar",
        )
        _active_chrome = chrome

        await asyncio.sleep(1.2)
        await chrome.navigate(target_url)

        _update_session(
            status="waiting_login",
            message=f"المتصفح جاهز في النافذة التفاعلية. (المهلة: {timeout_minutes} دقيقة)",
            current_url=target_url,
        )

        deadline = time.time() + (timeout_minutes * 60)
        authenticated = False

        while time.time() < deadline:
            if _auth_session["status"] in ("idle", "done", "error"):
                return

            await asyncio.sleep(2.0)

            try:
                if not chrome.is_running():
                    break

                curr_url, curr_title = await chrome.refresh_page_info()
                _update_session(current_url=curr_url, page_title=curr_title)

                cookies = await chrome.get_cookies()
                if _is_youtube_authenticated(cookies):
                    authenticated = True
                    logger.info(f"Authentication detected! Cookies count: {len(cookies)}")
                    break

                remaining = int(deadline - time.time())
                mins, secs = divmod(remaining, 60)
                _update_session(
                    message=f"في انتظار إتمام تسجيل الدخول... (متبقي {mins}:{secs:02d})"
                )
            except Exception as e:
                logger.debug(f"Check loop error: {e}")
                continue

        if _auth_session["status"] == "done":
            return

        if authenticated:
            _update_session(status="extracting", message="تم كشف الجلسة! جاري استخراج وحفظ الكوكيز...")
            await asyncio.sleep(2.0)
            all_cookies = await chrome.get_cookies()
            await _save_extracted_cookies(all_cookies)
        else:
            if _auth_session["status"] not in ("done", "idle"):
                _update_session(
                    status="timeout",
                    finished_at=time.time(),
                    error="انتهت مهلة تسجيل الدخول. يُرجى إعادة المحاولة.",
                    message="انتهت المهلة قبل إتمام تسجيل الدخول."
                )

    except Exception as e:
        logger.error(f"Login session execution error: {e}", exc_info=True)
        _update_session(
            status="error",
            finished_at=time.time(),
            error=str(e),
            message=f"خطأ في جلسة تسجيل الدخول: {str(e)}"
        )
    finally:
        await _cleanup_browser_resources()


async def _cleanup_browser_resources():
    """تنظيف وإغلاق موارد المتصفح بأمان."""
    global _active_chrome
    if _active_chrome is not None:
        try:
            await _active_chrome.stop()
        except Exception:
            pass
        _active_chrome = None


# =========================================================================
# التوليد التلقائي لـ PO Token و Visitor Data عبر Playwright
# =========================================================================

async def auto_generate_po_token_and_visitor_data() -> Dict[str, Any]:
    """
    تشغيل متصفح خفي في الخلفية لفتح صفحة مشغل يوتيوب،
    واعتراض طلبات الشبكة وكائن ytcfg لاستخراج VISITOR_DATA و PO Token تلقائياً
    وحفظهما في إعدادات النظام.
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore
    except ImportError:
        return {
            "success": False,
            "message": "مكتبة Playwright غير مثبتة على السيرفر."
        }

    if _auth_session["status"] in ("running", "waiting_login", "extracting"):
        return {
            "success": False,
            "message": "يوجد متصفح تسجيل دخول تفاعلي نشط حالياً. يرجى الانتظار حتى انتهائه."
        }

    captured_visitor_data = ""
    captured_po_token = ""

    pw = None
    browser = None
    try:
        exe_path = await _find_browser_executable()
        pw = await async_playwright().start()
        launch_opts: Dict[str, Any] = {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--mute-audio"
            ]
        }
        if exe_path:
            launch_opts["executable_path"] = exe_path
        browser = await pw.chromium.launch(**launch_opts)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()

        def _inspect_request(req):
            nonlocal captured_visitor_data, captured_po_token
            url = req.url
            if "googlevideo.com/videoplayback" in url:
                m = re.search(r"[?&]pot=([^&]+)", url)
                if m and not captured_po_token:
                    captured_po_token = m.group(1)
            elif "youtubei/v1/player" in url and req.method == "POST":
                try:
                    post_data = req.post_data
                    if post_data:
                        body = json.loads(post_data)
                        v_data = body.get("context", {}).get("client", {}).get("visitorData")
                        if v_data and not captured_visitor_data:
                            captured_visitor_data = v_data
                        po_tok = body.get("serviceIntegrityDimensions", {}).get("poToken")
                        if po_tok and not captured_po_token:
                            captured_po_token = po_tok
                except Exception:
                    pass

        page.on("request", _inspect_request)

        await page.goto("https://www.youtube.com/embed/dQw4w9WgXcQ?autoplay=1&mute=1", wait_until="domcontentloaded", timeout=25000)
        await asyncio.sleep(2.0)

        try:
            await page.click(".ytp-large-play-button", timeout=3000)
            await asyncio.sleep(2.5)
        except Exception:
            pass

        if not captured_visitor_data:
            try:
                captured_visitor_data = await page.evaluate(
                    "() => (window.ytcfg && window.ytcfg.get && window.ytcfg.get('VISITOR_DATA')) || ''"
                )
            except Exception:
                pass

        if not captured_po_token or not captured_visitor_data:
            await page.goto("https://www.youtube.com/watch?v=dQw4w9WgXcQ", wait_until="domcontentloaded", timeout=25000)
            await asyncio.sleep(2.5)
            if not captured_visitor_data:
                try:
                    captured_visitor_data = await page.evaluate(
                        "() => (window.ytcfg && window.ytcfg.get && window.ytcfg.get('VISITOR_DATA')) || ''"
                    )
                except Exception:
                    pass

        await browser.close()
        await pw.stop()
        browser = None
        pw = None

        if not captured_visitor_data and not captured_po_token:
            return {
                "success": False,
                "message": "تعذر استخراج Visitor Data أو PO Token تلقائياً من يوتيوب."
            }

        cur_sec = get_security_settings()
        new_po = captured_po_token or cur_sec.get("po_token", "")
        new_vd = captured_visitor_data or cur_sec.get("visitor_data", "")

        update_security_preferences(
            strict_mode=cur_sec.get("strict_mode", False),
            po_token=new_po,
            visitor_data=new_vd
        )

        logger.info(f"Auto-generated tokens: visitor_data={bool(new_vd)}, po_token={bool(new_po)}")
        return {
            "success": True,
            "visitor_data": new_vd,
            "po_token": new_po,
            "message": "تم استخراج وحفظ بيانات الجلسة (Visitor Data / PO Token) تلقائياً بنجاح!"
        }
    except Exception as e:
        logger.error(f"Error auto-generating PO Token / Visitor Data: {e}")
        return {
            "success": False,
            "message": f"خطأ أثناء التوليد التلقائي: {str(e)}"
        }
    finally:
        try:
            if browser:
                await browser.close()
        except Exception:
            pass
        try:
            if pw:
                await pw.stop()
        except Exception:
            pass


# =========================================================================
# أدوات التفاعل المباشر مع المتصفح (Interactive Remote Browser API)
# =========================================================================

async def capture_browser_screenshot() -> Dict[str, Any]:
    """التقاط لقطة شاشة سريعة من المتصفح النشط كـ Base64 JPEG."""
    global _active_chrome
    if not _active_chrome or not _active_chrome.is_running():
        return {
            "success": False,
            "message": _auth_session.get("message") or "لا يوجد متصفح نشط حالياً.",
            "error": _auth_session.get("error"),
            "status": _auth_session["status"]
        }

    try:
        b64 = await _active_chrome.screenshot_base64()
        url, title = await _active_chrome.refresh_page_info()
        return {
            "success": True,
            "image": f"data:image/jpeg;base64,{b64}",
            "url": url,
            "title": title,
            "status": _auth_session["status"],
            "message": _auth_session.get("message", "")
        }
    except Exception as e:
        return {"success": False, "error": str(e), "status": _auth_session["status"]}


async def browser_mouse_click(x: int, y: int) -> Dict[str, Any]:
    """إرسال نقرة ماوس طبيعية (مع تحريك تدريجي للماوس) إلى إحداثيات محددة في صفحة المتصفح."""
    global _active_chrome
    if not _active_chrome or not _active_chrome.is_running():
        return {"success": False, "message": "لا يوجد متصفح نشط."}

    try:
        await _active_chrome.click(x, y)
        await asyncio.sleep(0.45)
        return await capture_browser_screenshot()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_keyboard_type(text: str, press_enter: bool = False) -> Dict[str, Any]:
    """كتابة نص بسرعة بشرية متغيرة في الحقل النشط بالمتصفح، مع خيار الضغط على Enter."""
    global _active_chrome
    if not _active_chrome or not _active_chrome.is_running():
        return {"success": False, "message": "لا يوجد متصفح نشط."}

    try:
        await _active_chrome.type_text(text, press_enter=press_enter)
        await asyncio.sleep(0.6)
        return await capture_browser_screenshot()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_keyboard_key(key: str) -> Dict[str, Any]:
    """الضغط على مفتاح معين (مثل Enter, Backspace, Tab, ArrowDown)."""
    global _active_chrome
    if not _active_chrome or not _active_chrome.is_running():
        return {"success": False, "message": "لا يوجد متصفح نشط."}

    try:
        await _active_chrome.press_key(key)
        await asyncio.sleep(0.4)
        return await capture_browser_screenshot()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_reload_page() -> Dict[str, Any]:
    """إعادة تحميل الصفحة الحالية في المتصفح."""
    global _active_chrome
    if not _active_chrome or not _active_chrome.is_running():
        return {"success": False, "message": "لا يوجد متصفح نشط."}

    try:
        await _active_chrome.reload()
        await asyncio.sleep(0.6)
        return await capture_browser_screenshot()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_navigate_to(url: str) -> Dict[str, Any]:
    """الانتقال لعنوان URL محدد في المتصفح (مثلاً YouTube أو صفحة SSO)."""
    global _active_chrome
    if not _active_chrome or not _active_chrome.is_running():
        return {"success": False, "message": "لا يوجد متصفح نشط."}

    try:
        await _active_chrome.navigate(url)
        await asyncio.sleep(0.7)
        return await capture_browser_screenshot()
    except Exception as e:
        return {"success": False, "error": str(e)}


async def browser_manual_extract() -> Dict[str, Any]:
    """استخراج الكوكيز فورياً يدوياً بطلب من المستخدم، وحفظها وإنهاء الجلسة."""
    global _active_chrome
    if not _active_chrome or not _active_chrome.is_running():
        return {"success": False, "message": "لا توجد جلسة متصفح نشطة لاستخراج الكوكيز منها."}

    try:
        cookies = await _active_chrome.get_cookies()
        if not cookies:
            return {"success": False, "message": "لم يتم العثور على أي كوكيز في المتصفح حتى الآن."}

        count = await _save_extracted_cookies(cookies)
        await _cleanup_browser_resources()
        return {
            "success": True,
            "message": f"تم استخراج {count} كوكي وحفظها بنجاح في ملف cookies.txt ومسبح التدوير!",
            "cookies_count": count
        }
    except Exception as e:
        logger.error(f"Manual extract error: {e}", exc_info=True)
        return {"success": False, "error": str(e)}


async def cancel_auth_session() -> Dict[str, Any]:
    """إلغاء جلسة تسجيل الدخول الحالية فوراً."""
    _update_session(
        status="idle",
        finished_at=time.time(),
        message="تم إلغاء الجلسة وإغلاق المتصفح.",
        error=None
    )
    await _cleanup_browser_resources()
    return {"success": True, "message": "تم إلغاء جلسة تسجيل الدخول بنجاح."}


def is_playwright_available() -> bool:
    """التحقق من توفر متصفح نظام (Chrome/Chromium) أو مكتبة Playwright."""
    if _find_sync_system_browser():
        return True
    try:
        import playwright  # type: ignore
        return True
    except ImportError:
        return False


def get_playwright_status() -> Dict[str, Any]:
    """معلومات توفر المتصفح وخادم Xvfb وحالة الجلسة."""
    available = is_playwright_available()
    has_xvfb = bool(shutil.which("Xvfb")) or sys.platform == "win32"
    return {
        "playwright_installed": available,
        "xvfb_available": has_xvfb,
        "platform": sys.platform,
        "has_display": bool(os.environ.get("DISPLAY")),
        "session": get_auth_session_status()
    }
