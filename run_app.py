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


def _wait_for_server(timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(URL, timeout=0.5) as response:
                if 200 <= response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.1)
    raise TimeoutError(f"サーバーが {timeout:.0f} 秒以内に起動しませんでした")


def _port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def main() -> None:
    _ensure_stdio()

    browser = _find_chromium_browser()
    if browser is None:
        _message_box(
            "Microsoft Edge または Google Chrome が見つかりません。\n"
            "いずれかをインストールしてから再度起動してください。"
        )
        raise SystemExit(1)

    if not _port_available(HOST, PORT):
        _message_box(
            f"ポート {PORT} は既に使用中です。\n"
            "別の VTV TCP Sequencer が起動していないか確認してください。"
        )
        raise SystemExit(1)

    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    server_thread.start()

    try:
        _wait_for_server()
    except TimeoutError as exc:
        server.should_exit = True
        _message_box(str(exc))
        raise SystemExit(1) from exc

    process = subprocess.Popen(
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
    try:
        process.wait()
    finally:
        server.should_exit = True
        server_thread.join(timeout=5)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        _ensure_stdio()
        _message_box(f"起動に失敗しました:\n{exc}")
        raise SystemExit(1) from exc
