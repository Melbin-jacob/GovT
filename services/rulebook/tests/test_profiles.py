from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import control

from govhub_shared.oscal import (
    ProfileResolutionError,
    iter_controls,
    resolve_profile,
    validate,
)
from rulebook.cli import main
from rulebook.profiles import file_loader

REPO = Path(__file__).resolve().parents[3]
PROFILE_PATH = REPO / "data" / "profiles" / "dadm-level-ii-plus.json"
LEVEL_II_PLUS = [
    "DADM-6.1.1-A",
    "DADM-6.1.1-B",
    "DADM-6.1.1-C",
    "DADM-6.1.2",
    "DADM-6.1.3-A",
    "DADM-6.1.3-B",
    "DADM-6.2.1",
    "DADM-6.2.3",
    "DADM-6.3.6-A",
    "DADM-6.3.6-B",
    "DADM-6.3.7",
    "DADM-6.3.8",
    "DADM-IT-CONTINUITY",
    "DADM-HUMAN",
    "DADM-APPROVAL",
]


@pytest.fixture
def example_profile() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    return data


def _profile(imports: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "profile": {
            "uuid": "8f1c2e3a-0000-4000-8000-000000000099",
            "metadata": {
                "title": "Test profile",
                "last-modified": "2026-11-26T00:00:00+00:00",
                "version": "0.1.0",
                "oscal-version": "1.1.3",
            },
            "imports": imports,
            **extra,
        }
    }


def _loader(catalog: dict[str, Any]) -> Any:
    return lambda href: catalog


# --- the example profile ---------------------------------------------------------------


def test_example_profile_is_schema_valid(example_profile: dict[str, Any]) -> None:
    validate(example_profile, "profile")


def test_example_profile_resolves_to_level_ii_plus_selection(
    example_profile: dict[str, Any],
) -> None:
    result = resolve_profile(example_profile, file_loader(PROFILE_PATH.parent))
    assert result.control_ids == LEVEL_II_PLUS
    assert result.warnings == []
    validate(result.catalog, "catalog")
    catalog = result.catalog["catalog"]
    assert [g["id"] for g in catalog["groups"]] == ["dadm-6.1", "dadm-6.2", "dadm-6.3"]
    assert [c.id for c in iter_controls(result.catalog)] == LEVEL_II_PLUS
    # deterministic: same profile and catalog -> same resolved document
    again = resolve_profile(example_profile, file_loader(PROFILE_PATH.parent))
    assert again.catalog == result.catalog


def test_example_profile_resolves_identically_in_french(
    example_profile: dict[str, Any],
) -> None:
    example_profile["profile"]["imports"][0]["href"] = "../catalogs/dadm-section6.fr.json"
    result = resolve_profile(example_profile, file_loader(PROFILE_PATH.parent))
    assert result.control_ids == LEVEL_II_PLUS
    assert result.catalog["catalog"]["groups"][0]["title"] == (
        "Évaluation de l'incidence algorithmique"
    )


def test_cli_resolve_profile(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["resolve-profile", str(PROFILE_PATH), "--ids"]) == 0
    assert capsys.readouterr().out.split() == LEVEL_II_PLUS
    out = tmp_path / "resolved.json"
    assert main(["resolve-profile", str(PROFILE_PATH), "--out", str(out)]) == 0
    validate(json.loads(out.read_text()), "catalog")


# --- resolver behaviour ----------------------------------------------------------------


def test_flat_merge_drops_groups(golden_en: dict[str, Any]) -> None:
    result = resolve_profile(
        _profile([{"href": "x", "include-controls": [{"with-ids": ["DADM-HUMAN", "DADM-6.4.1"]}]}]),
        _loader(golden_en),
    )
    catalog = result.catalog["catalog"]
    assert "groups" not in catalog
    assert [c["id"] for c in catalog["controls"]] == ["DADM-HUMAN", "DADM-6.4.1"]


def test_matching_and_exclude(golden_en: dict[str, Any]) -> None:
    result = resolve_profile(
        _profile(
            [
                {
                    "href": "x",
                    "include-controls": [{"matching": [{"pattern": "DADM-6.5.*"}]}],
                    "exclude-controls": [{"with-ids": ["DADM-6.5.2.1"]}],
                }
            ]
        ),
        _loader(golden_en),
    )
    assert result.control_ids == ["DADM-6.5.1", "DADM-6.5.2"]


def test_include_all_skips_withdrawn_controls(golden_en: dict[str, Any]) -> None:
    control(golden_en, "DADM-6.3.5")["props"].append({"name": "status", "value": "withdrawn"})
    result = resolve_profile(
        _profile([{"href": "x", "include-all": {}}], merge={"as-is": True}), _loader(golden_en)
    )
    assert len(result.control_ids) == 38
    assert "DADM-6.3.5" not in result.control_ids
    assert result.warnings == ["DADM-6.3.5 is withdrawn and was not included"]


def test_set_parameters(golden_en: dict[str, Any]) -> None:
    # Synthetic parameter: the golden set has none yet.
    control(golden_en, "DADM-6.2.1")["params"] = [{"id": "DADM-6.2.1_prm_1", "label": "Channels"}]
    result = resolve_profile(
        _profile(
            [{"href": "x", "include-controls": [{"with-ids": ["DADM-6.2.1"]}]}],
            modify={
                "set-parameters": [
                    {"param-id": "DADM-6.2.1_prm_1", "values": ["online portal", "telephone"]}
                ]
            },
        ),
        _loader(golden_en),
    )
    (param,) = result.catalog["catalog"]["controls"][0]["params"]
    assert param["values"] == ["online portal", "telephone"]


@pytest.mark.parametrize(
    ("imports", "extra", "message"),
    [
        ([{"href": "x", "include-controls": [{"with-ids": ["DADM-NOPE"]}]}], {}, "DADM-NOPE"),
        (
            [{"href": "x", "include-all": {}}],
            {"modify": {"alters": [{"control-id": "DADM-6.4.1", "removes": [{"by-name": "x"}]}]}},
            "alters",
        ),
        ([{"href": "x", "include-all": {}}], {"merge": {"custom": {}}}, "custom"),
        (
            [{"href": "x", "include-all": {}}, {"href": "y", "include-all": {}}],
            {},
            "more than once",
        ),
        (
            [{"href": "x", "include-all": {}}],
            {"modify": {"set-parameters": [{"param-id": "nope", "values": ["a"]}]}},
            "nope",
        ),
    ],
)
def test_unsupported_or_invalid_profiles_fail(
    golden_en: dict[str, Any], imports: list[dict[str, Any]], extra: dict[str, Any], message: str
) -> None:
    with pytest.raises(ProfileResolutionError, match=message):
        resolve_profile(_profile(imports, **extra), _loader(golden_en))


def test_file_loader_refuses_network_hrefs(tmp_path: Path) -> None:
    load = file_loader(tmp_path)
    for href in ("https://example.org/catalog.json", "//example.org/c.json"):
        with pytest.raises(ValueError, match="no network"):
            load(href)


def test_profile_imports_are_not_supported(golden_en: dict[str, Any]) -> None:
    nested = _profile([{"href": "x", "include-all": {}}])
    with pytest.raises(ProfileResolutionError, match="importing profiles"):
        resolve_profile(_profile([{"href": "p", "include-all": {}}]), _loader(nested))


# --- API -------------------------------------------------------------------------------


def test_resolve_endpoint_uses_stored_catalogs(
    client: TestClient,
    golden_en: dict[str, Any],
    golden_fr: dict[str, Any],
    example_profile: dict[str, Any],
) -> None:
    client.post("/catalogs", json=golden_en)
    client.post("/catalogs", json=golden_fr)
    profile = copy.deepcopy(example_profile)
    profile["profile"]["imports"][0]["href"] = "/catalogs/dadm-section6/versions/1.0.0?lang=fr"
    resp = client.post("/profiles/resolve", json=profile)
    assert resp.status_code == 200
    assert resp.json()["control_ids"] == LEVEL_II_PLUS
    validate(resp.json()["catalog"], "catalog")

    # After retiring a selected control, resolving the next version leaves it out.
    client.post("/catalogs/dadm-section6/versions/1.0.0/retire-control/DADM-HUMAN")
    profile["profile"]["imports"][0]["href"] = "/catalogs/dadm-section6/versions/1.1.0"
    body = client.post("/profiles/resolve", json=profile).json()
    assert "DADM-HUMAN" not in body["control_ids"]
    assert body["warnings"] == ["DADM-HUMAN is withdrawn and was not included"]


def test_resolve_endpoint_errors(client: TestClient, example_profile: dict[str, Any]) -> None:
    resp = client.post("/profiles/resolve", json=example_profile)  # file href: not allowed
    assert resp.status_code == 422
    assert "stored catalog path" in resp.json()["errors"][0]
    bad = copy.deepcopy(example_profile)
    del bad["profile"]["metadata"]["title"]
    assert client.post("/profiles/resolve", json=bad).status_code == 422
