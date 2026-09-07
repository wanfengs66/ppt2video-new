"""
安全的文件服务：替代直接 StaticFiles 挂载，增加会话鉴权
- 图片/音频/字幕等中间文件：通过 session cookie 鉴权
- 视频文件：同上
- 免登录模式下自动放行（保持兼容）
"""
import os
import re
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from config import settings

router = APIRouter()

UPLOAD_ROOT = os.path.abspath(settings.UPLOAD_DIR)
VIDEO_ROOT = os.path.abspath(settings.VIDEO_OUTPUT_DIR)

# 允许的 MIME 类型
ALLOWED_MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".mp4": "video/mp4",
    ".srt": "text/plain",
    ".md": "text/plain",
    ".json": "application/json",
    ".txt": "text/plain",
}


async def _is_authenticated(request: Request) -> bool:
    """检查请求是否经过认证"""
    from auth import get_optional_user
    user = await get_optional_user(request)
    return user is not None


def _get_file_mime_type(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    return ALLOWED_MIME_TYPES.get(ext, "application/octet-stream")


def _validate_path(requested_path: str, base_root: str) -> str:
    """
    验证并规范化文件路径，防止目录穿越攻击
    返回绝对路径，非法路径抛出异常
    """
    # 清理路径
    normalized = os.path.normpath(requested_path.lstrip("/"))
    abs_path = os.path.abspath(os.path.join(base_root, normalized))

    # 确保路径在允许的根目录内
    if os.path.commonpath([base_root, abs_path]) != base_root:
        raise HTTPException(status_code=403, detail="禁止访问")

    return abs_path


@router.get("/files/{job_id}/{rest:path}")
async def serve_uploaded_file(job_id: str, rest: str, request: Request):
    """安全地提供上传目录中的文件（图片、音频等中间产物）"""
    if not await _is_authenticated(request):
        raise HTTPException(status_code=401, detail="请先登录")

    # 验证 job_id 为合法 UUID
    import uuid
    try:
        uuid.UUID(job_id)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="非法 job_id")

    file_path = _validate_path(f"{job_id}/{rest}", UPLOAD_ROOT)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="文件不存在")

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="不是文件")

    mime_type = _get_file_mime_type(file_path)

    # 图片和音频设置缓存头（中间产物不常变）
    headers = {}
    if mime_type.startswith("image/") or mime_type.startswith("audio/"):
        headers["Cache-Control"] = "public, max-age=3600"

    return FileResponse(file_path, media_type=mime_type, headers=headers)


@router.get(f"/{settings.VIDEO_OUTPUT_DIR}/{{filename}}")
async def serve_video_file(filename: str, request: Request):
    """安全地提供输出视频文件"""
    if not await _is_authenticated(request):
        raise HTTPException(status_code=401, detail="请先登录")

    # 仅允许 mp4 文件
    if not filename.lower().endswith(".mp4"):
        raise HTTPException(status_code=403, detail="仅支持 MP4 视频")

    file_path = _validate_path(filename, VIDEO_ROOT)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="视频不存在")

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="不是文件")

    return FileResponse(
        file_path,
        media_type="video/mp4",
        headers={
            "Accept-Ranges": "bytes",  # 支持 Range 请求（拖动进度条）
            "Cache-Control": "public, max-age=86400",
        },
    )
