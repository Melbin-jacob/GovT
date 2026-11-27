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


Tx = Annotated[Session, Depends(transaction)]
