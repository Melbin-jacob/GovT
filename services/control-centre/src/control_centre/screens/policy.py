"""Screen 1: policy change. Side-by-side clause diff between two source versions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from control_centre.web import BackendsDep, LangDep, SettingsDep, render

router = APIRouter()

# Display order of the flags on a row.
FLAG_ORDER = [
    "obligation-change",
    "split",
    "merge",
    "renumbered",
    "text-changed",
    "added",
    "removed",
    "unchanged",
]


@dataclass
class Row:
    old: list[tuple[str, str]] = field(default_factory=list)
    new: list[tuple[str, str]] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    score: float | None = None
    obligations_before: list[str] | None = None
    obligations_after: list[str] | None = None

    @property
    def changed(self) -> bool:
        return self.flags != ["unchanged"]


def _ordered(flags: set[str]) -> list[str]:
    return [f for f in FLAG_ORDER if f in flags]


def build_rows(
    diff: dict[str, Any], old_text: dict[str, str], new_text: dict[str, str]
) -> list[Row]:
    """Rows for the side-by-side table: matched pairs (a split or merge shown as one row
    with all its clauses), then removed and added clauses."""
    splits = {s["old"]: s for s in diff["splits"]}
    merges = {m["into"]: m for m in diff["merges"]}
    rows: list[Row] = []
    for pair in diff["pairs"]:
        flags = set(pair["flags"])
        if "split" in flags and pair["old"] in splits:
            into = splits[pair["old"]]["into"]
            row = Row(
                old=[(pair["old"], old_text.get(pair["old"], ""))],
                new=[(n, new_text.get(n, "")) for n in into],
            )
        elif "merge" in flags and pair["new"] in merges:
            olds = merges[pair["new"]]["olds"]
            row = Row(
                old=[(o, old_text.get(o, "")) for o in olds],
                new=[(pair["new"], new_text.get(pair["new"], ""))],
            )
        else:
            row = Row(
                old=[(pair["old"], pair.get("old_text") or old_text.get(pair["old"], ""))],
                new=[(pair["new"], pair.get("new_text") or new_text.get(pair["new"], ""))],
            )
        row.flags = _ordered(flags) or ["unchanged"]
        row.score = pair["score"]
        row.obligations_before = pair.get("obligations_before")
        row.obligations_after = pair.get("obligations_after")
        rows.append(row)
    shown_old = {n for r in rows for n, _ in r.old}
    shown_new = {n for r in rows for n, _ in r.new}
    rows += [
        Row(old=[(n, old_text.get(n, ""))], flags=["removed"])
        for n in diff["removed"]
        if n not in shown_old
    ]
    rows += [
        Row(new=[(n, new_text.get(n, ""))], flags=["added"])
        for n in diff["added"]
        if n not in shown_new
    ]
    return rows


def _clauses(doc: dict[str, Any]) -> dict[str, str]:
    return {c["number"]: c["text"] for c in doc.get("clauses", [])}


@router.get("/{lang}/policy-change", response_class=HTMLResponse)
def policy_change(
    request: Request,
    lang: LangDep,
    backends: BackendsDep,
    settings: SettingsDep,
    instrument: str | None = None,
    from_version: Annotated[str | None, Query(alias="from")] = None,
    to_version: Annotated[str | None, Query(alias="to")] = None,
) -> HTMLResponse:
    sources = backends.rulebook.get("/sources")
    by_name = {s["instrument"]: s for s in sources}
    if instrument not in by_name:
        instrument = (
            settings.default_instrument
            if settings.default_instrument in by_name
            else next(iter(by_name), None)
        )
    context: dict[str, Any] = {"sources": sources, "instrument": instrument, "rows": None}
    if instrument is not None:
        source = by_name[instrument]
        versions = [v["version"] for v in source["versions"] if lang in v["langs"]]
        from_version = from_version if from_version in versions else (versions or [None])[0]
        to_version = to_version if to_version in versions else (versions or [None])[-1]
        context.update(
            source=source,
            versions=versions,
            from_version=from_version,
            to_version=to_version,
            synthetic=bool(source.get("synthetic")) or settings.synthetic_data,
        )
        if from_version and to_version and from_version != to_version:
            diff = backends.rulebook.get(
                f"/sources/{instrument}/diff",
                **{"from": from_version, "to": to_version, "lang": lang, "include_text": "true"},
            )[lang]
            old = backends.rulebook.get(f"/sources/{instrument}/versions/{from_version}", lang=lang)
            new = backends.rulebook.get(f"/sources/{instrument}/versions/{to_version}", lang=lang)
            context.update(
                diff=diff,
                old_doc=old,
                new_doc=new,
                rows=build_rows(diff, _clauses(old), _clauses(new)),
            )
    return render(
        request,
        lang,
        "policy-change.html",
        title_key="policy.title",
        screen="policy",
        **context,
    )
