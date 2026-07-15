import pytest

from backend.catalog import format_command, load_catalog


def definition(code: str) -> dict:
    return next(item for item in load_catalog() if item["code"] == code)


def test_catalog_has_system_and_tool_commands() -> None:
    catalog = load_catalog()
    assert len(catalog) == 65
    assert len({item["code"] for item in catalog}) == 65
    assert sum(item["category"] == "system" for item in catalog) == 43
    assert sum(item["category"] == "tool" for item in catalog) == 22


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
