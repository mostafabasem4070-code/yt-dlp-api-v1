import time
import shutil
import hashlib
import logging
import asyncio
from urllib.parse import quote, urlparse
from typing import Optional, Tuple, AsyncGenerator
from cachetools import TTLCache
import httpx

logger = logging.getLogger("stream_service")

# الحجم الافتراضي لكل قطعة عند السحب من يوتيوب لتجاوز خانق السرعة (10MB)
DEFAULT_CHUNK_SIZE = 10 * 1024 * 1024  # 10 MB
BUFFER_READ_SIZE = 64 * 1024            # 64 KB per yield

# ذاكرة تخزين مؤقت محددة الحجم والوقت (TTLCache) لمنع تسرب الذاكرة (Memory Leak)
# المفتاح: md5(url) -> (total_size, content_type)
_METADATA_CACHE: TTLCache = TTLCache(maxsize=2000, ttl=7200)

# عميل HTTP مشترك (Connection Pool) لإعادة استخدام اتصالات TCP/TLS مع خوادم googlevideo
_SHARED_HTTP_CLIENT: Optional[httpx.AsyncClient] = None

# النطاقات المسموح ببثها عبر البروكسي لمنع ثغرات SSRF و Open Proxy
ALLOWED_STREAM_DOMAINS = (
    ".googlevideo.com",
    "googlevideo.com",
    ".youtube.com",
    "youtube.com",
    ".ytimg.com",
)


def validate_stream_url(url: str) -> bool:
    """
    التحقق الصارم من أن الرابط المطلوب بثه ينتمي فعلياً لخوادم وسائط يوتيوب (googlevideo.com)
    لحماية الخادم من ثغرات SSRF واستنزاف الباندويث كـ Open Proxy.
    """
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https"):
            return False
        host = (parsed.hostname or "").lower().strip()
        if not host:
            return False
        if host in ("localhost", "127.0.0.1", "0.0.0.0", "::1") or host.startswith("169.254.") or host.startswith("192.168.") or host.startswith("10."):
            return False
        return any(host == d or host.endswith(d) for d in ALLOWED_STREAM_DOMAINS)
    except Exception:
        return False


def get_shared_http_client() -> httpx.AsyncClient:
    """إرجاع عميل HTTPX مشترك يدعم Keep-Alive وتجميع الاتصالات لتسريع البث والـ Seeking."""
    global _SHARED_HTTP_CLIENT
    if _SHARED_HTTP_CLIENT is None or _SHARED_HTTP_CLIENT.is_closed:
        limits = httpx.Limits(max_keepalive_connections=40, max_connections=200, keepalive_expiry=30.0)
        timeout_cfg = httpx.Timeout(connect=10.0, read=45.0, write=15.0, pool=30.0)
        _SHARED_HTTP_CLIENT = httpx.AsyncClient(
            timeout=timeout_cfg,
            limits=limits,
            follow_redirects=True
        )
    return _SHARED_HTTP_CLIENT


async def close_shared_http_client():
    """إغلاق عميل HTTPX المشترك بأمان عند إيقاف الخادم."""
    global _SHARED_HTTP_CLIENT
    if _SHARED_HTTP_CLIENT is not None and not _SHARED_HTTP_CLIENT.is_closed:
        try:
            await _SHARED_HTTP_CLIENT.aclose()
        except Exception:
            pass
    _SHARED_HTTP_CLIENT = None


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
    if not validate_stream_url(url):
        raise ValueError("رابط البث غير مصرح به: يُسمح فقط بروابط خوادم googlevideo.com الرسمية.")

    key = _cache_key(url)

    if key in _METADATA_CACHE:
        return _METADATA_CACHE[key]

    if hint_size and hint_size > 0 and hint_mime:
        _METADATA_CACHE[key] = (hint_size, hint_mime)
        return hint_size, hint_mime

    headers = {
        "Range": "bytes=0-1",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Encoding": "identity"
    }

    total_size = hint_size or 0
    content_type = hint_mime or "video/mp4"

    try:
        client = get_shared_http_client()
        resp = await client.get(url, headers=headers, timeout=timeout)
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
    except ValueError:
        raise
    except Exception as e:
        logger.warning(f"Metadata probe failed for URL: {e}. Falling back to hints.")

    if total_size <= 0 and hint_size:
        total_size = hint_size

    _METADATA_CACHE[key] = (total_size, content_type)
    return total_size, content_type


def parse_range_header(
    range_header: Optional[str],
    total_size: int
) -> Tuple[Optional[int], Optional[int]]:
    """
    تحليل ترويسة Range من المتصفح (مثال: bytes=0- أو bytes=1048576-2097151).
    """
    if not range_header or not range_header.startswith("bytes="):
        return None, None

    range_val = range_header[6:].strip()
    if "," in range_val:
        range_val = range_val.split(",")[0].strip()

    parts = range_val.split("-")
    if len(parts) != 2:
        return None, None

    start_str, end_str = parts[0].strip(), parts[1].strip()

    try:
        if start_str == "" and end_str != "":
            suffix_len = int(end_str)
            if total_size > 0:
                start = max(0, total_size - suffix_len)
                end = total_size - 1
                return start, end
            return None, None

        if start_str != "" and end_str == "":
            start = int(start_str)
            end = (total_size - 1) if total_size > 0 else None
            return start, end

        if start_str != "" and end_str != "":
            start = int(start_str)
            end = int(end_str)
            if total_size > 0 and end >= total_size:
                end = total_size - 1
            return start, end
    except ValueError:
        return None, None

    return None, None


async def stream_chunked_response(
    url: str,
    start_byte: int,
    end_byte: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE
) -> AsyncGenerator[bytes, None]:
    """
    مولد بث ذكي يطلب البيانات من خوادم googlevideo على دفعات محددة (Chunks) بحجم 10MB،
    باستخدام عميل اتصالات مشترك (Keep-Alive Connection Pool) لتجاوز خانق السرعة (32KB/s).
    """
    curr = start_byte
    client = get_shared_http_client()

    while curr <= end_byte:
        c_end = min(curr + chunk_size - 1, end_byte)
        headers = {
            "Range": f"bytes={curr}-{c_end}",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
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
            return
        except Exception as exc:
            logger.warning(f"Error during streaming chunk {curr}-{c_end}: {exc}")
            break

        curr = c_end + 1


async def stream_muxed_ffmpeg(
    video_url: str,
    audio_url: str
) -> AsyncGenerator[bytes, None]:
    """
    دمج لحظي مباشر (On-The-Fly Streaming Mux) لمسار فيديو عالي الدقة (1080p/2K/4K) مع مسار الصوت
    عبر FFmpeg بصيغة Fragmented MP4 بدون حفظ أي ملفات على القرص الصلب.
    """
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise RuntimeError("محرك FFmpeg غير مثبت على الخادم.")

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "error",
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", video_url,
        "-reconnect", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-i", audio_url,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "128k",
        "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        "-f", "mp4",
        "pipe:1"
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    try:
        while True:
            if not proc.stdout:
                break
            chunk = await proc.stdout.read(BUFFER_READ_SIZE)
            if not chunk:
                break
            yield chunk
    except (asyncio.CancelledError, GeneratorExit):
        return
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass


def build_proxy_url(
    base_url: str,
    direct_url: str,
    filesize_bytes: Optional[int] = None,
    ext: Optional[str] = "mp4",
    is_video: bool = True
) -> str:
    """
    تكوين رابط البث البروكسي الموجه لخادم Railway أو Cloudflare Worker لفك خنق السرعة
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


def build_mux_proxy_url(
    base_url: str,
    video_url: str,
    audio_url: str
) -> str:
    """
    تكوين رابط البث المدمج لحظياً عبر FFmpeg للجودات الفائقة (1080p/2K/4K مع الصوت).
    """
    clean_base = base_url.rstrip("/")
    return f"{clean_base}/api/stream/mux?video_url={quote(video_url, safe='')}&audio_url={quote(audio_url, safe='')}"


def clear_stream_metadata_cache() -> int:
    """مسح كاش الميتاداتا للبث المباشر وإرجاع عدد العناصر التي تم مسحها."""
    count = len(_METADATA_CACHE)
    _METADATA_CACHE.clear()
    return count


def get_stream_metadata_cache_size() -> int:
    """إرجاع عدد العناصر المخزنة حالياً في كاش الميتاداتا للبث."""
    return len(_METADATA_CACHE)
