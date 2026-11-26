"""Field-level diff between two versions of a catalog (same language)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel

from govhub_shared import OSCAL_NS
from rulebook.obligations import Lang, obligation_terms

OBLIGATION_CHANGE = "obligation-change"
LABEL_CHANGE = "label-change"
STATUS_PROP = "status"
WITHDRAWN = "withdrawn"


class FieldChange(BaseModel):
    field: str
    before: Any = None
    after: Any = None
    flags: list[str] = []
    obligations_before: list[str] | None = None
    obligations_after: list[str] | None = None


class ControlChange(BaseModel):
    id: str
    flags: list[str]
    changes: list[FieldChange]


class CatalogDiff(BaseModel):
    catalog: str
    lang: Lang
    from_version: str
    to_version: str
    added: list[str]
    retired: list[str]
    reinstated: list[str]
    removed: list[str]
    changed: list[ControlChange]
    summary: dict[str, int]


def _prop_key(prop: Mapping[str, Any]) -> str:
    ns = prop.get("ns")
    if ns is None:
        return f"prop:{prop['name']}"
    if ns == OSCAL_NS:
        return f"prop:hub:{prop['name']}"
    return f"prop:{ns}#{prop['name']}"


def _flatten_parts(parts: list[Mapping[str, Any]], prefix: str, out: dict[str, Any]) -> None:
    seen: dict[str, int] = {}
    for part in parts:
        name = str(part.get("name"))
        seen[name] = seen.get(name, 0) + 1
        key = f"{prefix}{name}" if seen[name] == 1 else f"{prefix}{name}[{part.get('id')}]"
        if "prose" in part:
            out[f"part:{key}"] = part["prose"]
        _flatten_parts(part.get("parts", []), f"{key}/", out)


def control_fields(control: Mapping[str, Any], group_id: str | None) -> dict[str, Any]:
    """Flatten a control into comparable fields."""
    fields: dict[str, Any] = {"title": control.get("title"), "group": group_id}
    if "class" in control:
        fields["class"] = control["class"]
    props: dict[str, list[str]] = {}
    for prop in control.get("props", []):
        props.setdefault(_prop_key(prop), []).append(prop["value"])
    for key, values in props.items():
        fields[key] = values[0] if len(values) == 1 else values
    for param in control.get("params", []):
        fields[f"param:{param['id']}"] = param
    if control.get("links"):
        fields["links"] = [link.get("href") for link in control["links"]]
    _flatten_parts(control.get("parts", []), "", fields)
    return fields


def index_controls(catalog_doc: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Map control id -> flattened fields, for every control in a catalog document."""
    result: dict[str, dict[str, Any]] = {}

    def walk(container: Mapping[str, Any], group_id: str | None) -> None:
        for control in container.get("controls", []):
            result[control["id"]] = control_fields(control, group_id)
            walk(control, group_id)
        for group in container.get("groups", []):
            walk(group, group.get("id"))

    walk(catalog_doc["catalog"], None)
    return result


def is_withdrawn(fields: Mapping[str, Any]) -> bool:
    return fields.get(f"prop:{STATUS_PROP}") == WITHDRAWN


def diff_catalogs(
    before_doc: Mapping[str, Any],
    after_doc: Mapping[str, Any],
    *,
    catalog: str,
    lang: Lang,
    from_version: str,
    to_version: str,
) -> CatalogDiff:
    before, after = index_controls(before_doc), index_controls(after_doc)
    added = [cid for cid in after if cid not in before]
    removed = [cid for cid in before if cid not in after]
    retired: list[str] = []
    reinstated: list[str] = []
    changed: list[ControlChange] = []

    for cid, new in after.items():
        old = before.get(cid)
        if old is None:
            continue
        if is_withdrawn(new) and not is_withdrawn(old):
            retired.append(cid)
        elif is_withdrawn(old) and not is_withdrawn(new):
            reinstated.append(cid)

        changes: list[FieldChange] = []
        for key in sorted(set(old) | set(new)):
            if key == f"prop:{STATUS_PROP}" or old.get(key) == new.get(key):
                continue
            change = FieldChange(field=key, before=old.get(key), after=new.get(key))
            if key.startswith("part:"):
                terms_before = obligation_terms(old.get(key), lang)
                terms_after = obligation_terms(new.get(key), lang)
                if terms_before != terms_after:
                    change.flags.append(OBLIGATION_CHANGE)
                    change.obligations_before = sorted(terms_before.elements())
                    change.obligations_after = sorted(terms_after.elements())
            if key == "prop:label":
                change.flags.append(LABEL_CHANGE)
            changes.append(change)
        if changes:
            flags = sorted({flag for c in changes for flag in c.flags})
            changed.append(ControlChange(id=cid, flags=flags, changes=changes))

    return CatalogDiff(
        catalog=catalog,
        lang=lang,
        from_version=from_version,
        to_version=to_version,
        added=added,
        retired=retired,
        reinstated=reinstated,
        removed=removed,
        changed=changed,
        summary={
            "added": len(added),
            "retired": len(retired),
            "reinstated": len(reinstated),
            "removed": len(removed),
            "changed": len(changed),
            OBLIGATION_CHANGE: sum(OBLIGATION_CHANGE in c.flags for c in changed),
        },
    )
