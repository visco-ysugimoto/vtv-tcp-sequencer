"""VTV TCP Sequencer の起動入口（開発・exe 共通）。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import traceback
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
_server_error: BaseException | None = None


def _ensure_stdio() -> None:
    """console=False の exe では stdout/stderr が None になるため補う。"""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115


def _app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    path = base / "VTV_TCP_Sequencer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}"
    try:
        with (_app_data_dir() / "startup.log").open("a", encoding="utf-8") as fp:
            fp.write(line + "\n")
    except OSError:
        pass


def _message_box(text: str, title: str = "VTV TCP Sequencer") -> None:
    _log(f"MESSAGE: {text.replace(chr(10), ' | ')}")
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
    path = _app_data_dir() / "app-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _wait_for_server(url: str = CATALOG_URL, timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if _server_error is not None:
            raise RuntimeError(f"サーバー起動に失敗しました:\n{_server_error}") from _server_error
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    return
                last_error = f"HTTP {response.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
            time.sleep(0.1)
    raise TimeoutError(
        f"サーバーが {timeout:.0f} 秒以内に起動しませんでした。\n"
        f"詳細: {last_error or '不明'}\n\n"
        "ウイルス対策ソフトが exe を隔離していないか確認し、\n"
        "VTV_TCP_Sequencer フォルダを除外設定へ追加してください。\n"
        f"ログ: {_app_data_dir() / 'startup.log'}"
    )


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
    # 社内プロキシ経由で localhost へ飛ばされると接続拒否になるため回避する
    env = os.environ.copy()
    bypass = "127.0.0.1,localhost,::1"
    for key in ("NO_PROXY", "no_proxy"):
        existing = env.get(key, "").strip()
        env[key] = f"{existing},{bypass}" if existing else bypass

    return subprocess.Popen(
        [
            str(browser),
            f"--app={URL}",
            f"--user-data-dir={_profile_dir()}",
            "--proxy-bypass-list=<-loopback>;127.0.0.1;localhost;::1",
            "--no-proxy-server",
            "--no-first-run",
            "--no-default-browser-check",
            "--disk-cache-size=1",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=env,
    )


def _run_browser_session(
    browser: Path,
    server_thread: threading.Thread | None = None,
) -> None:
    if not _is_our_server_running():
        raise RuntimeError(
            "ローカルサーバー（127.0.0.1:8765）に接続できません。\n"
            "ウイルス対策ソフトがアプリを停止していないか確認し、\n"
            "除外設定のうえ再起動してください。"
        )
    _log("launching browser")
    process = _launch_browser(browser)
    try:
        while True:
            try:
                process.wait(timeout=1.0)
                break
            except subprocess.TimeoutExpired:
                if _server_error is not None:
                    _message_box(
                        "バックエンドが異常終了しました。\n"
                        f"{_server_error}\n\n"
                        f"ログ: {_app_data_dir() / 'startup.log'}"
                    )
                    break
                if server_thread is not None and not server_thread.is_alive():
                    _log(
                        "server thread exited unexpectedly "
                        f"error={_server_error!r}"
                    )
                    detail = (
                        str(_server_error)
                        if _server_error is not None
                        else "詳細は startup.log を確認してください"
                    )
                    _message_box(
                        "バックエンドが異常終了しました。\n"
                        f"{detail}\n\n"
                        "タスクマネージャーで VTV_TCP_Sequencer.exe / python.exe"
                        " をすべて終了してから再起動してください。\n\n"
                        f"ログ: {_app_data_dir() / 'startup.log'}"
                    )
                    break
                if not _is_our_server_running():
                    _message_box(
                        "アプリ画面は開いていますが、ローカルサーバーが停止しました。\n"
                        "よくある原因はウイルス対策ソフトによる隔離です。\n\n"
                        "1. 隔離されたファイルを復元する\n"
                        "2. VTV_TCP_Sequencer フォルダを除外設定に追加する\n"
                        "3. exe を再度起動する\n\n"
                        f"ログ: {_app_data_dir() / 'startup.log'}"
                    )
                    break
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()


def _attach_to_existing_server(browser: Path) -> None:
    _log("another instance holds mutex; attaching")
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        if _is_our_server_running():
            _run_browser_session(browser)
            return
        time.sleep(0.15)
    _message_box(
        "VTV TCP Sequencer は起動処理中、または前回のプロセスが残っています。\n"
        "タスクマネージャーで VTV_TCP_Sequencer.exe を終了し、\n"
        "少し待ってから再度実行してください。"
    )
    raise SystemExit(1)


def _port_blocked_message() -> None:
    _message_box(
        f"ポート {PORT} は別のプログラムが使用中です。\n"
        "タスクマネージャーで VTV_TCP_Sequencer.exe が残っていないか確認し、\n"
        "終了してから再度起動してください。"
    )


def _run_uvicorn() -> None:
    global _server_error
    try:
        config = uvicorn.Config(
            app,
            host=HOST,
            port=PORT,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        _run_uvicorn.server = server  # type: ignore[attr-defined]
        server.run()
    except BaseException as exc:  # noqa: BLE001 - surface startup failures
        _server_error = exc
        _log(f"uvicorn failed: {exc}\n{traceback.format_exc()}")


def _stop_uvicorn() -> None:
    server = getattr(_run_uvicorn, "server", None)
    if server is None:
        return
    server.should_exit = True
    if hasattr(server, "force_exit"):
        server.force_exit = True


def _run_server_and_browser(browser: Path) -> None:
    global _server_error
    _server_error = None
    _log(f"starting server on {URL}")
    server_thread = threading.Thread(target=_run_uvicorn, name="uvicorn", daemon=False)
    server_thread.start()

    try:
        _wait_for_server()
        _log("server ready")
    except Exception as exc:
        _stop_uvicorn()
        server_thread.join(timeout=10)
        _message_box(str(exc))
        raise SystemExit(1) from exc

    try:
        _run_browser_session(browser, server_thread)
    finally:
        _log("shutting down server")
        _stop_uvicorn()
        server_thread.join(timeout=15)


def main() -> None:
    _ensure_stdio()
    _log(f"start frozen={getattr(sys, 'frozen', False)} exe={sys.executable}")

    browser = _find_chromium_browser()
    if browser is None:
        _message_box(
            "Microsoft Edge または Google Chrome が見つかりません。\n"
            "いずれかをインストールしてから再度起動してください。"
        )
        raise SystemExit(1)
    _log(f"browser={browser}")

    if not _acquire_instance_lock():
        _attach_to_existing_server(browser)
        return

    try:
        if _port_listening(HOST, PORT):
            if _is_our_server_running():
                _log("reusing existing server")
                _run_browser_session(browser)
                return
            _port_blocked_message()
            raise SystemExit(1)

        _run_server_and_browser(browser)
    finally:
        _release_instance_lock()
        _log("exit")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        _ensure_stdio()
        _message_box(
            f"起動に失敗しました:\n{exc}\n\n"
            f"ログ: {_app_data_dir() / 'startup.log'}"
        )
        raise SystemExit(1) from exc
