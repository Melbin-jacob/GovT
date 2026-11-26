from __future__ import annotations

import copy
import json
from typing import Any

from govhub_shared.oscal import (
    content_hash,
    dump_json,
    iter_controls,
    normalize,
    stable_uuid,
    validate,
)


def test_stable_uuid_is_deterministic_and_distinct() -> None:
    assert stable_uuid("a", "b") == stable_uuid("a", "b")
    assert stable_uuid("a", "b") != stable_uuid("ab")


def test_content_hash_ignores_revision_identity(minimal_catalog: dict[str, Any]) -> None:
    other = copy.deepcopy(minimal_catalog)
    other["catalog"]["uuid"] = "8f1c2e3a-0000-4000-8000-0000000000ff"
    other["catalog"]["metadata"]["last-modified"] = "2030-01-01T00:00:00+00:00"
    assert content_hash(minimal_catalog, "catalog") == content_hash(other, "catalog")


def test_content_hash_changes_with_content(minimal_catalog: dict[str, Any]) -> None:
    other = copy.deepcopy(minimal_catalog)
    other["catalog"]["groups"][0]["controls"][0]["parts"][0]["prose"] += "!"
    assert content_hash(minimal_catalog, "catalog") != content_hash(other, "catalog")


def test_normalize_round_trips_and_stays_valid(minimal_catalog: dict[str, Any]) -> None:
    normalized = normalize(minimal_catalog, "catalog")
    validate(normalized, "catalog")
    assert normalize(normalized, "catalog") == normalized
    assert "évaluation" in dump_json(normalized)  # no \u escapes on disk
    assert json.loads(dump_json(normalized)) == normalized


def test_iter_controls_flattens_groups(minimal_catalog: dict[str, Any]) -> None:
    (control,) = iter_controls(minimal_catalog)
    assert control.id == "DADM-6.1.1-A"
    assert control.group_id == "dadm-6.1"
    assert control.prop("label") == "6.1.1"
    assert control.hub_prop("check-type") == "Rule-based"
    assert control.part("statement") == "Une évaluation a été réalisée."
