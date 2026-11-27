"""Generated text in English and French (``locales/messages.*.toml``)."""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from functools import lru_cache
from importlib.resources import files
from typing import Any, Final

LANGS: Final = ("en", "fr")


@lru_cache
def messages(lang: str) -> dict[str, str]:
    text = files("assessment_engine").joinpath("locales", f"messages.{lang}.toml")
    data = tomllib.loads(text.read_text("utf-8"))
    return {str(k): str(v) for k, v in data["messages"].items()}


def check_parity() -> list[str]:
    en, fr = set(messages("en")), set(messages("fr"))
    return [f"{k}: only in en" for k in sorted(en - fr)] + [
        f"{k}: only in fr" for k in sorted(fr - en)
    ]


def render(key: str, lang: str, **values: Any) -> str:
    return messages(lang)[key].format(**values)


def join(items: Sequence[str], lang: str) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return f"{'; '.join(items[:-1])} {messages(lang)['list.and']} {items[-1]}"


def value(v: Any, lang: str) -> str:
    if isinstance(v, bool):
        return messages(lang)["value.true" if v else "value.false"]
    if isinstance(v, float):
        text = f"{v:g}"
        return text.replace(".", ",") if lang == "fr" else text
    return str(v)
