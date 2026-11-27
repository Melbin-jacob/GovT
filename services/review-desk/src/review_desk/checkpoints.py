"""Decision-log checkpoints kept OUTSIDE the database.

A hash chain cannot notice its newest records being deleted by someone who controls the
database. So after every N decisions (``REVIEW_DESK_CHECKPOINT_EVERY``) the current
(seq, head hash) is written to two places the database owner does not control:

- a work note on the decided finding's ``u_govhub_task`` in ServiceNow (through
  connector-hub), in the fixed form ``GovHub decision-log checkpoint seq=N head=sha256:...``;
- one JSON line appended (and fsynced) to ``REVIEW_DESK_CHECKPOINT_FILE``, on a volume
  separate from the database's.

``verify-log`` can then trust either source (or both): every checkpoint found must still
match the log. Writing happens after the decision is committed; a failure is reported in
the decision response and never undoes the decision.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from review_desk.decision_log import Checkpoint
from review_desk.tasks import TaskSink

NOTE_PREFIX = "GovHub decision-log checkpoint"
_NOTE_RE = re.compile(r"GovHub decision-log checkpoint seq=(\d+) head=(sha256:[0-9a-f]{64})")


def note_text(seq: int, head_hash: str) -> str:
    return f"{NOTE_PREFIX} seq={seq} head={head_hash}"


def due(seq: int, every: int) -> bool:
    return every > 0 and seq % every == 0


def append_to_file(path: Path, seq: int, head_hash: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(
        {"seq": seq, "head_hash": head_hash, "written_at": datetime.now(UTC).isoformat()}
    )
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return "written"


def write(
    *,
    seq: int,
    head_hash: str,
    every: int,
    file_path: str,
    sink: TaskSink,
    task_correlation_id: str | None,
) -> dict[str, Any]:
    """Write a checkpoint if one is due. Returns what happened (never raises)."""
    if not due(seq, every):
        return {"due": False, "every": every}
    outcome: dict[str, Any] = {"due": True, "seq": seq, "head_hash": head_hash}
    if file_path:
        try:
            outcome["file"] = append_to_file(Path(file_path), seq, head_hash)
        except OSError as exc:
            outcome["file"] = f"not written: {exc.__class__.__name__}: {exc}"
    else:
        outcome["file"] = "not configured (REVIEW_DESK_CHECKPOINT_FILE)"
    if task_correlation_id:
        outcome["servicenow"] = sink.note(task_correlation_id, note_text(seq, head_hash)).get(
            "status", "sent"
        )
    else:
        outcome["servicenow"] = "not sent: finding has no ServiceNow task"
    return outcome


def read_file(path: Path) -> list[Checkpoint]:
    if not path.is_file():
        return []
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            obj = json.loads(line)
            found.append(Checkpoint(int(obj["seq"]), str(obj["head_hash"]), f"file {path.name}"))
    return found


def parse_notes(notes: Iterable[tuple[str, str]]) -> list[Checkpoint]:
    """Checkpoints from (task number, work-notes text) pairs, in any journal format."""
    return [
        Checkpoint(int(m.group(1)), m.group(2), f"servicenow {task}")
        for task, text in notes
        for m in _NOTE_RE.finditer(text)
    ]
