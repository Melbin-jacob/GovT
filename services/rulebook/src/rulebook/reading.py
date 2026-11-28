"""Has the approver read both languages? Server-side record, not only a checkbox.

The rulebook issues an **approval session** to a person (``POST /drafts/sessions``).
Each time that person opens one language's view of a batch, control-centre records a
**view** of every draft shown (``POST /drafts/batches/{id}/views``). Approving an edit or
a new control needs, in the approver's own session, a view of the English **and** the
French draft made after the draft last changed (``changed_at``): a draft edited after it
was read must be read again. Clause-reference updates and retirements have no wording,
so they need no views. The views are append-only (a DB trigger refuses changes), and the
approval record in the hash-chained log carries the session and both view times.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from rulebook.golden import LANGS
from rulebook.identity import EDITOR_ROLES, Actor
from rulebook.models import DraftBatch, DraftItem, DraftSession, DraftView

NEEDS_READING = ("edit", "new")


class ReadingError(ValueError):
    def __init__(self, status: int, message: str, code: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def now() -> datetime:
    return datetime.now(UTC)


def touch(item: DraftItem) -> None:
    """A draft changed: earlier views no longer count."""
    item.changed_at = now()


def start(session: Session, actor: Actor) -> DraftSession:
    if actor.role not in EDITOR_ROLES:
        raise ReadingError(403, "only reviewers and governance officers read drafts", "role")
    row = DraftSession(id=str(uuid.uuid4()), user_id=actor.id, role=actor.role, started_at=now())
    session.add(row)
    session.flush()
    return row


def own_session(session: Session, actor: Actor, session_id: str | None) -> DraftSession:
    row = session.get(DraftSession, session_id) if session_id else None
    if row is None or row.user_id != actor.id:
        raise ReadingError(403, "no approval session of yours with that ID", "session")
    return row


def record(
    session: Session,
    actor: Actor,
    batch: DraftBatch,
    items: list[DraftItem],
    session_id: str | None,
    lang: str,
) -> int:
    """Record that ``actor`` opened the ``lang`` view of these drafts."""
    if lang not in LANGS:
        raise ReadingError(422, f"unknown language {lang}", "lang")
    own = own_session(session, actor, session_id)
    at = now()
    count = 0
    for item in items:
        if item.batch_id != batch.id or item.kind not in NEEDS_READING:
            continue
        if item.status in ("approved", "rejected"):
            continue
        session.add(DraftView(session_id=own.id, item_id=item.id, lang=lang, viewed_at=at))
        count += 1
    session.flush()
    return count


def read_times(session: Session, item: DraftItem, session_id: str | None) -> dict[str, Any]:
    """Latest view per language in this session that still counts (None if none)."""
    out: dict[str, Any] = {lang: None for lang in LANGS}
    if not session_id:
        return out
    rows = session.scalars(
        select(DraftView).where(
            DraftView.session_id == session_id,
            DraftView.item_id == item.id,
            DraftView.viewed_at >= item.changed_at,
        )
    )
    for row in rows:
        current = out[row.lang]
        if current is None or row.viewed_at > current:
            out[row.lang] = row.viewed_at
    return {lang: (t.isoformat() if t else None) for lang, t in out.items()}


def require_both(
    session: Session, actor: Actor, item: DraftItem, session_id: str | None
) -> dict[str, Any] | None:
    """Raise unless both languages were opened in the approver's session since the last
    change; return the evidence for the approval record (None if no wording to read)."""
    if item.kind not in NEEDS_READING:
        return None
    if not session_id:
        raise ReadingError(
            409, "open the draft in English and in French before approving", "not-read"
        )
    own = own_session(session, actor, session_id)
    times = read_times(session, item, own.id)
    missing = [lang for lang in LANGS if times[lang] is None]
    if missing:
        raise ReadingError(
            409,
            f"not opened in this session since the draft last changed: {', '.join(missing)}",
            "not-read",
        )
    return {"session": own.id, "opened": times}
