"""Screen 6: Rulebook drafts (side by side; approve / edit / reject; publish)."""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
import pytest
from cc_support import (
    DRAFT_BATCH,
    DRAFT_SESSION,
    FakeHub,
    fixture,
    item_id,
    stub_catalog_change,
    stub_drafts,
)
from fastapi.testclient import TestClient

from control_centre.screens.drafts import (
    COOKIE,
    SESSION_COOKIE,
    check_source_date,
    min_source_date,
)

PAGE = f"/{{lang}}/drafts/{DRAFT_BATCH}"


def _json(request: httpx.Request) -> Any:
    return json.loads(request.content)


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_batch_shows_current_clause_change_and_draft_side_by_side(
    ui: TestClient, hub: FakeHub, lang: str
) -> None:
    batch = stub_drafts(hub)
    html = ui.get(PAGE.format(lang=lang)).text
    assert html.count('class="draft-item"') == len(batch["items"]) == 10
    section = html.split(f'id="item-{item_id(batch, "WID-6.1.2")}"')[1].split("</section>")[0]
    current = batch["current_controls"]["WID-6.1.2"][lang]["statement"]
    clauses = batch["plan"]["clauses"][lang]
    draft = next(i for i in batch["items"] if i["target_control"] == "WID-6.1.2")["drafts"][lang]
    for text in (current, clauses["old"]["6.1.2"], clauses["new"]["6.1.2"], draft["statement"]):
        assert _esc(text) in section, text
    assert section.index(_esc(current)) < section.index(_esc(clauses["new"]["6.1.2"]))
    assert "scripted-fake-v1" in section
    # the fixture flags the English draft only (a mismatch the approver must check)
    assert ("badge-obligation-mismatch" in section) is (lang == "en")
    # the page language only: the other language's draft is a link, never shown inline
    other = "fr" if lang == "en" else "en"
    other_draft = next(i for i in batch["items"] if i["target_control"] == "WID-6.1.2")["drafts"][
        other
    ]
    assert _esc(other_draft["statement"]) not in html
    assert f'href="/{other}/drafts/{DRAFT_BATCH}#item-' in section
    assert 'data-note="synthetic"' in html


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("'", "&#39;").replace('"', "&#34;")


def test_needs_human_reason_and_no_model_items(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    html = ui.get(PAGE.format(lang="fr")).text
    section = html.split(f'id="item-{item_id(batch, "WID-6.4.2")}"')[1].split("</section>")[0]
    assert 'data-draft-status="needs-human"' in section
    assert "la confiance du modèle est inférieure au seuil" in section
    assert "Ce n&#39;est qu&#39;une suggestion du modèle" in section
    en = ui.get(PAGE.format(lang="en")).text
    reference = en.split(f'id="item-{item_id(batch, "WID-6.2.2")}"')[1].split("</section>")[0]
    assert "Only the numbering changed" in reference and "6.3.2" in reference
    assert 'name="statement"' not in reference  # nothing to edit, only approve / reject
    retire = en.split(f'id="item-{item_id(batch, "WID-6.3.2")}"')[1].split("</section>")[0]
    assert "the control is retired" in retire
    new = en.split(f'id="item-{item_id(batch, "WID-C001")}"')[1].split("</section>")[0]
    assert "WID-C001" in new and 'name="proposed_id" value="WID-C001"' in new
    assert "New section: Risk assessment (widgets-G01)" in new


def test_approve_sends_the_acting_persons_identity(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    iid = item_id(batch, "WID-6.1.2")
    hub.rulebook.on("POST", f"/drafts/items/{iid}/approve", {"id": iid, "status": "approved"})
    ui.cookies.set(COOKIE, "demo-officer-02")
    resp = ui.post(
        f"/en/drafts/{DRAFT_BATCH}/items/{iid}/approve",
        data={"both_languages": "yes"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "notice=approved" in resp.headers["location"]
    (sent,) = [r for r in hub.rulebook.requests if r.method == "POST"]
    assert sent.headers["X-GovHub-User"] == "demo-officer-02"
    assert sent.headers["X-GovHub-Role"] == "governance-officer"


def test_approve_needs_the_both_languages_confirmation(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    iid = item_id(batch, "WID-6.1.2")
    resp = ui.post(f"/fr/drafts/{DRAFT_BATCH}/items/{iid}/approve", follow_redirects=False)
    assert "error=confirm-both" in resp.headers["location"]
    assert not [r for r in hub.rulebook.requests if r.method == "POST"]
    html = ui.get(resp.headers["location"]).text
    assert "Confirmez avoir lu les ébauches dans les deux langues" in html
    assert 'role="alert"' in html


@pytest.mark.parametrize(
    ("lang", "message"),
    [
        ("en", "Two-person rule: you last edited this draft"),
        ("fr", "Règle des deux personnes : vous avez modifié cette ébauche en dernier"),
    ],
)
def test_two_person_rule_refusal_is_shown_with_its_reason(
    ui: TestClient, hub: FakeHub, lang: str, message: str
) -> None:
    """The rulebook enforces the rule (409 two-person-rule); the screen explains it."""
    batch = stub_drafts(hub)
    iid = item_id(batch, "WID-C002")
    refusal = fixture("drafts-error.two-person-rule.json")
    hub.rulebook.on("POST", f"/drafts/items/{iid}/approve", httpx.Response(409, json=refusal))
    resp = ui.post(
        f"/{lang}/drafts/{DRAFT_BATCH}/items/{iid}/approve",
        data={"both_languages": "yes"},
        follow_redirects=False,
    )
    assert "error=two-person-rule" in resp.headers["location"]
    assert resp.headers["location"].endswith(f"#item-{iid}")
    html = ui.get(resp.headers["location"]).text
    section = html.split(f'id="item-{iid}"')[1].split("</section>")[0]
    assert message in section and message in html.split("</main>")[0]


def test_last_editor_sees_the_two_person_note(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    for item in batch["items"]:
        if item["proposed_id"] == "WID-C002":
            item["last_edited_by"] = "demo-officer-01"
    html = ui.get(PAGE.format(lang="en")).text  # acting as demo-officer-01 (default)
    section = html.split(f'id="item-{item_id(batch, "WID-C002")}"')[1].split("</section>")[0]
    assert "Last edited by demo-officer-01." in section
    assert "another governance officer must approve it (two-person rule)" in section
    ui.cookies.set(COOKIE, "demo-officer-02")
    other = ui.get(PAGE.format(lang="en")).text
    assert (
        "two-person rule)"
        not in other.split(f'id="item-{item_id(batch, "WID-C002")}"')[1].split("</section>")[0]
    )


def test_edit_sends_only_the_page_language(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    iid = item_id(batch, "WID-C001")
    hub.rulebook.on("PUT", f"/drafts/items/{iid}", {"id": iid})
    ui.cookies.set(COOKIE, "demo-reviewer-01")
    resp = ui.post(
        f"/fr/drafts/{DRAFT_BATCH}/items/{iid}/edit",
        data={"statement": " Texte corrigé. ", "obligation": "must", "check_type": "judgment",
              "proposed_id": "WID-C007"},
        follow_redirects=False,
    )  # fmt: skip
    assert "notice=edited" in resp.headers["location"]
    (sent,) = [r for r in hub.rulebook.requests if r.method == "PUT"]
    assert _json(sent) == {
        "languages": {
            "fr": {"statement": "Texte corrigé.", "no_change": False, "obligation": "must",
                   "check_type": "judgment"}
        },
        "proposed_id": "WID-C007",
    }  # fmt: skip
    assert sent.headers["X-GovHub-Role"] == "reviewer"


def test_id_reuse_refusal_is_translated(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    iid = item_id(batch, "WID-C001")
    hub.rulebook.on(
        "PUT", f"/drafts/items/{iid}",
        httpx.Response(422, json={"detail": {"code": "id-used", "message": "WID-6.1.1 used"}}),
    )  # fmt: skip
    resp = ui.post(
        f"/fr/drafts/{DRAFT_BATCH}/items/{iid}/edit",
        data={"statement": "x", "proposed_id": "WID-6.1.1"},
    )
    assert "les identifiants ne sont jamais réutilisés" in resp.text


def test_reviewer_cannot_approve(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    iid = item_id(batch, "WID-6.1.2")
    hub.rulebook.on(
        "POST", f"/drafts/items/{iid}/approve",
        httpx.Response(403, json={"detail": {"code": "role", "message": "officers only"}}),
    )  # fmt: skip
    ui.cookies.set(COOKIE, "demo-reviewer-01")
    resp = ui.post(f"/en/drafts/{DRAFT_BATCH}/items/{iid}/approve", data={"both_languages": "yes"})
    assert "only a governance officer approves or rejects" in resp.text


def test_reject_needs_a_reason(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    iid = item_id(batch, "WID-6.4.2")
    hub.rulebook.on("POST", f"/drafts/items/{iid}/reject", {"id": iid})
    html = ui.get(PAGE.format(lang="en")).text
    section = html.split(f'id="item-{iid}"')[1].split("</section>")[0]
    assert re.search(r'<input id="reason-[^"]+" name="reason" required', section)
    ui.post(f"/en/drafts/{DRAFT_BATCH}/items/{iid}/reject", data={"reason": "Wrong year."})
    (sent,) = [r for r in hub.rulebook.requests if r.url.path.endswith("/reject")]
    assert _json(sent)["reason"] == "Wrong year."


def test_source_date_rules() -> None:
    assert min_source_date("2026-11-28T00:00:00Z") == "2026-11-29"
    assert check_source_date("2026-11-29", "2026-11-28T00:00:00Z") == "2026-11-29T00:00:00Z"
    assert check_source_date("2026-11-28", "2026-11-28T00:00:00Z") is None  # not later
    assert check_source_date("2025-01-01", "2026-11-28T00:00:00Z") is None
    assert check_source_date("29/11/2026", "2026-11-28T00:00:00Z") is None


def test_publish_form_defaults_to_a_date_the_guard_accepts(ui: TestClient, hub: FakeHub) -> None:
    stub_drafts(hub, "decided")
    html = ui.get(PAGE.format(lang="en")).text
    assert 'value="2026-11-29" min="2026-11-29"' in html
    assert "Publish version 1.1.0" in html
    assert "later than the previous source date (2026-11-28)" in html


def test_publish_refuses_a_date_the_guard_would_refuse_before_calling(
    ui: TestClient, hub: FakeHub
) -> None:
    stub_drafts(hub, "decided")
    resp = ui.post(
        f"/fr/drafts/{DRAFT_BATCH}/publish", data={"source_date": "2026-11-28"},
        follow_redirects=False,
    )  # fmt: skip
    assert "error=source-date" in resp.headers["location"]
    assert not [r for r in hub.rulebook.requests if r.method == "POST"]
    html = ui.get(resp.headers["location"]).text
    assert "le contrôle de SOURCE_DATE la refuserait" in html


def test_publish_sends_the_chosen_date(ui: TestClient, hub: FakeHub) -> None:
    stub_drafts(hub, "decided")
    hub.rulebook.on(
        "POST", f"/drafts/batches/{DRAFT_BATCH}/publish", fixture("drafts-published.json")
    )
    resp = ui.post(
        f"/en/drafts/{DRAFT_BATCH}/publish", data={"source_date": "2026-12-03"},
        follow_redirects=False,
    )  # fmt: skip
    assert "notice=published" in resp.headers["location"]
    (sent,) = [r for r in hub.rulebook.requests if r.method == "POST"]
    assert _json(sent) == {"source_date": "2026-12-03T00:00:00Z"}
    assert sent.headers["X-GovHub-Role"] == "governance-officer"


def test_publish_waits_for_every_decision(ui: TestClient, hub: FakeHub) -> None:
    stub_drafts(hub, "open")
    html = ui.get(PAGE.format(lang="en")).text
    assert "Every item needs a decision" in html and 'name="source_date"' not in html


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_published_batch_links_to_the_catalog_change_impact(
    ui: TestClient, hub: FakeHub, lang: str
) -> None:
    batch = stub_drafts(hub, "published")
    html = ui.get(PAGE.format(lang=lang)).text
    assert 'data-published="1.1.0"' in html
    assert f'href="/{lang}/impact?catalog_from=1.0.0&amp;catalog_to=1.1.0"' in html
    assert 'name="both_languages"' not in html  # decided: no more forms
    for item in batch["items"]:
        assert f'data-decision="{item["status"]}"' in html
    assert "badge-status-approved" in html


def test_start_plans_then_asks_the_engine(ui: TestClient, hub: FakeHub) -> None:
    stub_drafts(hub)
    hub.rulebook.on("POST", "/drafts/batches", {"id": DRAFT_BATCH})
    hub.engine.on("POST", f"/drafting/batches/{DRAFT_BATCH}/draft", {"drafted": 14})
    resp = ui.post(
        "/en/drafts",
        data={"catalog": "example-widgets", "version": "1.0.0", "instrument": "example-widgets",
              "from": "2023-01-01", "to": "2025-01-01"},
        follow_redirects=False,
    )  # fmt: skip
    assert resp.headers["location"] == f"/en/drafts/{DRAFT_BATCH}?notice=drafted"
    (plan,) = [r for r in hub.rulebook.requests if r.method == "POST"]
    assert (
        _json(plan)["from"] == "2023-01-01" and plan.headers["X-GovHub-User"] == "demo-officer-01"
    )
    assert [r.url.path for r in hub.engine.requests] == [f"/drafting/batches/{DRAFT_BATCH}/draft"]


def test_list_and_acting_as(ui: TestClient, hub: FakeHub) -> None:
    stub_drafts(hub)
    html = ui.get("/fr/drafts").text
    assert f'href="/fr/drafts/{DRAFT_BATCH}"' in html
    assert "agent de gouvernance" in html and "Agir en tant que (démo)" in html
    resp = ui.post(
        "/fr/drafts/actor", data={"actor": "demo-reviewer-01", "back": f"/fr/drafts/{DRAFT_BATCH}"},
        follow_redirects=False,
    )  # fmt: skip
    assert resp.headers["location"] == f"/fr/drafts/{DRAFT_BATCH}"
    assert f"{COOKIE}=demo-reviewer-01" in resp.headers["set-cookie"]
    bad = ui.post("/fr/drafts/actor", data={"actor": "root", "back": "//evil.example"},
                  follow_redirects=False)  # fmt: skip
    assert bad.headers["location"] == "/fr/drafts" and "set-cookie" not in bad.headers


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_impact_screen_shows_a_catalog_change(ui: TestClient, hub: FakeHub, lang: str) -> None:
    """The impact report generated from the version the drafts produced (1.0.0 -> 1.1.0)."""
    stub_catalog_change(hub)
    html = ui.get(f"/{lang}/impact?catalog_from=1.0.0&catalog_to=1.1.0").text
    report = fixture(f"impact-catalog.{lang}.json")
    assert report["report_id"] in html and 'data-trigger="catalog"' in html
    for control in report["affected_controls"]:
        assert control["id"] in html
    assert "WID-6.1.1, WID-6.2.2, WID-6.2.3, WID-6.4.1" in html  # renumbered only
    (sent,) = [r for r in hub.rulebook.requests if r.method == "POST"]
    assert "source" not in _json(sent)


def _posts(hub: FakeHub, suffix: str) -> list[httpx.Request]:
    return [r for r in hub.rulebook.requests if r.method == "POST" and r.url.path.endswith(suffix)]


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_opening_a_page_records_that_languages_view(
    ui: TestClient, hub: FakeHub, lang: str
) -> None:
    """The server, not the checkbox, knows which languages the approver opened."""
    stub_drafts(hub)
    ui.cookies.set(COOKIE, "demo-officer-02")
    resp = ui.get(PAGE.format(lang=lang))
    (started,) = _posts(hub, "/drafts/sessions")
    assert started.headers["X-GovHub-User"] == "demo-officer-02"
    (view,) = _posts(hub, "/views")
    assert _json(view) == {"session_id": DRAFT_SESSION, "lang": lang}
    assert view.headers["X-GovHub-User"] == "demo-officer-02"
    shown = [
        r
        for r in hub.rulebook.requests
        if r.method == "GET"
        and r.url.path == f"/drafts/batches/{DRAFT_BATCH}"
        and "session_id" in r.url.params
    ]
    assert shown and shown[-1].url.params["session_id"] == DRAFT_SESSION
    assert f"demo-officer-02 {DRAFT_SESSION}" in resp.headers["set-cookie"].replace('"', "")


def test_the_session_is_reused_and_sent_with_the_approval(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    iid = item_id(batch, "WID-6.1.2")
    hub.rulebook.on("POST", f"/drafts/items/{iid}/approve", {"id": iid})
    ui.get(PAGE.format(lang="en"))
    ui.get(PAGE.format(lang="fr"))
    assert len(_posts(hub, "/drafts/sessions")) == 1  # one session, both languages in it
    assert [_json(v)["lang"] for v in _posts(hub, "/views")] == ["en", "fr"]
    ui.post(f"/en/drafts/{DRAFT_BATCH}/items/{iid}/approve", data={"both_languages": "yes"})
    (approved,) = _posts(hub, "/approve")
    assert _json(approved)["session_id"] == DRAFT_SESSION


def test_another_person_gets_another_session(ui: TestClient, hub: FakeHub) -> None:
    stub_drafts(hub)
    ui.get(PAGE.format(lang="en"))
    resp = ui.post("/en/drafts/actor", data={"actor": "demo-officer-02", "back": PAGE.format(lang="en")},
                   follow_redirects=False)  # fmt: skip
    assert (
        f'{SESSION_COOKIE}=""' in resp.headers["set-cookie"]
        or "Max-Age=0" in resp.headers["set-cookie"]
    )
    # A session cookie that belongs to someone else is never sent for this person.
    ui.cookies.set(COOKIE, "demo-officer-02")
    ui.cookies.set(SESSION_COOKIE, f'"demo-officer-01 {DRAFT_SESSION}"')
    batch = fixture("drafts-batch.open.json")
    iid = item_id(batch, "WID-6.1.2")
    hub.rulebook.on("POST", f"/drafts/items/{iid}/approve", {"id": iid})
    ui.post(f"/en/drafts/{DRAFT_BATCH}/items/{iid}/approve", data={"both_languages": "yes"})
    assert _json(_posts(hub, "/approve")[-1])["session_id"] is None


@pytest.mark.parametrize(
    ("lang", "message"),
    [
        ("en", "Open this draft in both languages"),
        ("fr", "Ouvrez cette ébauche dans les deux langues"),
    ],
)
def test_not_read_refusal_is_shown(ui: TestClient, hub: FakeHub, lang: str, message: str) -> None:
    batch = stub_drafts(hub)
    iid = item_id(batch, "WID-6.1.2")
    refusal = {"detail": {"code": "not-read", "message": "not opened in this session: fr"}}
    hub.rulebook.on("POST", f"/drafts/items/{iid}/approve", httpx.Response(409, json=refusal))
    resp = ui.post(
        f"/{lang}/drafts/{DRAFT_BATCH}/items/{iid}/approve", data={"both_languages": "yes"}
    )
    section = resp.text.split(f'id="item-{iid}"')[1].split("</section>")[0]
    assert message in section


def test_read_status_is_shown_per_item(ui: TestClient, hub: FakeHub) -> None:
    batch = stub_drafts(hub)
    for entry in batch["items"]:
        entry["read"] = {"en": "2026-11-28T10:00:00+00:00", "fr": None}
    html = ui.get(PAGE.format(lang="fr")).text
    section = html.split(f'id="item-{item_id(batch, "WID-6.1.2")}"')[1].split("</section>")[0]
    assert 'data-read-en="yes" data-read-fr="no"' in section
    assert (
        "ébauche en anglais ouverte" in section
        and "ébauche en français pas encore ouverte" in section
    )


def test_a_published_batch_records_no_views(ui: TestClient, hub: FakeHub) -> None:
    stub_drafts(hub, "published")
    ui.get(PAGE.format(lang="en"))
    assert not _posts(hub, "/drafts/sessions") and not _posts(hub, "/views")
