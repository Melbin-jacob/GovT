"""Screen 3: review queue, finding detail and the five actions."""

from __future__ import annotations

import json
import re

import httpx
import pytest
from cc_support import FakeHub, fixture, stub_review
from fastapi.testclient import TestClient

from control_centre.i18n import Translator
from control_centre.screens.review import ACTIONS, decision_body


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_queue_keeps_review_desk_ranking(ui: TestClient, hub: FakeHub, lang: str) -> None:
    stub_review(hub)
    html = ui.get(f"/{lang}/review").text
    queue = fixture("queue.json")["findings"]
    links = re.findall(r'href="/' + lang + r'/review/([0-9a-f-]{36})"', html)
    assert links == [f["id"] for f in queue]
    assert 'data-note="synthetic"' in html and 'data-note="fictional"' in html
    assert html.count("badge-placeholder") == len(queue)


def test_finding_detail_shows_the_french_requirement(ui: TestClient, hub: FakeHub) -> None:
    finding = stub_review(hub)
    html = ui.get(f"/fr/review/{finding['id']}").text
    assert "Le registre consigne le propriétaire" in html  # from the French catalog
    assert "Impossible à déterminer" in html and "VALEUR PROVISOIRE" in html
    assert "Commencer l&#39;examen" in html
    assert 'name="action"' not in html  # the form appears only once the review started


def test_open_starts_a_timed_session_then_shows_the_five_actions(
    ui: TestClient, hub: FakeHub
) -> None:
    finding = stub_review(hub)
    resp = ui.post(f"/en/review/{finding['id']}/open", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/en/review/{finding['id']}?session=41#decision"
    assert [r.url.path for r in hub.desk.requests if r.method == "POST"] == [
        f"/findings/{finding['id']}/open"
    ]
    html = ui.get(resp.headers["location"]).text
    assert re.findall(r'name="action" value="([^"]+)"', html) == list(ACTIONS)
    assert 'name="session_id" value="41"' in html
    for field in ("annotation", "verdict", "remediation_description", "remediation_due"):
        assert f'<label for="{field}">' in html


def test_accept_with_remediation_is_sent_and_redirects(ui: TestClient, hub: FakeHub) -> None:
    finding = stub_review(hub)
    fid = finding["id"]
    hub.desk.on("POST", f"/findings/{fid}/decisions", {"log": {"seq": 6}})
    form = {
        "session_id": "41",
        "action": "accept-with-remediation",
        "annotation": "Register lacks the firmware version.",
        "verdict": "met",  # ignored: only override-verdict sends a verdict
        "remediation_description": "Add the firmware version.",
        "remediation_due": "2027-01-31",
    }
    resp = ui.post(f"/en/review/{fid}/decide", data=form, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == f"/en/review/{fid}?decided=6#result"
    (sent,) = [
        r for r in hub.desk.requests if r.method == "POST" and r.url.path.endswith("/decisions")
    ]
    assert json.loads(sent.content) == {
        "action": "accept-with-remediation",
        "annotation": "Register lacks the firmware version.",
        "session_id": 41,
        "remediation": {"description": "Add the firmware version.", "due_date": "2027-01-31"},
    }
    hub.desk.on("GET", f"/findings/{fid}/decisions", fixture("decision-history.json"))
    html = ui.get(resp.headers["location"]).text
    assert "Decision recorded as record 6 of the decision log." in html
    assert "Plan of action version 1" in html and "GOVT0000008" in html


@pytest.mark.parametrize(
    ("form", "message"),
    [
        ({}, "decide.error_action"),
        ({"action": "reject"}, "decide.error_annotation"),
        ({"action": "override-verdict", "annotation": "x"}, "decide.error_verdict"),
        ({"action": "accept-with-remediation"}, "decide.error_remediation"),
    ],
)
@pytest.mark.parametrize("lang", ["en", "fr"])
def test_incomplete_decisions_are_explained_and_not_sent(
    ui: TestClient, hub: FakeHub, form: dict[str, str], message: str, lang: str
) -> None:
    finding = stub_review(hub)
    resp = ui.post(f"/{lang}/review/{finding['id']}/decide", data={"session_id": "41", **form})
    assert resp.status_code == 422
    assert Translator(lang)(message).replace("'", "&#39;") in resp.text
    assert 'role="alert"' in resp.text
    assert 'name="session_id" value="41"' in resp.text  # timing continues
    assert not [
        r for r in hub.desk.requests if r.method == "POST" and r.url.path.endswith("/decisions")
    ]


def test_refusal_by_review_desk_is_shown(ui: TestClient, hub: FakeHub) -> None:
    finding = stub_review(hub)
    hub.desk.on(
        "POST",
        f"/findings/{finding['id']}/decisions",
        httpx.Response(409, json={"detail": "finding is already decided"}),
    )
    resp = ui.post(
        f"/en/review/{finding['id']}/decide", data={"session_id": "41", "action": "accept"}
    )
    assert resp.status_code == 422
    assert "The review desk refused the decision: finding is already decided" in resp.text


def test_decision_body_sends_only_what_the_action_needs() -> None:
    t = Translator("en")
    body, errors = decision_body(
        {"action": "override-verdict", "annotation": " Online only. ", "verdict": "not-met"}, t
    )
    assert errors == []
    assert body == {
        "action": "override-verdict",
        "annotation": "Online only.",
        "verdict": "not-met",
    }
    body, errors = decision_body({"action": "accept", "remediation_description": "x"}, t)
    assert body == {"action": "accept", "annotation": ""} and errors == []


def test_decided_finding_has_no_form(ui: TestClient, hub: FakeHub) -> None:
    finding = stub_review(hub)
    hub.desk.on("GET", f"/findings/{finding['id']}", {**finding, "state": "accepted"})
    html = ui.get(f"/en/review/{finding['id']}?session=41").text
    assert 'name="action"' not in html and "Start review" not in html
    assert 'data-state="accepted"' in html


@pytest.mark.parametrize(
    ("lang", "intro", "reason"),
    [
        ("en", "Conflict of interest: you cannot decide this finding",
         "facts (you recorded facts used by the rule-based checks)"),
        ("fr", "Conflit d&#39;intérêts : vous ne pouvez pas trancher cette constatation",
         "des faits (vous avez consigné des faits utilisés"),
    ],
)  # fmt: skip
def test_conflict_of_interest_is_explained(
    ui: TestClient, hub: FakeHub, lang: str, intro: str, reason: str
) -> None:
    """review-desk refuses a reviewer who supplied the system's evidence or facts."""
    finding = stub_review(hub)
    refusal = {"detail": {"code": "conflict-of-interest", "reasons": ["wrote-facts"],
                          "message": "demo-reviewer-01 supplied this system's facts"}}  # fmt: skip
    hub.desk.on("POST", f"/findings/{finding['id']}/decisions", httpx.Response(409, json=refusal))
    resp = ui.post(
        f"/{lang}/review/{finding['id']}/decide",
        data={"session_id": "41", "action": "accept", "annotation": "Looks complete."},
    )
    assert intro in resp.text and reason in resp.text
    assert "demo-reviewer-01 supplied" not in resp.text  # never review-desk's own message
