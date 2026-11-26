"""Golden-set importer: hand-mapped CSV -> separate EN and FR OSCAL 1.1.3 catalogs.

The CSV is the only source of check wording. This module copies text; it never writes,
translates or "fixes" policy text. Missing optional text is omitted, not filled in.

Mapping (one CSV row -> one control in each language catalog, identical IDs):

- ``id`` = Check ID; ``title`` = Check ID (the CSV has no title column)
- props: ``label`` = Clause (as-is); namespaced ``check-type``, ``numbering-status``,
  ``numbering-note`` (if any), ``review-status`` (``reviewed`` | ``draft``)
- parts: ``statement`` = agreed wording if filled, else Check (EN) / Contrôle (FR);
  ``guidance`` = Applies when; ``assessment-objective`` = Evidence that would satisfy it.
  French guidance/objective/agreed wording come only from the optional columns
  ``S'applique lorsque``, ``Preuves attendues``, ``Libellé final convenu``.
- groups: first ``N.N`` section number found in the Clause column (``6.3.9 or 6.3.10`` -> 6.3)
"""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from govhub_shared import OSCAL_NS, OSCAL_VERSION
from govhub_shared.oscal import (
    content_hash,
    dump_json,
    normalize,
    stable_uuid,
    validate,
)
from rulebook.parity import require_parity

Lang = Literal["en", "fr"]
LANGS: tuple[Lang, ...] = ("en", "fr")

COL_ID = "Check ID"
COL_CLAUSE = "Clause (draft numbering)"
COL_CHECK_EN = "Check (EN)"
COL_CHECK_FR = "Contrôle (FR)"
COL_APPLIES_EN = "Applies when"
COL_EVIDENCE_EN = "Evidence that would satisfy it"
COL_CHECK_TYPE = "Check type"
COL_NUMBERING = "Numbering"
COL_AGREED_EN = "Agreed final wording"
REQUIRED_COLUMNS: tuple[str, ...] = (
    COL_ID,
    COL_CLAUSE,
    COL_CHECK_EN,
    COL_CHECK_FR,
    COL_APPLIES_EN,
    COL_EVIDENCE_EN,
    COL_CHECK_TYPE,
    COL_NUMBERING,
    "Annotator A",
    "Annotator A notes",
    "Annotator B",
    "Annotator B notes",
    "A and B",
    COL_AGREED_EN,
)
# Optional, forward-compatible French columns. Absent or blank -> FR field omitted.
COL_APPLIES_FR = "S'applique lorsque"
COL_EVIDENCE_FR = "Preuves attendues"
COL_AGREED_FR = "Libellé final convenu"

NUMBERING_STATUSES = frozenset({"Confirmed", "Likely", "Verify"})
_SECTION_RE = re.compile(r"(\d+)\.(\d+)")
_SINGLE_CLAUSE_RE = re.compile(r"^\d+(?:\.\d+)+$")
_ID_CLAUSE_RE = re.compile(r"\d+(?:\.\d+)+")
_TOKEN_RE = re.compile(r"^[^\W\d][\w.\-]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

SOURCE_AMENDED = "2025-06-24"
SOURCE: dict[Lang, dict[str, str]] = {
    "en": {
        "document": "Directive on Automated Decision-Making",
        "href": "https://www.tbs-sct.canada.ca/pol/doc-eng.aspx?id=32592",
        "title": "Directive on Automated Decision-Making — section 6 checks (golden set)",
        "remarks": (
            "Source: Directive on Automated Decision-Making, as amended 2025-06-24 "
            "(Treasury Board of Canada Secretariat). Check statements are paraphrases "
            "pending verification against the official text; they are not the text of the "
            "Directive. Clause numbers are draft numbering. Generated from {source} by the "
            "rulebook golden-set importer."
        ),
    },
    "fr": {
        "document": "Directive sur la prise de décisions automatisée",
        "href": "https://www.tbs-sct.canada.ca/pol/doc-fra.aspx?id=32592",
        "title": (
            "Directive sur la prise de décisions automatisée — contrôles de la section 6 "
            "(ensemble de référence)"
        ),
        "remarks": (
            "Source : Directive sur la prise de décisions automatisée, telle que modifiée le "
            "2025-06-24 (Secrétariat du Conseil du Trésor du Canada). Les énoncés des "
            "contrôles sont des paraphrases en attente de vérification par rapport au texte "
            "officiel; ils ne constituent pas le texte de la Directive. Les numéros de "
            "disposition sont provisoires. Généré à partir de {source} par l'importateur de "
            "l'ensemble de référence du rulebook."
        ),
    },
}


class GoldenImportError(ValueError):
    """The CSV cannot be imported. Lists every problem found, not just the first."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("golden-set import failed:\n" + "\n".join(f"  - {e}" for e in self.errors))


@dataclass(frozen=True)
class GroupTitle:
    section: str
    title: dict[Lang, str]


@dataclass(frozen=True)
class GoldenRow:
    line: int
    check_id: str
    clause: str
    group: str
    check_type: str
    numbering_status: str
    numbering_note: str | None
    statement: dict[Lang, str]
    reviewed: dict[Lang, bool]
    guidance: dict[Lang, str | None]
    objective: dict[Lang, str | None]


@dataclass
class ImportResult:
    name: str
    version: str
    source: Path
    rows: list[GoldenRow]
    catalogs: dict[Lang, dict[str, Any]]
    paths: dict[Lang, Path]
    changed: dict[Lang, bool]
    warnings: list[str] = field(default_factory=list)


def _cell(record: Mapping[str, str | None], column: str) -> str:
    return (record.get(column) or "").strip()


def parse_numbering(value: str) -> tuple[str, str | None]:
    """Split a Numbering cell into (status, note).

    ``"Verify: new in 2025"`` -> ``("Verify", "new in 2025")``;
    ``"Likely"`` -> ``("Likely", None)``.
    """
    status, sep, note = value.partition(":")
    return status.strip(), (note.strip() or None) if sep else None


def section_of(clause: str) -> str | None:
    """First ``N.N`` section number in a clause label, or ``None``."""
    match = _SECTION_RE.search(clause)
    return f"{match.group(1)}.{match.group(2)}" if match else None


def group_id(section: str) -> str:
    return f"dadm-{section}"


def read_groups(path: Path) -> dict[str, GroupTitle]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {
            _cell(r, "Section"): GroupTitle(
                section=_cell(r, "Section"),
                title={"en": _cell(r, "Title (EN)"), "fr": _cell(r, "Titre (FR)")},
            )
            for r in csv.DictReader(fh)
        }


def read_rows(
    csv_path: Path, groups: Mapping[str, GroupTitle]
) -> tuple[list[GoldenRow], list[str]]:
    """Parse and check every row. Raises ``GoldenImportError`` listing all problems."""
    errors: list[str] = []
    warnings: list[str] = []
    rows: list[GoldenRow] = []
    seen: dict[str, int] = {}

    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        missing = [c for c in REQUIRED_COLUMNS if c not in header]
        if missing:
            raise GoldenImportError([f"missing required column(s): {missing}"])

        for line, record in enumerate(reader, start=2):
            check_id = _cell(record, COL_ID)
            where = f"line {line} ({check_id or 'no ID'})"
            row_errors: list[str] = []

            if not check_id:
                row_errors.append(f"{where}: blank Check ID")
            elif not _TOKEN_RE.match(check_id):
                row_errors.append(f"{where}: Check ID is not a valid OSCAL token")
            elif check_id in seen:
                row_errors.append(f"{where}: duplicate Check ID (first on line {seen[check_id]})")
            else:
                seen[check_id] = line

            clause = _cell(record, COL_CLAUSE)
            section = section_of(clause)
            if not clause:
                row_errors.append(f"{where}: blank Clause")
            elif section is None:
                row_errors.append(f"{where}: no section number in Clause {clause!r}")
            elif section not in groups:
                row_errors.append(f"{where}: section {section} has no entry in the groups file")

            status, note = parse_numbering(_cell(record, COL_NUMBERING))
            if status not in NUMBERING_STATUSES:
                row_errors.append(
                    f"{where}: Numbering status {status!r} is not one of "
                    f"{sorted(NUMBERING_STATUSES)}"
                )

            check_type = _cell(record, COL_CHECK_TYPE)
            if not check_type:
                row_errors.append(f"{where}: blank Check type")

            check_en, check_fr = _cell(record, COL_CHECK_EN), _cell(record, COL_CHECK_FR)
            if not check_en:
                row_errors.append(f"{where}: blank Check (EN)")
            if not check_fr:
                row_errors.append(f"{where}: blank Contrôle (FR)")

            errors.extend(row_errors)
            if row_errors or section is None:
                continue

            if status == "Verify":
                warnings.append(
                    f"{check_id}: numbering marked Verify" + (f": {note}" if note else "")
                )
            if not _SINGLE_CLAUSE_RE.match(clause):
                warnings.append(
                    f"{check_id}: clause label {clause!r} is not a single number (kept as-is)"
                )
            id_clause = _ID_CLAUSE_RE.search(check_id)
            if id_clause and id_clause.group(0) != clause:
                warnings.append(
                    f"{check_id}: ID implies clause {id_clause.group(0)} but Clause is {clause!r}"
                )

            agreed_en, agreed_fr = _cell(record, COL_AGREED_EN), _cell(record, COL_AGREED_FR)
            rows.append(
                GoldenRow(
                    line=line,
                    check_id=check_id,
                    clause=clause,
                    group=section,
                    check_type=check_type,
                    numbering_status=status,
                    numbering_note=note,
                    statement={"en": agreed_en or check_en, "fr": agreed_fr or check_fr},
                    reviewed={"en": bool(agreed_en), "fr": bool(agreed_fr)},
                    guidance={
                        "en": _cell(record, COL_APPLIES_EN) or None,
                        "fr": _cell(record, COL_APPLIES_FR) or None,
                    },
                    objective={
                        "en": _cell(record, COL_EVIDENCE_EN) or None,
                        "fr": _cell(record, COL_EVIDENCE_FR) or None,
                    },
                )
            )

    if errors:
        raise GoldenImportError(errors)
    if not rows:
        raise GoldenImportError(["the CSV has no data rows"])
    return rows, warnings


def _hub_prop(name: str, value: str) -> dict[str, str]:
    return {"name": name, "ns": OSCAL_NS, "value": value}


def _control(row: GoldenRow, lang: Lang) -> dict[str, Any]:
    props: list[dict[str, str]] = [
        {"name": "label", "value": row.clause},
        _hub_prop("check-type", row.check_type),
        _hub_prop("numbering-status", row.numbering_status),
    ]
    if row.numbering_note:
        props.append(_hub_prop("numbering-note", row.numbering_note))
    props.append(_hub_prop("review-status", "reviewed" if row.reviewed[lang] else "draft"))

    parts: list[dict[str, str]] = [
        {"id": f"{row.check_id}_smt", "name": "statement", "prose": row.statement[lang]}
    ]
    guidance, objective = row.guidance[lang], row.objective[lang]
    if guidance:
        parts.append({"id": f"{row.check_id}_gdn", "name": "guidance", "prose": guidance})
    if objective:
        parts.append(
            {"id": f"{row.check_id}_obj", "name": "assessment-objective", "prose": objective}
        )
    return {"id": row.check_id, "title": row.check_id, "props": props, "parts": parts}


def _section_key(section: str) -> tuple[int, ...]:
    return tuple(int(p) for p in section.split("."))


def build_catalog(
    rows: Sequence[GoldenRow],
    groups: Mapping[str, GroupTitle],
    lang: Lang,
    *,
    name: str,
    version: str,
    source_name: str,
    last_modified: datetime,
) -> dict[str, Any]:
    """Build, normalize and schema-validate one language catalog.

    The top-level ``uuid`` is derived from the content hash, so the same content always
    yields the same uuid and any content change yields a new one.
    """
    src = SOURCE[lang]
    sections = sorted({r.group for r in rows}, key=_section_key)
    body: dict[str, Any] = {
        "uuid": "00000000-0000-4000-8000-000000000000",  # replaced below
        "metadata": {
            "title": src["title"],
            "last-modified": last_modified.isoformat(),
            "version": version,
            "oscal-version": OSCAL_VERSION,
            "props": [
                _hub_prop("catalog-name", name),
                _hub_prop("language", lang),
                _hub_prop("source-document", src["document"]),
                _hub_prop("source-amended", SOURCE_AMENDED),
                _hub_prop("statement-status", "paraphrase-pending-verification"),
                _hub_prop("source-file", source_name),
            ],
            "links": [{"href": src["href"], "rel": "reference", "text": src["document"]}],
            "remarks": src["remarks"].format(source=source_name),
        },
        "groups": [
            {
                "id": group_id(section),
                "class": "section",
                "title": groups[section].title[lang],
                "props": [{"name": "label", "value": section}],
                "controls": [_control(r, lang) for r in rows if r.group == section],
            }
            for section in sections
        ],
    }
    draft = normalize({"catalog": body}, "catalog")
    digest = content_hash(draft, "catalog")
    draft["catalog"]["uuid"] = stable_uuid("oscal-catalog", digest)
    final = normalize(draft, "catalog")
    validate(final, "catalog")
    return final


def _existing_last_modified(path: Path, digest: str) -> datetime | None:
    """Reuse the on-disk last-modified when the content is unchanged (keeps re-runs identical)."""
    if not path.is_file():
        return None
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if content_hash(existing, "catalog") != digest:
            return None
        return datetime.fromisoformat(existing["catalog"]["metadata"]["last-modified"])
    except (ValueError, KeyError, TypeError):
        return None


def import_golden(
    csv_path: Path,
    out_dir: Path,
    *,
    name: str | None = None,
    version: str = "1.0.0",
    groups_path: Path | None = None,
    last_modified: datetime | None = None,
    write: bool = True,
) -> ImportResult:
    """Import a golden-set CSV into EN and FR catalogs (validated, parity-checked)."""
    if not _SEMVER_RE.match(version):
        raise GoldenImportError([f"version {version!r} is not MAJOR.MINOR.PATCH"])
    name = name or csv_path.name.removesuffix(".csv")
    groups_path = groups_path or csv_path.with_name(f"{name}.groups.csv")
    if not groups_path.is_file():
        raise GoldenImportError([f"groups file not found: {groups_path}"])
    groups = read_groups(groups_path)
    rows, warnings = read_rows(csv_path, groups)
    now = (last_modified or datetime.now(UTC)).replace(microsecond=0)

    catalogs: dict[Lang, dict[str, Any]] = {}
    paths: dict[Lang, Path] = {}
    changed: dict[Lang, bool] = {}
    for lang in LANGS:
        path = out_dir / f"{name}.{lang}.json"
        kwargs: dict[str, Any] = {"name": name, "version": version, "source_name": csv_path.name}
        probe = build_catalog(rows, groups, lang, last_modified=now, **kwargs)
        stamp = (
            None if last_modified else _existing_last_modified(path, content_hash(probe, "catalog"))
        )
        catalog = (
            probe
            if stamp is None
            else build_catalog(rows, groups, lang, last_modified=stamp, **kwargs)
        )
        catalogs[lang], paths[lang] = catalog, path
        text = dump_json(catalog)
        changed[lang] = not path.is_file() or path.read_text(encoding="utf-8") != text
        if write and changed[lang]:
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    require_parity(catalogs["en"], catalogs["fr"])
    return ImportResult(
        name=name,
        version=version,
        source=csv_path,
        rows=rows,
        catalogs=catalogs,
        paths=paths,
        changed=changed,
        warnings=warnings,
    )


def format_summary(result: ImportResult) -> str:
    """Console summary of an import."""
    rows = result.rows
    lines = [
        f"Golden-set import: {result.source} -> {result.name} v{result.version}",
        f"  rows: {len(rows)}",
        "  groups:",
    ]
    by_group = Counter(r.group for r in rows)
    for section in sorted(by_group, key=_section_key):
        lines.append(f"    {group_id(section):<10} {by_group[section]:>3} controls")
    for label, counter in (
        ("numbering-status", Counter(r.numbering_status for r in rows)),
        ("check-type", Counter(r.check_type for r in rows)),
        ("review-status (en)", Counter("reviewed" if r.reviewed["en"] else "draft" for r in rows)),
        ("review-status (fr)", Counter("reviewed" if r.reviewed["fr"] else "draft" for r in rows)),
    ):
        lines.append(f"  {label}: " + ", ".join(f"{k}={v}" for k, v in sorted(counter.items())))
    fr_extra = {
        "guidance": sum(1 for r in rows if r.guidance["fr"]),
        "assessment-objective": sum(1 for r in rows if r.objective["fr"]),
    }
    lines.append(
        "  fr optional parts present: " + ", ".join(f"{k}={v}" for k, v in fr_extra.items())
    )
    lines.append("  EN/FR parity: OK (identical control IDs)")
    for lang in LANGS:
        doc = result.catalogs[lang]["catalog"]
        state = "written" if result.changed[lang] else "unchanged"
        lines.append(
            f"  {lang}: {result.paths[lang]}  schema OK (OSCAL {OSCAL_VERSION})  "
            f"uuid={doc['uuid']}  {state}"
        )
    lines.append(f"  warnings: {len(result.warnings)}")
    lines.extend(f"    - {w}" for w in result.warnings)
    return "\n".join(lines)
