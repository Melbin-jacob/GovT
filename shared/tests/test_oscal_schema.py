from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

import pytest

from govhub_shared import OSCAL_VERSION
from govhub_shared.oscal import OscalValidationError, schema_dir, validate


def test_vendored_schemas_match_source_checksums() -> None:
    directory = schema_dir()
    source = (directory / "SOURCE.md").read_text(encoding="utf-8")
    rows = re.findall(r"`(oscal_[\w-]+_schema\.json)` \| \S+ \| `([0-9a-f]{64})`", source)
    assert len(rows) == 4
    for name, expected in rows:
        actual = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        assert actual == expected, f"{name} differs from the NIST release"
        schema = json.loads((directory / name).read_text(encoding="utf-8"))
        assert f"/oscal/{OSCAL_VERSION}/" in schema["$id"]


def test_minimal_catalog_validates(minimal_catalog: dict[str, Any]) -> None:
    validate(minimal_catalog, "catalog")


@pytest.mark.parametrize(
    ("path", "value", "reason"),
    [
        (("groups", 0, "id"), "6.1", "token must start with a letter (\\p{L} pattern)"),
        (("groups", 0, "controls", 0, "id"), "DADM 6", "token cannot contain a space"),
        (("metadata", "last-modified"), "yesterday", "date-time format is asserted"),
        (("groups", 0, "controls", 0, "props", 1, "ns"), "not a uri", "ns must be a URI"),
        (("uuid",), "not-a-uuid", "uuid pattern"),
    ],
)
def test_invalid_catalogs_fail(
    minimal_catalog: dict[str, Any], path: tuple[Any, ...], value: str, reason: str
) -> None:
    doc = copy.deepcopy(minimal_catalog)
    target: Any = doc["catalog"]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(OscalValidationError):
        validate(doc, "catalog")


def test_missing_required_metadata_fails(minimal_catalog: dict[str, Any]) -> None:
    del minimal_catalog["catalog"]["metadata"]["oscal-version"]
    with pytest.raises(OscalValidationError, match="oscal-version"):
        validate(minimal_catalog, "catalog")


def test_minimal_profile_validates() -> None:
    profile = {
        "profile": {
            "uuid": "8f1c2e3a-0000-4000-8000-000000000011",
            "metadata": {
                "title": "P",
                "last-modified": "2026-11-26T00:00:00+00:00",
                "version": "1.0.0",
                "oscal-version": "1.1.3",
            },
            "imports": [{"href": "cat.json", "include-controls": [{"with-ids": ["DADM-6.1.1-A"]}]}],
        }
    }
    validate(profile, "profile")
