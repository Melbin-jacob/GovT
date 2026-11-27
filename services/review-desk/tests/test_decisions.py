"""Reviewer decisions and the hash-chained decision log."""

from __future__ import annotations

import itertools
import json
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from review_desk_support import OFFICER, REVIEWER, decide, load_report
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from review_desk import decision_log
from review_desk.cli import main

ALL_ACTIONS: list[dict[str, Any]] = [
    {"action": "accept", "annotation": "Evidence is sufficient."},
    {
        "action": "accept-with-remediation",
        "annotation": "Notices missing for two channels.",
        "remediation": {
            "description": "Deliver telephone notice scripts.",
            "due_date": "2027-01-31",
        },
    },
    {"action": "reject", "annotation": "Control does not apply to this system."},
    {"action": "request-more-evidence", "annotation": "Attach the calibration log for 2026."},
    {"action": "override-verdict", "verdict": "partially-met", "annotation": "Online only."},
]


@pytest.fixture
def findings(desk: TestClient, impact_report: dict[str, Any]) -> list[dict[str, Any]]:
    return load_report(desk, impact_report)


def test_each_action_updates_the_finding(desk: TestClient, findings: list[dict[str, Any]]) -> None:
    expected = [
        "accepted",
        "accepted-with-remediation",
        "rejected",
        "awaiting-evidence",
        "overridden",
    ]
    for finding, body, state in zip(findings, ALL_ACTIONS, expected, strict=False):
        resp = decide(desk, finding["id"], body)
        assert resp.status_code == 200, resp.json()
        assert resp.json()["finding"]["state"] == state
    overridden = desk.get(f"/findings/{findings[4]['id']}", headers=OFFICER).json()
    assert overridden["verdict"] == "partially-met"
    record = desk.get(f"/findings/{findings[4]['id']}/decisions", headers=OFFICER).json()[0]
    assert (record["verdict-before"], record["verdict-after"]) == (
        "unable-to-determine",
        "partially-met",
    )
    assert record["reviewer"] == {
        "id": "governance-officer-01",
        "role": "governance-officer",
        "authorized": True,
    }
    assert record["placeholder-finding"] is True
    assert record["confidence-at-review"] is None


def test_awaiting_evidence_can_be_decided_later_but_decided_cannot(
    desk: TestClient, findings: list[dict[str, Any]]
) -> None:
    fid = findings[0]["id"]
    assert decide(desk, fid, ALL_ACTIONS[3]).json()["finding"]["state"] == "awaiting-evidence"
    assert decide(desk, fid, ALL_ACTIONS[0], REVIEWER).status_code == 200
    again = decide(desk, fid, ALL_ACTIONS[0])
    assert again.status_code == 409
    assert "already accepted" in again.json()["detail"]
    assert [
        r["action"] for r in desk.get(f"/findings/{fid}/decisions", headers=OFFICER).json()
    ] == [
        "request-more-evidence",
        "accept",
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"action": "reject"},
        {"action": "request-more-evidence", "annotation": "  "},
        {"action": "override-verdict", "annotation": "x"},
        {"action": "accept", "verdict": "met"},
        {"action": "accept-with-remediation"},
        {"action": "accept", "remediation": {"description": "x", "due_date": "2027-01-01"}},
        {"action": "escalate"},
    ],
)
def test_invalid_decisions(
    desk: TestClient, findings: list[dict[str, Any]], body: dict[str, Any]
) -> None:
    assert decide(desk, findings[0]["id"], body).status_code == 422


def test_override_to_same_verdict_is_refused(
    desk: TestClient, findings: list[dict[str, Any]]
) -> None:
    body = {"action": "override-verdict", "verdict": "unable-to-determine", "annotation": "x"}
    assert decide(desk, findings[0]["id"], body).status_code == 422


def test_review_time_is_measured_on_the_server(
    desk: TestClient, findings: list[dict[str, Any]]
) -> None:
    fid = findings[0]["id"]
    opened = desk.post(f"/findings/{fid}/open", headers=OFFICER).json()
    decide(desk, fid, {**ALL_ACTIONS[0], "session_id": opened["session_id"]})
    record = desk.get(f"/findings/{fid}/decisions", headers=OFFICER).json()[0]
    assert record["review-seconds"] is not None and record["review-seconds"] >= 0
    other = findings[1]["id"]
    decide(desk, other, ALL_ACTIONS[0])  # never opened: no timing
    assert (
        desk.get(f"/findings/{other}/decisions", headers=OFFICER).json()[0]["review-seconds"]
        is None
    )
    third = findings[2]["id"]
    assert decide(desk, third, {**ALL_ACTIONS[0], "session_id": 999}).status_code == 409


# --- the chain -------------------------------------------------------------------------


def _decide_all(desk: TestClient, findings: list[dict[str, Any]]) -> None:
    for finding, body in zip(findings, ALL_ACTIONS, strict=False):
        assert decide(desk, finding["id"], body).status_code == 200


def test_chain_links_and_verifies(desk: TestClient, findings: list[dict[str, Any]]) -> None:
    _decide_all(desk, findings)
    result = desk.get("/decision-log/verify", headers=OFFICER).json()
    assert result["ok"] is True and result["records"] == 5 and result["problems"] == []
    lines = desk.get("/decision-log/export", headers=OFFICER).text.splitlines()
    entries = [json.loads(line) for line in lines]
    assert entries[0]["previous_hash"] == decision_log.GENESIS
    for prev, cur in itertools.pairwise(entries):
        assert cur["previous_hash"] == prev["record_hash"]
    checkpoint = desk.get("/decision-log/checkpoint", headers=OFFICER).json()
    assert checkpoint == {"head_seq": 5, "head_hash": entries[-1]["record_hash"], "records": 5}


def test_database_refuses_changes(
    desk: TestClient, findings: list[dict[str, Any]], review_db: Session
) -> None:
    _decide_all(desk, findings)
    for statement in (
        "UPDATE decision_log SET action = 'accept' WHERE seq = 2",
        "DELETE FROM decision_log WHERE seq = 2",
        "TRUNCATE decision_log",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            review_db.execute(text(statement))
        review_db.rollback()


def _tamper(engine: Engine, statement: str) -> None:
    """Simulate an attacker with owner rights who switches the triggers off."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE decision_log DISABLE TRIGGER USER"))
        for part in filter(None, (p.strip() for p in statement.split(";"))):
            conn.execute(text(part))
        conn.execute(text("ALTER TABLE decision_log ENABLE TRIGGER USER"))


@pytest.mark.parametrize(
    ("statement", "problem"),
    [
        (
            "UPDATE decision_log SET record_text = replace(record_text, 'sufficient', 'fine') "
            "WHERE seq = 1",
            "seq 1: record content does not match its hash",
        ),
        ("DELETE FROM decision_log WHERE seq = 3", "seq 4: expected seq 3"),
        (
            "UPDATE decision_log SET seq = 99 WHERE seq = 2; "
            "UPDATE decision_log SET seq = 2 WHERE seq = 4; "
            "UPDATE decision_log SET seq = 4 WHERE seq = 99",
            "previous hash does not match",
        ),
    ],
)
def test_database_tampering_is_detected(
    desk: TestClient,
    findings: list[dict[str, Any]],
    review_engine: Engine,
    statement: str,
    problem: str,
) -> None:
    _decide_all(desk, findings)
    _tamper(review_engine, statement)
    result = desk.get("/decision-log/verify", headers=OFFICER).json()
    assert result["ok"] is False
    assert any(problem in p for p in result["problems"]), result["problems"]


def test_exported_file_tampering_and_truncation(
    desk: TestClient,
    findings: list[dict[str, Any]],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _decide_all(desk, findings)
    export = tmp_path / "log.jsonl"
    export.write_text(desk.get("/decision-log/export", headers=OFFICER).text, encoding="utf-8")
    head = desk.get("/decision-log/checkpoint", headers=OFFICER).json()
    assert main(["verify-log", "--file", str(export)]) == 0

    tampered = tmp_path / "tampered.jsonl"
    lines = export.read_text("utf-8").splitlines()
    lines[1] = lines[1].replace("Notices missing", "Notices present")
    tampered.write_text("\n".join(lines) + "\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["verify-log", "--file", str(tampered)]) == 1
    assert "seq 2: record content does not match its hash" in capsys.readouterr().out

    truncated = tmp_path / "truncated.jsonl"
    truncated.write_text("\n".join(export.read_text("utf-8").splitlines()[:3]) + "\n", "utf-8")
    assert main(["verify-log", "--file", str(truncated)]) == 0  # a chain alone can't tell
    args = ["--expect-seq", str(head["head_seq"]), "--expect-head", head["head_hash"]]
    assert main(["verify-log", "--file", str(truncated), *args]) == 1
    assert main(["verify-log", "--file", str(export), *args]) == 0


def test_concurrent_decisions_keep_one_chain(
    desk: TestClient, findings: list[dict[str, Any]]
) -> None:
    errors: list[str] = []

    def run(finding_id: str) -> None:
        resp = decide(desk, finding_id, ALL_ACTIONS[0])
        if resp.status_code != 200:
            errors.append(resp.text)

    threads = [threading.Thread(target=run, args=(f["id"],), daemon=True) for f in findings[:12]]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert errors == []
    result = desk.get("/decision-log/verify", headers=OFFICER).json()
    assert result["ok"] is True and result["records"] == 12


def test_verify_uploaded_export(desk: TestClient, findings: list[dict[str, Any]]) -> None:
    _decide_all(desk, findings)
    export = desk.get("/decision-log/export", headers=OFFICER).text
    head = desk.get("/decision-log/checkpoint", headers=OFFICER).json()
    ok = desk.post("/decision-log/verify-export", content=export, headers=OFFICER).json()
    assert ok["ok"] is True and ok["records"] == 5
    tampered = export.replace("Evidence is sufficient.", "Evidence is excellent.")
    bad = desk.post("/decision-log/verify-export", content=tampered, headers=OFFICER).json()
    assert bad["ok"] is False
    assert bad["problems"] == ["seq 1: record content does not match its hash (modified)"]
    cut = "\n".join(export.splitlines()[:2])
    params = {"expect_seq": head["head_seq"], "expect_head": head["head_hash"]}
    short = desk.post("/decision-log/verify-export", content=cut, headers=OFFICER, params=params)
    assert short.json()["ok"] is False
    junk = desk.post("/decision-log/verify-export", content="not json", headers=OFFICER)
    assert junk.status_code == 422
