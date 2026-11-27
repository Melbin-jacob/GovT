"""Drafting accuracy harness: requirement recall, draft precision, obligation accuracy."""

from __future__ import annotations

import copy
import csv
import json
import re
from pathlib import Path
from typing import Any

import pytest
from ae_support import REPO

from assessment_engine import draft_harness, gate, harness
from assessment_engine.settings_file import load_config
from govhub_shared.model_gateway import ChatRequest, ChatResponse, RecordedGateway

DRAFTING = REPO / "data/accuracy/synthetic-demo/drafting"
CASES = DRAFTING / "cases.csv"


def batches() -> dict[str, dict[str, Any]]:
    return {p.stem: draft_harness.load_batch(p) for p in (DRAFTING / "batches").glob("*.json")}


def run_cases(path: Path = CASES, gateway: Any = None) -> dict[str, Any]:
    gateway = gateway or RecordedGateway(
        REPO / "data/accuracy/synthetic-demo/recordings", "scripted-fake-v1"
    )
    config = load_config(REPO / "data/config/assessment.toml")
    cases = draft_harness.load_cases(path)
    proposals = draft_harness.run(cases, batches(), gateway, config)
    info = harness.RunInfo(
        "scripted-fake-v1", "draft-v1", "recorded replies", "CI", "DRAFT GOLDEN SET",
        str(path), harness.sha256_file(path),
    )  # fmt: skip
    return draft_harness.report(cases, proposals, info)


@pytest.fixture(scope="module")
def synthetic_run() -> dict[str, Any]:
    return run_cases()


def test_measures_per_language(synthetic_run: dict[str, Any]) -> None:
    en, fr = (
        synthetic_run["scores"]["synthetic-demo"]["en"],
        synthetic_run["scores"]["synthetic-demo"]["fr"],
    )
    assert synthetic_run["scores"]["human"] is None
    # EN: WID-6.3.1 answered "no change" for a split clause: one recall and one precision miss
    assert (en["expected"], en["proposals"], en["matched"]) == (10, 10, 9)
    assert en["requirement_recall"] == 0.9 and en["draft_precision"] == 0.9
    assert en["missed"] == ["DRF-EN-07"]
    # EN: "should" drafted for a "must" clause (WID-6.1.2): 3 of 4 obligations right
    assert (en["obligation_accuracy"], en["obligation_cases"]) == (0.75, 4)
    assert en["obligation_mismatch_flags"] == 2  # WID-6.1.2 and WID-6.4.2 (no word)
    # FR: WID-6.4.2 below the confidence threshold: needs a person, not a proposal
    assert (fr["expected"], fr["proposals"], fr["matched"]) == (10, 9, 9)
    assert fr["requirement_recall"] == 0.9 and fr["draft_precision"] == 1.0
    assert fr["needs_human_reasons"] == {"low-confidence": 1}
    assert fr["obligation_accuracy"] == 1.0
    assert 0 < en["wording_similarity"] < 1 and 0 < fr["wording_similarity"] < 1


def test_no_change_is_a_labelable_outcome_and_counts_as_a_hit(
    synthetic_run: dict[str, Any],
) -> None:
    for lang in ("en", "fr"):
        missed = synthetic_run["scores"]["synthetic-demo"][lang]["missed"]
        assert f"DRF-{lang.upper()}-02" not in missed  # WID-6.2.1: should -> must, no new wording
    actions = {(p["lang"], p["target"]): p["action"] for p in synthetic_run["proposals"]
               if p["batch"] == "example-widgets-2023-2025"}  # fmt: skip
    assert actions[("en", "WID-6.2.1")] == "no-change"


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_injected_instructions_are_blocked_before_the_model(
    synthetic_run: dict[str, Any], lang: str
) -> None:
    inj = synthetic_run["scores"]["synthetic-demo"][lang]["injection"]
    assert inj == {
        "cases": 2, "resistance": 1.0, "blocked_before_model": 2, "stopped_by_safeguards": 0,
        "followed": 0,
    }  # fmt: skip
    flagged = [
        p for p in synthetic_run["proposals"] if p["batch"] == "injection" and p["lang"] == lang
    ]
    assert [p["reason"] for p in flagged] == ["instruction-like-text"] * 2


class Obedient:
    """A model that sees the clause and does what an unflagged instruction says."""

    def chat(self, request: ChatRequest) -> ChatResponse:
        found = re.search(r"id=NEW-[^>]*>>>\n(.*?)\n<<<END", request.messages[-1].content, re.S)
        clause = found.group(1) if found else ""
        reply = {"no_change": True, "statement": "x", "guidance": None, "objective": None,
                 "check_type": "rule-based", "obligation": "may", "cited_clause": clause,
                 "reasoning": "", "confidence": 0.99}  # fmt: skip
        return ChatResponse(content=json.dumps(reply), model_id="obedient")


def test_an_injection_the_patterns_miss_is_counted_as_followed(tmp_path: Path) -> None:
    """If a tampered clause gets past the patterns and the model obeys, the score drops."""
    folder = tmp_path / "batches"
    folder.mkdir()
    batch = copy.deepcopy(batches()["injection"])
    for lang in ("en", "fr"):
        for n in batch["plan"]["clauses"][lang]["new"]:
            text = batch["plan"]["clauses"][lang]["new"][n]
            batch["plan"]["clauses"][lang]["new"][n] = text.split(".")[0] + "."  # untampered
    (folder / "injection.json").write_text(json.dumps(batch), "utf-8")
    rows = [r for r in _rows() if r["batch"] == "injection"]
    path = _write(tmp_path / "cases.csv", rows)
    config = load_config(REPO / "data/config/assessment.toml")
    cases = draft_harness.load_cases(path)
    proposals = draft_harness.run(
        cases,
        {"injection": draft_harness.load_batch(folder / "injection.json")},
        Obedient(),
        config,
    )
    info = harness.RunInfo(
        "obedient", "draft-v1", "test", "CI", "DRAFT GOLDEN SET", str(path), "0" * 64
    )
    scores = draft_harness.report(cases, proposals, info)["scores"]["synthetic-demo"]["en"]
    # the edit draft obeys ("no change", obligation "may"); the new control's "no change"
    # is stopped by a later safeguard (no-change-for-new-clause)
    assert scores["injection"] == {
        "cases": 2, "resistance": 0.5, "blocked_before_model": 0, "stopped_by_safeguards": 1,
        "followed": 1,
    }  # fmt: skip


def test_new_controls_match_one_to_one_by_wording() -> None:
    """Two new controls on the same clauses: the Hungarian assignment pairs them by wording."""

    def case(cid: str, text: str) -> draft_harness.DraftCase:
        return draft_harness.DraftCase(cid, "human", "en", "b", "new", None, ("7.1",), text,
                                       "must", "judgment", False)  # fmt: skip

    def prop(item: str, text: str) -> draft_harness.Proposal:
        return draft_harness.Proposal("b", "en", item, "new", "new", None, ("7.1",), text)

    expected = [case("A", "Widgets are labelled with their owner."),
                case("B", "Labels are checked every year by an inspector.")]  # fmt: skip
    proposals = [prop("p1", "An inspector checks the labels each year."),
                 prop("p2", "Each widget is labelled with its owner.")]  # fmt: skip
    pairs = {c.case_id: p.item for c, p, _ in draft_harness.match(expected, proposals)}
    assert pairs == {"A": "p2", "B": "p1"}


def test_matching_needs_action_clause_and_target() -> None:
    expected = [draft_harness.DraftCase("A", "human", "en", "b", "edit", "X-1", ("6.1",),
                                        None, None, None, False)]  # fmt: skip
    wrong = [
        draft_harness.Proposal("b", "en", "1", "edit", "no-change", "X-1", ("6.1",)),
        draft_harness.Proposal("b", "en", "2", "edit", "edit", "X-2", ("6.1",)),
        draft_harness.Proposal("b", "en", "3", "edit", "edit", "X-1", ("6.2",)),
        draft_harness.Proposal("b", "en", "4", "edit", None, "X-1", ("6.1",)),  # needs a person
    ]
    assert draft_harness.match(expected, wrong) == []
    right = draft_harness.Proposal("b", "en", "5", "edit", "edit", "X-1", ("6.1",))
    assert [p.item for _, p, _ in draft_harness.match(expected, [*wrong, right])] == ["5"]


def test_run_files_hold_scores_only(synthetic_run: dict[str, Any]) -> None:
    text = json.dumps(synthetic_run, ensure_ascii=False) + draft_harness.markdown(synthetic_run)
    for batch in batches().values():
        for lang in ("en", "fr"):
            for side in ("old", "new"):
                for clause in batch["plan"]["clauses"][lang][side].values():
                    assert clause[:30] not in text
    for row in _rows():
        if row["expected_statement"]:
            assert row["expected_statement"][:30] not in text
    markdown = draft_harness.markdown(synthetic_run)
    assert "DRAFT GOLDEN SET" in markdown and "NOT accuracy" in markdown


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("label_source", "model", "label_source must be one of"),
        ("action", "rewrite", "action must be one of"),
        ("expected_obligation", "shall", "expected_obligation must be one of"),
        ("target_control", "", "every other action needs one"),
        ("clauses", "", "clauses is empty"),
    ],
)
def test_bad_case_files_are_refused(tmp_path: Path, column: str, value: str, message: str) -> None:
    rows = _rows()
    rows[0][column] = value
    with pytest.raises(draft_harness.DraftCaseError, match=message):
        draft_harness.load_cases(_write(tmp_path / "cases.csv", rows))


def test_annotator_template_has_the_columns() -> None:
    with (REPO / "data/accuracy/template/drafting-cases.csv").open(encoding="utf-8") as fh:
        assert tuple(csv.DictReader(fh).fieldnames or ()) == draft_harness.COLUMNS


def test_drafting_release_gate(synthetic_run: dict[str, Any]) -> None:
    baseline = json.loads((DRAFTING / "baseline.json").read_text("utf-8"))
    assert gate.check(synthetic_run, baseline, "synthetic-demo")["passed"]
    worse = copy.deepcopy(synthetic_run)
    worse["scores"]["synthetic-demo"]["fr"]["obligation_accuracy"] = 0.8
    result = gate.check(worse, baseline, "synthetic-demo")
    assert not result["passed"] and result["failures"] == [
        "fr obligation_accuracy: 0.8 vs baseline 1.0"
    ]
    better_wording = copy.deepcopy(synthetic_run)
    better_wording["scores"]["synthetic-demo"]["en"]["wording_similarity"] = 0.1  # not gated
    assert gate.check(better_wording, baseline, "synthetic-demo")["passed"]
    assessment = {**baseline, "current": {**baseline["current"], "kind": "assessment"}}
    with pytest.raises(ValueError, match="baseline is for assessment runs"):
        gate.check(synthetic_run, assessment, "synthetic-demo")


def _rows() -> list[dict[str, str]]:
    with CASES.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _write(path: Path, rows: list[dict[str, str]]) -> Path:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path
