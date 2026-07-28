from __future__ import annotations

from dataclasses import dataclass

from .memory import DeviceMemory

# MC 3E binary (Q/L/QnA series) — based on pymcprotocol framing.
SUBHEADER_REQUEST = 0x5000
SUBHEADER_RESPONSE = 0xD000
DEVICE_D = 0xA8
DEVICE_M = 0x90
CMD_BATCH_READ = 0x0401
CMD_BATCH_WRITE = 0x1401
SUBCMD_WORD = 0x0000
SUBCMD_BIT = 0x0001

CODE_BY_DEVICE = {
    DEVICE_D: "D",
    DEVICE_M: "M",
}
DEVICE_BY_NAME = {
    "D": DEVICE_D,
    "M": DEVICE_M,
}


@dataclass(slots=True)
class McRequest:
    network: int
    pc: int
    dest_moduleio: int
    dest_modulesta: int
    timer: int
    command: int
    subcommand: int
    device: str
    head: int
    points: int
    payload: bytes


class McProtocolError(Exception):
    def __init__(self, end_code: int, message: str = ""):
        self.end_code = end_code
        super().__init__(message or f"MC end code 0x{end_code:04X}")


def encode_u16(value: int) -> bytes:
    return int(value & 0xFFFF).to_bytes(2, "little", signed=False)


def encode_i16(value: int) -> bytes:
    return int(value).to_bytes(2, "little", signed=True)


def decode_u16(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=False)


def decode_i16(data: bytes, offset: int = 0) -> int:
    return int.from_bytes(data[offset : offset + 2], "little", signed=True)


def pack_bits(values: list[int]) -> bytes:
    packed = bytearray((len(values) + 1) // 2)
    for index, value in enumerate(values):
        if value not in (0, 1):
            raise ValueError("ビット値は 0 または 1 です")
        bit_index = 4 if index % 2 == 0 else 0
        packed[index // 2] |= value << bit_index
    return bytes(packed)


def unpack_bits(data: bytes, count: int) -> list[int]:
    values: list[int] = []
    for index in range(count):
        byte = data[index // 2]
        bit_index = 4 if index % 2 == 0 else 0
        values.append(1 if byte & (1 << bit_index) else 0)
    return values


def build_device_data(device: str, head: int) -> bytes:
    code = DEVICE_BY_NAME.get(device.upper())
    if code is None:
        raise McProtocolError(0xC050, f"未対応デバイス: {device}")
    return head.to_bytes(3, "little") + code.to_bytes(1, "little")


def parse_device_data(data: bytes) -> tuple[str, int]:
    if len(data) < 4:
        raise McProtocolError(0xC050, "デバイス指定が不正です")
    head = int.from_bytes(data[:3], "little")
    code = data[3]
    name = CODE_BY_DEVICE.get(code)
    if name is None:
        raise McProtocolError(0xC050, f"未対応デバイスコード: 0x{code:02X}")
    return name, head


def build_request(
    *,
    command: int,
    subcommand: int,
    device: str,
    head: int,
    points: int,
    write_payload: bytes = b"",
    network: int = 0,
    pc: int = 0xFF,
    dest_moduleio: int = 0x3FF,
    dest_modulesta: int = 0,
    timer: int = 4,
) -> bytes:
    request = (
        encode_u16(command)
        + encode_u16(subcommand)
        + build_device_data(device, head)
        + encode_u16(points)
        + write_payload
    )
    length = 2 + len(request)  # timer + request
    return (
        SUBHEADER_REQUEST.to_bytes(2, "big")
        + bytes([network & 0xFF, pc & 0xFF])
        + encode_u16(dest_moduleio)
        + bytes([dest_modulesta & 0xFF])
        + encode_u16(length)
        + encode_u16(timer)
        + request
    )


def build_response(
    request: McRequest,
    *,
    end_code: int = 0,
    data: bytes = b"",
) -> bytes:
    body = encode_u16(end_code) + data
    return (
        SUBHEADER_RESPONSE.to_bytes(2, "big")
        + bytes([request.network & 0xFF, request.pc & 0xFF])
        + encode_u16(request.dest_moduleio)
        + bytes([request.dest_modulesta & 0xFF])
        + encode_u16(len(body))
        + body
    )


def parse_request(frame: bytes) -> McRequest:
    if len(frame) < 15:
        raise McProtocolError(0xC050, "要求電文が短すぎます")
    subheader = int.from_bytes(frame[0:2], "big")
    if subheader != SUBHEADER_REQUEST:
        raise McProtocolError(0xC050, f"不正なサブヘッダ: 0x{subheader:04X}")
    network = frame[2]
    pc = frame[3]
    dest_moduleio = decode_u16(frame, 4)
    dest_modulesta = frame[6]
    length = decode_u16(frame, 7)
    expected = 9 + length
    if len(frame) < expected:
        raise McProtocolError(0xC050, "要求電文長が不足しています")
    timer = decode_u16(frame, 9)
    command = decode_u16(frame, 11)
    subcommand = decode_u16(frame, 13)
    device, head = parse_device_data(frame[15:19])
    points = decode_u16(frame, 19)
    payload = frame[21:expected]
    return McRequest(
        network=network,
        pc=pc,
        dest_moduleio=dest_moduleio,
        dest_modulesta=dest_modulesta,
        timer=timer,
        command=command,
        subcommand=subcommand,
        device=device,
        head=head,
        points=points,
        payload=payload,
    )


def handle_request(memory: DeviceMemory, frame: bytes) -> bytes:
    request: McRequest | None = None
    try:
        request = parse_request(frame)
        data = _execute(memory, request)
        return build_response(request, end_code=0, data=data)
    except (McProtocolError, IndexError, ValueError) as exc:
        end_code = exc.end_code if isinstance(exc, McProtocolError) else 0xC050
        # Prefer echoing header fields when parse partially succeeded.
        fallback = McRequest(
            network=frame[2] if len(frame) > 2 else 0,
            pc=frame[3] if len(frame) > 3 else 0xFF,
            dest_moduleio=decode_u16(frame, 4) if len(frame) >= 6 else 0x3FF,
            dest_modulesta=frame[6] if len(frame) > 6 else 0,
            timer=0,
            command=0,
            subcommand=0,
            device="D",
            head=0,
            points=0,
            payload=b"",
        )
        if request is None:
            try:
                request = parse_request(frame)
            except McProtocolError:
                request = fallback
        return build_response(request, end_code=end_code)


def _execute(memory: DeviceMemory, request: McRequest) -> bytes:
    if request.command == CMD_BATCH_READ and request.subcommand == SUBCMD_WORD:
        if request.device != "D":
            raise McProtocolError(0xC050, "ワード読出は D のみ対応")
        words = memory.read_words(request.head, request.points)
        return b"".join(encode_i16(value) for value in words)

    if request.command == CMD_BATCH_READ and request.subcommand == SUBCMD_BIT:
        if request.device != "M":
            raise McProtocolError(0xC050, "ビット読出は M のみ対応")
        bits = memory.read_bits(request.head, request.points)
        return pack_bits(bits)

    if request.command == CMD_BATCH_WRITE and request.subcommand == SUBCMD_WORD:
        if request.device != "D":
            raise McProtocolError(0xC050, "ワード書込は D のみ対応")
        needed = request.points * 2
        if len(request.payload) < needed:
            raise McProtocolError(0xC050, "書込データが不足しています")
        values = [
            decode_i16(request.payload, index * 2)
            for index in range(request.points)
        ]
        memory.write_words(request.head, values)
        return b""

    if request.command == CMD_BATCH_WRITE and request.subcommand == SUBCMD_BIT:
        if request.device != "M":
            raise McProtocolError(0xC050, "ビット書込は M のみ対応")
        needed = (request.points + 1) // 2
        if len(request.payload) < needed:
            raise McProtocolError(0xC050, "書込データが不足しています")
        bits = unpack_bits(request.payload, request.points)
        memory.write_bits(request.head, bits)
        return b""

    raise McProtocolError(
        0xC050,
        f"未対応コマンド: 0x{request.command:04X}/0x{request.subcommand:04X}",
    )


def minimum_frame_length(buffer: bytes) -> int | None:
    """バッファ先頭が完全な要求電文になるまでの必要長。不足時は None。"""
    if len(buffer) < 9:
        return None
    if int.from_bytes(buffer[0:2], "big") != SUBHEADER_REQUEST:
        return 2  # 不正だが呼び出し側で切り捨て判定させる
    length = decode_u16(buffer, 7)
    return 9 + length
