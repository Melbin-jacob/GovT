"""Helpers for the drafting tests (synthetic Example Widgets 2023 -> 2025)."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

OFFICER = {"X-GovHub-User": "officer-01", "X-GovHub-Role": "governance-officer"}
OFFICER_2 = {"X-GovHub-User": "officer-02", "X-GovHub-Role": "governance-officer"}
REVIEWER = {"X-GovHub-User": "reviewer-01", "X-GovHub-Role": "reviewer"}
ENGINE = {"X-GovHub-User": "assessment-engine", "X-GovHub-Role": "assessment-engine"}
BATCH = {
    "catalog": "example-widgets",
    "version": "1.0.0",
    "instrument": "example-widgets",
    "from": "2023-01-01",
    "to": "2025-01-01",
}


def create_batch(client: TestClient) -> dict[str, Any]:
    resp = client.post("/drafts/batches", json=BATCH, headers=OFFICER)
    assert resp.status_code == 201, resp.json()
    data: dict[str, Any] = resp.json()
    return data


def by_kind(batch: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for item in batch["items"]:
        out.setdefault(item["kind"], []).append(item)
    return out


def model_draft(statement: str, **extra: Any) -> dict[str, Any]:
    return {
        "status": "drafted",
        "statement": statement,
        "check_type": "rule-based",
        "obligation": "must",
        "cited_clause": "",
        "reasoning": "",
        "confidence": 0.9,
        "model_id": "scripted-fake-v1",
        "prompt_version": "draft-v1",
        **extra,
    }


# Fictional drafted wording for the synthetic batch (as a scripted model would return).
WORDING: dict[str, dict[str, str]] = {
    "WID-6.1.2": {
        "en": "The register records the owner, location, model and firmware version of each widget.",
        "fr": "Le registre consigne le propriétaire, l'emplacement, le modèle et la version du micrologiciel de chaque widget.",
    },
    "WID-6.3.1": {
        "en": "Every calibration is logged, and the calibration log is kept for two years.",
        "fr": "Chaque étalonnage est consigné, et le registre d'étalonnage est conservé deux ans.",
    },
    "WID-6.4.2": {
        "en": "Departments report annually, for the fiscal year, on widgets in service.",
        "fr": "Les ministères font rapport chaque année, pour l'exercice, sur les widgets en service.",
    },
    "6.2.1": {
        "en": "A widget risk assessment is completed before the widget is put into service.",
        "fr": "Une évaluation des risques du widget est réalisée avant sa mise en service.",
    },
    "6.2.2": {
        "en": "The widget risk assessment is updated when the widget's purpose changes.",
        "fr": "L'évaluation des risques du widget est mise à jour lorsque sa fin change.",
    },
}


def draft_everything(client: TestClient, batch: dict[str, Any]) -> None:
    """Post a model draft for every edit and new item, in both languages."""
    for item in batch["items"]:
        if item["kind"] not in ("edit", "new"):
            continue
        key = item["target_control"] or item["new_clauses"][0]
        for lang in ("en", "fr"):
            clause = batch["plan"]["clauses"][lang]["new"][item["new_clauses"][0]]
            if key == "WID-6.2.1":  # should -> must: the wording stays, only the force changed
                body = model_draft(
                    batch["current_controls"][key][lang]["statement"], no_change=True
                )
            else:
                body = model_draft(WORDING[key][lang])
            body["cited_clause"] = clause
            if item["kind"] == "new":
                body["check_type"] = "judgment" if key == "6.2.2" else "rule-based"
            resp = client.put(f"/drafts/items/{item['id']}/model/{lang}", json=body, headers=ENGINE)
            assert resp.status_code == 200, resp.json()


def open_both(client: TestClient, batch_id: str, headers: dict[str, str]) -> str:
    """Start an approval session and open the English and French views of the batch."""
    sid: str = client.post("/drafts/sessions", headers=headers).json()["id"]
    for lang in ("en", "fr"):
        resp = client.post(
            f"/drafts/batches/{batch_id}/views",
            json={"session_id": sid, "lang": lang},
            headers=headers,
        )
        assert resp.status_code == 200, resp.json()
    return sid


def approve(
    client: TestClient, batch_id: str, item_id: str, headers: dict[str, str] = OFFICER
) -> Any:
    """Read both languages in a fresh session, then approve."""
    sid = open_both(client, batch_id, headers)
    return client.post(
        f"/drafts/items/{item_id}/approve", json={"session_id": sid}, headers=headers
    )
