"""FastAPI application for the assessment engine.

Internal only: reached by control-centre and the demo scripts on localhost or the internal
network. It calls the rulebook and review-desk (internal) and the self-hosted model server
through the model gateway (allow-listed host); nothing else.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from assessment_engine import engine, evidence, rules
from assessment_engine.access import (
    ASSESSORS,
    EVIDENCE_READERS,
    EVIDENCE_WRITERS,
    METADATA_READERS,
    AnySignedIn,
    Officer,
    PrincipalDep,
    ReviewDeskOnly,
    Systems,
    check_system,
)
from assessment_engine.config import get_settings
from assessment_engine.controls import ControlSource, RulebookControls
from assessment_engine.db import get_session
from assessment_engine.models import (
    Assessment,
    AssessmentResultsDocument,
    EvidenceDocument,
    SystemFact,
)
from assessment_engine.review_desk import HttpReviewDesk, ReviewDesk, draft_of
from assessment_engine.rulebook_drafts import HttpRulebookDrafts, RulebookDrafts, draft_batch
from assessment_engine.settings_file import AssessmentConfig, load_config
from govhub_shared.auth.client import trust_store
from govhub_shared.auth.web import install
from govhub_shared.model_gateway import ChatGateway, gateway_from_env

app = FastAPI(title="Canadian AI Governance Hub - Assessment engine", version="0.1.0")
ReadSession = Annotated[Session, Depends(get_session)]
# Internal tokens (GOVHUB_TRUST_FILE); without them protected endpoints answer 503.
_trust = trust_store()
if _trust is not None:
    install(app, "assessment-engine", _trust)


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready(session: ReadSession) -> dict[str, str]:
    try:
        session.execute(text("SELECT 1"))
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return {"status": "ready"}


@app.get("/evidence-policy", tags=["evidence"])
def evidence_policy(who: AnySignedIn) -> dict[str, Any]:
    """How evidence is protected and kept. Retention is a PLACEHOLDER owned by
    control-centre later (TODO(control-centre)): nothing is deleted automatically yet."""
    settings = get_settings()
    return {
        "service_encryption": "aes-256-gcm" if settings.evidence_key else "off",
        "volume_encryption": "platform (encrypted volume where the platform allows)",
        "retention_days": settings.evidence_retention_days,
        "retention_status": "PLACEHOLDER: owned by control-centre (TODO(control-centre))",
        "passage_text_logged": False,
    }


# --- evidence --------------------------------------------------------------------------


@app.post("/systems/{system_id}/evidence", tags=["evidence"], status_code=201)
async def upload_evidence(
    system_id: str,
    session: ReadSession,
    file: Annotated[UploadFile, File(description="TXT, Markdown, HTML, PDF or DOCX")],
    who: PrincipalDep,
    systems: Systems,
) -> dict[str, Any]:
    """Store and index one evidence file for a system (same file twice: no duplicate).
    The system's owners and reviewers; the uploader is recorded (conflict of interest)."""
    check_system(systems, who, system_id, *EVIDENCE_WRITERS)
    user = who.id
    settings = get_settings()
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(413, f"file larger than {settings.max_upload_bytes} bytes")
    doc, rows, created = evidence.ingest(
        session,
        evidence.store_for(settings),
        system_id=system_id,
        filename=file.filename or "upload",
        data=data,
        uploaded_by=user,
    )
    session.commit()
    return {**evidence.document_view(doc, rows), "created": created}


@app.get("/systems/{system_id}/evidence", tags=["evidence"])
def list_evidence(
    system_id: str, session: ReadSession, who: PrincipalDep, systems: Systems
) -> list[dict[str, Any]]:
    """Evidence files of a system (metadata and passage counts, no text)."""
    check_system(systems, who, system_id, *METADATA_READERS)
    docs = session.scalars(
        select(EvidenceDocument)
        .where(EvidenceDocument.system_id == system_id)
        .order_by(EvidenceDocument.uploaded_at)
    )
    return [evidence.document_view(d, evidence.passages_of(session, d.id)) for d in docs]


@app.get("/evidence/{document_id}/passages", tags=["evidence"])
def document_passages(
    document_id: str, session: ReadSession, who: PrincipalDep, systems: Systems
) -> list[dict[str, Any]]:
    """The document's text, passage by passage (owners, reviewers, auditors)."""
    doc = session.get(EvidenceDocument, document_id)
    if doc is None:
        raise HTTPException(404, "evidence document not found")
    check_system(systems, who, doc.system_id, *EVIDENCE_READERS)
    return [evidence.passage_view(p) for p in evidence.passages_of(session, document_id)]


@app.get("/systems/{system_id}/evidence/search", tags=["evidence"])
def search_evidence(
    system_id: str,
    session: ReadSession,
    who: PrincipalDep,
    systems: Systems,
    q: Annotated[str, Query(min_length=2)],
    k: Annotated[int, Query(ge=1, le=20)] = 5,
) -> list[dict[str, Any]]:
    """Best-matching passages (BM25) for a query, e.g. a control statement."""
    check_system(systems, who, system_id, *EVIDENCE_READERS)
    return [
        {**evidence.passage_view(r.passage), "score": round(r.score, 4)}
        for r in evidence.retrieve(session, system_id, q, k)
    ]


# --- facts and rule-based checks -------------------------------------------------------


def facts_of(session: Session, system_id: str) -> dict[str, rules.Fact]:
    rows = session.scalars(select(SystemFact).where(SystemFact.system_id == system_id))
    return {r.name: rules.Fact(r.value, r.source) for r in rows}


@app.put("/systems/{system_id}/facts", tags=["facts"])
def put_facts(
    system_id: str,
    session: ReadSession,
    facts: Annotated[
        dict[str, dict[str, Any]],
        Body(embed=True, description='{"name": {"value": ..., "source": "..."}}'),
    ],
    who: PrincipalDep,
    systems: Systems,
) -> dict[str, Any]:
    """Record structured facts about a system (latest value wins; null clears a fact).
    The system's owners and reviewers; the writer is recorded (conflict of interest)."""
    check_system(systems, who, system_id, *EVIDENCE_WRITERS)
    user = who.id
    now = datetime.now(UTC)
    for name, entry in facts.items():
        if not isinstance(entry, dict) or "value" not in entry:
            raise HTTPException(422, f"fact {name}: expected {{'value': ..., 'source': ...}}")
        row = session.get(SystemFact, (system_id, name))
        if row is None:
            row = SystemFact(system_id=system_id, name=name)
            session.add(row)
        row.value = entry["value"]
        row.source = str(entry.get("source", ""))[:255]
        row.recorded_by = user[:128]
        row.recorded_at = now
    session.commit()
    return {"system_id": system_id, "facts": _facts_view(session, system_id)}


@app.get("/systems/{system_id}/facts", tags=["facts"])
def get_facts(
    system_id: str, session: ReadSession, who: PrincipalDep, systems: Systems
) -> dict[str, Any]:
    check_system(systems, who, system_id, *EVIDENCE_READERS)
    return _facts_view(session, system_id)


@app.get("/systems/{system_id}/provenance", tags=["facts"])
def provenance(system_id: str, session: ReadSession, who: ReviewDeskOnly) -> dict[str, Any]:
    """Who uploaded the system's evidence and who wrote its facts (review-desk's
    conflict-of-interest check: such a person cannot decide the system's findings)."""
    uploaders = session.scalars(
        select(EvidenceDocument.uploaded_by).where(EvidenceDocument.system_id == system_id)
    )
    writers = session.scalars(
        select(SystemFact.recorded_by).where(SystemFact.system_id == system_id)
    )
    return {
        "system_id": system_id,
        "evidence_uploaders": sorted(set(uploaders)),
        "fact_writers": sorted(set(writers)),
    }


def _facts_view(session: Session, system_id: str) -> dict[str, Any]:
    return {
        name: {"value": fact.value, "source": fact.source}
        for name, fact in sorted(facts_of(session, system_id).items())
    }


@app.get("/systems/{system_id}/rule-checks", tags=["facts"])
def rule_checks(
    system_id: str,
    session: ReadSession,
    who: PrincipalDep,
    systems: Systems,
    catalog: str,
    as_of: date,
    control: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    """Evaluate the catalog's rule-based checks for the system (no model, no storage)."""
    check_system(systems, who, system_id, *EVIDENCE_READERS)
    ruleset = rules.load_rules(Path(get_settings().rules_dir), catalog)
    if ruleset is None:
        raise HTTPException(404, f"no rules file for catalog {catalog}")
    facts = facts_of(session, system_id)
    ids = control or sorted(ruleset.rules)
    return {
        "catalog": catalog,
        "rules_file": ruleset.path,
        "rules_status": ruleset.status,
        "as_of": as_of.isoformat(),
        "results": [rules.assess_rule(ruleset, cid, facts, as_of).as_dict() for cid in ids],
    }


# --- assessment runs -------------------------------------------------------------------


def get_gateway() -> ChatGateway:
    """The model gateway from MODEL_GATEWAY_* (overridden in tests with recordings)."""
    return gateway_from_env()


def get_controls() -> ControlSource:
    return RulebookControls(get_settings().rulebook_url)


def get_config() -> AssessmentConfig:
    return load_config(Path(get_settings().assessment_config_path))


class RunBody(BaseModel):
    system_id: str
    catalog: str
    catalog_version: str
    control_ids: list[str] = Field(min_length=1)
    as_of: date
    findings: dict[str, str] = Field(default_factory=dict, description="control -> finding ID")


@app.post("/assessments", tags=["assessments"], status_code=201)
def run_assessments(
    body: RunBody,
    session: ReadSession,
    who: PrincipalDep,
    systems: Systems,
    gateway: Annotated[ChatGateway, Depends(get_gateway)],
    source: Annotated[ControlSource, Depends(get_controls)],
    config: Annotated[AssessmentConfig, Depends(get_config)],
) -> dict[str, Any]:
    """Assess controls for one system (a reviewer of its tenant). Results are drafts: a
    person decides."""
    check_system(systems, who, body.system_id, *ASSESSORS)
    try:
        run_id, rows, doc = engine.run(
            session,
            engine.RunRequest(**body.model_dump()),
            gateway=gateway,
            source=source,
            rules_dir=Path(get_settings().rules_dir),
            config=config,
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    session.commit()
    return {
        "run_id": run_id,
        "assessments": [engine.assessment_view(r) for r in rows],
        "assessment_results": {"run_id": run_id, "content_hash": doc.content_hash},
        "threshold": {"value": config.threshold, "status": config.threshold_status},
    }


@app.get("/assessments/{assessment_id}", tags=["assessments"])
def get_assessment(
    assessment_id: str, session: ReadSession, who: PrincipalDep, systems: Systems
) -> dict[str, Any]:
    row = session.get(Assessment, assessment_id)
    if row is None:
        raise HTTPException(404, "assessment not found")
    check_system(systems, who, row.system_id, *EVIDENCE_READERS)
    return engine.assessment_view(row)


@app.get("/runs/{run_id}/assessment-results", tags=["assessments"])
def get_assessment_results(
    run_id: str, session: ReadSession, who: PrincipalDep, systems: Systems
) -> dict[str, Any]:
    """The run's OSCAL 1.1.3 assessment-results document."""
    row = session.get(AssessmentResultsDocument, run_id)
    if row is None:
        raise HTTPException(404, "assessment run not found")
    check_system(systems, who, row.system_id, *EVIDENCE_READERS)
    return row.document


def get_review_desk() -> ReviewDesk:
    return HttpReviewDesk(get_settings().review_desk_url)


class SystemRunBody(BaseModel):
    as_of: date
    control_ids: list[str] | None = Field(default=None, description="Default: all open")


@app.post("/systems/{system_id}/assess-open-findings", tags=["assessments"])
def assess_open_findings(
    system_id: str,
    body: SystemRunBody,
    session: ReadSession,
    gateway: Annotated[ChatGateway, Depends(get_gateway)],
    source: Annotated[ControlSource, Depends(get_controls)],
    config: Annotated[AssessmentConfig, Depends(get_config)],
    desk: Annotated[ReviewDesk, Depends(get_review_desk)],
    who: PrincipalDep,
    systems: Systems,
) -> dict[str, Any]:
    """Assess the system's open findings in review-desk and post the drafts back (a
    reviewer of the system's tenant). The findings stay open: a person decides."""
    check_system(systems, who, system_id, *ASSESSORS)
    findings = [
        f
        for f in desk.open_findings(system_id)
        if body.control_ids is None or f["control_id"] in body.control_ids
    ]
    groups: dict[tuple[str, str], dict[str, str]] = {}
    for f in findings:
        groups.setdefault((f["catalog"], f["catalog_version"]), {})[f["control_id"]] = f["id"]
    runs = []
    for (catalog, version), by_control in sorted(groups.items()):
        request = engine.RunRequest(
            system_id=system_id,
            catalog=catalog,
            catalog_version=version,
            control_ids=sorted(by_control),
            as_of=body.as_of,
            findings=by_control,
        )
        try:
            run_id, rows, doc = engine.run(
                session,
                request,
                gateway=gateway,
                source=source,
                rules_dir=Path(get_settings().rules_dir),
                config=config,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        session.commit()
        pushed = {r.control_id: desk.push(str(r.finding_id), draft_of(r)) for r in rows}
        runs.append(
            {
                "run_id": run_id,
                "catalog": catalog,
                "catalog_version": version,
                "assessments": [engine.assessment_view(r) for r in rows],
                "review_desk": pushed,
                "assessment_results": {"run_id": run_id, "content_hash": doc.content_hash},
            }
        )
    return {"system_id": system_id, "findings": len(findings), "runs": runs}


# --- drafting control changes ----------------------------------------------------------


def get_rulebook_drafts() -> RulebookDrafts:
    return HttpRulebookDrafts(get_settings().rulebook_url)


@app.post("/drafting/batches/{batch_id}/draft", tags=["drafting"])
def draft_rulebook_batch(
    batch_id: str,
    who: Officer,
    gateway: Annotated[ChatGateway, Depends(get_gateway)],
    config: Annotated[AssessmentConfig, Depends(get_config)],
    rulebook: Annotated[RulebookDrafts, Depends(get_rulebook_drafts)],
) -> dict[str, Any]:
    """Draft every pending edit and new control of a rulebook batch, in English and French
    separately, and send the drafts to the rulebook. A person approves them there."""
    return draft_batch(rulebook, gateway, batch_id, config)
