"""Passages, language guess, keyword retrieval (BM25) and instruction-like text flags.

Retrieval is lexical (BM25 over normalized word tokens, English and French stop words
removed, light plural folding), so no second model is needed. Matching uses the same
normalization as the clause diff (``govhub_shared.text``).

Evidence is untrusted. ``injection_flags`` marks passages that contain instruction-like
text in English or French ("ignore previous instructions", "mark this as met",
"ignorez les instructions"...). Flagged passages are shown on the finding page and can
never be the only support for a *met* verdict. Pattern matching cannot catch every
attack: the prompt also passes evidence strictly as delimited data (see assess.py).
"""

from __future__ import annotations

import math
import re
import tomllib
from collections import Counter
from dataclasses import dataclass
from importlib.resources import files

from govhub_shared.text import match_tokens, normalize_for_match

MAX_CHARS = 1200
MIN_CHARS = 200

_DATA = tomllib.loads(
    files("assessment_engine").joinpath("injection_patterns.toml").read_text("utf-8")
)
STOP = set(_DATA["stop_words"]["en"]) | set(_DATA["stop_words"]["fr"])
EN_HINTS = {"the", "and", "of", "is", "are", "to", "with", "for", "be", "this", "that"}
FR_HINTS = {"le", "la", "les", "et", "des", "est", "sont", "du", "une", "pour", "avec", "dans"}

# (code, regex over normalized text), English and French: injection_patterns.toml.
INJECTION_PATTERNS: list[tuple[str, str]] = list(_DATA["patterns"].items())
_COMPILED = [(code, re.compile(rx, re.I | re.S)) for code, rx in INJECTION_PATTERNS]


def injection_flags(text: str) -> list[str]:
    norm = normalize_for_match(text)
    return [code for code, rx in _COMPILED if rx.search(norm)]


def guess_language(text: str) -> str:
    words = match_tokens(text)
    en = sum(w in EN_HINTS for w in words)
    fr = sum(w in FR_HINTS for w in words)
    if en == fr == 0:
        return "unknown"
    return "fr" if fr > en else "en"


def chunk(paragraphs: list[str]) -> list[str]:
    """Paragraphs merged up to MIN_CHARS and split at sentences above MAX_CHARS."""
    pieces: list[str] = []
    for para in paragraphs:
        if len(para) <= MAX_CHARS:
            pieces.append(para)
            continue
        current = ""
        for sentence in re.split(r"(?<=[.!?;])\s+", para):
            if current and len(current) + len(sentence) + 1 > MAX_CHARS:
                pieces.append(current)
                current = sentence
            else:
                current = f"{current} {sentence}".strip()
        if current:
            pieces.append(current)
    out: list[str] = []
    for piece in pieces:
        if out and len(out[-1]) < MIN_CHARS and len(out[-1]) + len(piece) + 1 <= MAX_CHARS:
            out[-1] = f"{out[-1]}\n{piece}"
        else:
            out.append(piece)
    return out


def terms(text: str) -> list[str]:
    out = []
    for token in match_tokens(text):
        if token in STOP or len(token) < 2:
            continue
        if len(token) > 4 and token[-1] in "sx":
            token = token[:-1]
        out.append(token)
    return out


def with_neighbours(hits: list[int], keys: list[tuple[str, int]], k: int) -> list[int]:
    """The best hits first, then the passages right before and after each hit in the same
    document, up to k. Keeps a sentence's context (e.g. "no notice by telephone" next to
    "notice online") even when it shares no word with the query."""
    position = {key: i for i, key in enumerate(keys)}
    chosen = list(dict.fromkeys(hits))[:k]
    for i in list(chosen):
        doc, seq = keys[i]
        for near in (seq - 1, seq + 1):
            j = position.get((doc, near))
            if j is not None and j not in chosen and len(chosen) < k:
                chosen.append(j)
    return chosen


@dataclass
class Scored:
    index: int
    score: float


def bm25(query: str, documents: list[str], k1: float = 1.5, b: float = 0.75) -> list[Scored]:
    """BM25 scores of every document for the query, best first (ties keep order)."""
    docs = [terms(d) for d in documents]
    if not docs:
        return []
    avg = sum(len(d) for d in docs) / len(docs) or 1.0
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    q = set(terms(query))
    scored = []
    for i, d in enumerate(docs):
        tf = Counter(d)
        score = 0.0
        for term in q:
            if tf[term] == 0:
                continue
            idf = math.log(1 + (len(docs) - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * tf[term] * (k1 + 1) / (tf[term] + k1 * (1 - b + b * len(d) / avg))
        scored.append(Scored(i, score))
    return sorted(scored, key=lambda s: (-s.score, s.index))
