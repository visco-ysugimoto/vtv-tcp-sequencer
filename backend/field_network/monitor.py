"""Field Network アセンブリ監視。"""

from __future__ import annotations

from typing import Any, Literal

from ..models import MemoryWatchItem, ProtocolSettings
from ..plc_link.commands import ByteOrder, words_to_dword
from .layout import (
    AssemblyLayout,
    build_layout,
    resolve_status_signal_bit,
)

INVALID_DWORD = -(2**31)

WatchDevice = Literal["D", "M", "IN", "OUT"]


def build_field_network_layout(settings: ProtocolSettings) -> AssemblyLayout:
    return build_layout(
        esi_ports=settings.fn_esi_ports,
        eso_ports=settings.fn_eso_ports,
        command_words=settings.command_size,
        response_words=settings.response_size,
        result_words=settings.result_data_size,
    )


def build_mapped_watch_items(settings: ProtocolSettings) -> list[MemoryWatchItem]:
    """接続設定からアセンブリ監視一覧を生成する。

    表示順は VTV 結果データモニタを優先（結果データ → レスポンス → コマンド）。
    """
    layout = build_field_network_layout(settings)
    cmd = layout.command_word
    rsp = layout.response_word
    result_base = layout.result_word
    items: list[MemoryWatchItem] = []
    for signal in settings.fn_status_signals:
        bit = resolve_status_signal_bit(signal, layout)
        items.append(
            MemoryWatchItem(
                id=f"fn-status-{signal.id}",
                label=signal.label,
                group="ステータス",
                device="IN",
                address=bit,
                format="bit",
            )
        )

    # 結果データ（VTV「結果データ出力モニタ」の相対アドレス）
    watch_words = min(settings.result_data_size, settings.result_data_watch_words)
    watch_words -= watch_words % 2
    for offset in range(0, watch_words, 2):
        items.append(
            MemoryWatchItem(
                id=f"result-data-{offset}",
                label=f"+{offset:05d}",
                group="結果データ (Assem10)",
                device="IN",
                address=result_base + offset,
                format="int32",
                decimals=settings.result_data_decimals,
            )
        )

    items.extend(
        [
            MemoryWatchItem(
                id="rsp-result",
                label="実行結果 (+0000)",
                group="レスポンス領域 (Assem10)",
                device="IN",
                address=rsp,
                format="int32",
            ),
            MemoryWatchItem(
                id="rsp-error",
                label="エラーコード (+0002)",
                group="レスポンス領域 (Assem10)",
                device="IN",
                address=rsp + 2,
                format="int32",
            ),
            MemoryWatchItem(
                id="rsp-echo",
                label="コマンドエコー (+0004)",
                group="レスポンス領域 (Assem10)",
                device="IN",
                address=rsp + 4,
                format="int32",
            ),
            MemoryWatchItem(
                id="rsp-param-size",
                label="パラメータ総サイズ (+0006)",
                group="レスポンス領域 (Assem10)",
                device="IN",
                address=rsp + 6,
                format="int32",
            ),
            MemoryWatchItem(
                id="cmd-trigger",
                label="トリガ (+0000)",
                group="コマンド領域 (Assem20)",
                device="OUT",
                address=cmd,
                format="int32",
            ),
            MemoryWatchItem(
                id="cmd-code",
                label="コマンドコード (+0002)",
                group="コマンド領域 (Assem20)",
                device="OUT",
                address=cmd + 2,
                format="int32",
            ),
        ]
    )

    for port in range(1, settings.fn_eso_ports + 1):
        bit = layout.eso_byte * 8 + (port - 1)
        items.append(
            MemoryWatchItem(
                id=f"eso-port-{port}",
                label=f"ESO-{port}",
                group="ESO出力 (Assem10)",
                device="IN",
                address=bit,
                format="bit",
            )
        )

    for port in range(1, min(settings.fn_esi_ports, 32) + 1):
        bit = layout.esi_byte * 8 + (port - 1)
        items.append(
            MemoryWatchItem(
                id=f"esi-port-{port}",
                label=f"ESI-{port}",
                group="ESI入力 (Assem20)",
                device="OUT",
                address=bit,
                format="bit",
            )
        )
    return items


def read_assembly_items(
    input_data: bytes,
    output_data: bytes,
    items: list[MemoryWatchItem],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> list[dict[str, Any]]:
    return [
        _read_item(
            input_data,
            output_data,
            item,
            encoding=encoding,
            byte_order=byte_order,
        )
        for item in items
    ]


def _read_item(
    input_data: bytes,
    output_data: bytes,
    item: MemoryWatchItem,
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> dict[str, Any]:
    buf = input_data if item.device == "IN" else output_data
    valid = True
    value: Any
    if item.format == "bit":
        byte_index = item.address // 8
        if byte_index < 0 or byte_index >= len(buf):
            value = None
            valid = False
        else:
            value = 1 if buf[byte_index] & (1 << (item.address % 8)) else 0
    elif item.format == "word":
        words = _read_words(buf, item.address, 1)
        value = words[0] if words is not None else None
        valid = words is not None
    elif item.format in {"int32", "fixed"}:
        words = _read_words(buf, item.address, 2)
        if words is None:
            value = None
            valid = False
        else:
            raw = words_to_dword(words)
            valid = raw != INVALID_DWORD
            if not valid:
                value = None
            elif item.format == "fixed":
                value = raw / (10**item.decimals)
            else:
                value = raw
    else:
        words = _read_words(buf, item.address, item.length)
        if words is None:
            value = None
            valid = False
        else:
            value = _decode_string(words, encoding=encoding, byte_order=byte_order)

    return {
        "id": item.id,
        "device": item.device,
        "address": item.address,
        "format": item.format,
        "value": value,
        "valid": valid,
    }


def _read_words(buf: bytes, word_index: int, count: int) -> list[int] | None:
    start = word_index * 2
    end = start + count * 2
    if start < 0 or end > len(buf):
        return None
    words: list[int] = []
    for offset in range(start, end, 2):
        words.append(buf[offset] | (buf[offset + 1] << 8))
    return words


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
