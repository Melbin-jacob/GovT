"""Approving drafts and publishing the new catalog version (synthetic Example Widgets)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from drafts_support import (
    ENGINE,
    OFFICER,
    OFFICER_2,
    REVIEWER,
    approve,
    by_kind,
    create_batch,
    draft_everything,
    open_both,
)
from fastapi.testclient import TestClient
from test_impact import seed

from govhub_shared import OSCAL_NS
from govhub_shared.oscal import iter_controls, validate
from rulebook.config import get_settings


@pytest.fixture(autouse=True)
def checkpoint_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "approval-log.jsonl"
    monkeypatch.setenv("RULEBOOK_APPROVAL_CHECKPOINT_FILE", str(path))
    get_settings.cache_clear()
    return path


def drafted_batch(client: TestClient) -> dict[str, Any]:
    seed(client)
    batch = create_batch(client)
    draft_everything(client, batch)
    data: dict[str, Any] = client.get(f"/drafts/batches/{batch['id']}").json()
    return data


def approve_all(
    client: TestClient, batch: dict[str, Any], headers: dict[str, str] = OFFICER
) -> None:
    sid = open_both(client, batch["id"], headers)
    for item in batch["items"]:
        resp = client.post(
            f"/drafts/items/{item['id']}/approve", json={"session_id": sid}, headers=headers
        )
        assert resp.status_code == 200, (item["kind"], resp.json())


def hub(control: Any, name: str) -> list[str]:
    return [p.value for p in control.props if p.name == name and p.ns == OSCAL_NS]


def test_two_person_rule(client: TestClient) -> None:
    batch = drafted_batch(client)
    item = by_kind(batch)["new"][0]
    fields = {"statement": "A widget risk assessment is done before use."}
    edit = client.put(
        f"/drafts/items/{item['id']}", json={"languages": {"en": fields}}, headers=OFFICER
    )
    assert edit.status_code == 200 and edit.json()["last_edited_by"] == "officer-01"
    refused = client.post(f"/drafts/items/{item['id']}/approve", headers=OFFICER)
    assert refused.status_code == 409
    assert refused.json()["detail"]["code"] == "two-person-rule"
    assert (
        "officer-01 last edited this draft and cannot also approve it"
        in refused.json()["detail"]["message"]
    )
    assert approve(client, batch["id"], item["id"], OFFICER_2).status_code == 200


def test_roles_needs_human_and_language_agreement(client: TestClient) -> None:
    batch = drafted_batch(client)
    item = by_kind(batch)["new"][1]
    assert client.post(f"/drafts/items/{item['id']}/approve", headers=REVIEWER).status_code == 403
    # French draft gives another obligation: refused until a person aligns them.
    mismatch = {"languages": {"fr": {"obligation": "should"}}}
    client.put(f"/drafts/items/{item['id']}", json=mismatch, headers=REVIEWER)
    refused = client.post(f"/drafts/items/{item['id']}/approve", headers=OFFICER)
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "languages-differ"
    # A needs-human draft must be written by a person first.
    other = by_kind(batch)["edit"][0]
    needs = {"status": "needs-human", "reason": "low-confidence", "statement": "x"}
    client.put(
        f"/drafts/items/{other['id']}/model/en",
        json=needs,
        headers=ENGINE,
    )
    refused = client.post(f"/drafts/items/{other['id']}/approve", headers=OFFICER)
    assert refused.json()["detail"]["code"] == "needs-human"
    # Proposed IDs: never reused.
    used = client.put(
        f"/drafts/items/{item['id']}", json={"proposed_id": "WID-6.1.1"}, headers=REVIEWER
    )
    assert used.status_code == 422 and used.json()["detail"]["code"] == "id-used"
    ok = client.put(
        f"/drafts/items/{item['id']}", json={"proposed_id": "WID-C050"}, headers=REVIEWER
    )
    assert ok.json()["proposed_id"] == "WID-C050"


def test_source_date_default_and_guard(client: TestClient) -> None:
    batch = drafted_batch(client)
    bounds = client.get(f"/drafts/batches/{batch['id']}/publish-defaults").json()
    assert bounds["previous"] == "2026-11-28T00:00:00Z"
    # The later of the 2025-01-01 effective date and the previous SOURCE_DATE + 1 day.
    assert bounds["default"] == "2026-11-29T00:00:00Z" and bounds["version"] == "1.1.0"
    approve_all(client, batch)
    early = client.post(
        f"/drafts/batches/{batch['id']}/publish",
        json={"source_date": "2026-11-28T00:00:00Z"},
        headers=OFFICER,
    )
    assert early.status_code == 422 and early.json()["detail"]["code"] == "source-date"


def test_publish_builds_version_1_1_0(client: TestClient, checkpoint_file: Path) -> None:
    batch = drafted_batch(client)
    undecided = client.post(f"/drafts/batches/{batch['id']}/publish", json={}, headers=OFFICER)
    assert undecided.json()["detail"]["code"] == "undecided"
    approve_all(client, batch)
    resp = client.post(f"/drafts/batches/{batch['id']}/publish", json={}, headers=OFFICER)
    assert resp.status_code == 200, resp.json()
    out = resp.json()
    assert (out["version"], out["source_date"], out["checkpoint"]) == (
        "1.1.0",
        "2026-11-29T00:00:00Z",
        "written",
    )
    for lang in ("en", "fr"):
        doc = client.get("/catalogs/example-widgets/versions/1.1.0", params={"lang": lang}).json()
        validate(doc, "catalog")
        controls = {c.id: c for c in iter_controls(doc)}
        new = controls["WID-C001"]
        assert new.group_id == "widgets-G01" and new.prop("label") == "6.2.1"
        assert hub(new, "source-clause") == ["6.2.1"] and hub(new, "obligation") == ["must"]
        assert hub(new, "review-status") == ["draft"]  # approval is not review
        assert hub(new, "approved-by") == ["officer-01"]
        assert hub(new, "drafted-by")[0].startswith("en: model scripted-fake-v1, prompt draft-v1")
        assert hub(new, "approval-record")[0].startswith("approval-log seq ")
        assert controls["WID-6.3.2"].prop("status") == "withdrawn"
        assert hub(controls["WID-6.2.2"], "source-clause") == ["6.3.2"]  # reference update
        calibration = controls["WID-6.2.1"]
        assert hub(calibration, "obligation") == ["must"] and hub(calibration, "source-clause") == [
            "6.3.1"
        ]
        assert hub(controls["WID-6.3.1"], "source-clause") == ["6.4.1", "6.4.2"]
        meta = {p["name"]: p["value"] for p in doc["catalog"]["metadata"]["props"]}
        assert meta["source-version"] == "2025-01-01"
        assert meta["approval-log-head"] == out["approval_log_head"]
    assert "Firmware" in json.dumps(
        client.get("/catalogs/example-widgets/versions/1.1.0").json()
    ).replace("firmware", "Firmware")
    log = client.get("/drafts/log/verify").json()
    assert log["ok"] and log["records"] == 1 + 2 * 6 + 10 + 1
    lines = checkpoint_file.read_text("utf-8").splitlines()
    assert json.loads(lines[-1])["seq"] == log["head_seq"]
    change_set = client.get(f"/drafts/batches/{batch['id']}/change-set").json()
    assert change_set["new_version"] == "1.1.0" and len(change_set["changes"]) == 10
    again = client.post(f"/drafts/batches/{batch['id']}/publish", json={}, headers=OFFICER)
    assert again.json()["detail"]["code"] == "batch-closed"


def test_rejecting_a_reference_update_leaves_a_stale_link(client: TestClient) -> None:
    batch = drafted_batch(client)
    ref = by_kind(batch)["reference"][0]
    for item in batch["items"]:
        if item["id"] == ref["id"]:
            client.post(
                f"/drafts/items/{item['id']}/reject",
                json={"reason": "check later"},
                headers=OFFICER,
            )
        else:
            approve(client, batch["id"], item["id"])
    resp = client.post(f"/drafts/batches/{batch['id']}/publish", json={}, headers=OFFICER)
    assert resp.status_code == 409 and resp.json()["detail"]["code"] == "stale-links"
