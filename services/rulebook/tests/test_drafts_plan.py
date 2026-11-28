"""Drafting work planned from the synthetic 2023 -> 2025 change (plain code, no model)."""

from __future__ import annotations

import pytest
from drafts_support import BATCH, ENGINE, OFFICER, by_kind, create_batch, model_draft
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_impact import seed


def test_plan_covers_every_kind_of_change(client: TestClient) -> None:
    seed(client)
    batch = create_batch(client)
    kinds = by_kind(batch)
    edits = {i["target_control"]: i for i in kinds["edit"]}
    assert sorted(edits) == ["WID-6.1.2", "WID-6.2.1", "WID-6.3.1", "WID-6.4.2"]
    assert edits["WID-6.2.1"]["flags"] == ["obligation-change", "renumbered"]
    assert edits["WID-6.2.1"]["new_clauses"] == ["6.3.1"]
    assert (
        edits["WID-6.3.1"]["new_clauses"] == ["6.4.1", "6.4.2"]
        and "split" in edits["WID-6.3.1"]["flags"]
    )
    refs = {i["target_control"]: i["new_clauses"] for i in kinds["reference"]}
    assert refs == {"WID-6.2.2": ["6.3.2"], "WID-6.2.3": ["6.3.3"], "WID-6.4.1": ["6.5.1"]}
    assert [i["target_control"] for i in kinds["retire"]] == ["WID-6.3.2"]
    new = kinds["new"]
    assert [(i["proposed_id"], i["new_clauses"], i["group"]) for i in new] == [
        ("WID-C001", ["6.2.1"], "widgets-G01"),
        ("WID-C002", ["6.2.2"], "widgets-G01"),
    ]
    group = batch["plan"]["new_groups"]["widgets-G01"]
    assert group == {
        "key": "6.2@2025-01-01",
        "section": "6.2",
        "title": {"en": "Risk assessment", "fr": group["title"]["fr"]},
    }
    assert group["title"]["fr"] and group["title"]["fr"] != "6.2"
    assert batch["plan"]["proposed_version"] == "1.1.0"
    # Only edits and new controls wait for the model; the rest is decided by code.
    assert {i["kind"] for i in batch["items"] if i["status"] == "pending"} == {"edit", "new"}
    clauses = batch["plan"]["clauses"]
    assert clauses["fr"]["new"]["6.2.1"].startswith("Les ministères")
    assert batch["current_controls"]["WID-6.2.1"]["fr"]["obligation"] == "should"


def test_new_ids_are_never_reused(client: TestClient) -> None:
    seed(client)
    create_batch(client)
    second = by_kind(create_batch(client))["new"]
    assert [i["proposed_id"] for i in second] == ["WID-C003", "WID-C004"]


def test_catalog_must_be_linked_to_the_from_version(client: TestClient) -> None:
    seed(client)
    resp = client.post(
        "/drafts/batches", json={**BATCH, "from": "2025-01-01", "to": "2023-01-01"}, headers=OFFICER
    )
    assert resp.status_code == 422 and "drafting needs a catalog linked to" in resp.json()["detail"]
    assert client.post("/drafts/batches", json=BATCH, auth=None).status_code == 401


def test_model_drafts_only_from_the_engine_and_logged(client: TestClient, engine: Engine) -> None:
    seed(client)
    batch = create_batch(client)
    item = by_kind(batch)["edit"][0]
    url = f"/drafts/items/{item['id']}/model"
    body = model_draft("The register records the owner, location, model and firmware version.")
    assert client.put(f"{url}/en", json=body, headers=OFFICER).status_code == 403
    assert (
        client.put(f"{url}/en", json={**body, "obligation": "maybe"}, headers=ENGINE).status_code
        == 422
    )
    assert client.put(f"{url}/en", json=body, headers=ENGINE).json()["status"] == "pending"
    after = client.put(
        f"{url}/fr", json={**body, "statement": "Le registre..."}, headers=ENGINE
    ).json()
    assert after["status"] == "ready" and after["drafts"]["fr"]["source"] == "model"
    retire = by_kind(batch)["retire"][0]
    assert (
        client.put(f"/drafts/items/{retire['id']}/model/en", json=body, headers=ENGINE).status_code
        == 409
    )
    log = client.get("/drafts/log/verify").json()
    assert log["ok"] is True and log["records"] == 3  # batch created + two model drafts
    with pytest.raises(DBAPIError, match="append-only"), engine.begin() as conn:
        conn.execute(text("DELETE FROM approval_log"))
