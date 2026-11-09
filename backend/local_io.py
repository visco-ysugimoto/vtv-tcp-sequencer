"""シーケンサ側の仮想入力（PLI / ESI）一括 ON/OFF。"""

from __future__ import annotations

import re
from typing import Any

from .i18n import DEFAULT_LANG, t
from .models import ProtocolSettings
from .protocol import CommandResult, ProtocolError

# カタログ上は TCP コマンドに見せるが、実体は SoftPLC / Scanner バッファ操作。
LOCAL_IO_COMMANDS: dict[str, dict[str, Any]] = {
    "PLI": {
        "transports": frozenset({"plclink"}),
        "label": "PLI",
        "reason_other": "local.reason.pli",
    },
    "ESI": {
        "transports": frozenset({"field_network"}),
        "label": "ESI",
        "reason_other": "local.reason.esi",
    },
}


def is_local_io_command(code: str) -> bool:
    return code.upper() in LOCAL_IO_COMMANDS


def local_io_metadata(
    tcp_code: str, lang: str = DEFAULT_LANG
) -> dict[str, object] | None:
    code = tcp_code.upper()
    info = LOCAL_IO_COMMANDS.get(code)
    if info is None:
        return None
    transports = info["transports"]
    reason_other = t(str(info["reason_other"]), lang)
    return {
        "local_io": True,
        "plclink_supported": "plclink" in transports,
        "plclink_code": code,
        "plclink_reason": None
        if "plclink" in transports
        else reason_other,
        "field_network_supported": "field_network" in transports,
        "field_network_code": code,
        "field_network_reason": None
        if "field_network" in transports
        else reason_other,
    }


def parse_port_list(text: str, *, max_port: int, label: str) -> list[int]:
    """'1,2,5-8' 形式をポート番号リストへ。"""
    raw = str(text or "").strip()
    if not raw:
        raise ProtocolError("local.portsRequired", label=label)
    ports: list[int] = []
    for token in re.split(r"[\s,;]+", raw):
        if not token:
            continue
        if "-" in token:
            left, right = token.split("-", 1)
            try:
                start = int(left)
                end = int(right)
            except ValueError as exc:
                raise ProtocolError("local.portRangeInvalid", token=token) from exc
            if start > end:
                start, end = end, start
            for port in range(start, end + 1):
                ports.append(port)
        else:
            try:
                ports.append(int(token))
            except ValueError as exc:
                raise ProtocolError("local.portInvalid", token=token) from exc
    if not ports:
        raise ProtocolError("local.portsRequired", label=label)
    unique = sorted(set(ports))
    for port in unique:
        if port < 1 or port > max_port:
            raise ProtocolError(
                "local.portOutOfRange", label=label, port=port, max=max_port
            )
    return unique


def parse_state(raw: object) -> int:
    text = str(raw).strip().lower()
    if text in {"1", "on", "true"}:
        return 1
    if text in {"0", "off", "false"}:
        return 0
    raise ProtocolError("local.stateInvalid")


def format_local_io_display(code: str, arguments: dict[str, Any]) -> str:
    state = parse_state(arguments.get("state", 0))
    ports = str(arguments.get("ports", "")).replace(" ", "")
    return f"{code.upper()}{'ON' if state else 'OFF'}[{ports}]"


async def apply_local_io(
    client: object,
    *,
    code: str,
    arguments: dict[str, Any],
) -> CommandResult:
    code = code.upper()
    info = LOCAL_IO_COMMANDS.get(code)
    if info is None:
        raise ProtocolError("local.undefinedCommand", code=code)

    settings: ProtocolSettings = client.settings  # type: ignore[attr-defined]
    transport = settings.transport
    if transport not in info["transports"]:
        raise ProtocolError(str(info["reason_other"]))

    state = parse_state(arguments.get("state", 0))
    display = format_local_io_display(code, arguments)

    if code == "PLI":
        max_port = max(1, int(settings.pli_port_count))
        ports = parse_port_list(
            str(arguments.get("ports", "")), max_port=max_port, label="PLI"
        )
        base = int(settings.pli_address)
        memory = client.memory  # type: ignore[attr-defined]
        for port in ports:
            memory.set_bit(base + port - 1, state)
        detail = (
            f"PLI {len(ports)} port(s) -> {'ON' if state else 'OFF'} "
            f"(M{base}+port-1)"
        )
        return CommandResult(display, "AK", ["AK", detail])

    if code == "ESI":
        max_port = max(1, int(settings.fn_esi_ports) or 0)
        if max_port <= 0:
            raise ProtocolError("local.esiPortsZero")
        ports = parse_port_list(
            str(arguments.get("ports", "")), max_port=max_port, label="ESI"
        )
        from .field_network.layout import build_layout

        layout = build_layout(
            esi_ports=settings.fn_esi_ports,
            eso_ports=settings.fn_eso_ports,
            command_words=settings.command_size,
            response_words=settings.response_size,
            result_words=settings.result_data_size,
        )
        set_bit = getattr(client, "set_output_bit", None)
        if set_bit is None:
            raise ProtocolError("local.esiWriteUnsupported")
        for port in ports:
            bit = layout.esi_byte * 8 + (port - 1)
            set_bit(bit, state)
        detail = (
            f"ESI {len(ports)} port(s) -> {'ON' if state else 'OFF'} "
            f"(Assem20 bit base {layout.esi_byte * 8})"
        )
        return CommandResult(display, "AK", ["AK", detail])

    raise ProtocolError("local.unsupportedCommand", code=code)
