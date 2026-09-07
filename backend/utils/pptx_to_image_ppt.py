"""
使用 Microsoft PowerPoint 将 PPTX 导出为图片（仅 Windows）
"""
import os
import platform
import tempfile
import threading
import time

# 跨进程文件锁：PowerPoint COM 一次只能处理一个文件
_PPT_LOCK_FILE = os.path.join(tempfile.gettempdir(), "ppt_com.lock")
_ppt_lock = threading.Lock()


def _acquire_ppt_lock() -> bool:
    """跨进程获取 PowerPoint COM 锁（最多等 30 秒）"""
    for _ in range(300):
        try:
            fd = os.open(_PPT_LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            os.close(fd)
            return True
        except FileExistsError:
            time.sleep(0.1)
    return False


def _release_ppt_lock():
    try:
        os.remove(_PPT_LOCK_FILE)
    except FileNotFoundError:
        pass


_PPT_AVAILABLE = platform.system() == "Windows"


def pptx_to_images_via_powerpoint(pptx_path: str, output_folder: str) -> bool:
    if not _PPT_AVAILABLE:
        return False

    import win32com.client
    import win32gui
    import win32con

    pptx_path = os.path.abspath(pptx_path)
    output_folder = os.path.abspath(output_folder)
    if not os.path.exists(pptx_path):
        return False
    os.makedirs(output_folder, exist_ok=True)

    with _ppt_lock:
        locked = _acquire_ppt_lock()
        if not locked:
            print("[PPT] COM lock timeout (busy)")
            return False
        try:
            print(f"[PPT] Rendering: {os.path.basename(pptx_path)}")
            powerpoint = None
            presentation = None
            try:
                powerpoint = win32com.client.Dispatch("PowerPoint.Application")
                powerpoint.Visible = True
                for _ in range(20):
                    hwnd = win32gui.FindWindow("PPTFrameClass", None)
                    if hwnd:
                        win32gui.ShowWindow(hwnd, win32con.SW_HIDE)
                        break
                    time.sleep(0.1)

                presentation = powerpoint.Presentations.Open(pptx_path, WithWindow=False)
                _ = presentation.Slides.Count
                time.sleep(2)

                sw = round(presentation.PageSetup.SlideWidth * 72.0 / 72.0)
                sh = round(presentation.PageSetup.SlideHeight * 72.0 / 72.0)

                for i, slide in enumerate(presentation.Slides, start=1):
                    for j in range(min(3, slide.Shapes.Count)):
                        try:
                            _ = slide.Shapes(j + 1).Left
                        except Exception:
                            pass
                    output_path = os.path.join(output_folder, f"slide_{i}.png")
                    slide.Export(output_path, "PNG", sw, sh)

                print(f"[PPT] Done: {os.path.basename(pptx_path)}")
                return True

            except Exception as e:
                print(f"[PPT] Error: {e}")
                return False

            finally:
                if presentation is not None:
                    try:
                        presentation.Close()
                    except Exception:
                        pass
                if powerpoint is not None:
                    try:
                        powerpoint.Quit()
                    except Exception:
                        pass
        finally:
            _release_ppt_lock()
            print("[PPT] Lock released")
