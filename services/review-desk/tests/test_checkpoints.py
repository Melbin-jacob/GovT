"""Decision-log checkpoints outside the database (ServiceNow work notes + a file).

The attack: someone with database-owner rights switches the log's triggers off and deletes
the newest records. The remaining chain is still internally consistent, so only an
external checkpoint can reveal it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from review_desk_support import OFFICER, decide, load_report
from sqlalchemy import Engine, text
from test_poam_and_tasks import servicenow  # noqa: F401 - fixture

from review_desk import checkpoints
from review_desk.config import get_settings

ACCEPT = {"action": "accept", "annotation": "Evidence is sufficient."}
TRUNCATED = "log ends at seq 3 but checkpoint says 5 (records removed from the end)"


def _decide_five(desk: TestClient, impact_report: dict[str, Any]) -> list[dict[str, Any]]:
    findings = load_report(desk, impact_report)[:5]
    assert len(findings) == 5
    return [decide(desk, f["id"], ACCEPT).json() for f in findings]


def _delete_newest(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE decision_log DISABLE TRIGGER USER"))
        conn.execute(text("DELETE FROM decision_log WHERE seq > 3"))
        conn.execute(text("ALTER TABLE decision_log ENABLE TRIGGER USER"))


def test_each_decision_writes_both_checkpoints(
    desk: TestClient,
    impact_report: dict[str, Any],
    servicenow: FastAPI,  # noqa: F811
    checkpoint_file: Path,
) -> None:
    bodies = _decide_five(desk, impact_report)
    for i, body in enumerate(bodies, start=1):
        cp = body["checkpoint"]
        assert cp == {
            "due": True,
            "seq": i,
            "head_hash": body["log"]["record_hash"],
            "file": "written",
            "servicenow": "sent",
        }
    lines = [json.loads(x) for x in checkpoint_file.read_text("utf-8").splitlines()]
    assert [x["seq"] for x in lines] == [1, 2, 3, 4, 5]
    notes = " ".join(
        n for t in servicenow.state.mock.tables["u_govhub_task"] for n in t.get("work_notes", [])
    )
    assert checkpoints.note_text(5, bodies[-1]["log"]["record_hash"]) in notes

    status = desk.get("/decision-log/checkpoint-status", headers=OFFICER).json()
    assert status["file"]["latest_seq"] == 5
    assert status["servicenow"]["latest_seq"] == 5
    assert status["file"]["behind_database"] == 0
    result = desk.get(
        "/decision-log/verify", headers=OFFICER, params={"trust": ["file", "servicenow"]}
    ).json()
    assert result["ok"] is True
    assert result["checkpoints_checked"] == 10


@pytest.mark.parametrize("trust", ["file", "servicenow"])
def test_owner_deleting_newest_records_is_detected(
    desk: TestClient,
    impact_report: dict[str, Any],
    servicenow: FastAPI,  # noqa: F811
    review_engine: Engine,
    trust: str,
) -> None:
    _decide_five(desk, impact_report)
    _delete_newest(review_engine)

    # The chain that is left is internally consistent: without a checkpoint it passes.
    plain = desk.get("/decision-log/verify", headers=OFFICER).json()
    assert plain["ok"] is True
    assert plain["head_seq"] == 3

    result = desk.get("/decision-log/verify", headers=OFFICER, params={"trust": trust}).json()
    assert result["ok"] is False
    assert any(p.startswith(TRUNCATED) for p in result["problems"]), result["problems"]
    assert any(trust in p for p in result["problems"])


def test_cli_verify_log_trusts_the_file(
    desk: TestClient,
    impact_report: dict[str, Any],
    review_engine: Engine,
    review_database_url: str,
    checkpoint_file: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from review_desk import cli

    _decide_five(desk, impact_report)
    _delete_newest(review_engine)
    monkeypatch.setenv("REVIEW_DESK_DATABASE_URL", review_database_url)
    get_settings.cache_clear()
    assert cli.main(["verify-log"]) == 0
    assert cli.main(["verify-log", "--trust-file", str(checkpoint_file)]) == 1
    assert TRUNCATED in capsys.readouterr().out


def test_batch_checkpoints_and_failures_do_not_block_decisions(
    desk: TestClient,
    impact_report: dict[str, Any],
    checkpoint_file: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REVIEW_DESK_CHECKPOINT_EVERY", "2")
    # A directory where the file should be: writing fails, the decision still succeeds.
    checkpoint_file.mkdir(parents=True)
    get_settings.cache_clear()
    bodies = _decide_five(desk, impact_report)
    assert [b["checkpoint"]["due"] for b in bodies] == [False, True, False, True, False]
    second = bodies[1]["checkpoint"]
    assert second["file"].startswith("not written: IsADirectoryError")
    assert second["servicenow"].startswith("not sent: connector-hub not configured")
    assert desk.get("/decision-log/verify", headers=OFFICER).json()["records"] == 5
