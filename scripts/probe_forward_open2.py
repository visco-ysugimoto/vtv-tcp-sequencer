"""142/614 通過後の 0x0132 切り分け。"""

from __future__ import annotations

import asyncio
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.field_network.eds import parse_connection_path
from backend.field_network.eip_scanner import (
    CIP_FORWARD_OPEN,
    CIP_LARGE_FORWARD_OPEN,
    ENC_SEND_RR_DATA,
    EipClass1Scanner,
    ITEM_NULL_ADDRESS,
    ITEM_SOCKADDR_TO,
    ITEM_UNCONNECTED_DATA,
    ORIGINATOR_SERIAL,
    VENDOR_ID,
    _extract_unconnected_reply,
    _local_ipv4_for_peer,
    _pack_cpf,
    _pack_network_params,
    _pack_sockaddr,
)


async def try_custom(
    *,
    label: str,
    path_hex: str,
    o_size: int = 142,
    t_size: int = 614,
    rpi: int = 10_000,
    transport: int = 0x01,
    timeout_mult: int = 0x03,
    vendor: int = VENDOR_ID,
    serial: int = ORIGINATOR_SERIAL,
    force_large: bool | None = None,
    include_sockaddr: bool = True,
    priority: int | None = None,
) -> bool:
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

        use_large = (
            force_large
            if force_large is not None
            else (o_size > 511 or t_size > 511)
        )
        service = CIP_LARGE_FORWARD_OPEN if use_large else CIP_FORWARD_OPEN
        connection_serial = 1

        body = bytearray()
        body.append(0x07)
        body.append(0xFA)
        body += struct.pack("<I", 0)
        body += struct.pack("<I", 0)
        body += struct.pack("<H", connection_serial)
        body += struct.pack("<H", vendor)
        body += struct.pack("<I", serial)
        body.append(timeout_mult)
        body += b"\x00\x00\x00"
        body += struct.pack("<I", rpi)
        if priority is None:
            body += _pack_network_params(o_size, large=use_large)
        else:
            if use_large:
                value = (o_size & 0xFFFF) | ((priority & 7) << 17) | (2 << 20)
                body += struct.pack("<I", value)
            else:
                value = (o_size & 0x1FF) | ((priority & 7) << 10) | (2 << 13)
                body += struct.pack("<H", value)
        body += struct.pack("<I", rpi)
        if priority is None:
            body += _pack_network_params(t_size, large=use_large)
        else:
            if use_large:
                value = (t_size & 0xFFFF) | ((priority & 7) << 17) | (2 << 20)
                body += struct.pack("<I", value)
            else:
                value = (t_size & 0x1FF) | ((priority & 7) << 10) | (2 << 13)
                body += struct.pack("<H", value)
        body.append(transport)
        body.append(len(path) // 2)
        body += path

        cm_path = bytes([0x20, 0x06, 0x24, 0x01])
        cip = bytes([service, len(cm_path) // 2]) + cm_path + body
        local_ip = _local_ipv4_for_peer(scanner.host)
        items: list[tuple[int, bytes]] = [
            (ITEM_NULL_ADDRESS, b""),
            (ITEM_UNCONNECTED_DATA, cip),
        ]
        if include_sockaddr:
            items.append(
                (
                    ITEM_SOCKADDR_TO,
                    _pack_sockaddr(scanner._local_udp_port, local_ip),
                )
            )
        response = await loop.run_in_executor(
            None,
            lambda: scanner._transact(
                ENC_SEND_RR_DATA, _pack_cpf(items, timeout_ms=2000)
            ),
        )
        cip_reply = _extract_unconnected_reply(response)
        general_status = cip_reply[2]
        add_words = cip_reply[3]
        ext = cip_reply[4 : 4 + add_words * 2]
        if general_status != 0:
            print(f"NG  {label}: status=0x{general_status:02X} ext={ext.hex()}")
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
        dict(label="baseline 142/614 large", path_hex="20 04 24 01 2C 14 2C 0A"),
        dict(label="no config inst", path_hex="20 04 2C 14 2C 0A"),
        dict(label="config inst0", path_hex="20 04 24 00 2C 14 2C 0A"),
        dict(label="points only", path_hex="2C 14 2C 0A"),
        dict(label="swap points", path_hex="20 04 24 01 2C 0A 2C 14"),
        dict(label="RPI 20000", path_hex="20 04 24 01 2C 14 2C 0A", rpi=20_000),
        dict(label="RPI 5000", path_hex="20 04 24 01 2C 14 2C 0A", rpi=5_000),
        dict(label="transport 0xA1", path_hex="20 04 24 01 2C 14 2C 0A", transport=0xA1),
        dict(label="priority low", path_hex="20 04 24 01 2C 14 2C 0A", priority=0),
        dict(label="priority high", path_hex="20 04 24 01 2C 14 2C 0A", priority=1),
        dict(label="no sockaddr", path_hex="20 04 24 01 2C 14 2C 0A", include_sockaddr=False),
        dict(label="timeout mult 0", path_hex="20 04 24 01 2C 14 2C 0A", timeout_mult=0),
        dict(label="vendor 1724", path_hex="20 04 24 01 2C 14 2C 0A", vendor=1724),
        # T size without +2 but O with +2 already known fail; try O=142 T=612+0 again no
        dict(label="O142 T612", path_hex="20 04 24 01 2C 14 2C 0A", t_size=612),
        dict(
            label="electronic key loose",
            path_hex="34 04 00 00 00 00 00 00 00 00 20 04 24 01 2C 14 2C 0A",
        ),
        dict(
            label="key Visco exact",
            # Vend 1724=0x06BC, type 43=0x2B, prod 826=0x033A, maj 1 compat
            path_hex="34 04 BC 06 2B 00 3A 03 01 00 20 04 24 01 2C 14 2C 0A",
        ),
    ]
    for case in cases:
        ok = await try_custom(**case)
        if ok:
            print("success")
            return
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
