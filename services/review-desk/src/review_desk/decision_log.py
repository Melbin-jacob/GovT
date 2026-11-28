"""Append-only, hash-chained decision log.

Every human decision is one record. Each record contains the hash of the previous record
and is itself hashed (SHA-256 over its canonical JSON: sorted keys, no whitespace, UTF-8),
so changing, removing or reordering any record breaks the chain from that point on.

Protection in depth:
- the database refuses UPDATE, DELETE and TRUNCATE on the log (triggers);
- appends are serialized with a transaction-level advisory lock, so the chain never forks;
- ``verify`` recomputes every hash and link, from the database or an exported file;
- a hash chain alone cannot notice records cut off at the *end*. After each decision (or
  every N) the service stores (sequence number, head hash) outside the database: as a work
  note on the task in ServiceNow and in an append-only file (``checkpoints.py``). ``verify``
  takes those as trusted checkpoints, so a database owner who disables the triggers and
  deletes the newest records is still caught.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from govhub_shared import tenancy
from govhub_shared.hashchain import (
    GENESIS,
    Checkpoint,
    Entry,
    VerifyResult,
    canonical,
    entry_line,
    file_entries,
    hash_text,
    verify_entries,
)
from review_desk.models import DecisionRecord

__all__ = [
    "GENESIS",
    "Checkpoint",
    "Entry",
    "VerifyResult",
    "canonical",
    "file_entries",
    "hash_text",
    "verify_entries",
]

LOG_LOCK_KEY = 0x4C4F47434841494E  # "LOGCHAIN"


def append(session: Session, record: dict[str, Any]) -> DecisionRecord:
    """Append a record (inside the caller's transaction). Fills seq and both hashes."""
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOG_LOCK_KEY})
    # One chain for every tenant until per-tenant chains: its head may be another
    # tenant's record, so it is read across tenants (only seq and hash are used). The new
    # record is still inserted under the caller's scope (row-level security checks it).
    with tenancy.widened(session, tenancy.ALL_TENANTS):
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


def db_entries(session: Session) -> list[Entry]:
    rows = session.scalars(select(DecisionRecord).order_by(DecisionRecord.seq))
    return [Entry(r.seq, r.record_text, r.previous_hash, r.record_hash) for r in rows]


def verify_db(
    session: Session,
    *,
    expect_seq: int | None = None,
    expect_head: str | None = None,
    checkpoints: Sequence[Checkpoint] = (),
) -> VerifyResult:
    return verify_entries(
        db_entries(session),
        expect_seq=expect_seq,
        expect_head=expect_head,
        checkpoints=checkpoints,
    )


def export_lines(session: Session) -> Iterator[str]:
    """JSON Lines: one object per record, with the exact canonical text that was hashed."""
    for entry in db_entries(session):
        yield entry_line(entry)


def checkpoint(session: Session) -> dict[str, Any]:
    entries = db_entries(session)
    head = entries[-1] if entries else None
    return {
        "head_seq": head.seq if head else 0,
        "head_hash": head.record_hash if head else GENESIS,
        "records": len(entries),
    }
