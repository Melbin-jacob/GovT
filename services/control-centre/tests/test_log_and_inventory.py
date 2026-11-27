"""Screens 4 (decision log) and 5 (inventory)."""

from __future__ import annotations

import re

import httpx
import pytest
from cc_support import FakeHub, fixture, stub_inventory, stub_log
from fastapi.testclient import TestClient

from control_centre.screens.log import checkpoint_state


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_log_lists_records_newest_first_with_checkpoints(
    ui: TestClient, hub: FakeHub, lang: str
) -> None:
    stub_log(hub)
    html = ui.get(f"/{lang}/decision-log").text
    seqs = [int(s) for s in re.findall(r'<th scope="row" class="num">(\d+)</th>', html)]
    assert seqs == [6, 5, 4, 3, 2, 1]
    assert 'data-source="file" data-state="in-step"' in html
    assert 'data-source="servicenow" data-state="in-step"' in html
    assert "verify-result" not in html  # verifying is a click
    assert not [r for r in hub.desk.requests if r.url.path == "/decision-log/verify"]


def test_verify_trusts_the_ticked_sources(ui: TestClient, hub: FakeHub) -> None:
    stub_log(hub)
    html = ui.get("/en/decision-log?verify=true&trust=file&trust=servicenow").text
    assert 'data-ok="true"' in html
    assert "6 records checked; 12 external checkpoints match." in html
    (call,) = [r for r in hub.desk.requests if r.url.path == "/decision-log/verify"]
    assert call.url.params.get_list("trust") == ["file", "servicenow"]


def test_verify_failure_lists_the_problems(ui: TestClient, hub: FakeHub) -> None:
    stub_log(hub)
    problem = "log ends at seq 3 but checkpoint says 6 (records removed from the end) [file x]"
    hub.desk.on(
        "GET",
        "/decision-log/verify",
        {**fixture("verify.json"), "ok": False, "problems": [problem]},
    )
    html = ui.get("/fr/decision-log?verify=true&trust=file").text
    assert 'data-ok="false"' in html and 'role="alert"' in html
    assert "Le registre a été modifié" in html
    assert f'<li lang="en">{problem}</li>' in html


@pytest.mark.parametrize(
    ("source", "state"),
    [
        ({"behind_database": 0}, "in-step"),
        ({"behind_database": 2}, "behind"),
        ({"behind_database": -2}, "ahead"),
        ({"behind_database": None}, "none"),
        ({"available": False, "behind_database": None}, "unavailable"),
    ],
)
def test_checkpoint_state(source: dict[str, object], state: str) -> None:
    assert checkpoint_state(source) == state


def test_records_missing_from_the_database_are_flagged(ui: TestClient, hub: FakeHub) -> None:
    stub_log(hub)
    status = fixture("checkpoint-status.json")
    status["file"]["behind_database"] = -3
    hub.desk.on("GET", "/decision-log/checkpoint-status", status)
    html = ui.get("/en/decision-log").text
    assert "Ahead of the database by 3: records are missing" in html


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_inventory_lists_systems_with_gaps_first(ui: TestClient, hub: FakeHub, lang: str) -> None:
    stub_inventory(hub)
    html = ui.get(f"/{lang}/inventory").text
    order = re.findall(r'data-system="([^"]+)"', html)
    assert order[0] == "SYS-009" and len(order) == 9
    assert 'data-note="fictional"' in html
    assert 'data-note="synthetic"' not in html  # no policy text on this screen
    row = html[html.index('data-system="SYS-009"') :].split("</tr>")[0]
    assert row.count("badge-gap") == 4
    assert ("Missing: owner" if lang == "en" else "Manquant : responsable") in row
    assert ">IV<" in html  # impact level 4 shown as IV


def test_inventory_backend_failure(ui: TestClient, hub: FakeHub) -> None:
    hub.rulebook.on("GET", "/inventory", httpx.Response(404, json={"detail": "no inventory"}))
    resp = ui.get("/en/inventory")
    assert resp.status_code == 400 and "no inventory" in resp.text
