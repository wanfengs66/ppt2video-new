"""
简易请求频率限制中间件（基于 IP + 滑动窗口）
"""
import time
import threading
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


# 默认限流规则（每 IP 每分钟最大请求数）
DEFAULT_RATE_LIMITS = {
    "/api/outline": 10,              # 上传：10次/分钟
    "/api/generate-script": 30,       # 单页解说词：30次/分钟
    "/api/generate-script-list": 5,   # 批量解说词：5次/分钟
    "/api/generate-audio": 10,        # 音频合成：10次/分钟
    "/api/generate-video": 5,         # 视频合成：5次/分钟（最消耗资源）
    "/api/async/generate-script-list": 5,
    "/api/async/task": 120,           # 轮询：120次/分钟（支持多标签）
    "/auth/callback": 20,
}


class InMemoryRateLimiter:
    """内存版限流器（滑动窗口）"""

    def __init__(self):
        self._windows: Dict[str, list] = defaultdict(list)
        self._lock = threading.Lock()

    def is_allowed(self, client_ip: str, path: str, max_requests: int, window_sec: int = 60) -> Tuple[bool, int]:
        """返回 (是否允许, 剩余等待秒数)"""
        now = time.time()
        key = f"{client_ip}:{path}"

        with self._lock:
            timestamps = self._windows.get(key, [])
            # 清理过期记录
            timestamps = [t for t in timestamps if now - t < window_sec]

            if len(timestamps) < max_requests:
                timestamps.append(now)
                self._windows[key] = timestamps
                return True, 0
            else:
                oldest = timestamps[0]
                wait = int(window_sec - (now - oldest)) + 1
                self._windows[key] = timestamps
                return False, max(wait, 0)


_rate_limiter = InMemoryRateLimiter()


class RateLimitMiddleware(BaseHTTPMiddleware):
    """FastAPI 限流中间件"""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # 跳过静态文件和非 API 请求
        if not path.startswith("/api/") and path not in ("/auth/callback",):
            return await call_next(request)

        # 查找匹配的限流规则（精确匹配优先，其次前缀匹配）
        max_requests = None
        for route, limit in DEFAULT_RATE_LIMITS.items():
            if path == route or path.startswith(route + "/") or path.startswith(route + "?"):
                max_requests = limit
                break

        if max_requests is None:
            max_requests = 60  # 默认 API 限制

        # 获取客户端 IP
        client_ip = request.client.host if request.client else "unknown"
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            client_ip = forwarded.split(",")[0].strip()

        allowed, wait_sec = _rate_limiter.is_allowed(client_ip, path, max_requests)

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": f"请求过于频繁，请 {wait_sec} 秒后再试"},
                headers={"Retry-After": str(wait_sec)},
            )

        response = await call_next(request)
        return response
