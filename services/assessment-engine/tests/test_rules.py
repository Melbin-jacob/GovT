"""Rule-based checks: plain code against facts; rules files checked against the catalogs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from ae_support import REPO
from fastapi.testclient import TestClient

from assessment_engine import messages
from assessment_engine.rules import Fact, assess_rule, load_rules, referenced_facts
from govhub_shared.auth.testing import headers, user

RULES = REPO / "data" / "rules"
CATALOGS = {
    "example-widgets": REPO / "data/demo/catalogs/example-widgets.en.json",
    "dadm-section6": REPO / "data/catalogs/dadm-section6.en.json",
}
AS_OF = date(2026, 12, 1)


def check_types(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}

    def walk(node: dict[str, Any]) -> None:
        for control in node.get("controls", []):
            for prop in control.get("props", []):
                if prop["name"] == "check-type":
                    out[control["id"]] = prop["value"]
            walk(control)
        for group in node.get("groups", []):
            walk(group)

    walk(json.loads(path.read_text("utf-8"))["catalog"])
    return out


@pytest.mark.parametrize("catalog", sorted(CATALOGS))
def test_rules_file_matches_the_catalog(catalog: str) -> None:
    ruleset = load_rules(RULES, catalog)
    assert ruleset is not None and ruleset.status == "unverified-draft"
    types = check_types(CATALOGS[catalog])
    rule_based = {cid for cid, t in types.items() if t.startswith("rule-based")}
    assert set(ruleset.rules) == rule_based  # every rule-based check, nothing else
    for cid, rule in ruleset.rules.items():
        assert rule["en"].strip() and rule["fr"].strip(), cid
        if rule.get("rollup"):
            assert types[cid] == "rule-based-roll-up"
            continue
        names: set[str] = set()
        for key in ("applies_when", "met", "partial"):
            names |= referenced_facts(rule.get(key))
        assert names and names <= set(ruleset.facts), (cid, names - set(ruleset.facts))
    for name, fact in ruleset.facts.items():
        assert fact["en"] and fact["fr"] and fact["type"], name


def test_messages_have_the_same_keys() -> None:
    assert messages.check_parity() == []


WIDGETS = load_rules(RULES, "example-widgets")


def facts(**values: Any) -> dict[str, Fact]:
    return {k: Fact(v, "register export 2026-11") for k, v in values.items()}


@pytest.mark.parametrize(
    ("control", "values", "verdict"),
    [
        ("WID-6.1.1", {"widgets_registered_late": 0, "register_kept": True}, "met"),
        ("WID-6.1.1", {"widgets_registered_late": 2, "register_kept": True}, "partially-met"),
        ("WID-6.1.1", {"widgets_registered_late": 2, "register_kept": False}, "not-met"),
        ("WID-6.1.1", {"register_kept": True}, "unable-to-determine"),
        ("WID-6.1.2", {"register_fields_complete_ratio": 0.6}, "partially-met"),
        ("WID-6.2.1", {"widgets_in_service": 0}, "not-applicable"),
        ("WID-6.2.1", {"widgets_in_service": 4, "last_calibration_date": "2026-01-15"}, "met"),
        ("WID-6.2.1", {"widgets_in_service": 4, "last_calibration_date": "2025-06-01"}, "not-met"),
        ("WID-6.2.1", {"last_calibration_date": "2026-01-15"}, "unable-to-determine"),
        ("WID-6.2.3", {"faults_recorded": 0}, "not-applicable"),
        ("WID-6.3.1", {"calibration_log_months": 30}, "met"),
        ("WID-6.4.2", {}, "unable-to-determine"),
    ],
)
def test_widget_rules(control: str, values: dict[str, Any], verdict: str) -> None:
    outcome = assess_rule(WIDGETS, control, facts(**values), AS_OF)
    assert outcome.verdict == verdict
    if verdict == "unable-to-determine":
        assert outcome.confidence is None and outcome.missing
    else:
        assert outcome.confidence == 1.0


def test_dadm_interval_from_a_fact_and_roll_up() -> None:
    dadm = load_rules(RULES, "dadm-section6")
    ok = facts(aia_last_approval_date="2026-06-01", aia_review_interval_days=365)
    late = facts(aia_last_approval_date="2025-06-01", aia_review_interval_days=365)
    assert assess_rule(dadm, "DADM-6.1.3-A", ok, AS_OF).verdict == "met"
    assert assess_rule(dadm, "DADM-6.1.3-A", late, AS_OF).verdict == "not-met"
    roll = assess_rule(dadm, "DADM-6.1.2", {}, AS_OF)
    assert roll.verdict == "unable-to-determine" and "Appendix C" in roll.rationale["en"]
    assert assess_rule(dadm, "DADM-6.9.9", {}, AS_OF).verdict == "unable-to-determine"


def test_rationale_is_bilingual_and_names_facts_and_sources() -> None:
    values = {"widgets_in_service": 4, "last_calibration_date": "2026-01-15"}
    outcome = assess_rule(WIDGETS, "WID-6.2.1", facts(**values), AS_OF)
    en, fr = outcome.rationale["en"], outcome.rationale["fr"]
    assert en.startswith("Rule-based check (unverified draft rule):")
    assert "Number of widgets in service = 4 (source: register export 2026-11)" in en
    assert fr.startswith("Contrôle fondé sur une règle (règle provisoire non vérifiée) :")
    assert "Nombre de widgets en service = 4 (source : register export 2026-11)" in fr
    missing = assess_rule(WIDGETS, "WID-6.4.2", {}, AS_OF).rationale["fr"]
    assert "Faits manquants : Date du dernier rapport annuel" in missing


def test_facts_api_and_rule_checks(engine_api: TestClient) -> None:
    body = {
        "facts": {
            "widgets_in_service": {"value": 4, "source": "register export"},
            "last_calibration_date": {"value": "2026-01-15", "source": "calibration log"},
            "register_fields_complete_ratio": {"value": 1.0, "source": "register export"},
        }
    }
    writer = headers(user("o", reviewer=["agency-sample-benefits"]), "assessment-engine")
    resp = engine_api.put("/systems/SYS-001/facts", json=body, headers=writer)
    assert resp.status_code == 200
    assert resp.json()["facts"]["widgets_in_service"] == {"value": 4, "source": "register export"}
    result = engine_api.get(
        "/systems/SYS-001/rule-checks",
        params={"catalog": "example-widgets", "as_of": "2026-12-01"},
    ).json()
    verdicts = {r["control_id"]: r["verdict"] for r in result["results"]}
    assert verdicts["WID-6.2.1"] == "met" and verdicts["WID-6.1.2"] == "met"
    assert verdicts["WID-6.1.1"] == "unable-to-determine"
    assert result["rules_status"] == "unverified-draft"
    cleared = {"facts": {"widgets_in_service": {"value": None}}}
    engine_api.put("/systems/SYS-001/facts", json=cleared)
    again = engine_api.get(
        "/systems/SYS-001/rule-checks",
        params={"catalog": "example-widgets", "as_of": "2026-12-01", "control": "WID-6.2.1"},
    ).json()
    assert again["results"][0]["verdict"] == "unable-to-determine"
    assert engine_api.put("/systems/SYS-001/facts", json={"facts": {"x": 1}}).status_code == 422
