"""The 3-minute evaluator demo, clicked through in a real browser, in EN and FR.

Needs the synthetic demo data (``scripts/demo-review.sh``): open findings in the queue,
a decision log with external checkpoints, the fictional inventory with a data gap.
"""

from __future__ import annotations

import re
import time

from e2e_support import TIMINGS, Recorder
from playwright.sync_api import Page, expect
from test_french_pages import english_phrases

PHRASES = english_phrases()


def assert_no_english(page: Page) -> None:
    """The French page's main content holds none of the known English phrases."""
    text = page.locator("main").inner_text()
    leaks = sorted(p for p in PHRASES if p in text)
    assert not leaks, f"{page.url}: English text on a French page: {leaks}"


def _open_first_open_finding(page: Page, start_label: str) -> None:
    rows = page.locator("table[data-table=queue] tbody tr")
    expect(rows.first).to_be_visible()
    # Take an "open" finding (not one already awaiting evidence).
    for i in range(rows.count()):
        row = rows.nth(i)
        if row.locator("td").nth(5).inner_text().strip() in ("Open", "Ouverte"):
            row.locator("a").first.click()
            break
    else:
        raise AssertionError("no open finding in the queue: run scripts/demo-review.sh")
    page.get_by_role("button", name=start_label).click()
    expect(page.locator('input[name="session_id"]')).to_have_count(1)


def test_english_demo_click_through(rec: Recorder) -> None:
    """Screens 1 -> 5 as an evaluator would follow them. Timed end to end."""
    page = rec.page
    start = time.perf_counter()

    page.goto("/")
    rec.capture("en-0-choose-language")
    page.get_by_role("link", name="English").click()
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.get_by_text("Demo mode: fictional users, no sign-in.")).to_be_visible()

    # 1. Policy change
    page.get_by_role("link", name="1. Policy change").click()
    page.get_by_label("Older version").select_option("2023-01-01")
    page.get_by_label("Newer version").select_option("2025-01-01")
    page.get_by_role("button", name="Compare").click()
    expect(page.get_by_text("Synthetic test data, not real policy")).to_be_visible()
    expect(page.locator('tr[data-flags^="obligation-change"]')).to_contain_text("must")
    expect(page.locator('tr[data-flags^="split"]')).to_contain_text("6.4.2")
    rec.capture("en-1-policy-change")

    # 2. Impact report
    page.get_by_role("link", name="See the impact of this change").click()
    expect(page.locator("table[data-table=systems] tbody tr").first).to_contain_text("IV")
    expect(page.locator("table[data-table=tasks]")).to_contain_text("GOVT")
    expect(page.locator("table[data-table=capacity]")).to_contain_text("PLACEHOLDER")
    rec.capture("en-2-impact-report")

    # 3. Review queue -> finding -> decision
    page.get_by_role("link", name="Go to the review queue").click()
    rec.capture("en-3-review-queue")
    _open_first_open_finding(page, "Start review")
    page.get_by_label("Accept with remediation").check()
    page.get_by_label("Reason or note").fill("Register lacks the firmware version field.")
    page.get_by_label("Remediation to do").fill("Add the firmware version to the register.")
    page.get_by_label("Remediation due date").fill("2027-02-26")
    rec.capture("en-3-finding-decision")
    page.get_by_role("button", name="Record decision").click()
    expect(page.get_by_role("status")).to_contain_text("Decision recorded as record")
    expect(page.locator("table[data-table=history]")).to_contain_text("Plan of action version")

    # 4. Decision log, verified against both external checkpoints
    page.get_by_role("link", name="See the decision log").click()
    page.get_by_role("button", name="Verify the log").click()
    expect(page.locator("#verify-result")).to_have_attribute("data-ok", "true")
    expect(page.locator("#verify-result")).to_contain_text("external checkpoints match")
    expect(page.locator('tr[data-source="file"]')).to_have_attribute("data-state", "in-step")
    expect(page.locator('tr[data-source="servicenow"]')).to_have_attribute("data-state", "in-step")
    rec.capture("en-4-decision-log")

    # 5. Inventory with a data gap
    page.get_by_role("link", name="5. System inventory").click()
    expect(page.get_by_text("Fictional systems and owners")).to_be_visible()
    expect(page.locator('tr[data-system="SYS-009"]')).to_contain_text("Missing: owner")
    rec.capture("en-5-inventory")

    total = time.perf_counter() - start
    TIMINGS["en click-through, total (incl. screenshots and axe scans)"] = total
    TIMINGS["en click-through, browser time only"] = total - rec.overhead


def test_french_screens(rec: Recorder) -> None:
    """Every screen in French, through the language switch, with a French decision."""
    page = rec.page
    start = time.perf_counter()
    page.goto("/")
    page.get_by_role("link", name="Français").click()
    expect(page.locator("html")).to_have_attribute("lang", "fr")
    expect(page.get_by_text("Mode démo : utilisateurs fictifs, sans connexion.")).to_be_visible()
    rec.capture("fr-0-overview")
    assert_no_english(page)

    page.get_by_role("link", name="1. Changement de politique").click()
    expect(
        page.get_by_text("Données d'essai synthétiques, pas une politique réelle")
    ).to_be_visible()
    expect(page.locator('tr[data-flags^="obligation-change"]')).to_contain_text("doivent")
    rec.capture("fr-1-policy-change")
    assert_no_english(page)

    page.get_by_role("link", name="2. Rapport d'incidence").click()
    expect(page.locator("table[data-table=tasks]")).to_contain_text("GOVT")
    rec.capture("fr-2-impact-report")
    assert_no_english(page)

    page.get_by_role("link", name="3. File d'examen").click()
    rec.capture("fr-3-review-queue")
    assert_no_english(page)
    _open_first_open_finding(page, "Commencer l'examen")
    page.get_by_label("Demander d'autres preuves").check()
    page.get_by_label("Motif ou note").fill("Joindre le registre d'étalonnage de 2026.")
    rec.capture("fr-3-finding-decision")
    assert_no_english(page)
    page.get_by_role("button", name="Consigner la décision").click()
    expect(page.get_by_role("status")).to_contain_text("Décision consignée")
    assert_no_english(page)

    page.get_by_role("link", name="4. Registre des décisions").click()
    page.get_by_role("button", name="Vérifier le registre").click()
    expect(page.locator("#verify-result")).to_have_attribute("data-ok", "true")
    rec.capture("fr-4-decision-log")
    assert_no_english(page)

    page.get_by_role("link", name="5. Inventaire des systèmes").click()
    expect(page.get_by_text("Systèmes et responsables fictifs")).to_be_visible()
    expect(page.locator('tr[data-system="SYS-009"]')).to_contain_text("Manquant")
    rec.capture("fr-5-inventory")
    assert_no_english(page)

    # The switch keeps the page: back to English on the same screen.
    page.get_by_role("link", name="English").click()
    expect(page).to_have_url(re.compile(r"/en/inventory$"))
    TIMINGS["fr screens, total (incl. screenshots and axe scans)"] = time.perf_counter() - start


def test_keyboard_only_decision(rec: Recorder) -> None:
    """Skip link, navigation and a full decision without a mouse."""
    page = rec.page
    page.goto("/en/")
    page.keyboard.press("Tab")
    skip = page.get_by_role("link", name="Skip to main content")
    expect(skip).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("main")).to_be_focused()

    page.goto("/en/review")
    links = page.locator("table[data-table=queue] tbody tr a")
    expect(links.first).to_be_visible()
    target = None
    for i in range(links.count()):
        row = page.locator("table[data-table=queue] tbody tr").nth(i)
        if row.locator("td").nth(5).inner_text().strip() == "Open":
            target = links.nth(i)
            break
    assert target is not None, "no open finding left in the queue"
    target.focus()
    page.keyboard.press("Enter")
    start_button = page.get_by_role("button", name="Start review")
    start_button.focus()
    page.keyboard.press("Enter")
    accept = page.get_by_label("Accept", exact=True)
    accept.focus()
    page.keyboard.press("Space")
    expect(accept).to_be_checked()
    page.keyboard.press("Tab")  # leaves the radio group for the next field
    page.get_by_label("Reason or note").focus()
    page.keyboard.type("Checked with the keyboard only.")
    page.get_by_role("button", name="Record decision").focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("status")).to_contain_text("Decision recorded as record")


def _open_finding(page: Page, base: str, system: str, control: str, lang: str) -> None:
    page.goto(f"/{lang}/review")
    row = page.locator("table[data-table=queue] tbody tr", has_text=system).filter(has_text=control)
    expect(row).to_have_count(1)
    row.locator("a").first.click()


def test_engine_draft_with_flagged_evidence(rec: Recorder) -> None:
    """After scripts/demo-assessment.sh: the register finding of SYS-003 carries a model
    draft that the engine downgraded because the evidence holds an injected instruction."""
    page = rec.page
    for lang in ("en", "fr"):
        _open_finding(page, rec.base_url, "SYS-003", "WID-6.3.2", lang)
        expect(page.locator('[data-assessment="model"]')).to_be_visible()
        expect(page.locator("[data-flagged]")).to_be_visible()
        expect(page.locator("[data-flagged] blockquote").first).to_contain_text(
            "ignore previous instructions"
        )
        rec.capture(f"{lang}-3-finding-engine-draft")
        if lang == "fr":
            expect(page.get_by_text("Ébauche du modèle")).to_be_visible()
            assert_no_english(page)
