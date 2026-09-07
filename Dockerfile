# ── Stage 1: Build Frontend ──
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install
COPY frontend/ .
RUN npm run build

# ── Stage 2: Python Backend ──
FROM python:3.10-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-impress \
    poppler-utils \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖（包含 gunicorn）
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# 复制后端代码
COPY backend/ .

# 复制前端构建产物
COPY --from=frontend-builder /app/backend/static/frontend ./static/frontend

# 创建必要目录
RUN mkdir -p files output_videos

EXPOSE 9002

# 生产模式使用 gunicorn，开发模式可直接覆盖 CMD
CMD ["gunicorn", "-c", "gunicorn_conf.py", "main:app"]
