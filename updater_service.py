import sys
import json
import logging
import asyncio
import subprocess
import importlib
import urllib.request
from typing import Dict, Any, Optional

logger = logging.getLogger("updater_service")

# حالة التحديثات في الذاكرة
_UPDATE_STATE: Dict[str, Any] = {
    "auto_update_enabled": True,
    "last_check_timestamp": None,
    "last_update_status": "initialized",
    "last_update_message": "جاهز للفحص التلقائي",
}


def get_current_ytdlp_version() -> str:
    """إرجاع إصدار yt-dlp المثبت حالياً."""
    try:
        import yt_dlp.version
        return str(yt_dlp.version.__version__)
    except Exception as e:
        logger.error(f"Failed to get yt-dlp version: {e}")
        return "unknown"


def get_latest_pypi_version() -> Optional[str]:
    """الاستعلام عن أحدث إصدار متاح لـ yt-dlp على مستودع PyPI الرسمي."""
    try:
        url = "https://pypi.org/pypi/yt-dlp/json"
        req = urllib.request.Request(url, headers={"User-Agent": "YouTube-API-Updater/1.0"})
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode("utf-8"))
            return str(data.get("info", {}).get("version", ""))
    except Exception as e:
        logger.warning(f"Could not fetch latest yt-dlp version from PyPI: {e}")
        return None


def _parse_version_tuple(v_str: Optional[str]):
    if not v_str:
        return ()
    try:
        clean = v_str.replace("v", "").strip()
        parts = []
        for x in clean.split("."):
            digits = "".join(ch for ch in x if ch.isdigit())
            parts.append(int(digits) if digits else 0)
        return tuple(parts)
    except Exception:
        return ()


def run_ytdlp_upgrade(force: bool = False) -> Dict[str, Any]:
    """
    فحص وتحديث مكتبة yt-dlp إلى أحدث إصدار متاح فوراً دون الحاجة لإعادة تشغيل الحاوية.
    """
    current_ver = get_current_ytdlp_version()
    latest_pypi = get_latest_pypi_version()

    curr_tuple = _parse_version_tuple(current_ver)
    latest_tuple = _parse_version_tuple(latest_pypi)

    needs_update = force or (latest_tuple and latest_tuple > curr_tuple)

    if not needs_update and latest_pypi:
        msg = f"مكتبة yt-dlp محدثة بالفعل إلى أحدث إصدار ({current_ver})."
        logger.info(msg)
        return {
            "success": True,
            "updated": False,
            "current_version": current_ver,
            "latest_pypi_version": latest_pypi,
            "message": msg
        }

    logger.info(f"Initiating yt-dlp upgrade (Current: {current_ver}, Latest: {latest_pypi or 'unknown'})...")
    try:
        cmd = [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--upgrade", "yt-dlp"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if proc.returncode != 0:
            err_msg = f"فشل أمر التحديث: {proc.stderr[:200]}"
            logger.error(err_msg)
            return {
                "success": False,
                "updated": False,
                "current_version": current_ver,
                "error": err_msg,
                "message": err_msg
            }

        # إعادة تحميل موديول yt_dlp في الذاكرة لتطبيق التحديث فوراً
        try:
            import yt_dlp
            import yt_dlp.version
            importlib.reload(yt_dlp.version)
            importlib.reload(yt_dlp)
            new_ver = yt_dlp.version.__version__
        except Exception:
            new_ver = get_current_ytdlp_version()

        success_msg = f"تم تحديث yt-dlp بنجاح من الإصدار {current_ver} إلى {new_ver}!"
        logger.info(success_msg)
        _UPDATE_STATE["last_update_status"] = "success"
        _UPDATE_STATE["last_update_message"] = success_msg

        return {
            "success": True,
            "updated": True,
            "old_version": current_ver,
            "current_version": new_ver,
            "latest_pypi_version": latest_pypi or new_ver,
            "message": success_msg
        }

    except subprocess.TimeoutExpired:
        err_msg = "انتهت مهلة التحديث (تجاوزت 120 ثانية)."
        logger.error(err_msg)
        return {"success": False, "updated": False, "current_version": current_ver, "message": err_msg}
    except Exception as e:
        err_msg = f"خطأ أثناء التحديث: {str(e)}"
        logger.error(err_msg)
        return {"success": False, "updated": False, "current_version": current_ver, "message": err_msg}


async def background_auto_updater(interval_seconds: int = 43200):
    """
    مهمة خلفية تعمل بشكل دوري (كل 12 ساعة افتراضياً) لفحص وتحديث yt-dlp تلقائياً.
    """
    logger.info("Background auto-updater service started (Running every 12 hours).")
    # انتظر 30 ثانية بعد تشغيل السيرفر قبل أول فحص لتفادي الضغط على بدء التشغيل
    await asyncio.sleep(30)

    while True:
        try:
            logger.info("Executing scheduled automatic update check for yt-dlp...")
            res = await asyncio.to_thread(run_ytdlp_upgrade, False)
            logger.info(f"Scheduled update check finished: {res.get('message')}")
        except Exception as e:
            logger.error(f"Error in background auto-updater: {e}")

        await asyncio.sleep(interval_seconds)


def get_updater_status() -> Dict[str, Any]:
    """إرجاع تقرير تشخيصي عن حالة التحديثات والإصدار الحالي والمتاح."""
    current_ver = get_current_ytdlp_version()
    latest_ver = get_latest_pypi_version()
    return {
        "auto_update_enabled": True,
        "current_ytdlp_version": current_ver,
        "latest_pypi_version": latest_ver or current_ver,
        "is_up_to_date": (_parse_version_tuple(latest_ver) <= _parse_version_tuple(current_ver)) if latest_ver else True,
        "schedule": "كل 12 ساعة تلقائياً",
        "last_status": _UPDATE_STATE.get("last_update_status"),
        "last_message": _UPDATE_STATE.get("last_update_message")
    }
