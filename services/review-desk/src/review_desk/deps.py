"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from review_desk.db import get_session
from review_desk.identity import Reviewer, authorized_reviewer, current_reviewer


def transaction(session: Annotated[Session, Depends(get_session)]) -> Iterator[Session]:
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise


Tx = Annotated[Session, Depends(transaction)]
ReadSession = Annotated[Session, Depends(get_session)]
AnyUser = Annotated[Reviewer, Depends(current_reviewer)]
AuthorizedReviewer = Annotated[Reviewer, Depends(authorized_reviewer)]
