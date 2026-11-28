"""Server-side web sessions: the cookie holds a random token, the database its hash.

Idle timeout 30 minutes, absolute 8 hours (PLACEHOLDER values). Signing out ends the
session at once; an ended or expired session is never accepted again.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy.orm import Session

from control_centre.models import WebSession
from govhub_shared.auth import Principal

COOKIE: Final = "govhub_session"
IDLE: Final = timedelta(minutes=30)  # PLACEHOLDER
ABSOLUTE: Final = timedelta(hours=8)  # PLACEHOLDER


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", "replace")).hexdigest()


def now() -> datetime:
    return datetime.now(UTC)


def start(session: Session, principal: Principal, mode: str) -> str:
    token = secrets.token_urlsafe(32)
    at = now()
    session.add(WebSession(
        token_hash=_hash(token), mode=mode,
        principal={"sub": principal.id, **principal.claims()},
        created_at=at, last_seen=at,
    ))  # fmt: skip
    session.commit()
    return token


def load(session: Session, token: str | None, mode: str) -> Principal | None:
    if not token:
        return None
    row = session.get(WebSession, _hash(token))
    at = now()
    if (row is None or row.ended_at is not None or row.mode != mode
            or at - row.created_at > ABSOLUTE or at - row.last_seen > IDLE):  # fmt: skip
        return None
    row.last_seen = at
    session.commit()
    return Principal.from_claims(row.principal)


def end(session: Session, token: str | None) -> None:
    if not token:
        return
    row = session.get(WebSession, _hash(token))
    if row is not None and row.ended_at is None:
        row.ended_at = now()
        session.commit()
