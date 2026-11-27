"""The rulebook's append-only, hash-chained approval log (same chain as the decision log).

Every drafting and approval action is one record: batch created, model draft received,
draft edited, approved, rejected, version published. The database refuses UPDATE, DELETE
and TRUNCATE; appends are serialized with an advisory lock; the head is also written to
a checkpoint file outside the database and stamped on the catalog version it produced.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from govhub_shared.hashchain import (
    GENESIS,
    Entry,
    VerifyResult,
    canonical,
    entry_line,
    hash_text,
    verify_entries,
)
from rulebook.models import ApprovalRecord

LOCK_KEY = 0x415050524F56414C  # "APPROVAL"


def append(
    session: Session, record: dict[str, Any], *, batch_id: str, item_id: str | None = None
) -> ApprovalRecord:
    session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    last = session.scalar(select(ApprovalRecord).order_by(ApprovalRecord.seq.desc()).limit(1))
    seq = (last.seq + 1) if last else 1
    previous = last.record_hash if last else GENESIS
    body = {**record, "seq": seq, "previous-record-hash": previous}
    canonical_text = canonical(body)
    row = ApprovalRecord(
        seq=seq,
        batch_id=batch_id,
        item_id=item_id,
        action=str(record["action"]),
        record_text=canonical_text,
        previous_hash=previous,
        record_hash=hash_text(canonical_text),
    )
    session.add(row)
    session.flush()
    return row


def entries(session: Session) -> list[Entry]:
    rows = session.scalars(select(ApprovalRecord).order_by(ApprovalRecord.seq))
    return [Entry(r.seq, r.record_text, r.previous_hash, r.record_hash) for r in rows]


def verify(session: Session) -> VerifyResult:
    return verify_entries(entries(session))


def export_lines(session: Session) -> list[str]:
    return [entry_line(e) for e in entries(session)]


def write_checkpoint(path: str, row: ApprovalRecord) -> str:
    """Append (seq, head hash) to the checkpoint file outside the database; never raises."""
    if not path:
        return "not configured (RULEBOOK_APPROVAL_CHECKPOINT_FILE)"
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            {
                "seq": row.seq,
                "head_hash": row.record_hash,
                "written_at": datetime.now(UTC).isoformat(),
            }
        )
        with target.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
    except OSError as exc:
        return f"not written: {exc.__class__.__name__}"
    return "written"
