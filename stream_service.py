import time
import hashlib
import logging
import asyncio
from urllib.parse import quote
from typing import Optional, Tuple, Dict, AsyncGenerator
import httpx

logger = logging.getLogger("stream_service")

# الحجم الافتراضي لكل قطعة عند السحب من يوتيوب لتجاوز خانق السرعة (10MB)
DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB
BUFFER_READ_SIZE = 64 * 1024            # 64 KB per yield

# ذاكرة تخزين مؤقت خفيفة لمعلومات الميديا (الحجم والنوع) لتجنب تكرار فحص الميتاداتا
# المفتاح: md5(url) -> (total_size, content_type, timestamp)
_METADATA_CACHE: Dict[str, Tuple[int, str, float]] = {}
_CACHE_TTL_SECONDS = 7200  # ساعتان


def _cache_key(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()


async def get_stream_metadata(
    url: str,
    hint_size: Optional[int] = None,
    hint_mime: Optional[str] = None,
    timeout: float = 12.0
) -> Tuple[int, str]:
    """
    استخراج الحجم الإجمالي (total_size) ونوع الميديا (content_type) للرابط المباشر.
    إذا تم تمرير hint_size و hint_mime يتم استخدامهما فوراً، وإلا يتم إجراء فحص خفيف (Range: bytes=0-1).
    """
    key = _cache_key(url)
    now = time.time()

    if key in _METADATA_CACHE:
        cached_size, cached_mime, cached_at = _METADATA_CACHE[key]
        if (now - cached_at) < _CACHE_TTL_SECONDS:
            return cached_size, cached_mime

    # إذا توفرت التلميحات كاملة من قبل
    if hint_size and hint_size > 0 and hint_mime:
        _METADATA_CACHE[key] = (hint_size, hint_mime, now)
        return hint_size, hint_mime

    # إجراء فحص ميتاداتا سريع (Range 0-1) لاستخراج Content-Range و Content-Type
    headers = {
        "Range": "bytes=0-1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Encoding": "identity"
    }

    total_size = hint_size or 0
    content_type = hint_mime or "video/mp4"

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code in (200, 206):
                cr = resp.headers.get("content-range", "")
                if "/" in cr:
                    try:
                        total_size = int(cr.split("/")[-1])
                    except (ValueError, TypeError):
                        pass
                ct = resp.headers.get("content-type")
                if ct:
                    content_type = ct.split(";")[0].strip()
            elif resp.status_code == 403:
                raise ValueError("YouTube direct stream link has expired or access was forbidden (HTTP 403).")
    except Exception as e:
        logger.warning(f"Metadata probe failed for URL: {e}. Falling back to hints.")

    if total_size <= 0 and hint_size:
        total_size = hint_size

    _METADATA_CACHE[key] = (total_size, content_type, now)
    return total_size, content_type


def parse_range_header(
    range_header: Optional[str],
    total_size: int
) -> Tuple[Optional[int], Optional[int]]:
    """
    تحليل ترويسة Range من المتصفح (مثال: bytes=0- أو bytes=1048576-2097151).
    إرجاع (start, end) أو رفع ValueError إذا كان النطاق غير صالح.
    """
    if not range_header or not range_header.startswith("bytes="):
        return None, None

    range_val = range_header[6:].strip()
    if "," in range_val:
        # المتصفحات تطلب نطاقاً واحداً للفيديو، إذا تعددت نأخذ الأول
        range_val = range_val.split(",")[0].strip()

    parts = range_val.split("-")
    if len(parts) != 2:
        return None, None

    start_str, end_str = parts[0].strip(), parts[1].strip()

    if start_str == "" and end_str != "":
        # Suffix byte range (مثال: bytes=-500)
        suffix_len = int(end_str)
        if total_size > 0:
            start = max(0, total_size - suffix_len)
            end = total_size - 1
            return start, end
        return None, None

    if start_str != "" and end_str == "":
        # Open-ended range (مثال: bytes=1000-)
        start = int(start_str)
        end = (total_size - 1) if total_size > 0 else None
        return start, end

    if start_str != "" and end_str != "":
        start = int(start_str)
        end = int(end_str)
        if total_size > 0 and end >= total_size:
            end = total_size - 1
        return start, end

    return None, None


async def stream_chunked_response(
    url: str,
    start_byte: int,
    end_byte: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE
) -> AsyncGenerator[bytes, None]:
    """
    مولد بث ذكي يطلب البيانات من خوادم googlevideo على دفعات محددة (Chunks) بحجم 10MB،
    مما يتجاوز خانق السرعة (32KB/s) المفروض على الطلبات المفتوحة بالكامل،
    ويغذي المتصفح بالتدفق بسلاسة تامة مع دعم القفز (Seeking) دون استهلاك رام أو خنق السيرفر.
    """
    curr = start_byte

    timeout_cfg = httpx.Timeout(connect=10.0, read=45.0, write=15.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout_cfg, follow_redirects=True) as client:
        while curr <= end_byte:
            c_end = min(curr + chunk_size - 1, end_byte)
            headers = {
                "Range": f"bytes={curr}-{c_end}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Encoding": "identity",
            }

            try:
                async with client.stream("GET", url, headers=headers) as upstream_resp:
                    if upstream_resp.status_code not in (200, 206):
                        logger.warning(f"Upstream returned {upstream_resp.status_code} for chunk {curr}-{c_end}")
                        break

                    async for chunk in upstream_resp.aiter_bytes(chunk_size=BUFFER_READ_SIZE):
                        yield chunk

            except (asyncio.CancelledError, GeneratorExit):
                # المتصفح أغلق الاتصال أو انتقل لمكان آخر في الفيديو (Seek)
                return
            except Exception as exc:
                logger.warning(f"Error during streaming chunk {curr}-{c_end}: {exc}")
                break

            curr = c_end + 1


def build_proxy_url(
    base_url: str,
    direct_url: str,
    filesize_bytes: Optional[int] = None,
    ext: Optional[str] = "mp4",
    is_video: bool = True
) -> str:
    """
    تكوين رابط البث البروكسي الموجه لخادم Railway لفك خنق السرعة
    """
    clean_base = base_url.rstrip("/")
    mime = "video/mp4"
    if is_video:
        mime = f"video/{ext}" if ext in ("mp4", "webm") else "video/mp4"
    else:
        mime = "audio/mp4" if ext in ("m4a", "mp4") else f"audio/{ext}"

    query = f"url={quote(direct_url, safe='')}"
    if filesize_bytes and filesize_bytes > 0:
        query += f"&size={filesize_bytes}"
    if mime:
        query += f"&mime={quote(mime, safe='')}"

    if "workers.dev" in clean_base:
        return f"{clean_base}/?{query}"

    return f"{clean_base}/api/stream?{query}"


def clear_stream_metadata_cache() -> int:
    """مسح كاش الميتاداتا للبث المباشر وإرجاع عدد العناصر التي تم مسحها."""
    count = len(_METADATA_CACHE)
    _METADATA_CACHE.clear()
    return count


def get_stream_metadata_cache_size() -> int:
    """إرجاع عدد العناصر المخزنة حالياً في كاش الميتاداتا للبث."""
    return len(_METADATA_CACHE)

