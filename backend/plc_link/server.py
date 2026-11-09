from __future__ import annotations

import asyncio
import select
import socket
import sys
import threading
import time
from collections.abc import Awaitable, Callable

from ..bit_edges import stamp_bit_edges
from . import mc3e
from .memory import DeviceMemory

ConnectionHandler = Callable[[str], Awaitable[None] | None]
Arrival = tuple[float, bytes] | None

# 受信スレッドが GIL を取り直すまでの上限。
# 既定の 5ms だと、ループが Python 処理を抱えているあいだ立下りが数 ms 遅れる。
_STAMP_SWITCH_S = 0.0001
_stamp_guard = threading.Lock()
_stamp_users = 0
_stamp_previous: float | None = None


def _acquire_stamp_window() -> None:
    """待受中だけ、受信スレッドが時刻を残せる間隔まで GIL の占有を短くする。"""
    global _stamp_users, _stamp_previous
    with _stamp_guard:
        if _stamp_users == 0:
            _stamp_previous = sys.getswitchinterval()
            if _stamp_previous > _STAMP_SWITCH_S:
                sys.setswitchinterval(_STAMP_SWITCH_S)
        _stamp_users += 1


def _release_stamp_window() -> None:
    global _stamp_users, _stamp_previous
    with _stamp_guard:
        if _stamp_users == 0:
            return
        _stamp_users -= 1
        if _stamp_users == 0 and _stamp_previous is not None:
            sys.setswitchinterval(_stamp_previous)
            _stamp_previous = None


class _ListenSocket:
    """asyncio.Server と同じ参照箇所（sockets / close / wait_closed）だけを持つ。"""

    def __init__(self, sock: socket.socket) -> None:
        self.sockets = [sock]

    def close(self) -> None:
        try:
            self.sockets[0].close()
        except OSError:
            pass

    async def wait_closed(self) -> None:
        return None


def format_socket_address(addr: object) -> str | None:
    """接続が着地したローカルアドレスを host:port にする。

    待受が 0.0.0.0 でも、accept 済みソケットの getsockname は
    VTV が指定した接続先（127.0.0.1 や LAN IP）になる。
    """
    if not isinstance(addr, tuple) or len(addr) < 2:
        return None
    host, port = addr[0], addr[1]
    if not isinstance(host, str) or isinstance(port, bool) or not isinstance(port, int):
        return None
    if host.startswith("::ffff:"):
        host = host.removeprefix("::ffff:")
    if host in {"0.0.0.0", "::", ""}:
        return None
    if ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"


class _SocketWriter:
    """受信用スレッドとは別スレッドで、短い MC 応答を送る。"""

    def __init__(self, sock: socket.socket, recv_thread: threading.Thread) -> None:
        self._sock = sock
        self._recv_thread = recv_thread
        self._outgoing = bytearray()
        self._closed = False
        try:
            local_addr = sock.getsockname()
        except OSError:
            local_addr = None
        self.local_endpoint = format_socket_address(local_addr)

    def write(self, data: bytes) -> None:
        self._outgoing.extend(data)

    async def drain(self) -> None:
        if not self._outgoing:
            return
        payload = bytes(self._outgoing)
        self._outgoing.clear()
        await asyncio.to_thread(self._sock.sendall, payload)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    async def wait_closed(self) -> None:
        if self._recv_thread.is_alive():
            await asyncio.to_thread(self._recv_thread.join, 2.0)
        try:
            self._sock.close()
        except OSError:
            pass

    def get_extra_info(self, name: str) -> object:
        if name == "socket":
            return self._sock
        if name == "peername":
            try:
                return self._sock.getpeername()
            except OSError:
                return None
        return None


def _prepare_accepted(conn: socket.socket) -> None:
    """小さい MC 応答を溜めず、アイドル切断も減らす。"""
    try:
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except OSError:
        pass
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if hasattr(socket, "TCP_KEEPIDLE"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        if hasattr(socket, "TCP_KEEPINTVL"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        if hasattr(socket, "TCP_KEEPCNT"):
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        if hasattr(socket, "SIO_KEEPALIVE_VALS"):
            conn.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 30_000, 10_000))
    except (OSError, AttributeError, ValueError):
        pass


def _recv_loop(
    loop: asyncio.AbstractEventLoop,
    conn: socket.socket,
    arrivals: asyncio.Queue[Arrival],
) -> None:
    """recv が戻った時刻を、イベントループが空くのを待たずに残す。"""
    try:
        while True:
            try:
                ready, _, _ = select.select([conn], [], [], 0.5)
            except OSError:
                break
            if not ready:
                continue
            try:
                data = conn.recv(65536)
            except OSError:
                break
            if not data:
                break
            arrived = time.perf_counter()
            try:
                loop.call_soon_threadsafe(arrivals.put_nowait, (arrived, data))
            except RuntimeError:
                break
    finally:
        try:
            loop.call_soon_threadsafe(arrivals.put_nowait, None)
        except RuntimeError:
            pass


class SoftPlcServer:
    """MC プロトコル 3E バイナリの疑似 PLC TCP サーバ。"""

    def __init__(
        self,
        memory: DeviceMemory,
        host: str = "0.0.0.0",
        port: int = 5000,
        on_connect: ConnectionHandler | None = None,
        on_disconnect: ConnectionHandler | None = None,
    ):
        self.memory = memory
        self.host = host
        self.port = port
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self._server: _ListenSocket | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._clients: set[_SocketWriter] = set()
        self._tasks: set[asyncio.Task[None]] = set()
        self._accept_stop = threading.Event()
        self._accept_thread: threading.Thread | None = None
        self._stamp_held = False
        self._connected = asyncio.Event()
        self._communicated = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    @property
    def connected_targets(self) -> list[str]:
        """いま繋がっている VTV が実際に指定した接続先。"""
        targets: list[str] = []
        for writer in tuple(self._clients):
            endpoint = writer.local_endpoint
            if endpoint and endpoint not in targets:
                targets.append(endpoint)
        return targets

    async def start(self) -> None:
        if self._server is not None:
            return
        self._loop = asyncio.get_running_loop()
        _acquire_stamp_window()
        self._stamp_held = True
        try:
            listener = socket.create_server((self.host, self.port))
        except Exception:
            self._stamp_held = False
            _release_stamp_window()
            raise
        listener.settimeout(0.2)
        self._server = _ListenSocket(listener)
        self._accept_stop.clear()
        self._accept_thread = threading.Thread(
            target=self._accept_loop,
            name="plclink-accept",
            daemon=True,
        )
        self._accept_thread.start()

    async def stop(self) -> None:
        try:
            self._accept_stop.set()
            for writer in list(self._clients):
                writer.close()
            for writer in list(self._clients):
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
            self._clients.clear()
            self._connected.clear()
            self._communicated.clear()
            if self._server is not None:
                self._server.close()
                await self._server.wait_closed()
                self._server = None
            thread = self._accept_thread
            self._accept_thread = None
            if thread is not None and thread.is_alive():
                await asyncio.to_thread(thread.join, 2.0)
            if self._tasks:
                await asyncio.gather(*list(self._tasks), return_exceptions=True)
        finally:
            if self._stamp_held:
                self._stamp_held = False
                _release_stamp_window()

    async def wait_for_client(self, timeout: float) -> None:
        await asyncio.wait_for(self._connected.wait(), timeout=timeout)

    async def wait_for_communication(self, timeout: float) -> None:
        """正常な MC 3E 要求へ応答を送信するまで待つ。"""
        await asyncio.wait_for(self._communicated.wait(), timeout=timeout)

    async def __aenter__(self) -> SoftPlcServer:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()

    def _accept_loop(self) -> None:
        listener = self._server.sockets[0] if self._server is not None else None
        if listener is None:
            return
        while not self._accept_stop.is_set():
            try:
                conn, _addr = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            loop = self._loop
            if loop is None:
                conn.close()
                break
            try:
                loop.call_soon_threadsafe(self._on_accept, conn)
            except RuntimeError:
                conn.close()
                break

    def _on_accept(self, conn: socket.socket) -> None:
        loop = self._loop
        if loop is None:
            conn.close()
            return
        task = loop.create_task(self._handle_socket(conn))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _handle_socket(self, conn: socket.socket) -> None:
        loop = self._loop
        if loop is None:
            conn.close()
            return
        _prepare_accepted(conn)
        try:
            peer = conn.getpeername()
        except OSError:
            peer = None
        peer_text = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        arrivals: asyncio.Queue[Arrival] = asyncio.Queue()
        recv_thread = threading.Thread(
            target=_recv_loop,
            args=(loop, conn, arrivals),
            name="plclink-recv",
            daemon=True,
        )
        writer = _SocketWriter(conn, recv_thread)
        self._clients.add(writer)
        self._connected.set()
        recv_thread.start()
        buffer = bytearray()
        try:
            if self.on_connect is not None:
                result = self.on_connect(peer_text)
                if asyncio.iscoroutine(result):
                    await result
            while True:
                item = await arrivals.get()
                if item is None:
                    break
                arrived, chunk = item
                buffer.extend(chunk)
                wrote, accepted = self._consume_frames(buffer, arrived, writer)
                if wrote:
                    await self._drain_writer(writer)
                if accepted:
                    self._communicated.set()
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
            pass
        except Exception:
            # 1 クライアントの予期せぬ例外でサーバ全体は落とさない。
            pass
        finally:
            self._clients.discard(writer)
            if not self._clients:
                self._connected.clear()
                self._communicated.clear()
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            if self.on_disconnect is not None:
                result = self.on_disconnect(peer_text)
                if asyncio.iscoroutine(result):
                    await result

    def _consume_frames(
        self,
        buffer: bytearray,
        arrived: float,
        writer: _SocketWriter,
    ) -> tuple[bool, bool]:
        """届いたバイト列のうち、完結した要求を受信時刻のまま処理する。"""
        wrote = False
        accepted = False
        while True:
            needed = mc3e.minimum_frame_length(buffer)
            if needed is None:
                break
            if needed == 2 and int.from_bytes(buffer[0:2], "big") != (
                mc3e.SUBHEADER_REQUEST
            ):
                del buffer[0]
                continue
            if len(buffer) < needed:
                break
            frame = bytes(buffer[:needed])
            del buffer[:needed]
            try:
                with stamp_bit_edges(arrived):
                    response = mc3e.handle_request(self.memory, frame)
            except Exception:
                # handle_request は原則例外を返さないが、接続維持を優先する。
                response = mc3e.error_response(frame)
            writer.write(response)
            wrote = True
            if mc3e.decode_u16(response, 9) == 0:
                accepted = True
        return wrote, accepted

    async def _drain_writer(self, writer: _SocketWriter) -> None:
        """応答を送り切る。エッジ時刻はこの待ちの前に確定している。"""
        await writer.drain()
