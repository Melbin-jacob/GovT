"""Append-only, hash-chained decision log.

Every human decision is one record. Each record contains the hash of the previous record
and is itself hashed (SHA-256 over its canonical JSON: sorted keys, no whitespace, UTF-8),
so changing, removing or reordering any record breaks the chain from that point on.

Protection in depth:
- the database refuses UPDATE, DELETE and TRUNCATE on the log (triggers);
- appends are serialized with a transaction-level advisory lock, so the chain never forks;
- ``verify`` recomputes every hash and link, from the database or an exported file;
- a hash chain alone cannot notice records cut off at the *end*. ``checkpoint`` returns
  (sequence number, head hash); store it elsewhere (e.g. print it into a ServiceNow work
  note or a signed report) and pass it to ``verify`` to detect truncation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from review_desk.models import DecisionRecord

GENESIS = "sha256:" + "0" * 64
LOG_LOCK_KEY = 0x4C4F47434841494E  # "LOGCHAIN"


def canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_text(canonical_text: str) -> str:
    return "sha256:" + hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


def append(session: Session, record: dict[str, Any]) -> DecisionRecord:
    """Append a record (inside the caller's transaction). Fills seq and both hashes."""
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOG_LOCK_KEY})
    last = session.scalar(select(DecisionRecord).order_by(DecisionRecord.seq.desc()).limit(1))
    seq = (last.seq + 1) if last else 1
    previous = last.record_hash if last else GENESIS
    body = {**record, "seq": seq, "previous-record-hash": previous}
    canonical_text = canonical(body)
    row = DecisionRecord(
        seq=seq,
        uuid=str(record["uuid"]),
        finding_id=str(record["finding-uuid"]),
        action=str(record["action"]),
        record_text=canonical_text,
        previous_hash=previous,
        record_hash=hash_text(canonical_text),
    )
    session.add(row)
    session.flush()
    return row


@dataclass(frozen=True)
class Entry:
    seq: int
    record_text: str
    previous_hash: str
    record_hash: str


@dataclass
class VerifyResult:
    ok: bool
    records: int
    head_seq: int
    head_hash: str
    problems: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "records": self.records,
            "head_seq": self.head_seq,
            "head_hash": self.head_hash,
            "problems": self.problems,
        }


def verify_entries(
    entries: Iterable[Entry],
    *,
    expect_seq: int | None = None,
    expect_head: str | None = None,
) -> VerifyResult:
    entries = list(entries)
    problems: list[str] = []
    expected_seq, expected_previous, count = 1, GENESIS, 0
    head_seq, head_hash = 0, GENESIS
    for entry in entries:
        count += 1
        if entry.seq != expected_seq:
            problems.append(
                f"seq {entry.seq}: expected seq {expected_seq} (record missing or reordered)"
            )
        if entry.previous_hash != expected_previous:
            problems.append(
                f"seq {entry.seq}: previous hash does not match record {expected_seq - 1}"
            )
        if hash_text(entry.record_text) != entry.record_hash:
            problems.append(f"seq {entry.seq}: record content does not match its hash (modified)")
        try:
            body = json.loads(entry.record_text)
            if (
                body.get("seq") != entry.seq
                or body.get("previous-record-hash") != entry.previous_hash
            ):
                problems.append(f"seq {entry.seq}: chain fields inside the record were altered")
        except json.JSONDecodeError:
            problems.append(f"seq {entry.seq}: record is not valid JSON")
        expected_seq = entry.seq + 1
        expected_previous = entry.record_hash
        head_seq, head_hash = entry.seq, entry.record_hash
    if expect_seq is not None and expect_head is not None:
        if head_seq < expect_seq:
            problems.append(
                f"log ends at seq {head_seq} but checkpoint says {expect_seq} (records removed "
                "from the end)"
            )
        elif problems == [] and _hash_at(entries, expect_seq) not in (None, expect_head):
            problems.append(f"seq {expect_seq}: hash differs from the checkpoint")
    return VerifyResult(not problems, count, head_seq, head_hash, problems)


def _hash_at(entries: Iterable[Entry], seq: int) -> str | None:
    for entry in entries:
        if entry.seq == seq:
            return entry.record_hash
    return None


def db_entries(session: Session) -> list[Entry]:
    rows = session.scalars(select(DecisionRecord).order_by(DecisionRecord.seq))
    return [Entry(r.seq, r.record_text, r.previous_hash, r.record_hash) for r in rows]


def verify_db(
    session: Session, *, expect_seq: int | None = None, expect_head: str | None = None
) -> VerifyResult:
    return verify_entries(db_entries(session), expect_seq=expect_seq, expect_head=expect_head)


def export_lines(session: Session) -> Iterator[str]:
    """JSON Lines: one object per record, with the exact canonical text that was hashed."""
    for entry in db_entries(session):
        yield json.dumps(
            {
                "seq": entry.seq,
                "previous_hash": entry.previous_hash,
                "record_hash": entry.record_hash,
                "record": entry.record_text,
            },
            ensure_ascii=False,
        )


def file_entries(lines: Iterable[str]) -> list[Entry]:
    entries = []
    for line in lines:
        if line.strip():
            obj = json.loads(line)
            entries.append(
                Entry(
                    int(obj["seq"]),
                    str(obj["record"]),
                    str(obj["previous_hash"]),
                    str(obj["record_hash"]),
                )
            )
    return entries


def checkpoint(session: Session) -> dict[str, Any]:
    entries = db_entries(session)
    head = entries[-1] if entries else None
    return {
        "head_seq": head.seq if head else 0,
        "head_hash": head.record_hash if head else GENESIS,
        "records": len(entries),
    }
