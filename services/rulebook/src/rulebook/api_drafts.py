"""Rulebook drafts API: batches planned from a source change, drafts per language.

Placeholder identity (``identity.py``): keep the rulebook on localhost or the internal
network until control-centre provides sign-in.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from govhub_shared.obligations import OBLIGATION_CODES
from rulebook import approval_log, drafts
from rulebook.db import get_session
from rulebook.identity import ENGINE_ROLE, ActorDep
from rulebook.models import DraftBatch, DraftItem

router = APIRouter(prefix="/drafts", tags=["drafts"])
SessionDep = Annotated[Session, Depends(get_session)]
CHECK_TYPES = ("rule-based", "judgment")


class BatchRequest(BaseModel):
    catalog: str
    version: str = Field(description="Catalog version whose links use the 'from' numbering")
    instrument: str
    from_version: str = Field(alias="from")
    to_version: str = Field(alias="to")


class LanguageDraft(BaseModel):
    """One language's draft of one item, from the model (or a person, see approval)."""

    status: Literal["drafted", "needs-human"]
    no_change: bool = False
    statement: str | None = None
    guidance: str | None = None
    objective: str | None = None
    check_type: Literal["rule-based", "judgment"] | None = None
    obligation: str | None = None
    cited_clause: str | None = None
    reasoning: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    model_id: str | None = None
    prompt_version: str | None = None
    flags: list[str] = Field(default_factory=list)
    reason: str | None = Field(default=None, description="Why a person must draft it")


def get_batch(session: Session, batch_id: str) -> DraftBatch:
    batch = session.get(DraftBatch, batch_id)
    if batch is None:
        raise HTTPException(404, "draft batch not found")
    return batch


def get_item(session: Session, item_id: str) -> DraftItem:
    item = session.get(DraftItem, item_id)
    if item is None:
        raise HTTPException(404, "draft item not found")
    return item


@router.post("/batches", status_code=201)
def create_batch(body: BatchRequest, session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    """Plan the drafting work for a source change (plain code; no model yet)."""
    try:
        batch = drafts.plan_batch(
            session,
            catalog=body.catalog,
            version=body.version,
            instrument=body.instrument,
            from_version=body.from_version,
            to_version=body.to_version,
            created_by=actor.id,
        )
    except drafts.DraftPlanError as exc:
        raise HTTPException(422, str(exc)) from exc
    session.commit()
    return drafts.batch_view(session, batch)


@router.get("/batches")
def list_batches(session: SessionDep, catalog: str | None = None) -> list[dict[str, Any]]:
    query = select(DraftBatch).order_by(DraftBatch.created_at.desc())
    if catalog:
        query = query.where(DraftBatch.catalog == catalog)
    return [
        {
            "id": b.id,
            "catalog": b.catalog,
            "base_version": b.base_version,
            "source_change": f"{b.instrument} {b.from_version} -> {b.to_version}",
            "status": b.status,
            "new_version": b.new_version,
            "created_at": b.created_at.isoformat(),
        }
        for b in session.scalars(query)
    ]


@router.get("/batches/{batch_id}")
def read_batch(batch_id: str, session: SessionDep) -> dict[str, Any]:
    return drafts.batch_view(session, get_batch(session, batch_id))


@router.put("/items/{item_id}/model/{lang}")
def put_model_draft(
    item_id: str,
    lang: Literal["en", "fr"],
    draft: LanguageDraft,
    session: SessionDep,
    actor: ActorDep,
) -> dict[str, Any]:
    """The assessment engine's draft for one language (only it may post model drafts)."""
    if actor.role != ENGINE_ROLE:
        raise HTTPException(403, "only the assessment engine posts model drafts")
    item = get_item(session, item_id)
    batch = get_batch(session, item.batch_id)
    if batch.status != "open" or item.status in ("approved", "rejected"):
        raise HTTPException(409, f"item is {item.status} in a {batch.status} batch")
    if item.kind not in ("edit", "new"):
        raise HTTPException(409, f"{item.kind} items are not drafted by the model")
    if draft.obligation is not None and draft.obligation not in OBLIGATION_CODES:
        raise HTTPException(422, f"obligation must be one of {list(OBLIGATION_CODES)}")
    item.drafts = {**item.drafts, lang: {**draft.model_dump(), "source": "model"}}
    if all(item.drafts[la].get("status") != "pending" for la in drafts.LANGS):
        item.status = "ready"
    approval_log.append(
        session,
        {
            "action": "model-drafted",
            "batch": batch.id,
            "item": item.id,
            "lang": lang,
            "draft": draft.model_dump(),
            "by": actor.id,
        },
        batch_id=batch.id,
        item_id=item.id,
    )
    session.commit()
    return drafts.item_view(item)


@router.get("/log/verify")
def verify_log(session: SessionDep) -> dict[str, Any]:
    return approval_log.verify(session).as_dict()
