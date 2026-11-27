from __future__ import annotations

import pytest

from rulebook.obligations import obligation_changed, obligation_terms


@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("The department must publish.", "en", {"must": 1}),
        (
            "It SHALL and Should; it may. Approval is required.",
            "en",
            {"shall": 1, "should": 1, "may": 1, "required": 1},
        ),
        ("The mayor is mustard-yellow; requirements apply.", "en", {}),
        (
            "Le ministère doit publier; les avis doivent être clairs.",
            "fr",
            {"doit": 1, "doivent": 1},
        ),
        (
            "Il peut, elles peuvent; l'administrateur est tenu de; elle est  tenue de.",
            "fr",
            {"peut": 1, "peuvent": 1, "est tenu": 2},
        ),
        ("Le doigt et la peuplade.", "fr", {}),
        (None, "en", {}),
    ],
)
def test_obligation_terms(text: str | None, lang: str, expected: dict[str, int]) -> None:
    assert dict(obligation_terms(text, lang)) == expected  # type: ignore[arg-type]


def test_obligation_changed() -> None:
    assert obligation_changed("You must do it.", "You should do it.", "en")
    assert obligation_changed("Do it.", "You must do it.", "en")
    assert not obligation_changed("You must do it.", "You MUST do it now.", "en")
    assert obligation_changed("Il doit le faire.", "Il peut le faire.", "fr")
