"""0x0132 (Null FO) の切り分け: data segment / multicast / NCP raw."""

from __future__ import annotations

import asyncio
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.field_network.eds import parse_connection_path
from backend.field_network.eip_scanner import (
    CIP_LARGE_FORWARD_OPEN,
    ENC_SEND_RR_DATA,
    EipClass1Scanner,
    ITEM_NULL_ADDRESS,
    ITEM_SOCKADDR_OT,
    ITEM_SOCKADDR_TO,
    ITEM_UNCONNECTED_DATA,
    ORIGINATOR_SERIAL,
    VENDOR_ID,
    _extract_unconnected_reply,
    _local_ipv4_for_peer,
    _pack_cpf,
    _pack_sockaddr,
)


def pack_ncp(size: int, *, conn_type: int = 2, priority: int = 2, variable: int = 0, redundant: int = 0) -> bytes:
    value = (
        (size & 0xFFFF)
        | ((variable & 1) << 16)
        | ((priority & 7) << 17)
        | ((conn_type & 7) << 20)
        | ((redundant & 1) << 24)
    )
    return struct.pack("<I", value)


async def try_once(label: str, **kw) -> bool:
    path_hex = kw.get("path_hex", "20 04 24 01 2C 14 2C 0A")
    o_size = kw.get("o_size", 142)
    t_size = kw.get("t_size", 614)
    o_type = kw.get("o_type", 2)
    t_type = kw.get("t_type", 2)
    rpi = kw.get("rpi", 10_000)
    transport = kw.get("transport", 0x01)
    add_ot_sockaddr = kw.get("add_ot_sockaddr", False)
    o_priority = kw.get("o_priority", 2)
    t_priority = kw.get("t_priority", 2)

    scanner = EipClass1Scanner(
        "192.168.0.10",
        input_size=612,
        output_size=136,
        rpi_us=rpi,
        timeout=3.0,
    )
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, scanner._open_sockets_and_session)
        path = parse_connection_path(path_hex)
        if len(path) % 2:
            path += b"\x00"

        body = bytearray()
        body.append(0x07)
        body.append(0xFA)
        body += struct.pack("<I", 0)
        body += struct.pack("<I", 0)
        body += struct.pack("<H", 7)
        body += struct.pack("<H", VENDOR_ID)
        body += struct.pack("<I", ORIGINATOR_SERIAL)
        body.append(0x03)
        body += b"\x00\x00\x00"
        body += struct.pack("<I", rpi)
        body += pack_ncp(o_size, conn_type=o_type, priority=o_priority)
        body += struct.pack("<I", rpi)
        body += pack_ncp(t_size, conn_type=t_type, priority=t_priority)
        body.append(transport)
        body.append(len(path) // 2)
        body += path

        cm_path = bytes([0x20, 0x06, 0x24, 0x01])
        cip = bytes([CIP_LARGE_FORWARD_OPEN, len(cm_path) // 2]) + cm_path + body
        local_ip = _local_ipv4_for_peer(scanner.host)
        items: list[tuple[int, bytes]] = [
            (ITEM_NULL_ADDRESS, b""),
            (ITEM_UNCONNECTED_DATA, cip),
            (ITEM_SOCKADDR_TO, _pack_sockaddr(scanner._local_udp_port, local_ip)),
        ]
        if add_ot_sockaddr:
            items.append(
                (ITEM_SOCKADDR_OT, _pack_sockaddr(2222, local_ip))
            )

        response = await loop.run_in_executor(
            None,
            lambda: scanner._transact(
                ENC_SEND_RR_DATA, _pack_cpf(items, timeout_ms=2000)
            ),
        )
        cip_reply = _extract_unconnected_reply(response)
        status = cip_reply[2]
        add_words = cip_reply[3]
        ext = cip_reply[4 : 4 + add_words * 2]
        if status != 0:
            print(f"NG  {label}: ext={ext.hex()}")
            await scanner.close()
            return False
        print(f"OK  {label}")
        await scanner.close()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"NG  {label}: {exc}")
        try:
            await scanner.close()
        except Exception:  # noqa: BLE001
            pass
        return False


async def main() -> None:
    cases = [
        dict(label="data seg empty", path_hex="20 04 24 01 2C 14 2C 0A 80 00"),
        dict(label="data seg 2words zero", path_hex="20 04 24 01 2C 14 2C 0A 80 02 00 00 00 00"),
        dict(label="T multicast", t_type=1),
        dict(label="O multicast T p2p", o_type=1, t_type=2),
        dict(label="both multicast", o_type=1, t_type=1),
        dict(label="OT sockaddr too", add_ot_sockaddr=True),
        dict(label="priority 0/0", o_priority=0, t_priority=0),
        dict(label="transport 0x00 class0?", transport=0x00),
        dict(label="transport 0x01", transport=0x01),
        dict(label="transport 0x81 server", transport=0x81),
        # Some stacks want size WITHOUT run/idle in FO but still 142? already know 142 works for O
        # Try T=612 with O=142 again after forward close? 
        dict(label="T=612 again", t_size=612),
        # Maybe target wants T size 614 but O size without seq = 140? already failed O
        # Try connection path with 16-bit logical format
        dict(label="16bit logical path", path_hex="21 00 04 00 25 00 01 00 2D 00 14 00 2D 00 0A 00"),
    ]
    for case in cases:
        if await try_once(**case):
            print("SUCCESS")
            return
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
