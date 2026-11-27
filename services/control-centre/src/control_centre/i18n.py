"""UI strings in English and French.

``locales/en.toml`` and ``locales/fr.toml`` hold the same keys (``check_parity``).
French strings written by Claude Code are unverified; the ones provided by the project
owner are listed in ``fr.toml`` under ``[provenance]``. ``docs/fr-ui-strings.md`` is
generated from these files (``control-centre fr-strings``).
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from importlib.resources import files
from typing import Any, Final, Literal

Lang = Literal["en", "fr"]
LANGS: Final[tuple[Lang, Lang]] = ("en", "fr")
OTHER: Final[dict[str, Lang]] = {"en": "fr", "fr": "en"}


def _load(lang: str) -> dict[str, Any]:
    text = files("control_centre").joinpath("locales", f"{lang}.toml").read_text("utf-8")
    return tomllib.loads(text)


@lru_cache
def strings(lang: str) -> dict[str, str]:
    table = _load(lang)["strings"]
    return {str(k): str(v) for k, v in table.items()}


@lru_cache
def provided_by_owner() -> frozenset[str]:
    """French keys whose wording the project owner provided (not written by Claude Code)."""
    provenance = _load("fr").get("provenance", {})
    return frozenset(provenance.get("provided_by_project_owner", []))


def check_parity() -> list[str]:
    en, fr = set(strings("en")), set(strings("fr"))
    problems = [f"key {k} is in en.toml but not in fr.toml" for k in sorted(en - fr)]
    problems += [f"key {k} is in fr.toml but not in en.toml" for k in sorted(fr - en)]
    problems += [f"provenance lists unknown key {k}" for k in sorted(provided_by_owner() - fr)]
    return problems


class Translator:
    def __init__(self, lang: str) -> None:
        self.lang = lang
        self._strings = strings(lang)

    def __call__(self, key: str, **values: object) -> str:
        text = self._strings[key]  # a missing key is a bug: fail the render
        return text.format(**values) if values else text


PROVIDED = "Provided by the project owner"
UNVERIFIED = "Unverified, written by Claude Code"


def fr_strings_markdown() -> str:
    """docs/fr-ui-strings.md: every French UI string with its provenance."""
    fr, en, owner = strings("fr"), strings("en"), provided_by_owner()

    def cell(text: str) -> str:
        return text.replace("|", "\\|")

    lines = [
        "# French UI strings (control-centre)",
        "",
        "Generated from `services/control-centre/src/control_centre/locales/fr.toml` by",
        "`uv run control-centre fr-strings docs/fr-ui-strings.md`; CI fails if it is stale.",
        "",
        "Every French string is **unverified, written by Claude Code**, unless marked",
        "**provided by the project owner**. Policy wording never comes from these files: it comes",
        "from the French catalog. Have a qualified translator review the unverified strings",
        "before any use outside the demo.",
        "",
        f"{len(fr)} strings: {len(owner)} provided by the project owner, "
        f"{len(fr) - len(owner)} unverified.",
        "",
        "| Key | French | English | Status |",
        "|---|---|---|---|",
    ]
    for key in sorted(fr):
        status = PROVIDED if key in owner else UNVERIFIED
        lines.append(f"| `{key}` | {cell(fr[key])} | {cell(en[key])} | {status} |")
    return "\n".join(lines) + "\n"
