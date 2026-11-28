"""Approval needs both languages opened, recorded by the server (not only a checkbox)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from drafts_support import ENGINE, OFFICER, OFFICER_2, REVIEWER, by_kind, open_both
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from test_drafts_approval import drafted_batch


def _session(client: TestClient, headers: dict[str, str] = OFFICER) -> str:
    resp = client.post("/drafts/sessions", headers=headers)
    assert resp.status_code == 201, resp.json()
    sid: str = resp.json()["id"]
    return sid


def _open(client: TestClient, batch_id: str, sid: str, lang: str, **extra: Any) -> Any:
    return client.post(
        f"/drafts/batches/{batch_id}/views",
        json={"session_id": sid, "lang": lang, **extra},
        headers=OFFICER,
    )


def _approve(
    client: TestClient, item_id: str, sid: str | None, headers: dict[str, str] = OFFICER
) -> Any:
    body = {"session_id": sid} if sid else {}
    return client.post(f"/drafts/items/{item_id}/approve", json=body, headers=headers)


def test_approval_needs_both_languages_opened_in_the_session(client: TestClient) -> None:
    batch = drafted_batch(client)
    item = by_kind(batch)["edit"][0]
    refused = _approve(client, item["id"], None)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "not-read"

    sid = _session(client)
    assert _open(client, batch["id"], sid, "en").json()["recorded"] == 6  # 4 edits, 2 new
    refused = _approve(client, item["id"], sid)
    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "not-read",
        "message": "not opened in this session since the draft last changed: fr",
    }
    _open(client, batch["id"], sid, "fr")
    assert _approve(client, item["id"], sid).status_code == 200


def test_the_approval_record_carries_the_reading(client: TestClient) -> None:
    batch = drafted_batch(client)
    item = by_kind(batch)["new"][0]
    sid = open_both(client, batch["id"], OFFICER)
    assert _approve(client, item["id"], sid).status_code == 200
    records = [json.loads(json.loads(line)["record"]) for line in
               client.get("/drafts/log/export").text.splitlines() if line]  # fmt: skip
    approved = next(r for r in records if r["action"] == "approved" and r["item"] == item["id"])
    assert approved["read"]["session"] == sid
    assert approved["read"]["opened"]["en"] and approved["read"]["opened"]["fr"]
    assert client.get("/drafts/log/verify").json()["ok"]


def test_a_change_after_reading_must_be_read_again(client: TestClient) -> None:
    batch = drafted_batch(client)
    item = by_kind(batch)["new"][1]
    sid = open_both(client, batch["id"], OFFICER)
    shown = client.get(f"/drafts/batches/{batch['id']}", params={"session_id": sid}).json()
    read = next(i for i in shown["items"] if i["id"] == item["id"])["read"]
    assert read["en"] and read["fr"]
    # A reviewer corrects the French draft after the officer read it.
    fix = {"languages": {"fr": {"statement": "L'évaluation est mise à jour."}}}
    assert client.put(f"/drafts/items/{item['id']}", json=fix, headers=REVIEWER).status_code == 200
    shown = client.get(f"/drafts/batches/{batch['id']}", params={"session_id": sid}).json()
    assert next(i for i in shown["items"] if i["id"] == item["id"])["read"] == {
        "en": None,
        "fr": None,
    }
    refused = _approve(client, item["id"], sid)
    assert refused.json()["detail"]["code"] == "not-read"
    assert "en, fr" in refused.json()["detail"]["message"]
    _open(client, batch["id"], sid, "fr")
    _open(client, batch["id"], sid, "en")
    assert _approve(client, item["id"], sid).status_code == 200


def test_a_new_model_draft_also_resets_the_reading(client: TestClient) -> None:
    batch = drafted_batch(client)
    item = by_kind(batch)["edit"][1]
    sid = open_both(client, batch["id"], OFFICER)
    keep = ("status", "no_change", "statement", "check_type", "obligation", "cited_clause",
            "confidence", "model_id", "prompt_version")  # fmt: skip
    redraft = {k: item["drafts"]["en"][k] for k in keep if k in item["drafts"]["en"]}
    redraft["statement"] = "Redrafted."
    resp = client.put(f"/drafts/items/{item['id']}/model/en", json=redraft, headers=ENGINE)
    assert resp.status_code == 200
    assert _approve(client, item["id"], sid).json()["detail"]["code"] == "not-read"


def test_someone_elses_session_does_not_count(client: TestClient) -> None:
    batch = drafted_batch(client)
    item = by_kind(batch)["edit"][0]
    theirs = open_both(client, batch["id"], OFFICER_2)
    refused = _approve(client, item["id"], theirs)  # OFFICER using OFFICER_2's session
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "session"
    views = _open(client, batch["id"], theirs, "en")  # recording into it is refused too
    assert views.status_code == 403
    assert client.post("/drafts/sessions", headers=ENGINE).status_code == 403  # not a reader


def test_items_without_wording_need_no_reading(client: TestClient) -> None:
    batch = drafted_batch(client)
    for kind in ("reference", "retire"):
        item = by_kind(batch)[kind][0]
        assert _approve(client, item["id"], None).status_code == 200, kind


def test_two_person_rule_still_comes_first(client: TestClient) -> None:
    batch = drafted_batch(client)
    item = by_kind(batch)["new"][0]
    fields = {"statement": "A widget risk assessment is done before use."}
    client.put(f"/drafts/items/{item['id']}", json={"languages": {"en": fields}}, headers=OFFICER)
    sid = open_both(client, batch["id"], OFFICER)
    refused = _approve(client, item["id"], sid)
    assert refused.json()["detail"]["code"] == "two-person-rule"


def test_decided_items_record_no_views(client: TestClient) -> None:
    batch = drafted_batch(client)
    item = by_kind(batch)["edit"][0]
    sid = open_both(client, batch["id"], OFFICER)
    _approve(client, item["id"], sid)
    assert _open(client, batch["id"], sid, "en").json()["recorded"] == 5
    only = _open(client, batch["id"], sid, "fr", items=[item["id"]])
    assert only.json()["recorded"] == 0


def test_views_are_append_only(client: TestClient, engine: Engine) -> None:
    batch = drafted_batch(client)
    open_both(client, batch["id"], OFFICER)
    with engine.begin() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text("UPDATE draft_views SET lang = 'fr'"))
    with engine.begin() as conn, pytest.raises(DBAPIError, match="append-only"):
        conn.execute(text("DELETE FROM draft_views"))
