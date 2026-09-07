# utils/movie_editor.py
import asyncio
import math
import os
import re
import subprocess

import imageio_ffmpeg
import natsort

from config import settings


def get_ffmpeg_path():
    # 优先使用配置中指定的路径
    if settings.FFMPEG_PATH and os.path.exists(settings.FFMPEG_PATH):
        return settings.FFMPEG_PATH

    candidates = [
        imageio_ffmpeg.get_ffmpeg_exe(),
        "ffmpeg",
    ]

    for candidate in candidates:
        if not candidate:
            continue
        if candidate == "ffmpeg" or os.path.exists(candidate):
            return candidate

    return "ffmpeg"


FFMPEG_PATH = get_ffmpeg_path()
VIDEO_CODEC = "libx264"


def get_audio_duration(audio_path):
    from moviepy.audio.io.AudioFileClip import AudioFileClip
    audio = AudioFileClip(audio_path)
    try:
        return audio.duration
    finally:
        audio.close()


async def image_to_video(file, duration, fps, base_name, output_video_path):
    """Use FFmpeg directly for image-to-video conversion."""
    output_filename = f"{base_name}.mp4"
    output_path = os.path.join(output_video_path, output_filename)

    def sync_image_to_video():
        command = [
            FFMPEG_PATH,
            "-y",
            "-loop",
            "1",
            "-i",
            file,
            "-t",
            str(duration),
            "-vf",
            "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2:white",
            "-c:v",
            VIDEO_CODEC,
            "-r",
            str(fps),
            "-pix_fmt",
            "yuv420p",
            output_path,
        ]
        subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return output_path

    return await asyncio.to_thread(sync_image_to_video)


def concatenate_videos(video_paths, output_path):
    """Use FFmpeg concat to merge videos with clean timestamps."""
    list_file = output_path + "_list.txt"
    with open(list_file, "w", encoding="utf-8") as file_handle:
        for path in video_paths:
            abs_path = os.path.abspath(path).replace("\\", "/")
            file_handle.write(f"file '{abs_path}'\n")

    command = [
        FFMPEG_PATH,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-fflags",
        "+genpts",          # 重新生成时间戳，消除边界毛刺
        "-i",
        list_file,
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        output_path,
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    os.remove(list_file)


async def merge_audio_video_subtitle(image_video_path, audio_path, srt_path, output_path, target_duration=None):
    subtitle_enabled = srt_path is not None and os.path.exists(srt_path)
    if srt_path is not None and not os.path.exists(srt_path):
        raise FileNotFoundError(f"SRT file not found: {srt_path}")

    audio_duration = get_audio_duration(audio_path)
    # 使用对齐后的目标时长，确保视频帧边界干净
    effective_duration = target_duration if target_duration else audio_duration

    # 音频结尾加微弱淡出（0.05s），消除 TTS 尾部杂音和拼接边界噪点
    afade_st = max(0, effective_duration - 0.05)
    afade_filter = f"afade=t=out:st={afade_st:.3f}:d=0.05"

    command = [
        FFMPEG_PATH,
        "-y",
        "-i",
        image_video_path,
        "-i",
        audio_path,
        "-map",
        "0:v",
        "-map",
        "1:a",
        "-t",
        str(effective_duration),
        "-c:v",
        VIDEO_CODEC,
        "-c:a",
        "aac",
        "-pix_fmt",
        "yuv420p",
    ]

    # 字幕：仅当启用且文件存在时添加
    if subtitle_enabled:
        srt_abs_path = os.path.abspath(srt_path).replace("\\", "/").replace(":", "\\:")
        subtitle_style = (
            "FontName=Arial,FontSize=20,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,Outline=2,Shadow=1,Alignment=2,"
            "MarginV=30,WrapStyle=0,PlayResX=1280,PlayResY=720"
        )
        command += ["-vf", f"subtitles='{srt_abs_path}':force_style='{subtitle_style}'"]

    command += ["-af", afade_filter, output_path]

    def run_command():
        return subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    try:
        await asyncio.to_thread(run_command)
    except subprocess.CalledProcessError as exc:
        print(f"FFmpeg error: {exc.stderr.decode('utf-8', errors='replace')}")
        raise


def images_to_video_with_durations(input_image_path, output_video_path, durations, fps, base_name):
    pattern = r"^" + re.escape(base_name) + r"_(\d+)\.png$"
    image_files = [
        f"{input_image_path}/{file}"
        for file in os.listdir(input_image_path)
        if re.match(pattern, file)
    ]
    image_files = natsort.natsorted(
        image_files,
        key=lambda path: int(re.match(pattern, os.path.basename(path)).group(1)),
    )

    target_width, target_height = 1280, 720
    background_size = (target_width, target_height)

    import numpy as np
    from PIL import Image
    from moviepy import ColorClip, CompositeVideoClip, ImageClip, concatenate_videoclips

    clips = []
    for index, file in enumerate(image_files):
        img = Image.open(file)
        width, height = img.size
        ratio = width / height
        if width > target_width or height > target_height:
            if ratio > target_width / target_height:
                new_width = target_width
                new_height = math.floor(new_width / ratio)
            else:
                new_height = target_height
                new_width = math.floor(new_height * ratio)
        else:
            new_width, new_height = width, height

        img = img.resize((new_width, new_height), resample=Image.Resampling.LANCZOS)
        img_clip = ImageClip(np.array(img)).with_duration(durations[index])
        img_clip = img_clip.with_position("center")

        bg_clip = ColorClip(size=background_size, color=(255, 255, 255), duration=durations[index])
        composite_clip = CompositeVideoClip([bg_clip, img_clip])
        clips.append(composite_clip)

    final_clip = concatenate_videoclips(clips, method="compose")
    output_filename = f"{base_name}.mp4"
    final_clip.write_videofile(os.path.join(output_video_path, output_filename), fps=fps)
