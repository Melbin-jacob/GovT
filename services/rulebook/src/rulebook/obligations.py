"""Obligation-word extraction (plain code, no AI).

A change in obligation words between two versions of a statement is flagged as
``obligation-change`` so a human reviews it: "must" -> "should", but also "must" ->
"must not", because a negated obligation is a different value.

Matching runs on the typography-normalized text (``normalize_for_match``: case-folded,
typographic apostrophes and no-break spaces unified), on whole words, per language.
Negated forms are found first; a word inside a negated form never also counts as the
positive word.

English: must, shall, should, may, required; negated: must not, shall not, should not,
may not (also mustn't, shan't, shouldn't).

French: doit, doivent, peut, peuvent, devrait, devraient, est tenu(e); negated:
ne/n' ... <verb> ... pas|plus|jamais|aucunement|nullement|en aucun cas (up to three words
between ``ne`` and the verb and between the verb and the negator, e.g. "ne le doit pas",
"ne peut toutefois pas"), and "n'est pas tenu(e)" / "ne sont pas tenu(e)s".
Punctuation ends a match. A negated form is reported as ``ne <verb> <negator>``,
e.g. ``ne doit pas``.

"ne <verb> que" (e.g. "ne doit que" = "must only") is a **restriction, not a negation**:
it is reported as its own value ``ne <verb> que``, and "que" never fills a negation gap,
so "ne peut que constater pas moins de deux erreurs" is not read as "ne peut pas".
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Literal

from rulebook.sources.normalize import normalize_for_match

Lang = Literal["en", "fr"]

OBLIGATION_TERMS: dict[Lang, tuple[str, ...]] = {
    "en": ("must", "shall", "should", "may", "required"),
    "fr": ("doit", "doivent", "peut", "peuvent", "devrait", "devraient", "est tenu"),
}
NEGATED_TERMS: dict[Lang, tuple[str, ...]] = {
    "en": ("must not", "shall not", "should not", "may not"),
    "fr": (
        *(
            f"ne {verb} {neg}"
            for verb in ("doit", "doivent", "peut", "peuvent", "devrait", "devraient")
            for neg in ("pas", "plus", "jamais", "aucunement", "nullement", "en aucun cas")
        ),
        "n'est pas tenu",
    ),
}
RESTRICTION_TERMS: tuple[str, ...] = tuple(
    f"ne {verb} que" for verb in ("doit", "doivent", "peut", "peuvent", "devrait", "devraient")
)

# A word, without crossing punctuation. "que"/"qu'" never fills a gap: "ne ... que" is a
# restriction ("ne doit que" = "must only"), and must not be bridged into a negation.
_WORD = r"(?!qu(?:e\b|'))[^\W\d][\w'-]*"
_GAP = rf"(?:{_WORD}\s+){{0,3}}?"  # up to three words, each followed by whitespace
_GAP_AFTER = rf"(?:\s+{_WORD}){{0,3}}?"
_FR_VERBS = r"doit|doivent|peut|peuvent|devrait|devraient"
_FR_NEGATORS = r"pas|plus|jamais|aucunement|nullement|en\s+aucun\s+cas"

# "ne <verb> que" / "ne <verb> qu'": a restriction, never a negation. Its own value.
_FR_RESTRICTION = re.compile(rf"(?:\bne\s+|\bn')({_GAP})?\b({_FR_VERBS})\s+qu(?:e\b|')")

_NEGATED: dict[Lang, list[re.Pattern[str]]] = {
    "en": [
        re.compile(r"\b(must|shall|should|may)\s+not\b"),
        re.compile(r"\b(must|sha|should)n't\b"),
    ],
    "fr": [
        re.compile(rf"(?:\bne\s+|\bn')({_GAP})?\b({_FR_VERBS})\b{_GAP_AFTER}\s+({_FR_NEGATORS})\b"),
        re.compile(r"(?:\bn'est|\bne\s+sont)\s+pas\s+tenue?s?\b"),
    ],
}
_POSITIVE: dict[Lang, re.Pattern[str]] = {
    "en": re.compile(r"\b(must|shall|should|may|required)\b"),
    "fr": re.compile(rf"\b({_FR_VERBS}|est\s+tenue?)\b"),
}
_CONTRACTION = {"must": "must", "sha": "shall", "should": "should"}


def _negated_term(lang: Lang, match: re.Match[str]) -> str:
    if lang == "en":
        verb = match.group(1)
        return f"{_CONTRACTION.get(verb, verb)} not"
    if match.re is _NEGATED["fr"][1]:
        return "n'est pas tenu"
    return f"ne {match.group(2)} {' '.join(match.group(3).split())}"


def obligation_terms(text: str | None, lang: Lang) -> Counter[str]:
    """Multiset of obligation terms (positive and negated) in ``text``."""
    if not text:
        return Counter()
    normalized = normalize_for_match(text)
    terms: Counter[str] = Counter()
    negated_spans: list[tuple[int, int]] = []
    if lang == "fr":
        for match in _FR_RESTRICTION.finditer(normalized):
            negated_spans.append(match.span())
            terms[f"ne {match.group(2)} que"] += 1
    for pattern in _NEGATED[lang]:
        for match in pattern.finditer(normalized):
            if any(s <= match.start() < e for s, e in negated_spans):
                continue
            negated_spans.append(match.span())
            terms[_negated_term(lang, match)] += 1
    for match in _POSITIVE[lang].finditer(normalized):
        if any(s <= match.start() < e for s, e in negated_spans):
            continue
        term = " ".join(match.group(1).split())
        terms["est tenu" if term.startswith("est tenu") else term] += 1
    return terms


def obligation_changed(before: str | None, after: str | None, lang: Lang) -> bool:
    return obligation_terms(before, lang) != obligation_terms(after, lang)
