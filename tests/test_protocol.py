import asyncio

import pytest

from backend.models import ProtocolSettings
from backend.protocol import (
    ProtocolError,
    VtvTcpClient,
    add_checksum,
    remove_and_verify_checksum,
    xor_checksum,
)


def test_checksum_matches_manual_example() -> None:
    payload = "GRP01 TSK01 OK "
    assert xor_checksum(payload.encode("cp932")) == "2D"


def test_add_and_remove_checksum() -> None:
    framed = add_checksum("AK", " ", "cp932")
    assert remove_and_verify_checksum(framed, " ", "cp932") == "AK"


def test_invalid_checksum_is_rejected() -> None:
    with pytest.raises(ProtocolError, match="チェックサム不一致"):
        remove_and_verify_checksum("AK FF", " ", "cp932")


async def test_tcp_command_and_result_round_trip() -> None:
    received = b""

    async def device(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        nonlocal received
        received = await reader.readuntil(b"\r")
        writer.write(
            f"{add_checksum('AK', ' ', 'cp932')}\r".encode("cp932")
        )
        writer.write(
            f"{add_checksum('00000001', ' ', 'cp932')}\r".encode("cp932")
        )
        await writer.drain()
        writer.close()

    server = await asyncio.start_server(device, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    settings = ProtocolSettings(host="127.0.0.1", port=port)
    async with server:
        async with VtvTcpClient(settings) as client:
            result = await client.send_command("POP01", expect_result=True)

    assert received == b"POP01\r"
    assert result.status == "AK"
    assert result.responses == ["AK", "00000001"]


async def test_tcp_collects_result_lines_until_idle() -> None:
    async def device(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        await reader.readuntil(b"\r")
        for line in ("AK", r"C01 R012 C:\temp\a", r"C01 R016 C:\temp\b"):
            writer.write(
                f"{add_checksum(line, ' ', 'cp932')}\r".encode("cp932")
            )
        await writer.drain()
        await asyncio.sleep(0.3)
        writer.close()

    server = await asyncio.start_server(device, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    settings = ProtocolSettings(host="127.0.0.1", port=port)
    async with server:
        async with VtvTcpClient(settings) as client:
            result = await client.send_command(
                "DFA01001",
                expect_result=True,
                result_mode="until_idle",
            )

    assert result.responses == [
        "AK",
        r"C01 R012 C:\temp\a",
        r"C01 R016 C:\temp\b",
    ]
