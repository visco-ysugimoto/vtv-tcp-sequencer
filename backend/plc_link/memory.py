from __future__ import annotations

import threading


class DeviceMemory:
    """疑似 PLC のデータメモリ（D: ワード、M: ビット）。"""

    MAX_D_SIZE = 1_048_576
    MAX_M_SIZE = 1_048_576

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
            self._ensure_d_range(head, count)
            return list(self._d[head : head + count])

    def write_words(self, head: int, values: list[int]) -> None:
        with self._lock:
            self._ensure_d_range(head, len(values))
            for offset, value in enumerate(values):
                self._d[head + offset] = self._to_u16(value)

    def read_bits(self, head: int, count: int) -> list[int]:
        with self._lock:
            self._ensure_m_range(head, count)
            return list(self._m[head : head + count])

    def write_bits(self, head: int, values: list[int]) -> None:
        with self._lock:
            self._ensure_m_range(head, len(values))
            for offset, value in enumerate(values):
                if value not in (0, 1):
                    raise ValueError("ビット値は 0 または 1 です")
                self._m[head + offset] = value

    def read_bit_words(self, head: int, count: int) -> list[int]:
        """ビットデバイスをワード単位（16bit パック）で読む。"""
        words: list[int] = []
        for index in range(count):
            bits = self.read_bits(head + index * 16, 16)
            value = 0
            for bit_index, bit in enumerate(bits):
                if bit:
                    value |= 1 << bit_index
            words.append(value)
        return words

    def write_bit_words(self, head: int, values: list[int]) -> None:
        """ビットデバイスへワード単位（16bit パック）で書く。"""
        for index, value in enumerate(values):
            unsigned = self._to_u16(value)
            bits = [1 if unsigned & (1 << bit_index) else 0 for bit_index in range(16)]
            self.write_bits(head + index * 16, bits)

    def get_bit(self, address: int) -> int:
        with self._lock:
            self._ensure_m_range(address, 1)
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

    def _ensure_d_range(self, head: int, count: int) -> None:
        if head < 0 or count < 0:
            raise IndexError(f"D アドレス範囲外: {head}+{count}")
        need = head + count
        if need <= len(self._d):
            return
        if need > self.MAX_D_SIZE:
            raise IndexError(f"D アドレス範囲外: {head}+{count}")
        self._d.extend([0] * (need - len(self._d)))

    def _ensure_m_range(self, head: int, count: int) -> None:
        if head < 0 or count < 0:
            raise IndexError(f"M アドレス範囲外: {head}+{count}")
        need = head + count
        if need <= len(self._m):
            return
        if need > self.MAX_M_SIZE:
            raise IndexError(f"M アドレス範囲外: {head}+{count}")
        self._m.extend([0] * (need - len(self._m)))

    @staticmethod
    def _to_u16(value: int) -> int:
        return value & 0xFFFF
