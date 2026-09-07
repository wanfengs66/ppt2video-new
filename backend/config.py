"""
PPT2Video 集中配置管理
所有配置项从 .env 读取，提供合理的默认值
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """应用配置"""

    # ── 路径配置 ──────────────────────────────────────────
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "files")
    VIDEO_OUTPUT_DIR: str = os.getenv("VIDEO_OUTPUT_DIR", "output_videos")
    DB_PATH: str = os.path.join(
        os.path.dirname(__file__),
        os.getenv("DB_PATH", "ppt2video.db"),
    )
    TASK_DB_PATH: str = os.path.join(
        os.path.dirname(__file__),
        os.getenv("TASK_DB_PATH", "files/tasks.db"),
    )

    # ── JWT 配置 ──────────────────────────────────────────
    JWT_SECRET: str = os.getenv("JWT_SECRET") or os.urandom(24).hex()
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = int(os.getenv("JWT_EXPIRE_HOURS", "24"))

    # ── SiliconFlow AI 配置 ───────────────────────────────
    SILICONFLOW_API_KEY: str = os.getenv("SILICONFLOW_API_KEY", "")
    SILICONFLOW_BASE_URL: str = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.cn/v1")
    TEXT_MODEL: str = os.getenv("TEXT_MODEL", "Qwen/Qwen2.5-7B-Instruct")
    VLM_MODEL: str = os.getenv("VLM_MODEL", "Qwen/Qwen2-VL-7B-Instruct")
    TTS_MODEL: str = os.getenv("TTS_MODEL", "FunAudioLLM/CosyVoice2-0.5B")
    TTS_MODE: str = os.getenv("TTS_MODE", "api")  # api / chattts / local

    # ── 外部工具路径（留空自动检测） ──────────────────────
    LIBREOFFICE_PATH: str = os.getenv("LIBREOFFICE_PATH", "")
    POPPLER_PATH: str = os.getenv("POPPLER_PATH", "")
    FFMPEG_PATH: str = os.getenv("FFMPEG_PATH", "")

    # ── VLM 过滤关键词（逗号分隔） ────────────────────────
    VLM_FILTER_PATTERNS: list = [
        p.strip()
        for p in os.getenv("VLM_FILTER_PATTERNS", "").split(",")
        if p.strip()
    ]

    # ── VLM 并发控制 ──────────────────────────────────────
    VLM_CONCURRENCY: int = int(os.getenv("VLM_CONCURRENCY", "1"))

    # ── 异步切换阈值（超过此页数自动走异步任务） ──────────
    ASYNC_THRESHOLD_SLIDES: int = int(os.getenv("ASYNC_THRESHOLD_SLIDES", "10"))

    # ── 服务配置 ──────────────────────────────────────────
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "9000"))
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:5173")
    COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"  # 生产 HTTPS 时设为 true
    FILE_RETENTION_DAYS: int = int(os.getenv("FILE_RETENTION_DAYS", "7"))  # 文件保留天数

    # ── 文件上传限制 ──────────────────────────────────────
    MAX_FILE_SIZE: int = int(os.getenv("MAX_FILE_SIZE", str(200 * 1024 * 1024)))
    ALLOWED_EXTENSIONS: set = {"pptx", "ppt"}


# 全局单例
settings = Settings()
