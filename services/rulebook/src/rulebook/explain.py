"""Generated explanations in English and French, from ``locales/explanations.*.toml``.

The rulebook never writes prose inline: every generated sentence has a code and
parameters, and is rendered in both languages from the templates. Reports carry
``{"code", "params", "text": {"en", "fr"}}``, so they are language-neutral (the report ID
hashes codes and parameters only) and a French page never shows English text.
"""

from __future__ import annotations

import tomllib
from collections.abc import Mapping, Sequence
from functools import lru_cache
from importlib.resources import files
from typing import Any, Final

LANGS: Final = ("en", "fr")


@lru_cache
def templates(lang: str) -> dict[str, str]:
    text = files("rulebook").joinpath("locales", f"explanations.{lang}.toml").read_text("utf-8")
    return {str(k): str(v) for k, v in tomllib.loads(text)["templates"].items()}


def check_parity() -> list[str]:
    en, fr = set(templates("en")), set(templates("fr"))
    return [f"{k}: only in en" for k in sorted(en - fr)] + [
        f"{k}: only in fr" for k in sorted(fr - en)
    ]


def number(value: float, lang: str) -> str:
    """Two decimals; French uses a decimal comma."""
    text = f"{value:.2f}"
    return text.replace(".", ",") if lang == "fr" else text


def join(items: Sequence[str], lang: str) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} {templates(lang)['list.and']} {items[-1]}"


def _value(value: Any, lang: str) -> str:
    if isinstance(value, float):
        return number(value, lang)
    if isinstance(value, list | tuple):
        return join([_value(v, lang) for v in value], lang)
    return str(value)


def field_name(field: str, lang: str) -> str:
    return templates(lang).get(f"field.{field}", field)


def render(key: str, lang: str, params: Mapping[str, Any] | None = None) -> str:
    values: dict[str, str] = {}
    for name, value in (params or {}).items():
        if name == "fields":  # catalog field codes, e.g. part:statement
            values[name] = join([field_name(f, lang) for f in value], lang)
        elif name == "kind" and key == "maintenance.language-divergence":
            values[name] = templates(lang).get(f"divergence.{value}", str(value))
        else:
            values[name] = _value(value, lang)
    return templates(lang)[key].format(**values)


def both(key: str, params: Mapping[str, Any] | None = None) -> dict[str, str]:
    return {lang: render(key, lang, params) for lang in LANGS}


def item(key: str, params: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    """A coded explanation: ``{"code", "params", "text": {"en", "fr"}, **extra}``."""
    code = key.split(".", 1)[1]
    return {"code": code, "params": dict(params or {}), "text": both(key, params), **extra}
