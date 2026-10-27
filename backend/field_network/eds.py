"""VTV Field Network 用 EDS ファイルの簡易パーサ。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class EdsConnectionInfo:
    """EDS から抽出した Class 1 接続パラメータ。"""

    product_name: str = ""
    catalog: str = ""
    vendor_code: int | None = None
    product_code: int | None = None
    major_revision: int | None = None
    minor_revision: int | None = None
    input_size: int = 0
    output_size: int = 0
    input_size_min: int | None = None
    input_size_max: int | None = None
    output_size_min: int | None = None
    output_size_max: int | None = None
    rpi_us: int = 10_000
    rpi_min_us: int | None = None
    rpi_max_us: int | None = None
    connection_path: str = "20 04 24 01 2C 14 2C 0A"
    assem_input_instance: int = 10
    assem_output_instance: int = 20
    o_to_t_header_bytes: int = 4
    source_name: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def input_words(self) -> int:
        return self.input_size // 2

    @property
    def output_words(self) -> int:
        return self.output_size // 2

    @property
    def rpi_ms(self) -> float:
        return self.rpi_us / 1000.0

    def to_dict(self) -> dict[str, object]:
        return {
            "product_name": self.product_name,
            "catalog": self.catalog,
            "vendor_code": self.vendor_code,
            "product_code": self.product_code,
            "major_revision": self.major_revision,
            "minor_revision": self.minor_revision,
            "input_size": self.input_size,
            "output_size": self.output_size,
            "input_size_min": self.input_size_min,
            "input_size_max": self.input_size_max,
            "output_size_min": self.output_size_min,
            "output_size_max": self.output_size_max,
            "rpi_us": self.rpi_us,
            "rpi_min_us": self.rpi_min_us,
            "rpi_max_us": self.rpi_max_us,
            "rpi_ms": self.rpi_ms,
            "connection_path": self.connection_path,
            "assem_input_instance": self.assem_input_instance,
            "assem_output_instance": self.assem_output_instance,
            "o_to_t_header_bytes": self.o_to_t_header_bytes,
            "source_name": self.source_name,
            "warnings": list(self.warnings),
        }


_PARAM_BLOCK_RE = re.compile(
    r"Param(?P<num>\d+)\s*=\s*(?P<body>.*?);",
    re.IGNORECASE | re.DOTALL,
)
_ASSEM_RE = re.compile(
    r"Assem(?P<num>\d+)\s*=\s*(?P<body>.*?);",
    re.IGNORECASE | re.DOTALL,
)
_CONNECTION_RE = re.compile(
    r"Connection\d+\s*=\s*(?P<body>.*?);",
    re.IGNORECASE | re.DOTALL,
)
_FIELD_RE = re.compile(
    r'(?P<key>ProdName|Catalog|VendCode|ProdCode|MajRev|MinRev)\s*=\s*"?(?P<val>[^";\n]+)"?\s*;',
    re.IGNORECASE,
)
_PATH_RE = re.compile(
    r'"((?:[0-9A-Fa-f]{2}\s*)+)"\s*;?\s*(?:\$|$)',
)
_INT_LIST_RE = re.compile(r"(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)")


def parse_eds_text(text: str, *, source_name: str = "") -> EdsConnectionInfo:
    """EDS テキストから VTV Field Network 接続情報を抽出する。"""
    info = EdsConnectionInfo(source_name=source_name)
    cleaned = _strip_eds_comments(text)

    for match in _FIELD_RE.finditer(cleaned):
        key = match.group("key").lower()
        value = match.group("val").strip().strip('"')
        if key == "prodname":
            info.product_name = value
        elif key == "catalog":
            info.catalog = value
        elif key == "vendcode":
            info.vendor_code = _parse_int(value)
        elif key == "prodcode":
            info.product_code = _parse_int(value)
        elif key == "majrev":
            info.major_revision = _parse_int(value)
        elif key == "minrev":
            info.minor_revision = _parse_int(value)

    params: dict[int, dict[str, object]] = {}
    for match in _PARAM_BLOCK_RE.finditer(cleaned):
        num = int(match.group("num"))
        body = match.group("body")
        name = _extract_quoted(body, 0) or ""
        ranges = _INT_LIST_RE.findall(body)
        # EDS Param の min,max,default は後半の数値リスト
        min_v = max_v = default_v = None
        if ranges:
            min_v, max_v, default_v = (int(x) for x in ranges[-1])
        params[num] = {
            "name": name,
            "min": min_v,
            "max": max_v,
            "default": default_v,
        }

    assemblies: dict[int, int] = {}
    for match in _ASSEM_RE.finditer(cleaned):
        num = int(match.group("num"))
        body = match.group("body")
        size = _first_plain_int(body)
        if size is not None:
            assemblies[num] = size

    if 10 in assemblies:
        info.assem_input_instance = 10
        info.input_size = assemblies[10]
    if 20 in assemblies:
        info.assem_output_instance = 20
        info.output_size = assemblies[20]

    for num, meta in params.items():
        name = str(meta.get("name") or "").lower()
        default = meta.get("default")
        if default is None:
            continue
        if "input size" in name:
            info.input_size = int(default)
            info.input_size_min = meta.get("min")  # type: ignore[assignment]
            info.input_size_max = meta.get("max")  # type: ignore[assignment]
        elif "output size" in name:
            info.output_size = int(default)
            info.output_size_min = meta.get("min")  # type: ignore[assignment]
            info.output_size_max = meta.get("max")  # type: ignore[assignment]
        elif name == "rpi":
            info.rpi_us = int(default)
            info.rpi_min_us = meta.get("min")  # type: ignore[assignment]
            info.rpi_max_us = meta.get("max")  # type: ignore[assignment]

    conn_match = _CONNECTION_RE.search(cleaned)
    if conn_match:
        body = conn_match.group("body")
        path_match = _PATH_RE.search(body)
        if path_match:
            info.connection_path = " ".join(path_match.group(1).split()).upper()
        # O=>T header: bits 8-10 of connection parameters word
        # EDS comment often documents 4 byte run/idle
        if "4 byte run/idle" in body.lower() or "run/idle" in body.lower():
            info.o_to_t_header_bytes = 4
        instances = _path_connection_points(info.connection_path)
        if instances:
            out_inst, in_inst = instances
            info.assem_output_instance = out_inst
            info.assem_input_instance = in_inst

    if info.input_size <= 0 or info.output_size <= 0:
        info.warnings.append("EDS から入出力サイズを取得できませんでした")
    if info.input_size % 2:
        info.warnings.append("入力サイズが奇数バイトです（ワード割付と不一致の可能性）")
    if info.output_size % 2:
        info.warnings.append("出力サイズが奇数バイトです（ワード割付と不一致の可能性）")
    if info.output_size < 8:
        info.warnings.append(
            "出力アセンブリが小さいため、コマンド領域を含められない可能性があります"
        )
    return info


def parse_eds_file(path: str | Path) -> EdsConnectionInfo:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8", errors="replace")
    return parse_eds_text(text, source_name=file_path.name)


def parse_connection_path(path: str) -> bytes:
    """空白区切り HEX 文字列をバイト列へ変換する。"""
    parts = [p for p in path.replace(",", " ").split() if p]
    return bytes(int(part, 16) for part in parts)


def _strip_eds_comments(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        if "$" in line:
            # 文字列内の $ は稀なので、単純に行コメントとして扱う
            in_string = False
            cut = len(line)
            for index, char in enumerate(line):
                if char == '"':
                    in_string = not in_string
                elif char == "$" and not in_string:
                    cut = index
                    break
            line = line[:cut]
        lines.append(line)
    return "\n".join(lines)


def _extract_quoted(text: str, index: int) -> str | None:
    matches = re.findall(r'"([^"]*)"', text)
    if 0 <= index < len(matches):
        return matches[index]
    return None


def _first_plain_int(body: str) -> int | None:
    """Assem ブロック先頭付近のサイズ数値を取る。"""
    for token in re.split(r"[\s,]+", body):
        token = token.strip()
        if not token or token.startswith("0x") or token.startswith('"'):
            continue
        if re.fullmatch(r"\d+", token):
            return int(token)
    return None


def _parse_int(value: str) -> int | None:
    try:
        return int(value, 0)
    except ValueError:
        return None


def _path_connection_points(path: str) -> tuple[int, int] | None:
    """`20 04 24 xx 2C yy 2C zz` から (O->T, T->O) 接続点を返す。"""
    raw = parse_connection_path(path)
    points: list[int] = []
    index = 0
    while index < len(raw):
        if raw[index] == 0x2C and index + 1 < len(raw):
            points.append(raw[index + 1])
            index += 2
            continue
        if raw[index] in {0x20, 0x24} and index + 1 < len(raw):
            index += 2
            continue
        index += 1
    if len(points) >= 2:
        return points[0], points[1]
    return None
