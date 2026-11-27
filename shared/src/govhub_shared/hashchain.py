"""Hash chains: append-only records where each holds the previous record's hash.

Shared by review-desk's decision log and the rulebook's approval log. A record's hash is
``sha256:`` over its canonical JSON (sorted keys, no whitespace, UTF-8), stored verbatim
as text so verification hashes the exact bytes. Changing, removing or reordering any
record breaks the chain from that point; checkpoints kept elsewhere catch records cut off
at the end.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

GENESIS = "sha256:" + "0" * 64


def canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_text(canonical_text: str) -> str:
    return "sha256:" + hashlib.sha256(canonical_text.encode("utf-8")).hexdigest()


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
    checkpoints_checked: int = 0
    # The same problems as codes and parameters, so a UI can show them in any language.
    issues: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checkpoints_checked": self.checkpoints_checked,
            "records": self.records,
            "head_seq": self.head_seq,
            "head_hash": self.head_hash,
            "problems": self.problems,
            "issues": self.issues,
        }


@dataclass(frozen=True)
class Checkpoint:
    """A (seq, head hash) pair recorded outside the database; ``source`` says where."""

    seq: int
    head_hash: str
    source: str = "given"


def verify_entries(
    entries: Iterable[Entry],
    *,
    expect_seq: int | None = None,
    expect_head: str | None = None,
    checkpoints: Sequence[Checkpoint] = (),
) -> VerifyResult:
    """Check the chain. Every trusted checkpoint must also still hold: the log reaches its
    seq and has the same hash there. That is what catches records removed from the end."""
    entries = list(entries)
    trusted = list(checkpoints)
    if expect_seq is not None and expect_head is not None:
        trusted.append(Checkpoint(expect_seq, expect_head))
    problems: list[str] = []
    issues: list[dict[str, Any]] = []

    def problem(code: str, text: str, **params: Any) -> None:
        problems.append(text)
        issues.append({"code": code, "params": params})

    expected_seq, expected_previous, count = 1, GENESIS, 0
    head_seq, head_hash = 0, GENESIS
    for entry in entries:
        count += 1
        if entry.seq != expected_seq:
            problem(
                "sequence-gap",
                f"seq {entry.seq}: expected seq {expected_seq} (record missing or reordered)",
                seq=entry.seq,
                expected=expected_seq,
            )
        if entry.previous_hash != expected_previous:
            problem(
                "previous-hash-mismatch",
                f"seq {entry.seq}: previous hash does not match record {expected_seq - 1}",
                seq=entry.seq,
                previous=expected_seq - 1,
            )
        if hash_text(entry.record_text) != entry.record_hash:
            problem(
                "content-modified",
                f"seq {entry.seq}: record content does not match its hash (modified)",
                seq=entry.seq,
            )
        try:
            body = json.loads(entry.record_text)
            if (
                body.get("seq") != entry.seq
                or body.get("previous-record-hash") != entry.previous_hash
            ):
                problem(
                    "chain-fields-altered",
                    f"seq {entry.seq}: chain fields inside the record were altered",
                    seq=entry.seq,
                )
        except json.JSONDecodeError:
            problem("invalid-json", f"seq {entry.seq}: record is not valid JSON", seq=entry.seq)
        expected_seq = entry.seq + 1
        expected_previous = entry.record_hash
        head_seq, head_hash = entry.seq, entry.record_hash
    hashes = {e.seq: e.record_hash for e in entries}
    for cp in sorted(set(trusted), key=lambda c: (c.seq, c.source)):
        kind, _, name = cp.source.partition(" ")
        where = {"source_kind": kind, "source_name": name}
        if head_seq < cp.seq:
            problem(
                "truncated",
                f"log ends at seq {head_seq} but checkpoint says {cp.seq} (records removed "
                f"from the end) [{cp.source}]",
                head=head_seq,
                checkpoint=cp.seq,
                **where,
            )
        elif hashes.get(cp.seq) != cp.head_hash:
            problem(
                "checkpoint-hash-mismatch",
                f"seq {cp.seq}: hash differs from the checkpoint [{cp.source}]",
                seq=cp.seq,
                **where,
            )
    return VerifyResult(
        not problems, count, head_seq, head_hash, problems, len(set(trusted)), issues
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


def entry_line(entry: Entry) -> str:
    """One JSON Lines export record, with the exact canonical text that was hashed."""
    return json.dumps(
        {
            "seq": entry.seq,
            "previous_hash": entry.previous_hash,
            "record_hash": entry.record_hash,
            "record": entry.record_text,
        },
        ensure_ascii=False,
    )
