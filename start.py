import subprocess
import sys
import os
import time
import signal
import platform
import argparse

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

IS_WINDOWS = platform.system() == "Windows"
BACKEND_PORT = 9002
FRONTEND_PORT = 5173

processes = []


def find_vite_cmd():
    if IS_WINDOWS:
        local_vite = os.path.join(FRONTEND_DIR, "node_modules", ".bin", "vite.cmd")
        if os.path.exists(local_vite):
            return [local_vite]
        for npx in ["npx.cmd", "npx"]:
            try:
                subprocess.run([npx, "--version"], capture_output=True, timeout=5)
                return [npx, "vite"]
            except Exception:
                continue
    else:
        local_vite = os.path.join(FRONTEND_DIR, "node_modules", ".bin", "vite")
        if os.path.exists(local_vite):
            return [local_vite]
        try:
            subprocess.run(["npx", "--version"], capture_output=True, timeout=5)
            return ["npx", "vite"]
        except Exception:
            pass
    return None


def start_backend():
    print("[backend] 启动 FastAPI 后端...")
    cmd = [sys.executable, "main.py"]
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["preexec_fn"] = os.setsid

    p = subprocess.Popen(cmd, cwd=BACKEND_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, **kwargs)
    processes.append(("backend", p))
    return p


def start_frontend():
    static_index = os.path.join(BACKEND_DIR, "static", "frontend", "index.html")
    if os.path.exists(static_index):
        print("[frontend] 已检测到静态构建产物，前端将由后端直接提供")
        return None

    if not os.path.exists(os.path.join(FRONTEND_DIR, "node_modules")):
        print("[frontend] node_modules 未安装，跳过后端模式启动")
        return None

    print("[frontend] 启动 Vite 前端...")
    cmd_parts = find_vite_cmd()
    if not cmd_parts:
        print("[frontend] 错误: 找不到 npx/vite")
        sys.exit(1)

    full_cmd = cmd_parts + ["--host"]
    print(f"[frontend] 命令: {' '.join(full_cmd)}")
    kwargs = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["preexec_fn"] = os.setsid

    p = subprocess.Popen(full_cmd, cwd=FRONTEND_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, **kwargs)
    processes.append(("frontend", p))
    return p


def check_port(port):
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


def cleanup():
    print("\n[stop] 正在停止所有服务...")
    for name, p in processes:
        if p.poll() is None:
            print(f"[stop] 停止 {name} (PID={p.pid})...")
            try:
                if IS_WINDOWS:
                    p.send_signal(signal.CTRL_BREAK_EVENT)
            except Exception:
                pass
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    p.kill()
                except Exception:
                    pass
            print(f"[stop] {name} 已停止")


def main():
    parser = argparse.ArgumentParser(description="PPT2Video 启动器")
    parser.add_argument("--backend", action="store_true", help="仅启动后端")
    parser.add_argument("--frontend", action="store_true", help="仅启动前端")
    args = parser.parse_args()

    start_both = not args.backend and not args.frontend
    start_be = start_both or args.backend
    start_fe = start_both or args.frontend

    static_index = os.path.join(BACKEND_DIR, "static", "frontend", "index.html")
    server_mode = os.path.exists(static_index)

    print("=" * 50)
    print("  PPT2Video 启动器")
    if start_be:
        print(f"  后端 API:  http://localhost:{BACKEND_PORT}")
    if start_fe and not server_mode:
        print(f"  前端界面:  http://localhost:{FRONTEND_PORT}")
    if server_mode:
        print(f"  访问地址:  http://localhost:{BACKEND_PORT}")
    print("  按 Ctrl+C 停止所有服务")
    print("=" * 50)
    print()

    if start_be and check_port(BACKEND_PORT):
        print(f"[warn] 端口 {BACKEND_PORT} 已被占用")

    p_be = None
    p_fe = None
    if start_be:
        p_be = start_backend()
    if start_fe:
        p_fe = start_frontend()

    print("[wait] 等待服务就绪...")
    time.sleep(4)

    if start_be:
        if p_be.poll() is not None:
            print("[error] 后端启动失败!")
            cleanup()
            sys.exit(1)
        if check_port(BACKEND_PORT):
            print(f"[OK] 后端已就绪 → http://localhost:{BACKEND_PORT}")
        else:
            print("[warn] 后端可能还在启动中...")

    if start_fe and p_fe is not None:
        if p_fe.poll() is not None:
            print("[error] 前端启动失败!")
            cleanup()
            sys.exit(1)
        if check_port(FRONTEND_PORT):
            print(f"[OK] 前端已就绪 → http://localhost:{FRONTEND_PORT}")

    print()
    print(f"[ready] 打开浏览器访问 http://localhost:{BACKEND_PORT}")
    print("[ready] 按 Ctrl+C 停止所有服务")
    print()

    try:
        while True:
            time.sleep(1)
            if start_be and p_be.poll() is not None:
                print("[error] 后端意外退出!")
                break
            if start_fe and p_fe is not None and p_fe.poll() is not None:
                print("[error] 前端意外退出!")
                break
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()
        print("[bye] 再见!")


if __name__ == "__main__":
    main()
