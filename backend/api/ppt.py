import asyncio
import json
import os
import re
import shutil
import subprocess
import time
import traceback
import uuid

import natsort
from fastapi import APIRouter, Body, File, HTTPException, Query, Request, UploadFile

from config import settings
from utils.audio_generate import calculate_audio_durations, generate_srt_from_audio, synthesize_md_to_speech
from utils.feishu_sync import sync_user_usage, sync_video_completed
from utils.image_to_text import parse_image_to_text
from utils.movie_editor import concatenate_videos, image_to_video, merge_audio_video_subtitle
from utils.pptx_to_image import pptx_to_images, get_libreoffice_command
from utils.context_manager import PPTContextManager
from utils.enhanced_narration import generate_contextual_narration
from utils.database import add_video_record, update_video_record
from utils.concurrency import _ffmpeg_semaphore

router = APIRouter()

UPLOAD_DIRECTORY = settings.UPLOAD_DIR
UPLOAD_ROOT = os.path.abspath(UPLOAD_DIRECTORY)
IMAGES_DIRECTORY = "images"
SCRIPTS_DIRECTORY = "scripts"
VIDEO_OUTPUT_DIR = settings.VIDEO_OUTPUT_DIR
ALLOWED_EXTENSIONS = settings.ALLOWED_EXTENSIONS
MAX_FILE_SIZE = settings.MAX_FILE_SIZE

os.makedirs(UPLOAD_DIRECTORY, exist_ok=True)
os.makedirs(VIDEO_OUTPUT_DIR, exist_ok=True)


def _get_user_from_request(request: Request):
    """本地模式：返回默认本地用户"""
    from auth import LOCAL_USER
    return {"open_id": LOCAL_USER["open_id"], "name": LOCAL_USER["name"]}


def save_to_local(local_file_path: str, output_name: str) -> str:
    output_path = os.path.join(VIDEO_OUTPUT_DIR, output_name)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    shutil.copy2(local_file_path, output_path)
    return f"/{VIDEO_OUTPUT_DIR}/{output_name}"


def get_slide_index(slide_key: str):
    if slide_key is None:
        return None
    slide_key = str(slide_key)
    if slide_key.isdigit():
        return int(slide_key)
    match = re.search(r"slide_(\d+)", slide_key)
    if match:
        return int(match.group(1))
    return None


def extract_all_slide_texts_from_pptx(
    source_pptx_path: str,
    unique_images_directory: str,
    use_vlm: bool = True,
) -> list:
    """两级 fallback 文本提取：VLM → python-pptx → SmartArt"""
    if use_vlm and unique_images_directory and os.path.exists(unique_images_directory):
        try:
            from utils.vlm_text_extractor import extract_slide_texts_with_vlm
            slide_texts = extract_slide_texts_with_vlm(unique_images_directory)
            if slide_texts and any(slide_texts):
                print(f"[Extract] VLM success: {len(slide_texts)} pages")
                return slide_texts
            print(f"[Extract] VLM returned empty")
        except Exception as e:
            print(f"[Extract] VLM error: {e}")

    if source_pptx_path:
        try:
            from utils.pptx_text import extract_slide_texts
            slide_texts = extract_slide_texts(source_pptx_path)
            if slide_texts and any(slide_texts):
                print(f"[Extract] python-pptx success: {len(slide_texts)} pages")
                return slide_texts
            print(f"[Extract] python-pptx returned empty")
        except Exception as e:
            print(f"[Extract] python-pptx error: {e}")

    if source_pptx_path:
        try:
            from utils.smartart_detector import extract_smartart_texts
            slide_texts = extract_smartart_texts(source_pptx_path)
            if slide_texts and any(slide_texts):
                print(f"[Extract] SmartArt text: {len(slide_texts)} pages")
                return slide_texts
        except Exception as e:
            print(f"[Extract] SmartArt error: {e}")

    return []


def _extract_single_slide_text(
    source_pptx_path: str,
    images_directory: str,
    slide_index: int,
    use_vlm: bool = True,
) -> str:
    """提取单页文字：VLM 优先（识别更准确），python-pptx 兜底，仅提取当前页"""
    # 1. VLM 优先：视觉识别当前页（能处理图片/图表中的文字）
    if use_vlm and images_directory and os.path.exists(images_directory):
        image_path = os.path.join(images_directory, f"slide_{slide_index}.png")
        if os.path.exists(image_path):
            try:
                from utils.vlm_text_extractor import get_slide_text_with_vlm
                text = get_slide_text_with_vlm(image_path)
                if text and text.strip():
                    return text.strip()
            except Exception:
                pass

    # 2. python-pptx 兜底（结构化提取，无 API 调用）
    if source_pptx_path:
        try:
            from utils.pptx_text import extract_slide_texts
            all_texts = extract_slide_texts(source_pptx_path)
            if all_texts and 1 <= slide_index <= len(all_texts):
                text = all_texts[slide_index - 1]
                if text and text.strip():
                    return text.strip()
        except Exception:
            pass

    # 3. SmartArt 兜底
    if source_pptx_path:
        try:
            from utils.smartart_detector import extract_smartart_texts
            all_texts = extract_smartart_texts(source_pptx_path)
            if all_texts and 1 <= slide_index <= len(all_texts):
                return all_texts[slide_index - 1].strip()
        except Exception:
            pass

    return ""


def clean_slide_texts(texts: list) -> list:
    """统一清理提取到的文本"""
    cleaned = []
    for t in texts:
        t = re.sub(r"(?<=[^\x00-\x7F])\s*[dD]\s*(?=[^\x00-\x7F])", "", t)
        t = re.sub(r'[dD]{2,}', '', t)
        cleaned.append(t.strip())
    return cleaned


def normalize_slide_index(slide_key: str) -> int:
    slide_index = get_slide_index(slide_key)
    if slide_index is None or slide_index <= 0:
        raise HTTPException(status_code=400, detail="非法 slide index")
    return slide_index


def resolve_upload_directory(file_path: str) -> str:
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path 参数不能为空")
    try:
        job_id = str(uuid.UUID(str(file_path)))
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail="非法 file_path") from exc
    resolved_path = os.path.abspath(os.path.join(UPLOAD_ROOT, job_id))
    if os.path.commonpath([UPLOAD_ROOT, resolved_path]) != UPLOAD_ROOT:
        raise HTTPException(status_code=400, detail="非法 file_path")
    return resolved_path


def save_sentences_to_markdown(text: str, output_directory: str, slide_index: int) -> None:
    """
    将解说词拆分为句子并保存为 markdown 文件。
    规则：
    1. 按句末标点（。！？）拆分
    2. 过短的句子（<10字）合并到前一句，但合并后不超过 MAX_SENTENCE_LENGTH
    3. 超过 MAX_SENTENCE_LENGTH 的句子在逗号/分号处二次拆分
    """
    MAX_SENTENCE_LENGTH = 80  # 单个句子最大字数（TTS API 限制 ~100 字，留余量）

    paragraph_directory = os.path.join(output_directory, f"paragraph_{slide_index}")
    os.makedirs(paragraph_directory, exist_ok=True)
    text = text.replace("\n", "")
    # 保留标点的拆分
    raw_parts = re.split(r'(?<=[。！？])', text)
    raw_sentences = [s.strip() for s in raw_parts if s.strip()]

    # 合并过短句子
    sentences = []
    for s in raw_sentences:
        if sentences and len(s.rstrip('。！？')) < 10:
            candidate = sentences[-1] + s
            if len(candidate) <= MAX_SENTENCE_LENGTH:
                sentences[-1] = candidate
                continue
        sentences.append(s)

    # 二次拆分：超长句子在逗号/分号处切开
    final_sentences = []
    for s in sentences:
        if len(s) <= MAX_SENTENCE_LENGTH:
            final_sentences.append(s)
        else:
            sub_parts = re.split(r'(?<=[，,；;])', s)
            buf = ""
            for part in sub_parts:
                if len(buf) + len(part) <= MAX_SENTENCE_LENGTH:
                    buf += part
                else:
                    if buf:
                        final_sentences.append(buf)
                    # 如果单个 part 还是超长，按固定长度强制切
                    if len(part) > MAX_SENTENCE_LENGTH:
                        for i in range(0, len(part), MAX_SENTENCE_LENGTH):
                            final_sentences.append(part[i:i + MAX_SENTENCE_LENGTH])
                    else:
                        buf = part
            if buf:
                final_sentences.append(buf)

    for index, sentence in enumerate(final_sentences, start=1):
        sentence_path = os.path.join(paragraph_directory, f"sentence_{index}.md")
        with open(sentence_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(sentence)


def get_source_pptx_path(upload_directory: str) -> str:
    for file_name in os.listdir(upload_directory):
        if file_name.lower().endswith(".pptx"):
            return os.path.join(upload_directory, file_name)
    for file_name in os.listdir(upload_directory):
        if file_name.lower().endswith(".ppt"):
            return os.path.join(upload_directory, file_name)
    return ""


def is_remote_image_path(image_path: str) -> bool:
    return bool(re.match(r"^(https?:)?//|^data:", str(image_path or ""), flags=re.IGNORECASE))


def resolve_slide_image_path(upload_directory: str, slide_index: int, requested_path: str = "") -> str:
    default_path = os.path.abspath(os.path.join(upload_directory, IMAGES_DIRECTORY, f"slide_{slide_index}.png"))
    candidates = []
    if requested_path and not is_remote_image_path(requested_path):
        candidates.append(os.path.abspath(requested_path))
        candidates.append(os.path.abspath(os.path.join(upload_directory, requested_path)))
    candidates.append(default_path)
    for candidate in candidates:
        try:
            if os.path.commonpath([upload_directory, candidate]) == upload_directory and os.path.exists(candidate):
                return candidate
        except ValueError:
            continue
    return default_path


def build_source_text(ppt_source_text: str, image_path: str, global_context: str = "") -> str:
    text = (ppt_source_text or "").strip()
    if global_context:
        text = f"[PPT整体内容概览]\n{global_context}\n\n[当前页内容]\n{text}"
    return text


@router.post("/api/outline")
async def outline(request: Request, file: UploadFile = File(...)):
    file_extension = file.filename.split(".")[-1].lower()
    if file_extension not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"支持的文件扩展名为 {', '.join(ALLOWED_EXTENSIONS)}")

    file_content = await file.read(MAX_FILE_SIZE + 1)
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="上传的 PPTX 需控制在 200MB 以内")

    unique_id = str(uuid.uuid4())
    unique_upload_directory = os.path.join(UPLOAD_DIRECTORY, unique_id)
    unique_images_directory = os.path.join(unique_upload_directory, IMAGES_DIRECTORY)
    os.makedirs(unique_images_directory, exist_ok=True)

    file_path = os.path.join(unique_upload_directory, f"source.{file_extension}")
    with open(file_path, "wb") as buffer:
        buffer.write(file_content)

    if file_extension == "ppt":
        try:
            pptx_path = os.path.join(unique_upload_directory, "source.pptx")
            subprocess.run(
                [get_libreoffice_command(), "--headless", "--convert-to", "pptx",
                 "--outdir", unique_upload_directory, file_path],
                capture_output=True, text=True, timeout=120, check=True
            )
            file_path = pptx_path
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"PPT 转 PPTX 失败: {str(e)}")

    try:
        from utils.pptx_to_image_ppt import pptx_to_images_via_powerpoint
    except ImportError:
        pptx_to_images_via_powerpoint = None
    if not pptx_to_images_via_powerpoint or not pptx_to_images_via_powerpoint(file_path, unique_images_directory):
        print(f"[Upload] PowerPoint render failed, falling back to LibreOffice")
        pptx_to_images(file_path, unique_images_directory, None)

    image_files = natsort.natsorted(
        (f for f in os.listdir(unique_images_directory) if re.match(r"slide_(\d+)\.png", f)),
        key=lambda f: int(re.match(r"slide_(\d+)\.png", f).group(1))
    )
    image_urls = {}
    for png_file in image_files:
        match = re.match(r"slide_(\d+)\.png", png_file)
        slide_number = match.group(1)
        image_urls[slide_number] = f"/files/{unique_id}/images/{png_file}"

    from utils.smartart_detector import detect_smartart_slides
    src_path = get_source_pptx_path(unique_upload_directory)
    smartart_slides = detect_smartart_slides(src_path)

    user = _get_user_from_request(request)

    try:
        add_video_record(
            job_id=unique_id,
            original_filename=file.filename,
            slide_count=len(image_files),
            open_id=user["open_id"] if user else "",
        )
    except Exception as e:
        print(f"[History] Failed to add video record: {e}")
    if user and user["open_id"] != "local-user":
        await sync_user_usage(open_id=user["open_id"], name=user["name"])
    return {
        "message": "文件已成功处理",
        "file_path": unique_id,
        "oss_urls": image_urls,
        "smartart_slides": smartart_slides,
    }


@router.post("/api/generate-script")
async def generate_script(payload: dict = Body(...)):
    oss_url = payload.get("oss_url", "")
    file_path = payload.get("file_path", "")
    slide_index = normalize_slide_index(payload.get("index", "1"))
    if not oss_url:
        raise HTTPException(status_code=400, detail="参数不能为空")

    understanding_level = payload.get("understanding_level", "text-understanding")
    use_vlm_extraction = payload.get("use_vlm_extraction", True)
    use_enhanced_narration = payload.get("use_enhanced_narration", True)

    unique_upload_directory = resolve_upload_directory(file_path)
    unique_scripts_directory = os.path.join(unique_upload_directory, SCRIPTS_DIRECTORY)
    unique_images_directory = os.path.join(unique_upload_directory, IMAGES_DIRECTORY)
    os.makedirs(unique_scripts_directory, exist_ok=True)

    context_manager = PPTContextManager(file_path, UPLOAD_DIRECTORY)
    source_pptx_path = get_source_pptx_path(unique_upload_directory)

    # 单页模式：先尝试快速的 python-pptx 提取，仅当前页回退到 VLM
    ppt_source_text = _extract_single_slide_text(
        source_pptx_path, unique_images_directory, slide_index, use_vlm=use_vlm_extraction
    )
    if ppt_source_text:
        context_manager.set_slide_text(slide_index, ppt_source_text)

    if use_enhanced_narration:
        context_info = context_manager.get_context_for_slide(slide_index, window_size=2)
        prev_script = context_manager.get_previous_script(slide_index)
        next_text = context_manager.get_next_text(slide_index)
        total_slides = len([f for f in os.listdir(unique_images_directory) if f.startswith("slide_") and f.endswith(".png")]) if os.path.exists(unique_images_directory) else 1

        flag, parsed_text = generate_contextual_narration(
            current_text=ppt_source_text, context_info=context_info,
            prev_script=prev_script, next_text=next_text,
            understanding_level=understanding_level,
            slide_index=slide_index, total_slides=total_slides
        )
        if not flag:
            raise HTTPException(status_code=471, detail=parsed_text)
    else:
        source_text = build_source_text(ppt_source_text, oss_url)
        flag, parsed_text = parse_image_to_text(oss_url, understanding_level, source_text=source_text, ocr_text="")
        if not flag:
            raise HTTPException(status_code=471, detail=parsed_text)

    context_manager.set_generated_script(slide_index, parsed_text)
    md_filepath = os.path.join(unique_scripts_directory, f"slide_{slide_index}.md")
    save_sentences_to_markdown(parsed_text, unique_scripts_directory, slide_index)
    with open(md_filepath, "w", encoding="utf-8") as md_file:
        md_file.write(parsed_text)

    return {"message": "文案生成成功", "scripts": parsed_text}


@router.post("/api/generate-script-list")
async def generate_script_list(payload: dict = Body(...)):
    oss_urls = payload.get("oss_urls", {})
    file_path = payload.get("file_path", "")
    if not oss_urls:
        raise HTTPException(status_code=490, detail="oss_urls 不能为空")

    slide_count = len(oss_urls)
    if slide_count > settings.ASYNC_THRESHOLD_SLIDES:
        raise HTTPException(
            status_code=400,
            detail=f"页面数({slide_count})超过同步处理上限({settings.ASYNC_THRESHOLD_SLIDES})，"
                   f"请使用 /api/async/generate-script-list 异步接口",
        )

    understanding_level = payload.get("understanding_level", "text-understanding")
    use_vlm_extraction = payload.get("use_vlm_extraction", True)
    use_enhanced_narration = payload.get("use_enhanced_narration", True)

    unique_upload_directory = resolve_upload_directory(file_path)
    unique_scripts_directory = os.path.join(unique_upload_directory, SCRIPTS_DIRECTORY)
    os.makedirs(unique_scripts_directory, exist_ok=True)
    source_pptx_path = get_source_pptx_path(unique_upload_directory)
    unique_images_directory = os.path.join(unique_upload_directory, IMAGES_DIRECTORY)

    context_manager = PPTContextManager(file_path, UPLOAD_DIRECTORY)
    context_manager.context["slide_texts"] = {}
    context_manager.context["generated_scripts"] = {}
    context_manager.context["ppt_full_content"] = ""
    context_manager._save_context()

    slide_source_texts = extract_all_slide_texts_from_pptx(
        source_pptx_path, unique_images_directory, use_vlm=use_vlm_extraction
    )
    slide_source_texts = clean_slide_texts(slide_source_texts)
    for idx, text in enumerate(slide_source_texts, start=1):
        if text:
            context_manager.set_slide_text(idx, text)

    sorted_oss_urls = sorted(
        oss_urls.items(),
        key=lambda item: get_slide_index(item[0]) if get_slide_index(item[0]) is not None else float("inf"),
    )

    parsed_scripts = []
    failures = []
    total_slides = len(slide_source_texts)

    # 构建任务列表
    tasks = []
    for slide_key, oss_url in sorted_oss_urls:
        slide_index = get_slide_index(slide_key)
        if slide_index is None:
            failures.append({"slide": slide_key, "error": "Invalid slide key"})
            continue
        ppt_text = slide_source_texts[slide_index - 1] if 1 <= slide_index <= len(slide_source_texts) else ""
        tasks.append((slide_index, oss_url, ppt_text))

    # 并行生成（2 并发，兼顾速度和上下文连贯性）
    import threading
    ctx_lock = threading.Lock()

    def _gen_one(slide_index, oss_url, ppt_text):
        for retry in range(2):
            try:
                with ctx_lock:
                    context_info = context_manager.get_context_for_slide(slide_index, window_size=2)
                    prev_script = context_manager.get_previous_script(slide_index)
                    next_text = context_manager.get_next_text(slide_index)

                if use_enhanced_narration:
                    flag, text = generate_contextual_narration(
                        current_text=ppt_text, context_info=context_info,
                        prev_script=prev_script, next_text=next_text,
                        understanding_level=understanding_level,
                        slide_index=slide_index, total_slides=total_slides,
                        skip_quality_check=True,
                    )
                else:
                    source_text = build_source_text(ppt_text, oss_url, global_context="")
                    flag, text = parse_image_to_text(oss_url, understanding_level, source_text=source_text, ocr_text="")

                if not flag:
                    if retry < 1:
                        time.sleep(2)
                        continue
                    return {"error": text, "slide_index": slide_index}

                with ctx_lock:
                    context_manager.set_generated_script(slide_index, text)
                return {"slide_index": slide_index, "image_url": oss_url, "text": text}

            except Exception as exc:
                if retry < 1:
                    time.sleep(2)
                else:
                    return {"error": str(exc), "slide_index": slide_index}
        return {"error": "max retries", "slide_index": slide_index}

    # 先串行生成首页（为后续提供上下文种子）
    if tasks:
        first = tasks[0]
        result = _gen_one(*first)
        if "error" in result:
            failures.append({"slide": result["slide_index"], "error": result["error"]})
        else:
            parsed_scripts.append(result)
        tasks = tasks[1:]

    # 剩余页面并行生成
    if tasks:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        NARRATION_WORKERS = min(3, len(tasks))  # 最多 3 并发
        with ThreadPoolExecutor(max_workers=NARRATION_WORKERS) as executor:
            future_map = {
                executor.submit(_gen_one, si, ou, pt): si
                for si, ou, pt in tasks
            }
            for future in as_completed(future_map):
                result = future.result()
                if "error" in result:
                    failures.append({"slide": result["slide_index"], "error": result["error"]})
                else:
                    parsed_scripts.append(result)

    # 按页码排序
    parsed_scripts.sort(key=lambda x: x["slide_index"])

    if failures:
        raise HTTPException(status_code=502, detail={
            "message": "批量文案生成失败", "failures": failures,
        })

    script_data = []
    for item in parsed_scripts:
        slide_index = item["slide_index"]
        parsed_text = item["text"]
        md_filepath = os.path.join(unique_scripts_directory, f"slide_{slide_index}.md")
        save_sentences_to_markdown(parsed_text, unique_scripts_directory, slide_index)
        with open(md_filepath, "w", encoding="utf-8") as md_file:
            md_file.write(parsed_text)
        script_data.append({"image_url": item["image_url"], "text": parsed_text})

    return {"message": "文案生成成功", "scripts": script_data}


@router.post("/api/save-script")
async def save_script(payload: dict = Body(...)):
    slide_index = normalize_slide_index(payload.get("index", ""))
    text = payload.get("text", "")
    file_path = payload.get("file_path", "")
    if not text:
        raise HTTPException(status_code=400, detail="参数不能为空")

    unique_upload_directory = resolve_upload_directory(file_path)
    unique_scripts_directory = os.path.join(unique_upload_directory, SCRIPTS_DIRECTORY)
    if not os.path.exists(unique_scripts_directory):
        raise HTTPException(status_code=404, detail="指定目录不存在")

    md_filepath = os.path.join(unique_scripts_directory, f"slide_{slide_index}.md")
    if os.path.exists(md_filepath):
        os.remove(md_filepath)

    paragraph_directory = os.path.join(unique_scripts_directory, f"paragraph_{slide_index}")
    if os.path.exists(paragraph_directory):
        shutil.rmtree(paragraph_directory)

    with open(md_filepath, "w", encoding="utf-8") as md_file:
        md_file.write(text)

    save_sentences_to_markdown(text, unique_scripts_directory, slide_index)
    return {"message": "文案保存成功"}


@router.post("/api/generate-audio")
async def generate_audio(payload: dict = Body(...)):
    voice_type = payload.get("voice_type", "male")
    file_path = payload.get("file_path", "")
    slide_index = payload.get("index")  # 可选：仅生成指定页

    unique_upload_directory = resolve_upload_directory(file_path)
    unique_scripts_directory = os.path.join(unique_upload_directory, SCRIPTS_DIRECTORY)
    if not os.path.exists(unique_scripts_directory):
        raise HTTPException(status_code=404, detail="指定目录不存在")

    synthesize_md_to_speech(unique_scripts_directory, voice_type=voice_type, slide_index=slide_index)
    return {"message": "音频生成成功"}


@router.post("/api/generate-srt")
async def generate_srt(payload: dict = Body(...)):
    file_path = payload.get("file_path", "")
    slide_index = payload.get("index")  # 可选：仅生成指定页

    unique_upload_directory = resolve_upload_directory(file_path)
    unique_scripts_directory = os.path.join(unique_upload_directory, SCRIPTS_DIRECTORY)
    if not os.path.exists(unique_scripts_directory):
        raise HTTPException(status_code=404, detail="指定目录不存在")

    generate_srt_from_audio(unique_scripts_directory, unique_scripts_directory, slide_index=slide_index)
    return {"message": "字幕生成成功"}


@router.post("/api/generate-video")
async def generate_video(request: Request, payload: dict = Body(...)):
    file_path = payload.get("file_path", "")
    subtitle_enabled = payload.get("subtitle_enabled", False)  # 默认关

    unique_upload_directory = resolve_upload_directory(file_path)
    unique_scripts_directory = os.path.join(unique_upload_directory, SCRIPTS_DIRECTORY)
    unique_image_directory = os.path.join(unique_upload_directory, IMAGES_DIRECTORY)
    if not os.path.exists(unique_scripts_directory):
        raise HTTPException(status_code=404, detail="指定目录不存在")
    if not os.path.exists(unique_image_directory):
        raise HTTPException(status_code=404, detail="图片目录不存在")

    pattern = r"^slide_(\d+)\.png$"
    image_files = [
        os.path.join(unique_image_directory, file_name)
        for file_name in os.listdir(unique_image_directory)
        if re.match(pattern, file_name)
    ]
    image_files = natsort.natsorted(
        image_files,
        key=lambda path: int(re.match(pattern, os.path.basename(path)).group(1)),
    )
    if not image_files:
        raise HTTPException(status_code=404, detail="未找到可用于合成的视频图片")

    audio_durations = calculate_audio_durations(unique_scripts_directory)
    if len(audio_durations) != len(image_files):
        raise HTTPException(status_code=400, detail="图片页数与音频页数不一致，请先完整生成讲稿、音频和字幕")

    for index in range(1, len(image_files) + 1):
        audio_file_path = os.path.join(unique_scripts_directory, f"slide_{index}.mp3")
        srt_file_path = os.path.join(unique_scripts_directory, f"slide_{index}.srt")
        if not os.path.exists(audio_file_path) or not os.path.exists(srt_file_path):
            raise HTTPException(status_code=400, detail=f"第 {index} 页缺少音频或字幕文件")

    fps = 6
    frame_duration = 1.0 / fps  # 单帧时长 ~0.167s
    temp_video_directory = os.path.join(unique_upload_directory, "videos")
    os.makedirs(temp_video_directory, exist_ok=True)

    async def process_page(image_file: str, duration: float, index: int):
        async with _ffmpeg_semaphore:
            # 将时长对齐到帧边界，消除拼接时边界碎片帧
            aligned_duration = round(duration / frame_duration) * frame_duration
            if aligned_duration <= 0:
                aligned_duration = frame_duration

            page_video_path = os.path.join(temp_video_directory, f"slide_{index}.mp4")
            await image_to_video(image_file, aligned_duration, fps, f"slide_{index}", temp_video_directory)

            audio_file_path = os.path.join(unique_scripts_directory, f"slide_{index}.mp3")
            srt_file_path = os.path.join(unique_scripts_directory, f"slide_{index}.srt")
            page_video_with_audio_subtitle_path = os.path.join(
                temp_video_directory, f"slide_{index}_with_audio_subtitle.mp4",
            )

            try:
                await merge_audio_video_subtitle(
                    page_video_path, audio_file_path, srt_file_path if subtitle_enabled else None,
                    page_video_with_audio_subtitle_path,
                    target_duration=aligned_duration,
                )
            except Exception as exc:
                print(f"Error processing slide_{index}: {exc}")
                raise

            return page_video_with_audio_subtitle_path

    tasks = [
        process_page(image_file, audio_durations[index - 1], index)
        for index, image_file in enumerate(image_files, start=1)
    ]
    page_videos_with_audio_subtitle = await asyncio.gather(*tasks, return_exceptions=True)

    for index, task_result in enumerate(page_videos_with_audio_subtitle, start=1):
        if isinstance(task_result, Exception):
            raise HTTPException(status_code=500, detail=f"Error processing slide_{index}: {task_result}")

    final_video_path = os.path.join(unique_upload_directory, "final_video.mp4")
    concatenate_videos(page_videos_with_audio_subtitle, final_video_path)

    video_filename = f"{file_path}_final_video.mp4"
    video_url = save_to_local(final_video_path, video_filename)

    user = _get_user_from_request(request)

    try:
        video_size = os.path.getsize(os.path.join(VIDEO_OUTPUT_DIR, video_filename))
        total_duration = sum(audio_durations)
        update_video_record(
            job_id=file_path, video_url=video_url,
            video_size=video_size, duration=total_duration, status="completed",
            open_id=user["open_id"] if user else "",
        )
    except Exception as e:
        print(f"Failed to update video record: {e}")

    if user and user["open_id"] != "local-user":
        await sync_user_usage(open_id=user["open_id"], name=user["name"])
        # 同步累计视频时长到多维表格
        total_minutes = total_duration / 60.0
        await sync_video_completed(open_id=user["open_id"], name=user["name"], duration_minutes=total_minutes)

    return {"message": "视频生成成功", "video_url": video_url}


@router.get("/api/resources")
async def resources(file_path: str = Query(..., description="路径到上传文件的目录")):
    unique_upload_directory = resolve_upload_directory(file_path)
    unique_scripts_directory = os.path.join(unique_upload_directory, SCRIPTS_DIRECTORY)
    if not os.path.exists(unique_scripts_directory):
        raise HTTPException(status_code=404, detail="指定目录不存在")

    files_by_index = {}
    for file_name in os.listdir(unique_scripts_directory):
        mp3_match = re.match(r"slide_(\d+)\.mp3", file_name)
        if mp3_match:
            index = mp3_match.group(1)
            files_by_index.setdefault(index, {})["mp3"] = os.path.join(unique_scripts_directory, file_name)
            continue
        md_match = re.match(r"slide_(\d+)\.md", file_name)
        if md_match:
            index = md_match.group(1)
            files_by_index.setdefault(index, {})["md"] = os.path.join(unique_scripts_directory, file_name)

    result = [
        {"index": index, "mp3": files.get("mp3"), "md": files.get("md")}
        for index, files in files_by_index.items()
    ]
    return {"message": "获取成功", "files": result}


@router.get("/api/heartbeat")
async def heartbeat():
    return {"message": "Heartbeat", "status": "OK"}


@router.get("/api/voices")
async def list_voices():
    """返回可用音色列表"""
    voices = [
        {"label": "Alex (男声)", "value": "FunAudioLLM/CosyVoice2-0.5B:alex"},
        {"label": "Anna (女声)", "value": "FunAudioLLM/CosyVoice2-0.5B:anna"},
    ]
    return {"voices": voices}


# ─── 异步任务队列 ─────────────────────────────────────────────
@router.post("/api/async/generate-script-list")
async def async_generate_script_list(payload: dict = Body(...)):
    """异步批量生成解说词"""
    file_path = payload.get("file_path", "")
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path 不能为空")

    from utils.task_queue import get_queue
    queue = get_queue()
    task_id = queue.create_task(job_id=file_path, task_type="generate-scripts", params=payload)
    return {"message": "任务已提交", "task_id": task_id, "status": "pending"}


@router.get("/api/async/task/{task_id}")
async def get_task_status(task_id: str):
    """查询任务状态"""
    from utils.task_queue import get_queue
    queue = get_queue()
    task = queue.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "task_id": task["id"], "status": task["status"],
        "progress": task["progress"], "message": task["message"],
        "result": json.loads(task["result"]) if task["result"] else None,
        "error": task["error"], "created_at": task["created_at"], "updated_at": task["updated_at"],
    }


@router.post("/api/replace-slide-image")
async def replace_slide_image(request: Request, file: UploadFile = File(...)):
    """替换指定幻灯片图片（解决渲染偏移问题）"""
    file_path = request.headers.get("X-File-Path", "")
    slide_index = request.headers.get("X-Slide-Index", "")

    if not file_path or not slide_index:
        raise HTTPException(status_code=400, detail="缺少 file_path 或 slide_index")

    unique_upload_directory = resolve_upload_directory(file_path)
    images_dir = os.path.join(unique_upload_directory, IMAGES_DIRECTORY)
    if not os.path.exists(images_dir):
        raise HTTPException(status_code=404, detail="任务目录不存在")

    content = await file.read()
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg"):
        raise HTTPException(status_code=400, detail="仅支持 PNG/JPG 格式")

    dest_path = os.path.join(images_dir, f"slide_{slide_index}.png")
    with open(dest_path, "wb") as f:
        f.write(content)

    # 仅替换图片，不解说来、音频、字幕（内容未变）
    return {
        "message": f"第 {slide_index} 页图片已替换",
        "image_url": f"/files/{file_path}/images/slide_{slide_index}.png",
    }


def handle_async_task(task: dict):
    """后台工作线程：处理异步任务"""
    from utils.task_queue import get_queue
    queue = get_queue()
    params = json.loads(task["params"])
    task_id = task["id"]

    try:
        file_path = params.get("file_path", "")
        unique_upload_directory = resolve_upload_directory(file_path)
        source_pptx_path = get_source_pptx_path(unique_upload_directory)
        unique_images_directory = os.path.join(unique_upload_directory, IMAGES_DIRECTORY)

        understanding_level = params.get("understanding_level", "text-understanding")
        use_vlm_extraction = params.get("use_vlm_extraction", True)
        use_enhanced_narration = params.get("use_enhanced_narration", True)

        context_manager = PPTContextManager(file_path, UPLOAD_DIRECTORY)
        context_manager.context["slide_texts"] = {}
        context_manager.context["generated_scripts"] = {}
        context_manager.context["ppt_full_content"] = ""
        context_manager._save_context()

        queue.update_task(task_id, status="processing", progress=5, message="正在提取 PPT 文字...")
        slide_source_texts = extract_all_slide_texts_from_pptx(
            source_pptx_path, unique_images_directory, use_vlm=use_vlm_extraction
        )
        slide_source_texts = clean_slide_texts(slide_source_texts)
        for idx, text in enumerate(slide_source_texts, start=1):
            if text:
                context_manager.set_slide_text(idx, text)

        total = len(slide_source_texts)

        parsed_scripts = []
        scripts_dir = os.path.join(unique_upload_directory, SCRIPTS_DIRECTORY)
        os.makedirs(scripts_dir, exist_ok=True)

        for slide_index in range(1, total + 1):
            pct = 5 + int(85 * slide_index / total)
            queue.update_task(task_id, status="processing", progress=pct,
                              message=f"正在生成第 {slide_index}/{total} 页解说词...")

            ppt_text = slide_source_texts[slide_index - 1] if slide_index <= len(slide_source_texts) else ""
            context_info = context_manager.get_context_for_slide(slide_index, window_size=2)
            prev_script = context_manager.get_previous_script(slide_index)
            next_text = context_manager.get_next_text(slide_index)

            if use_enhanced_narration:
                flag, text = generate_contextual_narration(
                    current_text=ppt_text, context_info=context_info,
                    prev_script=prev_script, next_text=next_text,
                    understanding_level=understanding_level,
                    slide_index=slide_index, total_slides=total,
                    skip_quality_check=True,
                )
            else:
                flag, text = False, ""

            if not flag:
                raise ValueError(f"第{slide_index}页生成失败: {text}")

            context_manager.set_generated_script(slide_index, text)
            parsed_scripts.append({"slide_index": slide_index, "text": text})

            # 逐页保存：生成立即写入磁盘，同时更新 result 供前端实时呈现
            md_filepath = os.path.join(scripts_dir, f"slide_{slide_index}.md")
            save_sentences_to_markdown(text, scripts_dir, slide_index)
            with open(md_filepath, "w", encoding="utf-8") as f:
                f.write(text)

            # 实时暴露部分结果
            queue.update_task(
                task_id, status="processing", progress=pct,
                message=f"正在生成第 {slide_index}/{total} 页解说词...",
                result=json.dumps(parsed_scripts, ensure_ascii=False),
            )

        queue.update_task(task_id, status="completed", progress=100,
                          message=f"全部 {total} 页生成完成",
                          result=json.dumps(parsed_scripts, ensure_ascii=False))

    except Exception as e:
        queue.update_task(task_id, status="failed", error=str(e),
                          message=f"处理失败: {str(e)[:100]}")
        traceback.print_exc()
