from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator


class ProtocolSettings(BaseModel):
    transport: Literal["tcp", "plclink", "field_network"] = "tcp"
    host: str = ""
    port: int = Field(default=55555, ge=1, le=65535)
    timeout: float = Field(default=5.0, gt=0, le=300)
    input_terminator: Literal["CR"] = "CR"
    output_terminator: Literal["CR", "CRLF"] = "CR"
    separator: Literal[
        "space", "comma", "tab", "underscore", "hyphen", "none"
    ] = "space"
    header_separator: bool = False
    footer_separator: bool = False
    checksum: bool = True
    input_response: bool = True
    encoding: Literal["cp932", "utf-8"] = "cp932"
    line_number_digits: Literal[2, 3] = 2
    # PLCLINK SoftPLC / Field Network 共通（コマンド・レスポンス語数）
    command_address: int = Field(default=4096, ge=0, le=65535)
    command_size: int = Field(default=64, ge=4, le=512)
    response_address: int = Field(default=8192, ge=0, le=65535)
    response_size: int = Field(default=64, ge=4, le=512)
    plo_address: int = Field(default=1024, ge=0, le=65535)
    plo_port_count: int = Field(default=32, ge=1, le=256)
    busy_port: int = Field(default=1, ge=1, le=256)
    byte_order: Literal["high_low", "low_high"] = "high_low"
    # 結果データ出力（VTV 環境設定 → PLCLINK / Field Network）
    result_data_enabled: bool = False
    result_data_address: int = Field(default=512, ge=0, le=65535)
    result_data_size: int = Field(default=2048, ge=0, le=65536)
    result_data_watch_words: int = Field(default=64, ge=0, le=512)
    # VTV「環境設定 → 詳細設定 → 小数点以下桁数」と合わせる
    result_data_decimals: int = Field(default=3, ge=0, le=9)
    notify_area_enabled: bool = False
    notify_address: int = Field(default=2560, ge=0, le=65535)
    # Field Network（EtherNet/IP）
    fn_esi_ports: Literal[0, 32, 64, 96, 128] = 32
    fn_eso_ports: Literal[0, 32, 64, 96, 128] = 32
    fn_input_size: int = Field(default=612, ge=4, le=1444)
    fn_output_size: int = Field(default=136, ge=4, le=1444)
    fn_rpi_us: int = Field(default=10_000, ge=2_000, le=1_000_000)
    fn_connection_path: str = "20 04 24 01 2C 14 2C 0A"
    fn_o_to_t_header_bytes: Literal[0, 4] = 4
    fn_eds_name: str = ""

    @computed_field
    @property
    def busy_address(self) -> int:
        """BUSY = 仮想出力(PLO)先頭 + ポート番号 - 1。"""
        return self.plo_address + self.busy_port - 1

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("装置IP / 待受アドレスを入力してください")
        return value

    @model_validator(mode="before")
    @classmethod
    def migrate_busy_settings(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        values = dict(data)
        if "plo_address" not in values and "busy_address" in values:
            values["plo_address"] = values["busy_address"]
            values.setdefault("busy_port", 1)
        values.pop("busy_address", None)
        if values.get("transport") == "field_network":
            values.setdefault("port", 44818)
            # VTV 典型設定: ESI/ESO 32, コマンド64, 結果238, レスポンス64
            values.setdefault("result_data_size", 238)
            values.setdefault("fn_input_size", 612)
            values.setdefault("fn_output_size", 136)
            values.setdefault("fn_esi_ports", 32)
            values.setdefault("fn_eso_ports", 32)
            values.setdefault("command_size", 64)
            values.setdefault("response_size", 64)
        return values

    @model_validator(mode="after")
    def validate_plclink_layout(self) -> ProtocolSettings:
        if self.command_size % 2:
            raise ValueError("コマンドアドレスサイズは偶数にしてください")
        if self.response_size % 2:
            raise ValueError("レスポンスアドレスサイズは偶数にしてください")
        if self.result_data_size % 2:
            raise ValueError("結果データ出力サイズは偶数にしてください")
        if self.result_data_watch_words % 2:
            raise ValueError("結果データ監視ワード数は偶数にしてください")
        if self.fn_input_size % 2:
            raise ValueError("Field Network 入力サイズは偶数バイトにしてください")
        if self.fn_output_size % 2:
            raise ValueError("Field Network 出力サイズは偶数バイトにしてください")

        if self.transport == "field_network":
            if self.host in {"0.0.0.0", "127.0.0.1", "localhost"}:
                raise ValueError(
                    "Field Network の装置 IP には VTV 本体の IP を指定してください"
                    "（PLCLINK の待受アドレス 0.0.0.0 とは異なります）"
                )
            from .field_network.layout import build_layout, validate_layout_against_sizes
            from .protocol import ProtocolError

            try:
                layout = build_layout(
                    esi_ports=self.fn_esi_ports,
                    eso_ports=self.fn_eso_ports,
                    command_words=self.command_size,
                    response_words=self.response_size,
                    result_words=self.result_data_size,
                )
                validate_layout_against_sizes(
                    layout,
                    input_bytes=self.fn_input_size,
                    output_bytes=self.fn_output_size,
                )
            except ProtocolError as exc:
                raise ValueError(str(exc)) from exc
            return self

        if self.busy_port > self.plo_port_count:
            raise ValueError(
                "BUSYポート番号は仮想出力ポート数以下にしてください"
            )
        if self.busy_address > 65535:
            raise ValueError(
                "BUSYアドレスが範囲外です"
                f"（PLO先頭 M{self.plo_address} + Port {self.busy_port}）"
            )
        plo_end = self.plo_address + self.plo_port_count - 1
        if plo_end > 65535:
            raise ValueError(
                "仮想出力ポート範囲がデバイス範囲を超えています"
            )
        command_start = self.command_address
        command_end = self.command_address + self.command_size
        response_start = self.response_address
        response_end = self.response_address + self.response_size
        if _ranges_overlap(command_start, command_end, response_start, response_end):
            raise ValueError(
                "コマンド領域とレスポンス領域が重複しています"
            )

        d_ranges: list[tuple[str, int, int]] = [
            ("コマンド領域", command_start, command_end),
            ("レスポンス領域", response_start, response_end),
        ]
        if self.result_data_enabled:
            result_end = self.result_data_address + self.result_data_size
            if result_end > 65536:
                raise ValueError(
                    "結果データ出力範囲がデバイス範囲を超えています"
                )
            d_ranges.append(
                ("結果データ領域", self.result_data_address, result_end)
            )
        if self.notify_area_enabled:
            notify_end = self.notify_address + 8
            if notify_end > 65536:
                raise ValueError(
                    "通知エリア範囲がデバイス範囲を超えています"
                )
            d_ranges.append(("通知エリア", self.notify_address, notify_end))

        for index, (left_name, left_start, left_end) in enumerate(d_ranges):
            for right_name, right_start, right_end in d_ranges[index + 1 :]:
                if _ranges_overlap(left_start, left_end, right_start, right_end):
                    raise ValueError(
                        f"{left_name}と{right_name}が重複しています"
                    )
        return self


def _ranges_overlap(start_a: int, end_a: int, start_b: int, end_b: int) -> bool:
    return not (end_a <= start_b or end_b <= start_a)


class MemoryWatchItem(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=100)
    group: str = Field(default="", max_length=40)
    device: Literal["D", "M", "IN", "OUT"]
    address: int = Field(ge=0, le=1_048_575)
    format: Literal["bit", "word", "int32", "fixed", "string"]
    length: int = Field(default=8, ge=1, le=128)
    decimals: int = Field(default=3, ge=0, le=9)

    @model_validator(mode="after")
    def validate_device_format(self) -> MemoryWatchItem:
        if self.device == "M" and self.format != "bit":
            raise ValueError("Mデバイスの表示形式はbitのみ指定できます")
        if self.device == "D" and self.format == "bit":
            raise ValueError("Dデバイスにbit形式は指定できません")
        if self.device in {"IN", "OUT"} and self.format == "bit":
            return self
        needed = 2 if self.format in {"int32", "fixed"} else self.length
        if self.format in {"bit", "word"}:
            needed = 1
        if self.device in {"D", "M"} and self.address + needed > 65536:
            raise ValueError("監視アドレスがデバイス範囲を超えています")
        return self


class MemoryReadRequest(BaseModel):
    items: list[MemoryWatchItem] = Field(min_length=1, max_length=512)


class CommandStep(BaseModel):
    type: Literal["command"]
    command: str = Field(min_length=3, max_length=3)
    arguments: dict[str, str | int | float] = Field(default_factory=dict)


class DelayStep(BaseModel):
    type: Literal["delay"]
    milliseconds: int = Field(default=100, ge=0, le=3_600_000)


class BreakStep(BaseModel):
    type: Literal["break"]


class IfStep(BaseModel):
    type: Literal["if"]
    source: Literal["status", "response"] = "status"
    operator: Literal["equals", "contains", "not_contains"] = "equals"
    value: str = "AK"
    then_steps: list[SequenceStep] = Field(default_factory=list)
    else_steps: list[SequenceStep] = Field(default_factory=list)


class LoopStep(BaseModel):
    type: Literal["loop"]
    count: int = Field(default=2, ge=1, le=10_000)
    steps: list[SequenceStep] = Field(default_factory=list)


SequenceStep = Annotated[
    CommandStep | DelayStep | BreakStep | IfStep | LoopStep,
    Field(discriminator="type"),
]


class SequenceRequest(BaseModel):
    settings: ProtocolSettings
    steps: list[SequenceStep]


class SendRequest(BaseModel):
    settings: ProtocolSettings
    command: str = Field(min_length=1, max_length=4096)
    expect_result: bool = False
