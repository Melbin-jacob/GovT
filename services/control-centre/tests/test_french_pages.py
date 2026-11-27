"""No English generated text on French pages.

Every French screen is rendered (with canned hub responses captured from the synthetic
demo) and its main content is scanned for known English phrases: the literal parts of the
rulebook's English explanation templates, the English UI strings, and the English text
review-desk writes (placeholder rationale, verification problems, side-effect statuses).
Data (system names, people's annotations) is not template text and is not scanned for.
"""

from __future__ import annotations

import html as htmlmod
import re
import tomllib
from pathlib import Path

import pytest
from cc_support import (
    MODEL_DRAFT,
    FakeHub,
    fixture,
    stub_engine,
    stub_impact,
    stub_inventory,
    stub_log,
    stub_review,
)
from fastapi.testclient import TestClient

from control_centre import i18n

ROOT = Path(__file__).parents[3]
EXPLANATIONS = ROOT / "services/rulebook/src/rulebook/locales/explanations.en.toml"
ENGINE_MESSAGES = ROOT / "services/assessment-engine/src/assessment_engine/locales/messages.en.toml"
# English that review-desk and the old report format produced (must never reach FR pages).
REVIEW_DESK_ENGLISH = [
    "Placeholder finding: the assessment engine does not exist yet",
    "a reviewer decides from the evidence",
    "log ends at seq",
    "hash differs from the checkpoint",
    "record content does not match its hash",
    "records removed from the end",
    "not sent",
    "Due date basis",
    "changed (similarity",
    "generated details are in English",
]


def _fragments(template: str) -> list[str]:
    pieces = (p.strip(" .:;,()[]") for p in re.split(r"\{[^}]*\}", template))
    return [p for p in pieces if len(p) >= 8]


def english_phrases() -> set[str]:
    phrases = set(REVIEW_DESK_ENGLISH)
    for template in tomllib.loads(EXPLANATIONS.read_text("utf-8"))["templates"].values():
        phrases.update(_fragments(template))
    for template in tomllib.loads(ENGINE_MESSAGES.read_text("utf-8"))["messages"].values():
        phrases.update(_fragments(template))
    en, fr = i18n.strings("en"), i18n.strings("fr")
    for key, text in en.items():
        if text != fr[key]:
            phrases.update(p for p in _fragments(text) if len(p) >= 12)
    return phrases


def main_text(page: str) -> str:
    """Visible text of <main>, without passages marked as another language (evidence is
    data in its own language; the footer is bilingual by design)."""
    main = page.split("<main", 1)[1].split("</main>", 1)[0]
    main = re.sub(r'<blockquote class="quote" lang="en">.*?</blockquote>', " ", main, flags=re.S)
    main = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", main, flags=re.S)
    return htmlmod.unescape(re.sub(r"<[^>]+>", " ", main))


def french_pages(ui: TestClient, hub: FakeHub) -> dict[str, str]:
    stub_impact(hub)
    finding = stub_review(hub)
    stub_log(hub)
    stub_inventory(hub)
    fid = finding["id"]
    pages = {
        "overview": "/fr/",
        "policy": "/fr/policy-change",
        "impact": "/fr/impact",
        "queue": "/fr/review",
        "finding": f"/fr/review/{fid}",
        "finding-form": f"/fr/review/{fid}?session=41",
        "log": "/fr/decision-log",
        "log-verified": "/fr/decision-log?verify=true&trust=file&trust=servicenow",
        "inventory": "/fr/inventory",
    }
    out = {name: ui.get(url).text for name, url in pages.items()}
    # A decided finding with its follow-up, and a failed verification.
    hub.desk.on("GET", f"/findings/{fid}/decisions", fixture("decision-history.json"))
    out["finding-decided"] = ui.get(f"/fr/review/{fid}?decided=6").text
    hub.desk.on(
        "GET",
        "/decision-log/verify",
        {
            **fixture("verify.json"),
            "ok": False,
            "problems": ["log ends at seq 3 but checkpoint says 5 (records removed ...)"],
            "issues": [
                {
                    "code": "truncated",
                    "params": {
                        "head": 3,
                        "checkpoint": 5,
                        "source_kind": "servicenow",
                        "source_name": "GOVT0000002",
                    },
                },
                {"code": "content-modified", "params": {"seq": 2}},
            ],
        },
    )
    out["log-failed"] = ui.get("/fr/decision-log?verify=true&trust=servicenow").text
    # A finding with a model draft that was downgraded because of flagged evidence.
    hub.desk.on(
        "GET", f"/findings/{fid}", {**finding, "placeholder": False, "assessment": MODEL_DRAFT}
    )
    stub_engine(hub, finding["system_id"])
    out["finding-assessed"] = ui.get(f"/fr/review/{fid}?notice=assessed").text
    return out


def test_phrase_list_is_meaningful() -> None:
    phrases = english_phrases()
    assert "split into" in phrases or any("split into" in p for p in phrases)
    assert any("Reassess" in p for p in phrases)
    assert len(phrases) > 100


def test_no_english_generated_text_on_any_french_page(ui: TestClient, hub: FakeHub) -> None:
    phrases = english_phrases()
    leaks: dict[str, list[str]] = {}
    for name, page in french_pages(ui, hub).items():
        text = main_text(page)
        found = sorted(p for p in phrases if p in text)
        if found:
            leaks[name] = found
    assert leaks == {}


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        ("impact", "Disposition 6.3.1 scindée en 6.4.1 et 6.4.2"),
        ("impact", "Réévaluer 5 contrôle(s) pour Sample Benefits Triage Assistant (fictional)"),
        ("finding", "Disposition 6.1.2 modifiée (similarité 0,84)"),
        ("finding", "Constatation provisoire"),
        ("finding-decided", "Plan d'action, version 1"),
        ("log-failed", "Le registre se termine à l'enregistrement 3"),
        ("log-failed", "Enregistrement 2 : son contenu ne correspond plus"),
        ("policy", "Les dispositions identiques sont jumelées d'abord."),
        ("finding-assessed", "injection d'invite possible"),
        ("finding-assessed", "Un texte ressemblant à des instructions a été trouvé"),
    ],
)
def test_french_pages_show_the_french_text(
    ui: TestClient, hub: FakeHub, page: str, expected: str
) -> None:
    assert expected in main_text(french_pages(ui, hub)[page])


def test_the_scan_catches_english(ui: TestClient, hub: FakeHub) -> None:
    """A finding stored before this change carries an English reason string: caught."""
    finding = stub_review(hub)
    legacy = {
        **finding,
        "reasons": ["clause changed: clause 6.1.2 -> 6.1.2 changed (similarity 0.8387)"],
    }
    hub.desk.on("GET", f"/findings/{finding['id']}", legacy)
    text = main_text(ui.get(f"/fr/review/{finding['id']}").text)
    assert "changed (similarity" in {p for p in english_phrases() if p in text}
