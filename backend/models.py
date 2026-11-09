from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

from .i18n import DEFAULT_LANG, LocalizedError, Msg, rebuild_error, t

StatusSignalSource = Literal["status", "eso", "plo"]
StatusSignalRole = Literal["none", "busy", "auto", "result_valid", "error"]


class StatusSignalMapping(BaseModel):
    """ステータス信号の監視／BUSY 判定用割付（FN / PLCLINK 共通）。"""

    id: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=40)
    source: StatusSignalSource = "status"
    bit: int | None = Field(default=None, ge=0, le=2047)
    eso_port: int | None = Field(default=None, ge=1, le=128)
    plo_port: int | None = Field(default=None, ge=1, le=256)
    role: StatusSignalRole = "none"

    @model_validator(mode="after")
    def validate_source_fields(self) -> StatusSignalMapping:
        if self.source == "status":
            if self.bit is None:
                raise LocalizedError("models.signal.bitRequired", label=self.label)
        elif self.source == "eso":
            if self.eso_port is None:
                raise LocalizedError(
                    "models.signal.esoPortRequired", label=self.label
                )
        elif self.source == "plo":
            if self.plo_port is None:
                raise LocalizedError(
                    "models.signal.ploPortRequired", label=self.label
                )
        return self


def sanitize_port_names(value: object) -> dict[str, str]:
    """ポート番号→名称の辞書を正規化する（キーは文字列のポート番号）。"""
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key, name in value.items():
        try:
            port = int(key)
        except (TypeError, ValueError):
            continue
        if port < 1 or port > 256:
            continue
        text = str(name or "").strip()[:40]
        if text:
            result[str(port)] = text
    return result


def port_display_label(
    port: int,
    names: dict[str, str] | None,
    *,
    fallback: str,
) -> str:
    """監視表示用のポートラベル。名称があれば『fallback: 名称』。"""
    custom = (names or {}).get(str(port), "").strip()
    if custom:
        return f"{fallback}: {custom}"
    return fallback


def default_fn_status_signals(lang: str = DEFAULT_LANG) -> list[StatusSignalMapping]:
    """VTV 既定のステータス出力領域割付（Field Network）。"""
    return [
        StatusSignalMapping(
            id="auto",
            label=t("models.defaultSignal.auto", lang),
            source="status",
            bit=0,
            role="auto",
        ),
        StatusSignalMapping(
            id="busy", label="BUSY", source="status", bit=1, role="busy"
        ),
        StatusSignalMapping(
            id="result_valid",
            label=t("models.defaultSignal.resultValid", lang),
            source="status",
            bit=2,
            role="result_valid",
        ),
        StatusSignalMapping(
            id="error",
            label=t("models.defaultSignal.error", lang),
            source="status",
            bit=3,
            role="error",
        ),
    ]


def default_plclink_status_signals(
    *, busy_port: int = 1
) -> list[StatusSignalMapping]:
    """VTV 既定に近い PLCLINK ステータス信号割付（PLO ポート）。"""
    port = max(1, min(256, int(busy_port) or 1))
    return [
        StatusSignalMapping(
            id="busy",
            label="BUSY",
            source="plo",
            plo_port=port,
            role="busy",
        ),
    ]


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
    pli_address: int = Field(default=0, ge=0, le=65535)
    pli_port_count: int = Field(default=32, ge=1, le=256)
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
    fn_status_signals: list[StatusSignalMapping] = Field(
        default_factory=default_fn_status_signals
    )
    plclink_status_signals: list[StatusSignalMapping] = Field(default_factory=list)
    # ポート名称（キーは "1","2",... / 値は表示名。空は未設定）
    pli_port_names: dict[str, str] = Field(default_factory=dict)
    plo_port_names: dict[str, str] = Field(default_factory=dict)
    esi_port_names: dict[str, str] = Field(default_factory=dict)
    eso_port_names: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "pli_port_names",
        "plo_port_names",
        "esi_port_names",
        "eso_port_names",
        mode="before",
    )
    @classmethod
    def validate_port_names(cls, value: object) -> dict[str, str]:
        return sanitize_port_names(value)

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
            raise LocalizedError("models.host.required")
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
        busy_port = int(values.get("busy_port") or 1)
        if not values.get("plclink_status_signals"):
            values["plclink_status_signals"] = [
                item.model_dump()
                for item in default_plclink_status_signals(busy_port=busy_port)
            ]
        rpi = values.get("fn_rpi_us")
        if rpi is not None and not isinstance(rpi, bool):
            try:
                if int(rpi) < 2000:
                    # VTV EDS の RPI 下限は 2000μs。1ms 設定は接続できない。
                    values["fn_rpi_us"] = 2000
            except (TypeError, ValueError):
                pass
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
            if not values.get("fn_status_signals"):
                values["fn_status_signals"] = [
                    item.model_dump() for item in default_fn_status_signals()
                ]
        return values

    @model_validator(mode="after")
    def validate_plclink_layout(self) -> ProtocolSettings:
        if self.command_size % 2:
            raise LocalizedError("models.commandSizeEven")
        if self.response_size % 2:
            raise LocalizedError("models.responseSizeEven")
        if self.result_data_size % 2:
            raise LocalizedError("models.resultSizeEven")
        if self.result_data_watch_words % 2:
            raise LocalizedError("models.resultWatchEven")
        if self.fn_input_size % 2:
            raise LocalizedError("models.fnInputEven")
        if self.fn_output_size % 2:
            raise LocalizedError("models.fnOutputEven")

        if self.transport == "field_network":
            if self.host in {"0.0.0.0", "127.0.0.1", "localhost"}:
                raise LocalizedError("models.fnHostInvalid")
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
                raise rebuild_error(exc, LocalizedError) from exc
            self._validate_fn_status_signals(layout)
            return self

        self._validate_plclink_status_signals()
        if self.busy_port > self.plo_port_count:
            raise LocalizedError("models.busyPortExceedsPlo")
        if self.busy_address > 65535:
            raise LocalizedError(
                "models.busyAddressOutOfRange",
                plo_address=self.plo_address,
                busy_port=self.busy_port,
            )
        plo_end = self.plo_address + self.plo_port_count - 1
        if plo_end > 65535:
            raise LocalizedError("models.ploRangeOverflow")
        pli_end = self.pli_address + self.pli_port_count - 1
        if pli_end > 65535:
            raise LocalizedError("models.pliRangeOverflow")
        if _ranges_overlap(
            self.pli_address,
            self.pli_address + self.pli_port_count,
            self.plo_address,
            self.plo_address + self.plo_port_count,
        ):
            raise LocalizedError("models.pliPloOverlap")
        command_start = self.command_address
        command_end = self.command_address + self.command_size
        response_start = self.response_address
        response_end = self.response_address + self.response_size
        if _ranges_overlap(command_start, command_end, response_start, response_end):
            raise LocalizedError("models.commandResponseOverlap")

        d_ranges: list[tuple[Msg, int, int]] = [
            (Msg("models.area.command"), command_start, command_end),
            (Msg("models.area.response"), response_start, response_end),
        ]
        if self.result_data_enabled:
            result_end = self.result_data_address + self.result_data_size
            if result_end > 65536:
                raise LocalizedError("models.resultRangeOverflow")
            d_ranges.append(
                (Msg("models.area.result"), self.result_data_address, result_end)
            )
        if self.notify_area_enabled:
            notify_end = self.notify_address + 8
            if notify_end > 65536:
                raise LocalizedError("models.notifyRangeOverflow")
            d_ranges.append(
                (Msg("models.area.notify"), self.notify_address, notify_end)
            )

        for index, (left_name, left_start, left_end) in enumerate(d_ranges):
            for right_name, right_start, right_end in d_ranges[index + 1 :]:
                if _ranges_overlap(left_start, left_end, right_start, right_end):
                    raise LocalizedError(
                        "models.areaOverlap", left=left_name, right=right_name
                    )
        return self

    def _validate_fn_status_signals(self, layout: object) -> None:
        from .field_network.layout import resolve_status_signal_bit

        signals = self.fn_status_signals
        if not signals:
            raise LocalizedError("models.fnSignalsEmpty")
        ids = [item.id for item in signals]
        if len(ids) != len(set(ids)):
            raise LocalizedError("models.signalIdDuplicate")
        busy_count = sum(1 for item in signals if item.role == "busy")
        if busy_count != 1:
            raise LocalizedError("models.busyRoleCount", count=busy_count)
        max_bit = self.fn_input_size * 8 - 1
        for item in signals:
            if item.source == "plo":
                raise LocalizedError(
                    "models.signal.fnPloUnsupported", label=item.label
                )
            if item.source == "eso":
                if self.fn_eso_ports <= 0:
                    raise LocalizedError(
                        "models.signal.esoPortsZero", label=item.label
                    )
                assert item.eso_port is not None
                if item.eso_port > self.fn_eso_ports:
                    raise LocalizedError(
                        "models.signal.esoPortExceeds",
                        label=item.label,
                        port=item.eso_port,
                        count=self.fn_eso_ports,
                    )
            bit = resolve_status_signal_bit(item, layout)  # type: ignore[arg-type]
            if bit < 0 or bit > max_bit:
                raise LocalizedError(
                    "models.signal.bitOutOfRange",
                    label=item.label,
                    bit=bit,
                    max_bit=max_bit,
                )

    def _validate_plclink_status_signals(self) -> None:
        signals = self.plclink_status_signals
        if not signals:
            raise LocalizedError("models.plclinkSignalsEmpty")
        ids = [item.id for item in signals]
        if len(ids) != len(set(ids)):
            raise LocalizedError("models.signalIdDuplicate")
        busy_count = sum(1 for item in signals if item.role == "busy")
        if busy_count != 1:
            raise LocalizedError("models.busyRoleCount", count=busy_count)
        for item in signals:
            if item.source != "plo":
                raise LocalizedError(
                    "models.signal.plclinkSourceMustBePlo", label=item.label
                )
            assert item.plo_port is not None
            if item.plo_port > self.plo_port_count:
                raise LocalizedError(
                    "models.signal.ploPortExceeds",
                    label=item.label,
                    port=item.plo_port,
                    count=self.plo_port_count,
                )
        busy = next(item for item in signals if item.role == "busy")
        assert busy.plo_port is not None
        self.busy_port = busy.plo_port

    def find_status_signal(
        self, *, role: StatusSignalRole | None = None, signal_id: str | None = None
    ) -> StatusSignalMapping | None:
        signals = (
            self.fn_status_signals
            if self.transport == "field_network"
            else self.plclink_status_signals
        )
        for item in signals:
            if role is not None and item.role == role:
                return item
            if signal_id is not None and item.id == signal_id:
                return item
        return None


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
            raise LocalizedError("models.watch.mDeviceBitOnly")
        if self.device == "D" and self.format == "bit":
            raise LocalizedError("models.watch.dDeviceNoBit")
        if self.device in {"IN", "OUT"} and self.format == "bit":
            return self
        needed = 2 if self.format in {"int32", "fixed"} else self.length
        if self.format in {"bit", "word"}:
            needed = 1
        if self.device in {"D", "M"} and self.address + needed > 65536:
            raise LocalizedError("models.watch.addressOutOfRange")
        return self


class MemoryReadRequest(BaseModel):
    items: list[MemoryWatchItem] = Field(min_length=1, max_length=512)


class LocalIoRequest(BaseModel):
    """PLI / ESI ポートの単純な ON/OFF。"""

    settings: ProtocolSettings
    code: Literal["PLI", "ESI"]
    state: Literal[0, 1, "0", "1", "on", "off", "ON", "OFF"] = 1
    ports: str = Field(min_length=1, max_length=200)


def _coerce_step_id(value: object) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:64]


class _StepIdentity(BaseModel):
    id: Annotated[str | None, BeforeValidator(_coerce_step_id)] = None


class CommandStep(_StepIdentity):
    type: Literal["command"]
    command: str = Field(min_length=3, max_length=3)
    arguments: dict[str, str | int | float] = Field(default_factory=dict)
    # 引数名 → 変数カードの名前。指定した引数だけ、実行時にその変数で置き換える
    argument_variables: dict[str, str] = Field(default_factory=dict)
    # True のとき送信後に装置応答を待たず、すぐ次のカードへ進む
    ignore_response: bool = False


class DelayStep(_StepIdentity):
    type: Literal["delay"]
    milliseconds: int = Field(default=100, ge=0, le=3_600_000)


class BreakStep(_StepIdentity):
    type: Literal["break"]


class NoteStep(_StepIdentity):
    type: Literal["note"]
    text: str = Field(default="", max_length=500)


class VariableStep(_StepIdentity):
    type: Literal["variable"]
    name: str = Field(default="", max_length=40)
    source: Literal[
        "last_response",
        "last_status",
        "card_response",
        "card_status",
        "output_port",
        "result_data",
        "literal",
    ] = "last_response"
    card_id: str = ""
    port: int = Field(default=1, ge=1, le=256)
    offset: int = Field(default=0, ge=0, le=65534)
    result_format: Literal["dec", "fixed", "hex", "string"] = "dec"
    value: str = Field(default="", max_length=500)


class IfStep(_StepIdentity):
    type: Literal["if"]
    source: Literal["status", "response"] = "status"
    operator: Literal["equals", "contains", "not_contains"] = "equals"
    value: str = "AK"
    then_steps: list[SequenceStep] = Field(default_factory=list)
    else_steps: list[SequenceStep] = Field(default_factory=list)


class LoopStep(_StepIdentity):
    type: Literal["loop"]
    count: int = Field(default=2, ge=1, le=10_000)
    steps: list[SequenceStep] = Field(default_factory=list)


SequenceStep = Annotated[
    CommandStep | DelayStep | BreakStep | NoteStep | VariableStep | IfStep | LoopStep,
    Field(discriminator="type"),
]


class SequenceRequest(BaseModel):
    settings: ProtocolSettings
    steps: list[SequenceStep]


class SendRequest(BaseModel):
    settings: ProtocolSettings
    command: str = Field(min_length=1, max_length=4096)
    expect_result: bool = False
