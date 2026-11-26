"""Clause diff endpoint for source documents."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from rulebook.db import get_session
from rulebook.sources import store as source_store
from rulebook.sources.diff import METHOD, SPLIT_THRESHOLD, THRESHOLD, cross_check, diff_sources

router = APIRouter(prefix="/sources", tags=["sources"])

FromQ = Annotated[str, Query(alias="from", description="Base version (YYYY-MM-DD)")]
ToQ = Annotated[str, Query(alias="to", description="Target version (YYYY-MM-DD)")]
LangQ = Annotated[Literal["en", "fr", "both"], Query(description="Language(s) to diff")]
TextQ = Annotated[bool, Query(description="Include old/new clause text in each pair")]


def source_diff(
    session: Session,
    instrument: str,
    from_version: str,
    to_version: str,
    lang: str = "both",
    include_text: bool = True,
) -> dict[str, Any]:
    langs = ["en", "fr"] if lang == "both" else [lang]
    diffs = {
        code: diff_sources(
            source_store.get_source(session, instrument, from_version, code),
            source_store.get_source(session, instrument, to_version, code),
            include_text=include_text,
        )
        for code in langs
    }
    out: dict[str, Any] = {
        "instrument": instrument,
        "from_version": from_version,
        "to_version": to_version,
        "method": METHOD,
        "threshold": THRESHOLD,
        "split_threshold": SPLIT_THRESHOLD,
    }
    for code, diff in diffs.items():
        out[code] = diff.model_dump(mode="json")
    if len(diffs) == 2:
        out["cross_check"] = [
            d.model_dump(mode="json") for d in cross_check(diffs["en"], diffs["fr"])
        ]
    return out


def _endpoint(
    instrument: str,
    session: Annotated[Session, Depends(get_session)],
    from_version: FromQ,
    to_version: ToQ,
    lang: LangQ = "both",
    include_text: TextQ = True,
) -> dict[str, Any]:
    """Clause-by-clause diff: pairs (with method, score and flags), added, removed, splits,
    merges; with ``lang=both`` also an EN/FR cross-check. Reports the method and
    thresholds used."""
    return source_diff(session, instrument, from_version, to_version, lang, include_text)


router.add_api_route("/{instrument}/diff", _endpoint, methods=["GET"])
router.add_api_route("/{instrument}/diff", _endpoint, methods=["POST"], name="source_diff_post")
