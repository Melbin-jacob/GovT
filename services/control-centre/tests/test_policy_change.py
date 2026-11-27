"""Screen 1: policy change (clause diff)."""

from __future__ import annotations

import re

import httpx
import pytest
from cc_support import FakeHub, fixture, stub_policy
from fastapi.testclient import TestClient

from control_centre.screens.policy import build_rows


def _rows(html: str) -> list[str]:
    return re.findall(r'data-flags="([^"]*)"', html)


def test_build_rows_shows_a_split_as_one_row_and_keeps_every_clause() -> None:
    diff = fixture("diff.en.json")["en"]
    old = {c["number"]: c["text"] for c in fixture("source.2023-01-01.en.json")["clauses"]}
    new = {c["number"]: c["text"] for c in fixture("source.2025-01-01.en.json")["clauses"]}
    rows = build_rows(diff, old, new)
    split = next(r for r in rows if "split" in r.flags)
    assert [n for n, _ in split.old] == ["6.3.1"]
    assert [n for n, _ in split.new] == ["6.4.1", "6.4.2"]
    assert all(text for _, text in split.new)
    # Every clause of both versions appears exactly once.
    assert sorted(n for r in rows for n, _ in r.old) == sorted(old)
    assert sorted(n for r in rows for n, _ in r.new) == sorted(new)
    obligation = next(r for r in rows if "obligation-change" in r.flags)
    assert obligation.flags[0] == "obligation-change"
    assert (obligation.obligations_before, obligation.obligations_after) == (["should"], ["must"])


def test_policy_change_page_in_english(ui: TestClient, hub: FakeHub) -> None:
    stub_policy(hub)
    resp = ui.get("/en/policy-change")
    assert resp.status_code == 200
    html = resp.text
    assert "Synthetic test data, not real policy" in html
    assert "Directive on Example Widgets (synthetic)" in html
    flags = _rows(html)
    assert "obligation-change renumbered text-changed" in flags
    assert "split renumbered text-changed" in flags
    assert "removed" in flags and "added" in flags
    assert "Obligation: should → must" in html
    assert "Widgets must be calibrated at least once a year." in html
    (diff_call,) = [r for r in hub.rulebook.requests if r.url.path.endswith("/diff")]
    assert diff_call.url.params["from"] == "2023-01-01"
    assert diff_call.url.params["to"] == "2025-01-01"
    assert diff_call.url.params["lang"] == "en"


def test_policy_change_page_in_french_uses_the_french_text(ui: TestClient, hub: FakeHub) -> None:
    stub_policy(hub)
    html = ui.get("/fr/policy-change?from=2023-01-01&to=2025-01-01").text
    assert "Données d&#39;essai synthétiques, pas une politique réelle" in html
    assert "Obligation modifiée" in html and "Scindée" in html
    assert "Le registre consigne" not in html  # catalog text is not on this screen
    assert "Directive sur les widgets d&#39;exemple (synthétique)" in html
    assert all(r.url.params.get("lang", "fr") == "fr" for r in hub.rulebook.requests)


def test_same_version_asks_for_two_versions(ui: TestClient, hub: FakeHub) -> None:
    stub_policy(hub)
    html = ui.get("/en/policy-change?from=2025-01-01&to=2025-01-01").text
    assert "Pick two different versions." in html
    assert not any(r.url.path.endswith("/diff") for r in hub.rulebook.requests)


@pytest.mark.parametrize(("lang", "text"), [("en", "could not complete"), ("fr", "n&#39;a pas pu")])
def test_backend_failure_shows_an_error_page(
    ui: TestClient, hub: FakeHub, lang: str, text: str
) -> None:
    hub.rulebook.on("GET", "/sources", httpx.Response(503, json={"detail": "database down"}))
    resp = ui.get(f"/{lang}/policy-change")
    assert resp.status_code == 502
    assert text in resp.text and "database down" in resp.text
    assert 'role="alert"' in resp.text
