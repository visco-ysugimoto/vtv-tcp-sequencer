"""NCP フラグ違いで 142/614 Forward Open を試す。"""

from __future__ import annotations

import asyncio
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.field_network.eds import parse_connection_path
from backend.field_network import eip_scanner as eip


async def try_fo(
    label: str,
    o_flags: int,
    t_flags: int,
    *,
    transport: int = 0x01,
    tick: int = 0x07,
    tm: int = 0x03,
) -> bool:
    scanner = eip.EipClass1Scanner(
        "192.168.0.10", input_size=612, output_size=136, timeout=3.0
    )
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, scanner._open_sockets_and_session)
    path = parse_connection_path("20 04 24 01 2C 14 2C 0A")
    o_size, t_size = 142, 614
    body = bytearray()
    body.append(tick)
    body.append(0xFA)
    body += struct.pack("<II", 0, 0)
    body += struct.pack("<HHI", 1, eip.VENDOR_ID, eip.ORIGINATOR_SERIAL)
    body.append(tm)
    body += b"\x00\x00\x00"
    body += struct.pack("<I", 10_000)
    body += struct.pack("<I", o_size | o_flags)
    body += struct.pack("<I", 10_000)
    body += struct.pack("<I", t_size | t_flags)
    body.append(transport)
    body.append(len(path) // 2)
    body += path
    cm_path = bytes([0x20, 0x06, 0x24, 0x01])
    cip = bytes([eip.CIP_LARGE_FORWARD_OPEN, len(cm_path) // 2]) + cm_path + body
    ip = eip._local_ipv4_for_peer(scanner.host)
    items = [
        (eip.ITEM_NULL_ADDRESS, b""),
        (eip.ITEM_UNCONNECTED_DATA, cip),
        (eip.ITEM_SOCKADDR_TO, eip._pack_sockaddr(scanner._local_udp_port, ip)),
    ]
    try:
        resp = await loop.run_in_executor(
            None,
            lambda: scanner._transact(
                eip.ENC_SEND_RR_DATA, eip._pack_cpf(items, timeout_ms=2000)
            ),
        )
        reply = eip._extract_unconnected_reply(resp)
        status = reply[2]
        add_words = reply[3]
        ext = reply[4 : 4 + add_words * 2]
        ok = status == 0
        print(f"{'OK' if ok else 'NG'}  {label}: ext={ext.hex() if not ok else '0'}")
        await scanner.close()
        return ok
    except Exception as exc:  # noqa: BLE001
        print(f"NG  {label}: {exc}")
        try:
            await scanner.close()
        except Exception:  # noqa: BLE001
            pass
        return False


async def main() -> None:
    p2p = 2 << 20
    cases = [
        ("fixed low p2p", p2p, p2p),
        ("fixed sched p2p", p2p | (2 << 17), p2p | (2 << 17)),
        ("fixed high p2p", p2p | (1 << 17), p2p | (1 << 17)),
        ("var low p2p", p2p | (1 << 16), p2p | (1 << 16)),
        ("pycomm 0x42000000", 0x42000000, 0x42000000),
        ("fixed low tick0A", p2p, p2p),
        ("O fixed T var", p2p, p2p | (1 << 16)),
        ("multicast T", p2p, 1 << 20),
    ]
    for label, oflags, tflags in cases:
        kwargs = {}
        if "tick0A" in label:
            kwargs["tick"] = 0x0A
            kwargs["tm"] = 7
        if await try_fo(label, oflags, tflags, **kwargs):
            print("SUCCESS")
            return
    print("done")


if __name__ == "__main__":
    asyncio.run(main())
