"""
简易异步任务队列（SQLite + 后台线程，无需外部依赖）
"""
import json
import sqlite3
import uuid
import threading
import time
import os
from datetime import datetime
from typing import Dict, Optional, Callable

from config import settings


class TaskQueue:
    """基于 SQLite 的任务队列，支持并发安全"""

    def __init__(self):
        os.makedirs(os.path.dirname(settings.TASK_DB_PATH), exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(settings.TASK_DB_PATH, check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        conn = self._get_conn()
        conn.execute("PRAGMA journal_mode=WAL")  # WAL 模式支持读写并发
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL,
                task_type TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                progress INTEGER DEFAULT 0,
                message TEXT DEFAULT '',
                params TEXT DEFAULT '{}',
                result TEXT DEFAULT '',
                error TEXT DEFAULT '',
                created_at TEXT,
                updated_at TEXT
            )
        """)
        conn.commit()

    def create_task(self, job_id: str, task_type: str, params: dict = None) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.now().isoformat()
        conn = self._get_conn()
        conn.execute(
            "INSERT INTO tasks (id, job_id, task_type, status, params, created_at, updated_at) VALUES (?, ?, ?, 'pending', ?, ?, ?)",
            (task_id, job_id, task_type, json.dumps(params or {}, ensure_ascii=False), now, now),
        )
        conn.commit()
        return task_id

    def update_task(self, task_id: str, status: str = None, progress: int = None,
                    message: str = None, result: str = None, error: str = None):
        updates = []
        values = []
        if status is not None:
            updates.append("status=?")
            values.append(status)
        if progress is not None:
            updates.append("progress=?")
            values.append(progress)
        if message is not None:
            updates.append("message=?")
            values.append(message)
        if result is not None:
            updates.append("result=?")
            values.append(result)
        if error is not None:
            updates.append("error=?")
            values.append(error)
        if not updates:
            return
        updates.append("updated_at=?")
        values.append(datetime.now().isoformat())
        values.append(task_id)
        conn = self._get_conn()
        conn.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id=?", values)
        conn.commit()

    def get_task(self, task_id: str) -> Optional[Dict]:
        conn = self._get_conn()
        row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row:
            return dict(row)
        return None

    def claim_pending_task(self) -> Optional[Dict]:
        """原子领取一个 pending 任务（避免多个 worker 抢同一个）"""
        conn = self._get_conn()
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM tasks WHERE status='pending' ORDER BY created_at ASC LIMIT 1"
        ).fetchone()
        if row:
            conn.execute("UPDATE tasks SET status='processing', updated_at=? WHERE id=?",
                         (datetime.now().isoformat(), row["id"]))
        conn.commit()
        if row:
            return dict(row)
        return None


# 全局单例
_task_queue = TaskQueue()
_worker_thread = None
_worker_running = False


def get_queue() -> TaskQueue:
    return _task_queue


def start_worker(handler: Callable[[Dict], None]):
    """启动后台工作线程"""
    global _worker_thread, _worker_running
    if _worker_running:
        return

    _worker_running = True

    def _loop():
        queue = get_queue()
        while _worker_running:
            try:
                task = queue.claim_pending_task()
                if task:
                    try:
                        handler(task)
                        # handler 已自行管理 completed/failed 状态和 result，
                        # 仅当 handler 未更新状态时才兜底标记完成
                        current = queue.get_task(task["id"])
                        if current and current["status"] == "processing":
                            queue.update_task(task["id"], status="completed", progress=100,
                                              message="处理完成")
                    except Exception as e:
                        queue.update_task(task["id"], status="failed", error=str(e),
                                          message=f"处理失败: {str(e)[:100]}")
            except Exception:
                pass
            time.sleep(2)

    _worker_thread = threading.Thread(target=_loop, daemon=True)
    _worker_thread.start()


def stop_worker():
    global _worker_running
    _worker_running = False
