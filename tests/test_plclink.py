from __future__ import annotations

import asyncio

import pytest

from backend.models import MemoryWatchItem, ProtocolSettings
from backend.plc_link import PlcLinkClient, mc3e
from backend.plc_link.commands import (
    build_command_words,
    command_metadata,
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
    assert command_metadata("RRA") == {
        "plclink_supported": True,
        "plclink_code": 9,
        "plclink_reason": None,
    }
    assert command_metadata("POA")["plclink_supported"] is False


def test_busy_address_from_plo_port() -> None:
    settings = ProtocolSettings(
        transport="plclink",
        host="0.0.0.0",
        plo_address=1024,
        busy_port=5,
    )
    assert settings.busy_address == 1028


def test_build_mapped_watch_items() -> None:
    settings = ProtocolSettings(
        transport="plclink",
        host="0.0.0.0",
        command_address=4096,
        response_address=8192,
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
    assert [item.id for item in items if item.group == "PLO出力"] == [
        "plo-port-1",
        "plo-port-2",
        "plo-port-3",
        "plo-port-4",
    ]
    assert by_id["plo-port-2"].label == "BUSY (Port 2)"
    assert by_id["plo-port-2"].address == 1025
    assert by_id["plo-port-2"].format == "bit"


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


def test_mc3e_out_of_range_returns_error_response() -> None:
    memory = DeviceMemory()
    request = mc3e.build_request(
        command=mc3e.CMD_BATCH_READ,
        subcommand=mc3e.SUBCMD_WORD,
        device="D",
        head=65535,
        points=2,
    )

    response = mc3e.handle_request(memory, request)

    assert response[0:2] == b"\xd0\x00"
    assert mc3e.decode_u16(response, 9) == 0xC050


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
