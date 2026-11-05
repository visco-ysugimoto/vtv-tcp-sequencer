from __future__ import annotations

import asyncio

import pytest

from backend.local_io import (
    apply_local_io,
    format_local_io_display,
    local_io_metadata,
    parse_port_list,
)
from backend.models import ProtocolSettings
from backend.plc_link.client import PlcLinkClient
from backend.plc_link.commands import command_metadata
from backend.protocol import ProtocolError


def test_parse_port_list_supports_ranges() -> None:
    assert parse_port_list("1,3,5-8", max_port=16, label="PLI") == [1, 3, 5, 6, 7, 8]


def test_parse_port_list_rejects_out_of_range() -> None:
    with pytest.raises(ProtocolError, match="範囲外"):
        parse_port_list("1,40", max_port=32, label="PLI")


def test_local_io_metadata() -> None:
    pli = local_io_metadata("PLI")
    assert pli is not None
    assert pli["plclink_supported"] is True
    assert pli["field_network_supported"] is False
    esi = command_metadata("ESI")
    assert esi["field_network_supported"] is True
    assert esi["plclink_supported"] is False
    assert esi["local_io"] is True


def test_format_local_io_display() -> None:
    assert format_local_io_display("PLI", {"state": "1", "ports": "1,2"}) == "PLION[1,2]"
    assert format_local_io_display("ESI", {"state": 0, "ports": "3"}) == "ESIOFF[3]"


def test_pli_sets_multiple_ports() -> None:
    settings = ProtocolSettings(
        transport="plclink",
        host="0.0.0.0",
        pli_address=200,
        pli_port_count=16,
        plo_address=1024,
        plo_port_count=16,
        busy_port=1,
    )
    client = PlcLinkClient(settings)

    async def _run() -> None:
        result = await apply_local_io(
            client,
            code="PLI",
            arguments={"state": "1", "ports": "1,3,5-6"},
        )
        assert result.status == "AK"
        assert client.memory.get_bit(200) == 1
        assert client.memory.get_bit(201) == 0
        assert client.memory.get_bit(202) == 1
        assert client.memory.get_bit(204) == 1
        assert client.memory.get_bit(205) == 1
        assert client.memory.get_bit(1024) == 0
        await apply_local_io(
            client,
            code="PLI",
            arguments={"state": "0", "ports": "3"},
        )
        assert client.memory.get_bit(202) == 0

    asyncio.run(_run())
