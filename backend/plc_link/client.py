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
        self.server = SoftPlcServer(
            self.memory,
            host=settings.host or "0.0.0.0",
            port=settings.port,
        )
        self._peer: str | None = None

    async def __aenter__(self) -> PlcLinkClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def connect(self) -> None:
        self.memory.clear()
        try:
            await self.server.start()
        except OSError as exc:
            raise ProtocolError(
                f"疑似 PLC を起動できません"
                f"（{self.settings.host}:{self.settings.port}）: {exc}"
            ) from exc
        try:
            await self.wait_for_client()
        except ProtocolError:
            await self.server.stop()
            raise

    async def wait_for_client(self) -> None:
        """起動済みの疑似 PLC へ VTV が接続するまで待つ。"""
        try:
            await self.server.wait_for_client(self.settings.timeout)
        except TimeoutError as exc:
            raise ProtocolError(
                f"{self.settings.timeout:g}秒以内に VTV からの接続がありません。"
                f" VTV の PLCLINK 通信先を"
                f" この PC の IP:{self.settings.port} に設定してください"
            ) from exc

    async def close(self) -> None:
        await self.server.stop()

    async def wait_for_communication(self) -> None:
        """VTV との正常な MC 3E 要求・応答成立を待つ。"""
        try:
            await self.server.wait_for_communication(self.settings.timeout)
        except TimeoutError as exc:
            raise ProtocolError(
                f"{self.settings.timeout:g}秒以内に VTV からの"
                "正常な MC 3E 通信を確認できませんでした"
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
    ) -> CommandResult:
        del expect_result, result_mode  # PLCLINK は常にレスポンス領域を読む
        if self.server.client_count == 0:
            raise ProtocolError("装置に接続されていません")

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
            raise ProtocolError(f"不正な実行結果です: {result_code}")
        return CommandResult(display, status, responses)

    async def _wait_bit(self, address: int, expected: int, label: str) -> None:
        deadline = asyncio.get_running_loop().time() + self.settings.timeout
        while True:
            if self.memory.get_bit(address) == expected:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise ProtocolError(
                    f"{self.settings.timeout:g}秒以内に {label} を検出できません"
                    f"（M{address} = PLO先頭 M{self.settings.plo_address}"
                    f" + Port {self.settings.busy_port}）"
                )
            if self.server.client_count == 0:
                raise ProtocolError("応答の途中で接続が切断されました")
            await asyncio.sleep(0.02)

    async def _wait_response_ready(self, response_base: int) -> None:
        deadline = asyncio.get_running_loop().time() + self.settings.timeout
        while True:
            result_code = self.memory.read_dword(response_base)
            if result_code in (1, 8):
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise ProtocolError(
                    f"{self.settings.timeout:g}秒以内にレスポンスがありません"
                )
            if self.server.client_count == 0:
                raise ProtocolError("応答の途中で接続が切断されました")
            await asyncio.sleep(0.02)
