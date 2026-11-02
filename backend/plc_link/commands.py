from __future__ import annotations

import re
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
    blank_strings: frozenset[str] = frozenset()
    """空文字でも NULL 文字列として書くキー。"""
    defaults: tuple[tuple[str, int], ...] = ()
    """省略時に書く整数。マルチ番号 0（先頭）など。"""
    folder_as_code: bool = False
    """フォルダ種類の TCP 文字（M/I/B...）を PLCLINK の数値へ変換する。"""
    packer: str | None = None
    """標準の並びでは表現できないコマンド。"""
    form_arguments: tuple[dict[str, Any], ...] | None = None
    """TCP と引数の形が違うときの PLCLINK / Field Network 用入力項目。"""
    unsupported_reason: str | None = None


def _choice(
    key: str,
    label: str,
    options: list[tuple[str, str]],
    *,
    show: dict[str, Any] | None = None,
    default: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": "enum",
        "options": [{"value": value, "label": text} for value, text in options],
        "default": default if default is not None else options[0][0],
    }
    if show is not None:
        item["show_if"] = show
    return item


def _number(
    key: str,
    label: str,
    minimum: int,
    maximum: int,
    *,
    default: int = 0,
    show: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": "integer",
        "min": minimum,
        "max": maximum,
        "default": default,
    }
    if show is not None:
        item["show_if"] = show
    return item


def _text(
    key: str,
    label: str,
    max_length: int,
    *,
    optional: bool = False,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key": key,
        "label": label,
        "type": "string",
        "max_length": max_length,
    }
    if optional:
        item["optional"] = True
        item["default"] = ""
    return item


def _kinds(*values: int) -> dict[str, Any]:
    return {"key": "kind", "in": [str(value) for value in values]}


def _flag(
    key: str,
    label: str,
    show: dict[str, Any] | None = None,
    *,
    off: str = "しない",
    on: str = "する",
) -> dict[str, Any]:
    return _choice(key, label, [("0", off), ("1", on)], show=show, default="0")


_INCLUDE = [("0", "含まない"), ("1", "含む")]
_IMAGE_SAVE = [
    ("0", "手動保存画像のみ"),
    ("1", "全ての画像"),
    ("2", "画像は保存しない"),
    ("3", "ロック画像のみ"),
]
_IMAGE_FORMAT = [
    ("0", "変換なし"),
    ("1", "Bitmap"),
    ("2", "JPEG"),
    ("3", "PNG"),
    ("4", "TIFF"),
    ("5", "GIF"),
]
_EXPORT_KINDS = [
    ("0", "一括"),
    ("1", "マスクデータ"),
    ("2", "キャリブレーションデータ"),
    ("3", "タスクグループ"),
    ("4", "特定タスク"),
    ("5", "システム共有データ一括"),
    ("6", "フォントデータ一括"),
    ("7", "お問い合わせ e-mail"),
    ("9", "タスク画像"),
    ("10", "操作記録"),
    ("11", "共有照明制御テンプレート"),
    ("12", "特定タスクの出力設定"),
    ("13", "3Dキャリブレーションデータ"),
    ("14", "カメラ ホワイトバランスデータ"),
    ("15", "ユーザーディスプレイデータ"),
    ("16", "点検用画像指定フォルダ"),
    ("17", "ロボットキャリブレーションデータ"),
]
_IMPORT_KINDS = [item for item in _EXPORT_KINDS if item[0] not in {"10"}]

# 種類の直後に続く整数引数。最後のフォルダ／パス文字列は別扱い。
# C013-01 第6.11版のアドレス表。
_EXPORT_FIELDS: dict[int, tuple[str, ...]] = {
    0: ("image_save", "shared_light", "history", "inspect_folder"),
    1: (),
    2: (),
    3: ("group", "image_save", "shared_light", "history", "inspect_folder"),
    4: (
        "group",
        "task",
        "image_save",
        "image_format",
        "shared_light",
        "history",
        "inspect_folder",
        "inspect_folder_number",
    ),
    5: (),
    6: (),
    7: (
        "group",
        "task",
        "image_save",
        "image_format",
        "shared_light",
        "history",
        "inspect_folder",
        "inspect_folder_number",
    ),
    9: (
        "group",
        "task",
        "image_save",
        "image_format",
        "inspect_folder",
        "inspect_folder_number",
    ),
    10: ("csv_convert",),
    11: (),
    12: ("group", "task"),
    13: (),
    14: (),
    15: ("display_number",),
    16: ("group", "task", "inspect_specified", "inspect_specified_number"),
    17: (),
}
_NUMERIC = "__numeric__"
_IMPORT_FIELDS: dict[int, tuple[str, ...]] = {
    0: (
        "delete_images",
        "delete_inspect",
        "keep_capture",
        "shared_light",
        "include_3d",
        _NUMERIC,
        "include_system",
    ),
    1: (),
    2: (),
    3: (
        "group",
        "delete_images",
        "delete_inspect",
        "keep_capture",
        "shared_light",
        _NUMERIC,
    ),
    4: (
        "group",
        "task",
        "delete_images",
        "delete_inspect",
        "keep_capture",
        "shared_light",
        _NUMERIC,
    ),
    5: (),
    6: (),
    7: (
        "group",
        "task",
        "delete_images",
        "delete_inspect",
        "keep_capture",
        "shared_light",
        "include_3d",
        _NUMERIC,
        "include_system",
    ),
    9: ("group", "task", "delete_images", "delete_inspect"),
    11: (),
    12: ("group", "task"),
    13: (),
    14: (),
    15: (),
    16: ("group", "task", "delete_inspect_specified"),
    17: (),
}
_NUMERIC_KINDS = {0, 3, 4, 7}

_SLI_FORM = (
    _number("increment", "増加数", 0, 99_999_999, default=1),
)
_SLP_FORM = (
    _number("lot_number", "ロット番号（0は変更なし）", 0, 99_999_999),
    _text("lot_name", "ロット名（空欄は指定なし）", 64, optional=True),
)
_EXPORT_FORM = (
    _choice("kind", "エクスポート種類", _EXPORT_KINDS, default="0"),
    _flag("progress", "経過を確認"),
    _number("version_major", "変換先バージョン（メジャー、0は変換しない）", 0, 999),
    _number("version_minor", "変換先バージョン（マイナー）", 0, 999),
    _number("version_sub", "変換先バージョン（サブマイナー）", 0, 999),
    _number(
        "group",
        "グループ番号（0はアクティブタスク）",
        0,
        20,
        show=_kinds(3, 4, 7, 9, 12, 16),
    ),
    _number(
        "task",
        "タスク番号（0はアクティブタスク）",
        0,
        50,
        show=_kinds(4, 7, 9, 12, 16),
    ),
    _choice(
        "image_save",
        "画像ファイル保存方法",
        _IMAGE_SAVE,
        show=_kinds(0, 3, 4, 7, 9),
    ),
    _choice(
        "image_format",
        "画像ファイル形式変換",
        _IMAGE_FORMAT,
        show=_kinds(4, 7, 9),
    ),
    _choice(
        "shared_light",
        "共有照明制御テンプレート",
        _INCLUDE,
        show=_kinds(0, 3, 4, 7),
    ),
    _choice("history", "変更履歴", _INCLUDE, show=_kinds(0, 3, 4, 7)),
    _choice(
        "inspect_folder",
        "点検用画像タスクフォルダ",
        _INCLUDE,
        show=_kinds(0, 3, 4, 7, 9),
    ),
    _number(
        "inspect_folder_number",
        "点検用画像タスクフォルダ番号（0は全て）",
        0,
        100,
        show=_kinds(4, 7, 9),
    ),
    _flag("csv_convert", "操作記録の CSV 変換", _kinds(10)),
    _number(
        "display_number",
        "ユーザーディスプレイ（0は全て）",
        0,
        10,
        show=_kinds(15),
    ),
    _choice("inspect_specified", "点検用画像指定フォルダ", _INCLUDE, show=_kinds(16)),
    _number(
        "inspect_specified_number",
        "点検用画像指定フォルダ番号（0は全て）",
        0,
        100,
        show=_kinds(16),
    ),
    _text("folder", "エクスポート先フォルダ", 200),
)
_IMPORT_FORM = (
    _choice("kind", "インポート種類", _IMPORT_KINDS, default="0"),
    _flag("progress", "経過を確認"),
    _choice(
        "numeric_adjust_mode",
        "数値補正データの指定",
        [("0", "指定しない"), ("1", "指定する")],
        show=_kinds(0, 3, 4, 7),
        default="0",
    ),
    _choice(
        "numeric_adjust",
        "数値補正データ",
        [("0", "初期化"), ("1", "含む"), ("2", "保持する")],
        show={"key": "numeric_adjust_mode", "equals": "1"},
        default="0",
    ),
    _number(
        "group",
        "グループ番号（0はアクティブタスク）",
        0,
        20,
        show=_kinds(3, 4, 7, 9, 12, 16),
    ),
    _number(
        "task",
        "タスク番号（0はアクティブタスク）",
        0,
        50,
        show=_kinds(4, 7, 9, 12, 16),
    ),
    _flag("delete_images", "インポート先の画像を削除", _kinds(0, 3, 4, 7, 9)),
    _flag(
        "delete_inspect",
        "インポート先の点検用画像タスクフォルダを削除",
        _kinds(0, 3, 4, 7, 9),
    ),
    _flag("keep_capture", "画像取込ツールの設定を保持", _kinds(0, 3, 4, 7)),
    _choice(
        "shared_light",
        "共有照明制御テンプレート",
        _INCLUDE,
        show=_kinds(0, 3, 4, 7),
    ),
    _choice("include_3d", "3Dキャリブレーションデータ", _INCLUDE, show=_kinds(0, 7)),
    _choice("include_system", "システムファイル", _INCLUDE, show=_kinds(0, 7)),
    _flag(
        "delete_inspect_specified",
        "インポート先の点検用画像指定フォルダを削除",
        _kinds(16),
    ),
    _text("path", "インポートファイルパス", 256),
)

# C013-01 第6.11版「1 PLCLINK コマンド一覧」のコマンドコード。
DOCUMENTED_COMMAND_CODES = frozenset(
    {
        1, 2, 3, 4, 5, 9, 10, 12,
        34, 35, 36, 37, 38, 39, 42, 43, 44, 45,
        64, 65, 66, 67, 70, 71, 80, 96, 97,
        128, 129, 130, 131, 160, 161, 162,
        1000, 4000,
        16000, 16002,
        18000, 18002, 18003,
        26000, 30000,
        34000, 34001, 34002, 34003, 34004, 34005,
        56000, 56002, 56003,
        75000, 75001,
    }
)

# TCP カタログコード → PLCLINK コマンド番号。
# アドレス順は C013-01 第6.11版。TCP に無い操作（単接点、DIO、分散、手動教示）は対象外。
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
    "SIE": PlcLinkCommandSpec(36, ("delete_mode", "locked")),
    "SFB": PlcLinkCommandSpec(37),
    "SFE": PlcLinkCommandSpec(38),
    "SGI": PlcLinkCommandSpec(39),
    "SSD": PlcLinkCommandSpec(42),
    "SGS": PlcLinkCommandSpec(43),
    "SRB": PlcLinkCommandSpec(44),
    "SRE": PlcLinkCommandSpec(45),
    "SLI": PlcLinkCommandSpec(
        64, ("increment",), packer="sli", form_arguments=_SLI_FORM
    ),
    "SLP": PlcLinkCommandSpec(
        65, ("lot_number", "lot_name"), packer="slp", form_arguments=_SLP_FORM
    ),
    "SLH": PlcLinkCommandSpec(66),
    "SLR": PlcLinkCommandSpec(67),
    "EXP": PlcLinkCommandSpec(
        70, ("kind", "folder"), packer="export", form_arguments=_EXPORT_FORM
    ),
    "IMP": PlcLinkCommandSpec(
        71, ("kind", "path"), packer="import", form_arguments=_IMPORT_FORM
    ),
    "RWC": PlcLinkCommandSpec(80),
    "SFS": PlcLinkCommandSpec(
        96, ("folder", "mode", "path"), string_params=frozenset({"path"}), packer="sfs"
    ),
    "SFI": PlcLinkCommandSpec(97, ("folder", "increment"), folder_as_code=True),
    "COA": PlcLinkCommandSpec(128, ("camera", "line")),
    "CPO": PlcLinkCommandSpec(129, ("group", "task", "camera", "line")),
    "CIA": PlcLinkCommandSpec(130, ("camera", "line")),
    "CPI": PlcLinkCommandSpec(131, ("group", "task", "camera", "line")),
    "TCA": PlcLinkCommandSpec(
        160, ("camera", "line", "text"), string_params=frozenset({"text"})
    ),
    "SMA": PlcLinkCommandSpec(
        161,
        (
            "camera",
            "line",
            "angle",
            "position",
            "font_size",
            "color",
            "outline",
            "text",
        ),
        string_params=frozenset({"text"}),
        blank_strings=frozenset({"text"}),
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
        4000, ("camera", "line", "fixed_position", "rows", "columns")
    ),
    "MAA": PlcLinkCommandSpec(
        16000, ("camera", "line", "multi"), defaults=(("multi", 0),)
    ),
    "MAC": PlcLinkCommandSpec(16002, ("camera", "line")),
    "MMA": PlcLinkCommandSpec(
        0,
        unsupported_reason="手動文字／パターン教示は PLCLINK コマンドにありません",
    ),
    "DAA": PlcLinkCommandSpec(
        18000, ("camera", "line", "multi"), defaults=(("multi", 0),)
    ),
    "DLA": PlcLinkCommandSpec(18002, ("camera", "line")),
    "DDA": PlcLinkCommandSpec(18003, ("camera", "line")),
    "DMA": PlcLinkCommandSpec(
        0,
        unsupported_reason="手動基準画像登録は PLCLINK コマンドにありません",
    ),
    "KMA": PlcLinkCommandSpec(
        26000,
        ("camera", "line", "multi", "module_number", "x", "y"),
        defaults=(("multi", 0),),
    ),
    "DFA": PlcLinkCommandSpec(
        30000,
        ("camera", "line", "mode", "path"),
        string_params=frozenset({"path"}),
        packer="dfa",
    ),
    "WAS": PlcLinkCommandSpec(34000, ("camera", "line", "block"), packer="ocv"),
    "WMS": PlcLinkCommandSpec(
        34001, ("group", "task", "camera", "line", "block"), packer="ocv"
    ),
    "WAA": PlcLinkCommandSpec(34002, ("camera", "line", "block"), packer="ocv"),
    "WMA": PlcLinkCommandSpec(
        34003, ("group", "task", "camera", "line", "block"), packer="ocv"
    ),
    "WAC": PlcLinkCommandSpec(34004, ("camera", "line", "block"), packer="ocv"),
    "WMC": PlcLinkCommandSpec(
        34005, ("group", "task", "camera", "line", "block"), packer="ocv"
    ),
    "NAA": PlcLinkCommandSpec(
        56000,
        ("camera", "line", "multi", "allow_search_ng", "region_row", "region_column"),
        defaults=(("multi", 0),),
    ),
    "NLA": PlcLinkCommandSpec(
        56002,
        ("camera", "line", "region_row", "region_column"),
        packer="region",
    ),
    "NDA": PlcLinkCommandSpec(
        56003,
        ("camera", "line", "region_row", "region_column"),
        packer="region",
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
    "DDN": PlcLinkCommandSpec(75001, ("camera", "line", "identifier")),
}


def resolve_spec(tcp_code: str) -> PlcLinkCommandSpec:
    code = tcp_code.upper()
    spec = COMMAND_SPECS.get(code)
    if spec is None:
        raise ProtocolError(f"PLCLINK 未対応のコマンドです: {code}")
    if spec.unsupported_reason:
        raise ProtocolError(f"{code}: {spec.unsupported_reason}")
    return spec


def command_metadata(tcp_code: str) -> dict[str, Any]:
    """カタログ表示用の PLCLINK 対応情報を返す。"""
    from ..local_io import local_io_metadata

    code = tcp_code.upper()
    local = local_io_metadata(code)
    if local is not None:
        return local  # type: ignore[return-value]
    spec = COMMAND_SPECS.get(code)
    if spec is None:
        return {
            "local_io": False,
            "plclink_supported": False,
            "plclink_code": None,
            "plclink_reason": "PLCLINK 未対応のコマンドです",
            "field_network_supported": False,
            "field_network_code": None,
            "field_network_reason": "Field Network 未対応のコマンドです",
        }
    supported = spec.unsupported_reason is None
    meta: dict[str, Any] = {
        "local_io": False,
        "plclink_supported": supported,
        "plclink_code": spec.code if spec.code else None,
        "plclink_reason": spec.unsupported_reason,
        "field_network_supported": supported,
        "field_network_code": spec.code if spec.code else None,
        "field_network_reason": spec.unsupported_reason,
    }
    if spec.form_arguments is not None:
        meta["plclink_arguments"] = list(spec.form_arguments)
    return meta


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


_FOLDER_CODE = {
    "B": 1,
    "F": 2,
    "L": 3,
    "M": 4,
    "I": 5,
    "O": 6,
    "S": 7,
    "T": 8,
    "H": 9,
}
_OCV_TASK = {34001, 34003, 34005}
_OCV_MULTI = {34000, 34001}
_OCV_REPLACE = {34004, 34005}
_BLOCK_BODY = re.compile(
    r"^(?P<block>\d+)"
    r"(?:,BF(?P<enabled>[01]))?"
    r"(?:,FG(?P<font>\d+))?"
    r"(?:,FC(?P<count>\d+))?"
    r"(?:,FS(?P<text>[0-9A-Za-z-]*))?"
    r"(?:,FM(?P<pos>\d+)(?P<chars>[0-9A-Za-z-]*))?"
    r"(?:,FR(?P<rpos>\d+)(?P<rchars>[0-9A-Za-z-]*))?"
    r"$"
)


def _append_int(words: list[int], value: int) -> None:
    words.extend(dword_to_words(value))


def _append_str(
    words: list[int],
    text: str,
    *,
    encoding: str,
    byte_order: ByteOrder,
    limit: int | None = None,
    label: str = "文字列",
) -> None:
    if limit is not None and len(text) > limit:
        raise ProtocolError(f"{label}は{limit}文字以内です")
    words.extend(pack_string(text, encoding=encoding, byte_order=byte_order))


def _need(arguments: dict[str, Any], key: str) -> Any:
    if key not in arguments or str(arguments[key]) == "":
        raise ProtocolError(f"引数 {key} が不足しています")
    return arguments[key]


def _as_int(raw: Any, label: str) -> int:
    try:
        return int(str(raw).strip())
    except ValueError as exc:
        raise ProtocolError(f"{label}は整数で入力してください") from exc


def _need_int(arguments: dict[str, Any], key: str) -> int:
    return _as_int(_need(arguments, key), f"引数 {key} ")


def _opt_int(arguments: dict[str, Any], key: str, default: int = 0) -> int:
    raw = arguments.get(key, "")
    if raw is None or str(raw) == "":
        return default
    return _as_int(raw, f"引数 {key} ")


def _folder_code(value: Any) -> int:
    text = str(value).strip().upper()
    if text.isdigit():
        number = int(text)
        if 1 <= number <= 9:
            return number
    code = _FOLDER_CODE.get(text)
    if code is None:
        raise ProtocolError("フォルダ種類が不正です")
    return code


def _pack_standard(
    words: list[int],
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    values = dict(arguments)
    if spec.folder_as_code:
        values["folder"] = _folder_code(values.get("folder", ""))
    defaults = dict(spec.defaults)
    for key in spec.params:
        missing = key not in values or str(values[key]) == ""
        if missing and key in defaults:
            raw: Any = defaults[key]
        elif missing and key in spec.blank_strings:
            raw = ""
        elif missing:
            raise ProtocolError(f"引数 {key} が不足しています")
        else:
            raw = values[key]
        if key in spec.string_params or key in spec.blank_strings:
            _append_str(words, str(raw), encoding=encoding, byte_order=byte_order)
            continue
        if key in {"x", "y"}:
            # 固定小数点（小数点以下 3 桁）。VTV の実数データ初期値に合わせる。
            _append_int(words, int(round(float(raw) * 1000)))
            continue
        _append_int(words, _as_int(raw, f"引数 {key} "))


def _pack_sli(
    words: list[int],
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    del spec, encoding, byte_order
    raw = arguments.get("increment", "")
    if str(raw) == "":
        raw = arguments.get("raw", "")
    if str(raw) == "":
        raise ProtocolError("増加数が不足しています")
    value = _as_int(raw, "増加数")
    if value < 0 or value > 99_999_999:
        raise ProtocolError("増加数は 0〜99999999 で入力してください")
    _append_int(words, value)


def _parse_slp_raw(raw: str) -> tuple[int, str]:
    text = raw.strip()
    if not text:
        raise ProtocolError("ロット番号またはロット名が不足しています")
    if text.startswith("N"):
        rest = text[1:]
        number, _, name = rest.partition("S")
        return _as_int(number, "ロット番号"), name
    if text.startswith("S"):
        return 0, text[1:]
    return _as_int(text, "ロット番号"), ""


def _pack_slp(
    words: list[int],
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    del spec
    if "lot_number" not in arguments and "lot_name" not in arguments:
        number, name = _parse_slp_raw(str(arguments.get("raw", "")))
    else:
        number = _opt_int(arguments, "lot_number", 0)
        name = str(arguments.get("lot_name", "") or "")
    if number == 0 and name == "":
        raise ProtocolError("ロット番号とロット名の両方を未指定にはできません")
    if number < 0 or number > 99_999_999:
        raise ProtocolError("ロット番号は 0〜99999999 で入力してください")
    _append_int(words, number)
    _append_str(
        words,
        name,
        encoding=encoding,
        byte_order=byte_order,
        limit=64,
        label="ロット名",
    )


def _pack_sfs(
    words: list[int],
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    del spec
    _append_int(words, _folder_code(arguments.get("folder", "")))
    mode = _need_int(arguments, "mode")
    if mode not in {0, 1}:
        raise ProtocolError("動作モードが不正です")
    _append_int(words, mode)
    if mode == 0:
        path = str(_need(arguments, "path"))
        _append_str(
            words,
            path,
            encoding=encoding,
            byte_order=byte_order,
            limit=200,
            label="フォルダパス",
        )


def _pack_dfa(
    words: list[int],
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    del spec
    _append_int(words, _need_int(arguments, "camera"))
    _append_int(words, _need_int(arguments, "line"))
    mode = _need_int(arguments, "mode")
    if mode not in {0, 1}:
        raise ProtocolError("動作モードが不正です")
    _append_int(words, mode)
    if mode == 0:
        path = str(_need(arguments, "path"))
        _append_str(
            words,
            path,
            encoding=encoding,
            byte_order=byte_order,
            limit=200,
            label="フォルダパス",
        )


def _pack_export(
    words: list[int],
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    del spec
    kind = _need_int(arguments, "kind")
    fields = _EXPORT_FIELDS.get(kind)
    if fields is None:
        raise ProtocolError(f"未対応のエクスポート種類です: {kind}")
    _append_int(words, kind)
    _append_int(words, _opt_int(arguments, "progress"))
    _append_int(words, _opt_int(arguments, "version_major"))
    _append_int(words, _opt_int(arguments, "version_minor"))
    _append_int(words, _opt_int(arguments, "version_sub"))
    for key in fields:
        _append_int(words, _opt_int(arguments, key))
    folder = str(_need(arguments, "folder"))
    _append_str(
        words,
        folder,
        encoding=encoding,
        byte_order=byte_order,
        limit=200,
        label="エクスポート先フォルダ",
    )


def _pack_import(
    words: list[int],
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    del spec
    kind = _need_int(arguments, "kind")
    fields = _IMPORT_FIELDS.get(kind)
    if fields is None:
        raise ProtocolError(f"未対応のインポート種類です: {kind}")
    use_numeric = (
        str(arguments.get("numeric_adjust_mode", "0")) == "1" and kind in _NUMERIC_KINDS
    )
    _append_int(words, kind + 100 if use_numeric else kind)
    _append_int(words, _opt_int(arguments, "progress"))
    for key in fields:
        if key == _NUMERIC:
            if use_numeric:
                _append_int(words, _opt_int(arguments, "numeric_adjust"))
            continue
        _append_int(words, _opt_int(arguments, key))
    path = str(_need(arguments, "path"))
    _append_str(
        words,
        path,
        encoding=encoding,
        byte_order=byte_order,
        limit=256,
        label="インポートファイルパス",
    )


def _pack_region(
    words: list[int],
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    del spec, encoding, byte_order
    _append_int(words, _need_int(arguments, "camera"))
    _append_int(words, _need_int(arguments, "line"))
    # +0008 と +0010 はダミー。行／列は 56000 と同じ +0012 / +0014。
    _append_int(words, 0)
    _append_int(words, 0)
    _append_int(words, _need_int(arguments, "region_row"))
    _append_int(words, _need_int(arguments, "region_column"))


def _ocv_block_from_groups(groups: dict[str, str | None]) -> dict[str, Any]:
    additions: list[tuple[int, str]] = []
    if groups["pos"]:
        additions.append((int(groups["pos"]), groups["chars"] or ""))
    replacements: list[tuple[int, str]] = []
    if groups["rpos"]:
        replacements.append((int(groups["rpos"]), groups["rchars"] or ""))
    return {
        "number": int(groups["block"] or "0"),
        "enabled": 1 if groups["enabled"] is None else int(groups["enabled"]),
        "font": 0 if not groups["font"] else int(groups["font"]),
        "text": groups["text"] or "",
        "additions": additions,
        "replacements": replacements,
    }


def _parse_additional_blocks(text: str) -> list[dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return []
    if not raw.startswith(",BL"):
        raise ProtocolError("追加ブロックは ,BL から指定してください")
    blocks: list[dict[str, Any]] = []
    for part in raw.split(",BL")[1:]:
        matched = _BLOCK_BODY.match(part)
        if matched is None:
            raise ProtocolError(f"追加ブロックの形式が不正です: ,BL{part}")
        blocks.append(_ocv_block_from_groups(matched.groupdict()))
    return blocks


def _primary_ocv_block(arguments: dict[str, Any], *, replace: bool) -> dict[str, Any]:
    enabled_raw = str(arguments.get("enabled", "") or "")
    enabled = 1 if enabled_raw == "" else _as_int(enabled_raw, "ブロック状態")
    font_raw = arguments.get("font", "")
    font = 0 if str(font_raw) == "" else _as_int(font_raw, "フォント番号")
    text = str(arguments.get("text", "") or "")
    additions: list[tuple[int, str]] = []
    position = arguments.get("multi_position", "")
    if str(position) != "":
        chars = str(arguments.get("multi_characters", "") or "")
        if chars == "":
            raise ProtocolError("追加する複数文字が不足しています")
        additions.append((_as_int(position, "文字番号"), chars))
    replacements: list[tuple[int, str]] = []
    replace_position = arguments.get("replace_position", "")
    if replace and enabled != 0 and str(replace_position) == "":
        raise ProtocolError("入れ換える文字番号が不足しています")
    if str(replace_position) != "":
        chars = str(arguments.get("replace_characters", "") or "")
        if chars == "":
            raise ProtocolError("入れ換え文字が不足しています")
        replacements.append((_as_int(replace_position, "入れ換える文字番号"), chars))
    if not replace and enabled != 0 and text == "":
        raise ProtocolError("文字列が不足しています")
    return {
        "number": _need_int(arguments, "block"),
        "enabled": enabled,
        "font": font,
        "text": text,
        "additions": additions,
        "replacements": replacements,
    }


def _pack_ocv_block(
    words: list[int],
    block: dict[str, Any],
    *,
    replace: bool,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    _append_int(words, int(block["number"]))
    _append_int(words, int(block["enabled"]))
    if replace:
        pairs = block["replacements"]
        limit = 63
        label = "入れ換え文字"
    else:
        _append_int(words, int(block["font"]))
        _append_str(
            words,
            str(block["text"]),
            encoding=encoding,
            byte_order=byte_order,
            limit=25,
            label="文字列",
        )
        pairs = block["additions"]
        limit = 62
        label = "追加する照合文字"
    for position, chars in pairs:
        if len(chars) > limit:
            raise ProtocolError(f"{label}は{limit}文字以内です")
        _append_int(words, position)
        _append_str(
            words,
            chars,
            encoding=encoding,
            byte_order=byte_order,
            limit=limit,
            label=label,
        )
    _append_int(words, 0)


def _pack_ocv(
    words: list[int],
    spec: PlcLinkCommandSpec,
    arguments: dict[str, Any],
    *,
    encoding: str,
    byte_order: ByteOrder,
) -> None:
    replace = spec.code in _OCV_REPLACE
    if spec.code in _OCV_TASK:
        _append_int(words, _need_int(arguments, "group"))
        _append_int(words, _need_int(arguments, "task"))
    _append_int(words, _need_int(arguments, "camera"))
    _append_int(words, _need_int(arguments, "line"))
    if spec.code in _OCV_MULTI:
        _append_int(words, _opt_int(arguments, "multi"))
    else:
        _append_int(words, 0)
    blocks = [_primary_ocv_block(arguments, replace=replace)]
    extra = str(arguments.get("additional_blocks", "") or "")
    blocks.extend(_parse_additional_blocks(extra))
    if not 1 <= len(blocks) <= 20:
        raise ProtocolError("設定ブロック個数は 1〜20 です")
    _append_int(words, len(blocks))
    for block in blocks:
        _pack_ocv_block(
            words, block, replace=replace, encoding=encoding, byte_order=byte_order
        )


_PACKERS = {
    "sli": _pack_sli,
    "slp": _pack_slp,
    "sfs": _pack_sfs,
    "dfa": _pack_dfa,
    "export": _pack_export,
    "import": _pack_import,
    "region": _pack_region,
    "ocv": _pack_ocv,
}


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
    pack = _PACKERS.get(spec.packer or "", _pack_standard)
    pack(words, spec, arguments, encoding=encoding, byte_order=byte_order)

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
