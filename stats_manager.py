import os
import re
import time
import sqlite3
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("stats_manager")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "extraction_stats.db")


def extract_video_id(url: str) -> Optional[str]:
    """استخراج المعرف الفريد للفيديو (Video ID) من أي صيغة رابط يوتيوب."""
    if not url:
        return None
    patterns = [
        r'(?:v=|\/|youtu\.be\/|embed\/|shorts\/|live\/)([0-9A-Za-z_-]{11})',
        r'([0-9A-Za-z_-]{11})'
    ]
    for pattern in patterns:
        m = re.search(pattern, url)
        if m:
            return m.group(1)
    return None


def get_db_connection() -> sqlite3.Connection:
    """الحصول على اتصال بقاعدة بيانات SQLite مع تهيئة وضع WAL للسرعة وتعدد العمليات."""
    conn = sqlite3.connect(DB_PATH, timeout=15.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_stats_db():
    """تهيئة جدول الإحصائيات والفهارس في قاعدة البيانات إذا لم تكن موجودة."""
    try:
        with get_db_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extractions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT,
                    url TEXT NOT NULL,
                    title TEXT,
                    thumbnail TEXT,
                    duration_seconds INTEGER DEFAULT 0,
                    channel TEXT,
                    status TEXT NOT NULL,
                    is_cached INTEGER DEFAULT 0,
                    response_time_ms INTEGER DEFAULT 0,
                    client_ip TEXT,
                    referer TEXT,
                    error_message TEXT,
                    timestamp REAL NOT NULL,
                    created_at TEXT NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extractions_video_id ON extractions(video_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extractions_created_at ON extractions(created_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extractions_status ON extractions(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_extractions_timestamp ON extractions(timestamp);")
            conn.commit()
            logger.info("Extraction stats database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize stats database: {e}")


# تهيئة تلقائية عند استيراد الملف
init_stats_db()


def record_extraction(
    url: str,
    video_info: Optional[Dict[str, Any]] = None,
    status: str = "success",
    is_cached: bool = False,
    response_time_ms: int = 0,
    client_ip: Optional[str] = None,
    referer: Optional[str] = None,
    error_message: Optional[str] = None
) -> Optional[int]:
    """
    تسجيل عملية استخراج فورية في قاعدة البيانات.
    يتم تسجيل كل رابط يُطلب عبر الـ API سواء كان جديداً أو من الـ TTLCache وسواء نجح أو فشل.
    """
    try:
        url_clean = (url or "").strip()
        v_id = extract_video_id(url_clean)

        title = None
        thumbnail = None
        duration = 0
        channel = None

        if video_info and isinstance(video_info, dict):
            title = video_info.get("title")
            thumbnail = video_info.get("thumbnail")
            duration = video_info.get("duration") or 0
            channel = video_info.get("uploader") or video_info.get("channel")
            if not v_id:
                v_id = video_info.get("id")

        # تنظيف الدومين الطالب (Referer or Origin)
        clean_referer = None
        if referer:
            ref_str = str(referer).strip()
            # إزالة المسارات الطويلة للحصول على اسم الدومين
            m = re.search(r'https?://([^/]+)', ref_str)
            clean_referer = m.group(1) if m else ref_str[:100]

        now_ts = time.time()
        created_at_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        with get_db_connection() as conn:
            cur = conn.execute("""
                INSERT INTO extractions (
                    video_id, url, title, thumbnail, duration_seconds, channel,
                    status, is_cached, response_time_ms, client_ip, referer,
                    error_message, timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                v_id,
                url_clean,
                title,
                thumbnail,
                duration,
                channel,
                status,
                1 if is_cached else 0,
                max(0, int(response_time_ms)),
                client_ip or "",
                clean_referer or "",
                error_message or "",
                now_ts,
                created_at_str
            ))
            conn.commit()
            return cur.lastrowid
    except Exception as e:
        logger.error(f"Error recording extraction stat: {e}")
        return None


def get_extraction_summary_metrics(top_limit: int = 10, recent_limit: int = 20) -> Dict[str, Any]:
    """
    استرجاع تقرير إحصائي متكامل وشامل لعمليات الاستخراج:
    - إجمالي العمليات الكلية.
    - عمليات اليوم (منذ منتصف الليل).
    - العمليات الناجحة والفاشلة ونسبة النجاح.
    - استخراجات الكاش (Cache Hits) ونسبة التوفير.
    - متوسط زمن المعالجة (بالمللي ثانية).
    - أكثر الروابط استخراجاً وطلباً.
    - أحدث عمليات الاستخراج المباشرة.
    - الاتجاهات اليومية (Daily trends) لآخر 7 أيام.
    - توزيع الطلبات حسب المنصات والدومينات (Top Referrers).
    """
    try:
        with get_db_connection() as conn:
            # 1. الإحصائيات العامة الكلية
            row_total = conn.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_count,
                    SUM(CASE WHEN is_cached = 1 THEN 1 ELSE 0 END) as cache_hits,
                    AVG(CASE WHEN status = 'success' AND is_cached = 0 THEN response_time_ms ELSE NULL END) as avg_fresh_time,
                    AVG(CASE WHEN status = 'success' THEN response_time_ms ELSE NULL END) as avg_total_time,
                    COUNT(DISTINCT CASE WHEN video_id IS NOT NULL AND video_id != '' THEN video_id ELSE url END) as unique_videos
                FROM extractions
            """).fetchone()

            total_extractions = row_total["total"] if row_total else 0
            success_count = row_total["success_count"] if row_total and row_total["success_count"] else 0
            failed_count = row_total["failed_count"] if row_total and row_total["failed_count"] else 0
            cache_hits = row_total["cache_hits"] if row_total and row_total["cache_hits"] else 0
            unique_videos = row_total["unique_videos"] if row_total and row_total["unique_videos"] else 0
            avg_fresh_ms = round(row_total["avg_fresh_time"] or 0, 1) if row_total else 0
            avg_total_ms = round(row_total["avg_total_time"] or 0, 1) if row_total else 0

            success_rate = round((success_count / total_extractions) * 100, 1) if total_extractions > 0 else 100.0
            cache_hit_rate = round((cache_hits / total_extractions) * 100, 1) if total_extractions > 0 else 0.0

            # 2. إحصائيات اليوم (Today's metrics)
            today_prefix = datetime.now().strftime("%Y-%m-%d")
            row_today = conn.execute("""
                SELECT 
                    COUNT(*) as today_total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as today_success,
                    SUM(CASE WHEN is_cached = 1 THEN 1 ELSE 0 END) as today_cached
                FROM extractions
                WHERE created_at LIKE ?
            """, (f"{today_prefix}%",)).fetchone()

            today_total = row_today["today_total"] if row_today and row_today["today_total"] else 0
            today_success = row_today["today_success"] if row_today and row_today["today_success"] else 0
            today_cached = row_today["today_cached"] if row_today and row_today["today_cached"] else 0

            # 3. أكثر الروابط استخراجاً (Top Extracted Videos)
            top_rows = conn.execute("""
                SELECT 
                    COALESCE(video_id, url) as identifier,
                    video_id,
                    MAX(url) as url,
                    COALESCE(MAX(title), 'فيديو يوتيوب') as title,
                    MAX(thumbnail) as thumbnail,
                    MAX(channel) as channel,
                    MAX(duration_seconds) as duration_seconds,
                    COUNT(*) as count,
                    SUM(CASE WHEN is_cached = 1 THEN 1 ELSE 0 END) as cache_hits,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success_count,
                    MAX(created_at) as last_extracted_at
                FROM extractions
                GROUP BY COALESCE(video_id, url)
                ORDER BY count DESC, last_extracted_at DESC
                LIMIT ?
            """, (top_limit,)).fetchall()

            top_videos = []
            for r in top_rows:
                top_videos.append({
                    "identifier": r["identifier"],
                    "video_id": r["video_id"],
                    "url": r["url"] or (f"https://www.youtube.com/watch?v={r['video_id']}" if r["video_id"] else ""),
                    "title": r["title"] or "فيديو يوتيوب",
                    "thumbnail": r["thumbnail"],
                    "channel": r["channel"] or "",
                    "duration_seconds": r["duration_seconds"] or 0,
                    "count": r["count"],
                    "cache_hits": r["cache_hits"],
                    "success_count": r["success_count"],
                    "last_extracted_at": r["last_extracted_at"],
                    "percentage_of_total": round((r["count"] / total_extractions) * 100, 1) if total_extractions > 0 else 0
                })

            # 4. أحدث عمليات الاستخراج (Recent Extractions Log)
            recent_rows = conn.execute("""
                SELECT 
                    id, video_id, url, title, thumbnail, channel, duration_seconds,
                    status, is_cached, response_time_ms, client_ip, referer,
                    error_message, created_at
                FROM extractions
                ORDER BY id DESC
                LIMIT ?
            """, (recent_limit,)).fetchall()

            recent_extractions = []
            for r in recent_rows:
                recent_extractions.append({
                    "id": r["id"],
                    "video_id": r["video_id"],
                    "url": r["url"],
                    "title": r["title"] or (f"فيديو ({r['video_id']})" if r["video_id"] else "طلب استخراج"),
                    "thumbnail": r["thumbnail"],
                    "channel": r["channel"],
                    "duration_seconds": r["duration_seconds"],
                    "status": r["status"],
                    "is_cached": bool(r["is_cached"]),
                    "response_time_ms": r["response_time_ms"],
                    "client_ip": r["client_ip"] or "--",
                    "referer": r["referer"] or "مباشر (API)",
                    "error_message": r["error_message"] or "",
                    "created_at": r["created_at"]
                })

            # 5. التطور اليومي لآخر 7 أيام (Daily Trend)
            trend_rows = conn.execute("""
                SELECT 
                    substr(created_at, 1, 10) as day_date,
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                    SUM(CASE WHEN is_cached = 1 THEN 1 ELSE 0 END) as cached
                FROM extractions
                GROUP BY substr(created_at, 1, 10)
                ORDER BY day_date DESC
                LIMIT 7
            """).fetchall()

            daily_trends = []
            for r in reversed(trend_rows):
                daily_trends.append({
                    "date": r["day_date"],
                    "total": r["total"],
                    "success": r["success"],
                    "cached": r["cached"]
                })

            # 6. أكثر الدومينات / المنصات الطالبة (Top Referrers)
            ref_rows = conn.execute("""
                SELECT 
                    COALESCE(NULLIF(referer, ''), 'Direct / API Client') as domain_name,
                    COUNT(*) as count
                FROM extractions
                GROUP BY domain_name
                ORDER BY count DESC
                LIMIT 5
            """).fetchall()

            top_referrers = [{"domain": r["domain_name"], "count": r["count"]} for r in ref_rows]

            return {
                "status": "ok",
                "kpis": {
                    "total_extractions": total_extractions,
                    "today_extractions": today_total,
                    "today_success": today_success,
                    "today_cached": today_cached,
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "success_rate": success_rate,
                    "cache_hits": cache_hits,
                    "cache_hit_rate": cache_hit_rate,
                    "unique_videos": unique_videos,
                    "avg_response_time_ms": avg_total_ms,
                    "avg_fresh_response_time_ms": avg_fresh_ms
                },
                "top_videos": top_videos,
                "recent_extractions": recent_extractions,
                "daily_trends": daily_trends,
                "top_referrers": top_referrers
            }
    except Exception as e:
        logger.error(f"Error fetching extraction stats summary: {e}")
        return {
            "status": "error",
            "message": str(e),
            "kpis": {
                "total_extractions": 0,
                "today_extractions": 0,
                "today_success": 0,
                "today_cached": 0,
                "success_count": 0,
                "failed_count": 0,
                "success_rate": 100.0,
                "cache_hits": 0,
                "cache_hit_rate": 0.0,
                "unique_videos": 0,
                "avg_response_time_ms": 0,
                "avg_fresh_response_time_ms": 0
            },
            "top_videos": [],
            "recent_extractions": [],
            "daily_trends": [],
            "top_referrers": []
        }


def clear_extraction_stats() -> bool:
    """مسح كافة سجلات وإحصائيات الاستخراج وتصفير العدادات."""
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM extractions;")
            conn.commit()
            conn.execute("VACUUM;")
        logger.info("Extraction stats wiped clean successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to clear extraction stats: {e}")
        return False
