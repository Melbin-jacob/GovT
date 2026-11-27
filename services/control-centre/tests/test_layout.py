"""Layout, languages, banner, footer and safety headers."""

from __future__ import annotations

import re

import pytest
from cc_support import FakeHub
from fastapi.testclient import TestClient

from control_centre import i18n
from control_centre.app import CSP

FOOTER_EN = (
    "Prototype by Envision Global Consultancy Services Inc. Not a Government of Canada website."
)
FOOTER_FR = (
    "Prototype par Envision Global Consultancy Services Inc. Ce n'est pas un site Web du "
    "gouvernement du Canada."
)
# Wording that would make the page look official. Never on any page.
FORBIDDEN = re.compile(r"canada\.ca|wordmark|symbole du drapeau|flag of canada|\bFIP\b", re.I)


def test_strings_have_the_same_keys_in_both_languages() -> None:
    assert i18n.check_parity() == []
    assert set(i18n.strings("en")) == set(i18n.strings("fr"))


def test_owner_provided_french_strings_are_exact() -> None:
    fr = i18n.strings("fr")
    assert fr["footer.notice"] == FOOTER_FR
    assert fr["note.synthetic"] == "Données d'essai synthétiques, pas une politique réelle"
    assert fr["note.fictional"] == "Systèmes et responsables fictifs"
    assert i18n.provided_by_owner() == {"footer.notice", "note.synthetic", "note.fictional"}
    en = i18n.strings("en")
    assert en["footer.notice"] == FOOTER_EN
    assert en["note.synthetic"] == "Synthetic test data, not real policy"
    assert en["note.fictional"] == "Fictional systems and owners"


def test_root_is_a_bilingual_language_choice(ui: TestClient) -> None:
    html = ui.get("/").text
    assert 'href="/en/"' in html and 'href="/fr/"' in html
    assert ">English<" in html and ">Français<" in html
    assert "Demo only: no authentication." in html
    assert "Démo seulement : aucune authentification." in html
    assert FOOTER_EN in html and FOOTER_FR.replace("'", "&#39;") in html


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_every_page_has_banner_footer_and_language_switch(ui: TestClient, lang: str) -> None:
    resp = ui.get(f"/{lang}/")
    assert resp.status_code == 200
    html = resp.text
    assert f'<html lang="{lang}">' in html
    assert i18n.strings(lang)["banner.demo"].replace("'", "&#39;") in html
    assert FOOTER_EN in html and FOOTER_FR.replace("'", "&#39;") in html
    other = "fr" if lang == "en" else "en"
    assert f'class="lang-switch" href="/{other}/"' in html
    assert 'href="#main"' in html and 'id="main"' in html
    assert not FORBIDDEN.search(html)


def test_language_switch_keeps_path_and_query(ui: TestClient, hub: FakeHub) -> None:
    html = ui.get("/en/?x=1").text
    assert 'href="/fr/?x=1"' in html


def test_unknown_language_is_404(ui: TestClient) -> None:
    assert ui.get("/de/").status_code == 404


def test_security_headers_forbid_other_origins(ui: TestClient) -> None:
    resp = ui.get("/en/")
    assert resp.headers["content-security-policy"] == CSP
    assert "default-src 'self'" in CSP
    assert resp.headers["x-frame-options"] == "DENY"
    css = ui.get("/static/style.css")
    assert css.status_code == 200
    assert "http" not in css.text.replace("http-equiv", "")  # nothing loaded from elsewhere
