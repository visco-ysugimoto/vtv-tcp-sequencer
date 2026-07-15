import asyncio

import pytest

from backend.engine import SequenceEngine
from backend.models import BreakStep, LoopStep, ProtocolSettings
from backend.protocol import ProtocolError, VtvTcpClient


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
