"""Obligation words, including negated forms, in English and French."""

from __future__ import annotations

import pytest

from rulebook.obligations import obligation_changed, obligation_terms


@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        # English: positive forms
        ("The department must publish.", "en", {"must": 1}),
        (
            "It SHALL and Should; it may. Approval is required.",
            "en",
            {"shall": 1, "should": 1, "may": 1, "required": 1},
        ),
        ("The mayor is mustard-yellow; requirements apply.", "en", {}),
        # English: negated forms are their own values, never also counted as positive
        ("The department must not publish it.", "en", {"must not": 1}),
        ("It shall not apply; it should not be skipped.", "en", {"shall not": 1, "should not": 1}),
        ("Approval may not be waived but is required.", "en", {"may not": 1, "required": 1}),
        (
            "You mustn't, shan't and shouldn't.",
            "en",
            {"must not": 1, "shall not": 1, "should not": 1},
        ),
        ("It may, not always, apply.", "en", {"may": 1}),  # punctuation: not a negation
        # French: positive forms (devrait/devraient added, #38)
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
        (
            "Il devrait informer; les ministères devraient agir.",
            "fr",
            {"devrait": 1, "devraient": 1},
        ),
        ("Le doigt et la peuplade.", "fr", {}),
        # French: negated forms, singular and plural, with words in between
        ("Le ministère ne doit pas publier.", "fr", {"ne doit pas": 1}),
        ("Les avis ne doivent pas être affichés.", "fr", {"ne doivent pas": 1}),
        (
            "Il ne peut pas refuser; ils ne peuvent pas refuser.",
            "fr",
            {"ne peut pas": 1, "ne peuvent pas": 1},
        ),
        ("Il ne le doit pas.", "fr", {"ne doit pas": 1}),  # word between ne and the verb
        ("Il ne peut toutefois pas refuser.", "fr", {"ne peut pas": 1}),  # verb ... pas
        (
            "Ils ne peuvent plus attendre; elle ne devrait jamais agir.",
            "fr",
            {"ne peuvent plus": 1, "ne devrait jamais": 1},
        ),
        ("Il ne doit en aucun cas agir.", "fr", {"ne doit en aucun cas": 1}),
        ("Les ministères ne devraient pas attendre.", "fr", {"ne devraient pas": 1}),
        ("L’administrateur n’est pas tenu de répondre.", "fr", {"n'est pas tenu": 1}),
        ("Ils ne sont pas tenus de répondre.", "fr", {"n'est pas tenu": 1}),
        ("Il ne publie pas; il doit attendre.", "fr", {"doit": 1}),  # punctuation ends it
        (None, "en", {}),
    ],
)
def test_obligation_terms(text: str | None, lang: str, expected: dict[str, int]) -> None:
    assert dict(obligation_terms(text, lang)) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("before", "after", "lang"),
    [
        ("You must do it.", "You should do it.", "en"),
        ("Do it.", "You must do it.", "en"),
        ("Il doit le faire.", "Il peut le faire.", "fr"),
        ("Il doit le faire.", "Il devrait le faire.", "fr"),
        # only the negation changes
        (
            "The department must publish the report.",
            "The department must not publish the report.",
            "en",
        ),
        ("Records shall be kept.", "Records shall not be kept.", "en"),
        ("Data may be shared.", "Data may not be shared.", "en"),
        (
            "Le ministère doit publier le rapport.",
            "Le ministère ne doit pas publier le rapport.",
            "fr",
        ),
        (
            "Les données peuvent être communiquées.",
            "Les données ne peuvent pas être communiquées.",
            "fr",
        ),
        ("Il peut refuser.", "Il ne peut pas refuser.", "fr"),
    ],
)
def test_obligation_changed(before: str, after: str, lang: str) -> None:
    assert obligation_changed(before, after, lang)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("before", "after", "lang"),
    [
        ("You must do it.", "You MUST do it now.", "en"),
        ("You must not do it.", "You must not ever do it.", "en"),
        ("Il ne doit pas agir.", "Il ne doit toutefois pas agir.", "fr"),
        ("Il n'est pas tenu de répondre.", "Il n’est pas tenu de répondre.", "fr"),  # ' vs ’
    ],
)
def test_obligation_unchanged(before: str, after: str, lang: str) -> None:
    assert not obligation_changed(before, after, lang)  # type: ignore[arg-type]
