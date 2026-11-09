import pytest

from backend.catalog import format_command, load_catalog


def definition(code: str) -> dict:
    return next(item for item in load_catalog() if item["code"] == code)


def test_catalog_has_system_and_tool_commands() -> None:
    catalog = load_catalog()
    assert len(catalog) == 68
    assert len({item["code"] for item in catalog}) == 68
    assert sum(item["category"] == "system" for item in catalog) == 45
    assert sum(item["category"] == "tool" for item in catalog) == 23
    assert {item["code"] for item in catalog} >= {"PLI", "ESI", "PIP"}


def test_rrt_is_zero_padded() -> None:
    assert format_command(
        definition("RRT"), {"group": 1, "task": 2}
    ) == "RRT0102"


def test_out_of_range_argument_is_rejected() -> None:
    with pytest.raises(ValueError, match="1〜20"):
        format_command(definition("RRT"), {"group": 21, "task": 1})


def test_ica_uses_configured_line_number_digits() -> None:
    values = {"camera": 2, "line": 16, "calibration_id": 1}
    assert format_command(definition("ICA"), values, 2) == "ICA021601"
    assert format_command(definition("ICA"), values, 3) == "ICA0201601"


def test_kma_formats_comma_separated_coordinates() -> None:
    values = {
        "camera": 1,
        "line": 5,
        "module_type": "2",
        "module_id": "09",
        "operation": "1",
        "module_number": 10,
        "x": "-20.2",
        "y": "+123.5",
    }
    assert (
        format_command(definition("KMA"), values)
        == "KMA0105,2,09,1,010,-20.2,+123.5"
    )


def test_dfa_validates_path_by_mode() -> None:
    setting = {"camera": 1, "line": 16, "mode": "0", "path": r"C:\temp"}
    assert format_command(definition("DFA"), setting) == r"DFA01160C:\temp"
    assert format_command(
        definition("DFA"),
        {"camera": 1, "line": 0, "mode": "1", "path": ""},
    ) == "DFA01001"
    with pytest.raises(ValueError, match="フォルダ名を入力"):
        format_command(
            definition("DFA"),
            {"camera": 1, "line": 16, "mode": "0", "path": ""},
        )


def test_was_formats_ocv_subcommands() -> None:
    values = {
        "camera": 1,
        "line": 2,
        "block": 1,
        "enabled": "1",
        "font": 23,
        "character_count": 10,
        "text": "0123ABCabc",
        "multi_position": 5,
        "multi_characters": "BCDEabcde",
        "additional_blocks": "",
    }
    assert format_command(definition("WAS"), values) == (
        "WAS0102,BL01,BF1,FG023,FC10,FS0123ABCabc,FM05BCDEabcde"
    )
    assert format_command(definition("WAS"), {**values, "multi": 1}) == (
        "WAS0102,BL01,BF1,FG023,FC10,FS0123ABCabc,FM05BCDEabcde"
    )


def test_load_catalog_en_overlay_and_ja_unchanged() -> None:
    en = {item["code"]: item for item in load_catalog("en")}
    ja = {item["code"]: item for item in load_catalog("ja")}
    assert en["RRT"]["name"] == "Run specified task"
    assert en["RRT"]["arguments"][0]["label"] == "Group number"
    assert ja["RRT"]["name"] == "指定タスク実行"
    assert ja["RRT"]["arguments"][0]["label"] == "グループ番号"
    # 構文・桁数などは変更されない
    assert en["RRT"]["arguments"][0]["digits"] == ja["RRT"]["arguments"][0]["digits"]
    assert en["SIE"]["arguments"][0]["options"][0] == {
        "value": "0",
        "label": "All images",
    }
    assert format_command(en["RRT"], {"group": 1, "task": 2}) == "RRT0102"
    # オーバーレイ適用後も元の ja データは汚染されない
    assert load_catalog("ja")[0]["name"] == ja[load_catalog("ja")[0]["code"]]["name"]


def test_en_catalog_has_no_japanese_text() -> None:
    import re

    japanese = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef]")
    leftovers: list[str] = []
    for command in load_catalog("en"):
        texts = [command["name"], command["description"], command.get("tool_name", ""),
                 command.get("syntax", ""), command["category_name"]]
        for argument in command.get("arguments", []):
            texts.append(argument["label"])
            texts.extend(option["label"] for option in argument.get("options", []))
        leftovers += [f"{command['code']}: {x}" for x in texts if japanese.search(x)]
    assert not leftovers
