from __future__ import annotations

from pathlib import Path

import pytest

from backend.field_network.eds import parse_eds_file, parse_eds_text
from backend.field_network.layout import (
    build_layout,
    resolve_status_signal_bit,
    validate_layout_against_sizes,
)
from backend.field_network.monitor import build_mapped_watch_items, read_assembly_items
from backend.models import ProtocolSettings, StatusSignalMapping, default_fn_status_signals
from backend.protocol import ProtocolError

DOCS = Path(__file__).resolve().parents[1] / "docs" / "field_network"


def test_parse_variable_eds() -> None:
    info = parse_eds_file(DOCS / "VTV-9000.eds")
    assert info.input_size == 612
    assert info.output_size == 132
    assert info.rpi_us == 10_000
    assert "2C 14" in info.connection_path
    assert "2C 0A" in info.connection_path
    assert info.o_to_t_header_bytes == 4


def test_parse_fixed_eds() -> None:
    info = parse_eds_file(
        DOCS / "VTV-9000 Field Network (Normal) In240Out002Word.eds"
    )
    assert info.input_size == 480
    assert info.output_size == 4
    assert info.warnings  # コマンド領域を含められない可能性


def test_layout_matches_variable_eds_defaults() -> None:
    layout = build_layout(
        esi_ports=0,
        eso_ports=0,
        command_words=64,
        response_words=64,
        result_words=240,
    )
    assert layout.input_bytes == 612
    assert layout.output_bytes == 132
    assert layout.command_word == 2
    assert layout.response_word == 242
    validate_layout_against_sizes(layout, input_bytes=612, output_bytes=132)


def test_layout_with_esi_eso() -> None:
    layout = build_layout(
        esi_ports=128,
        eso_ports=128,
        command_words=64,
        response_words=64,
        result_words=238,
    )
    # status2 + eso8 + result238 + response64 = 312 words = 624
    assert layout.input_bytes == 624
    # reserved2 + esi8 + command64 = 74 words = 148
    assert layout.output_bytes == 148
    assert layout.command_word == 10
    assert layout.response_word == 248


def test_layout_mismatch_raises() -> None:
    layout = build_layout(
        esi_ports=0,
        eso_ports=0,
        command_words=64,
        response_words=64,
        result_words=240,
    )
    with pytest.raises(ProtocolError, match="入力アセンブリ"):
        validate_layout_against_sizes(layout, input_bytes=480, output_bytes=132)


def test_field_network_settings_defaults() -> None:
    settings = ProtocolSettings(
        transport="field_network",
        host="192.168.0.10",
    )
    assert settings.port == 44818
    assert settings.fn_input_size == 612
    assert settings.fn_output_size == 136
    assert settings.fn_esi_ports == 32
    assert settings.fn_eso_ports == 32
    assert settings.result_data_size == 238


def test_suggest_layout_matches_vtv_screenshot_totals() -> None:
    from backend.field_network.layout import suggest_layout_from_sizes

    suggested = suggest_layout_from_sizes(input_bytes=612, output_bytes=136)
    assert suggested["fn_esi_ports"] == 32
    assert suggested["fn_eso_ports"] == 32
    assert suggested["command_size"] == 64
    assert suggested["response_size"] == 64
    assert suggested["result_data_size"] == 238


def test_field_network_settings_reject_mismatch() -> None:
    with pytest.raises(ValueError, match="一致しません"):
        ProtocolSettings(
            transport="field_network",
            host="192.168.0.10",
            result_data_size=2048,
            fn_input_size=612,
            fn_output_size=136,
            fn_esi_ports=32,
            fn_eso_ports=32,
        )


def test_watch_items_and_read() -> None:
    # eso 32 + result 240 → input 616。612 のままでは不一致
    with pytest.raises(ValueError):
        ProtocolSettings(
            transport="field_network",
            host="192.168.0.10",
            fn_esi_ports=32,
            fn_eso_ports=32,
            result_data_size=240,
            fn_input_size=612,
            fn_output_size=136,
        )

    settings = ProtocolSettings(
        transport="field_network",
        host="192.168.0.10",
        fn_esi_ports=32,
        fn_eso_ports=32,
        result_data_size=240,
        result_data_watch_words=4,
        command_size=64,
        response_size=64,
        fn_input_size=616,
        fn_output_size=136,
    )
    items = build_mapped_watch_items(settings)
    assert any(item.id == "fn-status-busy" for item in items)
    assert any(item.group == "ESO出力 (Assem10)" for item in items)
    assert any(item.group == "コマンド領域 (Assem20)" for item in items)
    assert any(item.id.startswith("result-data-") for item in items)
    # 結果データを先頭側に置き、VTV モニタと同じ相対オフセットで見えるようにする
    result_ids = [i.id for i in items if i.id.startswith("result-data-")]
    assert result_ids[0] == "result-data-0"
    assert items.index(next(i for i in items if i.id == "result-data-0")) < items.index(
        next(i for i in items if i.id == "cmd-trigger")
    )

    input_data = bytearray(616)
    output_data = bytearray(132)
    input_data[0] = 0x02  # BUSY
    # command area at word 2 (eso=2 words → command still at word 2? 
    # status2 + eso2 = command at word 4 for output; response at 2+2+240=244
    # write response result=1 at word 244
    rsp = 2 + 2 + 240
    pos = rsp * 2
    input_data[pos] = 1
    input_data[pos + 1] = 0
    input_data[pos + 2] = 0
    input_data[pos + 3] = 0

    values = {
        item["id"]: item
        for item in read_assembly_items(
            bytes(input_data),
            bytes(output_data),
            items,
            encoding="cp932",
            byte_order="high_low",
        )
    }
    assert values["fn-status-busy"]["value"] == 1
    assert values["rsp-result"]["value"] == 1


def test_default_status_signals() -> None:
    settings = ProtocolSettings(transport="field_network", host="192.168.0.10")
    signals = settings.fn_status_signals
    assert len(signals) == 4
    assert settings.find_status_signal(role="busy") is not None
    assert settings.find_status_signal(role="busy").bit == 1
    layout = build_layout(
        esi_ports=32,
        eso_ports=32,
        command_words=64,
        response_words=64,
        result_words=238,
    )
    busy = settings.find_status_signal(role="busy")
    assert resolve_status_signal_bit(busy, layout) == 1


def test_status_signal_busy_on_eso() -> None:
    signals = default_fn_status_signals()
    for item in signals:
        if item.role == "busy":
            item.source = "eso"
            item.bit = None
            item.eso_port = 3
    settings = ProtocolSettings(
        transport="field_network",
        host="192.168.0.10",
        fn_status_signals=signals,
    )
    layout = build_layout(
        esi_ports=32,
        eso_ports=32,
        command_words=64,
        response_words=64,
        result_words=238,
    )
    busy = settings.find_status_signal(role="busy")
    # eso_byte=4 → bit = 32 + (3-1) = 34
    assert resolve_status_signal_bit(busy, layout) == 34
    items = build_mapped_watch_items(settings)
    busy_item = next(item for item in items if item.id == "fn-status-busy")
    assert busy_item.address == 34
    assert busy_item.label == "BUSY"

    input_data = bytearray(612)
    # set ESO-3: byte 4, bit 2
    input_data[4] = 1 << 2
    values = {
        item["id"]: item
        for item in read_assembly_items(
            bytes(input_data),
            bytes(136),
            [busy_item],
            encoding="cp932",
            byte_order="high_low",
        )
    }
    assert values["fn-status-busy"]["value"] == 1


def test_status_signals_require_single_busy() -> None:
    signals = [
        StatusSignalMapping(
            id="a", label="A", source="status", bit=0, role="none"
        ),
        StatusSignalMapping(
            id="b", label="B", source="status", bit=1, role="none"
        ),
    ]
    with pytest.raises(ValueError, match="busy"):
        ProtocolSettings(
            transport="field_network",
            host="192.168.0.10",
            fn_status_signals=signals,
        )


def test_parse_eds_text_minimal() -> None:
    text = """
[Device]
        ProdName = "Demo";
[Params]
        Param1 =
                0,,,
                0x0000,0xC7,2,
                "Input Size","Bytes","Input Size",
                4,100,20,
                ,,,,
                ,,,,
                ;
        Param2 =
                0,,,
                0x0000,0xC7,2,
                "Output Size","Bytes","Output Size",
                4,100,10,
                ,,,,
                ,,,,
                ;
        Param4 =
                0,,,
                0x0000,0xC8,4,
                "RPI","","RPI",
                2000,1000000,5000,
                ,,,,
                ,,,,
                ;
[Assembly]
        Assem10 = "input",,20,0x0000,,,160,Param3;
        Assem20 = "output",,10,0x0000,,,80,Param3;
[Connection Manager]
        Connection1 =
                0x04010002,
                0x44640405,
                Param4,Param2,Assem20,
                Param4,Param1,Assem10,
                ,,
                ,,
                "conn","",
                "20 04 24 01 2C 14 2C 0A";
"""
    info = parse_eds_text(text, source_name="demo.eds")
    assert info.input_size == 20
    assert info.output_size == 10
    assert info.rpi_us == 5000
