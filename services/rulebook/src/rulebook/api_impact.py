"""Impact report endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from pydantic import ValidationError
from sqlalchemy.orm import Session

from rulebook.config import get_settings
from rulebook.db import get_session
from rulebook.impact import ImpactRequest, build_report, load_due_dates
from rulebook.store import InvalidCatalogError

router = APIRouter(tags=["impact"])


@router.post("/impact-reports")
def impact_report(
    session: Annotated[Session, Depends(get_session)],
    payload: Annotated[
        dict[str, Any],
        Body(
            description=(
                '{"catalog", "catalog_version", "source": {"instrument", "from", "to"}, '
                '"catalog_change": {"from", "to"}, "as_of", "lang", "tenant"}'
            )
        ),
    ],
) -> dict[str, Any]:
    """Affected controls, systems ranked by impact level, the reassessment tasks that would
    be created (ServiceNow-shaped JSON, not sent), and rulebook maintenance items.
    Deterministic for the same inputs. Not stored yet (TODO(review-desk))."""
    try:
        request = ImpactRequest.model_validate(payload)
    except ValidationError as exc:
        raise InvalidCatalogError(
            "invalid impact report request",
            [f"{'.'.join(map(str, e['loc'])) or 'request'}: {e['msg']}" for e in exc.errors()],
        ) from exc
    due_dates = load_due_dates(Path(get_settings().due_dates_path))
    return build_report(session, request, due_dates)
