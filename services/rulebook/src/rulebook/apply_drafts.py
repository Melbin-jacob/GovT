"""``rulebook apply-drafts``: write a published draft change set into the golden set.

The golden-set CSV stays the record (project owner's decision): the change set exported
from a published batch is applied to the CSV (cells edited, rows added, Status and
provenance columns filled), its groups file (new groups with their neutral Group ID) and
its settings (VERSION, SOURCE_DATE, SOURCE_VERSION, APPROVAL_LOG_HEAD). Re-importing then
gives exactly the version the rulebook stored (tested). Annotator columns are untouched;
an edited statement clears the agreed-wording cells, since the agreed text changed.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from typing import Any

from rulebook.golden import (
    CHECK_TYPE_CODES,
    COL_AGREED_EN,
    COL_AGREED_FR,
    COL_APPLIES_EN,
    COL_APPLIES_FR,
    COL_APPROVAL_RECORD,
    COL_APPROVED_BY,
    COL_CHECK_EN,
    COL_CHECK_FR,
    COL_CHECK_TYPE,
    COL_CLAUSE,
    COL_DRAFTED_BY,
    COL_EVIDENCE_EN,
    COL_EVIDENCE_FR,
    COL_GROUP,
    COL_ID,
    COL_NUMBERING,
    COL_OBLIGATION,
    COL_SOURCE_CLAUSES,
    COL_STATUS,
)

EXTRA = (
    COL_OBLIGATION,
    COL_STATUS,
    COL_GROUP,
    COL_DRAFTED_BY,
    COL_APPROVED_BY,
    COL_APPROVAL_RECORD,
)
LABEL_OF = {code: label for label, code in CHECK_TYPE_CODES.items()}


class ApplyError(ValueError):
    pass


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _write(fields: list[str], rows: list[dict[str, str]]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fields, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writeheader()
    writer.writerows([{f: r.get(f, "") or "" for f in fields} for r in rows])
    return out.getvalue()


def _set_text(row: dict[str, str], fields: list[str], column: str, value: str | None) -> None:
    if value is None:
        return
    if column not in fields:
        fields.append(column)
    row[column] = value


def apply_csv(csv_text_path: Path, change_set: dict[str, Any]) -> str:
    fields, rows = _read(csv_text_path)
    for column in EXTRA:
        if column not in fields:
            fields.append(column)
    by_id = {r[COL_ID]: r for r in rows}
    for change in change_set["changes"]:
        cid = change["control_id"]
        provenance = {
            COL_DRAFTED_BY: change.get("drafted_by") or "",
            COL_APPROVED_BY: change.get("approved_by") or "",
            COL_APPROVAL_RECORD: change.get("approval_record") or "",
        }
        if change["kind"] == "new":
            if cid in by_id:
                raise ApplyError(f"{cid} already exists in the golden set")
            row = {f: "" for f in fields}
            row.update(
                {
                    COL_ID: cid,
                    COL_CLAUSE: change["clause"],
                    COL_CHECK_EN: change["statement"]["en"],
                    COL_CHECK_FR: change["statement"]["fr"],
                    COL_APPLIES_EN: (change.get("guidance") or {}).get("en") or "",
                    COL_EVIDENCE_EN: (change.get("objective") or {}).get("en") or "",
                    COL_CHECK_TYPE: LABEL_OF[change["check_type"]],
                    COL_NUMBERING: "Confirmed",
                    COL_SOURCE_CLAUSES: ";".join(change["source_clauses"]),
                    COL_OBLIGATION: change.get("obligation") or "",
                    COL_GROUP: change["group"],
                    **provenance,
                }
            )
            _set_text(row, fields, COL_APPLIES_FR, (change.get("guidance") or {}).get("fr"))
            _set_text(row, fields, COL_EVIDENCE_FR, (change.get("objective") or {}).get("fr"))
            rows.append(row)
            by_id[cid] = row
            continue
        if cid not in by_id:
            raise ApplyError(f"{cid} is not in the golden set")
        row = by_id[cid]
        row.update(provenance)
        if change["kind"] == "retire":
            row[COL_STATUS] = "withdrawn"
            continue
        row[COL_SOURCE_CLAUSES] = ";".join(change["source_clauses"])
        if change["kind"] != "edit":
            continue
        if change.get("obligation"):
            row[COL_OBLIGATION] = change["obligation"]
        if change.get("no_change"):
            continue
        row[COL_CHECK_EN] = change["statement"]["en"]
        row[COL_CHECK_FR] = change["statement"]["fr"]
        row[COL_AGREED_EN] = ""
        if COL_AGREED_FR in fields:
            row[COL_AGREED_FR] = ""
        if change.get("check_type"):
            row[COL_CHECK_TYPE] = LABEL_OF[change["check_type"]]
        for name, en_col, fr_col in (
            ("guidance", COL_APPLIES_EN, COL_APPLIES_FR),
            ("objective", COL_EVIDENCE_EN, COL_EVIDENCE_FR),
        ):
            value = change.get(name) or {}
            if any(value.get(lang) for lang in ("en", "fr")):
                row[en_col] = value.get("en") or ""
                _set_text(row, fields, fr_col, value.get("fr") or "")
    return _write(fields, rows)


def apply_groups(groups_path: Path, change_set: dict[str, Any]) -> str:
    fields, rows = _read(groups_path)
    if "Group ID" not in fields:
        fields.append("Group ID")
    known = {r["Section"] for r in rows}
    for gid, group in change_set.get("new_groups", {}).items():
        if group["key"] in known:
            continue
        rows.append(
            {
                "Section": group["key"],
                "Title (EN)": group["title"]["en"],
                "Titre (FR)": group["title"]["fr"],
                "FR verified": "n/a",
                "Title source": f"Official heading of {change_set['source_instrument']} "
                f"{change_set['source_version']}, section {group['section']} (approved drafts).",
                "Group ID": gid,
            }
        )
    return _write(fields, rows)


def _setting(text: str, key: str, value: str) -> str:
    line = f'{key} = "{value}"'
    pattern = re.compile(rf"^{key}\s*=.*$", re.M)
    if pattern.search(text):
        return pattern.sub(line, text, count=1)
    # Before the first table so it stays a top-level key.
    first_table = text.find("\n[")
    if first_table < 0:
        return text.rstrip("\n") + "\n" + line + "\n"
    return text[:first_table] + "\n" + line + text[first_table:]


def apply_settings(settings_path: Path, change_set: dict[str, Any]) -> str:
    text = settings_path.read_text("utf-8")
    for key, value in (
        ("SOURCE_DATE", change_set["source_date"]),
        ("VERSION", change_set["new_version"]),
        ("SOURCE_VERSION", change_set["source_version"]),
        ("APPROVAL_LOG_HEAD", change_set["approval_log_head"]),
    ):
        text = _setting(text, key, value)
    return text


def apply(csv_path: Path, change_set: dict[str, Any]) -> dict[Path, str]:
    """New text of the CSV, groups file and settings (nothing written)."""
    name = csv_path.name.removesuffix(".csv")
    groups = csv_path.with_name(f"{name}.groups.csv")
    settings = csv_path.with_name(f"{name}.settings.toml")
    return {
        csv_path: apply_csv(csv_path, change_set),
        groups: apply_groups(groups, change_set),
        settings: apply_settings(settings, change_set),
    }
