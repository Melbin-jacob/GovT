"""Source-document endpoints, with synthetic data only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

DEMO = Path(__file__).resolve().parents[3] / "data" / "demo" / "sources"


def load(stem: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DEMO / f"{stem}.json").read_text("utf-8"))
    return data


EN_2023, FR_2023 = "example-widgets.2023-01-01.en", "example-widgets.2023-01-01.fr"


def test_store_and_read(client: TestClient) -> None:
    resp = client.post("/sources", json=load(EN_2023))
    assert resp.status_code == 201
    body = resp.json()
    assert body["clauses"] == 9
    assert body["synthetic"] is True
    assert body["parity_warnings"] == ["example-widgets 2023-01-01: no fr version stored yet"]
    assert client.post("/sources", json=load(FR_2023)).json()["parity_warnings"] == []

    doc = client.get("/sources/example-widgets/versions/2023-01-01", params={"lang": "fr"})
    assert doc.json()["clauses"][0]["text"].startswith("Chaque ministère doit")
    clause = client.get("/sources/example-widgets/versions/2023-01-01/clauses/6.2.1").json()
    assert clause["text"] == "Widgets should be calibrated at least once a year."
    assert (
        client.get("/sources/example-widgets/versions/2023-01-01/clauses/9.9.9").status_code == 404
    )
    assert client.get("/sources/example-widgets/versions/1999-01-01").status_code == 404
    assert client.get("/sources/example-widgets/versions/not-a-date").status_code == 422

    (listing,) = client.get("/sources").json()
    assert listing["versions"] == [
        {
            "version": "2023-01-01",
            "langs": ["en", "fr"],
            "clauses": {"en": 9, "fr": 9},
            "parity_warnings": [],
        }
    ]


def test_immutable_and_idempotent(client: TestClient, db: Session) -> None:
    doc = load(EN_2023)
    client.post("/sources", json=doc)
    again = client.post("/sources", json=doc)
    assert again.status_code == 200
    assert again.json()["created"] is False
    doc["clauses"][0]["text"] = "Synthetic edit."
    assert client.post("/sources", json=doc).status_code == 409
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("UPDATE source_versions SET lang = 'fr'"))
    db.rollback()


def test_parity_warnings_name_the_clauses(client: TestClient) -> None:
    fr = load(FR_2023)
    fr["clauses"] = [c for c in fr["clauses"] if c["number"] != "6.3.2"]
    client.post("/sources", json=load(EN_2023))
    body = client.post("/sources", json=fr).json()
    assert body["parity_warnings"] == ["clauses only in EN: ['6.3.2']"]


def test_rejects_metadata_only_and_invalid(client: TestClient) -> None:
    meta = json.loads((DEMO / f"{EN_2023}.meta.json").read_text("utf-8"))
    resp = client.post("/sources", json=meta)
    assert resp.status_code == 422
    assert "only full documents" in resp.json()["detail"]
    bad = load(EN_2023)
    bad["lang"] = "de"
    assert client.post("/sources", json=bad).status_code == 422
