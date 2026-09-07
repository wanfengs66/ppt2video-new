import os
import platform
import shutil
import subprocess

from fastapi import HTTPException
from pdf2image import convert_from_path

from config import settings


def get_libreoffice_command():
    """Resolve a usable LibreOffice executable."""
    # 优先使用配置中指定的路径
    if settings.LIBREOFFICE_PATH and os.path.exists(settings.LIBREOFFICE_PATH):
        return settings.LIBREOFFICE_PATH

    if platform.system() == "Windows":
        possible_paths = [
            r"E:\LibreOffice\program\soffice.exe",
            r"C:\Program Files\LibreOffice\program\soffice.exe",
            r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path

    return "soffice"


def get_poppler_path():
    """Return the Poppler bin directory if pdftoppm.exe is available there."""
    # 优先使用配置中指定的路径
    if settings.POPPLER_PATH:
        candidate = settings.POPPLER_PATH
        if os.path.exists(os.path.join(candidate, "pdftoppm.exe")):
            return candidate

    candidates = [
        r"E:\poppler-25.12.0\Library\bin",
        r"E:\poppler-windows-master\Library\bin",
        r"E:\poppler\Library\bin",
        r"C:\poppler\Library\bin",
    ]

    for candidate in candidates:
        if os.path.exists(os.path.join(candidate, "pdftoppm.exe")):
            return candidate

    pdftoppm = shutil.which("pdftoppm")
    if pdftoppm:
        return os.path.dirname(pdftoppm)

    return None


def pptx_to_pdf(pptx_path, pdf_path):
    """Convert a .pptx file to PDF using LibreOffice."""
    try:
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        soffice_cmd = get_libreoffice_command()
        env = os.environ.copy()
        env['HOME'] = '/tmp'
        if platform.system() == "Windows":
            env['SAL_USE_VCLPLUGIN'] = 'win'
            cmd = [soffice_cmd, "--headless", "--convert-to", "pdf",
                   "--outdir", os.path.dirname(pdf_path), pptx_path]
        else:
            # Linux: 用 xvfb-run 提供虚拟显示器，解决无头服务器渲染偏移问题
            env['SAL_USE_VCLPLUGIN'] = 'gen'
            cmd = ["xvfb-run", "--auto-servernum", soffice_cmd, "--headless",
                   "--convert-to", "pdf", "--outdir", os.path.dirname(pdf_path), pptx_path]

        subprocess.run(cmd, check=True, env=env)
        print(f"Converted {pptx_path} to {pdf_path}")
    except subprocess.CalledProcessError as exc:
        print(f"Failed to convert {pptx_path} to PDF: {exc}")
        raise
    except FileNotFoundError as exc:
        raise Exception(
            "LibreOffice not found. Install LibreOffice and ensure soffice.exe is available."
        ) from exc


def pdf_to_images(pdf_path, output_folder, max_pages=None):
    """Convert each PDF page into a PNG image (150 DPI 足够 720p 视频)."""
    os.makedirs(output_folder, exist_ok=True)

    poppler_path = get_poppler_path()
    try:
        # 150 DPI 对于 720p 视频完全足够：标准幻灯片 10"×7.5" → 1500×1125 像素
        convert_kwargs = {
            "dpi": 300,
            "fmt": "png",
            "poppler_path": poppler_path,
            "thread_count": os.cpu_count() or 4,
        } if poppler_path else {"dpi": 300, "fmt": "png", "thread_count": os.cpu_count() or 4}
        images = convert_from_path(pdf_path, **convert_kwargs)
    except Exception as exc:
        print(f"Poppler error: {exc}")
        raise Exception(
            "Poppler not found or unusable. Install a Windows Poppler build and set "
            "POPPLER_PATH to the bin directory that contains pdftoppm.exe."
        ) from exc

    if max_pages is not None and len(images) > max_pages:
        raise HTTPException(
            status_code=400,
            detail=f"Uploaded PPTX exceeds the page limit of {max_pages} slides.",
        )

    for index, image in enumerate(images, start=1):
        image.save(os.path.join(output_folder, f"slide_{index}.png"), "PNG")
        print(f"Saved slide_{index}.png")


def pptx_to_images(pptx_path, output_folder, max_pages=None):
    """Convert a .pptx file to slide images via PDF+Poppler (best quality)."""
    base_name = os.path.splitext(os.path.basename(pptx_path))[0]
    pdf_path = os.path.join(output_folder, f"{base_name}.pdf")
    try:
        pptx_to_pdf(pptx_path, pdf_path)
        pdf_to_images(pdf_path, output_folder, max_pages=max_pages)
    finally:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
