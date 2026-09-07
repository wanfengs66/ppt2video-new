import io
import os
import socket
import sys
import threading
import time

# 解决 Windows 终端 GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from api import ppt as ppt_router
from api import restore as restore_router
from api import history as history_router

app = FastAPI(
    title="PPT2Video",
    version="2.0",
    # 限制 JSON 请求体大小（防止内存耗尽攻击）
    max_request_body_size=2 * 1024 * 1024,  # 2MB
)

# 请求频率限制（在 CORS 之前添加，确保限流最优先）
from utils.rate_limiter import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 启动异步任务队列后台工作线程
from utils.task_queue import start_worker
from api.ppt import handle_async_task


@app.on_event("startup")
async def startup():
    start_worker(handle_async_task)
    print("[Worker] Async task worker started")


# 挂载静态文件目录（仅限公开资源）
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(_BASE_DIR, "static")), name="static")

# 安全文件服务（替代直接 StaticFiles 挂载，增加会话鉴权）
from utils.secure_files import router as secure_files_router
app.include_router(secure_files_router)

os.makedirs(settings.VIDEO_OUTPUT_DIR, exist_ok=True)

# 注册业务路由
app.include_router(ppt_router.router)
app.include_router(restore_router.router)
app.include_router(history_router.router)


# 前端构建产物服务（生产环境）
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), "static", "frontend")
if os.path.exists(FRONTEND_DIST):
    # 挂载前端 assets
    assets_dir = os.path.join(FRONTEND_DIST, "assets")
    if os.path.exists(assets_dir):
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/")
    async def serve_frontend_index():
        from fastapi.responses import FileResponse
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "PPT2Video API is running. Frontend not built yet."}

    # SPA fallback: 所有前端路由返回 index.html
    @app.get("/studio")
    @app.get("/login")
    @app.get("/history")
    async def serve_frontend_spa():
        from fastapi.responses import FileResponse
        index_path = os.path.join(FRONTEND_DIST, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"message": "Frontend not built yet."}
else:
    @app.get("/")
    async def api_root():
        return {
            "message": "PPT2Video API is running",
            "docs": "/docs",
            "note": "Frontend not built. Run 'npm run build' in frontend/ to generate static files."
        }


if __name__ == "__main__":
    import multiprocessing

    cpu_count = multiprocessing.cpu_count()
    workers = 1

    host_name = socket.gethostname()
    lan_ip = socket.gethostbyname(host_name)

    print(f"[OK] 启动 PPT2Video 服务...")
    print(f"   CPU 核心数: {cpu_count}")
    print(f"   Workers: {workers}")
    print(f"   局域网访问地址:")
    print(f"     http://{host_name}:{settings.PORT}")
    print(f"     http://{lan_ip}:{settings.PORT}")
    print(f"   本机访问地址: http://127.0.0.1:{settings.PORT}")
    print()

    # 定时清理 3 天前的临时文件
    def auto_cleanup():
        import shutil
        import datetime
        while True:
            try:
                now = datetime.datetime.now()
                retention = settings.FILE_RETENTION_DAYS
                for d in os.listdir(settings.UPLOAD_DIR):
                    p = os.path.join(settings.UPLOAD_DIR, d)
                    if os.path.isdir(p):
                        mtime = datetime.datetime.fromtimestamp(os.path.getmtime(p))
                        if (now - mtime).days >= retention:
                            try:
                                from utils.database import update_video_record
                                update_video_record(job_id=d, status="expired")
                            except Exception:
                                pass
                            shutil.rmtree(p)
                            print(f'[Cleanup] Removed old job: {d}, marked as expired')
            except Exception as e:
                print(f'[Cleanup] Error: {e}')
            time.sleep(3600)

    t = threading.Thread(target=auto_cleanup, daemon=True)
    t.start()
    print(f'[Cleanup] Auto-cleanup started ({settings.FILE_RETENTION_DAYS}-day retention)')

    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=workers,
        timeout_keep_alive=30,
        log_level="info",
    )
