"""短パルスは監視周期ではなく変化時刻で幅を取る。"""

from __future__ import annotations

import asyncio
import socket
import struct
import threading
import time

import pytest

from backend.bit_edges import stamp_bit_edges
from backend.field_network.eip_scanner import (
    ITEM_CONNECTED_DATA,
    ITEM_SEQUENCED_ADDRESS,
    Class1Connection,
    EipClass1Scanner,
    IoBuffers,
)
from backend.models import MemoryWatchItem, ProtocolSettings
from backend.plc_link import mc3e
from backend.plc_link.memory import DeviceMemory
from backend.plc_link.server import SoftPlcServer
from backend.watch_stream import format_bit_edges, run_watch_loop


def _on_pulse_widths_ms(messages: list[dict], item_id: str) -> list[float]:
    """タイミングチャートと同じく、ON の始点から次に値が変わる点までの幅。"""
    points: list[tuple[float, object]] = []
    level: object = None
    for message in messages:
        if message.get("type") != "sample":
            continue
        for edge in message.get("edges") or []:
            if edge.get("id") != item_id:
                continue
            level = edge.get("value")
            points.append((float(edge["mono_ms"]), level))
        found = False
        sample_value: object = None
        for row in message.get("values") or []:
            if row.get("id") == item_id:
                found = True
                sample_value = row.get("value")
        if message.get("full") or found:
            level = sample_value
        points.append((float(message["mono_ms"]), level))
    points.sort(key=lambda item: item[0])
    for index, (start, value) in enumerate(points):
        if value != 1:
            continue
        end_index = index + 1
        while end_index < len(points) and points[end_index][1] == 1:
            end_index += 1
        if end_index < len(points):
            return [points[end_index][0] - start]
        return []
    return []


async def _one_watch_sample(**kwargs: object) -> list[dict]:
    sent: list[dict] = []
    stop = {"flag": False}

    async def send_json(payload: dict) -> None:
        sent.append(payload)
        stop["flag"] = True

    await run_watch_loop(
        should_stop=lambda: stop["flag"],
        send_json=send_json,
        **kwargs,  # type: ignore[arg-type]
    )
    return sent


def test_unwatched_and_word_writes_are_not_edges() -> None:
    memory = DeviceMemory()
    memory.edges.arm({("M", 1)})
    memory.write_words(0, [1])
    memory.set_bit(2, 1)
    memory.set_bit(1, 0)
    _seq, edges = memory.edges.take(0)
    assert edges == []
    memory.set_bit(1, 1)
    memory.set_bit(1, 1)
    _seq, edges = memory.edges.take(0)
    assert [(edge.address, edge.value) for edge in edges] == [(1, 1)]


def test_clear_records_falling_edge_for_watched_bits() -> None:
    memory = DeviceMemory()
    memory.edges.arm({("M", 3)})
    memory.set_bit(3, 1)
    seq, _edges = memory.edges.take(0)
    memory.clear()
    _seq, edges = memory.edges.take(seq)
    assert [(edge.address, edge.value) for edge in edges] == [(3, 0)]


async def test_plclink_short_pulse_width_ignores_poll_period() -> None:
    memory = DeviceMemory()
    items = [MemoryWatchItem(id="bit", device="M", address=5, format="bit")]
    cursor = {"seq": memory.edges.arm({("M", 5)})}
    base = time.perf_counter()
    with stamp_bit_edges(base):
        memory.set_bit(5, 1)
    with stamp_bit_edges(base + 0.0015):
        memory.set_bit(5, 0)

    def read_once() -> list[dict]:
        return [{"id": "bit", "value": memory.get_bit(5), "valid": True}]

    def take_edges() -> list[dict]:
        seq, edges = memory.edges.take(cursor["seq"])
        cursor["seq"] = seq
        return format_bit_edges(edges, items)

    sent = await _one_watch_sample(
        transport="plclink",
        items=items,
        interval_ms=50,
        read_once=read_once,
        take_edges=take_edges,
    )
    assert len(sent) == 1
    assert sent[0]["values"] == [{"id": "bit", "value": 0, "valid": True}]
    assert [edge["value"] for edge in sent[0]["edges"]] == [1, 0]
    assert _on_pulse_widths_ms(sent, "bit") == pytest.approx([1.5])


async def test_field_network_one_packet_pulse_uses_packet_interval() -> None:
    buffers = IoBuffers(output_size=2, input_size=2)
    buffers.edges.min_interval_s = 0.002
    items = [MemoryWatchItem(id="eso", device="IN", address=0, format="bit")]
    cursor = {"seq": buffers.edges.arm({("IN", 0)})}
    base = time.perf_counter()
    buffers.write_input(b"\x00\x00", mono_s=base)
    buffers.write_input(b"\x01\x00", mono_s=base + 0.002)
    buffers.write_input(b"\x00\x00", mono_s=base + 0.004)

    def read_once() -> list[dict]:
        value = 1 if buffers.read_input()[0] & 1 else 0
        return [{"id": "eso", "value": value, "valid": True}]

    def take_edges() -> list[dict]:
        seq, edges = buffers.edges.take(cursor["seq"])
        cursor["seq"] = seq
        return format_bit_edges(edges, items)

    sent = await _one_watch_sample(
        transport="field_network",
        items=items,
        interval_ms=50,
        read_once=read_once,
        take_edges=take_edges,
    )
    assert sent[0]["values"] == [{"id": "eso", "value": 0, "valid": True}]
    assert [edge["value"] for edge in sent[0]["edges"]] == [1, 0]
    assert _on_pulse_widths_ms(sent, "eso") == pytest.approx([2.0])


def test_field_network_width_is_not_shorter_than_rpi() -> None:
    buffers = IoBuffers(output_size=2, input_size=2)
    buffers.edges.min_interval_s = 0.002
    buffers.edges.arm({("IN", 0), ("OUT", 3)})
    buffers.write_input(b"\x01\x00", mono_s=1.0)
    buffers.write_input(b"\x00\x00", mono_s=1.0004)
    with stamp_bit_edges(5.0):
        buffers.set_output_bit(3, 1)
    with stamp_bit_edges(5.0004):
        buffers.set_output_bit(3, 0)
    _seq, edges = buffers.edges.take(0)
    by_device = {edge.device: [] for edge in edges}
    for edge in edges:
        by_device[edge.device].append(edge)
    assert by_device["IN"][1].mono_s - by_device["IN"][0].mono_s == pytest.approx(
        0.002
    )
    assert by_device["OUT"][1].mono_s - by_device["OUT"][0].mono_s == pytest.approx(
        0.002
    )


def test_input_packet_keeps_recv_timestamp() -> None:
    scanner = EipClass1Scanner(
        "10.0.0.1",
        input_size=2,
        output_size=2,
        rpi_us=2000,
    )
    assert scanner.rpi_us == 2000
    assert scanner.buffers.edges.min_interval_s == pytest.approx(0.002)
    scanner.buffers.edges.arm({("IN", 0)})
    scanner._connection = Class1Connection(
        o_to_t_connection_id=1,
        t_to_o_connection_id=99,
        connection_serial=1,
        originator_vendor_id=1,
        originator_serial=1,
        o_to_t_rpi_us=2000,
        t_to_o_rpi_us=2000,
        o_to_t_api_us=2000,
        t_to_o_api_us=2000,
    )
    scanner._rx_queue.put((3.0, _class1_packet(99, 1, b"\x00\x00")))
    scanner._rx_queue.put((3.002, _class1_packet(99, 2, b"\x01\x00")))
    scanner._rx_queue.put((3.004, _class1_packet(99, 3, b"\x00\x00")))
    scanner._drain_input_queue()
    _seq, edges = scanner.buffers.edges.take(0)
    assert [edge.value for edge in edges] == [1, 0]
    assert edges[0].mono_s == pytest.approx(3.002)
    assert edges[1].mono_s - edges[0].mono_s == pytest.approx(0.002)


def test_udp_recv_stamps_arrival() -> None:
    scanner = EipClass1Scanner("10.0.0.1", input_size=2, output_size=2)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", 0))
    scanner._udp = sock
    scanner._stop.clear()
    thread = threading.Thread(target=scanner._udp_recv_loop, daemon=True)
    sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    thread.start()
    try:
        before = time.perf_counter()
        sender.sendto(b"xyz", sock.getsockname())
        mono, data = scanner._rx_queue.get(timeout=2)
        after = time.perf_counter()
    finally:
        scanner._stop.set()
        thread.join(1)
        sender.close()
        sock.close()
    assert data == b"xyz"
    assert before <= mono <= after


def test_rpi_below_2ms_is_raised() -> None:
    settings = ProtocolSettings(host="10.0.0.1", fn_rpi_us=1000)
    assert settings.fn_rpi_us == 2000
    kept = ProtocolSettings(host="10.0.0.1", fn_rpi_us=10_000)
    assert kept.fn_rpi_us == 10_000


async def test_mc_frame_shares_one_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = {"n": 0}

    def fake_clock() -> float:
        ticks["n"] += 1
        return 100.0 + ticks["n"]

    monkeypatch.setattr("backend.plc_link.server.time.perf_counter", fake_clock)
    memory = DeviceMemory()
    memory.edges.arm({("M", 0), ("M", 1), ("M", 16)})
    server = SoftPlcServer(memory, host="127.0.0.1", port=0)
    await server.start()
    assert server._server is not None
    port = server._server.sockets[0].getsockname()[1]
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            await server.wait_for_client(1)
            await _transact(reader, writer, _bit_word_write([0x0003, 0x0001]))
            await _transact(reader, writer, _bit_word_write([0x0000, 0x0000]))
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await server.stop()

    _seq, edges = memory.edges.take(0)
    rising = [edge for edge in edges if edge.value == 1]
    falling = [edge for edge in edges if edge.value == 0]
    assert sorted(edge.address for edge in rising) == [0, 1, 16]
    assert len({edge.mono_s for edge in rising}) == 1
    assert len({edge.mono_s for edge in falling}) == 1
    assert rising[0].mono_s != falling[0].mono_s


class _SlowDrainServer(SoftPlcServer):
    """応答の送信待ちを引き伸ばし、そのあいだに届く次フレームを試す。"""

    async def _drain_writer(self, writer: asyncio.StreamWriter) -> None:
        await asyncio.sleep(0.1)
        await super()._drain_writer(writer)


async def _wait_m0(memory: DeviceMemory, value: int) -> None:
    deadline = time.perf_counter() + 1.0
    while time.perf_counter() < deadline:
        if memory.get_bit(0) == value:
            return
        await asyncio.sleep(0.001)
    raise AssertionError(f"M0 did not become {value}")


async def test_falling_edge_keeps_arrival_time_while_response_drains() -> None:
    """立下りは応答送信の待ちが終わった時刻ではなく、受信が戻った時刻になる。"""
    memory = DeviceMemory()
    memory.edges.arm({("M", 0)})
    server = _SlowDrainServer(memory, host="127.0.0.1", port=0)
    await server.start()
    assert server._server is not None
    port = server._server.sockets[0].getsockname()[1]
    try:
        _reader, writer = await asyncio.open_connection("127.0.0.1", port)
        sock = writer.get_extra_info("socket")
        assert sock is not None
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            await server.wait_for_client(1)
            writer.write(_bit_word_write([0x0001]))
            await writer.drain()
            await _wait_m0(memory, 1)
            gap_started = time.perf_counter()
            while time.perf_counter() - gap_started < 0.002:
                pass
            writer.write(_bit_word_write([0x0000]))
            await writer.drain()
            await _wait_m0(memory, 0)
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await server.stop()

    _seq, edges = memory.edges.take(0)
    rising = [edge for edge in edges if edge.value == 1]
    falling = [edge for edge in edges if edge.value == 0]
    assert len(rising) == 1
    assert len(falling) == 1
    width = falling[0].mono_s - rising[0].mono_s
    # 注入した 100ms の送信待ちを、幅に足さない。
    assert 0.001 <= width < 0.05, width


class _BlockedLoopServer(SoftPlcServer):
    """最初のフレームを処理したあと、ループを同期的に止める。"""

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self._spun = False

    def _consume_frames(self, buffer, arrived, writer):  # type: ignore[no-untyped-def]
        wrote, accepted = super()._consume_frames(buffer, arrived, writer)
        if not self._spun:
            self._spun = True
            end = time.perf_counter() + 0.02
            while time.perf_counter() < end:
                pass
        return wrote, accepted


async def test_pulse_width_survives_blocked_event_loop() -> None:
    """ループが止まっていても、0.6ms 級の幅は受信スレッドの時刻のまま残る。"""
    memory = DeviceMemory()
    memory.edges.arm({("M", 0)})
    server = _BlockedLoopServer(memory, host="127.0.0.1", port=0)
    await server.start()
    assert server._server is not None
    port = server._server.sockets[0].getsockname()[1]

    def client() -> None:
        sock = socket.create_connection(("127.0.0.1", port), timeout=2)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        try:
            sock.sendall(_bit_word_write([0x0001]))
            deadline = time.perf_counter() + 1.0
            while memory.get_bit(0) != 1:
                if time.perf_counter() >= deadline:
                    raise AssertionError("M0 did not become 1")
                time.sleep(0.0002)
            gap_started = time.perf_counter()
            while time.perf_counter() - gap_started < 0.002:
                pass
            sock.sendall(_bit_word_write([0x0000]))
            time.sleep(0.05)
        finally:
            sock.close()

    try:
        worker = threading.Thread(target=client)
        worker.start()
        await asyncio.to_thread(worker.join, 2.0)
        assert not worker.is_alive()
    finally:
        await server.stop()

    _seq, edges = memory.edges.take(0)
    rising = [edge for edge in edges if edge.value == 1]
    falling = [edge for edge in edges if edge.value == 0]
    assert len(rising) == 1
    assert len(falling) == 1
    width = falling[0].mono_s - rising[0].mono_s
    # 20ms のループ停止を幅に足さない。注入した間隔は 2ms。
    assert 0.001 <= width < 0.01, width


def _bit_word_write(words: list[int]) -> bytes:
    payload = b"".join(mc3e.encode_u16(word) for word in words)
    return mc3e.build_request(
        command=mc3e.CMD_BATCH_WRITE,
        subcommand=mc3e.SUBCMD_WORD,
        device="M",
        head=0,
        points=len(words),
        write_payload=payload,
    )


def _class1_packet(conn_id: int, seq: int, payload: bytes) -> bytes:
    data_item = struct.pack("<H", seq) + payload
    packet = struct.pack("<H", 2)
    packet += struct.pack("<HH", ITEM_SEQUENCED_ADDRESS, 8)
    packet += struct.pack("<II", conn_id, 0)
    packet += struct.pack("<HH", ITEM_CONNECTED_DATA, len(data_item))
    packet += data_item
    return packet


async def _transact(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    request: bytes,
) -> bytes:
    writer.write(request)
    await writer.drain()
    header = await reader.readexactly(9)
    length = mc3e.decode_u16(header, 7)
    rest = await reader.readexactly(length)
    return header + rest
