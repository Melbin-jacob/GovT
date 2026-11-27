"""Language-neutral obligation codes (golden-set "Obligation" column)."""

from __future__ import annotations

import pytest

from govhub_shared.obligations import OBLIGATION_CODES, obligation_codes, primary_obligation


@pytest.mark.parametrize(
    ("text", "lang", "code"),
    [
        ("Each department must register every widget.", "en", "must"),
        ("The department shall publish the register.", "en", "must"),
        ("Widgets should be calibrated at least once a year.", "en", "should"),
        ("Operators must not disable the widget.", "en", "must-not"),
        ("Operators should not share passwords.", "en", "should-not"),
        ("The register may be published.", "en", "may"),
        ("The department may not delegate this task.", "en", "may-not"),
        ("Clients are told when a widget processes their request.", "en", None),
        ("Chaque ministère doit enregistrer chaque widget.", "fr", "must"),
        ("Les widgets devraient être étalonnés chaque année.", "fr", "should"),
        ("Le registre peut être publié.", "fr", "may"),
        ("L'opérateur ne doit pas désactiver le widget.", "fr", "must-not"),
        ("L'opérateur ne devrait pas partager son mot de passe.", "fr", "should-not"),
        ("Le ministère ne peut pas déléguer cette tâche.", "fr", "may-not"),
        ("Le ministère ne doit que consigner les résultats.", "fr", "restriction"),
        ("Le ministère n'est pas tenu de publier le registre.", "fr", "may"),
    ],
)
def test_primary_obligation(text: str, lang: str, code: str | None) -> None:
    assert primary_obligation(text, lang) == code  # type: ignore[arg-type]


def test_strongest_code_wins_and_all_codes_are_known() -> None:
    text = "Operators must log every calibration and may publish the log."
    assert obligation_codes(text, "en") == {"must", "may"}
    assert primary_obligation(text, "en") == "must"
    assert set(OBLIGATION_CODES) == {
        "must",
        "must-not",
        "should",
        "should-not",
        "may",
        "may-not",
        "restriction",
    }
