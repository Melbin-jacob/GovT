"""Clause-by-clause diff between two versions of a source document (one language).

Matching (plain code, deterministic, no AI):

1. **Exact**: clauses whose normalized text is identical are paired regardless of number
   (``unchanged`` or ``renumbered``). Typography-only edits count as identical.
2. **Similarity**: the remaining clauses are paired by an optimal one-to-one assignment
   (Hungarian algorithm) maximizing ``difflib.SequenceMatcher`` ratio over normalized word
   tokens. Pairs scoring below ``THRESHOLD`` are left unpaired.
3. **Split / merge**: an unpaired new clause whose tokens are mostly contained in an old
   clause (containment >= ``SPLIT_THRESHOLD``) is reported as part of a split of that old
   clause; symmetrically for merges. A single contained clause with an unpaired
   counterpart is paired by containment instead.
4. Whatever remains is ``added`` or ``removed``.

Every pair carries its method and score so a reviewer can see why clauses were paired.
Obligation words are compared per pair (and per split/merge group as a whole).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from govhub_shared.matching import containment, hungarian_max, similarity
from rulebook.obligations import Lang, obligation_terms
from rulebook.sources.model import Clause, SourceDocument
from rulebook.sources.normalize import match_tokens

METHOD = (
    "exact normalized text, then optimal one-to-one assignment (Hungarian) on "
    "difflib.SequenceMatcher ratio over normalized word tokens, then token containment "
    "for splits and merges"
)
THRESHOLD = 0.6
SPLIT_THRESHOLD = 0.8

Status = Literal["unchanged", "renumbered", "changed", "changed-renumbered"]
PairMethod = Literal["exact", "similarity", "containment"]


class ClausePair(BaseModel):
    old: str
    new: str
    status: Status
    method: PairMethod
    score: float
    flags: list[str] = []
    obligations_before: list[str] | None = None
    obligations_after: list[str] | None = None
    old_text: str | None = None
    new_text: str | None = None


class Split(BaseModel):
    old: str
    into: list[str]
    containment: dict[str, float]
    flags: list[str] = []


class Merge(BaseModel):
    olds: list[str]
    into: str
    containment: dict[str, float]
    flags: list[str] = []


class SourceDiff(BaseModel):
    instrument: str
    lang: Lang
    from_version: str
    to_version: str
    method: str = METHOD
    threshold: float = THRESHOLD
    split_threshold: float = SPLIT_THRESHOLD
    pairs: list[ClausePair]
    added: list[str]
    removed: list[str]
    splits: list[Split]
    merges: list[Merge]
    summary: dict[str, int]

    def changed_old_numbers(self) -> set[str]:
        """Old clause numbers whose substance changed (not renumbering alone)."""
        out = {p.old for p in self.pairs if "text-changed" in p.flags}
        out |= {s.old for s in self.splits} | {o for m in self.merges for o in m.olds}
        return out | set(self.removed)


# --- diff ------------------------------------------------------------------------------


def _status(old: Clause, new: Clause) -> Status:
    same_text = old.match_sha256 == new.match_sha256
    same_number = old.number == new.number
    if same_text:
        return "unchanged" if same_number else "renumbered"
    return "changed" if same_number else "changed-renumbered"


def _terms(text: str | None, lang: Lang) -> list[str]:
    return sorted(obligation_terms(text, lang).elements())


def diff_sources(
    old_doc: SourceDocument,
    new_doc: SourceDocument,
    *,
    threshold: float = THRESHOLD,
    split_threshold: float = SPLIT_THRESHOLD,
    include_text: bool = True,
) -> SourceDiff:
    if (old_doc.instrument, old_doc.lang) != (new_doc.instrument, new_doc.lang):
        raise ValueError("can only diff two versions of the same instrument and language")
    lang: Lang = old_doc.lang
    olds, news = list(old_doc.clauses), list(new_doc.clauses)
    tokens_old = [match_tokens(c.text or "") for c in olds]
    tokens_new = [match_tokens(c.text or "") for c in news]
    matched: dict[
        int, tuple[int, Literal["exact", "similarity", "containment"], float]
    ] = {}  # old index -> (new index, method, score)
    used_new: set[int] = set()

    # 1. exact normalized text (prefer the same number, then document order)
    for i, old in enumerate(olds):
        candidates = [
            j
            for j, new in enumerate(news)
            if j not in used_new and new.match_sha256 == old.match_sha256
        ]
        if candidates:
            j = next((j for j in candidates if news[j].number == old.number), candidates[0])
            matched[i] = (j, "exact", 1.0)
            used_new.add(j)

    # 2. optimal assignment on similarity for the rest
    rest_old = [i for i in range(len(olds)) if i not in matched]
    rest_new = [j for j in range(len(news)) if j not in used_new]
    if rest_old and rest_new:
        scores = [
            [
                similarity(tokens_old[i], tokens_new[j])
                + (1e-6 if olds[i].number == news[j].number else 0.0)  # deterministic tie-break
                for j in rest_new
            ]
            for i in rest_old
        ]
        for r, c in hungarian_max(scores):
            score = round(scores[r][c], 4)
            if score >= threshold:
                matched[rest_old[r]] = (rest_new[c], "similarity", score)
                used_new.add(rest_new[c])

    # 3. splits and merges by containment
    new_of_old = {i: j for i, (j, _, _) in matched.items()}
    old_of_new = {j: i for i, j in new_of_old.items()}
    split_parts: dict[int, dict[int, float]] = {}
    for j in range(len(news)):
        if j in used_new:
            continue
        best = max(
            ((containment(tokens_new[j], tokens_old[i]), -i) for i in range(len(olds))),
            default=(0.0, 0),
        )
        if best[0] >= split_threshold:
            split_parts.setdefault(-best[1], {})[j] = round(best[0], 4)
    merge_parts: dict[int, dict[int, float]] = {}
    for i in range(len(olds)):
        if i in matched:
            continue
        best = max(
            ((containment(tokens_old[i], tokens_new[j]), -j) for j in range(len(news))),
            default=(0.0, 0),
        )
        if best[0] >= split_threshold:
            merge_parts.setdefault(-best[1], {})[i] = round(best[0], 4)

    splits: list[Split] = []
    in_split_new: set[int] = set()
    split_old: set[int] = set()
    for i, parts in sorted(split_parts.items()):
        all_parts = dict(parts)
        if i in new_of_old:
            all_parts[new_of_old[i]] = round(
                containment(tokens_new[new_of_old[i]], tokens_old[i]), 4
            )
        if len(all_parts) == 1 and i not in matched:  # one contained clause: a plain pair
            ((j, score),) = all_parts.items()
            matched[i] = (j, "containment", score)
            used_new.add(j)
            continue
        order = sorted(all_parts)
        splits.append(
            Split(
                old=olds[i].number,
                into=[news[j].number for j in order],
                containment={news[j].number: all_parts[j] for j in order},
            )
        )
        in_split_new |= set(parts)
        split_old.add(i)

    merges: list[Merge] = []
    in_merge_old: set[int] = set()
    merge_new: set[int] = set()
    for j, parts in sorted(merge_parts.items()):
        parts = {i: s for i, s in parts.items() if i not in matched}
        if not parts:
            continue
        all_parts = dict(parts)
        if j in old_of_new:
            all_parts[old_of_new[j]] = round(
                containment(tokens_old[old_of_new[j]], tokens_new[j]), 4
            )
        if len(all_parts) == 1 and j not in used_new:
            ((i, score),) = all_parts.items()
            matched[i] = (j, "containment", score)
            used_new.add(j)
            continue
        order = sorted(all_parts)
        merges.append(
            Merge(
                olds=[olds[i].number for i in order],
                into=news[j].number,
                containment={olds[i].number: all_parts[i] for i in order},
            )
        )
        in_merge_old |= set(parts)
        merge_new.add(j)

    # 4. obligations, flags, output
    group_obligation_ok: dict[int, bool] = {}  # old index (split) -> obligations preserved
    for split in splits:
        i = next(k for k, c in enumerate(olds) if c.number == split.old)
        part_text = " ".join(
            news[k].text or "" for k, c in enumerate(news) if c.number in split.into
        )
        preserved = _terms(olds[i].text, lang) == _terms(part_text, lang)
        group_obligation_ok[i] = preserved
        split.flags = [] if preserved else ["obligation-change"]
    merged_into_ok: dict[int, bool] = {}
    for merge in merges:
        j = next(k for k, c in enumerate(news) if c.number == merge.into)
        part_text = " ".join(
            olds[k].text or "" for k, c in enumerate(olds) if c.number in merge.olds
        )
        preserved = _terms(part_text, lang) == _terms(news[j].text, lang)
        merged_into_ok[j] = preserved
        merge.flags = [] if preserved else ["obligation-change"]

    pairs: list[ClausePair] = []
    for i in sorted(matched):
        j, method, score = matched[i]
        old, new = olds[i], news[j]
        status = _status(old, new)
        flags: list[str] = []
        if old.number != new.number:
            flags.append("renumbered")
        if old.match_sha256 != new.match_sha256:
            flags.append("text-changed")
        elif old.text_sha256 != new.text_sha256:
            flags.append("typography-only")
        before, after = _terms(old.text, lang), _terms(new.text, lang)
        if i in group_obligation_ok:
            flags.append("split")
            obligation_changed = not group_obligation_ok[i]
        elif j in merged_into_ok:
            flags.append("merge")
            obligation_changed = not merged_into_ok[j]
        else:
            obligation_changed = before != after
        if obligation_changed:
            flags.append("obligation-change")
        pairs.append(
            ClausePair(
                old=old.number,
                new=new.number,
                status=status,
                method=method,
                score=score,
                flags=flags,
                obligations_before=before if obligation_changed else None,
                obligations_after=after if obligation_changed else None,
                old_text=old.text if include_text else None,
                new_text=new.text if include_text else None,
            )
        )

    added = [c.number for j, c in enumerate(news) if j not in used_new and j not in in_split_new]
    removed = [c.number for i, c in enumerate(olds) if i not in matched and i not in in_merge_old]
    statuses = [p.status for p in pairs]
    groups: list[Split | Merge] = [*splits, *merges]
    return SourceDiff(
        instrument=new_doc.instrument,
        lang=lang,
        from_version=old_doc.version,
        to_version=new_doc.version,
        threshold=threshold,
        split_threshold=split_threshold,
        pairs=pairs,
        added=added,
        removed=removed,
        splits=splits,
        merges=merges,
        summary={
            "unchanged": statuses.count("unchanged"),
            "renumbered": sum("renumbered" in p.flags for p in pairs),
            "text-changed": sum("text-changed" in p.flags for p in pairs),
            "obligation-change": sum("obligation-change" in p.flags for p in pairs)
            + sum(_group_only_obligation(g, pairs) for g in groups),
            "added": len(added),
            "removed": len(removed),
            "splits": len(splits),
            "merges": len(merges),
        },
    )


def _group_only_obligation(group: Split | Merge, pairs: list[ClausePair]) -> bool:
    """An obligation change on a split/merge with no paired member to carry the flag."""
    olds = {group.old} if isinstance(group, Split) else set(group.olds)
    carried = any(p.old in olds and ("split" in p.flags or "merge" in p.flags) for p in pairs)
    return "obligation-change" in group.flags and not carried


# --- EN/FR cross-check -----------------------------------------------------------------


class Divergence(BaseModel):
    kind: Literal["mapping", "obligation", "text-change"]
    clause: str
    en: str
    fr: str


def _mapping(diff: SourceDiff) -> dict[str, str]:
    out = {p.old: p.new for p in diff.pairs}
    for split in diff.splits:
        out[split.old] = "+".join(split.into)
    for merge in diff.merges:
        for old in merge.olds:
            out[old] = merge.into
    for old in diff.removed:
        out[old] = "(removed)"
    for new in diff.added:
        out[f"(added) {new}"] = new
    return out


def cross_check(en: SourceDiff, fr: SourceDiff) -> list[Divergence]:
    """Where the EN and FR diffs disagree. Each divergence needs a human look."""
    divergences: list[Divergence] = []
    map_en, map_fr = _mapping(en), _mapping(fr)
    for key in sorted(set(map_en) | set(map_fr), key=_sort_key):
        a, b = map_en.get(key, "(absent)"), map_fr.get(key, "(absent)")
        if a != b:
            divergences.append(Divergence(kind="mapping", clause=key, en=a, fr=b))
    flags_en = {p.old: set(p.flags) for p in en.pairs}
    flags_fr = {p.old: set(p.flags) for p in fr.pairs}
    for old in sorted(set(flags_en) & set(flags_fr), key=_sort_key):
        checks: tuple[tuple[str, Literal["obligation", "text-change"]], ...] = (
            ("obligation-change", "obligation"),
            ("text-changed", "text-change"),
        )
        for flag, kind in checks:
            if (flag in flags_en[old]) != (flag in flags_fr[old]):
                divergences.append(
                    Divergence(
                        kind=kind,
                        clause=old,
                        en=flag if flag in flags_en[old] else "no change",
                        fr=flag if flag in flags_fr[old] else "no change",
                    )
                )
    return divergences


def _sort_key(number: str) -> tuple[int, ...]:
    digits = number.split()[-1]
    return tuple(int(p) for p in digits.split(".") if p.isdigit())
