import os
import re

from openai import OpenAI

from config import settings

MAX_SCRIPT_CHARS = 100  # 减少字数限制，适应简洁解说


def get_client() -> OpenAI:
    from utils.api_keys import get_next_key
    return OpenAI(
        api_key=get_next_key(),
        base_url=settings.SILICONFLOW_BASE_URL,
    )


def generate_short_narration(extracted_text: str, understanding_level: str) -> str:
    client = get_client()

    # 根据原文长度动态调整目标长度（缩短版本）
    source_length = len(extracted_text)
    if source_length > 200:
        target_length = "60到90个汉字"
        max_tokens = 150
    elif source_length > 100:
        target_length = "40到60个汉字"
        max_tokens = 100
    else:
        target_length = "30到50个汉字"
        max_tokens = 80

    system_prompt = (
        "你是一位专业的PPT讲解员，正在为技术培训课程录制解说词。\n"
        "要求：\n"
        "1. 用简洁精炼的口语化风格讲解，突出核心要点\n"
        f"2. 解说词长度严格控制在{target_length}，宁可少说也不要啰嗦\n"
        "3. 只保留最关键的信息：核心术语、关键步骤、重要数字\n"
        "4. 对于多个要点，只提及最重要的2-3个，其他可以概括\n"
        "5. 少用过渡词，直接说重点\n"
        "6. 专业术语必须保留，但解释要简短\n"
        "7. **严格避免重复**：不要重复使用相同的词语\n"
        "8. **标点规范**：正确使用中文标点符号\n"
        "9. **数字处理**：原文中的数字序号请转换为'首先'、'其次'、'最后'等，但要精简\n"
        "10. **输出纯净文本**：不要输出任何特殊符号、序号标记\n"
        "11. **极简原则**：能用一句话说清楚的，绝不用两句话"
        "12. 如果原文中有表格内容，请用空格或制表符对齐输出，但不要过度描述表格细节\n"
        "13. 完整输出句子，不要突然中断，确保每句话都表达完整的意思\n"
        "14. **自我检查**：生成后检查一下句子通顺度和信息完整性，确保没有遗漏重要信息或出现重复问题\n"
        "15. 请准确输出原文中的特殊符号例如℃、±等，不要替换成其他字符\n"
    )

    if understanding_level == "deep-understanding":
        system_prompt += "11. 可以适当补充说明，帮助学员理解概念之间的联系\n"
    else:
        system_prompt += "11. 忠实于原文内容，不要过度发挥\n"

    response = client.chat.completions.create(
        model=settings.TEXT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": extracted_text},
        ],
        max_tokens=max_tokens,
        temperature=0.7,
        top_p=0.9,
        frequency_penalty=0.3,
        presence_penalty=0.3,
    )
    return final_quality_check(response.choices[0].message.content.strip())


def text_improve(text: str) -> str:
    text = clean_generated_text(text)
    if len(text) <= MAX_SCRIPT_CHARS:
        return final_quality_check(text)

    # 如果超出限制，进行适度精简
    client = get_client()
    max_tokens = min(int(MAX_SCRIPT_CHARS * 1.5), 300)
    
    completion = client.chat.completions.create(
        model=settings.TEXT_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    f"请将这段教学解说词精简到{MAX_SCRIPT_CHARS}字以内，但要求：\n"
                    "1. 保留所有关键信息和专业术语（如CATIA、2D/3D、版本号等）\n"
                    "2. 保持教学讲解的语气和风格\n"
                    "3. 不要丢失重要的技术要点\n"
                    "4. 可以去掉冗余的过渡词，但要保持流畅\n"
                    "5. 绝对不能截断或简化专业术语\n"
                    "6. 避免重复相同的词语或短语\n"
                    "7. **严格检查重复**：确保没有重复字符、重复词语或乱码\n"
                    "8. **标点规范**：正确使用中文标点，不要重复标点符号\n"
                    "9. **自我验证**：生成前请仔细检查原文是否有重复问题并修复"
                ),
            },
            {"role": "user", "content": text},
        ],
        max_tokens=max_tokens,
        temperature=0.7,
        top_p=0.9,
        frequency_penalty=0.3,
        presence_penalty=0.3,
    )
    return final_quality_check(completion.choices[0].message.content.strip())


def protect_technical_terms(text: str):
    protected_terms = {}

    def protect(match):
        key = f"__TERM_{len(protected_terms)}__"
        protected_terms[key] = match.group(0)
        return key

    text = re.sub(r"\b\d+D\b|\bD\d+\b", protect, text, flags=re.IGNORECASE)
    text = re.sub(r"\bV?\d+(?:\.\d+)+\b", protect, text, flags=re.IGNORECASE)
    return text, protected_terms


def restore_technical_terms(text: str, protected_terms: dict) -> str:
    for key, value in protected_terms.items():
        text = text.replace(key, value)
    return text


def fix_technical_repetitions(text: str) -> str:
    """专门修复技术文档中的重复和乱码问题"""
    tech_terms = {
        r'CATIAIA': 'CATIA',
        r'SolidWorksWorks': 'SolidWorks', 
        r'AutoCADAD': 'AutoCAD',
        r'公差差公差': '公差',
        r'形位公差差': '形位公差',
        r'表面处理理': '表面处理',
        r'投影影': '投影',
        r'剖切切': '剖切',
        r'标注注': '标注',
        r'特性性': '特性',
        r'零件件': '零件',
        r'图纸纸': '图纸',
        r'规范范': '规范',
        r'准确确': '准确',
        r'详细细': '详细',
        r'掌握握': '掌握',
        r'理解解': '理解',
        r'学员员': '学员',
        r'要点点': '要点',
        r'适应性性': '适应性',
        r'作用用': '作用',
        r'功能能': '功能',
        r'尺寸寸': '尺寸',
        r'结构构': '结构',
        r'材料料': '材料',
        r'环境境': '环境',
        r'判断断': '判断',
        r'确定定': '确定',
        r'了解解': '了解',
        r'参考考': '参考',
        r'整体体': '整体'
    }
    
    for wrong, correct in tech_terms.items():
        text = re.sub(wrong, correct, text)
    
    text = re.sub(r'(.)\1(.)\2', r'\1\2', text)
    text = re.sub(r'(.)\1{2,}', r'\1', text)
    
    def fix_complex_repetition(s):
        if len(s) < 4:
            return s
        result = []
        i = 0
        while i < len(s):
            if i + 3 < len(s) and s[i] == s[i+2] and s[i+1] == s[i+3]:
                result.append(s[i:i+2])
                i += 4
            elif i + 2 < len(s) and s[i] == s[i+1] and s[i+1] == s[i+2]:
                result.append(s[i])
                i += 3
            elif i + 1 < len(s) and s[i] == s[i+1]:
                result.append(s[i])
                i += 2
            else:
                result.append(s[i])
                i += 1
        return ''.join(result)
    
    text = fix_complex_repetition(text)
    
    words = re.findall(r'[\u4e00-\u9fff]{2,}', text)
    for word in set(words):
        if len(word) >= 2:
            text = re.sub(f'{word}{{{2,}}}', word, text)
            text = re.sub(f'{word}\\s+{word}', word, text)
            text = re.sub(f'{word}[，。！？；：、,.!?;:]\\s*{word}', word, text)
    
    transition_words = ['首先', '其次', '然后', '接着', '最后', '另外', '同时', '此外']
    for word in transition_words:
        pattern = f'{word}\\s*{word}'
        text = re.sub(pattern, word, text)
    
    specific_fixes = {
        r'这对对这以以': '这对于',
        r'判断判断确定确定': '判断',
        r'中的的作用': '中的作用',
        r'工作环境适应性性': '工作环境适应性',
        r'名称和功能能': '名称和功能',
        r'结构特点点': '结构特点',
        r'材料这对对': '材料这对于'
    }
    
    for wrong, correct in specific_fixes.items():
        text = re.sub(wrong, correct, text)
    
    text = re.sub(r'([^.!?。！？])\1{2,}([^.!?。！？]*)$', r'\1\2', text)
    
    return text


def remove_stray_d_noise(text: str) -> str:
    text, protected_terms = protect_technical_terms(text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s*[dD]\s*(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"(?<=[，。！？；、])\s*[dD]\s*(?=[\u4e00-\u9fff])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff])\s*[dD]\s*(?=[，。！？；、])", "", text)
    text = re.sub(r"(?<=[\u4e00-\u9fff，。！？；、])\s*[dD]\s*$", "", text)
    text = re.sub(r'D{2,}', '', text)
    text = re.sub(r'd{2,}', '', text)
    return restore_technical_terms(text, protected_terms)


def remove_repetitive_patterns(text: str) -> str:
    """移除重复模式和乱码"""
    text = re.sub(r'(.)\1{2,}', r'\1', text)
    
    for length in range(2, 5):
        pattern = rf'(.{{{length}}})\1{{2,}}'
        while re.search(pattern, text):
            text = re.sub(pattern, r'\1', text)
    
    common_chars = ['其', '表', '塑', '求', '候', '公', '点', '轮', '要', '他', '的', '是', '在', '有', '和', '这', '们', '为', '了', '不', '人', '就', '中', '大', '上', '个', '国', '到', '说', '时', '地', '方', '面', '性', '能', '料', '牌', '号', '位', '置', '区', '域', '方', '式', '求', '技', '术', '要', '求']
    for char in common_chars:
        text = re.sub(f'{char}{{{3,}}}', char, text)
    
    text = re.sub(r'其他(other)?[其他(other)?]{2,}', '其他', text, flags=re.IGNORECASE)
    text = re.sub(r'(的要求)+', r'\1', text)
    text = re.sub(r'段{2,}型', '断面型', text)
    text = re.sub(r'熔{2,}接', '熔接', text)
    
    text = re.sub(r'[，。！？；：、]{2,}', lambda m: m.group(0)[0], text)
    text = re.sub(r'[,.!?;:]{2,}', lambda m: m.group(0)[0], text)
    text = re.sub(r'[，,.。!！?？;；:：、]{3,}', lambda m: m.group(0)[0], text)
    
    text = re.sub(r'\s{2,}', ' ', text)
    
    words = re.findall(r'([\u4e00-\u9fff]+)', text)
    for word in set(words):
        if len(word) >= 2:
            pattern = f'({word}[，。！？；：、,.!?;:]{{1,2}}){{{2,}}}'
            text = re.sub(pattern, f'\\1', text)
    
    text = re.sub(r'[，。！？；：、,.!?;:]+$', '。', text)
    
    return text


def clean_punctuation(text: str) -> str:
    """专门清理重复和异常的标点符号"""
    text = re.sub(r'，{2,}', '，', text)
    text = re.sub(r'。{2,}', '。', text)
    text = re.sub(r'！{2,}', '！', text)
    text = re.sub(r'？{2,}', '？', text)
    text = re.sub(r'；{2,}', '；', text)
    text = re.sub(r'：{2,}', '：', text)
    text = re.sub(r'、{2,}', '、', text)
    
    text = re.sub(r',{2,}', ',', text)
    text = re.sub(r'\.{2,}', '.', text)
    text = re.sub(r'!{2,}', '!', text)
    text = re.sub(r'\?{2,}', '?', text)
    text = re.sub(r';{2,}', ';', text)
    text = re.sub(r':{2,}', ':', text)
    
    text = re.sub(r'[,.，。]{2,}', '。', text)
    text = re.sub(r'[!?！？]{2,}', '！', text)
    text = re.sub(r'[;；:：]{2,}', '；', text)
    
    text = re.sub(r'\s+([,.!?;:，。！？；：、])', r'\1', text)
    
    if not re.search(r'[.!?。！？]$', text):
        text += '。'
    
    return text


def fix_technical_grammar(text: str) -> str:
    """修复技术文档中的语法和逻辑错误"""
    grammar_fixes = {
        r'这对对这': '这对于',
        r'以以判断': '以判断',
        r'判断确定确定': '判断确定',
        r'了解其工作环境适应性性': '了解其工作环境适应性',
        r'理解零件在整体中的的作用': '理解零件在整体中的作用',
        r'查看零件的标注和了解': '查看零件的标注并了解',
        r'尺寸理解其': '尺寸，理解其',
        r'材料这对对': '材料，这对于',
        r'注意零件的材料这对': '注意零件的材料，这对于'
    }
    
    for wrong, correct in grammar_fixes.items():
        text = re.sub(wrong, correct, text)
    
    text = re.sub(r'([。！？])\s*([^.!?。！？])', r'\1 \2', text)
    
    text = re.sub(r'(\d+)\s*首先', r'\1. 首先', text)
    text = re.sub(r'(\d+)\s*其次', r'\1. 其次', text)
    text = re.sub(r'(\d+)\s*另外', r'\1. 另外', text)
    text = re.sub(r'(\d+)\s*最后', r'\1. 最后', text)
    
    return text


def normalize_special_chars(text: str) -> str:
    """Normalize special characters and convert circled numbers"""
    circled_map = {
        '①': '1', '②': '2', '③': '3', '④': '4', '⑤': '5',
        '⑥': '6', '⑦': '7', '⑧': '8', '⑨': '9', '⑩': '10',
        '⑪': '11', '⑫': '12', '⑬': '13', '⑭': '14', '⑮': '15',
        '⑯': '16', '⑰': '17', '⑱': '18', '⑲': '19', '⑳': '20'
    }
    for circled, normal in circled_map.items():
        text = text.replace(circled, normal)

    text = text.replace('', '')
    text = re.sub(r'[\ufeff]', '', text)

    return text


def clean_generated_text(text: str) -> str:
    text = normalize_special_chars(text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    text = text.strip().strip("'\"""''")
    text = re.sub(r"^\s*[-*•]+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+[.)、]\s*", "", text, flags=re.MULTILINE)
    text = remove_stray_d_noise(text)
    text = fix_technical_repetitions(text)
    text = fix_technical_grammar(text)
    text = remove_repetitive_patterns(text)
    text = clean_punctuation(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def merge_extracted_text(source_text: str, extra_text: str = "") -> str:
    parts = []
    if source_text:
        parts.append(source_text.strip())
    if extra_text:
        parts.append(extra_text.strip())
    merged = "\n".join(part for part in parts if part).strip()
    merged = normalize_special_chars(merged)
    return clean_generated_text(merged)


def final_quality_check(text: str) -> str:
    """最终质量检查，确保没有明显的重复问题"""
    original_length = len(text)
    
    text = clean_generated_text(text)
    
    if len(text) < original_length * 0.5 and original_length > 50:
        basic_clean = re.sub(r"\s+", " ", text.strip())
        basic_clean = re.sub(r'[,.!?;:，。！？；：、]{2,}', lambda m: m.group(0)[0], basic_clean)
        return basic_clean
    
    return text


def parse_image_to_text(image_url: str, understanding_level: str, source_text: str = "", ocr_text: str = ""):
    try:
        extracted_text = merge_extracted_text(source_text or "", ocr_text or "")

        if not extracted_text:
            return False, "No text extracted from this slide (neither PPT text nor OCR)."

        narration = generate_short_narration(extracted_text, understanding_level)
        result = text_improve(narration)
        return True, result
    except Exception as e:
        return handle_exception(e)


def handle_exception(e):
    try:
        error_code = e.body.get("code", "") if hasattr(e, "body") else ""
        if error_code in {"InvalidApiKey", "invalid_api_key"}:
            return False, "SiliconFlow API Key error. Please check configuration."
        return False, f"API call error: {str(e)}"
    except Exception:
        return False, f"Internal service error: {str(e)}"
