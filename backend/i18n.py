"""バックエンド i18n（日本語 / 英語）。

メッセージは backend/locales/{lang}/messages.json（フラットな "ドット.区切り" キー）に置く。
``t(key, lang, **kwargs)`` で ``{var}`` 展開し、lang に無ければ ja、ja にも無ければキーを返す。

例外にはキー＋引数を保持させ、``str(exc)`` は常に日本語（既存挙動）、
リクエスト言語での表示が必要な箇所では ``error_message(exc, lang)`` を使う。
"""

from __future__ import annotations

import json
import re
from typing import Any

from .paths import locales_dir

SUPPORTED = ("ja", "en")
DEFAULT_LANG = "ja"

_catalogs: dict[str, dict[str, str]] = {}


def _load(lang: str) -> dict[str, str]:
    catalog = _catalogs.get(lang)
    if catalog is not None:
        return catalog
    path = locales_dir() / lang / "messages.json"
    try:
        with path.open(encoding="utf-8") as file:
            data = json.load(file)
    except (OSError, ValueError):
        data = {}
    catalog = {str(key): str(value) for key, value in data.items()}
    _catalogs[lang] = catalog
    return catalog


def reload_messages() -> None:
    """テスト・開発用: キャッシュを破棄して再読込する。"""
    _catalogs.clear()


def has_key(key: object) -> bool:
    return isinstance(key, str) and key in _load(DEFAULT_LANG)


def normalize_lang(lang: str | None) -> str:
    """'en-US' / 'EN' → 'en'。未対応は DEFAULT_LANG。"""
    if not lang:
        return DEFAULT_LANG
    primary = str(lang).strip().lower().replace("_", "-").split("-", 1)[0]
    return primary if primary in SUPPORTED else DEFAULT_LANG


class Msg:
    """遅延翻訳。t() の引数や例外パラメータへ入れ子で渡せる。"""

    __slots__ = ("key", "params")

    def __init__(self, key: str, /, **params: Any):
        self.key = key
        self.params = params

    def render(self, lang: str = DEFAULT_LANG) -> str:
        return t(self.key, lang, **self.params)

    def __str__(self) -> str:
        return self.render(DEFAULT_LANG)


class MsgJoin:
    """複数の Msg / 文字列を区切り文字で連結する遅延翻訳。"""

    __slots__ = ("parts", "sep")

    def __init__(self, parts: list[Any], sep: str = " "):
        self.parts = parts
        self.sep = sep

    def render(self, lang: str = DEFAULT_LANG) -> str:
        return self.sep.join(str(_render_param(part, lang)) for part in self.parts)

    def __str__(self) -> str:
        return self.render(DEFAULT_LANG)


def _render_param(value: Any, lang: str) -> Any:
    if isinstance(value, (Msg, MsgJoin)):
        return value.render(lang)
    if isinstance(value, BaseException):
        localize = getattr(value, "localize", None)
        if callable(localize):
            return localize(lang)
        return str(value)
    return value


def t(key: str, /, lang: str = DEFAULT_LANG, **kwargs: Any) -> str:
    """メッセージを取得して {var} を展開する。lang → ja → key の順にフォールバック。"""
    lang = normalize_lang(lang)
    template = _load(lang).get(key)
    if template is None:
        template = _load(DEFAULT_LANG).get(key)
    if template is None:
        return key
    if not kwargs:
        return template
    params = {name: _render_param(value, lang) for name, value in kwargs.items()}
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        return template


def parse_accept_language(header: str | None) -> list[str]:
    """Accept-Language を q 値の降順で言語タグ（小文字）に分解する。"""
    if not header:
        return []
    entries: list[tuple[float, int, str]] = []
    for index, part in enumerate(str(header).split(",")):
        piece = part.strip()
        if not piece:
            continue
        tag, _, rest = piece.partition(";")
        quality = 1.0
        match = re.search(r"q\s*=\s*([0-9.]+)", rest)
        if match:
            try:
                quality = float(match.group(1))
            except ValueError:
                quality = 0.0
        tag = tag.strip().lower()
        if tag and quality > 0:
            entries.append((-quality, index, tag))
    entries.sort()
    return [tag for _, _, tag in entries]


def resolve_lang(
    accept_language: str | None = None, explicit: str | None = None
) -> str:
    """明示指定（クエリ等）→ Accept-Language → DEFAULT_LANG の順で言語を決める。"""
    if explicit:
        primary = str(explicit).strip().lower().replace("_", "-").split("-", 1)[0]
        if primary in SUPPORTED:
            return primary
    for tag in parse_accept_language(accept_language):
        primary = tag.split("-", 1)[0]
        if primary in SUPPORTED:
            return primary
    return DEFAULT_LANG


def get_request_lang(request: Any) -> str:
    """FastAPI の Request / WebSocket から言語を決める。

    ``?lang=en`` を優先し、無ければ Accept-Language ヘッダを見る。
    """
    explicit: str | None = None
    query = getattr(request, "query_params", None)
    if query is not None:
        explicit = query.get("lang")
    headers = getattr(request, "headers", None)
    accept = headers.get("accept-language") if headers is not None else None
    return resolve_lang(accept, explicit)


class LocalizedMixin:
    """キー＋引数を保持する例外ミックスイン。

    ``Exc("some.key", a=1)`` のようにカタログのキーを渡すと翻訳対象になる。
    キーでない文字列を渡した場合はそのままメッセージとして扱う。
    """

    key: str | None
    params: dict[str, Any]

    def __init__(
        self, message: Any = "", /, *, lang: str = DEFAULT_LANG, **params: Any
    ):
        self._lazy: Any = None
        if isinstance(message, (Msg, MsgJoin)):
            self.key = None
            self.params = {}
            self._lazy = message
            text = message.render(lang)
        elif has_key(message):
            self.key = message
            self.params = params
            text = t(message, lang, **params)
        else:
            self.key = None
            self.params = {}
            text = str(message)
        super().__init__(text)  # type: ignore[misc]

    def localize(self, lang: str = DEFAULT_LANG) -> str:
        if self._lazy is not None:
            return self._lazy.render(lang)
        if self.key:
            return t(self.key, lang, **self.params)
        return str(self)


class LocalizedError(LocalizedMixin, ValueError):
    """検証エラー用（pydantic validator / format_command）。"""


class LocalizedIndexError(LocalizedMixin, IndexError):
    """メモリ／バッファの範囲外アクセス用。"""


def error_message(exc: BaseException, lang: str = DEFAULT_LANG) -> str:
    """例外を言語指定で文字列化する。未対応の例外は str(exc)。"""
    localize = getattr(exc, "localize", None)
    if callable(localize):
        return str(localize(lang))
    return str(exc)


def rebuild_error(exc: BaseException, cls: type[BaseException]) -> BaseException:
    """翻訳キーを保ったまま別の例外クラスへ載せ替える。"""
    lazy = getattr(exc, "_lazy", None)
    if lazy is not None:
        return cls(lazy)
    key = getattr(exc, "key", None)
    if key:
        return cls(key, **getattr(exc, "params", {}))
    return cls(str(exc))
