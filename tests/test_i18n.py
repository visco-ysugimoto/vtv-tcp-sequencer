from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend import i18n
from backend.catalog import format_command, load_catalog
from backend.i18n import (
    DEFAULT_LANG,
    SUPPORTED,
    LocalizedError,
    Msg,
    error_message,
    resolve_lang,
    t,
)
from backend.main import app
from backend.protocol import ProtocolError

BACKEND = Path(__file__).resolve().parent.parent / "backend"
_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_KEY_PREFIXES = (
    "main",
    "models",
    "catalog",
    "protocol",
    "engine",
    "cmd",
    "local",
    "plclink",
    "fn",
    "layout",
    "eds",
    "validation",
    "runapp",
)
_KEY_LITERAL = re.compile(
    r'"((?:' + "|".join(_KEY_PREFIXES) + r')\.[A-Za-z0-9_.]+)"'
)


def _load(lang: str) -> dict[str, str]:
    path = BACKEND / "locales" / lang / "messages.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_supported_and_default() -> None:
    assert SUPPORTED == ("ja", "en")
    assert DEFAULT_LANG == "ja"


def test_catalogs_have_same_keys_and_placeholders() -> None:
    ja, en = _load("ja"), _load("en")
    assert set(ja) == set(en)
    for key in ja:
        assert set(_PLACEHOLDER.findall(ja[key])) == set(
            _PLACEHOLDER.findall(en[key])
        ), key
        assert en[key].strip(), key


def test_every_key_used_in_backend_exists() -> None:
    ja = _load("ja")
    missing: list[str] = []
    for path in BACKEND.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        for key in _KEY_LITERAL.findall(path.read_text(encoding="utf-8")):
            if key not in ja:
                missing.append(f"{path.name}: {key}")
    assert not missing


def test_t_formats_and_falls_back() -> None:
    assert t("protocol.checksumMismatch", "ja", received="AA", calculated="BB") == (
        "チェックサム不一致: 受信=AA, 計算=BB"
    )
    assert t("protocol.checksumMismatch", "en", received="AA", calculated="BB") == (
        "Checksum mismatch: received=AA, calculated=BB"
    )
    assert t("no.such.key", "en") == "no.such.key"
    # 未対応言語は ja
    assert t("main.unknownOperation", "fr") == "不明な操作です"
    # Msg は入れ子で翻訳される
    assert "Command area" in t(
        "models.areaOverlap",
        "en",
        left=Msg("models.area.command"),
        right=Msg("models.area.response"),
    )


def test_resolve_lang() -> None:
    assert resolve_lang(None, None) == "ja"
    assert resolve_lang("en-US,en;q=0.9,ja;q=0.8") == "en"
    assert resolve_lang("ja,en;q=0.5") == "ja"
    assert resolve_lang("fr-FR,fr;q=0.9,en;q=0.5") == "en"
    assert resolve_lang("de") == "ja"
    assert resolve_lang("ja", explicit="en") == "en"
    assert resolve_lang("en", explicit="xx") == "en"


def test_protocol_error_is_localizable() -> None:
    exc = ProtocolError("protocol.notConnected")
    assert str(exc) == "装置に接続されていません"
    assert error_message(exc, "en") == "Not connected to the device"
    assert str(ProtocolError("raw text")) == "raw text"


def test_format_command_lang() -> None:
    definition = {
        "code": "XXX",
        "arguments": [
            {"key": "n", "label": "回数", "type": "integer", "min": 1, "max": 5, "digits": 2}
        ],
    }
    with pytest.raises(LocalizedError, match="回数は1〜5で入力してください"):
        format_command(definition, {"n": 9})
    with pytest.raises(LocalizedError, match="must be between 1 and 5") as info:
        format_command(definition, {"n": 9}, lang="en")
    assert info.value.localize("ja") == "回数は1〜5で入力してください"


def test_load_catalog_accepts_lang() -> None:
    assert load_catalog("en")[0]["code"] == load_catalog()[0]["code"]
    categories = {item["category_name"] for item in load_catalog("en")}
    assert "System" in categories


def test_api_localized_by_accept_language() -> None:
    client = TestClient(app)
    ja = client.post(
        "/api/plclink/memory/read",
        json={"items": [{"id": "a", "device": "D", "address": 0, "format": "word"}]},
    )
    en = client.post(
        "/api/plclink/memory/read",
        headers={"Accept-Language": "en-US,en;q=0.9"},
        json={"items": [{"id": "a", "device": "D", "address": 0, "format": "word"}]},
    )
    if ja.status_code == 503:
        assert ja.json()["detail"].startswith("疑似PLCが起動していません")
        assert en.json()["detail"].startswith("The simulated PLC is not running")


def test_reload_messages() -> None:
    i18n.reload_messages()
    assert t("main.unknownOperation") == "不明な操作です"
