"""Impact reports on the synthetic demo data (Directive on Example Widgets)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from helpers import new_version, set_statement
from test_inventory import payload, put_profiles

from rulebook.impact import load_due_dates

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "data" / "demo"
SOURCE = {"instrument": "example-widgets", "from": "2023-01-01", "to": "2025-01-01"}
REQUEST: dict[str, Any] = {
    "catalog": "example-widgets",
    "catalog_version": "1.0.0",
    "source": SOURCE,
    "as_of": "2026-12-01",
}


def _json(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text("utf-8"))
    return data


def seed(client: TestClient) -> None:
    for path in sorted((DEMO / "sources").glob("example-widgets.*.json")):
        if not path.name.endswith(".meta.json"):
            assert client.post("/sources", json=_json(path)).status_code == 201
    for lang in ("en", "fr"):
        resp = client.post(
            "/catalogs", json=_json(DEMO / "catalogs" / f"example-widgets.{lang}.json")
        )
        assert resp.status_code == 201
    put_profiles(client)
    assert client.put("/inventory", json=payload()).status_code == 201


def report(client: TestClient, **overrides: Any) -> dict[str, Any]:
    resp = client.post("/impact-reports", json={**REQUEST, **overrides})
    assert resp.status_code == 200, resp.json()
    data: dict[str, Any] = resp.json()
    return data


def test_source_change_report(client: TestClient) -> None:
    seed(client)
    body = report(client)

    affected = {c["id"]: c for c in body["affected_controls"]}
    assert sorted(affected) == ["WID-6.1.2", "WID-6.2.1", "WID-6.3.1", "WID-6.3.2", "WID-6.4.2"]
    assert [r["kind"] for r in affected["WID-6.3.1"]["reasons"]] == ["clause split"]
    assert [r["kind"] for r in affected["WID-6.3.2"]["reasons"]] == ["clause removed"]
    assert affected["WID-6.2.1"]["obligation_change"] is True
    assert affected["WID-6.2.1"]["reasons"][0]["flags"] == ["renumbered", "obligation-change"]
    assert [c for c in affected if affected[c]["obligation_change"]] == ["WID-6.2.1"]

    ranked = [(s["system_id"], s["impact_level"], s["findings_to_review"]) for s in body["systems"]]
    assert ranked == [
        ("SYS-001", "IV", 5),
        ("SYS-002", "III", 5),
        ("SYS-005", "III", 2),
        ("SYS-003", "II", 3),
        ("SYS-007", "II", 2),
        ("SYS-004", "I", 3),
    ]
    assert body["summary"]["findings_to_review"] == 20
    assert body["summary"]["findings_by_impact_level"] == {"IV": 5, "III": 7, "II": 5, "I": 3}
    excluded = {e["system_id"]: e["reason"] for e in body["excluded_systems"]}
    assert excluded == {
        "SYS-006": "no profile selects from example-widgets",
        "SYS-008": "lifecycle retired",
    }

    maintenance = {(m["kind"], m["clause"]) for m in body["maintenance"]}
    assert maintenance == {
        ("update clause reference", "6.2.2"),
        ("update clause reference", "6.2.3"),
        ("update clause reference", "6.4.1"),
        ("unmapped clause", "6.2.1"),
        ("unmapped clause", "6.2.2"),
    }
    trigger = body["triggers"]["source"]
    assert trigger["threshold"] == 0.6 and "Hungarian" in trigger["method"]
    assert trigger["language_divergences"] == 0


def test_tasks(client: TestClient) -> None:
    seed(client)
    tasks = {t["system_id"]: t for t in report(client)["tasks"]}
    assert list(tasks) == ["SYS-001", "SYS-002", "SYS-005", "SYS-003", "SYS-007", "SYS-004"]
    top = tasks["SYS-001"]
    assert top["table"] == "sc_task" and top["type"] == "reassessment"
    assert top["priority"] == 1
    assert top["assigned_to"] == "benefits.owner@example.invalid"
    assert top["assignment_group"] == "agency-sample-benefits"
    assert top["due_date"] == "2026-12-31"  # as_of + 30 days (PLACEHOLDER, level IV)
    assert top["due_date_basis"] == "PLACEHOLDER: level IV = 30 days (default)"
    assert "[OBLIGATION CHANGE]" in top["description"]
    cal = next(c for c in top["controls"] if c["id"] == "WID-6.2.1")
    assert cal["evidence_requested"] == "Calibration dates within the last 12 months"
    # Tenant override: office-fictional-permits level III = 30 days instead of 45.
    assert tasks["SYS-002"]["due_date"] == "2026-12-31"
    assert "tenant office-fictional-permits override" in tasks["SYS-002"]["due_date_basis"]
    assert tasks["SYS-005"]["due_date"] == "2027-01-15"  # default level III = 45 days
    assert tasks["SYS-004"]["priority"] == 4


def test_report_is_deterministic_and_tenant_filter(client: TestClient) -> None:
    seed(client)
    first, second = report(client), report(client)
    assert first == second
    assert len(first["report_id"]) == 16
    later = report(client, as_of="2027-01-01")
    assert later["report_id"] != first["report_id"]
    only = report(client, tenant="office-fictional-permits")
    assert [s["system_id"] for s in only["systems"]] == ["SYS-002", "SYS-007"]


def test_french_tasks_use_french_text(client: TestClient) -> None:
    seed(client)
    body = report(client, lang="fr")
    cal = next(c for c in body["tasks"][0]["controls"] if c["id"] == "WID-6.2.1")
    assert cal["statement"] == "Les widgets sont étalonnés au moins une fois par année."
    assert [s["system_id"] for s in body["systems"]][:2] == ["SYS-001", "SYS-002"]


def test_catalog_change_trigger(client: TestClient) -> None:
    """Controls edited directly, with no source change. Edits are synthetic test data."""
    seed(client)
    nxt = copy.deepcopy(_json(DEMO / "catalogs" / "example-widgets.en.json"))
    set_statement(nxt, "WID-6.2.2", "A qualified technician must review calibration results.")
    set_statement(
        nxt, "WID-6.4.1", "Clients are told, in writing, when a widget processes their request."
    )
    assert client.post("/catalogs", json=new_version(nxt, "1.1.0")).status_code == 201
    body = report(
        client,
        source=None,
        catalog_version=None,
        catalog_change={"from": "1.0.0", "to": "1.1.0"},
    )
    affected = {c["id"]: c for c in body["affected_controls"]}
    assert sorted(affected) == ["WID-6.2.2", "WID-6.4.1"]
    assert affected["WID-6.2.2"]["reasons"][0]["kind"] == "control changed"
    assert affected["WID-6.2.2"]["obligation_change"] is True
    assert affected["WID-6.4.1"]["obligation_change"] is False
    assert "source" not in body["triggers"]
    assert body["inputs"]["catalog_version"] == "1.1.0"
    ranked = [(s["system_id"], s["findings_to_review"]) for s in body["systems"]]
    assert ranked == [
        ("SYS-001", 2),
        ("SYS-002", 2),
        ("SYS-005", 1),
        ("SYS-003", 1),
        ("SYS-007", 1),
        ("SYS-004", 1),
    ]


def test_both_triggers_merge_reasons(client: TestClient) -> None:
    seed(client)
    nxt = copy.deepcopy(_json(DEMO / "catalogs" / "example-widgets.en.json"))
    set_statement(nxt, "WID-6.2.1", "Widgets are calibrated at least twice a year.")
    client.post("/catalogs", json=new_version(nxt, "1.1.0"))
    body = report(client, catalog_version=None, catalog_change={"from": "1.0.0", "to": "1.1.0"})
    kinds = [
        r["kind"]
        for r in next(c for c in body["affected_controls"] if c["id"] == "WID-6.2.1")["reasons"]
    ]
    assert kinds == ["clause changed", "control changed"]


def test_retired_control_is_reported(client: TestClient) -> None:
    seed(client)
    client.post("/catalogs/example-widgets/versions/1.0.0/retire-control/WID-6.3.2")
    body = report(
        client, source=None, catalog_version=None, catalog_change={"from": "1.0.0", "to": "1.1.0"}
    )
    assert body["affected_controls"] == []
    (item,) = body["maintenance"]
    assert item["kind"] == "control retired" and item["control"] == "WID-6.3.2"
    assert item["systems"] == ["SYS-001", "SYS-002", "SYS-003", "SYS-004"]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"source": None}, "give a source change"),
        ({"catalog_version": None}, "catalog_version is required"),
        ({"catalog_change": {"from": "1.0.0", "to": "1.1.0"}}, "must equal catalog_change.to"),
        ({"source": {**SOURCE, "instrument": "dadm"}}, "is linked to 'example-widgets'"),
        (
            {"source": {**SOURCE, "from": "2025-01-01", "to": "2030-01-01"}},
            "must start or end there",
        ),
    ],
)
def test_bad_requests(client: TestClient, overrides: dict[str, Any], message: str) -> None:
    seed(client)
    resp = client.post("/impact-reports", json={**REQUEST, **overrides})
    assert resp.status_code == 422
    assert message in json.dumps(resp.json())


def test_due_date_config_is_marked_placeholder() -> None:
    policy = load_due_dates(REPO / "data" / "config" / "due-dates.toml")
    assert {status for _, status in policy.default.values()} == {"PLACEHOLDER"}
    assert {d for d, _ in policy.default.values()} == {30, 45, 60, 90}


def test_due_date_config_validation(tmp_path: Path) -> None:
    bad = tmp_path / "due.toml"
    bad.write_text('[default]\nlevel_4 = { days = 30, status = "PLACEHOLDER" }\n', "utf-8")
    with pytest.raises(ValueError, match="missing level"):
        load_due_dates(bad)
