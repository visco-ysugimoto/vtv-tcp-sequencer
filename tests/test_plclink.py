from __future__ import annotations

import asyncio

import pytest

from backend.models import MemoryWatchItem, ProtocolSettings
from backend.plc_link import PlcLinkClient, mc3e
from backend.plc_link.commands import (
    COMMAND_SPECS,
    DOCUMENTED_COMMAND_CODES,
    build_command_words,
    command_metadata,
    dword_to_words,
    pack_string,
    resolve_spec,
)
from backend.plc_link.memory import DeviceMemory
from backend.plc_link.monitor import build_mapped_watch_items, read_memory_items
from backend.plc_link.server import SoftPlcServer
from backend.protocol import ProtocolError


def test_memory_dword_round_trip() -> None:
    memory = DeviceMemory()
    memory.write_dword(100, 0x12345678)
    assert memory.read_words(100, 2) == [0x5678, 0x1234]
    assert memory.read_dword(100) == 0x12345678


def test_pack_string_high_low() -> None:
    words = pack_string("ABC", encoding="cp932", byte_order="high_low")
    assert words == [0x4142, 0x4300]


def test_build_command_words_active_task_run() -> None:
    spec = resolve_spec("RRA")
    words = build_command_words(
        spec,
        {},
        encoding="cp932",
        byte_order="high_low",
        area_size=16,
    )
    assert words[0:4] == [0, 0, 9, 0]


def test_plclink_command_metadata() -> None:
    meta = command_metadata("RRA")
    assert meta["plclink_supported"] is True
    assert meta["plclink_code"] == 9
    assert meta["plclink_reason"] is None
    assert meta["field_network_supported"] is True
    assert meta["field_network_code"] == 9
    assert command_metadata("POA")["plclink_supported"] is False
    assert command_metadata("PLI")["plclink_supported"] is True
    assert command_metadata("PLI")["field_network_supported"] is False
    assert command_metadata("ESI")["field_network_supported"] is True


def test_busy_address_from_plo_port() -> None:
    settings = ProtocolSettings(
        transport="plclink",
        host="0.0.0.0",
        plo_address=1024,
        busy_port=5,
    )
    assert settings.busy_port == 5
    assert settings.busy_address == 1028
    assert settings.plclink_status_signals[0].plo_port == 5


def test_plclink_status_signals_drive_busy_and_watch() -> None:
    from backend.models import StatusSignalMapping

    settings = ProtocolSettings(
        transport="plclink",
        host="0.0.0.0",
        plo_address=1024,
        plo_port_count=16,
        plclink_status_signals=[
            StatusSignalMapping(
                id="auto", label="自動運転中", source="plo", plo_port=3, role="auto"
            ),
            StatusSignalMapping(
                id="busy", label="BUSY", source="plo", plo_port=7, role="busy"
            ),
            StatusSignalMapping(
                id="error", label="エラー", source="plo", plo_port=4, role="error"
            ),
        ],
    )
    assert settings.busy_port == 7
    assert settings.busy_address == 1030
    items = build_mapped_watch_items(settings)
    assert [item for item in items if item.group == "ステータス"] == []
    plo = [item for item in items if item.group == "PLO出力"]
    assert len(plo) == 16
    by_id = {item.id: item for item in plo}
    assert by_id["plo-port-3"].label == "自動運転中 (Port 3)"
    assert by_id["plo-port-7"].label == "BUSY (Port 7)"
    assert by_id["plo-port-4"].label == "エラー (Port 4)"
    assert by_id["plo-port-1"].label == "Port 1"


def test_plo_port_names_override_watch_labels() -> None:
    from backend.models import StatusSignalMapping

    settings = ProtocolSettings(
        transport="plclink",
        host="0.0.0.0",
        plo_address=1024,
        plo_port_count=4,
        plo_port_names={"1": "準備完了", "2": "  "},
        pli_port_names={"1": "起動要求"},
        plclink_status_signals=[
            StatusSignalMapping(
                id="busy", label="BUSY", source="plo", plo_port=1, role="busy"
            ),
        ],
    )
    assert settings.plo_port_names == {"1": "準備完了"}
    assert settings.pli_port_names == {"1": "起動要求"}
    items = build_mapped_watch_items(settings)
    by_id = {item.id: item for item in items}
    assert by_id["plo-port-1"].label == "Port 1: 準備完了"
    assert by_id["plo-port-2"].label == "Port 2"
    assert by_id["pli-port-1"].label == "PLI-1: 起動要求"
    assert by_id["pli-port-1"].address == 0
    assert by_id["pli-port-2"].label == "PLI-2"


def test_build_mapped_watch_items() -> None:
    settings = ProtocolSettings(
        transport="plclink",
        host="0.0.0.0",
        command_address=4096,
        response_address=8192,
        pli_address=0,
        pli_port_count=4,
        plo_address=1024,
        plo_port_count=4,
        busy_port=2,
        result_data_enabled=False,
        result_data_address=512,
        result_data_size=8,
        result_data_watch_words=8,
        notify_area_enabled=True,
        notify_address=2560,
    )
    items = build_mapped_watch_items(settings)
    by_id = {item.id: item for item in items}

    assert by_id["cmd-trigger"].address == 4096
    assert by_id["cmd-code"].address == 4098
    assert by_id["rsp-result"].address == 8192
    assert by_id["rsp-error"].address == 8194
    assert by_id["rsp-echo"].address == 8196
    assert by_id["rsp-param-size"].address == 8198
    assert by_id["notify-status"].address == 2560
    assert by_id["notify-error"].address == 2562
    assert by_id["notify-data-address"].address == 2564
    assert by_id["notify-data-size"].address == 2566
    assert [item.id for item in items if item.group == "結果データ"] == [
        "result-data-0",
        "result-data-2",
        "result-data-4",
        "result-data-6",
    ]
    assert by_id["result-data-0"].address == 512
    assert [item.id for item in items if item.group == "ステータス"] == []
    assert [item.id for item in items if item.group == "PLI入力"] == [
        "pli-port-1",
        "pli-port-2",
        "pli-port-3",
        "pli-port-4",
    ]
    assert by_id["pli-port-1"].address == 0
    assert by_id["pli-port-1"].format == "bit"
    assert [item.id for item in items if item.group == "PLO出力"] == [
        "plo-port-1",
        "plo-port-2",
        "plo-port-3",
        "plo-port-4",
    ]
    assert by_id["plo-port-2"].label == "BUSY (Port 2)"
    assert by_id["plo-port-2"].address == 1025
    assert by_id["plo-port-2"].format == "bit"
    assert by_id["cmd-data-4"].address == 4100
    assert by_id["cmd-data-62"].address == 4158
    assert "cmd-data-64" not in by_id
    assert by_id["rsp-data-8"].address == 8200
    assert by_id["rsp-data-62"].address == 8254
    assert "rsp-data-6" not in by_id
    command_ids = [item.id for item in items if item.group == "コマンド領域"]
    assert command_ids[:3] == ["cmd-trigger", "cmd-code", "cmd-data-4"]
    response_ids = [item.id for item in items if item.group == "レスポンス領域"]
    assert response_ids[3:5] == ["rsp-param-size", "rsp-data-8"]


def test_command_response_watch_stops_at_area_size() -> None:
    settings = ProtocolSettings(
        transport="plclink",
        host="0.0.0.0",
        command_address=4096,
        command_size=16,
        response_address=8192,
        response_size=16,
        result_data_size=0,
        result_data_watch_words=0,
        plo_port_count=1,
    )
    items = build_mapped_watch_items(settings)
    by_id = {item.id: item for item in items}
    assert by_id["cmd-data-14"].address == 4110
    assert "cmd-data-16" not in by_id
    assert by_id["rsp-data-14"].address == 8206
    assert "rsp-data-16" not in by_id
    assert by_id["rsp-data-8"].label == "+0008"


def test_pli_and_plo_use_separate_bit_ranges() -> None:
    settings = ProtocolSettings(transport="plclink", host="0.0.0.0")
    assert settings.pli_address == 0
    assert settings.pli_port_count == 32
    assert settings.plo_address == 1024
    items = build_mapped_watch_items(settings)
    by_id = {item.id: item for item in items}
    assert by_id["pli-port-1"].address == 0
    assert by_id["pli-port-32"].address == 31
    assert by_id["plo-port-1"].address == 1024
    ids = [item.id for item in items]
    assert ids.index("plo-port-1") < ids.index("pli-port-1")
    with pytest.raises(ValueError, match="仮想入力\\(PLI\\)と仮想出力\\(PLO\\)"):
        ProtocolSettings(
            transport="plclink",
            host="0.0.0.0",
            pli_address=1024,
            pli_port_count=8,
            plo_address=1028,
            plo_port_count=8,
        )


def test_result_data_overlap_rejected() -> None:
    with pytest.raises(ValueError, match="コマンド領域と結果データ領域が重複"):
        ProtocolSettings(
            transport="plclink",
            host="0.0.0.0",
            command_address=4096,
            command_size=64,
            result_data_enabled=True,
            result_data_address=4100,
            result_data_size=16,
        )


def test_busy_address_migrates_from_legacy_field() -> None:
    settings = ProtocolSettings.model_validate(
        {
            "transport": "plclink",
            "host": "0.0.0.0",
            "busy_address": 1100,
        }
    )
    assert settings.plo_address == 1100
    assert settings.busy_port == 1
    assert settings.busy_address == 1100


def test_read_typed_memory_items() -> None:
    memory = DeviceMemory()
    memory.set_bit(10, 1)
    memory.write_words(20, [0xFFFF])
    memory.write_dword(30, -123)
    memory.write_dword(40, 12345)
    memory.write_words(
        50,
        pack_string("検査OK", encoding="cp932", byte_order="high_low"),
    )
    memory.write_dword(60, -(2**31))
    items = [
        MemoryWatchItem(id="bit", device="M", address=10, format="bit"),
        MemoryWatchItem(id="word", device="D", address=20, format="word"),
        MemoryWatchItem(id="int", device="D", address=30, format="int32"),
        MemoryWatchItem(
            id="fixed",
            device="D",
            address=40,
            format="fixed",
            decimals=3,
        ),
        MemoryWatchItem(
            id="text",
            device="D",
            address=50,
            format="string",
            length=8,
        ),
        MemoryWatchItem(id="invalid", device="D", address=60, format="int32"),
    ]

    snapshots = read_memory_items(
        memory,
        items,
        encoding="cp932",
        byte_order="high_low",
    )
    values = {item["id"]: item for item in snapshots}

    assert values["bit"]["value"] == 1
    assert values["word"]["value"] == 0xFFFF
    assert values["int"]["value"] == -123
    assert values["fixed"]["value"] == 12.345
    assert values["text"]["value"] == "検査OK"
    assert values["invalid"]["value"] is None
    assert values["invalid"]["valid"] is False


def test_mc3e_word_read_write_round_trip() -> None:
    memory = DeviceMemory()
    memory.write_words(10, [1, 2, 3])
    request = mc3e.build_request(
        command=mc3e.CMD_BATCH_READ,
        subcommand=mc3e.SUBCMD_WORD,
        device="D",
        head=10,
        points=3,
    )
    response = mc3e.handle_request(memory, request)
    assert response[0:2] == b"\xd0\x00"
    assert mc3e.decode_u16(response, 9) == 0
    data = response[11:]
    assert [mc3e.decode_i16(data, i * 2) for i in range(3)] == [1, 2, 3]

    write = mc3e.build_request(
        command=mc3e.CMD_BATCH_WRITE,
        subcommand=mc3e.SUBCMD_WORD,
        device="D",
        head=20,
        points=2,
        write_payload=mc3e.encode_i16(7) + mc3e.encode_i16(8),
    )
    response = mc3e.handle_request(memory, write)
    assert mc3e.decode_u16(response, 9) == 0
    assert memory.read_words(20, 2) == [7, 8]


def test_mc3e_bit_read_write_round_trip() -> None:
    memory = DeviceMemory()
    write = mc3e.build_request(
        command=mc3e.CMD_BATCH_WRITE,
        subcommand=mc3e.SUBCMD_BIT,
        device="M",
        head=100,
        points=3,
        write_payload=mc3e.pack_bits([1, 0, 1]),
    )
    assert mc3e.decode_u16(mc3e.handle_request(memory, write), 9) == 0
    assert memory.read_bits(100, 3) == [1, 0, 1]

    read = mc3e.build_request(
        command=mc3e.CMD_BATCH_READ,
        subcommand=mc3e.SUBCMD_BIT,
        device="M",
        head=100,
        points=3,
    )
    response = mc3e.handle_request(memory, read)
    bits = mc3e.unpack_bits(response[11:], 3)
    assert bits == [1, 0, 1]


def test_mc3e_out_of_range_expands_memory() -> None:
    memory = DeviceMemory(d_size=100)
    request = mc3e.build_request(
        command=mc3e.CMD_BATCH_READ,
        subcommand=mc3e.SUBCMD_WORD,
        device="D",
        head=200,
        points=2,
    )

    response = mc3e.handle_request(memory, request)

    assert response[0:2] == b"\xd0\x00"
    assert mc3e.decode_u16(response, 9) == 0
    assert memory.read_words(200, 2) == [0, 0]


def test_mc3e_high_bit_word_read_does_not_crash() -> None:
    """自動運転移行時のメモリチェックで 0x8000/0xFFFF が読まれても応答する。"""
    memory = DeviceMemory()
    memory.write_words(10, [0xFFFF, 0x8000, 0x7FFF])
    request = mc3e.build_request(
        command=mc3e.CMD_BATCH_READ,
        subcommand=mc3e.SUBCMD_WORD,
        device="D",
        head=10,
        points=3,
    )
    response = mc3e.handle_request(memory, request)
    assert mc3e.decode_u16(response, 9) == 0
    data = response[11:]
    assert [mc3e.decode_u16(data, i * 2) for i in range(3)] == [0xFFFF, 0x8000, 0x7FFF]


def test_mc3e_m_word_read_write_round_trip() -> None:
    memory = DeviceMemory()
    write = mc3e.build_request(
        command=mc3e.CMD_BATCH_WRITE,
        subcommand=mc3e.SUBCMD_WORD,
        device="M",
        head=1024,
        points=1,
        write_payload=mc3e.encode_u16(0xA5A5),
    )
    assert mc3e.decode_u16(mc3e.handle_request(memory, write), 9) == 0
    assert memory.read_bits(1024, 16) == [
        1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1
    ]

    read = mc3e.build_request(
        command=mc3e.CMD_BATCH_READ,
        subcommand=mc3e.SUBCMD_WORD,
        device="M",
        head=1024,
        points=1,
    )
    response = mc3e.handle_request(memory, read)
    assert mc3e.decode_u16(response, 9) == 0
    assert mc3e.decode_u16(response, 11) == 0xA5A5


def test_mc3e_random_read_write_round_trip() -> None:
    memory = DeviceMemory()
    memory.write_words(10, [11])
    memory.write_words(20, [21, 22])

    # word_n=1, dword_n=1 → D10 + D20(dword)
    devices = mc3e.build_device_data("D", 10) + mc3e.build_device_data("D", 20)
    request_body = (
        mc3e.encode_u16(mc3e.CMD_RANDOM_READ)
        + mc3e.encode_u16(mc3e.SUBCMD_WORD)
        + bytes([1, 1])
        + devices
    )
    frame = (
        mc3e.SUBHEADER_REQUEST.to_bytes(2, "big")
        + bytes([0, 0xFF])
        + mc3e.encode_u16(0x3FF)
        + bytes([0])
        + mc3e.encode_u16(2 + len(request_body))
        + mc3e.encode_u16(4)
        + request_body
    )
    response = mc3e.handle_request(memory, frame)
    assert mc3e.decode_u16(response, 9) == 0
    data = response[11:]
    assert mc3e.decode_i16(data, 0) == 11
    assert mc3e.decode_i16(data, 2) == 21
    assert mc3e.decode_i16(data, 4) == 22

    write_body = (
        mc3e.encode_u16(mc3e.CMD_RANDOM_WRITE)
        + mc3e.encode_u16(mc3e.SUBCMD_WORD)
        + bytes([1, 0])
        + mc3e.build_device_data("D", 10)
        + mc3e.encode_i16(99)
    )
    write_frame = (
        mc3e.SUBHEADER_REQUEST.to_bytes(2, "big")
        + bytes([0, 0xFF])
        + mc3e.encode_u16(0x3FF)
        + bytes([0])
        + mc3e.encode_u16(2 + len(write_body))
        + mc3e.encode_u16(4)
        + write_body
    )
    assert mc3e.decode_u16(mc3e.handle_request(memory, write_frame), 9) == 0
    assert memory.read_words(10, 1) == [99]


async def _transact(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    request: bytes,
) -> bytes:
    writer.write(request)
    await writer.drain()
    header = await reader.readexactly(9)
    length = mc3e.decode_u16(header, 7)
    rest = await reader.readexactly(length)
    return header + rest


async def test_softplc_tcp_read_write() -> None:
    memory = DeviceMemory()
    memory.write_words(50, [11, 22])
    server = SoftPlcServer(memory, host="127.0.0.1", port=0)
    await server.start()
    assert server._server is not None
    port = server._server.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            await server.wait_for_client(1)
            with pytest.raises(TimeoutError):
                await server.wait_for_communication(0.01)

            response = await _transact(
                reader,
                writer,
                mc3e.build_request(
                    command=mc3e.CMD_BATCH_READ,
                    subcommand=mc3e.SUBCMD_WORD,
                    device="D",
                    head=50,
                    points=2,
                ),
            )
            assert mc3e.decode_u16(response, 9) == 0
            await server.wait_for_communication(1)
            data = response[11:]
            assert [mc3e.decode_i16(data, i * 2) for i in range(2)] == [11, 22]

            await _transact(
                reader,
                writer,
                mc3e.build_request(
                    command=mc3e.CMD_BATCH_WRITE,
                    subcommand=mc3e.SUBCMD_BIT,
                    device="M",
                    head=7,
                    points=1,
                    write_payload=mc3e.pack_bits([1]),
                ),
            )
            assert memory.get_bit(7) == 1
            assert server.connected_targets == [f"127.0.0.1:{port}"]
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await server.stop()


async def test_softplc_reports_localhost_when_vtv_uses_loopback() -> None:
    server = SoftPlcServer(DeviceMemory(), host="0.0.0.0", port=0)
    await server.start()
    assert server._server is not None
    port = server._server.sockets[0].getsockname()[1]
    try:
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            await server.wait_for_client(1)
            assert server.connected_targets == [f"127.0.0.1:{port}"]
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await server.stop()


async def test_plclink_rra_handshake() -> None:
    settings = ProtocolSettings(
        transport="plclink",
        host="127.0.0.1",
        port=37651,
        timeout=3,
    )
    client = PlcLinkClient(settings)
    client.server.port = 0
    await client.server.start()
    assert client.server._server is not None
    port = client.server._server.sockets[0].getsockname()[1]
    client.server.port = port

    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await client.server.wait_for_client(2)

    async def respond() -> None:
        for _ in range(300):
            trigger = client.memory.read_dword(settings.command_address)
            code = client.memory.read_dword(settings.command_address + 2)
            if trigger == 1 and code == 9:
                client.memory.set_bit(settings.busy_address, 1)
                client.memory.write_dword(settings.response_address, 1)
                client.memory.write_dword(settings.response_address + 2, 0)
                client.memory.write_dword(settings.response_address + 4, 9)
                client.memory.write_dword(settings.response_address + 6, 0)
                # アプリが BUSY ON を確認してトリガ OFF するまで BUSY を保持
                for _ in range(300):
                    if client.memory.read_dword(settings.command_address) == 0:
                        break
                    await asyncio.sleep(0.01)
                client.memory.set_bit(settings.busy_address, 0)
                return
            await asyncio.sleep(0.01)
        raise AssertionError(
            "trigger was not observed: "
            f"D{settings.command_address}="
            f"{client.memory.read_words(settings.command_address, 4)}"
        )

    try:
        result, _ = await asyncio.gather(
            client.send_command("RRA", tcp_code="RRA", arguments={}),
            respond(),
        )
        assert result.status == "AK"
        assert "result=1" in result.responses[1]
    finally:
        writer.close()
        await writer.wait_closed()
        await client.close()


async def test_plclink_timeout_resets_trigger() -> None:
    settings = ProtocolSettings(
        transport="plclink",
        host="127.0.0.1",
        port=37652,
        timeout=0.05,
    )
    client = PlcLinkClient(settings)
    client.server.port = 0
    await client.server.start()
    assert client.server._server is not None
    port = client.server._server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    del reader
    await client.server.wait_for_client(1)

    try:
        with pytest.raises(ProtocolError, match="BUSY ON"):
            await client.send_command("RRA", tcp_code="RRA", arguments={})
        assert client.memory.read_dword(settings.command_address) == 0
    finally:
        writer.close()
        await writer.wait_closed()
        await client.close()


async def test_unsupported_plclink_command() -> None:
    with pytest.raises(ProtocolError, match="DIO"):
        resolve_spec("POA")


def _words(code: str, arguments: dict, area_size: int = 64) -> list[int]:
    spec = resolve_spec(code)
    return build_command_words(
        spec,
        arguments,
        encoding="cp932",
        byte_order="high_low",
        area_size=area_size,
    )


def test_documented_commands_match_c013_01() -> None:
    supported = {
        spec.code
        for spec in COMMAND_SPECS.values()
        if spec.code and spec.unsupported_reason is None
    }
    assert supported == DOCUMENTED_COMMAND_CODES
    assert command_metadata("EXP")["plclink_supported"] is True
    assert command_metadata("EXP")["plclink_code"] == 70
    assert command_metadata("DDN")["plclink_code"] == 75001
    assert command_metadata("EXP")["plclink_arguments"]


def test_export_batch_words_follow_manual() -> None:
    words = _words(
        "EXP",
        {
            "kind": "0",
            "progress": "1",
            "version_major": 0,
            "version_minor": 0,
            "version_sub": 0,
            "image_save": "2",
            "shared_light": "0",
            "history": "1",
            "inspect_folder": "0",
            "folder": "AB",
        },
    )
    assert words[:24] == [
        0, 0,  # trigger
        70, 0,
        0, 0,  # 一括
        1, 0,  # 経過を確認
        0, 0,
        0, 0,
        0, 0,
        2, 0,  # 画像は保存しない
        0, 0,
        1, 0,  # 変更履歴を含む
        0, 0,
        *pack_string("AB", encoding="cp932", byte_order="high_low"),
    ]


def test_import_with_numeric_adjustment_uses_code_100() -> None:
    words = _words(
        "IMP",
        {
            "kind": "0",
            "progress": "0",
            "numeric_adjust_mode": "1",
            "numeric_adjust": "2",
            "delete_images": "1",
            "delete_inspect": "0",
            "keep_capture": "1",
            "shared_light": "0",
            "include_3d": "1",
            "include_system": "0",
            "path": "AB",
        },
    )
    assert words[:24] == [
        0, 0,
        71, 0,
        100, 0,  # 一括 + 数値補正
        0, 0,
        1, 0,  # 画像削除
        0, 0,
        1, 0,  # 画像取込設定を保持
        0, 0,
        1, 0,  # 3D
        2, 0,  # 数値補正は保持
        0, 0,  # システムファイル
        *pack_string("AB", encoding="cp932", byte_order="high_low"),
    ]


def test_folder_letter_is_converted_for_plclink() -> None:
    setting = _words(
        "SFS",
        {"folder": "M", "mode": "0", "path": "AB"},
    )
    assert setting[:10] == [0, 0, 96, 0, 4, 0, 0, 0, 0x4142, 0x0000]
    reading = _words("SFS", {"folder": "I", "mode": "1", "path": r"C:\ignored"})
    assert reading[:8] == [0, 0, 96, 0, 5, 0, 1, 0]
    assert reading[8:] == [0] * (len(reading) - 8)
    increased = _words("SFI", {"folder": "B", "increment": 100})
    assert increased[:8] == [0, 0, 97, 0, 1, 0, 100, 0]


def test_image_delete_and_lot_commands() -> None:
    deleted = _words("SIE", {"delete_mode": "2", "locked": "1"})
    assert deleted[:8] == [0, 0, 36, 0, 2, 0, 1, 0]
    increased = _words("SLI", {"raw": "4"})
    assert increased[:6] == [0, 0, 64, 0, 4, 0]
    named = _words("SLP", {"lot_number": 12, "lot_name": "AB"})
    assert named[:8] == [0, 0, 65, 0, 12, 0, 0x4142, 0x0000]
    with pytest.raises(ProtocolError, match="両方を未指定"):
        _words("SLP", {"lot_number": 0, "lot_name": ""})


def test_kma_matches_manual_fixed_point_example() -> None:
    words = _words(
        "KMA",
        {
            "camera": 1,
            "line": 3,
            "multi": 0,
            "module_type": "2",
            "module_id": "09",
            "operation": "1",
            "module_number": 10,
            "x": "640.0",
            "y": "480.0",
        },
    )
    assert words[:16] == [
        0, 0,
        26000, 0,
        1, 0,
        3, 0,
        0, 0,
        10, 0,
        *dword_to_words(640000),
        *dword_to_words(480000),
    ]


def test_ocv_reset_matches_manual_example() -> None:
    words = _words(
        "WAS",
        {
            "camera": 1,
            "line": 3,
            "multi": 1,
            "block": 3,
            "enabled": "1",
            "font": 10,
            "text": "ABCDE",
            "additional_blocks": ",BL05,BF0",
        },
        area_size=80,
    )
    expected = [
        *dword_to_words(0),
        *dword_to_words(34000),
        *dword_to_words(1),
        *dword_to_words(3),
        *dword_to_words(1),
        *dword_to_words(2),
        *dword_to_words(3),
        *dword_to_words(1),
        *dword_to_words(10),
        *pack_string("ABCDE", encoding="cp932", byte_order="high_low"),
        *dword_to_words(0),
        *dword_to_words(5),
        *dword_to_words(0),
        *dword_to_words(0),
        *pack_string("", encoding="cp932", byte_order="high_low"),
        *dword_to_words(0),
    ]
    assert pack_string("ABCDE", encoding="cp932", byte_order="high_low") == [
        0x4142, 0x4344, 0x4500, 0x0000,
    ]
    assert words[: len(expected)] == expected


def test_region_delete_inserts_dummy_dwords() -> None:
    words = _words(
        "NLA",
        {"camera": 1, "line": 5, "region_row": 2, "region_column": 3},
    )
    assert words[:16] == [
        0, 0,
        56002, 0,
        1, 0,
        5, 0,
        0, 0,
        0, 0,
        2, 0,
        3, 0,
    ]


def test_numeric_distribution_identifier() -> None:
    words = _words("DDN", {"camera": 1, "line": 5, "identifier": 123})
    assert words[:10] == [0, 0, *dword_to_words(75001), 1, 0, 5, 0, 123, 0]


def test_dfa_get_omits_path() -> None:
    words = _words("DFA", {"camera": 1, "line": 16, "mode": "1", "path": ""})
    assert words[:10] == [0, 0, 30000, 0, 1, 0, 16, 0, 1, 0]
    assert words[10:] == [0] * (len(words) - 10)
