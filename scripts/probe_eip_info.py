"""VTV の Identity / サービス一覧を取得し、Large FO の可否を探る。"""

from __future__ import annotations

import asyncio
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.field_network.eip_scanner import (
    ENC_LIST_SERVICES,
    ENC_SEND_RR_DATA,
    EipClass1Scanner,
    ITEM_NULL_ADDRESS,
    ITEM_UNCONNECTED_DATA,
    _extract_unconnected_reply,
    _pack_cpf,
)

# ListIdentity
ENC_LIST_IDENTITY = 0x0063


async def main() -> None:
    scanner = EipClass1Scanner(
        "192.168.0.10",
        input_size=612,
        output_size=136,
        timeout=3.0,
    )
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, scanner._open_sockets_and_session)

    # ListServices via encapsulation
    services = await loop.run_in_executor(
        None, lambda: scanner._transact(ENC_LIST_SERVICES, b"")
    )
    print("ListServices payload:", services.hex())

    # ListIdentity
    try:
        identity = await loop.run_in_executor(
            None, lambda: scanner._transact(ENC_LIST_IDENTITY, b"")
        )
        print("ListIdentity payload:", identity.hex())
    except Exception as exc:  # noqa: BLE001
        print("ListIdentity failed:", exc)

    # Get Attributes All on Identity Object (class 1 instance 1)
    # Service 0x01, path 20 01 24 01
    cip = bytes([0x01, 0x02, 0x20, 0x01, 0x24, 0x01])
    items = [(ITEM_NULL_ADDRESS, b""), (ITEM_UNCONNECTED_DATA, cip)]
    try:
        resp = await loop.run_in_executor(
            None,
            lambda: scanner._transact(
                ENC_SEND_RR_DATA, _pack_cpf(items, timeout_ms=2000)
            ),
        )
        reply = _extract_unconnected_reply(resp)
        print("Identity GetAttributesAll:", reply.hex())
        if len(reply) >= 4 and reply[2] == 0:
            data = reply[4:]
            # vendor, device type, product code, revision, status, serial, name...
            if len(data) >= 15:
                vendor, dtype, prod = struct.unpack_from("<HHH", data, 0)
                maj, minor = data[6], data[7]
                status, serial = struct.unpack_from("<HI", data, 8)
                name_len = data[14]
                name = data[15 : 15 + name_len]
                print(
                    f"vendor={vendor} type={dtype} product={prod} "
                    f"rev={maj}.{minor} serial={serial:08X} name={name!r}"
                )
    except Exception as exc:  # noqa: BLE001
        print("Identity explicit failed:", exc)

    # Forward Open service support via Get Attribute Single on CM?
    await scanner.close()


if __name__ == "__main__":
    asyncio.run(main())
