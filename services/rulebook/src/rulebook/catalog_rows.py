"""Golden-set rows <-> stored catalog versions, and draft change sets.

Publishing approved drafts must give exactly the catalog that the golden-set CSV gives
once the same change set is applied to it (``rulebook apply-drafts``). So the rulebook
rebuilds golden-set rows from the stored base version (both languages), applies the
change set, and builds the new version with the importer's own ``build_catalog``. A test
proves both paths give identical documents.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from pathlib import Path
from typing import Any

from govhub_shared import OSCAL_NS
from rulebook.golden import (
    LANGS,
    CatalogText,
    GoldenRow,
    GoldenSettings,
    GroupTitle,
    Lang,
    build_catalog,
)

FORMAT = "govhub-draft-change-set/1"


def _hub(props: list[dict[str, Any]], name: str) -> list[str]:
    return [p["value"] for p in props if p["name"] == name and p.get("ns") == OSCAL_NS]


def _one(props: list[dict[str, Any]], name: str) -> str | None:
    values = _hub(props, name)
    return values[0] if values else None


def _part(control: dict[str, Any], name: str) -> str | None:
    for part in control.get("parts", []):
        if part["name"] == name:
            return str(part["prose"])
    return None


def rows_from_catalogs(
    docs: dict[Lang, dict[str, Any]],
) -> tuple[list[GoldenRow], dict[str, GroupTitle], GoldenSettings, str]:
    """Golden-set rows, groups and settings that rebuild these documents exactly."""
    meta = {lang: docs[lang]["catalog"]["metadata"] for lang in LANGS}
    props = meta["en"]["props"]
    groups: dict[str, GroupTitle] = {}
    rows: list[GoldenRow] = []
    prefix = docs["en"]["catalog"]["groups"][0]["id"].rsplit("-", 1)[0]
    fr_controls = {
        c["id"]: c for g in docs["fr"]["catalog"]["groups"] for c in g.get("controls", [])
    }
    fr_groups = {g["id"]: g for g in docs["fr"]["catalog"]["groups"]}
    for group in docs["en"]["catalog"]["groups"]:
        section = next(p["value"] for p in group.get("props", []) if p["name"] == "label")
        groups[section] = GroupTitle(
            section=section,
            title={"en": group["title"], "fr": fr_groups[group["id"]]["title"]},
            group_id=None if group["id"] == f"{prefix}-{section}" else group["id"],
        )
        for control in group.get("controls", []):
            cprops = control.get("props", [])
            fr = fr_controls[control["id"]]
            frprops = fr.get("props", [])
            rows.append(
                GoldenRow(
                    line=len(rows) + 2,
                    check_id=control["id"],
                    clause=next(p["value"] for p in cprops if p["name"] == "label"),
                    group=section,
                    check_type=_one(cprops, "check-type") or "judgment",
                    numbering_status=_one(cprops, "numbering-status") or "confirmed",
                    numbering_note=_one(cprops, "numbering-note"),
                    statement={
                        "en": _part(control, "statement") or "",
                        "fr": _part(fr, "statement") or "",
                    },
                    reviewed={
                        "en": _one(cprops, "review-status") == "reviewed",
                        "fr": _one(frprops, "review-status") == "reviewed",
                    },
                    guidance={"en": _part(control, "guidance"), "fr": _part(fr, "guidance")},
                    objective={
                        "en": _part(control, "assessment-objective"),
                        "fr": _part(fr, "assessment-objective"),
                    },
                    source_clauses=tuple(_hub(cprops, "source-clause")),
                    obligation=_one(cprops, "obligation"),
                    status="withdrawn"
                    if any(
                        p["name"] == "status" and p["value"] == "withdrawn" and "ns" not in p
                        for p in cprops
                    )
                    else "active",
                    drafted_by=_one(cprops, "drafted-by"),
                    approved_by=_one(cprops, "approved-by"),
                    approval_record=_one(cprops, "approval-record"),
                )
            )
    hashes: dict[Lang, str] = {}
    for lang in LANGS:
        for res in docs[lang]["catalog"].get("back-matter", {}).get("resources", []):
            for rlink in res.get("rlinks", []):
                for h in rlink.get("hashes", []):
                    hashes[lang] = h["value"]

    def text(lang: Lang) -> CatalogText:
        m = meta[lang]
        return CatalogText(
            document=_one(m["props"], "source-document") or "",
            href=m["links"][0]["href"],
            title=m["title"],
            remarks=m["remarks"].replace("{", "{{").replace("}", "}}"),
        )

    settings = GoldenSettings(
        path=Path("stored-catalog"),
        source_date=datetime.fromisoformat(meta["en"]["last-modified"]),
        version=meta["en"]["version"],
        group_prefix=prefix,
        source_instrument=_one(props, "source-instrument") or "",
        source_version=_one(props, "source-version") or "",
        source_meta_dir=Path("/nonexistent"),
        statement_status=_one(props, "statement-status") or "",
        catalog={lang: text(lang) for lang in LANGS},
        source_hashes=hashes or None,
        approval_log_head=_one(props, "approval-log-head"),
    )
    return rows, groups, settings, _one(props, "source-file") or ""


def apply_change_set(
    rows: list[GoldenRow],
    groups: dict[str, GroupTitle],
    settings: GoldenSettings,
    change_set: dict[str, Any],
) -> tuple[list[GoldenRow], dict[str, GroupTitle], GoldenSettings]:
    by_id = {r.check_id: i for i, r in enumerate(rows)}
    rows = list(rows)
    groups = dict(groups)
    for gid, group in change_set.get("new_groups", {}).items():
        groups[group["key"]] = GroupTitle(group["key"], dict(group["title"]), gid)
    for change in change_set["changes"]:
        kind, cid = change["kind"], change["control_id"]
        provenance = {
            "drafted_by": change.get("drafted_by"),
            "approved_by": change.get("approved_by"),
            "approval_record": change.get("approval_record"),
        }
        if kind == "new":
            rows.append(
                GoldenRow(
                    line=len(rows) + 2,
                    check_id=cid,
                    clause=change["clause"],
                    group=change["group"],
                    check_type=change["check_type"],
                    numbering_status="confirmed",
                    numbering_note=None,
                    statement=dict(change["statement"]),
                    reviewed={"en": False, "fr": False},
                    guidance=dict(change.get("guidance") or {"en": None, "fr": None}),
                    objective=dict(change.get("objective") or {"en": None, "fr": None}),
                    source_clauses=tuple(change["source_clauses"]),
                    obligation=change.get("obligation"),
                    **provenance,
                )
            )
            continue
        row = rows[by_id[cid]]
        updates: dict[str, Any] = dict(provenance)
        if kind == "retire":
            updates["status"] = "withdrawn"
        else:  # edit | reference
            updates["source_clauses"] = tuple(change["source_clauses"])
        if kind == "edit":
            if change.get("obligation"):
                updates["obligation"] = change["obligation"]
            if not change.get("no_change"):
                updates["statement"] = dict(change["statement"])
                updates["reviewed"] = {"en": False, "fr": False}  # new wording: not agreed yet
                if change.get("check_type"):
                    updates["check_type"] = change["check_type"]
                for name in ("guidance", "objective"):
                    value = change.get(name) or {}
                    if any(value.get(lang) for lang in LANGS):
                        updates[name] = dict(value)
        rows[by_id[cid]] = dataclasses.replace(row, **updates)
    settings = dataclasses.replace(
        settings,
        version=change_set["new_version"],
        source_date=datetime.fromisoformat(change_set["source_date"]),
        source_version=change_set["source_version"],
        source_hashes=change_set.get("source_hashes") or None,
        approval_log_head=change_set.get("approval_log_head"),
    )
    return rows, groups, settings


def build(
    rows: list[GoldenRow],
    groups: dict[str, GroupTitle],
    settings: GoldenSettings,
    name: str,
    source_name: str,
) -> dict[Lang, dict[str, Any]]:
    return {
        lang: build_catalog(
            rows,
            groups,
            lang,
            name=name,
            version=settings.version,
            source_name=source_name,
            last_modified=settings.source_date,
            settings=settings,
        )
        for lang in LANGS
    }
