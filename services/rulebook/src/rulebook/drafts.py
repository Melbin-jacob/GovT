"""Rulebook drafts: from a source change to proposed control changes (plain code).

A batch covers one source change (instrument ``from`` -> ``to``) against the catalog
version whose source-clause links use the ``from`` numbering. The work is planned from
the clause diff (reference language: English when stored, as in impact reports):

- changed clause (text changed, maybe renumbered, maybe obligation changed) -> an
  ``edit`` item per linked control (the model proposes an edit or "no change needed");
  a changed clause no control links to -> a ``new`` item;
- split / merge -> an ``edit`` item per linked control, now linked to all new clauses;
- added clause -> a ``new`` item (proposed ID ``<prefix>-C<nnn>``, never reused);
- removed clause -> a ``retire`` item per linked control (no model);
- renumbered only -> a ``reference`` item per linked control (no model, no wording).

New sections of the new numbering get a neutral group ``<prefix>-G<nn>`` titled from
the official headings. Nothing is approved here: see approval.py.
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from govhub_shared.oscal import ControlView, iter_controls
from rulebook import approval_log, store
from rulebook.models import Catalog, CatalogVersion, DraftBatch, DraftItem
from rulebook.sources import store as source_store
from rulebook.sources.diff import diff_sources
from rulebook.sources.model import SourceDocument

LANGS = ("en", "fr")
_C_ID = re.compile(r"^(?P<prefix>.+)-C(?P<n>\d+)$")
_G_ID = re.compile(r"^(?P<prefix>.+)-G(?P<n>\d+)$")


class DraftPlanError(ValueError):
    pass


def _source_clauses(control: ControlView) -> list[str]:
    from govhub_shared import OSCAL_NS

    return [p.value for p in control.props if p.name == "source-clause" and p.ns == OSCAL_NS]


def _meta(doc: dict[str, Any], name: str) -> str | None:
    from govhub_shared import OSCAL_NS

    for prop in doc["catalog"]["metadata"].get("props", []):
        if prop.get("name") == name and prop.get("ns") == OSCAL_NS:
            return str(prop["value"])
    return None


def _all_ids(session: Session, catalog: str) -> tuple[set[str], set[str]]:
    """Every control and group ID ever used in any stored version of the catalog."""
    controls: set[str] = set()
    groups: set[str] = set()
    rows = session.scalars(select(CatalogVersion).join(Catalog).where(Catalog.name == catalog))
    for row in rows:
        for group in row.document["catalog"].get("groups", []):
            groups.add(group["id"])
        controls.update(c.id for c in iter_controls(row.document))
    for batch in session.scalars(select(DraftBatch).where(DraftBatch.catalog == catalog)):
        groups.update(batch.plan.get("new_groups", {}))
        for item in session.scalars(select(DraftItem).where(DraftItem.batch_id == batch.id)):
            if item.proposed_id:
                controls.add(item.proposed_id)
    return controls, groups


def _prefix(ids: list[str]) -> str:
    counts = Counter(i.split("-", 1)[0] for i in ids if "-" in i)
    if not counts:
        raise DraftPlanError("cannot tell the catalog's ID prefix")
    return counts.most_common(1)[0][0]


def _next(pattern: re.Pattern[str], used: set[str], prefix: str) -> int:
    numbers = [int(m["n"]) for i in used if (m := pattern.match(i)) and m["prefix"] == prefix]
    return max(numbers, default=0) + 1


def _heading(doc: SourceDocument, section: str) -> str:
    for clause in doc.clauses:
        if clause.section == section and clause.heading:
            return re.sub(rf"^\s*{re.escape(section)}\s*", "", clause.heading).strip()
    return section


def _texts(doc: SourceDocument) -> dict[str, str]:
    return {c.number: c.text or "" for c in doc.clauses}


def plan_batch(
    session: Session,
    *,
    catalog: str,
    version: str,
    instrument: str,
    from_version: str,
    to_version: str,
    created_by: str,
) -> DraftBatch:
    docs = {lang: store.get_version(session, catalog, version, lang).document for lang in LANGS}
    linked = _meta(docs["en"], "source-version")
    if _meta(docs["en"], "source-instrument") != instrument or linked != from_version:
        raise DraftPlanError(
            f"{catalog} {version} links to {_meta(docs['en'], 'source-instrument')} "
            f"{linked}; drafting needs a catalog linked to {instrument} {from_version}"
        )
    sources = {
        (lang, side): source_store.get_source(session, instrument, v, lang)
        for lang in LANGS
        for side, v in (("old", from_version), ("new", to_version))
    }
    diff = diff_sources(sources[("en", "old")], sources[("en", "new")], include_text=False)

    controls = [c for c in iter_controls(docs["en"]) if c.prop("status") != "withdrawn"]
    by_clause: dict[str, list[ControlView]] = defaultdict(list)
    for control in controls:
        for clause in _source_clauses(control):
            by_clause[clause].append(control)
    group_of = {c.id: c.group_id for c in controls}

    items: list[dict[str, Any]] = []

    def add(
        kind: str, old: list[str], new: list[str], target: str | None, flags: list[str]
    ) -> None:
        items.append(
            {"kind": kind, "old": old, "new": new, "target": target, "flags": sorted(set(flags))}
        )

    new_links: dict[str, list[str]] = {}  # control -> its links in the new numbering
    for pair in diff.pairs:
        if "split" in pair.flags or "merge" in pair.flags:
            continue
        targets = by_clause.get(pair.old, [])
        if "text-changed" in pair.flags:
            flags = [f for f in pair.flags if f in ("obligation-change", "renumbered")]
            if not targets:
                add("new", [pair.old], [pair.new], None, [*flags, "unmapped-clause"])
            for control in targets:
                add("edit", [pair.old], [pair.new], control.id, flags)
                new_links.setdefault(control.id, []).append(pair.new)
        else:
            for control in targets:
                new_links.setdefault(control.id, []).append(pair.new)
                if pair.old != pair.new:
                    add("reference", [pair.old], [pair.new], control.id, ["renumbered"])
    for split in diff.splits:
        for control in by_clause.get(split.old, []):
            add("edit", [split.old], list(split.into), control.id, ["split", *split.flags])
            new_links.setdefault(control.id, []).extend(split.into)
    for merge in diff.merges:
        for old in merge.olds:
            for control in by_clause.get(old, []):
                if not any(i["target"] == control.id and i["kind"] == "edit" for i in items):
                    add("edit", list(merge.olds), [merge.into], control.id, ["merge"])
                new_links.setdefault(control.id, []).append(merge.into)
    for old in diff.removed:
        for control in by_clause.get(old, []):
            add("retire", [old], [], control.id, ["removed"])
    for new in diff.added:
        add("new", [], [new], None, ["added"])

    # IDs and groups for new controls (never reused, person confirms or edits).
    used_controls, used_groups = _all_ids(session, catalog)
    prefix = _prefix([c.id for c in controls])
    group_prefix = _prefix(
        [g for g in used_groups if not g.startswith(f"{prefix}-")] or list(used_groups)
    )
    next_c = _next(_C_ID, used_controls, prefix)
    next_g = _next(_G_ID, used_groups, group_prefix)
    section_groups: dict[str, set[str]] = defaultdict(set)
    for control_id, links in new_links.items():
        for clause in links:
            section_groups[clause.rsplit(".", 1)[0]].add(group_of[control_id] or "")
    new_groups: dict[str, dict[str, Any]] = {}
    group_by_section: dict[str, str] = {}
    for item in items:
        if item["kind"] != "new":
            continue
        item["proposed_id"] = f"{prefix}-C{next_c:03d}"
        next_c += 1
        section = item["new"][0].rsplit(".", 1)[0]
        existing = section_groups.get(section, set()) - {""}
        if len(existing) == 1:
            item["group"] = next(iter(existing))
            continue
        if section not in group_by_section:
            gid = f"{group_prefix}-G{next_g:02d}"
            next_g += 1
            group_by_section[section] = gid
            new_groups[gid] = {
                "key": f"{section}@{to_version}",
                "section": section,
                "title": {lang: _heading(sources[(lang, "new")], section) for lang in LANGS},
            }
        item["group"] = group_by_section[section]

    involved_old = sorted({n for i in items for n in i["old"]})
    involved_new = sorted({n for i in items for n in i["new"]})
    texts = {
        lang: {
            "old": {n: _texts(sources[(lang, "old")]).get(n, "") for n in involved_old},
            "new": {n: _texts(sources[(lang, "new")]).get(n, "") for n in involved_new},
        }
        for lang in LANGS
    }
    latest = store.latest_version(session, catalog, "en")
    major, minor, _ = (int(x) for x in latest.split("."))
    batch = DraftBatch(
        id=str(uuid.uuid4()),
        catalog=catalog,
        base_version=version,
        instrument=instrument,
        from_version=from_version,
        to_version=to_version,
        status="open",
        new_version=None,
        plan={
            "id_prefix": prefix,
            "proposed_version": f"{major}.{minor + 1}.0",
            "new_groups": new_groups,
            "clauses": texts,
            "new_links": new_links,
            "diff_summary": diff.summary,
        },
        created_by=created_by,
        created_at=datetime.now(UTC),
    )
    session.add(batch)
    for seq, item in enumerate(items, start=1):
        needs_model = item["kind"] in ("edit", "new")
        session.add(
            DraftItem(
                id=str(uuid.uuid4()),
                batch_id=batch.id,
                seq=seq,
                kind=item["kind"],
                old_clauses=item["old"],
                new_clauses=item["new"],
                target_control=item["target"],
                proposed_id=item.get("proposed_id"),
                group_key=item.get("group"),
                flags=item["flags"],
                drafts={lang: {"status": "pending" if needs_model else "ready"} for lang in LANGS},
                status="pending" if needs_model else "ready",
            )
        )
    session.flush()
    approval_log.append(
        session,
        {
            "action": "batch-created",
            "batch": batch.id,
            "catalog": catalog,
            "base-version": version,
            "source-change": f"{instrument} {from_version} -> {to_version}",
            "items": [
                {k: i.get(k) for k in ("kind", "old", "new", "target", "proposed_id")}
                for i in items
            ],
            "by": created_by,
            "timestamp": batch.created_at.isoformat(),
        },
        batch_id=batch.id,
    )
    return batch


def items_of(session: Session, batch_id: str) -> list[DraftItem]:
    return list(
        session.scalars(
            select(DraftItem).where(DraftItem.batch_id == batch_id).order_by(DraftItem.seq)
        )
    )


def item_view(item: DraftItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "seq": item.seq,
        "kind": item.kind,
        "old_clauses": item.old_clauses,
        "new_clauses": item.new_clauses,
        "target_control": item.target_control,
        "proposed_id": item.proposed_id,
        "group": item.group_key,
        "flags": item.flags,
        "drafts": item.drafts,
        "status": item.status,
        "last_edited_by": item.last_edited_by,
        "decided_by": item.decided_by,
    }


def batch_view(session: Session, batch: DraftBatch) -> dict[str, Any]:
    docs = {
        lang: store.get_version(session, batch.catalog, batch.base_version, lang).document
        for lang in LANGS
    }
    items = items_of(session, batch.id)
    current: dict[str, dict[str, Any]] = {}
    for item in items:
        if item.target_control:
            current[item.target_control] = {
                lang: _control_text(docs[lang], item.target_control) for lang in LANGS
            }
    return {
        "id": batch.id,
        "catalog": batch.catalog,
        "base_version": batch.base_version,
        "source_change": {
            "instrument": batch.instrument,
            "from": batch.from_version,
            "to": batch.to_version,
        },
        "status": batch.status,
        "new_version": batch.new_version,
        "plan": batch.plan,
        "current_controls": current,
        "items": [item_view(i) for i in items],
        "created_by": batch.created_by,
        "created_at": batch.created_at.isoformat(),
    }


def _control_text(doc: dict[str, Any], control_id: str) -> dict[str, Any]:
    for control in iter_controls(doc):
        if control.id == control_id:
            return {
                "statement": control.part("statement"),
                "guidance": control.part("guidance"),
                "objective": control.part("assessment-objective"),
                "check_type": control.hub_prop("check-type"),
                "obligation": control.hub_prop("obligation"),
                "label": control.prop("label"),
                "source_clauses": _source_clauses(control),
            }
    return {}
