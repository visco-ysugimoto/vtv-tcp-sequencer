from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator


class ProtocolSettings(BaseModel):
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

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("装置IPを入力してください")
        return value


class CommandStep(BaseModel):
    type: Literal["command"]
    command: str = Field(min_length=3, max_length=3)
    arguments: dict[str, str | int] = Field(default_factory=dict)


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
