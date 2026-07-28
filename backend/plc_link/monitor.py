from __future__ import annotations

from typing import Any

from ..models import MemoryWatchItem, ProtocolSettings
from .commands import ByteOrder, words_to_dword
from .memory import DeviceMemory

INVALID_DWORD = -(2**31)
NOTIFY_AREA_WORDS = 8


def build_mapped_watch_items(settings: ProtocolSettings) -> list[MemoryWatchItem]:
    """接続設定からコマンド／レスポンス／結果データ／PLO の監視一覧を生成する。"""
    command = settings.command_address
    response = settings.response_address
    items = [
        MemoryWatchItem(
            id="cmd-trigger",
            label="トリガ",
            group="コマンド領域",
            device="D",
            address=command,
            format="int32",
        ),
        MemoryWatchItem(
            id="cmd-code",
            label="コマンドコード",
            group="コマンド領域",
            device="D",
            address=command + 2,
            format="int32",
        ),
        MemoryWatchItem(
            id="rsp-result",
            label="実行結果",
            group="レスポンス領域",
            device="D",
            address=response,
            format="int32",
        ),
        MemoryWatchItem(
            id="rsp-error",
            label="エラーコード",
            group="レスポンス領域",
            device="D",
            address=response + 2,
            format="int32",
        ),
        MemoryWatchItem(
            id="rsp-echo",
            label="コマンドエコー",
            group="レスポンス領域",
            device="D",
            address=response + 4,
            format="int32",
        ),
        MemoryWatchItem(
            id="rsp-param-size",
            label="パラメータ総サイズ",
            group="レスポンス領域",
            device="D",
            address=response + 6,
            format="int32",
        ),
    ]
    # 結果データ領域は監視用に常時マッピング（有効フラグは VTV 設定整合／重複検証用）
    watch_words = min(settings.result_data_size, settings.result_data_watch_words)
    watch_words -= watch_words % 2
    for offset in range(0, watch_words, 2):
        address = settings.result_data_address + offset
        items.append(
            MemoryWatchItem(
                id=f"result-data-{offset}",
                label=f"+{offset:04d}",
                group="結果データ",
                device="D",
                address=address,
                format="int32",
            )
        )
    if settings.notify_area_enabled:
        notify = settings.notify_address
        items.extend(
            [
                MemoryWatchItem(
                    id="notify-status",
                    label="書込ステータス",
                    group="結果通知エリア",
                    device="D",
                    address=notify,
                    format="int32",
                ),
                MemoryWatchItem(
                    id="notify-error",
                    label="エラーコード",
                    group="結果通知エリア",
                    device="D",
                    address=notify + 2,
                    format="int32",
                ),
                MemoryWatchItem(
                    id="notify-data-address",
                    label="結果データ先頭",
                    group="結果通知エリア",
                    device="D",
                    address=notify + 4,
                    format="int32",
                ),
                MemoryWatchItem(
                    id="notify-data-size",
                    label="結果データサイズ",
                    group="結果通知エリア",
                    device="D",
                    address=notify + 6,
                    format="int32",
                ),
            ]
        )
    for port in range(1, settings.plo_port_count + 1):
        address = settings.plo_address + port - 1
        label = f"Port {port}"
        if port == settings.busy_port:
            label = f"BUSY (Port {port})"
        items.append(
            MemoryWatchItem(
                id=f"plo-port-{port}",
                label=label,
                group="PLO出力",
                device="M",
                address=address,
                format="bit",
            )
        )
    return items


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
