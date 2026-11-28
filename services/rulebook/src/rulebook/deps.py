"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from rulebook.db import get_session

LangParam = Annotated[Literal["en", "fr"], Query(description="Catalog language")]


def current_user() -> str:
    """Placeholder identity.

    TODO(control-centre): replace with OIDC (Entra ID compatible) authentication and
    central role checks. Milestone 1 has no authentication.
    """
    return "anonymous"


User = Annotated[str, Depends(current_user)]


def transaction(session: Annotated[Session, Depends(get_session)]) -> Iterator[Session]:
    """A session that commits on success and rolls back on any error."""
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise


# scope="function": commit when the endpoint returns, BEFORE the response is sent. With the
# default ("request") the commit ran after the client already had its 201, so a fast next
# request could miss the row (seen in CI: a second POST /catalogs hit a duplicate name).
Tx = Annotated[Session, Depends(transaction, scope="function")]
