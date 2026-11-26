"""French typography is ignored for matching; original text is never altered."""

from __future__ import annotations

import pytest

from rulebook.sources.normalize import clean_original, match_tokens, normalize_for_match

NBSP, NNBSP = " ", " "


@pytest.mark.parametrize(
    ("a", "b"),
    [
        pytest.param(f"Article{NBSP}6", "Article 6", id="no-break-space"),
        pytest.param(f"Note{NNBSP}: voir", "Note : voir", id="narrow-no-break-space"),
        pytest.param(f"Note{NBSP}: voir", "Note: voir", id="space-before-colon"),
        pytest.param(f"le «{NNBSP}registre{NNBSP}»", "le « registre »", id="guillemets-nnbsp"),
        pytest.param("le « registre »", "le «registre»", id="guillemets-inner-space"),
        pytest.param("le « registre »", 'le "registre"', id="guillemets-vs-straight"),
        pytest.param("le “registre”", 'le "registre"', id="curly-double-quotes"),
        pytest.param("l’emplacement", "l'emplacement", id="right-single-quote"),
        pytest.param("l‘emplacement", "l'emplacement", id="left-single-quote"),
        pytest.param("lʼemplacement", "l'emplacement", id="modifier-apostrophe"),
        pytest.param("mise en œuvre", "mise en oeuvre", id="ligature-oe"),
        pytest.param("Œuvre", "OEuvre", id="ligature-OE"),
        pytest.param("curriculum vitæ", "curriculum vitae", id="ligature-ae"),
        pytest.param("ﬁchier", "fichier", id="ligature-fi"),
        pytest.param("ﬂux", "flux", id="ligature-fl"),
        pytest.param("2023–2025", "2023-2025", id="en-dash"),
        pytest.param("a — b", "a - b", id="em-dash"),
        pytest.param("Shall  Apply\n\tnow", "shall apply now", id="case-and-whitespace"),
    ],
)
def test_equal_for_matching(a: str, b: str) -> None:
    assert normalize_for_match(a) == normalize_for_match(b)
    assert match_tokens(a) == match_tokens(b)


@pytest.mark.parametrize(
    ("a", "b"),
    [
        pytest.param("été", "ete", id="accents-are-significant"),
        pytest.param("doit", "doivent", id="different-words"),
        pytest.param("must", "should", id="obligation-words"),
    ],
)
def test_not_equal_for_matching(a: str, b: str) -> None:
    assert normalize_for_match(a) != normalize_for_match(b)


def test_apostrophe_splits_words_for_tokens() -> None:
    assert match_tokens("l’emplacement du « registre »") == ["l", "emplacement", "du", "registre"]


def test_original_text_is_kept() -> None:
    original = f"le «{NNBSP}registre{NNBSP}» de l’œuvre{NBSP}:  voir\n  ﬁchier"
    cleaned = clean_original(original)
    # Only runs of ordinary whitespace are collapsed; every typographic character survives.
    assert cleaned == f"le «{NNBSP}registre{NNBSP}» de l’œuvre{NBSP}: voir ﬁchier"
    assert NNBSP in cleaned and NBSP in cleaned and "’" in cleaned and "œ" in cleaned
