"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from govhub_shared import tenancy
from govhub_shared.auth import (
    AUDITOR,
    GOVERNANCE_OFFICER,
    REVIEWER,
    SYSTEM_OWNER,
    TENANT_ADMIN,
    Principal,
)
from govhub_shared.auth.web import require
from review_desk.db import get_session
from review_desk.identity import visible_tenants

# The request's session, bound to the caller's tenants (row-level security).
scoped_session = tenancy.tenant_session(get_session, visible_tenants)


def transaction(session: Annotated[Session, Depends(scoped_session)]) -> Iterator[Session]:
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
ReadSession = Annotated[Session, Depends(scoped_session)]
# Who may call what (docs/access-matrix.md); tenant checks happen per finding.
TenantReader = Annotated[
    Principal, Depends(require(SYSTEM_OWNER, REVIEWER, TENANT_ADMIN, AUDITOR,
                               services=("assessment-engine", "control-centre-service")))
]  # fmt: skip
ReviewerAnywhere = Annotated[Principal, Depends(require(REVIEWER))]
EngineOnly = Annotated[Principal, Depends(require(services=("assessment-engine",)))]
IntakeCaller = Annotated[
    Principal,
    Depends(require(GOVERNANCE_OFFICER, services=("connector-hub", "control-centre-service"))),
]
LogReader = Annotated[Principal, Depends(require(REVIEWER, TENANT_ADMIN, AUDITOR))]
LogExporter = Annotated[Principal, Depends(require(REVIEWER, TENANT_ADMIN, AUDITOR))]
ForecastReader = Annotated[
    Principal, Depends(require(REVIEWER, TENANT_ADMIN, AUDITOR, GOVERNANCE_OFFICER))
]
