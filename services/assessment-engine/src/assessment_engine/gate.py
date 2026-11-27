"""Release gate: a new model or prompt fails if any measure falls below the baseline in
either language (proposal Appendix B). Only human-labelled scores are gated in a release;
the synthetic demo scores are gated in CI to protect the engine's safeguards.

The baseline file keeps every previous baseline (history), e.g. the DRAFT GOLDEN SET
baseline and, later, the confirmed-golden-set one (project owner's decision).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

# (path in the language scores, True if higher is better)
MEASURES: Final[tuple[tuple[str, bool], ...]] = (
    ("verdict_agreement", True),
    ("judgment.final_agreement", True),
    ("judgment.model_agreement", True),
    ("judgment.cited_expected_passage", True),
    ("rule.agreement", True),
    ("injection.resistance", True),
    ("calibration.token.ece", False),
    ("calibration.self_reported.ece", False),
)
TOLERANCE: Final = 1e-9


def _get(scores: dict[str, Any], path: str) -> float | None:
    value: Any = scores
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return None if value is None else float(value)


def baseline_from(run: dict[str, Any], source: str) -> dict[str, Any]:
    scores = run["scores"].get(source)
    if not scores:
        raise ValueError(f"the run has no {source} scores to use as a baseline")
    return {
        "label_source": source,
        "golden_set_status": run["golden_set_status"],
        "run": run["run"],
        "set_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "measures": {
            lang: {path: _get(by_lang, path) for path, _ in MEASURES}
            for lang, by_lang in scores.items()
        },
    }


def new_baseline_file(current: dict[str, Any] | None, baseline: dict[str, Any]) -> dict[str, Any]:
    history = list((current or {}).get("history", []))
    if current and current.get("current"):
        history.append(current["current"])
    return {"format": "govhub-accuracy-baseline/1", "current": baseline, "history": history}


def check(run: dict[str, Any], baseline_file: dict[str, Any] | None, source: str) -> dict[str, Any]:
    """Compare the run with the current baseline. Missing baseline: passes, says so."""
    base = (baseline_file or {}).get("current")
    if not base:
        return {
            "passed": True,
            "baseline": None,
            "failures": [],
            "checked": 0,
            "note": "no baseline yet: set one from a run on real hardware",
        }
    if base["label_source"] != source:
        raise ValueError(f"baseline is for {base['label_source']} scores, not {source}")
    scores = run["scores"].get(source) or {}
    failures, checked = [], 0
    for lang, measures in base["measures"].items():
        current = scores.get(lang)
        if current is None:
            failures.append(f"{lang}: no {source} cases in this run")
            continue
        for path, higher in MEASURES:
            was, now = measures.get(path), _get(current, path)
            if was is None:
                continue
            checked += 1
            if now is None:
                failures.append(f"{lang} {path}: missing (baseline {was})")
            elif (now < was - TOLERANCE) if higher else (now > was + TOLERANCE):
                failures.append(f"{lang} {path}: {now} vs baseline {was}")
    return {
        "passed": not failures,
        "baseline": {k: base[k] for k in ("golden_set_status", "set_at", "run")},
        "failures": failures,
        "checked": checked,
        "golden_set_status": run["golden_set_status"],
    }
