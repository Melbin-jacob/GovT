"""Screen 5: AI-system inventory, with the gaps in each record."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from control_centre.web import BackendsDep, LangDep, render

router = APIRouter()


@router.get("/{lang}/inventory", response_class=HTMLResponse)
def inventory(request: Request, lang: LangDep, backends: BackendsDep) -> HTMLResponse:
    data = backends.rulebook.get("/inventory")
    systems = sorted(data["systems"], key=lambda s: (not s["data_gaps"], s["system_id"]))
    return render(
        request,
        lang,
        "inventory.html",
        title_key="inventory.title",
        screen="inventory",
        inventory=data,
        systems=systems,
        with_gaps=sum(1 for s in systems if s["data_gaps"]),
    )
