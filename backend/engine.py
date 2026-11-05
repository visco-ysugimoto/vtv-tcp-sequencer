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
    ProtocolSettings,
    SequenceStep,
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
            elif isinstance(step, IfStep):
                await self._run_if(step)
            elif isinstance(step, LoopStep):
                await self._run_loop(step)
            await self.on_event(self._step_event("step_completed", step, current))

    async def _run_command(self, step: CommandStep, index: int) -> None:
        code = step.command.upper()
        if code not in self.catalog:
            raise ProtocolError(f"未定義のコマンドです: {code}")
        definition = self.catalog[code]
        transport = self.client.settings.transport

        from .local_io import apply_local_io, format_local_io_display, is_local_io_command

        if is_local_io_command(code):
            display = format_local_io_display(code, step.arguments)
            await self.on_event(
                {
                    "type": "tx",
                    "index": index,
                    "command": display,
                    "display": display,
                }
            )
            result = await apply_local_io(
                self.client, code=code, arguments=step.arguments
            )
            self.last_result = result
            for response in result.responses:
                self.last_response = response
                await self.on_event(
                    {"type": "rx", "index": index, "response": response}
                )
            if result.status in {"NK", "ER"}:
                raise ProtocolError(f"{code} が {result.status} を返しました")
            return

        if transport == "plclink" or transport == "field_network":
            from .plc_link.commands import format_plclink_display, resolve_spec

            spec = resolve_spec(code)
            display = format_plclink_display(spec, step.arguments)
            if transport == "field_network":
                display = display.replace("PLCLINK#", "FN#")
            await self.on_event(
                {
                    "type": "tx",
                    "index": index,
                    "command": display,
                    "display": display,
                }
            )
            result = await self.client.send_command(
                display,
                tcp_code=code,
                arguments=step.arguments,
                ignore_response=step.ignore_response,
            )
        else:
            try:
                command = format_command(
                    definition,
                    step.arguments,
                    self.client.settings.line_number_digits,
                )
            except ValueError as exc:
                raise ProtocolError(str(exc)) from exc

            framed = frame_outbound_command(command, self.client.settings)
            await self.on_event(
                {
                    "type": "tx",
                    "index": index,
                    "command": framed,
                    "display": framed + "\\r",
                }
            )
            expect_result = bool(definition.get("has_result"))
            condition = definition.get("result_condition")
            if condition:
                expect_result = (
                    str(step.arguments.get(condition["key"]))
                    == condition["equals"]
                )
            result = await self.client.send_command(
                command,
                expect_result,
                definition.get("result_mode", "single"),
                ignore_response=step.ignore_response,
            )

        self.last_result = result
        for response in result.responses:
            self.last_response = response
            await self.on_event(
                {"type": "rx", "index": index, "response": response}
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
