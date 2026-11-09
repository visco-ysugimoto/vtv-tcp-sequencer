from __future__ import annotations

import copy
import json
import math
import re
from typing import Any

from .i18n import DEFAULT_LANG, LocalizedError, normalize_lang, t
from .paths import catalog_dir, locales_dir

CATALOG_DIR = catalog_dir()
SYSTEM_CATALOG = CATALOG_DIR / "system_commands.json"


# i18n キー検査テストがリテラル文字列を翻訳キーと誤検知しないよう分割して記述
_OVERLAY_FILE = "catalog" + ".json"
_overlay_cache: dict[str, dict[str, Any]] = {}
_TEXT_FIELDS = ("name", "description", "tool_name", "syntax", "category_name")


def _load_overlay(lang: str) -> dict[str, Any]:
    if lang not in _overlay_cache:
        path = locales_dir() / lang / _OVERLAY_FILE
        if path.is_file():
            with path.open(encoding="utf-8") as file:
                _overlay_cache[lang] = json.load(file)
        else:
            _overlay_cache[lang] = {}
    return _overlay_cache[lang]


def apply_catalog_locale(
    catalog: list[dict[str, Any]], lang: str = DEFAULT_LANG
) -> list[dict[str, Any]]:
    """カタログ文言（名称・引数ラベルなど）を lang へ上書きする。

    ja は無変更でそのまま返す。それ以外は locales/<lang>/catalog.json を
    コマンドコード単位のオーバーレイとして適用する（元データは変更しない）。
    """
    lang = normalize_lang(lang)
    if lang == DEFAULT_LANG:
        return catalog
    overlay = _load_overlay(lang)
    if not overlay:
        return catalog

    result: list[dict[str, Any]] = []
    for command in catalog:
        entry = overlay.get(command["code"])
        if not entry:
            result.append(command)
            continue
        command = copy.deepcopy(command)
        for field in _TEXT_FIELDS:
            if field in entry:
                command[field] = entry[field]
        arg_overlay = entry.get("arguments", {})
        for argument in command.get("arguments", []):
            arg_entry = arg_overlay.get(argument["key"])
            if not arg_entry:
                continue
            if "label" in arg_entry:
                argument["label"] = arg_entry["label"]
            option_overlay = arg_entry.get("options", {})
            for option in argument.get("options", []):
                label = option_overlay.get(str(option["value"]))
                if label is not None:
                    option["label"] = label
        result.append(command)
    return result


def load_catalog(lang: str = DEFAULT_LANG) -> list[dict[str, Any]]:
    lang = normalize_lang(lang)
    catalog: list[dict[str, Any]] = []
    for path in sorted(CATALOG_DIR.glob("*_commands.json")):
        with path.open(encoding="utf-8") as file:
            commands = json.load(file)
        for command in commands:
            if path == SYSTEM_CATALOG:
                command.setdefault("category", "system")
                command.setdefault(
                    "category_name", t("catalog.category.system", lang)
                )
            else:
                command.setdefault("category", "tool")
                command.setdefault(
                    "category_name", t("catalog.category.tool", lang)
                )
            catalog.append(command)

    codes = [item["code"] for item in catalog]
    duplicates = sorted({code for code in codes if codes.count(code) > 1})
    if duplicates:
        raise LocalizedError(
            "catalog.duplicateCodes", codes=", ".join(duplicates)
        )
    return apply_catalog_locale(catalog, lang)


def catalog_by_code(lang: str = DEFAULT_LANG) -> dict[str, dict[str, Any]]:
    return {item["code"]: item for item in load_catalog(lang)}


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
    lang: str = DEFAULT_LANG,
) -> str:
    """コマンド文字列を組み立てる。

    不正値は LocalizedError。str(exc) は lang のメッセージで、
    キー＋引数も保持するので ``exc.localize(別言語)`` でも再翻訳できる。
    """
    try:
        return _format_command(definition, values, line_number_digits)
    except LocalizedError as exc:
        if normalize_lang(lang) == DEFAULT_LANG:
            raise
        raise LocalizedError(
            str(exc.key), lang=lang, **exc.params
        ) from exc


def _format_command(
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
        if argument.get("mapped_only"):
            # PLCLINK / Field Network 専用。TCP コマンド文字列には含めない。
            continue
        required = not argument.get("optional") or _condition_matches(
            argument.get("required_if"), values
        )
        if key not in values:
            if not required:
                continue
            raise LocalizedError("catalog.argRequired", label=argument["label"])
        value = values[key]
        value_text = str(value)
        if not value_text:
            if not required:
                continue
            raise LocalizedError("catalog.argRequired", label=argument["label"])
        if _condition_matches(argument.get("forbidden_if"), values):
            raise LocalizedError(
                "catalog.argForbidden", label=argument["label"]
            )
        if argument["type"] == "integer":
            try:
                number = int(value_text)
            except ValueError as exc:
                raise LocalizedError(
                    "catalog.argInteger", label=argument["label"]
                ) from exc
            if (
                not math.isfinite(number)
                or number < argument["min"]
                or number > argument["max"]
            ):
                raise LocalizedError(
                    "catalog.argRange",
                    label=argument["label"],
                    min=argument["min"],
                    max=argument["max"],
                )
            digits = (
                line_number_digits
                if argument.get("line_number")
                else argument["digits"]
            )
            if argument.get("line_number"):
                maximum = 99 if digits == 2 else 999
                if number > maximum:
                    raise LocalizedError(
                        "catalog.argLineNumberMax",
                        label=argument["label"],
                        max=maximum,
                    )
            value_text = (
                str(number)
                if argument.get("variable_digits")
                else f"{number:0{digits}d}"
            )
        elif argument["type"] == "enum":
            allowed = {str(option["value"]) for option in argument["options"]}
            if value_text not in allowed:
                raise LocalizedError(
                    "catalog.argInvalidValue", label=argument["label"]
                )
        elif argument["type"] == "number":
            try:
                number = float(value_text)
            except ValueError as exc:
                raise LocalizedError(
                    "catalog.argNumber", label=argument["label"]
                ) from exc
            if number < argument["min"] or number > argument["max"]:
                raise LocalizedError(
                    "catalog.argRange",
                    label=argument["label"],
                    min=argument["min"],
                    max=argument["max"],
                )
            max_length = argument.get("max_length")
            if max_length and len(value_text) > max_length:
                raise LocalizedError(
                    "catalog.argMaxLength",
                    label=argument["label"],
                    max=max_length,
                )
        elif argument["type"] == "string":
            min_length = argument.get("min_length", 0)
            max_length = argument.get("max_length")
            if len(value_text) < min_length:
                raise LocalizedError(
                    "catalog.argMinLength",
                    label=argument["label"],
                    min=min_length,
                )
            if max_length and len(value_text) > max_length:
                raise LocalizedError(
                    "catalog.argMaxLength",
                    label=argument["label"],
                    max=max_length,
                )
            pattern = argument.get("pattern")
            if pattern and not re.fullmatch(pattern, value_text):
                raise LocalizedError(
                    "catalog.argBadChars", label=argument["label"]
                )
        rendered.append(f"{argument.get('prefix', '')}{value_text}")

    return command + "".join(rendered)
