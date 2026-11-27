"""Screen 4: decision log, verification and the external checkpoints."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from control_centre.web import BackendsDep, LangDep, render

router = APIRouter()
SHOWN = 200  # newest records shown on the page; the export has them all


def parse_export(text: str) -> list[dict[str, Any]]:
    """Records of the JSON Lines export, newest first, with their hashes."""
    records = []
    for line in text.splitlines():
        if line.strip():
            entry = json.loads(line)
            record = json.loads(entry["record"])
            record["record-hash"] = entry["record_hash"]
            records.append(record)
    return sorted(records, key=lambda r: int(r["seq"]), reverse=True)


def checkpoint_state(source: dict[str, Any]) -> str:
    """in-step, behind, ahead (records missing from the database), none or unavailable."""
    if source.get("available") is False:
        return "unavailable"
    behind = source.get("behind_database")
    if behind is None:
        return "none"
    if behind < 0:
        return "ahead"
    return "in-step" if behind == 0 else "behind"


@router.get("/{lang}/decision-log", response_class=HTMLResponse)
def decision_log(
    request: Request,
    lang: LangDep,
    backends: BackendsDep,
    verify: bool = False,
    trust: Annotated[list[str], Query()] = [],  # noqa: B006 - FastAPI query default
) -> HTMLResponse:
    records = parse_export(backends.desk.text("/decision-log/export"))
    status = backends.desk.get("/decision-log/checkpoint-status")
    sources = {name: checkpoint_state(status[name]) for name in ("file", "servicenow")}
    trusted = [s for s in trust if s in ("file", "servicenow")]
    result = None
    if verify:
        result = backends.desk.get("/decision-log/verify", trust=trusted)
    return render(
        request,
        lang,
        "decision-log.html",
        title_key="log.title",
        screen="log",
        records=records[:SHOWN],
        total=len(records),
        status=status,
        sources=sources,
        result=result,
        trusted=trusted if verify else ["file", "servicenow"],
    )
