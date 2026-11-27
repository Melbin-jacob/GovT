"""Assessment-engine results replace placeholder findings (the finding stays open).

The engine only ever drafts: a result sets the finding's verdict, confidence and
rationale and keeps the engine's details, but never changes its state. Decided findings
are refused (409). Called by the assessment engine with the placeholder identity role
``assessment-engine`` (TODO(control-centre): service identity).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from review_desk.models import Finding
from review_desk.queue import OPEN_STATES

ENGINE_ROLE = "assessment-engine"
Verdict = Literal["met", "partially-met", "not-met", "not-applicable", "unable-to-determine"]


class AssessmentResult(BaseModel):
    assessment_id: str
    run_id: str
    method: Literal["rule", "model"]
    verdict: Verdict
    confidence: float | None = Field(default=None, ge=0, le=1)
    rationale: dict[str, str] = Field(description='{"en": ..., "fr": ...}')
    model_id: str | None = None
    prompt_version: str | None = None
    model_verdict: str | None = None
    downgrade_reason: str | None = None
    cited_passage_id: str | None = None
    cited_quote: str | None = None
    evidence_language: str | None = None
    flagged_passage_ids: list[str] = Field(default_factory=list)
    rule_status: str | None = None
    facts_used: dict[str, Any] = Field(default_factory=dict)
    missing_facts: list[str] = Field(default_factory=list)


class AssessmentRefusedError(ValueError):
    pass


def apply(session: Session, finding: Finding, result: AssessmentResult) -> Finding:
    if finding.state not in OPEN_STATES:
        raise AssessmentRefusedError(f"finding is {finding.state}: only open findings take drafts")
    finding.verdict = result.verdict
    finding.confidence = result.confidence
    finding.rationale = result.rationale.get("en", "")
    finding.placeholder = False
    finding.assessment = result.model_dump(mode="json")
    session.flush()
    return finding
