"""高速監視ストリーム（WebSocket）。HTTP ポールより低遅延を狙う。"""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, Literal

from .bit_edges import BitEdge
from .models import MemoryWatchItem

TransportName = Literal["plclink", "field_network"]


@contextmanager
def windows_1ms_timer():
    """Windows のタイマ分解能を 1 ms に上げる（既定 ~15.6 ms を回避）。"""
    if sys.platform != "win32":
        yield
        return
    try:
        import ctypes

        winmm = ctypes.WinDLL("winmm")
        winmm.timeBeginPeriod(1)
    except Exception:
        yield
        return
    try:
        yield
    finally:
        try:
            winmm.timeEndPeriod(1)
        except Exception:
            pass


async def precise_delay(seconds: float) -> None:
    """可能な範囲で目標間隔に近づける（イベントループは塞がない）。"""
    if seconds <= 0:
        await asyncio.sleep(0)
        return
    deadline = time.perf_counter() + seconds
    while True:
        remaining = deadline - time.perf_counter()
        if remaining <= 0:
            return
        if remaining > 0.0015:
            await asyncio.sleep(remaining - 0.0008)
        else:
            # timeBeginPeriod(1) 後の短い yield
            await asyncio.sleep(0)


def compact_values(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"id": row["id"], "value": row["value"], "valid": row.get("valid", True)}
        for row in rows
    ]


def format_bit_edges(
    edges: list[BitEdge],
    items: list[MemoryWatchItem],
) -> list[dict[str, Any]]:
    """エッジを監視項目 id と mono_ms（sample と同じ軸）に変換する。"""
    index: dict[tuple[str, int], list[str]] = {}
    for item in items:
        if item.format != "bit":
            continue
        if item.device not in {"M", "IN", "OUT"}:
            continue
        index.setdefault((item.device, item.address), []).append(item.id)
    payload: list[dict[str, Any]] = []
    for edge in sorted(edges, key=lambda item: (item.mono_s, item.seq)):
        for item_id in index.get((edge.device, edge.address), ()):
            payload.append(
                {
                    "id": item_id,
                    "value": edge.value,
                    "valid": True,
                    "mono_ms": edge.mono_s * 1000.0,
                }
            )
    return payload


def diff_values(
    previous: dict[str, tuple[Any, bool]],
    current: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, tuple[Any, bool]], bool]:
    """変化分だけ返す。初回や強制時は full=True。"""
    changed: list[dict[str, Any]] = []
    next_map: dict[str, tuple[Any, bool]] = {}
    for row in current:
        key = row["id"]
        valid = bool(row.get("valid", True))
        value = row["value"]
        next_map[key] = (value, valid)
        prev = previous.get(key)
        if prev is None or prev[0] != value or prev[1] != valid:
            changed.append({"id": key, "value": value, "valid": valid})
    return changed, next_map, False


async def run_watch_loop(
    *,
    transport: TransportName,
    items: list[MemoryWatchItem],
    interval_ms: float,
    read_once: Callable[[], list[dict[str, Any]]],
    send_json: Callable[[dict[str, Any]], Any],
    should_stop: Callable[[], bool],
    take_edges: Callable[[], list[dict[str, Any]]] | None = None,
) -> None:
    """監視ループ。send_json は awaitable でも同期でも可。"""
    interval_s = max(0.0005, float(interval_ms) / 1000.0)
    previous: dict[str, tuple[Any, bool]] = {}
    tick = 0
    full_every = max(20, int(1000 / max(1, interval_ms)))  # 約1秒に1回フル

    with windows_1ms_timer():
        next_deadline = time.perf_counter()
        while not should_stop():
            loop_started = time.perf_counter()
            try:
                # スナップショットより先にエッジを抜く。同じループ上の書込みは
                # await するまで入らないので、このサンプルより新しいエッジは次周へ回る。
                edge_rows = list(take_edges()) if take_edges is not None else []
                rows = compact_values(read_once())
            except Exception as exc:  # noqa: BLE001 - 監視継続のため捕捉
                payload = {"type": "error", "message": str(exc)}
                result = send_json(payload)
                if asyncio.iscoroutine(result):
                    await result
                break

            tick += 1
            force_full = tick == 1 or tick % full_every == 0 or not previous
            if force_full:
                previous = {
                    row["id"]: (row["value"], bool(row.get("valid", True)))
                    for row in rows
                }
                values = rows
                is_full = True
            else:
                values, previous, _ = diff_values(previous, rows)
                is_full = False

            # 変化がなくても毎周期送る（実測周期・タイミングチャートの時間軸を維持）
            # t: 壁時計, mono_ms: 単調時計（クライアント横軸は mono_ms を優先）
            now_perf = time.perf_counter()
            mono_ms = now_perf * 1000.0
            if edge_rows:
                newest_edge = max(float(edge["mono_ms"]) for edge in edge_rows)
                if newest_edge > mono_ms:
                    mono_ms = newest_edge
            payload = {
                "type": "sample",
                "t": time.time() * 1000.0,
                "mono_ms": mono_ms,
                "dt_ms": (now_perf - loop_started) * 1000.0,
                "full": is_full,
                "values": values,
                "edges": edge_rows,
            }
            result = send_json(payload)
            if asyncio.iscoroutine(result):
                await result

            next_deadline += interval_s
            delay = next_deadline - time.perf_counter()
            if delay < -interval_s:
                # 大きく遅延したらリスケジュール
                next_deadline = time.perf_counter()
                delay = 0
            if should_stop():
                break
            await precise_delay(delay)
