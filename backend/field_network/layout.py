"""Field Network アセンブリ内オフセット計算。"""

from __future__ import annotations

from dataclasses import dataclass

from ..protocol import ProtocolError

STATUS_OUTPUT_WORDS = 2
RESERVED_INPUT_WORDS = 2
VALID_IO_PORTS = (0, 32, 64, 96, 128)


@dataclass(frozen=True, slots=True)
class AssemblyLayout:
    """VTV 環境設定に対応する Assem10/20 のバイト／ワード割付。"""

    esi_ports: int
    eso_ports: int
    command_words: int
    response_words: int
    result_words: int

    @property
    def esi_words(self) -> int:
        return self.esi_ports // 16

    @property
    def eso_words(self) -> int:
        return self.eso_ports // 16

    # --- Assem10 (T->O / VTV -> PLC) ---
    @property
    def status_byte(self) -> int:
        return 0

    @property
    def status_word(self) -> int:
        return 0

    @property
    def eso_byte(self) -> int:
        return STATUS_OUTPUT_WORDS * 2

    @property
    def eso_word(self) -> int:
        return STATUS_OUTPUT_WORDS

    @property
    def result_byte(self) -> int:
        return self.eso_byte + self.eso_words * 2

    @property
    def result_word(self) -> int:
        return self.eso_word + self.eso_words

    @property
    def response_byte(self) -> int:
        return self.result_byte + self.result_words * 2

    @property
    def response_word(self) -> int:
        return self.result_word + self.result_words

    @property
    def input_words(self) -> int:
        return self.response_word + self.response_words

    @property
    def input_bytes(self) -> int:
        return self.input_words * 2

    # --- Assem20 (O->T / PLC -> VTV) ---
    @property
    def reserved_byte(self) -> int:
        return 0

    @property
    def reserved_word(self) -> int:
        return 0

    @property
    def esi_byte(self) -> int:
        return RESERVED_INPUT_WORDS * 2

    @property
    def esi_word(self) -> int:
        return RESERVED_INPUT_WORDS

    @property
    def command_byte(self) -> int:
        return self.esi_byte + self.esi_words * 2

    @property
    def command_word(self) -> int:
        return self.esi_word + self.esi_words

    @property
    def output_words(self) -> int:
        return self.command_word + self.command_words

    @property
    def output_bytes(self) -> int:
        return self.output_words * 2

    def to_dict(self) -> dict[str, int]:
        return {
            "esi_ports": self.esi_ports,
            "eso_ports": self.eso_ports,
            "esi_words": self.esi_words,
            "eso_words": self.eso_words,
            "command_words": self.command_words,
            "response_words": self.response_words,
            "result_words": self.result_words,
            "status_byte": self.status_byte,
            "eso_byte": self.eso_byte,
            "result_byte": self.result_byte,
            "response_byte": self.response_byte,
            "input_bytes": self.input_bytes,
            "reserved_byte": self.reserved_byte,
            "esi_byte": self.esi_byte,
            "command_byte": self.command_byte,
            "output_bytes": self.output_bytes,
            "command_word": self.command_word,
            "response_word": self.response_word,
            "result_word": self.result_word,
        }


def ports_to_words(ports: int) -> int:
    if ports not in VALID_IO_PORTS:
        raise ProtocolError(
            f"ESI/ESO ポート数は {VALID_IO_PORTS} のいずれかを指定してください"
            f"（指定: {ports}）"
        )
    return ports // 16


def build_layout(
    *,
    esi_ports: int,
    eso_ports: int,
    command_words: int,
    response_words: int,
    result_words: int,
) -> AssemblyLayout:
    ports_to_words(esi_ports)
    ports_to_words(eso_ports)
    if command_words < 4 or command_words % 2:
        raise ProtocolError("コマンドデータサイズは 4 以上の偶数ワードにしてください")
    if response_words < 4 or response_words % 2:
        raise ProtocolError("レスポンスデータサイズは 4 以上の偶数ワードにしてください")
    if result_words < 0 or result_words % 2:
        raise ProtocolError("結果データ出力サイズは 0 以上の偶数ワードにしてください")
    return AssemblyLayout(
        esi_ports=esi_ports,
        eso_ports=eso_ports,
        command_words=command_words,
        response_words=response_words,
        result_words=result_words,
    )


def suggest_layout_from_sizes(
    *,
    input_bytes: int,
    output_bytes: int,
    preferred_command: int = 64,
    preferred_response: int = 64,
) -> dict[str, int]:
    """EDS の入出力バイト数から ESI/ESO・コマンド／結果／レスポンスを推定する。"""
    if input_bytes % 2 or output_bytes % 2:
        raise ProtocolError("入出力サイズは偶数バイトである必要があります")
    in_words = input_bytes // 2
    out_words = output_bytes // 2
    if in_words < 6 or out_words < 6:
        raise ProtocolError("入出力サイズが Field Network コマンド用途として小さすぎます")

    # 出力: reserved(2) + ESI + command
    out_candidates: list[tuple[int, int, int]] = []
    for esi_ports in VALID_IO_PORTS:
        esi_words = esi_ports // 16
        command = out_words - RESERVED_INPUT_WORDS - esi_words
        if command < 4 or command % 2:
            continue
        # preferred_command に近いものを優先
        score = abs(command - preferred_command)
        out_candidates.append((score, esi_ports, command))
    if not out_candidates:
        raise ProtocolError(
            f"出力サイズ {output_bytes} bytes から ESI/コマンド割付を推定できません"
        )
    out_candidates.sort()
    _, esi_ports, command_words = out_candidates[0]

    # 入力: status(2) + ESO + result + response
    in_candidates: list[tuple[int, int, int, int]] = []
    for eso_ports in VALID_IO_PORTS:
        eso_words = eso_ports // 16
        remain = in_words - STATUS_OUTPUT_WORDS - eso_words
        if remain < 4:
            continue
        for response in (preferred_response, 64, 32, 16, 8, 4):
            if response > remain or response % 2:
                continue
            result = remain - response
            if result < 0 or result % 2:
                continue
            # VTV では ESI と ESO を同じポート数にすることが多い
            same_io = 0 if eso_ports == esi_ports else 10
            # 結果 238（ESI/ESO あり時の手動設定）と 240（なし時）の両方を許容
            score = (
                abs(response - preferred_response)
                + min(abs(result - 238), abs(result - 240))
                + same_io
            )
            in_candidates.append((score, eso_ports, result, response))
    if not in_candidates:
        raise ProtocolError(
            f"入力サイズ {input_bytes} bytes から ESO/結果/レスポンス割付を推定できません"
        )
    in_candidates.sort()
    _, eso_ports, result_words, response_words = in_candidates[0]

    layout = build_layout(
        esi_ports=esi_ports,
        eso_ports=eso_ports,
        command_words=command_words,
        response_words=response_words,
        result_words=result_words,
    )
    validate_layout_against_sizes(
        layout, input_bytes=input_bytes, output_bytes=output_bytes
    )
    return {
        "fn_esi_ports": esi_ports,
        "fn_eso_ports": eso_ports,
        "command_size": command_words,
        "response_size": response_words,
        "result_data_size": result_words,
        "fn_input_size": input_bytes,
        "fn_output_size": output_bytes,
    }


def validate_layout_against_sizes(
    layout: AssemblyLayout,
    *,
    input_bytes: int,
    output_bytes: int,
) -> None:
    """計算サイズと EDS／接続サイズの一致を検証する。"""
    if layout.input_bytes != input_bytes:
        raise ProtocolError(
            "入力アセンブリサイズが一致しません: "
            f"割付 {layout.input_bytes} bytes ≠ EDS/設定 {input_bytes} bytes。"
            " ESI/ESO・結果・レスポンス語数と EDS を合わせてください"
        )
    if layout.output_bytes != output_bytes:
        raise ProtocolError(
            "出力アセンブリサイズが一致しません: "
            f"割付 {layout.output_bytes} bytes ≠ EDS/設定 {output_bytes} bytes。"
            " ESI・コマンド語数と EDS を合わせてください"
        )


# ステータス出力ビット（Assem10 byte0）
STATUS_BIT_AUTO = 0
STATUS_BIT_BUSY = 1
STATUS_BIT_RESULT_VALID = 2
STATUS_BIT_ERROR = 3
