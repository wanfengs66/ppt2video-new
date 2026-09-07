"""
数据库模块：管理视频生成历史记录（按用户隔离）
使用 SQLite 轻量级数据库
"""
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional
from contextlib import contextmanager

from config import settings


@contextmanager
def get_db_connection():
    """获取数据库连接（上下文管理器）"""
    conn = sqlite3.connect(settings.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """初始化数据库表"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS video_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id TEXT UNIQUE NOT NULL,
                open_id TEXT NOT NULL DEFAULT '',
                original_filename TEXT NOT NULL,
                slide_count INTEGER DEFAULT 0,
                video_url TEXT,
                video_size INTEGER DEFAULT 0,
                duration REAL DEFAULT 0,
                status TEXT DEFAULT 'processing',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                error_message TEXT
            )
        """)

        # 尝试为旧表添加 open_id 列（兼容无此列的旧数据库）
        try:
            cursor.execute("ALTER TABLE video_history ADD COLUMN open_id TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # 列已存在

        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at
            ON video_history(created_at DESC)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_job_id
            ON video_history(job_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_open_id
            ON video_history(open_id)
        """)

        print("[OK] Database initialized")


def add_video_record(
    job_id: str,
    original_filename: str,
    slide_count: int = 0,
    open_id: str = "",
) -> int:
    """添加视频生成记录"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO video_history (job_id, open_id, original_filename, slide_count, status, created_at)
            VALUES (?, ?, ?, ?, 'processing', ?)
        """, (job_id, open_id, original_filename, slide_count, now))
        return cursor.lastrowid


def update_video_record(
    job_id: str,
    video_url: Optional[str] = None,
    video_size: Optional[int] = None,
    duration: Optional[float] = None,
    status: Optional[str] = None,
    error_message: Optional[str] = None,
    open_id: str = "",
):
    """更新视频记录（可选的 open_id 用于归属校验）"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        updates = []
        params = []

        if video_url is not None:
            updates.append("video_url = ?")
            params.append(video_url)
        if video_size is not None:
            updates.append("video_size = ?")
            params.append(video_size)
        if duration is not None:
            updates.append("duration = ?")
            params.append(duration)
        if status is not None:
            updates.append("status = ?")
            params.append(status)
            if status == "completed":
                updates.append("completed_at = ?")
                params.append(datetime.now().isoformat())
        if error_message is not None:
            updates.append("error_message = ?")
            params.append(error_message)

        if updates:
            sql = f"UPDATE video_history SET {', '.join(updates)} WHERE job_id = ?"
            params.append(job_id)
            if open_id:
                sql += " AND open_id = ?"
                params.append(open_id)
            cursor.execute(sql, params)


def get_video_history(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    open_id: str = "",
) -> List[Dict]:
    """获取视频历史记录列表（按用户过滤）"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        sql = "SELECT * FROM video_history WHERE 1=1"
        params = []

        if open_id:
            sql += " AND open_id = ?"
            params.append(open_id)
        if status:
            sql += " AND status = ?"
            params.append(status)

        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]


def get_video_record(job_id: str) -> Optional[Dict]:
    """获取单个视频记录"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM video_history WHERE job_id = ?", (job_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def delete_video_record(job_id: str, open_id: str = "") -> bool:
    """删除视频记录（校验归属）"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if open_id:
            cursor.execute(
                "DELETE FROM video_history WHERE job_id = ? AND open_id = ?",
                (job_id, open_id),
            )
        else:
            cursor.execute("DELETE FROM video_history WHERE job_id = ?", (job_id,))
        return cursor.rowcount > 0


def get_statistics(open_id: str = "") -> Dict:
    """获取统计信息（按用户过滤）"""
    with get_db_connection() as conn:
        cursor = conn.cursor()

        def q(sql, *params):
            cursor.execute(sql, params)
            return cursor.fetchone()[0]

        if open_id:
            total = q("SELECT COUNT(*) FROM video_history WHERE open_id = ?", open_id)
            completed = q("SELECT COUNT(*) FROM video_history WHERE open_id = ? AND status = 'completed'", open_id)
            processing = q("SELECT COUNT(*) FROM video_history WHERE open_id = ? AND status = 'processing'", open_id)
            failed = q("SELECT COUNT(*) FROM video_history WHERE open_id = ? AND status = 'failed'", open_id)
            cursor.execute("SELECT SUM(duration) FROM video_history WHERE open_id = ? AND status = 'completed'", (open_id,))
            total_duration = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(video_size) FROM video_history WHERE open_id = ? AND status = 'completed'", (open_id,))
            total_size = cursor.fetchone()[0] or 0
        else:
            total = q("SELECT COUNT(*) FROM video_history")
            completed = q("SELECT COUNT(*) FROM video_history WHERE status = 'completed'")
            processing = q("SELECT COUNT(*) FROM video_history WHERE status = 'processing'")
            failed = q("SELECT COUNT(*) FROM video_history WHERE status = 'failed'")
            cursor.execute("SELECT SUM(duration) FROM video_history WHERE status = 'completed'")
            total_duration = cursor.fetchone()[0] or 0
            cursor.execute("SELECT SUM(video_size) FROM video_history WHERE status = 'completed'")
            total_size = cursor.fetchone()[0] or 0

        return {
            "total": total,
            "completed": completed,
            "processing": processing,
            "failed": failed,
            "total_duration": round(total_duration, 2),
            "total_minutes": round(total_duration / 60, 1) if total_duration else 0,
            "total_size": total_size,
        }


def get_total_count(status: str = None, open_id: str = "") -> int:
    """获取记录总数（按用户过滤）"""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if open_id:
            if status:
                cursor.execute(
                    "SELECT COUNT(*) FROM video_history WHERE open_id = ? AND status = ?",
                    (open_id, status),
                )
            else:
                cursor.execute(
                    "SELECT COUNT(*) FROM video_history WHERE open_id = ?",
                    (open_id,),
                )
        else:
            if status:
                cursor.execute("SELECT COUNT(*) FROM video_history WHERE status = ?", (status,))
            else:
                cursor.execute("SELECT COUNT(*) FROM video_history")
        return cursor.fetchone()[0]


# 启动时初始化数据库
init_database()
