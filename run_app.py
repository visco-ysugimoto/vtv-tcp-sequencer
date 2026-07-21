"""VTV TCP Sequencer の起動入口（開発・exe 共通）。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from backend.main import app

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"
CATALOG_URL = f"{URL}/api/catalog"
MUTEX_NAME = "Local\\VTV_TCP_Sequencer"
_instance_mutex: int | None = None


def _ensure_stdio() -> None:
    """console=False の exe では stdout/stderr が None になるため補う。"""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _message_box(text: str, title: str = "VTV TCP Sequencer") -> None:
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
    else:
        print(text, file=sys.stderr)


def _find_chromium_browser() -> Path | None:
    env_paths = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Microsoft"
        / "Edge"
        / "Application"
        / "msedge.exe",
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
        Path(os.environ.get("LOCALAPPDATA", ""))
        / "Google"
        / "Chrome"
        / "Application"
        / "chrome.exe",
    ]
    for path in env_paths:
        if path.is_file():
            return path
    return None


def _profile_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = base / "VTV_TCP_Sequencer" / "app-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wait_for_server(url: str = URL, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if 200 <= response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.1)
    raise TimeoutError(f"サーバーが {timeout:.0f} 秒以内に起動しませんでした")


def _port_listening(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _is_our_server_running() -> bool:
    try:
        with urllib.request.urlopen(CATALOG_URL, timeout=0.5) as response:
            return response.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _acquire_instance_lock() -> bool:
    """True ならこのプロセスがサーバー担当。False なら別インスタンスがいる。"""
    global _instance_mutex
    if sys.platform != "win32":
        return True
    import ctypes

    kernel32 = ctypes.windll.kernel32
    ERROR_ALREADY_EXISTS = 183
    handle = kernel32.CreateMutexW(None, True, MUTEX_NAME)
    if kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        return False
    _instance_mutex = handle
    return True


def _release_instance_lock() -> None:
    global _instance_mutex
    if sys.platform != "win32" or _instance_mutex is None:
        return
    import ctypes

    ctypes.windll.kernel32.CloseHandle(_instance_mutex)
    _instance_mutex = None


def _launch_browser(browser: Path) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [
            str(browser),
            f"--app={URL}",
            f"--user-data-dir={_profile_dir()}",
            "--no-first-run",
            "--no-default-browser-check",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _run_browser_session(browser: Path) -> None:
    process = _launch_browser(browser)
    try:
        process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


def _attach_to_existing_server(browser: Path) -> None:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if _is_our_server_running():
            _run_browser_session(browser)
            return
        time.sleep(0.15)
    _message_box(
        "VTV TCP Sequencer は起動処理中です。\n"
        "少し待ってから再度 exe を実行してください。"
    )
    raise SystemExit(1)


def _port_blocked_message() -> None:
    _message_box(
        f"ポート {PORT} は別のプログラムが使用中です。\n"
        "タスクマネージャーで VTV_TCP_Sequencer.exe が残っていないか確認し、\n"
        "終了してから再度起動してください。"
    )


def _run_server_and_browser(browser: Path) -> None:
    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="uvicorn", daemon=False)
    server_thread.start()

    try:
        _wait_for_server()
    except TimeoutError as exc:
        server.should_exit = True
        server_thread.join(timeout=10)
        _message_box(str(exc))
        raise SystemExit(1) from exc

    try:
        _run_browser_session(browser)
    finally:
        server.should_exit = True
        if hasattr(server, "force_exit"):
            server.force_exit = True
        server_thread.join(timeout=15)


def main() -> None:
    _ensure_stdio()

    browser = _find_chromium_browser()
    if browser is None:
        _message_box(
            "Microsoft Edge または Google Chrome が見つかりません。\n"
            "いずれかをインストールしてから再度起動してください。"
        )
        raise SystemExit(1)

    if not _acquire_instance_lock():
        _attach_to_existing_server(browser)
        return

    try:
        if _port_listening(HOST, PORT):
            if _is_our_server_running():
                _run_browser_session(browser)
                return
            _port_blocked_message()
            raise SystemExit(1)

        _run_server_and_browser(browser)
    finally:
        _release_instance_lock()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        _ensure_stdio()
        _message_box(f"起動に失敗しました:\n{exc}")
        raise SystemExit(1) from exc
