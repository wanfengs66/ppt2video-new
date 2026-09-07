"""检测并提取 PPTX 中的 SmartArt 文字"""
import os
import zipfile
from lxml import etree

try:
    from pptx import Presentation
except ImportError:
    Presentation = None


def detect_smartart_slides(pptx_path: str) -> list:
    """返回包含 SmartArt 图表的页码列表"""
    if not pptx_path or not os.path.exists(pptx_path):
        return []
    if Presentation is None:
        return []

    smartart_slides = []
    try:
        prs = Presentation(pptx_path)
        for idx, slide in enumerate(prs.slides, start=1):
            for shape in slide.shapes:
                try:
                    xml = shape._element.xml
                except Exception:
                    continue
                if 'http://schemas.openxmlformats.org/drawingml/2006/diagram' in xml:
                    smartart_slides.append(idx)
                    break
    except Exception as e:
        print(f"[SmartArt] detect error: {e}")

    return smartart_slides


def extract_smartart_texts(pptx_path: str) -> list:
    """
    从 SmartArt 的 XML 数据中提取每页文字内容
    作为 VLM 和 python-pptx 都失败时的兜底方案
    返回: List[str] 每页的文字，无 SmartArt 的页返回空字符串
    """
    if not pptx_path or not os.path.exists(pptx_path):
        return []
    if Presentation is None:
        return []

    try:
        prs = Presentation(pptx_path)
        slides = list(prs.slides)
        total = len(slides)
        result = [""] * total

        # 先找出哪些页有 SmartArt 以及它们引用的 data XML
        smartart_refs = {}  # slide_index -> [data_xml_paths]
        for idx, slide in enumerate(slides):
            for shape in slide.shapes:
                try:
                    xml_str = shape._element.xml
                except Exception:
                    continue
                if 'http://schemas.openxmlformats.org/drawingml/2006/diagram' not in xml_str:
                    continue

                # 找到 dgm:relIds 中的 r:dm（数据模型引用）
                root = etree.fromstring(xml_str.encode())
                ns = {
                    'dgm': 'http://schemas.openxmlformats.org/drawingml/2006/diagram',
                    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
                }
                for rel_ids in root.iter('{http://schemas.openxmlformats.org/drawingml/2006/diagram}relIds'):
                    dm = rel_ids.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}dm')
                    if dm:
                        smartart_refs.setdefault(idx, []).append(f"../diagrams/{dm}.xml")

        if not smartart_refs:
            return result

        # 读取 PPTX 中的 SmartArt data XML 提取文字
        with zipfile.ZipFile(pptx_path, 'r') as z:
            for slide_idx, data_refs in smartart_refs.items():
                texts = []
                for ref in data_refs:
                    # 转为 ZIP 内的路径
                    if ref.startswith("../"):
                        zip_path = f"ppt/diagrams/{os.path.basename(ref)}"
                    else:
                        zip_path = ref
                    if zip_path not in z.namelist():
                        continue

                    xml_data = z.read(zip_path)
                    data_root = etree.fromstring(xml_data)

                    # 提取所有 <a:t> 元素的文本
                    for t in data_root.iter('{http://schemas.openxmlformats.org/drawingml/2006/main}t'):
                        if t.text and t.text.strip():
                            texts.append(t.text.strip())

                if texts:
                    result[slide_idx] = "; ".join(texts)

        return result

    except Exception as e:
        print(f"[SmartArt] extract error: {e}")
        return []
