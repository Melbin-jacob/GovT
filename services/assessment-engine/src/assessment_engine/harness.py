"""Accuracy harness (proposal Appendix B), in English and French separately.

Runs labelled cases through the same steps as the engine (text extraction, passages,
injection flags, BM25 retrieval, rules or the model through the gateway) without a
database, so it runs anywhere the model server is reachable (CPU box or GPU VM).

Measures, per language:
- **verdict agreement**: final verdict equals the expected verdict (and, for judgment
  checks, the model's own verdict before the engine's safeguards);
- **calibration**: agreement of the model's own verdict per confidence band, for the
  token-probability and the self-reported confidence, plus expected calibration error;
- **injection resistance**: on cases with injected instructions, share where the final
  verdict did not follow the injection (did not become "met" against the label);
- **human ceiling**: agreement between the two human annotators where both labelled;
- **speed and footprint**: time per assessment (median, 95th percentile), tokens per
  second, and the hardware described by whoever ran it.

Scores are computed separately for **human-labelled** cases and for **synthetic-demo**
cases and never mixed; only human-labelled scores count for the release gate. Every
report carries the golden-set status ("DRAFT GOLDEN SET" until confirmed). Reports hold
scores only: never evidence text, quotes or model replies.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Final

from assessment_engine import rules
from assessment_engine.controls import ControlSource
from assessment_engine.engine import retrieval_query
from assessment_engine.extract import extract
from assessment_engine.judgment import ControlText, EvidencePassage, assess_judgment
from assessment_engine.passages import bm25, chunk, injection_flags, with_neighbours
from assessment_engine.settings_file import AssessmentConfig
from govhub_shared.model_gateway import ChatGateway

LABEL_SOURCES: Final = ("human", "synthetic-demo")
VERDICTS: Final = ("met", "partially-met", "not-met", "not-applicable", "unable-to-determine")
BANDS: Final = ((0.0, 0.5), (0.5, 0.7), (0.7, 0.85), (0.85, 1.0001))
COLUMNS: Final = (
    "case_id",
    "label_source",
    "language",
    "catalog",
    "catalog_version",
    "control_id",
    "evidence",
    "facts_json",
    "as_of",
    "expected_verdict",
    "expected_passage",
    "injection",
    "annotator",
    "second_annotator",
    "second_annotator_verdict",
    "notes",
)


class CaseError(ValueError):
    pass


@dataclass
class Case:
    case_id: str
    label_source: str
    language: str
    catalog: str
    catalog_version: str
    control_id: str
    evidence: list[Path]
    facts: dict[str, rules.Fact]
    as_of: date
    expected_verdict: str
    expected_passage: str
    injection: bool
    annotator: str
    second_verdict: str | None


def load_cases(path: Path) -> list[Case]:
    """Read a case CSV; evidence paths are relative to the CSV's folder."""
    cases = []
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise CaseError(f"{path}: missing columns {missing}")
        for n, row in enumerate(reader, start=2):
            where = f"{path.name} line {n} ({row.get('case_id')})"
            if row["label_source"] not in LABEL_SOURCES:
                raise CaseError(f"{where}: label_source must be one of {LABEL_SOURCES}")
            if row["language"] not in ("en", "fr"):
                raise CaseError(f"{where}: language must be en or fr")
            for col in ("expected_verdict", "second_annotator_verdict"):
                if row[col] and row[col] not in VERDICTS:
                    raise CaseError(f"{where}: {col} must be one of {VERDICTS}")
            if not row["expected_verdict"]:
                raise CaseError(f"{where}: expected_verdict is required")
            facts_raw = json.loads(row["facts_json"]) if row["facts_json"].strip() else {}
            files = [path.parent / p.strip() for p in row["evidence"].split(";") if p.strip()]
            for f in files:
                if not f.is_file():
                    raise CaseError(f"{where}: evidence file not found: {f}")
            cases.append(
                Case(
                    case_id=row["case_id"],
                    label_source=row["label_source"],
                    language=row["language"],
                    catalog=row["catalog"],
                    catalog_version=row["catalog_version"],
                    control_id=row["control_id"],
                    evidence=files,
                    facts={
                        k: rules.Fact(v.get("value"), str(v.get("source", "")))
                        if isinstance(v, dict)
                        else rules.Fact(v, "case")
                        for k, v in facts_raw.items()
                    },
                    as_of=date.fromisoformat(row["as_of"]),
                    expected_verdict=row["expected_verdict"],
                    expected_passage=row["expected_passage"],
                    injection=row["injection"].strip().lower() in ("yes", "true", "1"),
                    annotator=row["annotator"],
                    second_verdict=row["second_annotator_verdict"] or None,
                )
            )
    return cases


@dataclass
class CaseResult:
    case: Case
    method: str
    verdict: str
    model_verdict: str | None = None
    downgrade_reason: str | None = None
    token_confidence: float | None = None
    self_confidence: float | None = None
    latency: float = 0.0
    completion_tokens: int | None = None
    flagged: int = 0
    passage_ok: bool | None = None
    model_id: str | None = None


def _passages(files: Iterable[Path]) -> list[EvidencePassage]:
    out = []
    for f in files:
        extracted = extract(f.name, f.read_bytes())
        for i, text in enumerate(chunk(extracted.paragraphs), start=1):
            out.append(EvidencePassage(f"{f.name}:{i}", text, injection_flags(text)))
    return out


def run_case(
    case: Case,
    *,
    gateway: ChatGateway,
    source: ControlSource,
    rules_dir: Path,
    config: AssessmentConfig,
) -> CaseResult:
    by_lang = {}
    for lang in ("en", "fr"):
        try:
            by_lang[lang] = source.controls(case.catalog, case.catalog_version, lang)
        except LookupError:
            by_lang[lang] = {}
    controls = by_lang[case.language] or by_lang["en"]
    info = controls.get(case.control_id)
    if info is None:
        raise CaseError(f"{case.case_id}: control {case.control_id} not in {case.catalog}")
    if info.check_type.startswith("rule-based"):
        ruleset = rules.load_rules(rules_dir, case.catalog)
        outcome = rules.assess_rule(ruleset, case.control_id, case.facts, case.as_of)
        return CaseResult(case, "rule", outcome.verdict)
    passages = _passages(case.evidence)
    query = retrieval_query(by_lang, case.control_id)
    ranked = bm25(query, [p.text for p in passages])
    hits = [s.index for s in ranked[: config.passages] if s.score > 0]
    keys = [(p.id.rsplit(":", 1)[0], int(p.id.rsplit(":", 1)[1])) for p in passages]
    chosen = [passages[i] for i in with_neighbours(hits, keys, config.passages)]
    judged = assess_judgment(
        gateway,
        ControlText(case.control_id, info.statement, info.objective),
        chosen,
        case.language,
        config,
    )
    latency = judged.latency_seconds  # 0 for recorded replies: speed is then n/a
    passage_ok = None
    if case.expected_passage and judged.cited_quote:
        from govhub_shared.text import normalize_for_match as norm

        passage_ok = norm(case.expected_passage)[:40] in norm(
            next((p.text for p in chosen if p.id == judged.cited_passage_id), "")
        )
    return CaseResult(
        case,
        "model",
        judged.verdict,
        model_verdict=judged.model_verdict,
        downgrade_reason=judged.downgrade_reason,
        token_confidence=judged.token_confidence,
        self_confidence=judged.self_confidence,
        latency=latency,
        completion_tokens=judged.completion_tokens,
        flagged=len(judged.flagged_passage_ids),
        passage_ok=passage_ok,
        model_id=judged.model_id,
    )


def _rate(hits: int, n: int) -> float | None:
    return round(hits / n, 4) if n else None


def calibration(results: list[CaseResult], attr: str) -> dict[str, Any]:
    bands: list[dict[str, Any]] = []
    total, ece = 0, 0.0
    for low, high in BANDS:
        inside = [
            r
            for r in results
            if (c := getattr(r, attr)) is not None and low <= c < high and r.model_verdict
        ]
        if not inside:
            bands.append({"band": f"{low:.2f}-{min(high, 1.0):.2f}", "n": 0})
            continue
        agree = sum(r.model_verdict == r.case.expected_verdict for r in inside)
        mean_conf = statistics.fmean(float(getattr(r, attr)) for r in inside)
        bands.append(
            {
                "band": f"{low:.2f}-{min(high, 1.0):.2f}",
                "n": len(inside),
                "agreement": round(agree / len(inside), 4),
                "mean_confidence": round(mean_conf, 4),
            }
        )
        total += len(inside)
        ece += len(inside) * abs(agree / len(inside) - mean_conf)
    return {"bands": bands, "ece": round(ece / total, 4) if total else None, "n": total}


def measures(results: list[CaseResult]) -> dict[str, Any]:
    judged = [r for r in results if r.method == "model"]
    ruled = [r for r in results if r.method == "rule"]
    injected = [r for r in results if r.case.injection]
    followed = [r for r in injected if r.verdict == "met" and r.case.expected_verdict != "met"]
    model_followed = [
        r for r in injected if r.model_verdict == "met" and r.case.expected_verdict != "met"
    ]
    pairs = [r for r in results if r.case.second_verdict]
    latencies = sorted(r.latency for r in judged if r.latency)
    rates = [r.completion_tokens / r.latency for r in judged if r.completion_tokens and r.latency]
    return {
        "cases": len(results),
        "verdict_agreement": _rate(
            sum(r.verdict == r.case.expected_verdict for r in results), len(results)
        ),
        "judgment": {
            "cases": len(judged),
            "final_agreement": _rate(
                sum(r.verdict == r.case.expected_verdict for r in judged), len(judged)
            ),
            "model_agreement": _rate(
                sum(r.model_verdict == r.case.expected_verdict for r in judged), len(judged)
            ),
            "unable_to_determine_rate": _rate(
                sum(r.verdict == "unable-to-determine" for r in judged), len(judged)
            ),
            "cited_expected_passage": _rate(
                sum(bool(r.passage_ok) for r in judged if r.passage_ok is not None),
                sum(1 for r in judged if r.passage_ok is not None),
            ),
            "downgrades": dict(sorted(_count(r.downgrade_reason for r in judged).items())),
        },
        "rule": {
            "cases": len(ruled),
            "agreement": _rate(
                sum(r.verdict == r.case.expected_verdict for r in ruled), len(ruled)
            ),
        },
        "calibration": {
            "token": calibration(judged, "token_confidence"),
            "self_reported": calibration(judged, "self_confidence"),
        },
        "injection": {
            "cases": len(injected),
            "resistance": _rate(len(injected) - len(followed), len(injected)),
            "model_followed_injection": len(model_followed),
            "engine_blocked": len(model_followed) - len(followed),
        },
        "human_ceiling": {
            "pairs": len(pairs),
            "agreement": _rate(
                sum(r.case.second_verdict == r.case.expected_verdict for r in pairs), len(pairs)
            ),
        },
        "speed": {
            "assessments": len(latencies),
            "median_seconds": round(statistics.median(latencies), 3) if latencies else None,
            "p95_seconds": round(latencies[max(0, int(len(latencies) * 0.95) - 1)], 3)
            if latencies
            else None,
            "tokens_per_second": round(statistics.median(rates), 2) if rates else None,
        },
    }


def _count(items: Iterable[str | None]) -> dict[str, int]:
    out: dict[str, int] = defaultdict(int)
    for item in items:
        if item:
            out[item] += 1
    return dict(out)


@dataclass
class RunInfo:
    model_id: str
    prompt_version: str
    gateway: str
    hardware: str
    golden_set_status: str
    cases_file: str
    cases_sha256: str
    started: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


def report(results: list[CaseResult], info: RunInfo) -> dict[str, Any]:
    """Scores per label source and language; never mixed; scores only."""
    out: dict[str, Any] = {
        "format": "govhub-accuracy-run/1",
        "golden_set_status": info.golden_set_status,
        "run": info.__dict__,
        "scores": {},
    }
    for source in LABEL_SOURCES:
        by_lang: dict[str, Any] = {}
        for lang in ("en", "fr"):
            subset = [
                r for r in results if r.case.label_source == source and r.case.language == lang
            ]
            if subset:
                by_lang[lang] = measures(subset)
        out["scores"][source] = by_lang or None
    out["cases"] = [
        {
            "case_id": r.case.case_id,
            "label_source": r.case.label_source,
            "language": r.case.language,
            "control_id": r.case.control_id,
            "method": r.method,
            "expected": r.case.expected_verdict,
            "verdict": r.verdict,
            "model_verdict": r.model_verdict,
            "downgrade_reason": r.downgrade_reason,
            "injection": r.case.injection,
            "flagged_passages": r.flagged,
        }
        for r in results
    ]
    return out


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def markdown(run: dict[str, Any]) -> str:
    """Human-readable summary (scores only)."""
    info = run["run"]
    lines = [
        f"# Accuracy run: {info['model_id']} / {info['prompt_version']}",
        "",
        f"**{run['golden_set_status']}**. Gateway: {info['gateway']}. "
        f"Hardware: {info['hardware']}. Started {info['started']}.",
        f"Cases: `{info['cases_file']}` (sha256 {info['cases_sha256'][:12]}).",
        "",
    ]
    for source, by_lang in run["scores"].items():
        title = {
            "human": "Human-labelled cases (these scores count)",
            "synthetic-demo": "Synthetic demo cases (pipeline check only, NOT accuracy)",
        }[source]
        lines += [f"## {title}", ""]
        if not by_lang:
            lines += ["No cases.", ""]
            continue
        lines += [
            "| Measure | EN | FR |",
            "|---|---|---|",
        ]

        def row(label: str, get: Any, by_lang: dict[str, Any] = by_lang) -> str:
            cells = []
            for lang in ("en", "fr"):
                m = by_lang.get(lang)
                cells.append("n/a" if m is None else str(get(m)))
            return f"| {label} | {cells[0]} | {cells[1]} |"

        lines += [
            row("Cases", lambda m: m["cases"]),
            row("Verdict agreement (final)", lambda m: _pct(m["verdict_agreement"])),
            row("Judgment: final agreement", lambda m: _pct(m["judgment"]["final_agreement"])),
            row(
                "Judgment: model's own agreement", lambda m: _pct(m["judgment"]["model_agreement"])
            ),
            row(
                "Judgment: unable to determine",
                lambda m: _pct(m["judgment"]["unable_to_determine_rate"]),
            ),
            row(
                "Judgment: cited the expected passage",
                lambda m: _pct(m["judgment"]["cited_expected_passage"]),
            ),
            row("Rule-based agreement", lambda m: _pct(m["rule"]["agreement"])),
            row("Calibration error (token)", lambda m: m["calibration"]["token"]["ece"]),
            row(
                "Calibration error (self-reported)",
                lambda m: m["calibration"]["self_reported"]["ece"],
            ),
            row("Injection cases", lambda m: m["injection"]["cases"]),
            row("Injection resistance (final)", lambda m: _pct(m["injection"]["resistance"])),
            row(
                "Model followed an injection", lambda m: m["injection"]["model_followed_injection"]
            ),
            row("Blocked by the engine", lambda m: m["injection"]["engine_blocked"]),
            row("Human ceiling (2 annotators)", lambda m: _pct(m["human_ceiling"]["agreement"])),
            row("Median seconds per assessment", lambda m: m["speed"]["median_seconds"]),
            row("95th percentile seconds", lambda m: m["speed"]["p95_seconds"]),
            row("Tokens per second", lambda m: m["speed"]["tokens_per_second"]),
            "",
        ]
        for lang, m in by_lang.items():
            bands = m["calibration"]["self_reported"]["bands"]
            cells = ", ".join(
                f"{b['band']}: {b['n']} case(s)"
                + (f", {_pct(b['agreement'])} agree" if b["n"] else "")
                for b in bands
            )
            lines.append(f"- Calibration bands ({lang.upper()}, self-reported): {cells}")
        lines.append("")
    lines += [
        "## Cases",
        "",
        "| Case | Lang | Control | Method | Expected | Model | Final | Downgrade |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for c in run["cases"]:
        lines.append(
            f"| {c['case_id']}{' (injection)' if c['injection'] else ''} | {c['language']} | "
            f"{c['control_id']} | {c['method']} | {c['expected']} | {c['model_verdict'] or '-'} "
            f"| {c['verdict']} | {c['downgrade_reason'] or '-'} |"
        )
    return "\n".join(lines) + "\n"
