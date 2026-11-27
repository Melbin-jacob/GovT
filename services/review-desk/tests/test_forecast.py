"""Reviewer-hours forecast: PLACEHOLDER rate first, measured median after 20 timed reviews."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from review_desk_support import OFFICER, decide, load_report
from sqlalchemy import Engine, text

from review_desk.config import get_settings


def test_placeholder_rate_before_enough_data(
    desk: TestClient, impact_report: dict[str, Any]
) -> None:
    body = desk.post("/forecast", json=impact_report, headers=OFFICER).json()
    assert body["findings"] == 20
    assert body["rate"]["minutes_per_finding"] == 20
    assert body["rate"]["source"].startswith("PLACEHOLDER: 20 min per finding from config (0 of 20")
    assert body["reviewer_hours"] == 6.7  # 20 findings x 20 min
    tenants = {t["tenant"]: t for t in body["by_tenant"]}
    assert {k: v["findings"] for k, v in tenants.items()} == {
        "agency-sample-benefits": 7,
        "dept-example-services": 6,
        "office-fictional-permits": 7,
    }
    assert tenants["dept-example-services"]["reviewer_hours"] == 2.0
    assert tenants["agency-sample-benefits"]["capacity_source"] == "PLACEHOLDER"
    assert body["by_impact_level"] == {"IV": 5, "III": 7, "II": 5, "I": 3}
    assert body["staged_rollout"] == "not needed"


def test_measured_rate_after_twenty_timed_decisions(
    desk: TestClient, impact_report: dict[str, Any], review_engine: Engine
) -> None:
    findings = load_report(desk, impact_report)
    for minutes, finding in enumerate(findings, start=1):  # 20 reviews of 1..20 minutes
        session_id = desk.post(f"/findings/{finding['id']}/open", headers=OFFICER).json()[
            "session_id"
        ]
        with review_engine.begin() as conn:  # simulate time spent reading the evidence
            conn.execute(
                text(
                    "UPDATE review_sessions SET opened_at = opened_at "
                    "- make_interval(mins => :m) WHERE id = :i"
                ),
                {"m": minutes, "i": session_id},
            )
        decide(desk, finding["id"], {"action": "accept", "session_id": session_id})
    body = desk.post("/forecast", json=impact_report, headers=OFFICER).json()
    assert body["rate"]["source"] == "measured: median of 20 timed decisions"
    assert body["rate"]["minutes_per_finding"] == pytest.approx(10.5, abs=0.05)
    assert body["reviewer_hours"] == pytest.approx(3.5, abs=0.1)
    queue = desk.get("/forecast", headers=OFFICER).json()
    assert queue["basis"] == "open review queue" and queue["findings"] == 0


def test_capacity_exceeded_is_flagged(
    desk: TestClient, impact_report: dict[str, Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "rate.toml"
    config.write_text(
        '[rate]\nminutes_per_finding = 20\nstatus = "PLACEHOLDER"\nmin_samples = 20\n'
        '[capacity.default]\nhours_per_week = 2\nstatus = "PLACEHOLDER"\n'
        "[capacity.tenants.dept-example-services]\nhours_per_week = 5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(get_settings(), "review_rate_path", str(config))
    body = desk.post("/forecast", json=impact_report, headers=OFFICER).json()
    tenants = {t["tenant"]: t for t in body["by_tenant"]}
    assert tenants["agency-sample-benefits"]["exceeds_weekly_capacity"] is True  # 2.3 h > 2
    assert tenants["agency-sample-benefits"]["weeks_needed"] == 2
    assert tenants["dept-example-services"]["capacity_source"] == "tenant setting"
    assert tenants["dept-example-services"]["exceeds_weekly_capacity"] is False
    assert body["staged_rollout"].startswith("needed")


def test_forecast_of_open_queue(desk: TestClient, impact_report: dict[str, Any]) -> None:
    findings = load_report(desk, impact_report)
    decide(desk, findings[0]["id"], {"action": "accept"})
    body = desk.get("/forecast", headers=OFFICER).json()
    assert body["findings"] == 19
