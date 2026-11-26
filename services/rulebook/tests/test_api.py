"""API tests against a real PostgreSQL test database. Edits are synthetic test data."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import drop_control, new_version, set_label, set_statement
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

NAME = "dadm-section6"


def _post(client: TestClient, doc: dict[str, Any], **params: str) -> Any:
    return client.post("/catalogs", json=doc, params=params)


@pytest.fixture
def seeded(client: TestClient, golden_en: dict[str, Any], golden_fr: dict[str, Any]) -> None:
    assert _post(client, golden_en).status_code == 201
    assert _post(client, golden_fr).status_code == 201


# --- ops -------------------------------------------------------------------------------


def test_ready(client: TestClient) -> None:
    assert client.get("/ready").json() == {"status": "ready"}


# --- import ----------------------------------------------------------------------------


def test_import_reads_identity_from_metadata(client: TestClient, golden_en: dict[str, Any]) -> None:
    resp = _post(client, golden_en)
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == NAME
    assert body["version"] == "1.0.0"
    assert body["lang"] == "en"
    assert body["controls"] == 39
    assert body["withdrawn"] == 0
    assert body["created"] is True
    assert body["uuid"] == golden_en["catalog"]["uuid"]


def test_reimport_identical_is_idempotent(client: TestClient, golden_en: dict[str, Any]) -> None:
    _post(client, golden_en)
    resp = _post(client, golden_en)
    assert resp.status_code == 200
    assert resp.json()["created"] is False


def test_stored_versions_are_immutable(client: TestClient, golden_en: dict[str, Any]) -> None:
    _post(client, golden_en)
    changed = copy.deepcopy(golden_en)
    set_statement(changed, "DADM-6.2.2-A", "Synthetic edit.")
    resp = _post(client, changed)
    assert resp.status_code == 409
    assert "immutable" in resp.json()["detail"]


def test_database_refuses_updates_and_deletes(seeded: None, db: Session) -> None:
    for statement in (
        "UPDATE catalog_versions SET version = '9.9.9'",
        "DELETE FROM catalog_versions",
    ):
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(text(statement))
        db.rollback()


def test_invalid_oscal_is_rejected_with_errors(
    client: TestClient, golden_en: dict[str, Any]
) -> None:
    golden_en["catalog"]["groups"][0]["id"] = "6.1"
    resp = _post(client, golden_en)
    assert resp.status_code == 422
    assert resp.json()["errors"]


def test_non_semver_version_is_rejected(client: TestClient, golden_en: dict[str, Any]) -> None:
    resp = _post(client, new_version(golden_en, "v1"))
    assert resp.status_code == 422
    assert "semantic version" in resp.json()["errors"][0]


def test_query_params_must_agree_with_metadata(
    client: TestClient, golden_en: dict[str, Any]
) -> None:
    assert _post(client, golden_en, lang="fr").status_code == 422
    assert _post(client, golden_en, name="other").status_code == 422


def test_versions_must_increase(client: TestClient, golden_en: dict[str, Any]) -> None:
    assert _post(client, new_version(golden_en, "2.0.0")).status_code == 201
    assert _post(client, golden_en).status_code == 409


# --- ID freeze and parity --------------------------------------------------------------


def test_removing_a_control_without_retire_is_rejected(
    client: TestClient, golden_en: dict[str, Any]
) -> None:
    _post(client, golden_en)
    nxt = copy.deepcopy(golden_en)
    drop_control(nxt, "DADM-LEGAL")
    resp = _post(client, new_version(nxt, "1.1.0"))
    assert resp.status_code == 422
    assert "DADM-LEGAL" in resp.json()["errors"][0]
    assert "retire-control" in resp.json()["errors"][0]


def test_reusing_an_id_for_a_different_clause_label_warns(
    client: TestClient, golden_en: dict[str, Any]
) -> None:
    _post(client, golden_en)
    nxt = copy.deepcopy(golden_en)
    set_label(nxt, "DADM-6.3.7", "6.3.8")
    resp = _post(client, new_version(nxt, "1.0.1"))
    assert resp.status_code == 201
    (warning,) = resp.json()["warnings"]
    assert "DADM-6.3.7" in warning
    assert "different clause label" in warning


def test_fr_must_match_en_control_ids(
    client: TestClient, golden_en: dict[str, Any], golden_fr: dict[str, Any]
) -> None:
    _post(client, golden_en)
    drop_control(golden_fr, "DADM-6.5.1")
    resp = _post(client, new_version(golden_fr, "1.0.0"))
    assert resp.status_code == 422
    assert "parity" in resp.json()["errors"][0]
    assert "DADM-6.5.1" in resp.json()["errors"][0]


# --- reads -----------------------------------------------------------------------------


def test_list_catalogs(client: TestClient, seeded: None) -> None:
    (entry,) = client.get("/catalogs").json()
    assert entry["name"] == NAME
    assert entry["latest"] == "1.0.0"
    assert entry["versions"] == [{"version": "1.0.0", "langs": ["en", "fr"], "derived_from": None}]


def test_get_version(
    client: TestClient, seeded: None, golden_en: dict[str, Any], golden_fr: dict[str, Any]
) -> None:
    assert client.get(f"/catalogs/{NAME}/versions/1.0.0").json() == golden_en
    assert client.get(f"/catalogs/{NAME}/versions/1.0.0", params={"lang": "fr"}).json() == (
        golden_fr
    )
    assert client.get(f"/catalogs/{NAME}/versions/9.9.9").status_code == 404
    assert client.get("/catalogs/nope/versions/1.0.0").status_code == 404


def test_get_control(client: TestClient, seeded: None) -> None:
    body = client.get("/controls/DADM-SECURITY").json()
    assert body["catalog"] == NAME
    assert body["version"] == "1.0.0"
    assert body["group"] == "dadm-6.3"
    assert body["status"] == "active"
    assert body["control"]["id"] == "DADM-SECURITY"
    fr = client.get("/controls/DADM-SECURITY", params={"lang": "fr", "version": "1.0.0"}).json()
    assert fr["control"]["parts"][0]["prose"].startswith("Les risques")
    assert client.get("/controls/DADM-NOPE").status_code == 404
    assert client.get("/controls/DADM-SECURITY", params={"version": "2.0.0"}).status_code == 404


# --- retire ----------------------------------------------------------------------------


def test_retire_creates_minor_version_in_both_languages(client: TestClient, seeded: None) -> None:
    resp = client.post(f"/catalogs/{NAME}/versions/1.0.0/retire-control/DADM-6.3.5")
    assert resp.status_code == 201
    assert resp.json() == {
        "catalog": NAME,
        "from_version": "1.0.0",
        "version": "1.1.0",
        "control_id": "DADM-6.3.5",
        "langs": ["en", "fr"],
        "warnings": [],
    }
    for lang in ("en", "fr"):
        body = client.get("/controls/DADM-6.3.5", params={"lang": lang}).json()
        assert body["version"] == "1.1.0"
        assert body["status"] == "withdrawn"
        assert {"name": "status", "value": "withdrawn"} in body["control"]["props"]
        old = client.get("/controls/DADM-6.3.5", params={"lang": lang, "version": "1.0.0"})
        assert old.json()["status"] == "active"  # history kept
        doc = client.get(f"/catalogs/{NAME}/versions/1.1.0", params={"lang": lang}).json()
        assert doc["catalog"]["metadata"]["version"] == "1.1.0"
    catalogs = client.get("/catalogs").json()
    assert catalogs[0]["latest"] == "1.1.0"
    assert catalogs[0]["versions"][1]["derived_from"] == "retire DADM-6.3.5 from 1.0.0"


def test_retire_errors(client: TestClient, seeded: None) -> None:
    base = f"/catalogs/{NAME}/versions"
    assert client.post(f"{base}/1.0.0/retire-control/DADM-NOPE").status_code == 404
    assert client.post(f"{base}/1.0.0/retire-control/DADM-6.3.5").status_code == 201
    stale = client.post(f"{base}/1.0.0/retire-control/DADM-6.3.6-A")
    assert stale.status_code == 409  # not the latest version
    again = client.post(f"{base}/1.1.0/retire-control/DADM-6.3.5")
    assert again.status_code == 409
    assert "already withdrawn" in again.json()["detail"]


# --- diff ------------------------------------------------------------------------------


def test_diff_after_retire(client: TestClient, seeded: None) -> None:
    client.post(f"/catalogs/{NAME}/versions/1.0.0/retire-control/DADM-6.3.5")
    body = client.post(f"/catalogs/{NAME}/diff", params={"from": "1.0.0", "to": "1.1.0"}).json()
    assert body["retired"] == ["DADM-6.3.5"]
    assert body["added"] == body["removed"] == body["changed"] == []


def test_diff_flags_obligation_change_post_and_get(
    client: TestClient, seeded: None, golden_en: dict[str, Any]
) -> None:
    nxt = copy.deepcopy(golden_en)
    set_statement(nxt, "DADM-6.2.2-A", "Notices must be displayed prominently.")
    assert _post(client, new_version(nxt, "1.1.0")).status_code == 201
    params = {"from": "1.0.0", "to": "1.1.0"}
    post = client.post(f"/catalogs/{NAME}/diff", params=params)
    get = client.get(f"/catalogs/{NAME}/diff", params=params)
    assert post.status_code == get.status_code == 200
    assert post.json() == get.json()
    (change,) = post.json()["changed"]
    assert change["id"] == "DADM-6.2.2-A"
    assert change["flags"] == ["obligation-change"]
    assert change["changes"][0]["obligations_after"] == ["must"]
    assert post.json()["summary"]["obligation-change"] == 1


def test_diff_errors(client: TestClient, seeded: None) -> None:
    assert client.get(f"/catalogs/{NAME}/diff", params={"from": "1.0.0"}).status_code == 422
    missing = client.get(f"/catalogs/{NAME}/diff", params={"from": "1.0.0", "to": "5.0.0"})
    assert missing.status_code == 404
