"""Field Network（EtherNet/IP）コマンドクライアント。"""

from __future__ import annotations

import asyncio
from typing import Any

from ..models import ProtocolSettings
from ..plc_link.commands import (
    build_command_words,
    format_plclink_display,
    resolve_spec,
)
from ..protocol import CommandResult, ProtocolError
from .eip_scanner import EipClass1Scanner
from .layout import (
    AssemblyLayout,
    build_layout,
    describe_status_signal,
    resolve_status_signal_bit,
    validate_layout_against_sizes,
)


class FieldNetworkClient:
    """EtherNet/IP Scanner として VTV に接続し、Field Network コマンドを発行する。"""

    def __init__(self, settings: ProtocolSettings):
        self.settings = settings
        self.layout = self._build_layout(settings)
        validate_layout_against_sizes(
            self.layout,
            input_bytes=settings.fn_input_size,
            output_bytes=settings.fn_output_size,
        )
        self.scanner = EipClass1Scanner(
            settings.host,
            tcp_port=settings.port,
            input_size=settings.fn_input_size,
            output_size=settings.fn_output_size,
            rpi_us=settings.fn_rpi_us,
            connection_path=settings.fn_connection_path,
            o_to_t_header_bytes=settings.fn_o_to_t_header_bytes,
            timeout=settings.timeout,
        )
        self._syncing = False

    @staticmethod
    def _build_layout(settings: ProtocolSettings) -> AssemblyLayout:
        return build_layout(
            esi_ports=settings.fn_esi_ports,
            eso_ports=settings.fn_eso_ports,
            command_words=settings.command_size,
            response_words=settings.response_size,
            result_words=settings.result_data_size,
        )

    async def __aenter__(self) -> FieldNetworkClient:
        await self.connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    @property
    def is_connected(self) -> bool:
        return self.scanner.is_connected

    async def connect(self) -> None:
        await self.scanner.connect()
        # 接続直後に空の O->T を流し、I/O を安定させる
        await asyncio.sleep(min(0.2, max(0.05, self.settings.fn_rpi_us / 1_000_000 * 3)))

    async def close(self) -> None:
        await self.scanner.close()

    async def wait_for_communication(self) -> None:
        """T->O パケット受信を確認する。"""
        deadline = asyncio.get_running_loop().time() + self.settings.timeout
        while True:
            stats = self.scanner.buffers.stats
            if int(stats.get("packets_rx") or 0) > 0:
                await asyncio.sleep(min(0.2, self.settings.timeout / 5))
                return
            if not self.scanner.is_connected:
                raise ProtocolError(
                    "EtherNet/IP 接続が切断されました"
                    + (f"（{self.scanner.last_error}）" if self.scanner.last_error else "")
                )
            if asyncio.get_running_loop().time() >= deadline:
                raise ProtocolError(
                    f"{self.settings.timeout:g}秒以内に VTV からの"
                    " Implicit I/O（T→O）を受信できませんでした。"
                    " Field Network 有効化・EDS サイズ一致・ファイアウォール"
                    "（UDP）を確認してください"
                )
            await asyncio.sleep(0.05)

    def sync_from_scanner(self) -> None:
        """スキャナ受信バッファを AssemblyMemory 互換のアクセス用に同期。

        実際の読み書きは scanner.buffers を直接使う。
        """
        return

    def read_input(self) -> bytes:
        return self.scanner.buffers.read_input()

    def read_output(self) -> bytes:
        return self.scanner.buffers.read_output()

    def _write_output_region(self, word_index: int, words: list[int]) -> None:
        buf = bytearray(self.scanner.buffers.read_output())
        for offset, value in enumerate(words):
            pos = (word_index + offset) * 2
            if pos + 1 >= len(buf):
                raise ProtocolError("出力アセンブリ範囲外への書き込みです")
            unsigned = value & 0xFFFF
            buf[pos] = unsigned & 0xFF
            buf[pos + 1] = (unsigned >> 8) & 0xFF
        self.scanner.buffers.write_output(buf)

    def _read_input_dword(self, word_index: int) -> int:
        data = self.scanner.buffers.read_input()
        pos = word_index * 2
        if pos + 3 >= len(data):
            raise ProtocolError("入力アセンブリ範囲外の読み出しです")
        low = data[pos] | (data[pos + 1] << 8)
        high = data[pos + 2] | (data[pos + 3] << 8)
        value = (high << 16) | low
        if value & 0x80000000:
            value -= 0x100000000
        return value

    def _write_output_dword(self, word_index: int, value: int) -> None:
        unsigned = int(value) & 0xFFFFFFFF
        self._write_output_region(
            word_index, [unsigned & 0xFFFF, (unsigned >> 16) & 0xFFFF]
        )

    def _busy_signal(self):
        signal = self.settings.find_status_signal(role="busy")
        if signal is None:
            raise ProtocolError("BUSY 役割のステータス信号が設定されていません")
        return signal

    def _get_busy(self) -> int:
        data = self.scanner.buffers.read_input()
        if not data:
            return 0
        signal = self._busy_signal()
        bit = resolve_status_signal_bit(signal, self.layout)
        byte_index = bit // 8
        if byte_index < 0 or byte_index >= len(data):
            return 0
        return 1 if data[byte_index] & (1 << (bit % 8)) else 0

    async def send_command(
        self,
        command: str,
        expect_result: bool = False,
        result_mode: str = "single",
        *,
        tcp_code: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> CommandResult:
        del expect_result, result_mode
        if not self.scanner.is_connected:
            raise ProtocolError("装置に接続されていません")

        code = (tcp_code or command).upper()
        spec = resolve_spec(code)
        args = arguments or {}
        display = format_plclink_display(spec, args).replace("PLCLINK#", "FN#")

        words = build_command_words(
            spec,
            args,
            encoding=self.settings.encoding,
            byte_order=self.settings.byte_order,
            area_size=self.settings.command_size,
        )
        cmd_base = self.layout.command_word
        rsp_base = self.layout.response_word

        # レスポンス領域は VTV 側が書く。コマンド領域をクリアしてセット。
        self._write_output_region(cmd_base, words)

        # トリガ ON
        self._write_output_dword(cmd_base, 1)

        try:
            await self._wait_busy(1, "BUSY ON")
            self._write_output_dword(cmd_base, 0)
            await self._wait_response_ready(rsp_base)
            await self._wait_busy(0, "BUSY OFF")
        finally:
            self._write_output_dword(cmd_base, 0)

        result_code = self._read_input_dword(rsp_base)
        error_code = self._read_input_dword(rsp_base + 2)
        echoed = self._read_input_dword(rsp_base + 4)
        param_size = self._read_input_dword(rsp_base + 6)
        status = "AK" if result_code == 1 else "NK"
        detail = (
            f"result={result_code} error={error_code} "
            f"cmd={echoed} param_words={param_size}"
        )
        if result_code not in (1, 8):
            raise ProtocolError(f"不正な実行結果です: {result_code}")
        return CommandResult(display, status, [status, detail])

    async def _wait_busy(self, expected: int, label: str) -> None:
        deadline = asyncio.get_running_loop().time() + self.settings.timeout
        while True:
            if self._get_busy() == expected:
                return
            if not self.scanner.is_connected:
                raise ProtocolError("応答の途中で接続が切断されました")
            if asyncio.get_running_loop().time() >= deadline:
                where = describe_status_signal(self._busy_signal())
                raise ProtocolError(
                    f"{self.settings.timeout:g}秒以内に {label} を検出できません"
                    f"（{where}）"
                )
            await asyncio.sleep(0.01)

    async def _wait_response_ready(self, response_word: int) -> None:
        deadline = asyncio.get_running_loop().time() + self.settings.timeout
        while True:
            result_code = self._read_input_dword(response_word)
            if result_code in (1, 8):
                return
            if not self.scanner.is_connected:
                raise ProtocolError("応答の途中で接続が切断されました")
            if asyncio.get_running_loop().time() >= deadline:
                raise ProtocolError(
                    f"{self.settings.timeout:g}秒以内にレスポンスがありません"
                )
            await asyncio.sleep(0.01)
