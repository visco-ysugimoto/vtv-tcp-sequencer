"""EtherNet/IP Class 1 Scanner（Implicit I/O Originator）。"""

from __future__ import annotations

import asyncio
import queue
import socket
import struct
import threading
import time
from dataclasses import dataclass, field

from ..bit_edges import BitEdgeLog, resolve_mono
from ..i18n import LocalizedError, LocalizedMixin, Msg, MsgJoin
from ..protocol import ProtocolError
from .eds import parse_connection_path



class ScannerError(LocalizedMixin, OSError):
    """Scanner の I/O 失敗。メッセージキー付きで言語別に取り出せる。"""


EIP_PORT = 44818
IO_UDP_PORT = 2222
# VTV は Class 1 の 2 byte シーケンス番号を接続サイズに含める
CLASS1_SEQUENCE_BYTES = 2

ENC_REGISTER_SESSION = 0x0065
ENC_UNREGISTER_SESSION = 0x0066
ENC_SEND_RR_DATA = 0x006F

CIP_FORWARD_OPEN = 0x54
CIP_LARGE_FORWARD_OPEN = 0x5B
CIP_FORWARD_CLOSE = 0x4E

ITEM_NULL_ADDRESS = 0x0000
ITEM_UNCONNECTED_DATA = 0x00B2
ITEM_CONNECTED_ADDRESS = 0x00A1
ITEM_CONNECTED_DATA = 0x00B1
ITEM_SOCKADDR_OT = 0x8000
ITEM_SOCKADDR_TO = 0x8001
ITEM_SEQUENCED_ADDRESS = 0x8002  # Class 1: conn_id(4) + encap_seq(4)

VENDOR_ID = 0x06BC  # private / unused ODVA range style
ORIGINATOR_SERIAL = 0x56545646  # "VTVF"
RUN_IDLE_RUN = 0x00000001


@dataclass
class Class1Connection:
    o_to_t_connection_id: int
    t_to_o_connection_id: int
    connection_serial: int
    originator_vendor_id: int
    originator_serial: int
    o_to_t_rpi_us: int
    t_to_o_rpi_us: int
    o_to_t_api_us: int
    t_to_o_api_us: int
    o_to_t_udp_port: int = IO_UDP_PORT
    t_to_o_udp_port: int = IO_UDP_PORT


@dataclass
class IoBuffers:
    """スレッドセーフな O->T / T->O データバッファ。"""

    output_size: int
    input_size: int
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _output: bytearray = field(init=False, repr=False)
    _input: bytearray = field(init=False, repr=False)
    _input_seq: int = field(default=0, init=False, repr=False)
    _output_seq: int = field(default=0, init=False, repr=False)
    _last_input_at: float = field(default=0.0, init=False, repr=False)
    _packets_rx: int = field(default=0, init=False, repr=False)
    _packets_tx: int = field(default=0, init=False, repr=False)
    edges: BitEdgeLog = field(default_factory=BitEdgeLog, repr=False)

    def __post_init__(self) -> None:
        self._output = bytearray(self.output_size)
        self._input = bytearray(self.input_size)

    def clear(self) -> None:
        now = resolve_mono(None)
        with self._lock:
            previous_output = bytes(self._output)
            previous_input = bytes(self._input)
            self._output[:] = b"\x00" * self.output_size
            self._input[:] = b"\x00" * self.input_size
            self._packets_rx = 0
            self._packets_tx = 0
            self._last_input_at = 0.0
            cleared_output = bytes(self._output)
            cleared_input = bytes(self._input)
        self._record_bit_changes("OUT", previous_output, cleared_output, now)
        self._record_bit_changes("IN", previous_input, cleared_input, now)

    def write_output(self, data: bytes | bytearray) -> None:
        if len(data) != self.output_size:
            raise LocalizedError(
                "fn.outputSizeMismatch",
                actual=len(data),
                expected=self.output_size,
            )
        now = resolve_mono(None)
        incoming = bytes(data)
        with self._lock:
            previous = bytes(self._output)
            self._output[:] = incoming
        self._record_bit_changes("OUT", previous, incoming, now)

    def read_output(self) -> bytes:
        with self._lock:
            return bytes(self._output)

    def set_output_bit(self, bit_index: int, value: int) -> None:
        """出力バッファの 1 bit をアトミックに更新（ESI 割り込み用）。"""
        byte_index = int(bit_index) // 8
        bit = int(bit_index) % 8
        now = resolve_mono(None)
        new_bit = 1 if int(value) else 0
        with self._lock:
            if byte_index < 0 or byte_index >= len(self._output):
                raise LocalizedError("fn.outputBitOutOfRange", bit=bit_index)
            mask = 1 << bit
            old_bit = 1 if self._output[byte_index] & mask else 0
            if old_bit == new_bit:
                return
            if new_bit:
                self._output[byte_index] |= mask
            else:
                self._output[byte_index] &= ~mask
        self.edges.record("OUT", int(bit_index), new_bit, now)

    def write_input(
        self,
        data: bytes | bytearray,
        *,
        sequence: int | None = None,
        mono_s: float | None = None,
    ) -> None:
        if len(data) != self.input_size:
            raise LocalizedError(
                "fn.inputSizeMismatch",
                actual=len(data),
                expected=self.input_size,
            )
        # mono_s は recvfrom 直後の時刻。処理が遅れてもパケット到達時刻を使う。
        arrived = resolve_mono(mono_s)
        incoming = bytes(data)
        with self._lock:
            previous = bytes(self._input)
            self._input[:] = incoming
            if sequence is not None:
                self._input_seq = sequence & 0xFFFF
            self._last_input_at = time.monotonic()
            self._packets_rx += 1
        self._record_bit_changes("IN", previous, incoming, arrived)

    def _record_bit_changes(
        self,
        device: str,
        previous: bytes,
        incoming: bytes,
        mono_s: float,
    ) -> None:
        watched = [
            address
            for watched_device, address in self.edges.watched_keys()
            if watched_device == device
        ]
        for address in watched:
            byte_index = address // 8
            if (
                byte_index < 0
                or byte_index >= len(previous)
                or byte_index >= len(incoming)
            ):
                continue
            mask = 1 << (address % 8)
            old_bit = 1 if previous[byte_index] & mask else 0
            new_bit = 1 if incoming[byte_index] & mask else 0
            if old_bit != new_bit:
                self.edges.record(device, address, new_bit, mono_s)

    def read_input(self) -> bytes:
        with self._lock:
            return bytes(self._input)

    def mark_tx(self) -> int:
        with self._lock:
            self._packets_tx += 1
            self._output_seq = (self._output_seq + 1) & 0xFFFF
            return self._output_seq

    @property
    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "packets_rx": self._packets_rx,
                "packets_tx": self._packets_tx,
                "last_input_age_ms": (
                    None
                    if self._last_input_at <= 0
                    else int((time.monotonic() - self._last_input_at) * 1000)
                ),
                "input_seq": self._input_seq,
                "output_seq": self._output_seq,
            }


class EipClass1Scanner:
    """VTV Adapter 向け最小 Class 1 Scanner。"""

    def __init__(
        self,
        host: str,
        *,
        tcp_port: int = EIP_PORT,
        input_size: int,
        output_size: int,
        rpi_us: int = 10_000,
        connection_path: str = "20 04 24 01 2C 14 2C 0A",
        o_to_t_header_bytes: int = 4,
        timeout: float = 5.0,
    ):
        self.host = host
        self.tcp_port = tcp_port
        self.input_size = input_size
        self.output_size = output_size
        self.rpi_us = max(2000, int(rpi_us))
        self.connection_path = connection_path
        self.o_to_t_header_bytes = o_to_t_header_bytes
        self.timeout = timeout
        self.buffers = IoBuffers(output_size=output_size, input_size=input_size)
        # 幅の量子は RPI。装置下限の 2ms 未満は出さない。
        self.buffers.edges.min_interval_s = self.rpi_us / 1_000_000

        self._tcp: socket.socket | None = None
        self._udp: socket.socket | None = None
        self._session = 0
        self._connection: Class1Connection | None = None
        self._connection_serial = 1
        self._sender_context = 1
        self._loop_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._connected = False
        self._local_udp_port = 0
        self._error: str | None = None
        self._rx_queue: queue.Queue[tuple[float, bytes]] = queue.Queue()
        self._rx_thread: threading.Thread | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._connection is not None

    @property
    def last_error(self) -> str | None:
        return self._error

    async def connect(self) -> None:
        if self.is_connected:
            return
        self._error = None
        self.buffers.clear()
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._open_sockets_and_session)
            await loop.run_in_executor(None, self._forward_open)
        except Exception as exc:
            await self.close()
            raise ProtocolError("fn.eipConnectFailed", detail=exc) from exc

        self._stop.clear()
        self._connected = True
        self._rx_queue = queue.Queue()
        self._rx_thread = threading.Thread(
            target=self._udp_recv_loop,
            name="eip-udp-rx",
            daemon=True,
        )
        self._rx_thread.start()
        self._loop_task = asyncio.create_task(self._io_loop(), name="eip-io")

    async def close(self) -> None:
        self._connected = False
        self._stop.set()
        task = self._loop_task
        self._loop_task = None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        thread = self._rx_thread
        self._rx_thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=1.0)

        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._close_sync)

    def _open_sockets_and_session(self) -> None:
        try:
            tcp = socket.create_connection(
                (self.host, self.tcp_port), timeout=self.timeout
            )
        except OSError as exc:
            winerr = getattr(exc, "winerror", None)
            errno = getattr(exc, "errno", None)
            if winerr == 10061 or errno in {111, 10061}:
                raise ScannerError(
                    "fn.tcpRefused", host=self.host, port=self.tcp_port
                ) from exc
            raise
        tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        tcp.settimeout(self.timeout)
        self._tcp = tcp

        # VTV は SOCKADDR のエフェメラルポートを無視し、常に UDP 2222 へ T→O を送る
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            udp.bind(("", IO_UDP_PORT))
        except OSError as exc:
            udp.close()
            raise ScannerError(
                "fn.udpBindFailed", port=IO_UDP_PORT, detail=str(exc)
            ) from exc
        self._udp = udp
        self._local_udp_port = IO_UDP_PORT

        request = struct.pack("<HH", 1, 0)  # protocol version, options
        response = self._transact(ENC_REGISTER_SESSION, request)
        if len(response) < 4:
            raise ScannerError("fn.registerSessionInvalid")
        # session handle is already in encapsulation header; also echoed in payload
        self._session = self._last_session

    def _forward_open(self) -> None:
        assert self._tcp is not None and self._udp is not None
        path = parse_connection_path(self.connection_path)
        if len(path) % 2:
            path += b"\x00"

        # VTV 実機確認: O→T = Assem + Run/Idle + Seq, T→O = Assem + Seq
        base_o = self.output_size + self.o_to_t_header_bytes
        base_t = self.input_size
        size_candidates = [
            (base_o + CLASS1_SEQUENCE_BYTES, base_t + CLASS1_SEQUENCE_BYTES),
            (base_o + CLASS1_SEQUENCE_BYTES, base_t),
            (base_o, base_t),
            (base_o, base_t + CLASS1_SEQUENCE_BYTES),
            (self.output_size, self.input_size),
        ]
        # 重複除去（順序維持）
        seen: set[tuple[int, int]] = set()
        unique_candidates: list[tuple[int, int]] = []
        for pair in size_candidates:
            if pair not in seen:
                seen.add(pair)
                unique_candidates.append(pair)

        last_exc: OSError | None = None
        for o_to_t_size, t_to_o_size in unique_candidates:
            try:
                self._forward_open_once(path, o_to_t_size, t_to_o_size)
                return
            except OSError as exc:
                last_exc = exc
                last_error = str(exc)
                # サイズ不一致以外は即座に打ち切る
                if "0x0127" not in last_error and "0x0128" not in last_error:
                    raise
        if last_exc is not None:
            raise last_exc
        raise ScannerError("fn.forwardOpenFailed")

    def _forward_open_once(
        self, path: bytes, o_to_t_size: int, t_to_o_size: int
    ) -> None:
        assert self._tcp is not None and self._udp is not None
        path_words = len(path) // 2
        use_large = o_to_t_size > 511 or t_to_o_size > 511
        service = CIP_LARGE_FORWARD_OPEN if use_large else CIP_FORWARD_OPEN

        connection_serial = self._connection_serial & 0xFFFF
        self._connection_serial = (self._connection_serial + 1) & 0xFFFF or 1

        # Priority/Tick Time + timeout ticks（接続タイムアウト用）
        priority_tick = 0x07
        timeout_ticks = 0xFA

        body = bytearray()
        body.append(priority_tick)
        body.append(timeout_ticks)
        body += struct.pack("<I", 0)  # O->T Network Connection ID（Target 割当）
        body += struct.pack("<I", 0)  # T->O Network Connection ID
        body += struct.pack("<H", connection_serial)
        body += struct.pack("<H", VENDOR_ID)
        body += struct.pack("<I", ORIGINATOR_SERIAL)
        body.append(0x03)  # timeout multiplier ×8
        body += b"\x00\x00\x00"
        body += struct.pack("<I", self.rpi_us)
        body += _pack_network_params(o_to_t_size, large=use_large)
        body += struct.pack("<I", self.rpi_us)
        body += _pack_network_params(t_to_o_size, large=use_large)
        body.append(0x01)  # Class 1, cyclic
        body.append(path_words)
        body += path

        cm_path = bytes([0x20, 0x06, 0x24, 0x01])
        cip = bytes([service, len(cm_path) // 2]) + cm_path + body

        local_ip = _local_ipv4_for_peer(self.host)
        items: list[tuple[int, bytes]] = [
            (ITEM_NULL_ADDRESS, b""),
            (ITEM_UNCONNECTED_DATA, cip),
            (ITEM_SOCKADDR_TO, _pack_sockaddr(self._local_udp_port, local_ip)),
        ]

        response = self._transact(ENC_SEND_RR_DATA, _pack_cpf(items, timeout_ms=2000))
        cip_reply = _extract_unconnected_reply(response)
        if len(cip_reply) < 4:
            raise ScannerError("fn.forwardOpenEmpty")

        general_status = cip_reply[2]
        add_words = cip_reply[3]
        add_bytes = add_words * 2
        if general_status != 0:
            ext = cip_reply[4 : 4 + add_bytes]
            raise ScannerError(
                _format_forward_open_error(
                    general_status,
                    ext,
                    o_to_t_size=o_to_t_size,
                    t_to_o_size=t_to_o_size,
                    output_size=self.output_size,
                    input_size=self.input_size,
                    o_to_t_header_bytes=self.o_to_t_header_bytes,
                )
            )

        data = cip_reply[4 + add_bytes :]
        if len(data) < 26:
            raise ScannerError("fn.forwardOpenShort", size=len(cip_reply))

        o_to_t_id, t_to_o_id = struct.unpack_from("<II", data, 0)
        conn_serial, vendor, serial = struct.unpack_from("<HHI", data, 8)
        o_api, t_api = struct.unpack_from("<II", data, 16)

        o_udp = IO_UDP_PORT
        for item_type, item_data in _iter_cpf_items(response):
            if item_type == ITEM_SOCKADDR_OT and len(item_data) >= 8:
                o_udp = struct.unpack("!H", item_data[2:4])[0] or IO_UDP_PORT

        self._connection = Class1Connection(
            o_to_t_connection_id=o_to_t_id,
            t_to_o_connection_id=t_to_o_id,
            connection_serial=conn_serial,
            originator_vendor_id=vendor,
            originator_serial=serial,
            o_to_t_rpi_us=self.rpi_us,
            t_to_o_rpi_us=self.rpi_us,
            o_to_t_api_us=o_api or self.rpi_us,
            t_to_o_api_us=t_api or self.rpi_us,
            o_to_t_udp_port=o_udp,
            t_to_o_udp_port=self._local_udp_port,
        )

    def _forward_close(self) -> None:
        conn = self._connection
        if conn is None or self._tcp is None:
            return
        path = parse_connection_path(self.connection_path)
        if len(path) % 2:
            path += b"\x00"
        body = bytearray()
        body.append(0x07)
        body.append(0xFA)
        body += struct.pack("<H", conn.connection_serial)
        body += struct.pack("<H", conn.originator_vendor_id)
        body += struct.pack("<I", conn.originator_serial)
        body.append(len(path) // 2)
        body.append(0x00)  # reserved
        body += path
        cm_path = bytes([0x20, 0x06, 0x24, 0x01])
        cip = bytes([CIP_FORWARD_CLOSE, len(cm_path) // 2]) + cm_path + body
        items = [
            (ITEM_NULL_ADDRESS, b""),
            (ITEM_UNCONNECTED_DATA, cip),
        ]
        try:
            self._transact(ENC_SEND_RR_DATA, _pack_cpf(items, timeout_ms=1000))
        except OSError:
            pass

    def _close_sync(self) -> None:
        try:
            self._forward_close()
        except Exception:
            pass
        if self._tcp is not None and self._session:
            try:
                self._transact(ENC_UNREGISTER_SESSION, b"")
            except Exception:
                pass
        if self._udp is not None:
            try:
                self._udp.close()
            except OSError:
                pass
            self._udp = None
        if self._tcp is not None:
            try:
                self._tcp.close()
            except OSError:
                pass
            self._tcp = None
        self._connection = None
        self._session = 0

    def _udp_recv_loop(self) -> None:
        """Windows ProactorEventLoop では UDP sock_recvfrom が不安定なためスレッド受信。"""
        udp = self._udp
        if udp is None:
            return
        udp.settimeout(0.05)
        while not self._stop.is_set():
            try:
                data, _addr = udp.recvfrom(2048)
            except (TimeoutError, socket.timeout):
                continue
            except OSError as exc:
                if not self._stop.is_set():
                    self._error = str(exc)
                    self._connected = False
                break
            arrived = time.perf_counter()
            try:
                self._rx_queue.put_nowait((arrived, data))
            except queue.Full:
                pass

    async def _io_loop(self) -> None:
        assert self._udp is not None and self._connection is not None
        conn = self._connection
        interval = max(conn.o_to_t_api_us, self.rpi_us) / 1_000_000
        interval = max(0.002, interval)
        loop = asyncio.get_running_loop()
        next_send = loop.time()

        while not self._stop.is_set():
            try:
                self._drain_input_queue()

                now = loop.time()
                if now >= next_send:
                    self._send_output()
                    next_send = now + interval
                await asyncio.sleep(min(0.001, max(0.0, next_send - now)))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._error = str(exc)
                self._connected = False
                break

    def _drain_input_queue(self) -> None:
        while True:
            try:
                mono_s, data = self._rx_queue.get_nowait()
            except queue.Empty:
                return
            self._handle_input_packet(data, mono_s=mono_s)

    def _handle_input_packet(self, packet: bytes, *, mono_s: float) -> None:
        conn = self._connection
        if conn is None or len(packet) < 20:
            return
        # CPF without encapsulation for Class 1 UDP
        try:
            item_count = struct.unpack_from("<H", packet, 0)[0]
        except struct.error:
            return
        offset = 2
        conn_id = None
        payload = None
        for _ in range(item_count):
            if offset + 4 > len(packet):
                return
            item_type, item_len = struct.unpack_from("<HH", packet, offset)
            offset += 4
            item_data = packet[offset : offset + item_len]
            offset += item_len
            if item_type == ITEM_SEQUENCED_ADDRESS and len(item_data) >= 4:
                conn_id = struct.unpack_from("<I", item_data, 0)[0]
            elif item_type == ITEM_CONNECTED_ADDRESS and len(item_data) >= 4:
                conn_id = struct.unpack_from("<I", item_data, 0)[0]
            elif item_type == ITEM_CONNECTED_DATA and len(item_data) >= 2:
                seq = struct.unpack_from("<H", item_data, 0)[0]
                payload = (seq, item_data[2:])
        if conn_id != conn.t_to_o_connection_id or payload is None:
            return
        seq, data = payload
        if len(data) < self.input_size:
            return
        self.buffers.write_input(
            data[: self.input_size],
            sequence=seq,
            mono_s=mono_s,
        )

    def _send_output(self) -> None:
        conn = self._connection
        udp = self._udp
        if conn is None or udp is None:
            return
        seq = self.buffers.mark_tx()
        assembly = self.buffers.read_output()
        if self.o_to_t_header_bytes:
            data = struct.pack("<I", RUN_IDLE_RUN) + assembly
        else:
            data = assembly
        # CIP 16-bit sequence + Run/Idle + assembly
        data_item = struct.pack("<H", seq) + data
        # VTV は Sequenced Address Item (0x8002) を使用
        packet = struct.pack("<H", 2)
        packet += struct.pack("<HH", ITEM_SEQUENCED_ADDRESS, 8)
        packet += struct.pack("<II", conn.o_to_t_connection_id, seq)
        packet += struct.pack("<HH", ITEM_CONNECTED_DATA, len(data_item))
        packet += data_item
        try:
            udp.sendto(packet, (self.host, conn.o_to_t_udp_port or IO_UDP_PORT))
        except OSError as exc:
            self._error = str(exc)
            self._connected = False

    # --- encapsulation helpers ---

    _last_session: int = 0

    def _transact(self, command: int, payload: bytes) -> bytes:
        assert self._tcp is not None
        context = self._sender_context & 0xFFFFFFFFFFFFFFFF
        self._sender_context = (self._sender_context + 1) & 0xFFFFFFFFFFFFFFFF
        header = struct.pack(
            "<HHII8sI",
            command,
            len(payload),
            self._session,
            0,
            context.to_bytes(8, "little"),
            0,
        )
        self._tcp.sendall(header + payload)
        resp_header = _recvexact(self._tcp, 24)
        cmd, length, session, status, _ctx, _opt = struct.unpack("<HHII8sI", resp_header)
        if status != 0:
            raise OSError(f"Encapsulation status=0x{status:08X} cmd=0x{cmd:04X}")
        body = _recvexact(self._tcp, length) if length else b""
        self._session = session or self._session
        self._last_session = self._session
        if command == ENC_REGISTER_SESSION and length >= 0:
            pass
        return body


def _pack_network_params(size: int, *, large: bool) -> bytes:
    """VTV 互換の Network Connection Parameters を打包する。

    CIP の Large FO では本来 size とフラグのビット位置が再配置されるが、
    VTV は 16-bit NCP のフラグビット位置を上位ワードにそのまま載せる方式
    （pycomm3 と同じ 0x4200 << 16）を要求する。
    0x4200 = Variable + Point-to-Point（実機プローブで Forward Open 成功を確認）。
    """
    # bit9=Variable, bit14=P2P (16-bit NCP レイアウト)
    flags_16 = 0x4200
    if large:
        value = (size & 0xFFFF) | (flags_16 << 16)
        return struct.pack("<I", value)
    value = (size & 0x1FF) | flags_16
    return struct.pack("<H", value)


_FORWARD_OPEN_EXT_STATUS = {
    0x0100: "fn.fwd.ext.0100",
    0x0103: "fn.fwd.ext.0103",
    0x0106: "fn.fwd.ext.0106",
    0x0108: "fn.fwd.ext.0108",
    0x0109: "fn.fwd.ext.0109",
    0x0111: "fn.fwd.ext.0111",
    0x0114: "fn.fwd.ext.0114",
    0x0117: "fn.fwd.ext.0117",
    0x0123: "fn.fwd.ext.0123",
    0x0124: "fn.fwd.ext.0124",
    0x0127: "fn.fwd.ext.0127",
    0x0128: "fn.fwd.ext.0128",
    0x0132: "fn.fwd.ext.0132",
}


def _format_forward_open_error(
    general_status: int,
    ext: bytes,
    *,
    o_to_t_size: int,
    t_to_o_size: int,
    output_size: int,
    input_size: int,
    o_to_t_header_bytes: int,
) -> MsgJoin:
    words = [
        struct.unpack_from("<H", ext, offset)[0]
        for offset in range(0, len(ext) - 1, 2)
    ]
    ext_code = words[0] if words else None
    expected = words[1] if len(words) > 1 else None
    meaning_key = _FORWARD_OPEN_EXT_STATUS.get(ext_code or -1)
    parts: list[object] = [
        Msg("fn.fwd.failed", status=f"{general_status:02X}"),
        f"ext={ext.hex() or '-'}",
    ]
    if ext_code is not None:
        label = f"0x{ext_code:04X}"
        if meaning_key:
            parts.append(
                Msg("fn.fwd.extWithMeaning", label=label, meaning=Msg(meaning_key))
            )
        else:
            parts.append(f"({label})")
        if expected is not None:
            parts.append(f"expected={expected}")

    if ext_code == 0x0127:
        parts.append(
            Msg(
                "fn.fwd.sendOtoT",
                size=o_to_t_size,
                output_size=output_size,
                header=o_to_t_header_bytes,
                seq=CLASS1_SEQUENCE_BYTES,
            )
        )
        if expected is not None:
            assembly = max(
                0, expected - o_to_t_header_bytes - CLASS1_SEQUENCE_BYTES
            )
            parts.append(
                Msg("fn.fwd.requestOtoT", expected=expected, assembly=assembly)
            )
    elif ext_code == 0x0128:
        parts.append(
            Msg(
                "fn.fwd.sendTtoO",
                size=t_to_o_size,
                input_size=input_size,
                seq=CLASS1_SEQUENCE_BYTES,
            )
        )
        if expected is not None:
            assembly = max(0, expected - CLASS1_SEQUENCE_BYTES)
            parts.append(
                Msg("fn.fwd.requestTtoO", expected=expected, assembly=assembly)
            )
    elif ext_code == 0x0106:
        parts.append(Msg("fn.fwd.ownership"))
    else:
        parts.append(
            Msg("fn.fwd.sizes", o_to_t=o_to_t_size, t_to_o=t_to_o_size)
        )
    return MsgJoin(parts)


def _pack_cpf(items: list[tuple[int, bytes]], *, timeout_ms: int) -> bytes:
    # SendRRData: interface handle + timeout(ms) + CPF
    out = bytearray()
    out += struct.pack("<IH", 0, max(0, min(timeout_ms, 0xFFFF)))
    out += struct.pack("<H", len(items))
    for item_type, data in items:
        out += struct.pack("<HH", item_type, len(data))
        out += data
    return bytes(out)


def _iter_cpf_items(send_rr_body: bytes) -> list[tuple[int, bytes]]:
    if len(send_rr_body) < 8:
        return []
    # skip interface handle + timeout
    offset = 6
    count = struct.unpack_from("<H", send_rr_body, offset)[0]
    offset += 2
    items: list[tuple[int, bytes]] = []
    for _ in range(count):
        if offset + 4 > len(send_rr_body):
            break
        item_type, item_len = struct.unpack_from("<HH", send_rr_body, offset)
        offset += 4
        data = send_rr_body[offset : offset + item_len]
        offset += item_len
        items.append((item_type, data))
    return items


def _extract_unconnected_reply(send_rr_body: bytes) -> bytes:
    for item_type, data in _iter_cpf_items(send_rr_body):
        if item_type == ITEM_UNCONNECTED_DATA:
            return data
    return b""


def _pack_sockaddr(port: int, ipv4: str) -> bytes:
    # CIP Sockaddr: sin_family(BE INT=2), sin_port(BE), sin_addr(BE), pad8
    parts = [int(p) for p in ipv4.split(".")]
    if len(parts) != 4:
        parts = [0, 0, 0, 0]
    addr = (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3]
    return struct.pack("!HHI", 2, port & 0xFFFF, addr) + b"\x00" * 8


def _local_ipv4_for_peer(peer_host: str) -> str:
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.connect((peer_host, EIP_PORT))
        ip = probe.getsockname()[0]
        probe.close()
        return ip
    except OSError:
        return "0.0.0.0"


def _recvexact(sock: socket.socket, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        block = sock.recv(size - len(chunks))
        if not block:
            raise ScannerError("fn.tcpClosed")
        chunks.extend(block)
    return bytes(chunks)
