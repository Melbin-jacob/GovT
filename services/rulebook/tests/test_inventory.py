"""Fictional AI-system inventory and stored profiles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from rulebook.cli import main
from rulebook.inventory import InventoryError, parse_inventory_csv

REPO = Path(__file__).resolve().parents[3]
INVENTORY = REPO / "data" / "inventory" / "systems.csv"
PROFILE_FILES = sorted(
    [
        *(REPO / "data" / "profiles").glob("*.json"),
        *(REPO / "data" / "demo" / "profiles").glob("*.json"),
    ]
)


def _csv() -> str:
    return INVENTORY.read_text(encoding="utf-8")


def payload() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(parse_inventory_csv(_csv(), "systems.csv").model_dump_json())
    return data


def put_profiles(client: TestClient) -> None:
    for path in PROFILE_FILES:
        name = path.name.removesuffix(".json")
        resp = client.put(f"/profiles/{name}", json=json.loads(path.read_text("utf-8")))
        assert resp.status_code in (200, 201), resp.json()


def test_demo_inventory_is_valid_and_clearly_fictional() -> None:
    inventory = parse_inventory_csv(_csv())
    assert len(inventory.systems) == 8
    assert {s.impact_level for s in inventory.systems} == {1, 2, 3, 4}
    for system in inventory.systems:
        assert "(fictional)" in system.name
        assert "(fictional)" in system.department
        assert system.owner_email.endswith("@example.invalid")
    sys1 = inventory.systems[0]
    assert (sys1.impact_level, sys1.impact_label) == (4, "IV")
    assert sys1.profiles == ["dadm-level-ii-plus", "widgets-all"]


def test_content_hash_is_order_independent() -> None:
    inventory = parse_inventory_csv(_csv())
    reordered = inventory.model_copy(update={"systems": list(reversed(inventory.systems))})
    assert inventory.content_hash() == reordered.content_hash()


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('"IV","production"', '"V","production"', "impact_level"),
        (
            '"production","dadm-level-ii-plus;widgets-all"',
            '"live","dadm-level-ii-plus;widgets-all"',
            "lifecycle",
        ),
        ("benefits.owner@example.invalid", "not-an-email", "owner_email"),
        ('"SYS-002"', '"SYS-001"', "duplicate System ID SYS-001"),
        ('"System ID"', '"Identifier"', "missing column"),
    ],
)
def test_invalid_inventory(old: str, new: str, message: str) -> None:
    with pytest.raises(InventoryError, match=message):
        parse_inventory_csv(_csv().replace(old, new, 1))


def test_cli_inventory_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["inventory-json", str(INVENTORY)]) == 0
    assert len(json.loads(capsys.readouterr().out)["systems"]) == 8


# --- API -------------------------------------------------------------------------------


def test_profiles_api(client: TestClient) -> None:
    put_profiles(client)
    names = [p["name"] for p in client.get("/profiles").json()]
    assert names == [
        "dadm-all",
        "dadm-level-ii-plus",
        "widgets-all",
        "widgets-calibration",
        "widgets-records",
    ]
    doc = json.loads((REPO / "data" / "profiles" / "dadm-all.json").read_text("utf-8"))
    again = client.put("/profiles/dadm-all", json=doc)
    assert again.status_code == 200 and again.json()["created"] is False
    assert client.put("/profiles/other-name", json=doc).status_code == 422  # name mismatch
    del doc["profile"]["imports"]
    assert client.put("/profiles/broken", json=doc).status_code == 422
    assert client.get("/profiles/nope").status_code == 404


def test_inventory_api(client: TestClient) -> None:
    assert client.get("/inventory").status_code == 404
    unknown = client.put("/inventory", json=payload())
    assert unknown.status_code == 422  # profiles not stored yet
    assert "unknown profile" in unknown.json()["errors"][0]

    put_profiles(client)
    stored = client.put("/inventory", json=payload())
    assert stored.status_code == 201
    body = stored.json()
    assert body["systems"] == 8
    assert body["tenants"] == [
        "agency-sample-benefits",
        "dept-example-services",
        "office-fictional-permits",
    ]
    inventory = client.get("/inventory").json()
    assert inventory["content_hash"] == body["content_hash"]
    tenant = client.get("/inventory", params={"tenant": "office-fictional-permits"}).json()
    assert [s["system_id"] for s in tenant["systems"]] == ["SYS-002", "SYS-007"]
    assert client.get("/systems/SYS-004").json()["impact_level"] == 1
    assert client.get("/systems/SYS-999").status_code == 404

    smaller = payload()
    smaller["systems"] = smaller["systems"][:3]
    second = client.put("/inventory", json=smaller).json()
    assert second["snapshot"] > body["snapshot"]
    assert len(client.get("/inventory").json()["systems"]) == 3  # newest snapshot is current

    bad = payload()
    bad["systems"][0]["impact_level"] = 5
    assert client.put("/inventory", json=bad).status_code == 422
