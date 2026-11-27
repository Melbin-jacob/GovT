"""Propose the golden-set "Obligation" column from linked source clauses (plain code).

For each row with Source clauses, the strongest obligation code found in the linked clause
text (same detector as the clause diff) is written into a blank Obligation cell. Rows
without links stay blank: never guessed. Filled cells are never overwritten. Annotators
confirm the proposed values.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from pathlib import Path

from govhub_shared.obligations import primary_obligation
from rulebook.golden import COL_ID, COL_OBLIGATION, COL_SOURCE_CLAUSES

_STRENGTH = ("must-not", "must", "restriction", "should-not", "should", "may-not", "may")


@dataclass
class Proposal:
    check_id: str
    clauses: list[str]
    code: str | None


def propose(csv_path: Path, source_json: Path, lang: str = "en") -> tuple[str, list[Proposal]]:
    """The CSV text with blank Obligation cells filled, and what was proposed."""
    clauses = {
        c["number"]: c["text"] for c in json.loads(source_json.read_text("utf-8"))["clauses"]
    }
    with csv_path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    if COL_OBLIGATION not in fields:
        fields.append(COL_OBLIGATION)
    proposals = []
    for row in rows:
        links = [n.strip() for n in (row.get(COL_SOURCE_CLAUSES) or "").split(";") if n.strip()]
        if not links or (row.get(COL_OBLIGATION) or "").strip():
            row.setdefault(COL_OBLIGATION, row.get(COL_OBLIGATION) or "")
            continue
        codes = {primary_obligation(clauses.get(n), lang) for n in links}  # type: ignore[arg-type]
        code = next((c for c in _STRENGTH if c in codes), None)
        row[COL_OBLIGATION] = code or ""
        proposals.append(Proposal(row[COL_ID], links, code))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue(), proposals
