"""Screen 2: impact report."""

from __future__ import annotations

import json
import re

import httpx
import pytest
from cc_support import FakeHub, fixture, stub_impact
from fastapi.testclient import TestClient


def _table(html: str, name: str) -> str:
    match = re.search(rf'<table data-table="{name}">(.*?)</table>', html, re.S)
    assert match, name
    return match.group(1)


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_impact_page(ui: TestClient, hub: FakeHub, lang: str) -> None:
    stub_impact(hub)
    resp = ui.get(f"/{lang}/impact")
    assert resp.status_code == 200
    html = resp.text
    for note in ("note.synthetic", "note.fictional"):
        assert 'data-note="' + note.split(".")[1] + '"' in html
    report = fixture("impact.en.json")
    systems = _table(html, "systems")
    names = [s["name"] for s in report["systems"]]
    positions = [systems.index(n) for n in names]
    assert positions == sorted(positions)  # ranked order kept
    tasks = _table(html, "tasks")
    assert "GOVT0000002" in tasks  # number from (mock) ServiceNow
    assert tasks.count("badge-placeholder") == len(report["tasks"])  # PLACEHOLDER due dates
    capacity = _table(html, "capacity")
    assert "agency-sample-benefits" in capacity and "badge-placeholder" in capacity

    (call,) = [r for r in hub.rulebook.requests if r.url.path == "/impact-reports"]
    body = json.loads(call.content)
    assert body["source"] == {
        "instrument": "example-widgets",
        "from": "2023-01-01",
        "to": "2025-01-01",
    }
    assert body["as_of"] == "2026-12-01" and body["catalog_version"] == "1.0.0"
    assert body["lang"] == lang  # the report ID is the same in both languages
    (forecast,) = hub.desk.requests
    assert json.loads(forecast.content)["report_id"] == report["report_id"]


def test_french_page_shows_generated_text_in_french(ui: TestClient, hub: FakeHub) -> None:
    stub_impact(hub)
    html = ui.get("/fr/impact").text
    assert "Disposition 6.1.2 modifiée (similarité 0,84)" in html
    assert "Réévaluer 5 contrôle(s) pour Sample Benefits Triage Assistant (fictional)" in html
    main = html.split("<main", 1)[1].split("</main>", 1)[0]
    assert 'lang="en"' not in main  # nothing marked as English
    assert "en anglais" not in html
    assert "Obligation modifiée" in html


def test_over_capacity_is_flagged(ui: TestClient, hub: FakeHub) -> None:
    stub_impact(hub)
    forecast = fixture("forecast.json")
    forecast["by_tenant"][0].update(exceeds_weekly_capacity=True, weeks_needed=3)
    hub.desk.on("POST", "/forecast", forecast)
    html = ui.get("/en/impact").text
    assert "Over weekly capacity: 3 weeks needed" in html


def test_servicenow_unavailable_does_not_break_the_page(ui: TestClient, hub: FakeHub) -> None:
    stub_impact(hub)
    hub.connector.on("GET", "/tasks/notes", httpx.Response(502, json={"detail": "hibernating"}))
    resp = ui.get("/en/impact")
    assert resp.status_code == 200
    assert "ServiceNow status is unavailable right now" in resp.text
    assert "Not yet in ServiceNow" in resp.text


def test_unknown_impact_level_and_data_gaps_are_shown(ui: TestClient, hub: FakeHub) -> None:
    stub_impact(hub)
    report = fixture("impact.en.json")
    report["systems"][0].update(impact_level=None, data_gaps=["owner", "impact_level"])
    hub.rulebook.on("POST", "/impact-reports", report)  # every language gets this one
    html = ui.get("/en/impact").text
    assert "Unknown (ranked as IV)" in html
    assert "Missing: owner" in html and "Missing: impact level" in html
