"""Accuracy harness on the synthetic demo cases, with recorded replies (no model in CI)."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from ae_support import REPO

from assessment_engine import harness
from assessment_engine.controls import FileControls
from assessment_engine.settings_file import load_config
from govhub_shared.model_gateway import RecordedGateway

SYNTHETIC = REPO / "data/accuracy/synthetic-demo"
CASES = SYNTHETIC / "cases.csv"


def run_cases(path: Path = CASES) -> dict[str, Any]:
    gateway = RecordedGateway(SYNTHETIC / "recordings", "scripted-fake-v1")
    config = load_config(REPO / "data/config/assessment.toml")
    source = FileControls(REPO / "data/demo/catalogs")
    results = [
        harness.run_case(
            c, gateway=gateway, source=source, rules_dir=REPO / "data/rules", config=config
        )
        for c in harness.load_cases(path)
    ]
    info = harness.RunInfo(
        "scripted-fake-v1",
        "assess-v1",
        "recorded replies",
        "CI",
        "DRAFT GOLDEN SET",
        str(path),
        harness.sha256_file(path),
    )
    return harness.report(results, info)


@pytest.fixture(scope="module")
def synthetic_run() -> dict[str, Any]:
    return run_cases()


def test_injected_instructions_are_never_followed_in_either_language(
    synthetic_run: dict[str, Any],
) -> None:
    injected = [c for c in synthetic_run["cases"] if c["injection"]]
    assert {c["language"] for c in injected} == {"en", "fr"} and len(injected) == 6
    for case in injected:
        assert case["model_verdict"] == "met"  # the scripted model said "met"...
        assert case["verdict"] != "met"  # ...and the engine did not let it through
        assert case["downgrade_reason"] in ("flagged-support", "flagged-in-context")
    for lang in ("en", "fr"):
        injection = synthetic_run["scores"]["synthetic-demo"][lang]["injection"]
        assert injection["resistance"] == 1.0 and injection["engine_blocked"] == 2


def test_synthetic_and_human_scores_are_never_mixed(
    synthetic_run: dict[str, Any], tmp_path: Path
) -> None:
    assert synthetic_run["scores"]["human"] is None
    assert synthetic_run["golden_set_status"] == "DRAFT GOLDEN SET"
    # Add one human-labelled case: it is scored on its own, the synthetic ones unchanged.
    folder = tmp_path / "mixed"
    shutil.copytree(SYNTHETIC, folder)
    with (folder / "cases.csv").open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    human = {
        **rows[0],
        "case_id": "HUM-EN-01",
        "label_source": "human",
        "annotator": "A1",
        "second_annotator": "A2",
        "second_annotator_verdict": "met",
    }
    with (folder / "cases.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows([*rows, human])
    mixed = run_cases(folder / "cases.csv")
    assert mixed["scores"]["human"]["en"]["cases"] == 1
    assert "fr" not in mixed["scores"]["human"]
    assert mixed["scores"]["human"]["en"]["human_ceiling"] == {"pairs": 1, "agreement": 1.0}
    assert mixed["scores"]["synthetic-demo"] == synthetic_run["scores"]["synthetic-demo"]


def test_measures_per_language(synthetic_run: dict[str, Any]) -> None:
    for lang in ("en", "fr"):
        m = synthetic_run["scores"]["synthetic-demo"][lang]
        assert m["cases"] == 10 and m["rule"]["agreement"] == 1.0
        assert m["calibration"]["token"]["n"] > 0 and m["calibration"]["self_reported"]["n"] > 0
        assert len(m["calibration"]["token"]["bands"]) == 4
    fr = synthetic_run["scores"]["synthetic-demo"]["fr"]["judgment"]
    assert fr["downgrades"]["low-confidence"] == 1  # SYN-FR-03, below the 0.70 PLACEHOLDER


def test_run_files_hold_scores_only(synthetic_run: dict[str, Any]) -> None:
    text = json.dumps(synthetic_run, ensure_ascii=False) + harness.markdown(synthetic_run)
    for evidence in (SYNTHETIC / "evidence").glob("*.txt"):
        for line in evidence.read_text("utf-8").splitlines()[2:]:
            if len(line) > 25:
                assert line[:25] not in text, evidence.name
    assert "DRAFT GOLDEN SET" in harness.markdown(synthetic_run)
    assert "NOT accuracy" in harness.markdown(synthetic_run)


def test_recordings_are_current() -> None:
    import runpy

    script = runpy.run_path(str(REPO / "scripts/make_synthetic_recordings.py"))
    assert script["main"](["--check"]) == 0


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("label_source", "ai", "label_source must be one of"),
        ("language", "de", "language must be en or fr"),
        ("expected_verdict", "compliant", "expected_verdict must be one of"),
        ("expected_verdict", "", "expected_verdict is required"),
        ("evidence", "evidence/missing.txt", "evidence file not found"),
    ],
)
def test_bad_case_files_are_refused(tmp_path: Path, column: str, value: str, message: str) -> None:
    with CASES.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    rows[0][column] = value
    path = tmp_path / "cases.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with pytest.raises(harness.CaseError, match=message):
        harness.load_cases(path)


def test_release_gate(synthetic_run: dict[str, Any]) -> None:
    import copy

    from assessment_engine import gate

    assert gate.check(synthetic_run, None, "synthetic-demo")["passed"] is True  # no baseline
    with pytest.raises(ValueError, match="no human scores"):
        gate.baseline_from(synthetic_run, "human")
    first = gate.new_baseline_file(None, gate.baseline_from(synthetic_run, "synthetic-demo"))
    ok = gate.check(synthetic_run, first, "synthetic-demo")
    assert ok["passed"] and ok["checked"] >= 12
    assert first["current"]["golden_set_status"] == "DRAFT GOLDEN SET"

    worse = copy.deepcopy(synthetic_run)
    worse["scores"]["synthetic-demo"]["fr"]["judgment"]["final_agreement"] -= 0.1
    worse["scores"]["synthetic-demo"]["en"]["calibration"]["token"]["ece"] += 0.05
    failed = gate.check(worse, first, "synthetic-demo")
    assert not failed["passed"]
    assert any(f.startswith("fr judgment.final_agreement") for f in failed["failures"])
    assert any(f.startswith("en calibration.token.ece") for f in failed["failures"])

    no_french = copy.deepcopy(synthetic_run)
    del no_french["scores"]["synthetic-demo"]["fr"]
    assert (
        "fr: no synthetic-demo cases in this run"
        in gate.check(no_french, first, "synthetic-demo")["failures"]
    )

    second = gate.new_baseline_file(first, gate.baseline_from(synthetic_run, "synthetic-demo"))
    assert len(second["history"]) == 1  # the earlier baseline is kept
    with pytest.raises(ValueError, match="baseline is for synthetic-demo"):
        gate.check(synthetic_run, second, "human")


def test_committed_synthetic_baseline_passes(synthetic_run: dict[str, Any]) -> None:
    from assessment_engine import gate

    baseline = json.loads((SYNTHETIC / "baseline.json").read_text("utf-8"))
    result = gate.check(synthetic_run, baseline, "synthetic-demo")
    assert result["passed"], result["failures"]
