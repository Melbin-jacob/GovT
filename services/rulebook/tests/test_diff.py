"""Diff engine on the golden catalogs, without a database. Edits are synthetic test data."""

from __future__ import annotations

import copy
from typing import Any

from helpers import add_control, drop_control, set_label, set_statement

from rulebook.diff import diff_catalogs


def _diff(a: dict[str, Any], b: dict[str, Any], lang: str = "en") -> Any:
    return diff_catalogs(a, b, catalog="t", lang=lang, from_version="1", to_version="2")  # type: ignore[arg-type]


def test_identical_catalogs_have_no_differences(golden_en: dict[str, Any]) -> None:
    result = _diff(golden_en, copy.deepcopy(golden_en))
    assert (result.added, result.retired, result.removed, result.changed) == ([], [], [], [])


def test_obligation_word_change_is_flagged(golden_en: dict[str, Any]) -> None:
    after = copy.deepcopy(golden_en)
    set_statement(after, "DADM-6.2.2-A", "Notices must be displayed prominently.")
    result = _diff(golden_en, after)
    (change,) = result.changed
    assert change.id == "DADM-6.2.2-A"
    assert change.flags == ["obligation-change"]
    (field,) = change.changes
    assert field.field == "part:statement"
    assert field.before == "Notices are displayed prominently."
    assert field.obligations_before == []
    assert field.obligations_after == ["must"]
    assert result.summary["obligation-change"] == 1


def test_must_to_should_is_flagged(golden_en: dict[str, Any]) -> None:
    before, after = copy.deepcopy(golden_en), copy.deepcopy(golden_en)
    set_statement(before, "DADM-6.4.1", "Clients must be informed.")
    set_statement(after, "DADM-6.4.1", "Clients should be informed.")
    (change,) = _diff(before, after).changed
    assert change.flags == ["obligation-change"]


def test_wording_change_without_obligation_change_is_not_flagged(
    golden_en: dict[str, Any],
) -> None:
    after = copy.deepcopy(golden_en)
    set_statement(after, "DADM-6.2.2-A", "Notices are shown prominently.")
    (change,) = _diff(golden_en, after).changed
    assert change.flags == []


def test_french_obligation_change(golden_fr: dict[str, Any]) -> None:
    after = copy.deepcopy(golden_fr)
    set_statement(after, "DADM-6.2.2-A", "Les avis doivent être affichés bien en vue.")
    (change,) = _diff(golden_fr, after, "fr").changed
    assert change.flags == ["obligation-change"]
    assert change.changes[0].obligations_after == ["doivent"]


def test_label_change_added_and_removed(golden_en: dict[str, Any]) -> None:
    after = copy.deepcopy(golden_en)
    set_label(after, "DADM-SECURITY", "6.3.10")
    add_control(after, 0, "DADM-NEW", "A new synthetic check.")
    drop_control(after, "DADM-LEGAL")
    result = _diff(golden_en, after)
    assert result.added == ["DADM-NEW"]
    assert result.removed == ["DADM-LEGAL"]
    (change,) = result.changed
    assert change.flags == ["label-change"]
    assert (change.changes[0].before, change.changes[0].after) == ("6.3.9 or 6.3.10", "6.3.10")


def test_hub_props_are_compared(golden_en: dict[str, Any]) -> None:
    after = copy.deepcopy(golden_en)
    for group in after["catalog"]["groups"]:
        for ctrl in group["controls"]:
            if ctrl["id"] == "DADM-6.1.1-A":
                ctrl["props"][1]["value"] = "judgment"
    (change,) = _diff(golden_en, after).changed
    assert change.changes[0].field == "prop:hub:check-type"
