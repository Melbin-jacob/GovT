"""Obligation-word extraction (plain code, no AI).

A change in obligation words between two versions of a statement ("must" -> "should") is
flagged as ``obligation-change`` so a human reviews it. Matching is case-insensitive, on
whole words, per language.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Literal

Lang = Literal["en", "fr"]

OBLIGATION_TERMS: dict[Lang, tuple[str, ...]] = {
    "en": ("must", "shall", "should", "may", "required"),
    # "est tenu" also matches its feminine form "est tenue".
    "fr": ("doit", "doivent", "peut", "peuvent", "est tenu"),
}

_PATTERNS: dict[Lang, re.Pattern[str]] = {
    "en": re.compile(r"\b(must|shall|should|may|required)\b", re.IGNORECASE),
    "fr": re.compile(r"\b(doit|doivent|peut|peuvent|est\s+tenue?)\b", re.IGNORECASE),
}


def _canonical(term: str) -> str:
    term = " ".join(term.lower().split())
    return "est tenu" if term == "est tenue" else term


def obligation_terms(text: str | None, lang: Lang) -> Counter[str]:
    """Multiset of obligation terms in ``text``."""
    if not text:
        return Counter()
    return Counter(_canonical(m.group(1)) for m in _PATTERNS[lang].finditer(text))


def obligation_changed(before: str | None, after: str | None, lang: Lang) -> bool:
    return obligation_terms(before, lang) != obligation_terms(after, lang)
