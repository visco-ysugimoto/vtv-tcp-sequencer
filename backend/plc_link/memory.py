from __future__ import annotations

import threading


class DeviceMemory:
    """疑似 PLC のデータメモリ（D: ワード、M: ビット）。"""

    def __init__(self, d_size: int = 65536, m_size: int = 65536):
        self._lock = threading.RLock()
        self._d = [0] * d_size
        self._m = [0] * m_size

    def clear(self) -> None:
        with self._lock:
            self._d = [0] * len(self._d)
            self._m = [0] * len(self._m)

    def read_words(self, head: int, count: int) -> list[int]:
        with self._lock:
            self._check_d_range(head, count)
            return list(self._d[head : head + count])

    def write_words(self, head: int, values: list[int]) -> None:
        with self._lock:
            self._check_d_range(head, len(values))
            for offset, value in enumerate(values):
                self._d[head + offset] = self._to_u16(value)

    def read_bits(self, head: int, count: int) -> list[int]:
        with self._lock:
            self._check_m_range(head, count)
            return list(self._m[head : head + count])

    def write_bits(self, head: int, values: list[int]) -> None:
        with self._lock:
            self._check_m_range(head, len(values))
            for offset, value in enumerate(values):
                if value not in (0, 1):
                    raise ValueError("ビット値は 0 または 1 です")
                self._m[head + offset] = value

    def get_bit(self, address: int) -> int:
        with self._lock:
            self._check_m_range(address, 1)
            return self._m[address]

    def set_bit(self, address: int, value: int) -> None:
        self.write_bits(address, [1 if value else 0])

    def read_dword(self, head: int) -> int:
        words = self.read_words(head, 2)
        low, high = words[0], words[1]
        value = (high << 16) | low
        if value & 0x80000000:
            value -= 0x100000000
        return value

    def write_dword(self, head: int, value: int) -> None:
        unsigned = value & 0xFFFFFFFF
        self.write_words(head, [unsigned & 0xFFFF, (unsigned >> 16) & 0xFFFF])

    def _check_d_range(self, head: int, count: int) -> None:
        if head < 0 or count < 0 or head + count > len(self._d):
            raise IndexError(f"D アドレス範囲外: {head}+{count}")

    def _check_m_range(self, head: int, count: int) -> None:
        if head < 0 or count < 0 or head + count > len(self._m):
            raise IndexError(f"M アドレス範囲外: {head}+{count}")

    @staticmethod
    def _to_u16(value: int) -> int:
        return value & 0xFFFF
