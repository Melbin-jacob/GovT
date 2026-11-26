"""Helpers for building test catalog versions.

Statement edits made here are synthetic test data, not policy text.
"""

from __future__ import annotations

import copy
from typing import Any

from govhub_shared.oscal import content_hash, normalize, stable_uuid


def control(doc: dict[str, Any], control_id: str) -> dict[str, Any]:
    for group in doc["catalog"]["groups"]:
        for ctrl in group["controls"]:
            if ctrl["id"] == control_id:
                return ctrl  # type: ignore[no-any-return]
    raise KeyError(control_id)


def new_version(doc: dict[str, Any], version: str) -> dict[str, Any]:
    """Copy a catalog under a new version with a fresh content-derived uuid."""
    out = copy.deepcopy(doc)
    out["catalog"]["metadata"]["version"] = version
    return reuuid(out)


def reuuid(doc: dict[str, Any]) -> dict[str, Any]:
    normalized = normalize(doc, "catalog")
    normalized["catalog"]["uuid"] = stable_uuid(
        "oscal-catalog", content_hash(normalized, "catalog")
    )
    return normalized


def set_statement(doc: dict[str, Any], control_id: str, prose: str) -> None:
    for part in control(doc, control_id)["parts"]:
        if part["name"] == "statement":
            part["prose"] = prose
            return
    raise KeyError(control_id)


def set_label(doc: dict[str, Any], control_id: str, label: str) -> None:
    for prop in control(doc, control_id)["props"]:
        if prop["name"] == "label":
            prop["value"] = label
            return
    raise KeyError(control_id)


def drop_control(doc: dict[str, Any], control_id: str) -> None:
    for group in doc["catalog"]["groups"]:
        group["controls"] = [c for c in group["controls"] if c["id"] != control_id]


def add_control(doc: dict[str, Any], group_index: int, control_id: str, prose: str) -> None:
    doc["catalog"]["groups"][group_index]["controls"].append(
        {
            "id": control_id,
            "title": control_id,
            "props": [{"name": "label", "value": "9.9.9"}],
            "parts": [{"id": f"{control_id}_smt", "name": "statement", "prose": prose}],
        }
    )
