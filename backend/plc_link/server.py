from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from . import mc3e
from .memory import DeviceMemory

ConnectionHandler = Callable[[str], Awaitable[None] | None]


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
        self._server: asyncio.Server | None = None
        self._clients: set[asyncio.StreamWriter] = set()
        self._connected = asyncio.Event()
        self._communicated = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._server is not None

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )

    async def stop(self) -> None:
        for writer in list(self._clients):
            writer.close()
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

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        peer = writer.get_extra_info("peername")
        peer_text = f"{peer[0]}:{peer[1]}" if peer else "unknown"
        self._clients.add(writer)
        self._connected.set()
        if self.on_connect is not None:
            result = self.on_connect(peer_text)
            if asyncio.iscoroutine(result):
                await result
        buffer = bytearray()
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buffer.extend(chunk)
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
                    response = mc3e.handle_request(self.memory, frame)
                    writer.write(response)
                    await writer.drain()
                    if mc3e.decode_u16(response, 9) == 0:
                        self._communicated.set()
        except (asyncio.IncompleteReadError, ConnectionResetError, OSError):
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
