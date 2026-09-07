"""
增强版解说词生成：解决上下文连贯性和内容贴合度问题
"""
import re
import time
from typing import Tuple
from openai import OpenAI

from config import settings


def get_client() -> OpenAI:
    from utils.api_keys import get_next_key
    return OpenAI(
        api_key=get_next_key(),
        base_url=settings.SILICONFLOW_BASE_URL,
    )


def generate_contextual_narration(
    current_text: str,
    context_info: str = "",
    prev_script: str = "",
    next_text: str = "",
    understanding_level: str = "text-understanding",
    slide_index: int = 1,
    total_slides: int = 1,
    skip_quality_check: bool = False,
) -> Tuple[bool, str]:
    if not current_text:
        return False, "当前页没有提取到文字内容"

    max_attempts = 3
    last_error = ""
    for attempt in range(max_attempts):
        try:
            client = get_client()

            is_first_page = slide_index == 1
            is_last_page = slide_index == total_slides
            is_middle_page = not is_first_page and not is_last_page

            system_prompt = build_system_prompt(
                is_first_page, is_last_page, is_middle_page, understanding_level
            )

            user_prompt = build_user_prompt(
                current_text, context_info, prev_script, next_text,
                is_first_page, is_last_page, slide_index, total_slides
            )

            response = client.chat.completions.create(
                model=settings.TEXT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=600,
                temperature=0.5,
                top_p=0.8,
                frequency_penalty=0.7,
                presence_penalty=0.5,
            )

            narration = response.choices[0].message.content.strip()
            narration = clean_narration(narration)

            if not skip_quality_check:
                narration = validate_and_fix_narration(
                    narration, client,
                    slide_index=slide_index,
                    current_text=current_text,
                    prev_script=prev_script
                )

            return True, narration

        except Exception as e:
            last_error = str(e)
            is_rate_limit = ('429' in last_error or 'rate limit' in last_error.lower()
                            or 'tpm limit' in last_error.lower())
            if is_rate_limit and attempt < max_attempts - 1:
                wait = 5 * (attempt + 1)
                print(f"[Narration] Rate limited, retry {attempt+1}/{max_attempts} after {wait}s")
                time.sleep(wait)
                continue
            break

    return False, f"生成解说词失败: {last_error[:200]}"


def build_system_prompt(
    is_first_page: bool,
    is_last_page: bool,
    is_middle_page: bool,
    understanding_level: str
) -> str:
    base_prompt = """你是一位专业的 PPT 讲解员，正在为培训课程录制解说词。每页只讲当前页的核心内容。所有输出必须使用简体中文。

核心要求：
1. **长度控制（重要）**：解说词精炼但不遗漏要点
   - 内容简单（<20字原文）：30-50 字解说词
   - 内容适中（20-60字原文）：50-100 字解说词
   - 内容丰富（60-120字原文）：100-180 字解说词
   - 内容很多（>120字原文）：150-250 字解说词，用2-4句话覆盖主要知识点
   - **解说词不能超过原文长度的 80%**
2. **覆盖要点**：原文中列出了多个要点（如清单、分条内容）时，每个要点都要简要提及，不能只讲第一条
3. **只讲当前页（最重要的规则）**：解说词必须严格基于【当前页内容】中的文字，只讲解当前页上的内容。绝不能讲其他页的内容
4. **上下文感知**：系统会提供前后页的解说词参考，帮助你与上一页自然衔接、避免重复已讲内容
5. **禁用词汇**：严禁使用以下词汇：
   - 过渡词："接下来"、"下面"、"然后"、"现在"、"那么"
   - 序号词："首先"、"其次"、"最后"、"第一"、"第二"
   - 套话："让我们"、"我们来"、"下面我们"、"接下来我们将"、"通过以上步骤"
6. **完整收尾**：每句话必须说完，不要半句结束
7. **术语一致**：使用统一的专业术语
8. **避免重复**：不要重复前面页面已经讲过的内容
9. **相邻页相似结构处理**：PPT 中常有连续多页结构相似但讲不同零件的情况（如侧板、光导、密封垫各有自己的规格参数）。即使结构相似，每页内容是独立的，必须各自覆盖当前页的全部要点。只需在措辞上避免与上一页完全相同的句式，而非删除内容。

✅ 好的解说词示例（内容丰富型，约120字）：
"支架在灯具中起安装、定位和强度保证作用，外观需注意浇口位置、分型线和皮纹处理。灯罩材料通常选用PC或PMMA，需管控透光率和雾度值，表面不得有划伤、气泡等缺陷。力学性能方面要满足振动和冲击测试要求，环境试验需通过高低温循环和盐雾测试验证。"

"""

    if is_first_page:
        base_prompt += """
【首页要求】
- 直接点题，说明主题和内容
- 例如："本课程讲解汽车灯具零件设计，包括零件分类、图纸识别和设计要点"
"""
    elif is_last_page:
        base_prompt += """
【末页要求】
- 简短总结核心内容
- 例如："掌握这些设计要点，就能完成零件的规范设计"
"""
    elif is_middle_page:
        base_prompt += """
【中间页要求】
- 直接讲解当前页内容，不要任何过渡词
- 与前一页内容自然衔接，但不要明确提及"前面"或"上一页"
- 例如："灯罩材料通常选用PC或PMMA，具有良好的透光性"
"""

    return base_prompt


def build_user_prompt(
    current_text: str,
    context_info: str,
    prev_script: str,
    next_text: str,
    is_first_page: bool,
    is_last_page: bool,
    slide_index: int,
    total_slides: int
) -> str:
    prompt_parts = []

    prompt_parts.append(
        f"【当前页内容（第{slide_index}/{total_slides}页）——这是你需要讲解的唯一内容】\n{current_text}\n"
        f"⚠️ 只基于以上文字生成解说词。如果以上文字中没有提到的内容（包括术语、概念、知识点），绝对不能讲。\n"
    )

    if context_info:
        prompt_parts.append(f"{context_info}\n")

    if prev_script and not is_first_page:
        prompt_parts.append(
            f"【上一页已讲内容——当前页请勿重复以上内容】\n{prev_script}\n"
            f"↑ 以上是上一页已经详细讲解过的全部内容。如果当前页涉及相同主题，只讲新增或不同的知识点，不要重复。\n"
        )

    if next_text and not is_last_page:
        prompt_parts.append(f"【下一页将讲什么】\n{next_text[:150]}\n")

    content_length = len(current_text.replace('\n', '').replace(' ', '').strip())

    if content_length < 20:
        target_length = "30-50字"
        detail_level = "简要"
    elif content_length < 60:
        target_length = "50-100字"
        detail_level = "适当"
    elif content_length < 120:
        target_length = "100-180字"
        detail_level = "详细覆盖每个要点"
    else:
        target_length = "150-250字"
        detail_level = "全面覆盖，用2-4句话逐一讲解各要点"

    if is_first_page:
        prompt_parts.append(f"请生成开场解说词（{target_length}），{detail_level}。\n如果系统提示了下一页的内容，可以在结尾处做简短预告。")
    elif is_last_page:
        prompt_parts.append(f"请生成总结解说词（{target_length}），{detail_level}。注意与上一页自然衔接，不要重复已讲内容。")
    else:
        prompt_parts.append(f"请生成解说词（{target_length}），{detail_level}，不要过渡词。\n原文中列出的每个要点都要覆盖到。与上一页自然衔接，措辞上避免完全相同的句式即可。")

    return "\n".join(prompt_parts)


def clean_narration(text: str) -> str:
    # 繁简转换
    text = _to_simplified(text)
    text = re.sub(r"(?<=[^\x00-\x7F])\s*[dD]\s*(?=[^\x00-\x7F])", "", text)
    text = re.sub(r'[dD]{2,}', '', text)

    text = re.sub(r'\s+', ' ', text).strip()

    text = re.sub(r'^\s*\d+[.)、]\s*', '', text)
    text = re.sub(r'^\s*[-*•]\s*', '', text)

    text = text.strip('"\'""''')

    transition_words = ['接下来', '下面', '然后', '现在', '那么', '首先', '其次', '最后', '第一', '第二', '让我们', '我们来']
    for word in transition_words:
        text = re.sub(f'^{word}[，,、]?', '', text)
        text = re.sub(f'^{word}', '', text)

    text = text.replace(',,', '，')
    text = text.replace('。。', '。')
    text = text.replace('  ', ' ')
    text = re.sub(r'[，。！？；：、]{2,}', lambda m: m.group(0)[0], text)
    text = re.sub(r'(?!等等)(.{2})\1+', r'\1', text)
    text = re.sub(r'(.)\1{2,}', r'\1', text)
    text = re.sub(r'(.)\1([一-鿿])\2', r'\1\2', text)
    _VALID_REDUP = re.compile(r'^(等等|往往|刚刚|仅仅|渐渐|常常|纷纷|缓缓|慢慢|好好|轻轻|悄悄|默默|深深|远远)$')
    text = re.sub(r'([一-鿿])\1', lambda m: m.group(1) if not _VALID_REDUP.match(m.group(0)) else m.group(0), text)

    MAX_CHARS = 300
    if len(text) > MAX_CHARS:
        last_end = -1
        for marker in ['。', '！', '？', '.', '!', '?']:
            pos = text.rfind(marker, 0, MAX_CHARS)
            if pos > last_end:
                last_end = pos
        if last_end > MAX_CHARS * 0.3:
            text = text[:last_end + 1]
        else:
            text = text[:MAX_CHARS] + '。'

    if text and text[-1] not in '。！？.!?':
        last_end = -1
        for marker in ['。', '！', '？', '.', '!', '?']:
            pos = text.rfind(marker)
            if pos > last_end:
                last_end = pos
        if last_end > 0:
            text = text[:last_end + 1]
        else:
            text += '。'

    return text.strip()


def validate_and_fix_narration(narration: str, client, slide_index: int = 0, current_text: str = "", prev_script: str = "") -> str:
    has_stray_d = bool(re.search(r'(?<=[^\x00-\x7F])[dD](?=[^\x00-\x7F])', narration))
    has_repetition = bool(re.search(r'(.)\1{2,}', narration)) or bool(re.search(r'(?!等等)(.{2})\1', narration))
    is_too_long = len(narration) > 300

    if not has_stray_d and not has_repetition and not is_too_long:
        return narration

    quality_prompt = f"""你是解说词质检员。检查并修复以下 PPT 解说词的质量问题：

【当前页原文参考】
{current_text[:200] if current_text else "无"}

【上一页解说词参考】
{prev_script[-100:] if prev_script else "无（这是第一页）"}

【待检查的解说词】
{narration}

修复规则（按优先级）：
1. **删除杂散字母**：中文句子中孤立的 D、d 等英文字母直接删除（保留 3D、2D 等数字+字母组合）
2. **修复重复字词**：如"包括包括"、"的的"、"性性"、"能能"、"等等等" → 合并为单次
3. **精简冗余内容**：删除啰嗦的过渡和重复，但保留所有知识要点
4. **提升流畅度**：确保句子通顺自然，与上一页不重复、不突兀衔接
5. **确保完整收尾**：以句号结尾，不要半句结束
6. **保持原意**：不要改变核心技术内容

只输出修复后的解说词，不要任何解释："""

    try:
        response = client.chat.completions.create(
            model=settings.TEXT_MODEL,
            messages=[{"role": "user", "content": quality_prompt}],
            max_tokens=200,
            temperature=0.3,
        )

        fixed = response.choices[0].message.content.strip()
        fixed = fixed.strip('"\'""''')

        fixed = re.sub(r'\\?\((\d+)\^\{?\\circ\}?\\?\)\s*C', r'\1℃', fixed)
        fixed = re.sub(r'(\d+)\s*\\circ\s*C', r'\1℃', fixed)
        fixed = re.sub(r'(\d+)\s*degrees?\s*C', r'\1℃', fixed)
        fixed = re.sub(r'\\pm\s*', '±', fixed)
        fixed = re.sub(r'\\times\s*', '×', fixed)
        fixed = re.sub(r'\\div\s*', '÷', fixed)
        fixed = re.sub(r'\\leq\s*', '≤', fixed)
        fixed = re.sub(r'\\geq\s*', '≥', fixed)
        fixed = re.sub(r'\\approx\s*', '≈', fixed)
        fixed = re.sub(r'\\[({]', '', fixed)
        fixed = re.sub(r'[})]', '', fixed)
        fixed = re.sub(r'\\\w+', '', fixed)
        fixed = re.sub(r'\s+', ' ', fixed).strip()
        fixed = re.sub(r'(?<=[^\x00-\x7F])\s*[dD]\s*(?=[^\x00-\x7F])', '', fixed)

        return fixed if fixed else narration

    except Exception as e:
        return narration


def _to_simplified(text: str) -> str:
    """将文本中的繁体字转为简体（优先 zhconv，回退 opencc，否则原样返回）"""
    try:
        import zhconv
        return zhconv.convert(text, 'zh-cn')
    except ImportError:
        pass
    try:
        import opencc
        cc = opencc.OpenCC('t2s')
        return cc.convert(text)
    except ImportError:
        pass
    return text


def extract_key_terms_from_text(text: str) -> list:
    terms = []
    english_terms = re.findall(r'\b[A-Z][A-Za-z0-9]+\b|\b[A-Z]{2,}\b', text)
    terms.extend(english_terms)
    chinese_patterns = [
        r'[一-鿿]{2,}(?:系统|平台|模型|算法|框架|技术|方法|工具|软件|硬件)',
        r'[一-鿿]{2,}(?:设计|开发|测试|部署|运维|管理)',
        r'[一-鿿]{2,}(?:架构|结构|组件|模块|接口|协议)',
    ]
    for pattern in chinese_patterns:
        chinese_terms = re.findall(pattern, text)
        terms.extend(chinese_terms)
    return list(set(terms))[:15]
