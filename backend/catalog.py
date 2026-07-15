from __future__ import annotations

import json
import math
import re
from typing import Any

from .paths import catalog_dir

CATALOG_DIR = catalog_dir()
SYSTEM_CATALOG = CATALOG_DIR / "system_commands.json"


def load_catalog() -> list[dict[str, Any]]:
    catalog: list[dict[str, Any]] = []
    for path in sorted(CATALOG_DIR.glob("*_commands.json")):
        with path.open(encoding="utf-8") as file:
            commands = json.load(file)
        for command in commands:
            if path == SYSTEM_CATALOG:
                command.setdefault("category", "system")
                command.setdefault("category_name", "システム")
            else:
                command.setdefault("category", "tool")
                command.setdefault("category_name", "ツール")
            catalog.append(command)

    codes = [item["code"] for item in catalog]
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    if duplicates:
        raise ValueError(
            f"コマンドコードが重複しています: {', '.join(duplicates)}"
        )
    return catalog


def catalog_by_code() -> dict[str, dict[str, Any]]:
    return {item["code"]: item for item in load_catalog()}


def _condition_matches(
    condition: dict[str, Any] | None, values: dict[str, str | int]
) -> bool:
    return bool(
        condition
        and str(values.get(condition["key"], "")) == str(condition["equals"])
    )


def format_command(
    definition: dict[str, Any],
    values: dict[str, str | int],
    line_number_digits: int = 2,
) -> str:
    command = definition["code"]
    if definition.get("raw_arguments"):
        return command + str(values.get("raw", ""))

    rendered: list[str] = []
    for argument in definition.get("arguments", []):
        key = argument["key"]
        required = not argument.get("optional") or _condition_matches(
            argument.get("required_if"), values
        )
        if key not in values:
            if not required:
                continue
            raise ValueError(f"{argument['label']}を入力してください")
        value = values[key]
        value_text = str(value)
        if not value_text:
            if not required:
                continue
            raise ValueError(f"{argument['label']}を入力してください")
        if _condition_matches(argument.get("forbidden_if"), values):
            raise ValueError(
                f"{argument['label']}はこの動作モードでは入力できません"
            )
        if argument["type"] == "integer":
            try:
                number = int(value_text)
            except ValueError as exc:
                raise ValueError(
                    f"{argument['label']}は整数で入力してください"
                ) from exc
            if (
                not math.isfinite(number)
                or number < argument["min"]
                or number > argument["max"]
            ):
                raise ValueError(
                    f"{argument['label']}は"
                    f"{argument['min']}〜{argument['max']}で入力してください"
                )
            digits = (
                line_number_digits
                if argument.get("line_number")
                else argument["digits"]
            )
            if argument.get("line_number"):
                maximum = 99 if digits == 2 else 999
                if number > maximum:
                    raise ValueError(
                        f"{argument['label']}は0〜{maximum}で入力してください"
                    )
            value_text = (
                str(number)
                if argument.get("variable_digits")
                else f"{number:0{digits}d}"
            )
        elif argument["type"] == "enum":
            allowed = {str(option["value"]) for option in argument["options"]}
            if value_text not in allowed:
                raise ValueError(f"{argument['label']}の値が不正です")
        elif argument["type"] == "number":
            try:
                number = float(value_text)
            except ValueError as exc:
                raise ValueError(
                    f"{argument['label']}は数値で入力してください"
                ) from exc
            if number < argument["min"] or number > argument["max"]:
                raise ValueError(
                    f"{argument['label']}は"
                    f"{argument['min']}〜{argument['max']}で入力してください"
                )
            max_length = argument.get("max_length")
            if max_length and len(value_text) > max_length:
                raise ValueError(
                    f"{argument['label']}は{max_length}文字以内です"
                )
        elif argument["type"] == "string":
            min_length = argument.get("min_length", 0)
            max_length = argument.get("max_length")
            if len(value_text) < min_length:
                raise ValueError(
                    f"{argument['label']}は{min_length}文字以上です"
                )
            if max_length and len(value_text) > max_length:
                raise ValueError(
                    f"{argument['label']}は{max_length}文字以内です"
                )
            pattern = argument.get("pattern")
            if pattern and not re.fullmatch(pattern, value_text):
                raise ValueError(
                    f"{argument['label']}に使用できない文字が含まれています"
                )
        rendered.append(f"{argument.get('prefix', '')}{value_text}")

    return command + "".join(rendered)
