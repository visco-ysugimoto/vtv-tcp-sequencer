from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class ProtocolSettings(BaseModel):
    transport: Literal["tcp", "plclink"] = "tcp"
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
    # PLCLINK SoftPLC
    command_address: int = Field(default=4096, ge=0, le=65535)
    command_size: int = Field(default=64, ge=4, le=256)
    response_address: int = Field(default=8192, ge=0, le=65535)
    response_size: int = Field(default=64, ge=8, le=256)
    busy_address: int = Field(default=1024, ge=0, le=65535)
    byte_order: Literal["high_low", "low_high"] = "high_low"

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("装置IP / 待受アドレスを入力してください")
        return value

    @model_validator(mode="after")
    def validate_plclink_layout(self) -> ProtocolSettings:
        if self.command_size % 2:
            raise ValueError("コマンドアドレスサイズは偶数にしてください")
        if self.response_size % 2:
            raise ValueError("レスポンスアドレスサイズは偶数にしてください")
        command_end = self.command_address + self.command_size
        response_end = self.response_address + self.response_size
        if not (
            command_end <= self.response_address
            or response_end <= self.command_address
        ):
            raise ValueError(
                "コマンド領域とレスポンス領域が重複しています"
            )
        return self


class MemoryWatchItem(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(default="", max_length=100)
    device: Literal["D", "M"]
    address: int = Field(ge=0, le=65535)
    format: Literal["bit", "word", "int32", "fixed", "string"]
    length: int = Field(default=8, ge=1, le=128)
    decimals: int = Field(default=3, ge=0, le=9)

    @model_validator(mode="after")
    def validate_device_format(self) -> MemoryWatchItem:
        if self.device == "M" and self.format != "bit":
            raise ValueError("Mデバイスの表示形式はbitのみ指定できます")
        if self.device == "D" and self.format == "bit":
            raise ValueError("Dデバイスにbit形式は指定できません")
        needed = 2 if self.format in {"int32", "fixed"} else self.length
        if self.format in {"bit", "word"}:
            needed = 1
        if self.address + needed > 65536:
            raise ValueError("監視アドレスがデバイス範囲を超えています")
        return self


class MemoryReadRequest(BaseModel):
    items: list[MemoryWatchItem] = Field(min_length=1, max_length=128)


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
