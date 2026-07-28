from __future__ import annotations

import asyncio
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
    ) -> CommandResult: ...


class SequenceStopped(RuntimeError):
    pass


class LoopBreak(RuntimeError):
    pass


def create_client(settings: ProtocolSettings) -> VtvTcpClient | PlcLinkClient:
    if settings.transport == "plclink":
        return PlcLinkClient(settings)
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

    async def run(self, steps: list[SequenceStep]) -> None:
        await self.on_event({"type": "sequence_started"})
        try:
            await self._run_steps(steps)
        except SequenceStopped:
            await self.on_event(
                {"type": "sequence_stopped", "message": "ユーザーが停止しました"}
            )
            return
        await self.on_event({"type": "sequence_completed"})

    async def _run_steps(self, steps: list[SequenceStep]) -> None:
        for step in steps:
            self._check_stopped()
            self.step_number += 1
            current = self.step_number
            await self.on_event(
                {"type": "step_started", "index": current, "step": step.type}
            )
            if isinstance(step, CommandStep):
                await self._run_command(step, current)
            elif isinstance(step, DelayStep):
                await self._run_delay(step)
            elif isinstance(step, BreakStep):
                if self.loop_depth == 0:
                    raise ProtocolError(
                        "BREAKカードはループの中で使用してください"
                    )
                await self.on_event(
                    {"type": "loop_break", "index": current}
                )
                await self.on_event(
                    {"type": "step_completed", "index": current}
                )
                raise LoopBreak
            elif isinstance(step, IfStep):
                await self._run_if(step)
            elif isinstance(step, LoopStep):
                await self._run_loop(step)
            await self.on_event({"type": "step_completed", "index": current})

    async def _run_command(self, step: CommandStep, index: int) -> None:
        code = step.command.upper()
        if code not in self.catalog:
            raise ProtocolError(f"未定義のコマンドです: {code}")
        definition = self.catalog[code]
        transport = self.client.settings.transport

        if transport == "plclink":
            from .plc_link.commands import format_plclink_display, resolve_spec

            spec = resolve_spec(code)
            display = format_plclink_display(spec, step.arguments)
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
            )

        self.last_result = result
        for response in result.responses:
            await self.on_event(
                {"type": "rx", "index": index, "response": response}
            )
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
            {"type": "condition", "matched": matched, "actual": actual}
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
