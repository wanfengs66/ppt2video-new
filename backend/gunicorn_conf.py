"""
Gunicorn 生产配置
启动: gunicorn -c gunicorn_conf.py main:app
"""
import multiprocessing
import os

# 绑定地址
bind = f"{os.getenv('HOST', '0.0.0.0')}:{os.getenv('PORT', '9000')}"

# Worker 配置
workers = int(os.getenv("GUNICORN_WORKERS", min(4, multiprocessing.cpu_count() * 2 + 1)))
worker_class = "uvicorn.workers.UvicornWorker"
threads = int(os.getenv("GUNICORN_THREADS", 2))

# 超时
timeout = int(os.getenv("GUNICORN_TIMEOUT", 120))
keepalive = 30

# 日志
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")  # "-" = stdout
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# 进程命名
proc_name = "ppt2video"

# 优雅重启
max_requests = 1000
max_requests_jitter = 100
graceful_timeout = 30
