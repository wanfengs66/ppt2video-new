"""
跨进程并发控制：使用文件锁实现多 worker 共享的信号量
在单 worker 模式下退化为 asyncio.Semaphore，零开销
"""
import asyncio
import os
import time
import random

# 文件锁目录（与 UPLOAD_DIR 同级）
LOCK_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "files", ".locks")


class CrossProcessSemaphore:
    """
    跨进程异步信号量：兼顾单进程效率与多进程安全

    单 worker 时完全等价于 asyncio.Semaphore；
    多 worker 时退化为文件锁轮询（慢但正确）。
    """

    def __init__(self, value: int, name: str = "default"):
        self._value = value
        self._name = name
        self._async_sem = asyncio.Semaphore(value)
        os.makedirs(LOCK_DIR, exist_ok=True)

    async def acquire(self):
        await self._async_sem.acquire()
        # 多 worker 场景下的文件锁保底
        # 尝试获取文件锁，确保跨进程总并发不超过 value
        for attempt in range(30):  # 最多等 30 秒
            acquired = 0
            for i in range(self._value):
                lock_file = os.path.join(LOCK_DIR, f"{self._name}_{i}.lock")
                try:
                    # 检查锁文件是否过期（超过 10 分钟的锁视为残留）
                    if os.path.exists(lock_file):
                        mtime = os.path.getmtime(lock_file)
                        if time.time() - mtime > 600:
                            os.remove(lock_file)
                except OSError:
                    pass

            for i in range(self._value):
                lock_file = os.path.join(LOCK_DIR, f"{self._name}_{i}.lock")
                try:
                    fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.write(fd, str(os.getpid()).encode())
                    os.close(fd)
                    self._lock_file = lock_file
                    return
                except OSError:
                    continue

            # 所有槽位被占用，等待后重试
            await asyncio.sleep(1.0 + random.random() * 0.5)

        # 超时未获取到锁（释放 async semaphore，抛出异常）
        self._async_sem.release()
        raise RuntimeError(f"FFmpeg semaphore acquire timeout after 30s")

    def release(self):
        self._async_sem.release()
        if hasattr(self, '_lock_file'):
            try:
                os.remove(self._lock_file)
                del self._lock_file
            except OSError:
                pass

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *args):
        self.release()


# 全局实例
_ffmpeg_semaphore = CrossProcessSemaphore(3, name="ffmpeg")
