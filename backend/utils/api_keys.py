"""
硅基流动 API Key 轮询管理
支持多个 Key 自动轮询 + 限流时自动切换
"""
import threading
from itertools import cycle

from config import settings

_keys = [k.strip() for k in settings.SILICONFLOW_API_KEY.split(",") if k.strip()]
_key_cycle = cycle(_keys) if _keys else None
_key_lock = threading.Lock()


def get_next_key() -> str:
    """轮询获取下一个 API Key"""
    if not _keys:
        return settings.SILICONFLOW_API_KEY
    with _key_lock:
        return next(_key_cycle)


def get_all_keys() -> list:
    return _keys


def key_count() -> int:
    return len(_keys)
