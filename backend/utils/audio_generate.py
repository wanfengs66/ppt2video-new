import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from config import settings

SENTENCE_GAP_SECONDS = 0.3

# TTS 并发控制（避免 API 限流）
from threading import BoundedSemaphore
_tts_semaphore = BoundedSemaphore(3)

# TTS API 单次最大输入字数（CosyVoice2 约 100 字限制，留余量用 80）
MAX_TTS_CHARS = 80

# 中文朗读速度估算（字/秒），用于检测截断
CHARS_PER_SECOND = 5.0

def _resolve_voice(voice_type: str) -> str:
    """
    将前端传来的音色标识解析为 API 需要的完整格式。
    API 要求: "FunAudioLLM/CosyVoice2-0.5B:speaker_name"
    输入示例：
      - "FunAudioLLM/CosyVoice2-0.5B:anna" → 直接透传（已是完整格式）
      - "male" → "FunAudioLLM/CosyVoice2-0.5B:alex"
      - "female" → "FunAudioLLM/CosyVoice2-0.5B:anna"
      - "speech:custom-xxx:yyy" → 直接透传（克隆音色）
    """
    if not voice_type:
        return "FunAudioLLM/CosyVoice2-0.5B:alex"
    v = str(voice_type).strip()
    # 已是完整音色 ID 或克隆音色 → 直接使用
    if "/" in v or v.startswith("speech:"):
        return v
    # 简写映射
    mapping = {
        "male": "FunAudioLLM/CosyVoice2-0.5B:alex",
        "female": "FunAudioLLM/CosyVoice2-0.5B:anna",
    }
    return mapping.get(v.lower(), "FunAudioLLM/CosyVoice2-0.5B:alex")


def _split_text_for_tts(text: str) -> list:
    """
    将文本拆分为适合 TTS API 的片段，确保每段不超过 MAX_TTS_CHARS。
    拆分策略（由宽松到强制）：
    1. 在句末标点（。！？）处拆分
    2. 仍超长的在句中标点（，, ；; 、）处拆分
    3. 仍超长的按 MAX_TTS_CHARS 强制切断
    """
    if len(text) <= MAX_TTS_CHARS:
        return [text]

    # 第一轮：句末标点拆分
    parts = re.split(r'(?<=[。！？])', text)
    chunks = _merge_parts(parts, MAX_TTS_CHARS)

    # 第二轮：对仍超长的片段在句中标点处拆分
    result = []
    for chunk in chunks:
        if len(chunk) <= MAX_TTS_CHARS:
            result.append(chunk)
        else:
            sub_parts = re.split(r'(?<=[，,；;、])', chunk)
            sub_chunks = _merge_parts(sub_parts, MAX_TTS_CHARS)
            # 第三轮：仍超长则强制按固定长度切
            for sc in sub_chunks:
                if len(sc) <= MAX_TTS_CHARS:
                    result.append(sc)
                else:
                    for i in range(0, len(sc), MAX_TTS_CHARS):
                        result.append(sc[i:i + MAX_TTS_CHARS])
    return result


def _merge_parts(parts: list, max_len: int) -> list:
    """将 parts 按 max_len 上限合并，贪心策略"""
    chunks = []
    buf = ""
    for part in parts:
        if not part.strip():
            continue
        if len(buf) + len(part) <= max_len:
            buf += part
        else:
            if buf:
                chunks.append(buf)
            buf = part
    if buf:
        chunks.append(buf)
    return chunks if chunks else parts


def _estimate_speech_duration(text: str) -> float:
    """估算中文文本的朗读时长（秒），用于截断检测"""
    # 只统计中文字符和英文单词
    chinese_chars = len(re.findall(r'[一-鿿]', text))
    other_chars = len(re.findall(r'[a-zA-Z0-9]', text))
    return (chinese_chars + other_chars * 0.5) / CHARS_PER_SECOND


def format_time(seconds):
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    milliseconds = int((seconds - int(seconds)) * 1000)
    seconds = int(seconds)
    return f"{int(hours):02d}:{int(minutes):02d}:{int(seconds):02d},{milliseconds:03d}"


def get_audio_duration(file_path):
    from moviepy.audio.io.AudioFileClip import AudioFileClip
    audio = AudioFileClip(file_path)
    try:
        return audio.duration
    finally:
        audio.close()


def create_srt_line(index, start_time, end_time, text):
    return f"{index}\n{start_time} --> {end_time}\n{text}\n\n"


def read_text_file(file_path):
    for encoding in ["utf-8", "gbk", "gb2312", "utf-16"]:
        try:
            with open(file_path, "r", encoding=encoding) as file_handle:
                return file_handle.read().strip()
        except (UnicodeDecodeError, UnicodeError):
            continue

    raise ValueError(f"Failed to decode {file_path}")


def synthesize_text_to_mp3(text, output_path, voice, reference_audio=None, prompt_text=None):
    """
    合成语音（支持本地模型和 API）

    Args:
        text: 要合成的文字
        output_path: 输出音频路径
        voice: 音色（API 模式）或音色类型（本地模式）
    """
    tts_mode = settings.TTS_MODE

    if tts_mode == "local":
        # 使用本地 CosyVoice 模型
        try:
            from utils.local_tts import synthesize_text_to_mp3_local
            voice_type = "female" if "bella" in voice else "male"
            synthesize_text_to_mp3_local(text, output_path, voice_type)
        except ImportError as e:
            print(f"本地 TTS 模块加载失败: {e}")
            raise
    elif tts_mode == "chattts":
        # 使用本地 ChatTTS 模型
        try:
            from utils.chattts_tts import synthesize_text_to_mp3_chattts
            voice_type = "female" if "bella" in voice else "male"
            synthesize_text_to_mp3_chattts(text, output_path, voice_type)
        except ImportError as e:
            print(f"ChatTTS 模块加载失败: {e}")
            raise
    else:
        # 使用硅基流动 API（有输入长度限制，须分段合成）
        from utils.api_keys import get_next_key
        api_key = get_next_key()
        if not api_key:
            raise ValueError("SILICONFLOW_API_KEY must be set in the environment variables.")

        # 将文本拆分为 API 安全长度的片段
        chunks = _split_text_for_tts(text)

        from moviepy.audio.io.AudioFileClip import AudioFileClip
        from moviepy import AudioClip, concatenate_audioclips

        audio_clips = []
        try:
            for i, chunk in enumerate(chunks):
                with _tts_semaphore:
                    for t_attempt in range(3):
                        try:
                            resp = requests.post(
                                f"{settings.SILICONFLOW_BASE_URL}/audio/speech",
                                json={"model": settings.TTS_MODEL, "input": chunk,
                                  "voice": voice, "response_format": "mp3", "seed": 42},
                            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                            timeout=60,
                        )
                            resp.raise_for_status()
                            break
                        except Exception as e:
                            if t_attempt < 2 and ('429' in str(e) or 'timeout' in str(e).lower()):
                                print(f"[TTS] Retry {t_attempt+1}/3 for chunk {i}: {str(e)[:60]}")
                                time.sleep(3 * (t_attempt + 1))
                            else:
                                raise

                tmp_path = output_path.replace(".mp3", f"_part{i}.mp3")
                with open(tmp_path, "wb") as f:
                    f.write(resp.content)

                # 校验：检测 API 是否截断了音频
                clip = AudioFileClip(tmp_path)
                expected_dur = _estimate_speech_duration(chunk)
                actual_dur = clip.duration
                if actual_dur < expected_dur * 0.4 and len(chunk) > 20:
                    print(f"[TTS] WARNING: chunk {i} audio seems truncated! "
                          f"text_len={len(chunk)}, expected~{expected_dur:.1f}s, actual={actual_dur:.1f}s")

                if len(audio_clips) > 0:
                    gap = AudioClip(lambda t: 0, duration=0.15)
                    audio_clips.append(gap)
                audio_clips.append(clip)

            # 合并所有片段
            if len(audio_clips) == 1:
                # 只有一个片段，直接使用（但已经是通过 tmp 文件加载的 clip，需写出）
                audio_clips[0].write_audiofile(output_path, logger=None)
            else:
                final = concatenate_audioclips(audio_clips)
                final.write_audiofile(output_path, logger=None)
                final.close()

            # 清理资源
            for clip in audio_clips:
                clip.close()
            for i in range(len(chunks)):
                tmp = output_path.replace(".mp3", f"_part{i}.mp3")
                if os.path.exists(tmp):
                    os.remove(tmp)

        except Exception as e:
            print(f"TTS failed: {e}")
            raise

    print(f"Synthesized text to file: {output_path}")


def get_sentence_audio_paths(paragraph_dir):
    sentence_mp3s = [
        entry.path
        for entry in os.scandir(paragraph_dir)
        if entry.is_file() and re.match(r"sentence_(\d+)\.mp3$", entry.name)
    ]
    return sorted(
        sentence_mp3s,
        key=lambda path: int(re.search(r"sentence_(\d+)\.mp3", os.path.basename(path)).group(1)),
    )


def build_slide_audio_from_sentences(base_directory):
    paragraph_dirs = [
        entry.path
        for entry in os.scandir(base_directory)
        if entry.is_dir() and entry.name.startswith("paragraph_")
    ]
    paragraph_dirs = sorted(
        paragraph_dirs,
        key=lambda path: int(re.search(r"paragraph_(\d+)", os.path.basename(path)).group(1)),
    )

    for paragraph_dir in paragraph_dirs:
        slide_number = re.search(r"paragraph_(\d+)", os.path.basename(paragraph_dir)).group(1)
        sentence_mp3s = get_sentence_audio_paths(paragraph_dir)
        if not sentence_mp3s:
            continue

        clips = []
        slide_audio = None
        try:
            from moviepy import AudioClip, concatenate_audioclips
            from moviepy.audio.io.AudioFileClip import AudioFileClip
            from moviepy.audio.fx.MultiplyVolume import MultiplyVolume
            for index, sentence_mp3 in enumerate(sentence_mp3s):
                if index > 0:
                    clips.append(AudioClip(lambda t: 0, duration=SENTENCE_GAP_SECONDS))
                clips.append(AudioFileClip(sentence_mp3))

            slide_audio = concatenate_audioclips(clips)
            # 首尾加微弱淡入淡出，消除拼接边界的咔嗒声/杂音
            if slide_audio.duration > 0.15:
                from moviepy.audio.fx.AudioFadeIn import AudioFadeIn
                from moviepy.audio.fx.AudioFadeOut import AudioFadeOut
                slide_audio = slide_audio.with_effects([
                    AudioFadeIn(0.02),
                    AudioFadeOut(0.05),
                ])
            output_path = os.path.join(base_directory, f"slide_{slide_number}.mp3")
            slide_audio.write_audiofile(output_path, logger=None)
            print(f"Built slide audio: {output_path}")
        finally:
            if slide_audio is not None:
                slide_audio.close()
            for clip in clips:
                try:
                    clip.close()
                except Exception:
                    pass


def calculate_audio_durations(directory):
    durations = []
    pattern = r"^slide_(\d+)\.mp3$"
    audio_files = [
        entry.path
        for entry in os.scandir(directory)
        if entry.name.endswith(".mp3") and re.match(pattern, entry.name)
    ]
    audio_files = sorted(
        audio_files,
        key=lambda path: int(re.match(pattern, os.path.basename(path)).group(1)),
    )

    for file_path in audio_files:
        duration_seconds = get_audio_duration(file_path)
        durations.append(duration_seconds)
        print(f"文件名: {os.path.basename(file_path)}, 持续时间: {duration_seconds} 秒")

    return durations


def generate_srt_from_audio(base_dir: str, output_dir: str, slide_index: int = None) -> None:
    os.makedirs(output_dir, exist_ok=True)

    paragraph_dirs = [
        entry.path
        for entry in os.scandir(base_dir)
        if entry.is_dir() and entry.name.startswith("paragraph_")
    ]
    paragraph_dirs = sorted(
        paragraph_dirs,
        key=lambda path: int(re.search(r"paragraph_(\d+)", os.path.basename(path)).group(1)),
    )

    # 支持单页生成：过滤到指定页码
    if slide_index is not None:
        paragraph_dirs = [
            d for d in paragraph_dirs
            if int(re.search(r"paragraph_(\d+)", os.path.basename(d)).group(1)) == slide_index
        ]

    for paragraph_dir in paragraph_dirs:
        slide_number = re.search(r"paragraph_(\d+)", os.path.basename(paragraph_dir)).group(1)
        output_srt_file = os.path.join(output_dir, f"slide_{slide_number}.srt")

        sentence_mds = [
            entry.path
            for entry in os.scandir(paragraph_dir)
            if entry.is_file() and entry.name.endswith(".md") and entry.name.startswith("sentence_")
        ]
        sentence_mds = sorted(
            sentence_mds,
            key=lambda path: int(re.search(r"sentence_(\d+)\.md", os.path.basename(path)).group(1)),
        )

        current_time = 0.0
        srt_index = 1
        with open(output_srt_file, "w", encoding="utf-8") as srt_file:
            for sentence_md in sentence_mds:
                sentence_mp3 = os.path.splitext(sentence_md)[0] + ".mp3"
                if not os.path.exists(sentence_mp3):
                    print(f"No corresponding MP3 file found for {sentence_md}")
                    continue

                text = read_text_file(sentence_md)
                if not text:
                    continue

                duration = get_audio_duration(sentence_mp3)
                start_time_str = format_time(current_time)
                end_time_str = format_time(current_time + duration)
                srt_file.write(create_srt_line(srt_index, start_time_str, end_time_str, text))

                current_time += duration + SENTENCE_GAP_SECONDS
                srt_index += 1

        print(f"SRT file generated successfully: {output_srt_file}")


def synthesize_md_to_speech(base_directory, voice=None, voice_type=None, reference_audio=None, prompt_text=None, slide_index=None):
    """
    批量合成 MD 文件为语音。

    Args:
        base_directory: 脚本目录（含 paragraph_N/sentence_N.md）
        voice: 完整音色 ID，支持：
               - 系统音色：FunAudioLLM/CosyVoice2-0.5B:alex / anna / bella ...
               - 克隆音色：speech:your-voice-name:xxx:xxx
        voice_type: 兼容参数：
               - 完整音色 ID（含 / 或 :）→ 直接作为 voice 使用
               - 'male' → alex, 'female' → anna
        slide_index: 可选，仅合成指定页码的音频（1-based）
    """
    # 解析音色：统一为 API 需要的完整格式
    if voice is None:
        voice = _resolve_voice(voice_type)
    else:
        voice = _resolve_voice(voice)

    paragraph_dirs = [
        entry.path
        for entry in os.scandir(base_directory)
        if entry.is_dir() and entry.name.startswith("paragraph_")
    ]
    paragraph_dirs = sorted(
        paragraph_dirs,
        key=lambda path: int(re.search(r"paragraph_(\d+)", os.path.basename(path)).group(1)),
    )

    # 支持单页合成：过滤到指定页码
    if slide_index is not None:
        paragraph_dirs = [
            d for d in paragraph_dirs
            if int(re.search(r"paragraph_(\d+)", os.path.basename(d)).group(1)) == slide_index
        ]
        if not paragraph_dirs:
            print(f"[TTS] No paragraph dir found for slide {slide_index}, skipping")

    # 收集所有需要合成的任务
    tasks = []
    for paragraph_dir in paragraph_dirs:
        sentence_mds = [
            entry.path
            for entry in os.scandir(paragraph_dir)
            if entry.is_file() and entry.name.endswith(".md") and entry.name.startswith("sentence_")
        ]
        sentence_mds = sorted(
            sentence_mds,
            key=lambda path: int(re.search(r"sentence_(\d+)\.md", os.path.basename(path)).group(1)),
        )

        for md_file_path in sentence_mds:
            try:
                text = read_text_file(md_file_path)
            except ValueError:
                print(f"Failed to decode {md_file_path}, skipping")
                continue

            if not text:
                continue

            mp3_file_path = os.path.splitext(md_file_path)[0] + ".mp3"
            tasks.append((text, mp3_file_path, voice, reference_audio, prompt_text))

    # 并发合成
    failed_tasks = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(synthesize_text_to_mp3, text, path, v, ref, pt): path for text, path, v, ref, pt in tasks}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception as exc:
                path = futures[future]
                print(f"Error synthesizing {path}: {exc}")
                failed_tasks.append(path)

    # 单线程重试失败任务
    if failed_tasks:
        print(f"[TTS] Retrying {len(failed_tasks)} failed tasks...")
        for text, mp3_path, voice, ref_audio, prompt_txt in [t for t in tasks if t[1] in failed_tasks]:
            for attempt in range(3):
                try:
                    synthesize_text_to_mp3(text, mp3_path, voice, ref_audio, prompt_txt)
                    print(f"[TTS] Retry OK: {mp3_path}")
                    break
                except Exception as e:
                    if attempt < 2:
                        print(f"[TTS] Retry {attempt+1}/3 failed: {str(e)[:50]}")
                        time.sleep(3)
                    else:
                        print(f"[TTS] Retry exhausted: {mp3_path}: {e}")

    build_slide_audio_from_sentences(base_directory)
