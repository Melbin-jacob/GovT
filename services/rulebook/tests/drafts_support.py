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
