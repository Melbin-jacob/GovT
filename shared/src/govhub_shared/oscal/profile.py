"""OSCAL 1.1.3 profile resolution (the subset the hub uses), producing a flat catalog.

Written in-house rather than using trestle's ProfileResolver, which needs a trestle
workspace with an on-disk cache and includes remote (HTTP/SFTP) fetchers; the hub must make
no outbound calls. Catalogs are obtained through a caller-supplied ``loader``.

Supported:
- ``imports`` of catalogs (not of other profiles), each with ``include-all`` or
  ``include-controls`` and optional ``exclude-controls``; selectors ``with-ids`` and
  ``matching`` (glob ``pattern``); ``with-child-controls``
- ``merge``: ``as-is: true`` (keep groups) or flat (no merge, or ``flat``)
- ``modify.set-parameters``

Anything else (``alters``, ``merge.custom``, ``combine`` other than ``use-first``, profile
imports) raises ``ProfileResolutionError`` rather than being silently ignored.

Withdrawn controls (prop ``status = withdrawn``) are never included; selecting one by ID is
reported as a warning.
"""

from __future__ import annotations

import copy
import fnmatch
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from govhub_shared import OSCAL_NS, OSCAL_VERSION
from govhub_shared.oscal.documents import content_hash, stable_uuid, unwrap
from govhub_shared.oscal.schema import validate
from govhub_shared.oscal.trestle_bridge import normalize

CatalogLoader = Callable[[str], Mapping[str, Any]]


class ProfileResolutionError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("profile resolution failed:\n" + "\n".join(f"  - {e}" for e in errors))


@dataclass
class ResolvedProfile:
    catalog: dict[str, Any]
    control_ids: list[str]
    warnings: list[str] = field(default_factory=list)


def _withdrawn(control: Mapping[str, Any]) -> bool:
    return any(
        p.get("name") == "status" and p.get("ns") is None and p.get("value") == "withdrawn"
        for p in control.get("props", [])
    )


def _matches(control_id: str, selectors: list[Mapping[str, Any]]) -> tuple[bool, bool]:
    """(selected, with_child_controls) for one control against a list of selectors."""
    for selector in selectors:
        ids = selector.get("with-ids", [])
        patterns = [m["pattern"] for m in selector.get("matching", [])]
        if control_id in ids or any(fnmatch.fnmatchcase(control_id, p) for p in patterns):
            return True, selector.get("with-child-controls") == "yes"
    return False, False


def _select(
    container: Mapping[str, Any],
    include: list[Mapping[str, Any]] | None,
    exclude: list[Mapping[str, Any]],
    forced: bool,
    picked: list[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    """Return copies of the selected controls of ``container`` (children nested as-is)."""
    selected: list[dict[str, Any]] = []
    for control in container.get("controls", []):
        cid = control["id"]
        if include is None:
            hit, children = True, True
        else:
            hit, children = _matches(cid, include)
            hit = hit or forced
        excluded, _ = _matches(cid, exclude)
        kids = _select(control, include, exclude, hit and children, picked, warnings)
        if hit and not excluded:
            if _withdrawn(control):
                warnings.append(f"{cid} is withdrawn and was not included")
                continue
            clone = {k: copy.deepcopy(v) for k, v in control.items() if k != "controls"}
            picked.append(cid)
            if kids:
                clone["controls"] = kids
            selected.append(clone)
        else:
            selected.extend(kids)  # a selected child of an unselected parent is promoted
    return selected


def _select_groups(
    container: Mapping[str, Any],
    include: list[Mapping[str, Any]] | None,
    exclude: list[Mapping[str, Any]],
    picked: list[str],
    warnings: list[str],
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for group in container.get("groups", []):
        controls = _select(group, include, exclude, False, picked, warnings)
        subgroups = _select_groups(group, include, exclude, picked, warnings)
        if controls or subgroups:
            clone = {
                k: copy.deepcopy(v) for k, v in group.items() if k not in ("controls", "groups")
            }
            if controls:
                clone["controls"] = controls
            if subgroups:
                clone["groups"] = subgroups
            groups.append(clone)
    return groups


def _explicit_ids(selectors: list[Mapping[str, Any]]) -> list[str]:
    return [cid for s in selectors for cid in s.get("with-ids", [])]


def _all_ids(container: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    for control in container.get("controls", []):
        ids.add(control["id"])
        ids |= _all_ids(control)
    for group in container.get("groups", []):
        ids |= _all_ids(group)
    return ids


def _set_parameters(
    controls_root: dict[str, Any], settings: list[Mapping[str, Any]], errors: list[str]
) -> None:
    params: dict[str, dict[str, Any]] = {}

    def walk(container: Mapping[str, Any]) -> None:
        for param in container.get("params", []):
            params[param["id"]] = param
        for key in ("controls", "groups"):
            for child in container.get(key, []):
                walk(child)

    walk(controls_root)
    for setting in settings:
        target = params.get(setting["param-id"])
        if target is None:
            errors.append(f"set-parameters: parameter {setting['param-id']!r} not in selection")
            continue
        for key, value in setting.items():
            if key != "param-id":
                target[key] = copy.deepcopy(value)


def resolve_profile(
    profile_doc: Mapping[str, Any], loader: CatalogLoader, *, source_href: str | None = None
) -> ResolvedProfile:
    """Resolve a ``{"profile": {...}}`` document into a schema-valid catalog."""
    validate(profile_doc, "profile")
    profile = unwrap(profile_doc, "profile")
    errors: list[str] = []
    warnings: list[str] = []

    merge = profile.get("merge", {})
    if "custom" in merge:
        errors.append("merge.custom is not supported")
    combine = merge.get("combine", {}).get("method", "use-first")
    if combine != "use-first":
        errors.append(f"merge.combine method {combine!r} is not supported")
    if profile.get("modify", {}).get("alters"):
        errors.append("modify.alters is not supported yet")  # TODO(rulebook): alters
    as_is = merge.get("as-is") is True

    picked: list[str] = []
    groups: list[dict[str, Any]] = []
    flat: list[dict[str, Any]] = []
    for imp in profile["imports"]:
        href = imp["href"]
        try:
            source = loader(href)
        except Exception as exc:
            errors.append(f"import {href!r}: {exc}")
            continue
        if "profile" in source:
            errors.append(f"import {href!r}: importing profiles is not supported yet")
            continue
        catalog = unwrap(source, "catalog")
        include = None if "include-all" in imp else imp.get("include-controls", [])
        exclude = imp.get("exclude-controls", [])
        missing = sorted(set(_explicit_ids(include or [])) - _all_ids(catalog))
        if missing:
            errors.append(f"import {href!r}: controls not in the catalog: {missing}")
        flat.extend(_select(catalog, include, exclude, False, picked, warnings))
        selected_groups = _select_groups(catalog, include, exclude, picked, warnings)
        if as_is:
            groups.extend(selected_groups)
        else:
            for group in selected_groups:
                flat.extend(_flatten_group(group))

    duplicates = sorted({cid for cid in picked if picked.count(cid) > 1})
    if duplicates:
        errors.append(f"controls selected more than once (use-first not applied): {duplicates}")

    metadata = profile["metadata"]
    body: dict[str, Any] = {
        "uuid": "00000000-0000-4000-8000-000000000000",
        "metadata": {
            "title": metadata["title"],
            "last-modified": metadata["last-modified"],
            "version": metadata["version"],
            "oscal-version": OSCAL_VERSION,
            "props": [
                {"name": "resolution-tool", "ns": OSCAL_NS, "value": "govhub-rulebook"},
                {"name": "source-profile-uuid", "ns": OSCAL_NS, "value": profile["uuid"]},
            ],
        },
    }
    if source_href:
        body["metadata"]["links"] = [{"href": source_href, "rel": "source-profile"}]
    if flat:
        body["controls"] = flat
    if groups:
        body["groups"] = groups

    _set_parameters(body, profile.get("modify", {}).get("set-parameters", []), errors)
    if errors:
        raise ProfileResolutionError(errors)

    doc = normalize({"catalog": body}, "catalog")
    doc["catalog"]["uuid"] = stable_uuid("resolved-profile", content_hash(doc, "catalog"))
    doc = normalize(doc, "catalog")
    validate(doc, "catalog")
    return ResolvedProfile(catalog=doc, control_ids=picked, warnings=warnings)


def _flatten_group(group: Mapping[str, Any]) -> list[dict[str, Any]]:
    out = list(group.get("controls", []))
    for sub in group.get("groups", []):
        out.extend(_flatten_group(sub))
    return out
