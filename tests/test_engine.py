import asyncio

import pytest

from backend.engine import SequenceEngine
from backend.models import BreakStep, CommandStep, LoopStep, ProtocolSettings
from backend.protocol import CommandResult, ProtocolError, VtvTcpClient


async def test_break_exits_nearest_loop() -> None:
    events: list[dict] = []

    async def collect(event: dict) -> None:
        events.append(event)

    client = VtvTcpClient(ProtocolSettings(host="127.0.0.1"))
    engine = SequenceEngine(client, collect, asyncio.Event())
    steps = [LoopStep(type="loop", count=10, steps=[BreakStep(type="break")])]

    await engine.run(steps)

    iterations = [event for event in events if event["type"] == "loop_iteration"]
    assert len(iterations) == 1
    assert any(event["type"] == "loop_break" for event in events)
    assert events[-1]["type"] == "sequence_completed"


async def test_break_outside_loop_is_rejected() -> None:
    async def discard(_event: dict) -> None:
        pass

    client = VtvTcpClient(ProtocolSettings(host="127.0.0.1"))
    engine = SequenceEngine(client, discard, asyncio.Event())

    with pytest.raises(ProtocolError, match="ループの中"):
        await engine.run([BreakStep(type="break")])


async def test_plclink_command_uses_shared_sequence_engine() -> None:
    events: list[dict] = []

    class FakePlcLinkClient:
        settings = ProtocolSettings(
            transport="plclink",
            host="0.0.0.0",
            port=5000,
        )

        async def send_command(
            self,
            command: str,
            expect_result: bool = False,
            result_mode: str = "single",
            *,
            tcp_code: str | None = None,
            arguments: dict | None = None,
        ) -> CommandResult:
            del expect_result, result_mode, arguments
            assert tcp_code == "RRA"
            return CommandResult(command, "AK", ["AK", "result=1"])

    async def collect(event: dict) -> None:
        events.append(event)

    engine = SequenceEngine(FakePlcLinkClient(), collect, asyncio.Event())
    await engine.run([CommandStep(type="command", command="RRA")])

    assert any(
        event["type"] == "tx" and event["display"] == "PLCLINK#9"
        for event in events
    )
    assert [event["response"] for event in events if event["type"] == "rx"] == [
        "AK",
        "result=1",
    ]
    assert events[-1]["type"] == "sequence_completed"
