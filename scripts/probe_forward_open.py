"""VTV に対する Forward Open サイズの実機プローブ。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.field_network.eds import parse_connection_path
from backend.field_network.eip_scanner import EipClass1Scanner


async def try_fo(host: str, o_size: int, t_size: int, label: str) -> bool:
    scanner = EipClass1Scanner(
        host,
        tcp_port=44818,
        input_size=612,
        output_size=136,
        rpi_us=10_000,
        connection_path="20 04 24 01 2C 14 2C 0A",
        o_to_t_header_bytes=4,
        timeout=3.0,
    )
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, scanner._open_sockets_and_session)
        path = parse_connection_path(scanner.connection_path)
        await loop.run_in_executor(
            None, lambda: scanner._forward_open_once(path, o_size, t_size)
        )
        print(f"OK  {label}: O={o_size} T={t_size}")
        await scanner.close()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"NG  {label}: O={o_size} T={t_size} | {exc}")
        try:
            await scanner.close()
        except Exception:  # noqa: BLE001
            pass
        return False


async def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.10"
    print(f"probe host={host}")
    pairs = [
        (142, 612, "142/612"),
        (142, 614, "142/614"),
        (140, 612, "140/612"),
        (140, 614, "140/614"),
        (136, 612, "136/612"),
        (138, 612, "138/612"),
        (144, 612, "144/612"),
        (142, 616, "142/616"),
        (142, 610, "142/610"),
        (134, 612, "134/612"),
        (132, 612, "132/612"),
        (68, 306, "words-as-bytes?"),
        (142, 306, "142/306"),
    ]
    for o_size, t_size, label in pairs:
        if await try_fo(host, o_size, t_size, label):
            print("success — stop")
            return
    print("all candidates failed")


if __name__ == "__main__":
    asyncio.run(main())
