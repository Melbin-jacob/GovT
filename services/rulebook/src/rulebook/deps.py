"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated, Literal

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from govhub_shared import tenancy
from govhub_shared.auth import Principal
from govhub_shared.auth.web import principal
from rulebook.access import visible_tenants
from rulebook.db import get_session

LangParam = Annotated[Literal["en", "fr"], Query(description="Catalog language")]


def current_user(who: Annotated[Principal, Depends(principal)]) -> str:
    """The caller's ID (from the internal token), recorded as ``created_by``."""
    return who.id


User = Annotated[str, Depends(current_user)]


# The request's session, bound to the caller's tenants (row-level security).
scoped_session = tenancy.tenant_session(get_session, visible_tenants)
ScopedSession = Annotated[Session, Depends(scoped_session)]


def transaction(session: ScopedSession) -> Iterator[Session]:
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
