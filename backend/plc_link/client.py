from __future__ import annotations

import asyncio
from typing import Any

from ..models import ProtocolSettings
from ..protocol import CommandResult, ProtocolError
from .commands import (
    build_command_words,
    format_plclink_display,
    resolve_spec,
)
from .memory import DeviceMemory
from .server import SoftPlcServer


class PlcLinkClient:
    """疑似 PLC 上で PLCLINK コマンドを発行するクライアント。"""

    def __init__(self, settings: ProtocolSettings):
        self.settings = settings
        self.memory = DeviceMemory()
        # 全 NIC で待受する。host 欄は表示・メッセージ用（特定 IP bind はしない）。
        self.server = SoftPlcServer(
            self.memory,
            host="0.0.0.0",
            port=settings.port,
        )
        self._peer: str | None = None
        self._ignore_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> PlcLinkClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> None:
        """疑似 PLC の待受を開始する（接続待ちは別メソッド）。"""
        if self.server.is_running:
            return
        self.memory.clear()
        try:
            await self.server.start()
        except OSError as exc:
            winerr = getattr(exc, "winerror", None)
            errno = getattr(exc, "errno", None)
            if winerr == 10048 or errno in {98, 10048}:
                raise ProtocolError(
                    "plclink.portInUse",
                    port=self.settings.port,
                    detail=str(exc),
                ) from exc
            if winerr == 10013 or errno in {13, 10013}:
                raise ProtocolError(
                    "plclink.portAccessDenied",
                    port=self.settings.port,
                    detail=str(exc),
                ) from exc
            raise ProtocolError(
                "plclink.startFailed",
                port=self.settings.port,
                detail=str(exc),
            ) from exc

    async def connect(self) -> None:
        await self.start()
        await self.wait_for_client()

    async def wait_for_client(self) -> None:
        """起動済みの疑似 PLC へ VTV が接続するまで待つ。"""
        try:
            await self.server.wait_for_client(self.settings.timeout)
        except TimeoutError as exc:
            raise ProtocolError(
                "plclink.noClientTimeout",
                timeout=f"{self.settings.timeout:g}",
                port=self.settings.port,
            ) from exc

    async def close(self) -> None:
        await self.server.stop()

    async def wait_for_communication(self) -> None:
        """VTV との正常な MC 3E 要求・応答成立を待つ。"""
        try:
            await self.server.wait_for_communication(self.settings.timeout)
        except TimeoutError as exc:
            raise ProtocolError(
                "plclink.communicationTimeout",
                timeout=f"{self.settings.timeout:g}",
            ) from exc

        # VTV が受信応答を処理して接続確認を完了する猶予を確保する。
        await asyncio.sleep(min(0.5, self.settings.timeout / 2))

    async def send_command(
        self,
        command: str,
        expect_result: bool = False,
        result_mode: str = "single",
        *,
        tcp_code: str | None = None,
        arguments: dict[str, Any] | None = None,
        ignore_response: bool = False,
    ) -> CommandResult:
        del expect_result, result_mode  # PLCLINK は常にレスポンス領域を読む
        if self.server.client_count == 0:
            raise ProtocolError("protocol.notConnected")

        await self._await_ignore_task()

        code = (tcp_code or command).upper()
        spec = resolve_spec(code)
        args = arguments or {}
        display = format_plclink_display(spec, args)

        words = build_command_words(
            spec,
            args,
            encoding=self.settings.encoding,
            byte_order=self.settings.byte_order,
            area_size=self.settings.command_size,
        )
        base = self.settings.command_address
        response_base = self.settings.response_address
        busy = self.settings.busy_address

        # 前回レスポンスをクリアし、コマンドをセット（トリガ OFF）
        self.memory.write_words(
            response_base, [0] * self.settings.response_size
        )
        self.memory.write_words(base, words)
        self.memory.set_bit(busy, 0)

        # トリガ ON
        self.memory.write_dword(base, 1)

        if ignore_response:
            self._ignore_task = asyncio.create_task(
                self._complete_ignored_command(base, busy)
            )
            return CommandResult(display, "AK", ["(応答無視)"])

        try:
            await self._wait_bit(busy, 1, "BUSY ON")
            # BUSY ON を確認したら速やかにトリガ OFF
            self.memory.write_dword(base, 0)
            await self._wait_response_ready(response_base)
            await self._wait_bit(busy, 0, "BUSY OFF")
        finally:
            # タイムアウトや切断時も次回の立上りを検出できる状態へ戻す。
            self.memory.write_dword(base, 0)

        result_code = self.memory.read_dword(response_base)
        error_code = self.memory.read_dword(response_base + 2)
        echoed = self.memory.read_dword(response_base + 4)
        param_size = self.memory.read_dword(response_base + 6)
        status = "AK" if result_code == 1 else "NK"
        detail = (
            f"result={result_code} error={error_code} "
            f"cmd={echoed} param_words={param_size}"
        )
        responses = [status, detail]
        if result_code not in (1, 8):
            raise ProtocolError("protocol.invalidResultCode", code=result_code)
        return CommandResult(display, status, responses)

    async def _await_ignore_task(self) -> None:
        task = self._ignore_task
        self._ignore_task = None
        if task is None:
            return
        try:
            await task
        except Exception:
            pass

    async def _complete_ignored_command(self, base: int, busy: int) -> None:
        """応答無視時もトリガ立下りと BUSY 解除をバックグラウンドで完了する。"""
        try:
            await self._wait_bit(busy, 1, "BUSY ON")
            self.memory.write_dword(base, 0)
            await self._wait_bit(busy, 0, "BUSY OFF")
        except Exception:
            self.memory.write_dword(base, 0)

    async def _wait_bit(self, address: int, expected: int, label: str) -> None:
        deadline = asyncio.get_running_loop().time() + self.settings.timeout
        while True:
            if self.memory.get_bit(address) == expected:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise ProtocolError(
                    "plclink.signalTimeout",
                    timeout=f"{self.settings.timeout:g}",
                    label=label,
                    address=address,
                    plo_address=self.settings.plo_address,
                    busy_port=self.settings.busy_port,
                )
            if self.server.client_count == 0:
                raise ProtocolError("protocol.disconnectedMidResponse")
            await asyncio.sleep(0.02)

    async def _wait_response_ready(self, response_base: int) -> None:
        deadline = asyncio.get_running_loop().time() + self.settings.timeout
        while True:
            result_code = self.memory.read_dword(response_base)
            if result_code in (1, 8):
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise ProtocolError(
                    "protocol.noResponseWithin",
                    timeout=f"{self.settings.timeout:g}",
                )
            if self.server.client_count == 0:
                raise ProtocolError("protocol.disconnectedMidResponse")
            await asyncio.sleep(0.02)
