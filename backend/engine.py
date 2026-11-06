from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from .catalog import catalog_by_code, format_command
from .models import (
    BreakStep,
    CommandStep,
    DelayStep,
    IfStep,
    LoopStep,
    NoteStep,
    ProtocolSettings,
    SequenceStep,
    VariableStep,
)
from .field_network import FieldNetworkClient
from .plc_link import PlcLinkClient
from .protocol import (
    CommandResult,
    ProtocolError,
    VtvTcpClient,
    frame_outbound_command,
)

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class DeviceClient(Protocol):
    settings: ProtocolSettings

    async def send_command(
        self,
        command: str,
        expect_result: bool = False,
        result_mode: str = "single",
        *,
        tcp_code: str | None = None,
        arguments: dict[str, Any] | None = None,
        ignore_response: bool = False,
    ) -> CommandResult: ...


class SequenceStopped(RuntimeError):
    pass


class LoopBreak(RuntimeError):
    pass


def _index_step_positions(
    steps: list[SequenceStep],
) -> tuple[dict[str, int], int]:
    """画面上のカード順（両分岐・ループ本体は1回）で位置を付ける。"""
    positions: dict[str, int] = {}
    counter = 0

    def walk(items: list[SequenceStep]) -> None:
        nonlocal counter
        for step in items:
            counter += 1
            if step.id:
                positions[step.id] = counter
            if isinstance(step, IfStep):
                walk(step.then_steps)
                walk(step.else_steps)
            elif isinstance(step, LoopStep):
                walk(step.steps)

    walk(steps)
    return positions, counter


def create_client(
    settings: ProtocolSettings,
) -> VtvTcpClient | PlcLinkClient | FieldNetworkClient:
    if settings.transport == "plclink":
        return PlcLinkClient(settings)
    if settings.transport == "field_network":
        return FieldNetworkClient(settings)
    return VtvTcpClient(settings)


class SequenceEngine:
    def __init__(
        self,
        client: DeviceClient,
        on_event: EventHandler,
        stop_event: asyncio.Event,
    ):
        self.client = client
        self.on_event = on_event
        self.stop_event = stop_event
        self.catalog = catalog_by_code()
        self.last_result: CommandResult | None = None
        self.step_number = 0
        self.loop_depth = 0
        self.positions: dict[str, int] = {}
        self.step_total = 0
        self.started_at = 0.0
        self.last_response = ""
        self.variables: dict[str, str] = {}
        self.card_results: dict[str, CommandResult] = {}

    def _elapsed_ms(self) -> int:
        if not self.started_at:
            return 0
        return int((time.perf_counter() - self.started_at) * 1000)

    def _outcome(self) -> dict[str, object]:
        return {
            "duration_ms": self._elapsed_ms(),
            "last_response": self.last_response,
        }

    def _step_label(self, step: SequenceStep) -> str:
        if isinstance(step, CommandStep):
            code = step.command.upper()
            definition = self.catalog.get(code)
            name = ""
            if isinstance(definition, dict):
                name = str(definition.get("name") or "")
            if name:
                return f"{code} {name}"
            return code
        if isinstance(step, DelayStep):
            return f"待機 {step.milliseconds}ms"
        if isinstance(step, IfStep):
            return "条件"
        if isinstance(step, LoopStep):
            return f"ループ ×{step.count}"
        if isinstance(step, NoteStep):
            text = step.text.strip()
            if not text:
                return "メモ"
            return f"メモ {text[:40]}"
        if isinstance(step, VariableStep):
            name = step.name.strip() or "無名"
            return f"変数 {name}"
        return "BREAK"

    def _step_event(
        self,
        event_type: str,
        step: SequenceStep,
        index: int,
        **extra: object,
    ) -> dict[str, Any]:
        position = index
        if step.id and step.id in self.positions:
            position = self.positions[step.id]
        event: dict[str, Any] = {
            "type": event_type,
            "index": index,
            "position": position,
            "total": self.step_total,
            "step": step.type,
            "id": step.id,
            "label": self._step_label(step),
        }
        event.update(extra)
        return event

    async def run(self, steps: list[SequenceStep]) -> None:
        self.positions, self.step_total = _index_step_positions(steps)
        self.step_number = 0
        self.started_at = time.perf_counter()
        self.last_response = ""
        self.variables = {}
        self.card_results = {}
        await self.on_event(
            {"type": "sequence_started", "total": self.step_total}
        )
        try:
            await self._run_steps(steps)
        except SequenceStopped:
            await self.on_event(
                {
                    "type": "sequence_stopped",
                    "message": "ユーザーが停止しました",
                    **self._outcome(),
                }
            )
            return
        await self.on_event(
            {"type": "sequence_completed", **self._outcome()}
        )

    async def _run_steps(self, steps: list[SequenceStep]) -> None:
        for step in steps:
            self._check_stopped()
            self.step_number += 1
            current = self.step_number
            await self.on_event(self._step_event("step_started", step, current))
            if isinstance(step, CommandStep):
                await self._run_command(step, current)
            elif isinstance(step, DelayStep):
                await self._run_delay(step)
            elif isinstance(step, BreakStep):
                if self.loop_depth == 0:
                    raise ProtocolError(
                        "BREAKカードはループの中で使用してください"
                    )
                await self.on_event(self._step_event("loop_break", step, current))
                await self.on_event(
                    self._step_event("step_completed", step, current)
                )
                raise LoopBreak
            elif isinstance(step, NoteStep):
                await self.on_event(
                    self._step_event("note", step, current, message=step.text)
                )
            elif isinstance(step, VariableStep):
                stored = self._store_variable(step)
                await self.on_event(
                    self._step_event(
                        "variable",
                        step,
                        current,
                        name=step.name.strip(),
                        value=stored,
                        source=step.source,
                    )
                )
            elif isinstance(step, IfStep):
                await self._run_if(step)
            elif isinstance(step, LoopStep):
                await self._run_loop(step)
            await self.on_event(self._step_event("step_completed", step, current))

    def _resolve_arguments(self, step: CommandStep) -> dict[str, Any]:
        resolved: dict[str, Any] = dict(step.arguments)
        for key, raw_name in step.argument_variables.items():
            name = str(raw_name or "").strip()
            if not name:
                continue
            if name not in self.variables:
                raise ProtocolError(f"{step.command}: 変数「{name}」はまだありません")
            resolved[key] = self.variables[name]
        return resolved

    def _remember_result(self, step: CommandStep, result: CommandResult) -> None:
        self.last_result = result
        if step.id:
            self.card_results[step.id] = result

    def _store_variable(self, step: VariableStep) -> str:
        name = step.name.strip()
        if not name:
            raise ProtocolError("変数カードに名前を入力してください")
        value = self._read_variable_source(step)
        self.variables[name] = value
        return value

    def _read_variable_source(self, step: VariableStep) -> str:
        if step.source == "literal":
            return step.value
        if step.source == "last_response":
            text = self.last_response.strip()
            if not text:
                raise ProtocolError("直前の応答がありません")
            return text
        if step.source == "last_status":
            if self.last_result is None or not self.last_result.status:
                raise ProtocolError("直前の結果がありません")
            return self.last_result.status
        if step.source in {"card_response", "card_status"}:
            result = self.card_results.get(step.card_id)
            if result is None:
                raise ProtocolError(
                    "指定したカードの結果がありません。先にそのカードを実行してください"
                )
            if step.source == "card_status":
                return result.status
            text = result.responses[-1].strip() if result.responses else ""
            if not text:
                raise ProtocolError("指定したカードの応答がありません")
            return text
        if step.source == "output_port":
            return self._read_output_port(step.port)
        if step.source == "result_data":
            return self._read_result_data(step)
        raise ProtocolError("変数の取り方が不正です")

    def _read_result_data(self, step: VariableStep) -> str:
        settings = self.client.settings
        if settings.transport == "tcp":
            raise ProtocolError(
                "TCP では結果データ出力を直接読めません。"
                "コマンドの応答を選んでください"
            )
        offset = int(step.offset)
        if offset < 0 or offset % 2:
            raise ProtocolError("結果データの相対アドレスは 0 以上の偶数にしてください")
        size = int(settings.result_data_size)
        if offset + 2 > size:
            raise ProtocolError(
                f"結果データの相対アドレス +{offset:04d} は範囲外です"
            )
        if step.result_format == "string":
            return self._read_result_string(offset)
        raw = self._read_result_dword(offset)
        return self._format_result_value(raw, step.result_format)

    def _read_result_dword(self, offset: int) -> int:
        settings = self.client.settings
        if settings.transport == "plclink":
            memory = getattr(self.client, "memory", None)
            if memory is None:
                raise ProtocolError("結果データ出力を読めません")
            address = int(settings.result_data_address) + offset
            try:
                return int(memory.read_dword(address))
            except (IndexError, ValueError) as exc:
                raise ProtocolError("結果データ出力の読み出し範囲外です") from exc
        if settings.transport != "field_network":
            raise ProtocolError("結果データ出力を読めません")
        from .field_network.layout import build_layout

        layout = build_layout(
            esi_ports=settings.fn_esi_ports,
            eso_ports=settings.fn_eso_ports,
            command_words=settings.command_size,
            response_words=settings.response_size,
            result_words=settings.result_data_size,
        )
        data = self.client.read_input()
        pos = (layout.result_word + offset) * 2
        if pos < 0 or pos + 3 >= len(data):
            raise ProtocolError("結果データ出力の読み出し範囲外です")
        low = data[pos] | (data[pos + 1] << 8)
        high = data[pos + 2] | (data[pos + 3] << 8)
        value = (high << 16) | low
        if value & 0x80000000:
            value -= 0x100000000
        return value

    def _read_result_words(self, offset: int, count: int) -> list[int]:
        settings = self.client.settings
        if count <= 0:
            return []
        if settings.transport == "plclink":
            memory = getattr(self.client, "memory", None)
            if memory is None:
                raise ProtocolError("結果データ出力を読めません")
            address = int(settings.result_data_address) + offset
            try:
                return [int(word) & 0xFFFF for word in memory.read_words(address, count)]
            except (IndexError, ValueError) as exc:
                raise ProtocolError("結果データ出力の読み出し範囲外です") from exc
        if settings.transport != "field_network":
            raise ProtocolError("結果データ出力を読めません")
        from .field_network.layout import build_layout

        layout = build_layout(
            esi_ports=settings.fn_esi_ports,
            eso_ports=settings.fn_eso_ports,
            command_words=settings.command_size,
            response_words=settings.response_size,
            result_words=settings.result_data_size,
        )
        data = self.client.read_input()
        pos = (layout.result_word + offset) * 2
        words: list[int] = []
        for index in range(count):
            byte = pos + index * 2
            if byte < 0 or byte + 1 >= len(data):
                break
            words.append(data[byte] | (data[byte + 1] << 8))
        return words

    def _read_result_string(self, offset: int) -> str:
        from .plc_link.commands import words_to_dword
        from .plc_link.monitor import _decode_string

        settings = self.client.settings
        count = int(settings.result_data_size) - offset
        words = self._read_result_words(offset, count)
        if len(words) >= 2 and words_to_dword(words[:2]) == 2_147_483_646:
            return "No Data"
        return _decode_string(
            words,
            encoding=settings.encoding,
            byte_order=settings.byte_order,
        )

    def _format_result_value(self, raw: int, fmt: str) -> str:
        if raw == 2_147_483_646:
            return "No Data"
        if fmt == "hex":
            return f"0x{raw & 0xFFFFFFFF:08X}"
        if fmt == "fixed":
            decimals = int(self.client.settings.result_data_decimals)
            return f"{raw / (10 ** decimals):.{decimals}f}"
        return str(raw)

    def _read_output_port(self, port: int) -> str:
        transport = self.client.settings.transport
        if transport == "plclink":
            return self._read_plo(port)
        if transport == "field_network":
            return self._read_eso(port)
        raise ProtocolError(
            "TCP では出力ポートを直接読めません。"
            "コマンドの応答を変数に入れてください"
        )

    def _read_plo(self, port: int) -> str:
        settings = self.client.settings
        count = max(1, int(settings.plo_port_count))
        if port < 1 or port > count:
            raise ProtocolError(f"PLO ポート {port} は範囲外です（1–{count}）")
        memory = getattr(self.client, "memory", None)
        if memory is None:
            raise ProtocolError("PLO を読めません")
        bit = memory.get_bit(int(settings.plo_address) + port - 1)
        return "1" if bit else "0"

    def _read_eso(self, port: int) -> str:
        from .field_network.layout import build_layout

        settings = self.client.settings
        count = int(settings.fn_eso_ports)
        if count <= 0:
            raise ProtocolError("ESO ポート数が 0 です")
        if port < 1 or port > count:
            raise ProtocolError(f"ESO ポート {port} は範囲外です（1–{count}）")
        layout = build_layout(
            esi_ports=settings.fn_esi_ports,
            eso_ports=settings.fn_eso_ports,
            command_words=settings.command_size,
            response_words=settings.response_size,
            result_words=settings.result_data_size,
        )
        bit = layout.eso_byte * 8 + (port - 1)
        scanner = getattr(self.client, "scanner", None)
        buffers = getattr(scanner, "buffers", None)
        if buffers is None:
            raise ProtocolError("ESO を読めません")
        try:
            value = buffers.get_in_bit(bit)
        except (IndexError, ValueError) as exc:
            raise ProtocolError("ESO の読み出し範囲外です") from exc
        return "1" if value else "0"

    async def _run_command(self, step: CommandStep, index: int) -> None:
        code = step.command.upper()
        if code not in self.catalog:
            raise ProtocolError(f"未定義のコマンドです: {code}")
        definition = self.catalog[code]
        transport = self.client.settings.transport
        arguments = self._resolve_arguments(step)

        from .local_io import apply_local_io, format_local_io_display, is_local_io_command

        if is_local_io_command(code):
            display = format_local_io_display(code, arguments)
            await self.on_event(
                {
                    "type": "tx",
                    "index": index,
                    "id": step.id,
                    "command": display,
                    "display": display,
                }
            )
            result = await apply_local_io(
                self.client, code=code, arguments=arguments
            )
            self._remember_result(step, result)
            for response in result.responses:
                self.last_response = response
                await self.on_event(
                    {
                        "type": "rx",
                        "index": index,
                        "id": step.id,
                        "response": response,
                    }
                )
            if result.status in {"NK", "ER"}:
                raise ProtocolError(f"{code} が {result.status} を返しました")
            return

        if transport == "plclink" or transport == "field_network":
            from .plc_link.commands import format_plclink_display, resolve_spec

            spec = resolve_spec(code)
            display = format_plclink_display(spec, arguments)
            if transport == "field_network":
                display = display.replace("PLCLINK#", "FN#")
            await self.on_event(
                {
                    "type": "tx",
                    "index": index,
                    "id": step.id,
                    "command": display,
                    "display": display,
                }
            )
            result = await self.client.send_command(
                display,
                tcp_code=code,
                arguments=arguments,
                ignore_response=step.ignore_response,
            )
        else:
            try:
                command = format_command(
                    definition,
                    arguments,
                    self.client.settings.line_number_digits,
                )
            except ValueError as exc:
                raise ProtocolError(str(exc)) from exc

            framed = frame_outbound_command(command, self.client.settings)
            await self.on_event(
                {
                    "type": "tx",
                    "index": index,
                    "id": step.id,
                    "command": framed,
                    "display": framed + "\\r",
                }
            )
            expect_result = bool(definition.get("has_result"))
            condition = definition.get("result_condition")
            if condition:
                expect_result = (
                    str(arguments.get(condition["key"]))
                    == condition["equals"]
                )
            result = await self.client.send_command(
                command,
                expect_result,
                definition.get("result_mode", "single"),
                ignore_response=step.ignore_response,
            )

        self._remember_result(step, result)
        for response in result.responses:
            self.last_response = response
            await self.on_event(
                {
                    "type": "rx",
                    "index": index,
                    "id": step.id,
                    "response": response,
                }
            )
        if step.ignore_response:
            return
        if result.status in {"NK", "ER"}:
            raise ProtocolError(f"{code} が {result.status} を返しました")

    async def _run_delay(self, step: DelayStep) -> None:
        remaining = step.milliseconds / 1000
        while remaining > 0:
            self._check_stopped()
            interval = min(remaining, 0.1)
            await asyncio.sleep(interval)
            remaining -= interval

    async def _run_if(self, step: IfStep) -> None:
        actual = ""
        if self.last_result is not None:
            actual = (
                self.last_result.status
                if step.source == "status"
                else self.last_result.response
            )
        if step.operator == "equals":
            matched = actual == step.value
        elif step.operator == "contains":
            matched = step.value in actual
        else:
            matched = step.value not in actual
        await self.on_event(
            {
                "type": "condition",
                "id": step.id,
                "matched": matched,
                "actual": actual,
                "expected": step.value,
            }
        )
        await self._run_steps(step.then_steps if matched else step.else_steps)

    async def _run_loop(self, step: LoopStep) -> None:
        self.loop_depth += 1
        try:
            for iteration in range(1, step.count + 1):
                self._check_stopped()
                await self.on_event(
                    {
                        "type": "loop_iteration",
                        "id": step.id,
                        "iteration": iteration,
                        "count": step.count,
                    }
                )
                try:
                    await self._run_steps(step.steps)
                except LoopBreak:
                    break
        finally:
            self.loop_depth -= 1

    def _check_stopped(self) -> None:
        if self.stop_event.is_set():
            raise SequenceStopped
