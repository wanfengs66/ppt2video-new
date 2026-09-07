"""
上下文管理器：维护 PPT 解说词的连贯性
解决问题：
1. 每页解说词能感知前后页内容
2. 避免重复讲解相同概念
3. 保持术语使用的一致性
"""
import os
import json
from typing import List, Dict, Optional

from config import settings


class PPTContextManager:
    """PPT 上下文管理器"""

    def __init__(self, job_id: str, cache_dir: str = None):
        self.job_id = job_id
        if cache_dir is None:
            cache_dir = settings.UPLOAD_DIR
        self.cache_file = os.path.join(cache_dir, job_id, "context_cache.json")
        self.context = self._load_context()

    def _load_context(self) -> Dict:
        """加载缓存的上下文"""
        if os.path.exists(self.cache_file):
            with open(self.cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "ppt_title": "",
            "ppt_summary": "",
            "ppt_full_content": "",
            "slide_texts": {},
            "generated_scripts": {},
            "key_terms": [],
            "slide_topics": {}
        }

    def _save_context(self):
        """保存上下文到缓存"""
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.context, f, ensure_ascii=False, indent=2)

    def set_ppt_summary(self, summary: str):
        """设置 PPT 整体摘要"""
        self.context["ppt_summary"] = summary
        self._save_context()

    def set_ppt_full_content(self, content: str):
        """设置完整 PPT 内容"""
        self.context["ppt_full_content"] = content
        self._save_context()

    def set_slide_text(self, slide_index: int, text: str):
        """设置某页的提取文字"""
        self.context["slide_texts"][str(slide_index)] = text
        self._save_context()

    def set_generated_script(self, slide_index: int, script: str):
        """设置某页的生成解说词"""
        self.context["generated_scripts"][str(slide_index)] = script
        self._save_context()

    def add_key_term(self, term: str):
        """添加关键术语"""
        if term not in self.context["key_terms"]:
            self.context["key_terms"].append(term)
            self._save_context()

    def get_context_for_slide(self, slide_index: int, window_size: int = 2) -> str:
        """获取某页的上下文信息"""
        context_parts = []

        # 前面页面的内容（已生成的解说词）
        prev_scripts = []
        for i in range(max(1, slide_index - window_size), slide_index):
            script = self.context["generated_scripts"].get(str(i))
            if script:
                prev_scripts.append(f"第{i}页：{script[:200]}")

        if prev_scripts:
            context_parts.append(f"【前面页面已讲内容（⚠️当前页请勿重复）】\n" + "\n".join(prev_scripts))

        # 后面页面的文字（提取的原文）
        next_texts = []
        for i in range(slide_index + 1, min(slide_index + window_size + 1, len(self.context["slide_texts"]) + 1)):
            text = self.context["slide_texts"].get(str(i))
            if text:
                next_texts.append(f"第{i}页：{text[:100]}")

        if next_texts:
            context_parts.append(f"【后面页面将讲内容】\n" + "\n".join(next_texts))

        # 关键术语
        if self.context["key_terms"]:
            context_parts.append(f"【关键术语】\n{', '.join(self.context['key_terms'][:20])}")

        return "\n\n".join(context_parts)

    def get_previous_script(self, slide_index: int) -> Optional[str]:
        """获取上一页的解说词"""
        return self.context["generated_scripts"].get(str(slide_index - 1))

    def get_next_text(self, slide_index: int) -> Optional[str]:
        """获取下一页的文字"""
        return self.context["slide_texts"].get(str(slide_index + 1))

    def extract_key_terms(self, text: str) -> List[str]:
        """从文本中提取关键术语"""
        import re
        terms = re.findall(r'[A-Z][A-Za-z0-9]+|[一-鿿]{2,}(?:系统|平台|模型|算法|框架|技术|方法)', text)
        return list(set(terms))[:10]

    def clear_cache(self):
        """清除缓存"""
        if os.path.exists(self.cache_file):
            os.remove(self.cache_file)
        self.context = self._load_context()


def build_enhanced_prompt(
    current_text: str,
    context_manager: PPTContextManager,
    slide_index: int,
    understanding_level: str = "text-understanding"
) -> str:
    """构建增强的提示词，包含上下文信息"""
    context = context_manager.get_context_for_slide(slide_index)
    prev_script = context_manager.get_previous_script(slide_index)

    prompt_parts = []

    if context:
        prompt_parts.append(context)

    prompt_parts.append(f"【当前页内容（第{slide_index}页）】\n{current_text}")

    if prev_script:
        prompt_parts.append(f"【衔接要求】\n上一页讲到：{prev_script[-50:]}\n请自然衔接，避免重复")

    return "\n\n".join(prompt_parts)
