from __future__ import annotations

from typing import Any

from ..models import MemoryWatchItem
from .commands import ByteOrder, words_to_dword
from .memory import DeviceMemory

INVALID_DWORD = -(2**31)


def read_memory_items(
    memory: DeviceMemory,
    items: list[MemoryWatchItem],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> list[dict[str, Any]]:
    """監視定義に従って SoftPLC メモリの現在値を読み取る。"""
    return [
        _read_memory_item(
            memory,
            item,
            encoding=encoding,
            byte_order=byte_order,
        )
        for item in items
    ]


def _read_memory_item(
    memory: DeviceMemory,
    item: MemoryWatchItem,
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> dict[str, Any]:
    valid = True
    if item.format == "bit":
        value: Any = memory.get_bit(item.address)
    elif item.format == "word":
        value = memory.read_words(item.address, 1)[0]
    elif item.format in {"int32", "fixed"}:
        raw = words_to_dword(memory.read_words(item.address, 2))
        valid = raw != INVALID_DWORD
        if not valid:
            value = None
        elif item.format == "fixed":
            value = raw / (10**item.decimals)
        else:
            value = raw
    else:
        words = memory.read_words(item.address, item.length)
        value = _decode_string(words, encoding=encoding, byte_order=byte_order)

    return {
        "id": item.id,
        "device": item.device,
        "address": item.address,
        "format": item.format,
        "value": value,
        "valid": valid,
    }


def _decode_string(
    words: list[int],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> str:
    raw = bytearray()
    for word in words:
        high = (word >> 8) & 0xFF
        low = word & 0xFF
        if byte_order == "high_low":
            raw.extend((high, low))
        else:
            raw.extend((low, high))
    terminator = raw.find(0)
    if terminator >= 0:
        del raw[terminator:]
    return raw.decode(encoding, errors="replace")
