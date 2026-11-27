"""Clause diff on synthetic data only (official text is never in CI)."""

from __future__ import annotations

import itertools
import json
import random
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from govhub_shared.matching import hungarian_max, similarity
from rulebook.sources.diff import THRESHOLD, cross_check, diff_sources
from rulebook.sources.model import Clause, SourceDocument, SourceFile
from rulebook.sources.normalize import match_tokens, normalize_for_match, sha256_text

DEMO = Path(__file__).resolve().parents[3] / "data" / "demo"
EXPECTED = json.loads((DEMO / "expected-diff.json").read_text("utf-8"))


def demo(version: str, lang: str) -> SourceDocument:
    path = DEMO / "sources" / f"example-widgets.{version}.{lang}.json"
    return SourceDocument.model_validate_json(path.read_text("utf-8"))


def make_doc(clauses: list[tuple[str, str]], version: str = "2025-01-01") -> SourceDocument:
    """A synthetic document from (number, text) pairs."""
    return SourceDocument(
        content="full",
        instrument="example-widgets",
        title="SYNTHETIC",
        effective_date=date.fromisoformat(version),
        lang="en",
        source_url="https://example.invalid",
        synthetic=True,
        file=SourceFile(name="synthetic.txt", sha256="0" * 64),
        clauses=[
            Clause(
                number=n,
                section=".".join(n.split(".")[:2]),
                text=t,
                text_sha256=sha256_text(t),
                match_sha256=sha256_text(normalize_for_match(t)),
            )
            for n, t in clauses
        ],
    )


# --- demo ground truth -----------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_demo_diff_matches_ground_truth(lang: str) -> None:
    diff = diff_sources(demo("2023-01-01", lang), demo("2025-01-01", lang))
    assert {p.old: [p.new, p.status] for p in diff.pairs} == EXPECTED["pairs"]
    assert [p.old for p in diff.pairs if "obligation-change" in p.flags] == (
        EXPECTED["obligation_change"]
    )
    assert {s.old: s.into for s in diff.splits} == EXPECTED["splits"]
    assert diff.added == EXPECTED["added"]
    assert diff.removed == EXPECTED["removed"]
    assert diff.merges == []
    assert diff.threshold == THRESHOLD
    if lang == "fr":
        typography = [p.old for p in diff.pairs if "typography-only" in p.flags]
        assert typography == EXPECTED["typography_only_fr"]


def test_demo_obligation_change_detail() -> None:
    diff = diff_sources(demo("2023-01-01", "en"), demo("2025-01-01", "en"))
    pair = next(p for p in diff.pairs if p.old == "6.2.1")
    assert (pair.obligations_before, pair.obligations_after) == (["should"], ["must"])
    assert pair.old_text == "Widgets should be calibrated at least once a year."
    split = diff.splits[0]
    assert split.flags == []  # "must" twice before, once in each part after


def test_demo_cross_check_agrees() -> None:
    en = diff_sources(demo("2023-01-01", "en"), demo("2025-01-01", "en"))
    fr = diff_sources(demo("2023-01-01", "fr"), demo("2025-01-01", "fr"))
    assert cross_check(en, fr) == []


def test_cross_check_reports_divergences() -> None:
    en = diff_sources(demo("2023-01-01", "en"), demo("2025-01-01", "en"))
    fr_new = demo("2025-01-01", "fr")
    clauses = [c for c in fr_new.clauses if c.number != "6.3.3"]  # FR drops a clause
    tweaked = []
    for c in clauses:
        if c.number == "6.3.2":  # FR-only obligation change on a renumbered clause
            text = (c.text or "").replace("doivent", "peuvent")
            c = c.model_copy(
                update={
                    "text": text,
                    "text_sha256": sha256_text(text),
                    "match_sha256": sha256_text(normalize_for_match(text)),
                }
            )
        tweaked.append(c)
    fr = diff_sources(demo("2023-01-01", "fr"), fr_new.model_copy(update={"clauses": tweaked}))
    kinds = {(d.kind, d.clause) for d in cross_check(en, fr)}
    assert ("mapping", "6.2.3") in kinds
    assert ("obligation", "6.2.2") in kinds


def test_diff_requires_same_instrument_and_language() -> None:
    with pytest.raises(ValueError, match="same instrument and language"):
        diff_sources(demo("2023-01-01", "en"), demo("2025-01-01", "fr"))


# --- primitives ------------------------------------------------------------------------


def _brute_force_best(scores: list[list[float]]) -> float:
    rows, cols = len(scores), len(scores[0])
    if rows <= cols:
        perms = itertools.permutations(range(cols), rows)
        return max(sum(scores[r][c] for r, c in enumerate(p)) for p in perms)
    perms = itertools.permutations(range(rows), cols)
    return max(sum(scores[r][c] for c, r in enumerate(p)) for p in perms)


def test_hungarian_matches_brute_force() -> None:
    rng = random.Random(7)  # noqa: S311 - deterministic test data
    for _ in range(40):
        rows, cols = rng.randint(1, 5), rng.randint(1, 5)
        scores = [[round(rng.random(), 3) for _ in range(cols)] for _ in range(rows)]
        got = hungarian_max(scores)
        assert len(got) == min(rows, cols)
        assert len({r for r, _ in got}) == len({c for _, c in got}) == len(got)
        assert sum(scores[r][c] for r, c in got) == pytest.approx(_brute_force_best(scores))


def test_similarity_ignores_typography() -> None:
    a = match_tokens("Les résultats d'étalonnage « doivent » être examinés")
    b = match_tokens("Les résultats d’étalonnage « doivent » être examinés")
    assert similarity(a, b) == 1.0


# --- seeded random transformations with known answers ----------------------------------

VOCAB = [
    "gadget",
    "gizmo",
    "sprocket",
    "lever",
    "spindle",
    "bracket",
    "flange",
    "gasket",
    "rivet",
    "ratchet",
    "pulley",
    "cog",
    "dial",
    "knob",
    "valve",
    "nozzle",
    "hinge",
    "latch",
    "toggle",
    "clamp",
]


def _new_clause(rng: random.Random, k: int) -> str:
    words = rng.sample(VOCAB, 8)
    return f"Synthetic clause {k}: the {' '.join(words)} are inspected."


def transform(
    rng: random.Random, base: list[tuple[str, str]]
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    """Apply recorded edits, then renumber within sections. Returns new clauses + truth."""
    items: list[dict[str, Any]] = [
        {"old": n, "text": t, "section": n.rsplit(".", 1)[0]} for n, t in base
    ]
    truth: dict[str, Any] = {"deleted": [], "split": {}, "obligation": [], "inserted": []}
    ops = rng.sample(["delete", "split", "obligation", "insert", "shift"], k=rng.randint(2, 5))
    if "delete" in ops:
        victim = rng.choice(items)
        items.remove(victim)
        truth["deleted"].append(victim["old"])
    if "split" in ops:
        candidates = [it for it in items if len(it["text"].split()) >= 10 and it["old"]]
        if candidates:
            it = rng.choice(candidates)
            words = it["text"].split()
            mid = len(words) // 2
            first = {**it, "text": " ".join(words[:mid]), "part": 1}
            second = {**it, "text": " ".join(words[mid:]), "part": 2}
            idx = items.index(it)
            items[idx : idx + 1] = [first, second]
            truth["split"][it["old"]] = True
    if "obligation" in ops:
        candidates = [it for it in items if " must " in it["text"] and "part" not in it]
        if candidates:
            it = rng.choice(candidates)
            it["text"] = it["text"].replace(" must ", " should ", 1)
            truth["obligation"].append(it["old"])
    if "insert" in ops:
        pos = rng.randrange(len(items) + 1)
        section = items[min(pos, len(items) - 1)]["section"]
        items.insert(pos, {"old": None, "text": _new_clause(rng, pos), "section": section})
        truth["inserted"].append(pos)
    if "shift" in ops:  # every section from a random point moves down by one (6.2 -> 6.3 ...)
        sections = sorted({it["section"] for it in items}, key=lambda s: int(s.split(".")[1]))
        start = rng.randrange(len(sections))
        moved = {s: f"6.{int(s.split('.')[1]) + 1}" for s in sections[start:]}
        for it in items:
            it["section"] = moved.get(it["section"], it["section"])
    counters: dict[str, int] = {}
    new: list[tuple[str, str]] = []
    for it in items:
        counters[it["section"]] = counters.get(it["section"], 0) + 1
        it["new"] = f"{it['section']}.{counters[it['section']]}"
        new.append((it["new"], it["text"]))
    truth["map"] = {it["old"]: it["new"] for it in items if it["old"] and "part" not in it}
    truth["parts"] = {}
    for it in items:
        if "part" in it:
            truth["parts"].setdefault(it["old"], []).append(it["new"])
    truth["added"] = [it["new"] for it in items if it["old"] is None]
    return new, truth


SEEDS = range(60)


def test_random_transformations_cover_every_kind_of_edit() -> None:
    base = [(c.number, c.text or "") for c in demo("2025-01-01", "en").clauses]
    seen = {"deleted": 0, "split": 0, "obligation": 0, "inserted": 0, "renumbered": 0}
    for seed in SEEDS:
        _, truth = transform(random.Random(seed), base)  # noqa: S311
        for key in ("deleted", "split", "obligation", "inserted"):
            seen[key] += bool(truth[key])
        seen["renumbered"] += any(old != new_ for old, new_ in truth["map"].items())
    assert all(count >= 10 for count in seen.values()), seen


@pytest.mark.parametrize("seed", SEEDS)
def test_random_transformations_are_recovered(seed: int) -> None:
    base_doc = demo("2025-01-01", "en")
    base = [(c.number, c.text or "") for c in base_doc.clauses]
    rng = random.Random(seed)  # noqa: S311 - deterministic test data
    new, truth = transform(rng, base)
    diff = diff_sources(make_doc(base, "2023-01-01"), make_doc(new))

    mapping = {p.old: p.new for p in diff.pairs if "split" not in p.flags}
    assert mapping == truth["map"], f"seed {seed}: {truth}"
    assert sorted(diff.removed) == sorted(truth["deleted"])
    assert diff.added == truth["added"]
    assert {s.old: s.into for s in diff.splits} == truth["parts"]
    flagged = sorted(p.old for p in diff.pairs if "obligation-change" in p.flags)
    assert flagged == sorted(truth["obligation"])
    for p in diff.pairs:
        assert ("renumbered" in p.flags) == (p.old != p.new)


# --- API -------------------------------------------------------------------------------


def _load_json(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DEMO / "sources" / name).read_text("utf-8"))
    return data


def test_diff_endpoint(client: TestClient) -> None:
    for version in ("2023-01-01", "2025-01-01"):
        for lang in ("en", "fr"):
            client.post("/sources", json=_load_json(f"example-widgets.{version}.{lang}.json"))
    params = {"from": "2023-01-01", "to": "2025-01-01"}
    both = client.get("/sources/example-widgets/diff", params=params).json()
    assert both["threshold"] == THRESHOLD
    assert both["split_threshold"] == 0.8
    assert "Hungarian" in both["method"]
    assert both["cross_check"] == []
    assert both["en"]["summary"]["splits"] == 1
    assert both["en"]["threshold"] == THRESHOLD
    one = client.post(
        "/sources/example-widgets/diff", params={**params, "lang": "fr", "include_text": False}
    ).json()
    assert "en" not in one and "cross_check" not in one
    assert one["fr"]["pairs"][0].get("old_text") is None
    assert (
        client.get(
            "/sources/example-widgets/diff", params={"from": "2023-01-01", "to": "2030-01-01"}
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    ("before", "after"),
    [
        ("Widgets must be calibrated every year.", "Widgets must not be calibrated every year."),
        ("Les widgets doivent être étalonnés.", "Les widgets ne doivent pas être étalonnés."),
    ],
)
def test_negation_only_change_is_an_obligation_change(before: str, after: str) -> None:
    old = make_doc([("6.1.1", before)], "2023-01-01")
    new = make_doc([("6.1.1", after)])
    lang = "fr" if "widgets doivent" in before.lower() else "en"
    old = old.model_copy(update={"lang": lang})
    new = new.model_copy(update={"lang": lang})
    (pair,) = diff_sources(old, new).pairs
    assert "obligation-change" in pair.flags
    assert pair.obligations_before != pair.obligations_after
