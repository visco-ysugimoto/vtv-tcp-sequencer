from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..protocol import ProtocolError

ByteOrder = Literal["high_low", "low_high"]


@dataclass(frozen=True, slots=True)
class PlcLinkCommandSpec:
    code: int
    params: tuple[str, ...] = ()
    """カタログ引数キー。並びが PLCLINK パラメータ順。"""
    string_params: frozenset[str] = frozenset()
    """文字列としてパックするキー。"""
    unsupported_reason: str | None = None


# TCP カタログコード → PLCLINK コマンド番号。
# Phase 1: システム系と単純なツール系。複雑な OCV ブロック列は未対応。
COMMAND_SPECS: dict[str, PlcLinkCommandSpec] = {
    "RRT": PlcLinkCommandSpec(1, ("group", "task")),
    "SRP": PlcLinkCommandSpec(2, ("system_command",)),
    "RCA": PlcLinkCommandSpec(3, ("group", "task")),
    "RLA": PlcLinkCommandSpec(4, ("group", "task")),
    "RUT": PlcLinkCommandSpec(5, ("group", "task")),
    "RRA": PlcLinkCommandSpec(9),
    "RCC": PlcLinkCommandSpec(10),
    "RAU": PlcLinkCommandSpec(12),
    "SLS": PlcLinkCommandSpec(34),
    "SLE": PlcLinkCommandSpec(35),
    "SIE": PlcLinkCommandSpec(
        36,
        unsupported_reason="PLCLINK 36 は引数レイアウトが TCP と異なるため未対応",
    ),
    "SFB": PlcLinkCommandSpec(37),
    "SFE": PlcLinkCommandSpec(38),
    "SGI": PlcLinkCommandSpec(39),
    "SSD": PlcLinkCommandSpec(42),
    "SGS": PlcLinkCommandSpec(43),
    "SRB": PlcLinkCommandSpec(44),
    "SRE": PlcLinkCommandSpec(45),
    "SLI": PlcLinkCommandSpec(
        64,
        unsupported_reason="PLCLINK 64 は引数レイアウトが TCP と異なるため未対応",
    ),
    "SLP": PlcLinkCommandSpec(
        65,
        unsupported_reason="PLCLINK 65 は引数レイアウトが TCP と異なるため未対応",
    ),
    "SLH": PlcLinkCommandSpec(66),
    "SLR": PlcLinkCommandSpec(67),
    "EXP": PlcLinkCommandSpec(
        70,
        unsupported_reason="PLCLINK 70（エクスポート）は Phase 1 未対応",
    ),
    "IMP": PlcLinkCommandSpec(
        71,
        unsupported_reason="PLCLINK 71（インポート）は Phase 1 未対応",
    ),
    "RWC": PlcLinkCommandSpec(80),
    "SFS": PlcLinkCommandSpec(
        96,
        unsupported_reason="PLCLINK 96 はフォルダ種別コード変換が必要なため未対応",
    ),
    "SFI": PlcLinkCommandSpec(
        97,
        unsupported_reason="PLCLINK 97 はフォルダ種別コード変換が必要なため未対応",
    ),
    "COA": PlcLinkCommandSpec(128, ("camera", "line")),
    "CPO": PlcLinkCommandSpec(129, ("group", "task", "camera", "line")),
    "CIA": PlcLinkCommandSpec(130, ("camera", "line")),
    "CPI": PlcLinkCommandSpec(131, ("group", "task", "camera", "line")),
    "TCA": PlcLinkCommandSpec(
        160, ("camera", "line", "text"), string_params=frozenset({"text"})
    ),
    "SMA": PlcLinkCommandSpec(
        161,
        unsupported_reason="PLCLINK 161 は引数レイアウトが TCP と異なるため未対応",
    ),
    "MTT": PlcLinkCommandSpec(162, ("folder_type", "folder_number", "show")),
    "SSA": PlcLinkCommandSpec(
        0, unsupported_reason="単接点トリガ設定は PLCLINK コマンドにありません"
    ),
    "SST": PlcLinkCommandSpec(
        0, unsupported_reason="単接点トリガ設定は PLCLINK コマンドにありません"
    ),
    "POA": PlcLinkCommandSpec(
        0, unsupported_reason="DIO 操作は仮想 I/O（Phase 2）で対応予定です"
    ),
    "POP": PlcLinkCommandSpec(
        0, unsupported_reason="DIO 操作は仮想 I/O（Phase 2）で対応予定です"
    ),
    "PIA": PlcLinkCommandSpec(
        0, unsupported_reason="DIO 操作は仮想 I/O（Phase 2）で対応予定です"
    ),
    "PIP": PlcLinkCommandSpec(
        0, unsupported_reason="DIO 操作は仮想 I/O（Phase 2）で対応予定です"
    ),
    "SOS": PlcLinkCommandSpec(
        0, unsupported_reason="分散システム運用は PLCLINK では使用できません"
    ),
    "SOP": PlcLinkCommandSpec(
        0, unsupported_reason="分散システム運用は PLCLINK では使用できません"
    ),
    "SLM": PlcLinkCommandSpec(
        0, unsupported_reason="ロット設定画面表示は PLCLINK コマンドにありません"
    ),
    # Tools
    "ICA": PlcLinkCommandSpec(1000, ("camera", "line", "calibration_id")),
    "MCA": PlcLinkCommandSpec(
        4000,
        unsupported_reason="PLCLINK 4000 は引数レイアウトが TCP と異なるため未対応",
    ),
    "MAA": PlcLinkCommandSpec(16000, ("camera", "line")),
    "MAC": PlcLinkCommandSpec(16002, ("camera", "line")),
    "MMA": PlcLinkCommandSpec(
        0,
        unsupported_reason="手動文字／パターン教示は PLCLINK コマンドにありません",
    ),
    "DAA": PlcLinkCommandSpec(18000, ("camera", "line")),
    "DLA": PlcLinkCommandSpec(18002, ("camera", "line")),
    "DDA": PlcLinkCommandSpec(18003, ("camera", "line")),
    "DMA": PlcLinkCommandSpec(
        0,
        unsupported_reason="手動基準画像登録は PLCLINK コマンドにありません",
    ),
    "KMA": PlcLinkCommandSpec(
        26000,
        unsupported_reason="PLCLINK 26000 は引数レイアウトが TCP と異なるため未対応",
    ),
    "DFA": PlcLinkCommandSpec(
        30000,
        unsupported_reason="PLCLINK 30000 は引数レイアウトが TCP と異なるため未対応",
    ),
    "WAS": PlcLinkCommandSpec(
        34000,
        unsupported_reason="OCV ブロック列の PLCLINK 変換は Phase 1 未対応",
    ),
    "WMS": PlcLinkCommandSpec(
        34001,
        unsupported_reason="OCV ブロック列の PLCLINK 変換は Phase 1 未対応",
    ),
    "WAA": PlcLinkCommandSpec(
        34002,
        unsupported_reason="OCV ブロック列の PLCLINK 変換は Phase 1 未対応",
    ),
    "WMA": PlcLinkCommandSpec(
        34003,
        unsupported_reason="OCV ブロック列の PLCLINK 変換は Phase 1 未対応",
    ),
    "WAC": PlcLinkCommandSpec(
        34004,
        unsupported_reason="OCV ブロック列の PLCLINK 変換は Phase 1 未対応",
    ),
    "WMC": PlcLinkCommandSpec(
        34005,
        unsupported_reason="OCV ブロック列の PLCLINK 変換は Phase 1 未対応",
    ),
    "NAA": PlcLinkCommandSpec(
        56000,
        unsupported_reason="PLCLINK 56000 は位置引数が必要なため未対応",
    ),
    "NLA": PlcLinkCommandSpec(
        56002,
        unsupported_reason="PLCLINK 56002 は位置引数が必要なため未対応",
    ),
    "NDA": PlcLinkCommandSpec(
        56003,
        unsupported_reason="PLCLINK 56003 は位置引数が必要なため未対応",
    ),
    "NMA": PlcLinkCommandSpec(
        0,
        unsupported_reason="手動基準画像登録は PLCLINK コマンドにありません",
    ),
    "DID": PlcLinkCommandSpec(
        75000,
        ("camera", "line", "identifier"),
        string_params=frozenset({"identifier"}),
    ),
}


def resolve_spec(tcp_code: str) -> PlcLinkCommandSpec:
    code = tcp_code.upper()
    spec = COMMAND_SPECS.get(code)
    if spec is None:
        raise ProtocolError(f"PLCLINK 未対応のコマンドです: {code}")
    if spec.unsupported_reason:
        raise ProtocolError(f"{code}: {spec.unsupported_reason}")
    return spec


def command_metadata(tcp_code: str) -> dict[str, int | str | bool | None]:
    """カタログ表示用の PLCLINK 対応情報を返す。"""
    code = tcp_code.upper()
    spec = COMMAND_SPECS.get(code)
    if spec is None:
        return {
            "plclink_supported": False,
            "plclink_code": None,
            "plclink_reason": "PLCLINK 未対応のコマンドです",
        }
    return {
        "plclink_supported": spec.unsupported_reason is None,
        "plclink_code": spec.code if spec.code else None,
        "plclink_reason": spec.unsupported_reason,
    }


def pack_string(
    text: str,
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> list[int]:
    raw = text.encode(encoding) + b"\x00"
    if len(raw) % 2:
        raw += b"\x00"
    words: list[int] = []
    for index in range(0, len(raw), 2):
        first, second = raw[index], raw[index + 1]
        if byte_order == "high_low":
            words.append((first << 8) | second)
        else:
            words.append((second << 8) | first)
    # 各パラメータは 2 ワード単位（32bit）なので、ワード数が奇数なら 0 を足す。
    if len(words) % 2:
        words.append(0)
    return words


def dword_to_words(value: int) -> list[int]:
    unsigned = int(value) & 0xFFFFFFFF
    return [unsigned & 0xFFFF, (unsigned >> 16) & 0xFFFF]


def words_to_dword(words: list[int]) -> int:
    low = words[0] & 0xFFFF
    high = words[1] & 0xFFFF
    value = (high << 16) | low
    if value & 0x80000000:
        value -= 0x100000000
    return value


def build_command_words(
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
    area_size: int,
) -> list[int]:
    """トリガ=0 の状態でコマンド領域へ書くワード列を生成する。"""
    words: list[int] = []
    words.extend(dword_to_words(0))  # trigger
    words.extend(dword_to_words(spec.code))
    for key in spec.params:
        if key not in arguments or str(arguments[key]) == "":
            raise ProtocolError(f"引数 {key} が不足しています")
        raw = arguments[key]
        if key in spec.string_params:
            words.extend(
                pack_string(str(raw), encoding=encoding, byte_order=byte_order)
            )
            continue
        if isinstance(raw, float) or (
            isinstance(raw, str) and "." in raw and key in {"x", "y"}
        ):
            # 固定小数点（小数点以下 3 桁）— VTV 初期値に合わせる
            number = float(raw)
            words.extend(dword_to_words(int(round(number * 1000))))
        else:
            words.extend(dword_to_words(int(raw)))

    if len(words) > area_size:
        raise ProtocolError(
            f"コマンドデータが割当サイズを超過しました"
            f"（{len(words)} > {area_size} ワード）"
        )
    # 残りは 0 埋め（クリア）
    words.extend([0] * (area_size - len(words)))
    return words


def format_plclink_display(spec: PlcLinkCommandSpec, arguments: dict[str, Any]) -> str:
    parts = [f"PLCLINK#{spec.code}"]
    for key in spec.params:
        parts.append(f"{key}={arguments.get(key, '')}")
    return " ".join(parts)
