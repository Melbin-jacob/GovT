"""Rulebook drafts API: batches planned from a source change, drafts per language.

Placeholder identity (``identity.py``): keep the rulebook on localhost or the internal
network until control-centre provides sign-in.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from govhub_shared.obligations import OBLIGATION_CODES
from rulebook import approval, approval_log, drafts, reading
from rulebook.access import audit_drafts, edit_drafts, engine_drafts, govern_drafts, read_drafts
from rulebook.config import get_settings
from rulebook.db import get_session
from rulebook.identity import ENGINE_ROLE, ActorDep
from rulebook.models import DraftBatch, DraftItem

router = APIRouter(prefix="/drafts", tags=["drafts"])
SessionDep = Annotated[Session, Depends(get_session)]


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


@router.post("/batches", status_code=201, dependencies=[Depends(govern_drafts)])
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


@router.get("/batches", dependencies=[Depends(read_drafts)])
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


@router.get("/batches/{batch_id}", dependencies=[Depends(read_drafts)])
def read_batch(batch_id: str, session: SessionDep, session_id: str | None = None) -> dict[str, Any]:
    """With ``session_id``: each item's ``read`` shows which languages count as opened."""
    view = drafts.batch_view(session, get_batch(session, batch_id))
    if session_id:
        by_id = {i.id: i for i in drafts.items_of(session, batch_id)}
        for entry in view["items"]:
            entry["read"] = reading.read_times(session, by_id[entry["id"]], session_id)
    return view


@router.put("/items/{item_id}/model/{lang}", dependencies=[Depends(engine_drafts)])
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
    reading.touch(item)
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


@router.get("/log/verify", dependencies=[Depends(audit_drafts)])
def verify_log(session: SessionDep) -> dict[str, Any]:
    return approval_log.verify(session).as_dict()


class EditRequest(BaseModel):
    languages: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description='{"en": {"statement": ..., "guidance": ..., "objective": ..., '
        '"check_type": ..., "obligation": ..., "no_change": false}, "fr": {...}}',
    )
    proposed_id: str | None = None


class DecisionRequest(BaseModel):
    reason: str = ""
    session_id: str | None = Field(
        default=None, description="Approval session in which both languages were opened"
    )


class ViewRequest(BaseModel):
    session_id: str
    lang: Literal["en", "fr"]
    items: list[str] | None = Field(default=None, description="Default: every draft shown")


class PublishRequest(BaseModel):
    source_date: str | None = Field(default=None, description="Default: see publish-defaults")


def _approval(call: Any) -> Any:
    try:
        return call()
    except (approval.ApprovalError, reading.ReadingError) as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": str(exc)}) from exc


@router.post("/sessions", status_code=201, dependencies=[Depends(edit_drafts)])
def start_session(session: SessionDep, actor: ActorDep) -> dict[str, Any]:
    """An approval session: the drafts this person opens are recorded in it."""
    row = _approval(lambda: reading.start(session, actor))
    session.commit()
    return {"id": row.id, "user": row.user_id, "started_at": row.started_at.isoformat()}


@router.post("/batches/{batch_id}/views", dependencies=[Depends(edit_drafts)])
def record_views(
    batch_id: str, body: ViewRequest, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    """The person opened one language's view of these drafts (control-centre calls this
    when it shows the page)."""
    batch = get_batch(session, batch_id)
    items = [
        i for i in drafts.items_of(session, batch.id) if body.items is None or i.id in body.items
    ]
    count = _approval(
        lambda: reading.record(session, actor, batch, items, body.session_id, body.lang)
    )
    session.commit()
    return {"recorded": count, "lang": body.lang, "session_id": body.session_id}


@router.put("/items/{item_id}", dependencies=[Depends(edit_drafts)])
def edit_item(
    item_id: str, body: EditRequest, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    """A person writes or corrects drafts (reviewer or governance officer)."""
    item = get_item(session, item_id)
    batch = get_batch(session, item.batch_id)
    for lang, fields in body.languages.items():
        LanguageDraft(status="drafted", **{k: v for k, v in fields.items() if k != "status"})
        if fields.get("obligation") not in (None, *OBLIGATION_CODES):
            raise HTTPException(422, f"{lang}: obligation must be one of {list(OBLIGATION_CODES)}")
    _approval(lambda: approval.edit(session, batch, item, actor, body.languages, body.proposed_id))
    session.commit()
    return drafts.item_view(item)


@router.post("/items/{item_id}/approve", dependencies=[Depends(govern_drafts)])
def approve_item(
    item_id: str, session: SessionDep, actor: ActorDep, body: DecisionRequest | None = None
) -> dict[str, Any]:
    """Both languages must have been opened in ``session_id`` since the last change."""
    item = get_item(session, item_id)
    batch = get_batch(session, item.batch_id)
    sid = body.session_id if body else None
    _approval(lambda: approval.decide(session, batch, item, actor, "approve", "", sid))
    session.commit()
    return drafts.item_view(item)


@router.post("/items/{item_id}/reject", dependencies=[Depends(govern_drafts)])
def reject_item(
    item_id: str, body: DecisionRequest, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    item = get_item(session, item_id)
    batch = get_batch(session, item.batch_id)
    _approval(lambda: approval.decide(session, batch, item, actor, "reject", body.reason))
    session.commit()
    return drafts.item_view(item)


@router.get("/batches/{batch_id}/publish-defaults", dependencies=[Depends(read_drafts)])
def publish_defaults(batch_id: str, session: SessionDep) -> dict[str, Any]:
    """The SOURCE_DATE default and the date it must be later than."""
    batch = get_batch(session, batch_id)
    return {
        **approval.source_date_bounds(session, batch),
        "version": batch.plan["proposed_version"],
    }


@router.post("/batches/{batch_id}/publish", dependencies=[Depends(govern_drafts)])
def publish_batch(
    batch_id: str, body: PublishRequest, session: SessionDep, actor: ActorDep
) -> dict[str, Any]:
    """Approved drafts become a new immutable catalog version (minor bump)."""
    batch = get_batch(session, batch_id)
    source_date = body.source_date or approval.source_date_bounds(session, batch)["default"]
    result = _approval(
        lambda: approval.publish(
            session, batch, actor, source_date, get_settings().approval_checkpoint_file
        )
    )
    batch.plan = {**batch.plan, "change_set": result["change_set"]}
    session.commit()
    return dict(result)


@router.get("/batches/{batch_id}/change-set", dependencies=[Depends(audit_drafts)])
def change_set(batch_id: str, session: SessionDep) -> dict[str, Any]:
    """The published change set, for ``rulebook apply-drafts`` (golden-set CSV)."""
    batch = get_batch(session, batch_id)
    if "change_set" not in batch.plan:
        raise HTTPException(404, "the batch is not published yet")
    data: dict[str, Any] = batch.plan["change_set"]
    return data


@router.get("/log/export", response_class=PlainTextResponse, dependencies=[Depends(audit_drafts)])
def export_log(session: SessionDep) -> str:
    return "\n".join(approval_log.export_lines(session)) + "\n"
