"""Drafting accuracy harness: requirement recall, draft precision, obligation accuracy.

Input: planned drafting batches (the rulebook's planner output, exported without IDs:
``govhub-drafting-batch/1``) and a CSV of **expected outcomes** labelled by people (or
synthetic ones for the pipeline check; see ``docs/accuracy-cases.md``). The engine drafts
every edit/new item in each language with its real safeguards (``drafting.draft_item``),
as in production but with no database; clause-reference updates and retirements come from
plain code and are taken from the plan as they are.

**What the system proposed** (per language): one action per item: ``reference``,
``retire``, ``new``, ``edit``, or ``no-change`` (an edit item the model answered "no
change" for). A draft that needs a person (needs-human) is not a proposal.

**Matching** (plain code): an expected outcome and a proposal match when action, clauses
and target control are equal (a labelled "no change needed" is an outcome like any other;
a match counts as a hit). New controls have no target: they are matched on action and
clauses, then one-to-one by wording similarity with the Hungarian assignment of the
clause diff (``govhub_shared.matching``).

Measures per language and label source (never mixed):
- requirement recall = matched expected outcomes / expected outcomes;
- draft precision = matched proposals / proposals;
- obligation accuracy = matched pairs whose drafted obligation equals the expected one
  (pairs with an expected obligation only);
- wording similarity (reported separately, not gated): mean similarity of matched
  edit/new pairs' statements, over normalized word tokens;
- needs-human rate; injection resistance (injection cases: the injected instruction must
  not shape the draft; blocked before the model or stopped by a later safeguard counts as
  resisted).

Run files hold identifiers, codes and scores only: never clause text, drafts or replies.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from assessment_engine import drafting
from assessment_engine.harness import RunInfo
from assessment_engine.rulebook_drafts import inputs_for
from assessment_engine.settings_file import AssessmentConfig
from govhub_shared.matching import hungarian_max, similarity
from govhub_shared.model_gateway import ChatGateway
from govhub_shared.obligations import OBLIGATION_CODES
from govhub_shared.text import match_tokens

LABEL_SOURCES: Final = ("human", "synthetic-demo")
ACTIONS: Final = ("edit", "new", "retire", "reference", "no-change")
LANGS: Final = ("en", "fr")
COLUMNS: Final = (
    "case_id", "label_source", "language", "batch", "action", "target_control", "clauses",
    "expected_statement", "expected_obligation", "expected_check_type", "injection",
    "annotator", "notes",
)  # fmt: skip


class DraftCaseError(ValueError):
    pass


@dataclass(frozen=True)
class DraftCase:
    case_id: str
    label_source: str
    language: str
    batch: str
    action: str
    target: str | None
    clauses: tuple[str, ...]
    statement: str | None
    obligation: str | None
    check_type: str | None
    injection: bool


@dataclass
class Proposal:
    batch: str
    lang: str
    item: str
    kind: str
    action: str | None  # None: needs a person (not a proposal)
    target: str | None
    clauses: tuple[str, ...]
    statement: str | None = None
    obligation: str | None = None
    check_type: str | None = None
    source: str = "plain code"  # or "model"
    model_id: str | None = None
    status: str = "plain-code"  # drafted | needs-human | plain-code
    reason: str | None = None
    flags: list[str] = field(default_factory=list)
    instruction_like: bool = False
    latency_seconds: float = 0.0
    completion_tokens: int | None = None


def load_cases(path: Path) -> list[DraftCase]:
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise DraftCaseError(f"{path}: missing columns {missing}")
        rows = list(reader)
    cases, seen = [], set()
    for n, row in enumerate(rows, start=2):

        def bad(message: str, n: int = n) -> DraftCaseError:
            return DraftCaseError(f"{path}:{n}: {message}")

        cid = row["case_id"].strip()
        if not cid or cid in seen:
            raise bad(f"case_id {cid!r} is empty or repeated")
        seen.add(cid)
        source, lang, action = row["label_source"], row["language"], row["action"]
        if source not in LABEL_SOURCES:
            raise bad(f"label_source must be one of {LABEL_SOURCES}")
        if lang not in LANGS:
            raise bad("language must be en or fr")
        if action not in ACTIONS:
            raise bad(f"action must be one of {ACTIONS}")
        target = row["target_control"].strip() or None
        if (action == "new") == (target is not None):
            raise bad("a new control has no target_control; every other action needs one")
        obligation = row["expected_obligation"].strip() or None
        if obligation is not None and obligation not in OBLIGATION_CODES:
            raise bad(f"expected_obligation must be one of {list(OBLIGATION_CODES)} or blank")
        check_type = row["expected_check_type"].strip() or None
        if check_type not in (None, "rule-based", "judgment"):
            raise bad("expected_check_type must be rule-based, judgment or blank")
        clauses = tuple(c.strip() for c in row["clauses"].split(";") if c.strip())
        if not clauses:
            raise bad("clauses is empty")
        if row["injection"] not in ("yes", "no"):
            raise bad("injection must be yes or no")
        cases.append(
            DraftCase(
                case_id=cid, label_source=source, language=lang, batch=row["batch"].strip(),
                action=action, target=target, clauses=clauses,
                statement=row["expected_statement"].strip() or None, obligation=obligation,
                check_type=check_type, injection=row["injection"] == "yes",
            )
        )  # fmt: skip
    return cases


def load_batch(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text("utf-8"))
    if data.get("format") != "govhub-drafting-batch/1":
        raise DraftCaseError(f"{path}: not a govhub-drafting-batch/1 file")
    return data


def draft_batch(
    name: str, batch: dict[str, Any], gateway: ChatGateway, config: AssessmentConfig
) -> list[Proposal]:
    """Every item of a planned batch, in both languages, through the engine's own steps."""
    out = []
    for item in batch["items"]:
        kind = item["kind"]
        for lang in LANGS:
            clauses = tuple(item["old_clauses"] if kind == "retire" else item["new_clauses"])
            base = Proposal(
                batch=name, lang=lang, item=item["id"], kind=kind, action=kind,
                target=item["target_control"], clauses=clauses,
            )  # fmt: skip
            if kind in ("edit", "new"):
                result = drafting.draft_item(gateway, inputs_for(batch, item, lang), config)
                d = result.draft
                no_change = bool(d.get("no_change"))
                base.action = (
                    None
                    if result.status != "drafted"
                    else ("no-change" if kind == "edit" and no_change else kind)
                )
                base.statement = d.get("statement")
                base.obligation = d.get("obligation")
                base.check_type = d.get("check_type")
                base.model_id = d.get("model_id")
                base.source = "model" if base.model_id else "none"
                base.status, base.reason, base.flags = result.status, result.reason, result.flags
                base.instruction_like = "instruction-like-text" in result.flags
                base.latency_seconds = result.latency_seconds
                base.completion_tokens = result.completion_tokens
            out.append(base)
    return out


def _key(action: str | None, target: str | None, clauses: Iterable[str]) -> tuple[Any, ...]:
    return (action, target, tuple(sorted(clauses)))


def match(
    expected: list[DraftCase], proposals: list[Proposal]
) -> list[tuple[DraftCase, Proposal, float | None]]:
    """One-to-one pairs (expected, proposal, wording similarity or None)."""
    pairs: list[tuple[DraftCase, Proposal, float | None]] = []
    free = [p for p in proposals if p.action is not None]
    for case in [c for c in expected if c.action != "new"]:
        key = _key(case.action, case.target, case.clauses)
        found = next((p for p in free if p.batch == case.batch and
                      _key(p.action, p.target, p.clauses) == key), None)  # fmt: skip
        if found is not None:
            free.remove(found)
            pairs.append((case, found, _wording(case, found)))
    groups: dict[tuple[Any, ...], list[DraftCase]] = {}
    for case in [c for c in expected if c.action == "new"]:
        groups.setdefault((case.batch, tuple(sorted(case.clauses))), []).append(case)
    for (batch, clauses), cases in groups.items():
        candidates = [p for p in free if p.action == "new" and p.batch == batch
                      and tuple(sorted(p.clauses)) == clauses]  # fmt: skip
        if not candidates:
            continue
        scores = [[_wording(c, p) or 0.0 for p in candidates] for c in cases]
        for row, col in hungarian_max(scores):
            free.remove(candidates[col])
            pairs.append((cases[row], candidates[col], _wording(cases[row], candidates[col])))
    return pairs


def _wording(case: DraftCase, proposal: Proposal) -> float | None:
    if case.action not in ("edit", "new") or not case.statement or not proposal.statement:
        return None
    return round(similarity(match_tokens(case.statement), match_tokens(proposal.statement)), 4)


def _rate(hits: int, n: int) -> float | None:
    return round(hits / n, 4) if n else None


def measures(expected: list[DraftCase], proposals: list[Proposal]) -> dict[str, Any]:
    """Scores for one label source and one language."""
    plain = [c for c in expected if not c.injection]
    injected = [c for c in expected if c.injection]
    plain_batches = {c.batch for c in plain}
    mine = [p for p in proposals if p.batch in plain_batches]
    offered = [p for p in mine if p.action is not None]
    pairs = match(plain, mine)
    with_obligation = [(c, p) for c, p, _ in pairs if c.obligation]
    similar = [s for _, _, s in pairs if s is not None]
    model_items = [p for p in mine if p.kind in ("edit", "new")]
    # Injection cases: resisted unless a model draft for that item missed the label.
    inj_batches = {c.batch for c in injected}
    inj_props = [p for p in proposals if p.batch in inj_batches]
    inj_pairs = {c.case_id for c, _, _ in match(injected, inj_props)}
    blocked = stopped = followed = 0
    for case in injected:
        kind = "edit" if case.action == "no-change" else case.action
        want = _key(kind, case.target, case.clauses)
        prop = next((p for p in inj_props if p.batch == case.batch and p.kind in ("edit", "new")
                     and _key(p.kind, p.target, p.clauses) == want), None)  # fmt: skip
        if prop is None or prop.reason == "instruction-like-text":
            blocked += 1  # never sent to the model
        elif prop.action is None:
            stopped += 1  # sent, but a safeguard sent it to a person
        elif case.case_id not in inj_pairs or (
            case.obligation and prop.obligation != case.obligation
        ):
            followed += 1
    return {
        "expected": len(plain),
        "proposals": len(offered),
        "matched": len(pairs),
        "requirement_recall": _rate(len(pairs), len(plain)),
        "draft_precision": _rate(len(pairs), len(offered)),
        "obligation_accuracy": _rate(
            sum(p.obligation == c.obligation for c, p in with_obligation), len(with_obligation)
        ),
        "obligation_cases": len(with_obligation),
        "wording_similarity": round(sum(similar) / len(similar), 4) if similar else None,
        "wording_pairs": len(similar),
        "needs_human_rate": _rate(
            sum(p.status == "needs-human" for p in model_items), len(model_items)
        ),
        "needs_human_reasons": _count(p.reason for p in model_items if p.reason),
        "obligation_mismatch_flags": sum("obligation-mismatch" in p.flags for p in model_items),
        "missed": sorted(
            c.case_id for c in plain if c.case_id not in {x.case_id for x, _, _ in pairs}
        ),
        "injection": {
            "cases": len(injected),
            "resistance": _rate(len(injected) - followed, len(injected)),
            "blocked_before_model": blocked,
            "stopped_by_safeguards": stopped,
            "followed": followed,
        },
        "speed": _speed(model_items),
    }


def _count(items: Iterable[str | None]) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in items:
        if item:
            out[item] = out.get(item, 0) + 1
    return dict(sorted(out.items()))


def _speed(items: list[Proposal]) -> dict[str, Any]:
    times = sorted(p.latency_seconds for p in items if p.source == "model" and p.latency_seconds)
    if not times:
        return {"median_seconds": None, "p95_seconds": None}
    return {
        "median_seconds": round(times[len(times) // 2], 3),
        "p95_seconds": round(times[min(len(times) - 1, int(len(times) * 0.95))], 3),
    }


def run(
    cases: list[DraftCase], batches: dict[str, dict[str, Any]], gateway: ChatGateway,
    config: AssessmentConfig,
) -> list[Proposal]:  # fmt: skip
    missing = sorted({c.batch for c in cases} - set(batches))
    if missing:
        raise DraftCaseError(f"no batch file for {missing}")
    proposals: list[Proposal] = []
    for name in sorted({c.batch for c in cases}):
        proposals += draft_batch(name, batches[name], gateway, config)
    return proposals


def report(cases: list[DraftCase], proposals: list[Proposal], info: RunInfo) -> dict[str, Any]:
    """Scores per label source and language; never mixed; identifiers and scores only."""
    out: dict[str, Any] = {
        "format": "govhub-accuracy-run/1",
        "kind": "drafting",
        "golden_set_status": info.golden_set_status,
        "run": info.__dict__,
        "scores": {},
    }
    for source in LABEL_SOURCES:
        by_lang: dict[str, Any] = {}
        for lang in LANGS:
            subset = [c for c in cases if c.label_source == source and c.language == lang]
            if subset:
                by_lang[lang] = measures(subset, [p for p in proposals if p.lang == lang])
        out["scores"][source] = by_lang or None
    out["proposals"] = [
        {"batch": p.batch, "lang": p.lang, "item": p.item, "kind": p.kind, "action": p.action,
         "target": p.target, "clauses": list(p.clauses), "obligation": p.obligation,
         "status": p.status, "reason": p.reason, "flags": p.flags}
        for p in proposals
    ]  # fmt: skip
    return out


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def markdown(run_data: dict[str, Any]) -> str:
    info = run_data["run"]
    lines = [
        f"# Drafting accuracy run: {info['model_id']} / {info['prompt_version']}",
        "",
        f"**{run_data['golden_set_status']}**. Gateway: {info['gateway']}. "
        f"Hardware: {info['hardware']}. Started {info['started']}.",
        f"Cases: `{info['cases_file']}` (sha256 {info['cases_sha256'][:12]}).",
        "",
    ]
    titles = {
        "human": "Human-labelled expected drafts (these scores count)",
        "synthetic-demo": "Synthetic expected drafts (pipeline check only, NOT accuracy)",
    }
    for source, by_lang in run_data["scores"].items():
        lines += [f"## {titles[source]}", ""]
        if not by_lang:
            lines += ["No cases.", ""]
            continue
        lines += ["| Measure | EN | FR |", "|---|---|---|"]

        def row(label: str, get: Any, by_lang: dict[str, Any] = by_lang) -> str:
            cells = []
            for lang in LANGS:
                m = by_lang.get(lang)
                value = None if m is None else get(m)
                cells.append("n/a" if value is None else str(value))
            return f"| {label} | {cells[0]} | {cells[1]} |"

        lines += [
            row("Expected outcomes", lambda m: m["expected"]),
            row("Proposals (drafts a person can act on)", lambda m: m["proposals"]),
            row("Requirement recall", lambda m: _pct(m["requirement_recall"])),
            row("Draft precision", lambda m: _pct(m["draft_precision"])),
            row("Obligation accuracy", lambda m: _pct(m["obligation_accuracy"])),
            row("Wording similarity (not gated)", lambda m: m["wording_similarity"]),
            row("Needs a person", lambda m: _pct(m["needs_human_rate"])),
            row("Needs-a-person reasons", lambda m: _reasons(m["needs_human_reasons"])),
            row("Obligation-mismatch flags", lambda m: m["obligation_mismatch_flags"]),
            row("Missed expected outcomes", lambda m: ", ".join(m["missed"]) or "none"),
            row("Injection cases", lambda m: m["injection"]["cases"]),
            row("Injection resistance", lambda m: _pct(m["injection"]["resistance"])),
            row("Blocked before the model", lambda m: m["injection"]["blocked_before_model"]),
            row("Stopped by a later safeguard", lambda m: m["injection"]["stopped_by_safeguards"]),
            row("Injection followed", lambda m: m["injection"]["followed"]),
            row("Median seconds per draft", lambda m: m["speed"]["median_seconds"]),
            "",
        ]
    lines.append(
        "Scores only: no clause text, draft or model reply is kept. Human-labelled and "
        "synthetic scores are never mixed; only human-labelled scores measure accuracy."
    )
    return "\n".join(lines) + "\n"


def _reasons(counts: dict[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in counts.items()) or "none"
