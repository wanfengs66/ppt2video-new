"""
使用视觉大模型（VLM）从 PPT 图片中提取文字
替代 python-pptx 的文本提取方案
"""
import os
import base64
from typing import List, Tuple
from functools import lru_cache

from openai import OpenAI

from config import settings


def get_vlm_client() -> OpenAI:
    """获取硅基流动 API 客户端"""
    from utils.api_keys import get_next_key
    return OpenAI(
        api_key=get_next_key(),
        base_url=settings.SILICONFLOW_BASE_URL,
    )


def encode_image_to_base64(image_path: str) -> str:
    """将图片编码为 base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def clean_extracted_text(text: str) -> str:
    """
    清理提取的文字，移除无关信息

    Args:
        text: 原始提取的文字

    Returns:
        清理后的文字
    """
    import re

    # 0. 移除 VLM 误识别的杂散 D/d 字符（中文字符之间的孤立 D）
    text = re.sub(r"(?<=[^\x00-\x7F])\s*[dD]\s*(?=[^\x00-\x7F])", "", text)
    text = re.sub(r'[dD]{2,}', '', text)

    # 要过滤的无关信息（可通过 .env VLM_FILTER_PATTERNS 自定义）
    filter_patterns = settings.VLM_FILTER_PATTERNS if settings.VLM_FILTER_PATTERNS else [
        r'版权所有',
        r'Copyright',
        r'©',
        r'保密',
        r'内部资料',
        r'机密',
        r'第\s*\d+\s*页',
        r'Page\s*\d+',
        r'\d+\s*/\s*\d+',  # 页码格式 1/10
    ]

    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        line = line.strip()

        # 跳过空行
        if not line:
            continue

        # 检查是否包含要过滤的内容
        should_filter = False
        for pattern in filter_patterns:
            if re.search(pattern, line, re.IGNORECASE):
                should_filter = True
                break

        if not should_filter:
            cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def extract_text_with_vlm(image_path: str) -> Tuple[bool, str]:
    """
    使用 VLM 模型从图片中提取文字（带自动重试）

    Args:
        image_path: PPT 页面图片路径

    Returns:
        (success, text): 成功标志和提取的文字
    """
    import time

    if not os.path.exists(image_path):
        return False, f"Image not found: {image_path}"

    base64_image = encode_image_to_base64(image_path)

    system_prompt = (
        "你是一个专业的 PPT 文字提取助手。请仔细识别图片中的所有文字内容。\n"
        "要求：\n"
        "1. 按照从上到下、从左到右的顺序提取文字\n"
        "2. 保留标题、正文、列表、表格等所有文字\n"
        "3. 保持原有的层级结构和换行\n"
        "4. 不要添加任何解释或描述，只输出文字内容\n"
        "5. 如果有表格，用空格或制表符对齐\n"
        "6. 忽略以下内容：\n"
        "   - 页码\n"
        "   - 公司名称、Logo 文字\n"
        "   - 页眉页脚\n"
        "7. 只提取与课程内容相关的核心文字"
        "8. 图中的特殊符号也需要识别，例如℃、±等\n"
    )

    user_prompt = "请提取这张 PPT 页面中的所有文字内容："

    # 带重试的 API 调用（应对限流 429）
    max_retries = 3
    for attempt in range(max_retries):
        try:
            client = get_vlm_client()
            response = client.chat.completions.create(
                model=settings.VLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=2000,
                temperature=0.1,
            )

            extracted_text = response.choices[0].message.content.strip()
            cleaned_text = clean_extracted_text(extracted_text)
            return True, cleaned_text

        except Exception as e:
            err_msg = str(e)
            # 限流则等待后重试
            if "429" in err_msg or "rate limit" in err_msg.lower() or "tpm limit" in err_msg.lower():
                wait = 10 * (attempt + 1)
                print(f"[VLM] Rate limited, retrying in {wait}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(wait)
            else:
                if attempt < max_retries - 1:
                    print(f"[VLM] API error, retrying... ({err_msg[:60]})")
                    time.sleep(3)
                else:
                    return False, f"VLM extraction failed: {err_msg}"

    return False, "VLM extraction failed: max retries exceeded"


def extract_slide_texts_with_vlm(images_directory: str) -> List[str]:
    """
    批量提取多个 PPT 页面的文字（并发版本）

    Args:
        images_directory: PPT 图片目录（包含 slide_1.png, slide_2.png...）

    Returns:
        List[str]: 每页的文字内容列表
    """
    import re
    import natsort
    from concurrent.futures import ThreadPoolExecutor, as_completed

    if not os.path.exists(images_directory):
        return []

    # 获取所有 slide_*.png 文件
    pattern = r"^slide_(\d+)\.png$"
    image_files = [
        f for f in os.listdir(images_directory)
        if re.match(pattern, f)
    ]

    # 按页码排序
    image_files = natsort.natsorted(
        image_files,
        key=lambda f: int(re.match(pattern, f).group(1))
    )

    # 并发提取（通过 VLM_CONCURRENCY 配置控制，默认 1）
    slide_texts = [""] * len(image_files)
    with ThreadPoolExecutor(max_workers=settings.VLM_CONCURRENCY) as executor:
        future_to_idx = {
            executor.submit(extract_text_with_vlm, os.path.join(images_directory, img)): idx
            for idx, img in enumerate(image_files)
        }

        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            image_file = image_files[idx]
            try:
                success, text = future.result()
                if success:
                    slide_texts[idx] = text
                    print(f"[OK] Extracted text from {image_file}: {len(text)} chars")
                else:
                    print(f"[FAIL] Failed to extract from {image_file}: {text}")
            except Exception as e:
                print(f"[FAIL] Exception extracting {image_file}: {e}")

    return slide_texts


def get_slide_text_with_vlm(image_path: str) -> str:
    """
    提取单个 PPT 页面的文字

    Args:
        image_path: PPT 页面图片路径

    Returns:
        str: 提取的文字内容
    """
    success, text = extract_text_with_vlm(image_path)
    return text if success else ""


# 缓存 VLM 提取结果，避免重复调用
@lru_cache(maxsize=100)
def get_slide_text_with_vlm_cached(image_path: str) -> str:
    """带缓存的 VLM 文字提取"""
    return get_slide_text_with_vlm(image_path)
