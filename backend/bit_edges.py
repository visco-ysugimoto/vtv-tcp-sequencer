"""ビット変化の時刻記録。

監視ポールの周期ではなく、値が変わった瞬間の単調時計を残す。
Field Network では min_interval_s（RPI）未満の間隔を切り上げ、
RPI より短い幅を出さない。
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

_mono_override: ContextVar[float | None] = ContextVar("bit_edge_mono", default=None)


def resolve_mono(explicit: float | None = None) -> float:
    """エッジ時刻。明示値、フレーム時刻、なければ現在の perf_counter。"""
    if explicit is not None:
        return float(explicit)
    stamped = _mono_override.get()
    if stamped is not None:
        return stamped
    return time.perf_counter()


@contextmanager
def stamp_bit_edges(mono_s: float) -> Iterator[None]:
    """この区間のビット書込みを、同じ単調時刻として記録する。"""
    token = _mono_override.set(float(mono_s))
    try:
        yield
    finally:
        _mono_override.reset(token)


@dataclass(frozen=True, slots=True)
class BitEdge:
    seq: int
    device: str
    address: int
    value: int
    mono_s: float


class BitEdgeLog:
    """監視対象ビットの変化だけをリングに積む。"""

    def __init__(self, *, maxlen: int = 16384) -> None:
        self._lock = threading.RLock()
        self._edges: deque[BitEdge] = deque(maxlen=maxlen)
        self._seq = 0
        self._watched: set[tuple[str, int]] = set()
        self._last_mono: dict[tuple[str, int], float] = {}
        self.min_interval_s = 0.0

    def arm(self, keys: Iterable[tuple[str, int]]) -> int:
        """監視対象を入れ替え、これ以降のエッジだけを返すカーソルを返す。"""
        with self._lock:
            self._watched = {(str(device), int(address)) for device, address in keys}
            self._edges.clear()
            self._last_mono.clear()
            return self._seq

    def disarm(self) -> None:
        self.arm(())

    def watched_keys(self) -> set[tuple[str, int]]:
        with self._lock:
            return set(self._watched)

    def record(self, device: str, address: int, value: int, mono_s: float) -> None:
        key = (str(device), int(address))
        bit = 1 if int(value) else 0
        with self._lock:
            if key not in self._watched:
                return
            interval = self.min_interval_s
            if interval > 0.0:
                last = self._last_mono.get(key)
                if last is not None and mono_s < last + interval:
                    mono_s = last + interval
            self._last_mono[key] = mono_s
            self._seq += 1
            self._edges.append(
                BitEdge(
                    seq=self._seq,
                    device=key[0],
                    address=key[1],
                    value=bit,
                    mono_s=mono_s,
                )
            )

    def take(self, after_seq: int) -> tuple[int, list[BitEdge]]:
        """after_seq より新しいエッジと、次回用カーソルを返す。"""
        with self._lock:
            found = [edge for edge in self._edges if edge.seq > after_seq]
            return self._seq, found
