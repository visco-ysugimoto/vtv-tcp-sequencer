from __future__ import annotations

import asyncio

from backend.watch_stream import compact_values, diff_values, precise_delay


def test_compact_and_diff_values() -> None:
    rows = [
        {"id": "a", "value": 1, "valid": True, "device": "M"},
        {"id": "b", "value": 0, "valid": True, "device": "M"},
    ]
    compact = compact_values(rows)
    assert compact == [
        {"id": "a", "value": 1, "valid": True},
        {"id": "b", "value": 0, "valid": True},
    ]
    changed, previous, _ = diff_values({}, compact)
    assert len(changed) == 2
    changed2, previous2, _ = diff_values(previous, compact)
    assert changed2 == []
    updated = [{"id": "a", "value": 0, "valid": True}, {"id": "b", "value": 0, "valid": True}]
    changed3, _, _ = diff_values(previous2, updated)
    assert changed3 == [{"id": "a", "value": 0, "valid": True}]


def test_precise_delay_roughly_honors_interval() -> None:
    async def _run() -> float:
        started = asyncio.get_running_loop().time()
        await precise_delay(0.005)
        return asyncio.get_running_loop().time() - started

    elapsed = asyncio.run(_run())
    assert 0.003 <= elapsed <= 0.05


def test_watch_loop_sends_heartbeat_when_unchanged() -> None:
    from backend.models import MemoryWatchItem
    from backend.watch_stream import run_watch_loop

    items = [MemoryWatchItem(id="a", device="M", address=0, format="bit")]
    sent: list[dict] = []

    def read_once():
        return [{"id": "a", "value": 1, "valid": True}]

    async def send_json(payload: dict) -> None:
        sent.append(payload)
        if len(sent) >= 3:
            stop["flag"] = True

    stop = {"flag": False}

    async def _run() -> None:
        await run_watch_loop(
            transport="plclink",
            items=items,
            interval_ms=1,
            read_once=read_once,
            send_json=send_json,
            should_stop=lambda: stop["flag"],
        )

    asyncio.run(_run())
    assert len(sent) >= 3
    assert sent[0]["full"] is True
    assert sent[1]["full"] is False
    assert sent[1]["values"] == []  # 変化なしでも送る
    assert isinstance(sent[0]["t"], (int, float))
    assert isinstance(sent[0]["mono_ms"], (int, float))
    assert sent[1]["mono_ms"] >= sent[0]["mono_ms"]
