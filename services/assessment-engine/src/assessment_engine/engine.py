"""One assessment run: each (system, control) goes to plain code or to the model.

Check type comes from the catalog (``check-type`` prop): rule-based checks are evaluated
against the system's facts; judgment checks get the best evidence passages and go to the
model through the gateway, in the evidence's language. Results are stored immutably and
as an OSCAL assessment-results document. Nothing here closes a finding.
"""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from assessment_engine import evidence, oscal_ar, rules
from assessment_engine.controls import ControlInfo, ControlSource
from assessment_engine.judgment import ControlText, EvidencePassage, assess_judgment
from assessment_engine.models import Assessment, AssessmentResultsDocument, SystemFact
from assessment_engine.settings_file import AssessmentConfig
from govhub_shared.model_gateway import ChatGateway
from govhub_shared.oscal import content_hash


@dataclass
class RunRequest:
    system_id: str
    catalog: str
    catalog_version: str
    control_ids: list[str]
    as_of: date
    findings: dict[str, str]  # control ID -> review-desk finding ID
    tenant: str | None = None  # the system's tenant (row-level security)


def facts_of(session: Session, system_id: str) -> dict[str, rules.Fact]:
    rows = session.scalars(select(SystemFact).where(SystemFact.system_id == system_id))
    return {r.name: rules.Fact(r.value, r.source) for r in rows}


def retrieval_query(controls: dict[str, dict[str, ControlInfo]], control_id: str) -> str:
    """Statement and expected evidence in both languages, so evidence in either language
    is found even when one catalog lacks a field."""
    texts = [controls[la][control_id] for la in ("en", "fr") if control_id in controls[la]]
    return " ".join(f"{t.statement} {t.objective or ''}" for t in texts)


def evidence_language(retrieved: list[evidence.Retrieved]) -> str:
    counts = Counter(r.passage.language for r in retrieved if r.passage.language in ("en", "fr"))
    return "fr" if counts["fr"] > counts["en"] else "en"


def assess_control(
    session: Session,
    *,
    gateway: ChatGateway,
    controls: dict[str, dict[str, ControlInfo]],
    ruleset: rules.RuleSet | None,
    facts: dict[str, rules.Fact],
    system_id: str,
    control_id: str,
    as_of: date,
    config: AssessmentConfig,
) -> tuple[str, str, float | None, str, dict[str, Any]]:
    """(method, verdict, confidence, lang, detail) for one control."""
    info = controls["en"].get(control_id) or controls["fr"].get(control_id)
    if info is None:
        raise LookupError(f"control {control_id} is not in the catalog")
    if info.check_type.startswith("rule-based"):
        outcome = rules.assess_rule(ruleset, control_id, facts, as_of)
        return "rule", outcome.verdict, outcome.confidence, "both", outcome.as_dict()
    query = retrieval_query(controls, control_id)
    retrieved = evidence.retrieve(session, system_id, query, config.passages)
    lang = evidence_language(retrieved)
    text = controls[lang].get(control_id) or info
    judged = assess_judgment(
        gateway,
        ControlText(control_id, text.statement, text.objective),
        [
            EvidencePassage(r.passage.id, r.passage.text, list(r.passage.injection_flags))
            for r in retrieved
        ],
        lang,
        config,
    )
    detail = judged.as_dict() | {
        "retrieval_scores": {r.passage.id: round(r.score, 4) for r in retrieved}
    }
    return "model", judged.verdict, judged.confidence, lang, detail


def run(
    session: Session,
    request: RunRequest,
    *,
    gateway: ChatGateway,
    source: ControlSource,
    rules_dir: Path,
    config: AssessmentConfig,
) -> tuple[str, list[Assessment], AssessmentResultsDocument]:
    run_id = str(uuid.uuid4())
    started = datetime.now(UTC)
    controls = {
        la: _safe(source, request.catalog, request.catalog_version, la) for la in ("en", "fr")
    }
    ruleset = rules.load_rules(rules_dir, request.catalog)
    facts = facts_of(session, request.system_id)
    rows: list[Assessment] = []
    for control_id in request.control_ids:
        method, verdict, confidence, lang, detail = assess_control(
            session,
            gateway=gateway,
            controls=controls,
            ruleset=ruleset,
            facts=facts,
            system_id=request.system_id,
            control_id=control_id,
            as_of=request.as_of,
            config=config,
        )
        rows.append(
            Assessment(
                id=str(uuid.uuid4()),
                run_id=run_id,
                finding_id=request.findings.get(control_id),
                system_id=request.system_id,
                tenant=request.tenant,
                catalog=request.catalog,
                catalog_version=request.catalog_version,
                control_id=control_id,
                method=method,
                lang=lang,
                verdict=verdict,
                confidence=confidence,
                detail=detail,
                created_at=started,
            )
        )
    session.add_all(rows)
    doc = oscal_ar.build(
        run_id=run_id,
        system_id=request.system_id,
        catalog=request.catalog,
        catalog_version=request.catalog_version,
        started=started,
        assessments=[assessment_view(r) for r in rows],
    )
    stored = AssessmentResultsDocument(
        run_id=run_id,
        system_id=request.system_id,
        tenant=request.tenant,
        document=doc,
        content_hash=content_hash(doc, "assessment-results"),
        created_at=started,
    )
    session.add(stored)
    session.flush()
    return run_id, rows, stored


def _safe(source: ControlSource, catalog: str, version: str, lang: str) -> dict[str, ControlInfo]:
    try:
        return source.controls(catalog, version, lang)
    except LookupError:
        return {}


def assessment_view(row: Assessment) -> dict[str, Any]:
    return {
        "id": row.id,
        "run_id": row.run_id,
        "finding_id": row.finding_id,
        "system_id": row.system_id,
        "catalog": row.catalog,
        "catalog_version": row.catalog_version,
        "control_id": row.control_id,
        "method": row.method,
        "lang": row.lang,
        "verdict": row.verdict,
        "confidence": row.confidence,
        "detail": row.detail,
        "created_at": row.created_at.isoformat(),
    }
