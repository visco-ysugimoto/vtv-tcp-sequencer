"""Field Network アセンブリバッファへのワード／ビットアクセス。"""

from __future__ import annotations

import threading
from typing import Literal

ByteOrder = Literal["high_low", "low_high"]


class AssemblyMemory:
    """O->T / T->O バイトバッファをワード／DWORD／ビットで扱う。"""

    def __init__(self, output_size: int, input_size: int):
        self.output_size = output_size
        self.input_size = input_size
        self._lock = threading.RLock()
        self._out = bytearray(output_size)
        self._in = bytearray(input_size)

    def clear(self) -> None:
        with self._lock:
            self._out[:] = b"\x00" * self.output_size
            self._in[:] = b"\x00" * self.input_size

    def replace_output(self, data: bytes | bytearray) -> None:
        if len(data) != self.output_size:
            raise ValueError("出力サイズ不一致")
        with self._lock:
            self._out[:] = data

    def replace_input(self, data: bytes | bytearray) -> None:
        if len(data) != self.input_size:
            raise ValueError("入力サイズ不一致")
        with self._lock:
            self._in[:] = data

    def snapshot_output(self) -> bytes:
        with self._lock:
            return bytes(self._out)

    def snapshot_input(self) -> bytes:
        with self._lock:
            return bytes(self._in)

    def read_out_words(self, word_index: int, count: int) -> list[int]:
        with self._lock:
            return _read_words(self._out, word_index, count)

    def write_out_words(self, word_index: int, values: list[int]) -> None:
        with self._lock:
            _write_words(self._out, word_index, values)

    def read_in_words(self, word_index: int, count: int) -> list[int]:
        with self._lock:
            return _read_words(self._in, word_index, count)

    def read_out_dword(self, word_index: int) -> int:
        words = self.read_out_words(word_index, 2)
        return _words_to_dword(words)

    def write_out_dword(self, word_index: int, value: int) -> None:
        unsigned = int(value) & 0xFFFFFFFF
        self.write_out_words(
            word_index, [unsigned & 0xFFFF, (unsigned >> 16) & 0xFFFF]
        )

    def read_in_dword(self, word_index: int) -> int:
        words = self.read_in_words(word_index, 2)
        return _words_to_dword(words)

    def get_in_bit(self, bit_address: int) -> int:
        with self._lock:
            byte_index = bit_address // 8
            if byte_index < 0 or byte_index >= len(self._in):
                raise IndexError(f"IN ビット範囲外: {bit_address}")
            return 1 if self._in[byte_index] & (1 << (bit_address % 8)) else 0

    def get_out_bit(self, bit_address: int) -> int:
        with self._lock:
            byte_index = bit_address // 8
            if byte_index < 0 or byte_index >= len(self._out):
                raise IndexError(f"OUT ビット範囲外: {bit_address}")
            return 1 if self._out[byte_index] & (1 << (bit_address % 8)) else 0

    def set_out_bit(self, bit_address: int, value: int) -> None:
        with self._lock:
            byte_index = bit_address // 8
            if byte_index < 0 or byte_index >= len(self._out):
                raise IndexError(f"OUT ビット範囲外: {bit_address}")
            mask = 1 << (bit_address % 8)
            if value:
                self._out[byte_index] |= mask
            else:
                self._out[byte_index] &= 0xFF ^ mask


def _read_words(buf: bytearray, word_index: int, count: int) -> list[int]:
    start = word_index * 2
    end = start + count * 2
    if start < 0 or end > len(buf):
        raise IndexError(f"ワード範囲外: {word_index}+{count}")
    words: list[int] = []
    for offset in range(start, end, 2):
        words.append(buf[offset] | (buf[offset + 1] << 8))
    return words


def _write_words(buf: bytearray, word_index: int, values: list[int]) -> None:
    start = word_index * 2
    end = start + len(values) * 2
    if start < 0 or end > len(buf):
        raise IndexError(f"ワード範囲外: {word_index}+{len(values)}")
    for index, value in enumerate(values):
        offset = start + index * 2
        unsigned = value & 0xFFFF
        buf[offset] = unsigned & 0xFF
        buf[offset + 1] = (unsigned >> 8) & 0xFF


def _words_to_dword(words: list[int]) -> int:
    low = words[0] & 0xFFFF
    high = words[1] & 0xFFFF
    value = (high << 16) | low
    if value & 0x80000000:
        value -= 0x100000000
    return value
