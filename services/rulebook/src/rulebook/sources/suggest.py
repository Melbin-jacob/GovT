"""Suggest source clauses for golden-set checks, as an aid for human annotators.

Plain text similarity, no AI. Output is a review CSV; nothing is written back to the
golden set. Annotators confirm links by filling the "Source clauses" column themselves.

Score = mean of the SequenceMatcher ratio and the token-set Jaccard index between the
check statement and the clause text (both normalized). Check statements are paraphrases,
so word-order-insensitive Jaccard complements the order-aware ratio.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from dataclasses import dataclass

from rulebook.golden import GoldenRow
from rulebook.obligations import Lang
from rulebook.sources.diff import similarity
from rulebook.sources.model import SourceDocument
from rulebook.sources.normalize import match_tokens

COLUMNS = (
    "Check ID",
    "Clause (draft numbering)",
    "Rank",
    "Suggested clause",
    "Score",
    "Ratio",
    "Jaccard",
    "Matches draft number",
    "Clause text (excerpt)",
)


@dataclass(frozen=True)
class Suggestion:
    check_id: str
    draft_clause: str
    rank: int
    clause: str
    score: float
    ratio: float
    jaccard: float
    matches_draft: bool
    excerpt: str | None


def jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 0.0


def suggest(
    rows: Sequence[GoldenRow],
    source: SourceDocument,
    *,
    lang: Lang = "en",
    top: int = 3,
    with_text: bool = False,
) -> list[Suggestion]:
    if source.content != "full":
        raise ValueError("suggestions need a full source document (with clause text)")
    clauses = [(c, match_tokens(c.text or "")) for c in source.clauses]
    out: list[Suggestion] = []
    for row in rows:
        tokens = match_tokens(row.statement[lang])
        scored = []
        for clause, clause_tokens in clauses:
            ratio = similarity(tokens, clause_tokens)
            jac = jaccard(tokens, clause_tokens)
            scored.append((round((ratio + jac) / 2, 4), round(ratio, 4), round(jac, 4), clause))
        scored.sort(key=lambda s: (-s[0], [int(p) for p in s[3].number.split(".")]))
        for rank, (score, ratio, jac, clause) in enumerate(scored[:top], start=1):
            out.append(
                Suggestion(
                    check_id=row.check_id,
                    draft_clause=row.clause,
                    rank=rank,
                    clause=clause.number,
                    score=score,
                    ratio=ratio,
                    jaccard=jac,
                    matches_draft=clause.number == row.clause,
                    excerpt=(clause.text or "")[:160] if with_text else None,
                )
            )
    return out


def to_csv(suggestions: Sequence[Suggestion]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerow(COLUMNS)
    for s in suggestions:
        writer.writerow(
            [
                s.check_id,
                s.draft_clause,
                s.rank,
                s.clause,
                s.score,
                s.ratio,
                s.jaccard,
                "yes" if s.matches_draft else "no",
                s.excerpt or "",
            ]
        )
    return buf.getvalue()
