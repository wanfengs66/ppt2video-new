"""
工作台恢复 API
恢复任务时同时加载已生成的解说词、音频、字幕状态
"""
import os
import re

import natsort
from fastapi import APIRouter, HTTPException, Query

from config import settings

router = APIRouter()

IMAGES_DIRECTORY = "images"
SCRIPTS_DIRECTORY = "scripts"


def _read_file_safe(path: str) -> str:
    """安全读取文件内容"""
    if not os.path.exists(path):
        return ""
    for encoding in ["utf-8", "gbk", "gb2312"]:
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read().strip()
        except (UnicodeDecodeError, UnicodeError):
            continue
    return ""


def _parse_slide_number(filename: str, prefix: str, suffix: str) -> int:
    """从文件名解析页码"""
    m = re.match(rf"{prefix}(\d+){suffix}", filename)
    return int(m.group(1)) if m else 0


@router.get("/api/restore-job")
async def restore_job(job_id: str = Query(..., description="任务 ID")):
    """
    恢复指定任务的全部信息，用于"继续编辑"功能
    返回：图片、已生成的解说词、音频/字幕状态
    """
    try:
        job_dir = os.path.join(settings.UPLOAD_DIR, job_id)
        if not os.path.exists(job_dir):
            # 检查是否是过期清理了
            from utils.database import get_video_record
            record = get_video_record(job_id)
            if record and record.get("status") == "expired":
                raise HTTPException(status_code=410, detail="该任务已超过3天，文件已过期清理，无法继续编辑")
            raise HTTPException(status_code=404, detail="任务不存在或已被删除")

        images_dir = os.path.join(job_dir, IMAGES_DIRECTORY)
        if not os.path.exists(images_dir):
            raise HTTPException(status_code=404, detail="任务图片不存在")

        # ── 图片列表 ──
        image_files = [
            f for f in os.listdir(images_dir)
            if re.match(r"slide_(\d+)\.png", f)
        ]
        if not image_files:
            raise HTTPException(status_code=404, detail="任务图片为空")

        image_files = natsort.natsorted(
            image_files,
            key=lambda f: int(re.match(r"slide_(\d+)\.png", f).group(1))
        )

        oss_urls = {}
        for png_file in image_files:
            match = re.match(r"slide_(\d+)\.png", png_file)
            slide_number = match.group(1)
            # 用文件修改时间做版本号，确保替换图片后能刷新缓存
            img_path = os.path.join(images_dir, png_file)
            mtime = int(os.path.getmtime(img_path)) if os.path.exists(img_path) else 0
            oss_urls[slide_number] = f"/files/{job_id}/images/{png_file}?v={mtime}"

        # ── 已生成的解说词 ──
        scripts = {}
        scripts_dir = os.path.join(job_dir, SCRIPTS_DIRECTORY)
        if os.path.exists(scripts_dir):
            for f in os.listdir(scripts_dir):
                m = re.match(r"slide_(\d+)\.md", f)
                if m:
                    idx = m.group(1)
                    content = _read_file_safe(os.path.join(scripts_dir, f))
                    if content:
                        scripts[idx] = content

        # ── 已生成的音频 ──
        audio_ready = {}
        if os.path.exists(scripts_dir):
            for f in os.listdir(scripts_dir):
                m = re.match(r"slide_(\d+)\.mp3", f)
                if m:
                    audio_ready[m.group(1)] = True

        # ── 已生成的字幕 ──
        srt_ready = {}
        if os.path.exists(scripts_dir):
            for f in os.listdir(scripts_dir):
                m = re.match(r"slide_(\d+)\.srt", f)
                if m:
                    srt_ready[m.group(1)] = True

        # ── 最终视频 ──
        video_url = ""
        final_video = os.path.join(job_dir, "final_video.mp4")
        if os.path.exists(final_video):
            video_url = final_video.replace("\\", "/")

        # ── SmartArt 信息 ──
        from utils.smartart_detector import detect_smartart_slides
        # 找原始 pptx 文件
        src_path = ""
        for fn in os.listdir(job_dir):
            if fn.lower().endswith(".pptx"):
                src_path = os.path.join(job_dir, fn)
                break
        smartart_slides = detect_smartart_slides(src_path) if src_path else []

        return {
            "message": "任务恢复成功",
            "file_path": job_id,
            "oss_urls": oss_urls,
            "slide_count": len(image_files),
            "scripts": scripts,
            "audio_ready": audio_ready,
            "srt_ready": srt_ready,
            "video_url": video_url,
            "smartart_slides": smartart_slides,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"恢复任务失败: {str(e)}")
