from __future__ import annotations

import socket


def local_ipv4_addresses() -> list[str]:
    """この PC の到達可能な IPv4 アドレス（ループバック除く）。"""
    addresses: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip in addresses:
                continue
            addresses.append(ip)
    except OSError:
        pass

    # getaddrinfo が空の環境向けフォールバック
    if not addresses:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                ip = sock.getsockname()[0]
                if not ip.startswith("127."):
                    addresses.append(ip)
        except OSError:
            pass
    return addresses


def connect_targets(port: int) -> list[str]:
    return [f"{ip}:{port}" for ip in local_ipv4_addresses()]
