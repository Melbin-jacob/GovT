"""Screen 2: impact report. Affected controls, ranked systems, tasks, forecast."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from control_centre.backends import BackendError, Backends
from control_centre.config import Settings
from control_centre.web import BackendsDep, LangDep, SettingsDep, render

router = APIRouter()


def servicenow_numbers(backends: Backends) -> dict[str, str] | None:
    """correlation ID -> task number for the hub's reassessment tasks; None if unavailable."""
    try:
        notes = backends.connector.get("/tasks/notes", type="reassessment")
    except BackendError:
        return None
    return {n["correlation_id"]: n["number"] for n in notes if n.get("correlation_id")}


def report_request(
    settings: Settings, lang: str, catalog: str, version: str, from_v: str, to_v: str, as_of: str
) -> dict[str, Any]:
    return {
        "catalog": catalog,
        "catalog_version": version,
        "source": {"instrument": settings.default_instrument, "from": from_v, "to": to_v},
        "as_of": as_of,
        "lang": lang,  # the report ID does not depend on it
    }


def catalog_request(catalog: str, from_v: str, to_v: str, as_of: str, lang: str) -> dict[str, Any]:
    return {
        "catalog": catalog,
        "catalog_change": {"from": from_v, "to": to_v},
        "as_of": as_of,
        "lang": lang,
    }


@router.get("/{lang}/impact", response_class=HTMLResponse)
def impact(
    request: Request,
    lang: LangDep,
    backends: BackendsDep,
    settings: SettingsDep,
    catalog: str | None = None,
    version: str | None = None,
    from_version: Annotated[str | None, Query(alias="from")] = None,
    to_version: Annotated[str | None, Query(alias="to")] = None,
    as_of: str | None = None,
    catalog_from: str | None = None,
    catalog_to: str | None = None,
) -> HTMLResponse:
    """A source change (default), or a catalog change (``catalog_from``/``catalog_to``,
    e.g. a version published from approved drafts)."""
    catalogs = backends.rulebook.get("/catalogs")
    names = [c["name"] for c in catalogs]
    catalog = catalog if catalog in names else settings.default_catalog
    current = next((c for c in catalogs if c["name"] == catalog), None)
    sources = {s["instrument"]: s for s in backends.rulebook.get("/sources")}
    source = sources.get(settings.default_instrument)
    source_versions = [v["version"] for v in source["versions"]] if source else []
    context: dict[str, Any] = {
        "catalogs": catalogs,
        "catalog": catalog,
        "source_versions": source_versions,
        "report": None,
    }
    if current is not None and len(source_versions) >= 2:
        versions = [v["version"] for v in current["versions"]]
        chosen = version if version in versions else str(current["latest"])
        old = str(from_version if from_version in source_versions else source_versions[0])
        new = str(to_version if to_version in source_versions else source_versions[-1])
        date = as_of or settings.default_as_of
        context.update(
            versions=versions, version=chosen, from_version=old, to_version=new, as_of=date
        )
        change = catalog_from in versions and catalog_to in versions and catalog_from != catalog_to
        if change:
            context.update(catalog_from=catalog_from, catalog_to=catalog_to)
        if change or old != new:
            body = (
                catalog_request(str(catalog), str(catalog_from), str(catalog_to), date, lang)
                if change
                else report_request(settings, lang, str(catalog), str(chosen), old, new, date)
            )
            report = backends.rulebook.post("/impact-reports", body)
            context.update(
                report=report,
                forecast=backends.desk.post("/forecast", report),
                servicenow=servicenow_numbers(backends),
            )
    return render(
        request, lang, "impact.html", title_key="impact.title", screen="impact", **context
    )
