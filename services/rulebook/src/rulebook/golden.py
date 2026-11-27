"""Golden-set importer: hand-mapped CSV -> separate EN and FR OSCAL 1.1.3 catalogs.

The CSV is the only source of check wording. This module copies text; it never writes,
translates or "fixes" policy text. Missing optional text is omitted, not filled in.

Mapping (one CSV row -> one control in each language catalog, identical IDs):

- ``id`` = Check ID; ``title`` = Check ID (the CSV has no title column)
- props: ``label`` = Clause (as-is); namespaced ``check-type`` and ``numbering-status``
  (language-neutral codes, see ``CHECK_TYPE_CODES``/``NUMBERING_STATUS_CODES``),
  ``numbering-note`` + ``numbering-note-lang`` (if any),
  ``review-status`` (``reviewed`` | ``draft``)
- parts: ``statement`` = agreed wording if filled, else Check (EN) / Contrôle (FR);
  ``guidance`` = Applies when; ``assessment-objective`` = Evidence that would satisfy it.
  French guidance/objective/agreed wording come only from the optional columns
  ``S'applique lorsque``, ``Preuves attendues``, ``Libellé final convenu``.
- groups: first ``N.N`` section number found in the Clause column (``6.3.9 or 6.3.10`` -> 6.3),
  id ``dadm-6.3``
- ``last-modified`` = ``SOURCE_DATE`` from ``<name>.settings.toml`` (never the clock)
"""

from __future__ import annotations

import csv
import json
import re
import tomllib
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from govhub_shared import OSCAL_NS, OSCAL_VERSION
from govhub_shared.obligations import OBLIGATION_CODES
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
# Optional: semicolon-separated clause numbers in the source version named by SOURCE_VERSION.
# Empty means "no links yet" (reported, not an error).
COL_SOURCE_CLAUSES = "Source clauses"
# Optional (Milestone 6). Blank or absent -> nothing is added to the catalog.
COL_OBLIGATION = "Obligation"  # language-neutral code (OBLIGATION_CODES)
COL_STATUS = "Status"  # active (default) | withdrawn: a retired control stays, withdrawn
COL_GROUP = "Group"  # explicit Section key of the groups file (default: from Clause)
COL_DRAFTED_BY = "Drafted by"  # provenance of AI-drafted wording, e.g. "model qwen3-8b ..."
COL_APPROVED_BY = "Approved by"  # the person who approved the drafted wording
COL_APPROVAL_RECORD = "Approval record"  # approval-log seq and hash
STATUS_CODES: tuple[str, ...] = ("active", "withdrawn")

# Controlled vocabularies: CSV display value -> language-neutral code stored in both catalogs.
NUMBERING_STATUS_CODES: dict[str, str] = {
    "Confirmed": "confirmed",
    "Likely": "likely",
    "Verify": "verify",
}
CHECK_TYPE_CODES: dict[str, str] = {
    "Rule-based": "rule-based",
    "Rule-based (roll-up)": "rule-based-roll-up",
    "Judgment": "judgment",
}
NOTE_LANG = "en"  # numbering notes are written by the (English-language) annotators
_SECTION_RE = re.compile(r"(\d+)\.(\d+)")
_SINGLE_CLAUSE_RE = re.compile(r"^\d+(?:\.\d+)+$")
_ID_CLAUSE_RE = re.compile(r"\d+(?:\.\d+)+")
_TOKEN_RE = re.compile(r"^[^\W\d][\w.\-]*$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


class GoldenImportError(ValueError):
    """The CSV cannot be imported. Lists every problem found, not just the first."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = list(errors)
        super().__init__("golden-set import failed:\n" + "\n".join(f"  - {e}" for e in self.errors))


@dataclass(frozen=True)
class CatalogText:
    document: str
    href: str
    title: str
    remarks: str


@dataclass(frozen=True)
class GoldenSettings:
    """Everything about a golden set that is not in its CSV (``<name>.settings.toml``)."""

    path: Path
    source_date: datetime
    version: str
    group_prefix: str
    source_instrument: str
    source_version: str
    source_meta_dir: Path
    statement_status: str
    catalog: dict[Lang, CatalogText]
    # Optional: the official file hash per language when no meta file is at hand (the
    # rulebook rebuilding a version from its database), and the approval-log head stamped
    # on a version produced by approved drafts (APPROVAL_LOG_HEAD).
    source_hashes: dict[Lang, str] | None = None
    approval_log_head: str | None = None

    def meta_path(self, lang: Lang) -> Path:
        name = f"{self.source_instrument}.{self.source_version}.{lang}.meta.json"
        return self.source_meta_dir / name


@dataclass(frozen=True)
class GroupTitle:
    section: str
    title: dict[Lang, str]
    group_id: str | None = None  # explicit ID (new groups: neutral <prefix>-G<nn>)


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
    source_clauses: tuple[str, ...] = ()
    obligation: str | None = None
    status: str = "active"
    drafted_by: str | None = None
    approved_by: str | None = None
    approval_record: str | None = None


@dataclass
class ImportResult:
    settings: GoldenSettings
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


def group_id(section: str, prefix: str = "dadm") -> str:
    return f"{prefix}-{section}"


def read_groups(path: Path) -> dict[str, GroupTitle]:
    with path.open(encoding="utf-8", newline="") as fh:
        return {
            _cell(r, "Section"): GroupTitle(
                section=_cell(r, "Section"),
                title={"en": _cell(r, "Title (EN)"), "fr": _cell(r, "Titre (FR)")},
                group_id=_cell(r, "Group ID") or None,
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
            section = _cell(record, COL_GROUP) or section_of(clause)
            if not clause:
                row_errors.append(f"{where}: blank Clause")
            elif section is None:
                row_errors.append(f"{where}: no section number in Clause {clause!r}")
            elif section not in groups:
                row_errors.append(f"{where}: section {section} has no entry in the groups file")

            status_label, note = parse_numbering(_cell(record, COL_NUMBERING))
            status = NUMBERING_STATUS_CODES.get(status_label)
            if status is None:
                row_errors.append(
                    f"{where}: Numbering status {status_label!r} is not one of "
                    f"{list(NUMBERING_STATUS_CODES)}"
                )

            check_type_label = _cell(record, COL_CHECK_TYPE)
            check_type = CHECK_TYPE_CODES.get(check_type_label)
            if check_type is None:
                row_errors.append(
                    f"{where}: Check type {check_type_label!r} is not one of "
                    f"{list(CHECK_TYPE_CODES)}"
                )

            check_en, check_fr = _cell(record, COL_CHECK_EN), _cell(record, COL_CHECK_FR)
            if not check_en:
                row_errors.append(f"{where}: blank Check (EN)")
            if not check_fr:
                row_errors.append(f"{where}: blank Contrôle (FR)")

            errors.extend(row_errors)
            if row_errors or section is None or status is None or check_type is None:
                continue

            if status == "verify":
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

            links = tuple(
                p.strip() for p in _cell(record, COL_SOURCE_CLAUSES).split(";") if p.strip()
            )
            bad_links = [n for n in links if not _SINGLE_CLAUSE_RE.match(n)]
            if bad_links:
                errors.append(f"{where}: Source clauses {bad_links} are not clause numbers")
                continue
            if len(set(links)) != len(links):
                errors.append(f"{where}: Source clauses lists a clause twice")
                continue
            obligation = _cell(record, COL_OBLIGATION) or None
            if obligation is not None and obligation not in OBLIGATION_CODES:
                errors.append(
                    f"{where}: Obligation {obligation!r} is not one of {list(OBLIGATION_CODES)}"
                )
                continue
            row_status = _cell(record, COL_STATUS) or "active"
            if row_status not in STATUS_CODES:
                errors.append(f"{where}: Status {row_status!r} is not one of {list(STATUS_CODES)}")
                continue
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
                    source_clauses=links,
                    obligation=obligation,
                    status=row_status,
                    drafted_by=_cell(record, COL_DRAFTED_BY) or None,
                    approved_by=_cell(record, COL_APPROVED_BY) or None,
                    approval_record=_cell(record, COL_APPROVAL_RECORD) or None,
                )
            )

    if errors:
        raise GoldenImportError(errors)
    if not rows:
        raise GoldenImportError(["the CSV has no data rows"])
    return rows, warnings


def _hub_prop(name: str, value: str) -> dict[str, str]:
    return {"name": name, "ns": OSCAL_NS, "value": value}


def _control(row: GoldenRow, lang: Lang, resource_uuid: str | None = None) -> dict[str, Any]:
    props: list[dict[str, str]] = [
        {"name": "label", "value": row.clause},
        _hub_prop("check-type", row.check_type),
        _hub_prop("numbering-status", row.numbering_status),
    ]
    if row.numbering_note:
        props.append(_hub_prop("numbering-note", row.numbering_note))
        props.append(_hub_prop("numbering-note-lang", NOTE_LANG))
    props.append(_hub_prop("review-status", "reviewed" if row.reviewed[lang] else "draft"))
    props.extend(_hub_prop("source-clause", number) for number in row.source_clauses)
    if row.obligation:
        props.append(_hub_prop("obligation", row.obligation))
    if row.status == "withdrawn":
        props.append({"name": "status", "value": "withdrawn"})  # OSCAL core prop
    for name, value in (
        ("drafted-by", row.drafted_by),
        ("approved-by", row.approved_by),
        ("approval-record", row.approval_record),
    ):
        if value:
            props.append(_hub_prop(name, value))

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
    control: dict[str, Any] = {"id": row.check_id, "title": row.check_id, "props": props}
    if row.source_clauses and resource_uuid:
        control["links"] = [{"href": f"#{resource_uuid}", "rel": "reference"}]
    control["parts"] = parts
    return control


def _source_resource(settings: GoldenSettings, lang: Lang) -> tuple[str, dict[str, Any]]:
    """Back-matter resource describing the source version that source-clause props cite."""
    uuid = stable_uuid("source-document", settings.source_instrument, settings.source_version, lang)
    rlink: dict[str, Any] = {"href": settings.catalog[lang].href}
    meta = settings.meta_path(lang)
    file_hash = (settings.source_hashes or {}).get(lang)
    if file_hash is None and meta.is_file():
        file_hash = json.loads(meta.read_text(encoding="utf-8"))["file"]["sha256"]
    if file_hash:
        rlink["hashes"] = [{"algorithm": "SHA-256", "value": file_hash}]
    return uuid, {
        "uuid": uuid,
        "title": f"{settings.catalog[lang].document} ({settings.source_version})",
        "props": [
            _hub_prop("source-instrument", settings.source_instrument),
            _hub_prop("source-version", settings.source_version),
            _hub_prop("language", lang),
        ],
        "rlinks": [rlink],
    }


def check_source_links(rows: Sequence[GoldenRow], settings: GoldenSettings) -> list[str]:
    """Every linked clause must exist in the source version (both languages)."""
    linked = [r for r in rows if r.source_clauses and r.status != "withdrawn"]
    if not linked:
        return []
    errors: list[str] = []
    for lang in LANGS:
        meta = settings.meta_path(lang)
        if not meta.is_file():
            errors.append(
                f"cannot check Source clauses: {meta} not found (import the {lang} source "
                f"{settings.source_instrument} {settings.source_version} first)"
            )
            continue
        numbers = {c["number"] for c in json.loads(meta.read_text(encoding="utf-8"))["clauses"]}
        for row in linked:
            missing = [n for n in row.source_clauses if n not in numbers]
            if missing:
                errors.append(
                    f"{row.check_id}: Source clauses {missing} not in "
                    f"{settings.source_instrument} {settings.source_version} ({lang})"
                )
    return errors


def _section_key(section: str) -> tuple[int, ...]:
    """Numeric sort key of a section ("6.2"); a later-version key ("6.2@2025-01-01") sorts
    right after the plain sections, by version."""
    number, _, version = section.partition("@")
    numbers = tuple(int(p) for p in number.split("."))
    if not version:
        return (0, *numbers)
    return (1, *(int(p) for p in version.split("-")), *numbers)


def build_catalog(
    rows: Sequence[GoldenRow],
    groups: Mapping[str, GroupTitle],
    lang: Lang,
    *,
    name: str,
    version: str,
    source_name: str,
    last_modified: datetime,
    settings: GoldenSettings,
) -> dict[str, Any]:
    """Build, normalize and schema-validate one language catalog.

    The top-level ``uuid`` is derived from the content hash, so the same content always
    yields the same uuid and any content change yields a new one.
    """
    src = settings.catalog[lang]
    resource_uuid, resource = _source_resource(settings, lang)
    sections = sorted({r.group for r in rows}, key=_section_key)
    group_ids = {
        section: groups[section].group_id or group_id(section, settings.group_prefix)
        for section in sections
    }
    body: dict[str, Any] = {
        "uuid": "00000000-0000-4000-8000-000000000000",  # replaced below
        "metadata": {
            "title": src.title,
            "last-modified": last_modified.isoformat(),
            "version": version,
            "oscal-version": OSCAL_VERSION,
            "props": [
                _hub_prop("catalog-name", name),
                _hub_prop("language", lang),
                _hub_prop("source-document", src.document),
                _hub_prop("source-amended", settings.source_version),
                _hub_prop("statement-status", settings.statement_status),
                _hub_prop("source-file", source_name),
                _hub_prop("source-instrument", settings.source_instrument),
                _hub_prop("source-version", settings.source_version),
                *(
                    [_hub_prop("approval-log-head", settings.approval_log_head)]
                    if settings.approval_log_head
                    else []
                ),
            ],
            "links": [{"href": src.href, "rel": "reference", "text": src.document}],
            "remarks": src.remarks.format(source=source_name),
        },
        "groups": [
            {
                "id": group_ids[section],
                "class": "section",
                "title": groups[section].title[lang],
                "props": [{"name": "label", "value": section}],
                "controls": [_control(r, lang, resource_uuid) for r in rows if r.group == section],
            }
            for section in sections
        ],
        "back-matter": {"resources": [resource]},
    }
    draft = normalize({"catalog": body}, "catalog")
    digest = content_hash(draft, "catalog")
    draft["catalog"]["uuid"] = stable_uuid("oscal-catalog", digest)
    final = normalize(draft, "catalog")
    validate(final, "catalog")
    return final


def _setting(settings: Mapping[str, Any], key: str, path: Path, default: str | None = None) -> str:
    value = settings.get(key, default)
    if not isinstance(value, str) or not value:
        raise GoldenImportError([f"{path}: {key} must be a non-empty string"])
    return value


def read_settings(path: Path) -> GoldenSettings:
    """Read the golden-set settings file.

    ``SOURCE_DATE`` (ISO 8601 with a UTC offset) becomes every catalog's ``last-modified``,
    so output never depends on the clock. Bump it whenever the CSV or groups file changes.
    """
    try:
        settings = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise GoldenImportError([f"settings file not found: {path}"]) from None
    except tomllib.TOMLDecodeError as exc:
        raise GoldenImportError([f"{path}: invalid TOML: {exc}"]) from None
    raw = settings.get("SOURCE_DATE")
    if not isinstance(raw, str):
        raise GoldenImportError([f"{path}: SOURCE_DATE must be an ISO 8601 string"])
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        raise GoldenImportError([f"{path}: SOURCE_DATE {raw!r} is not ISO 8601"]) from None
    if value.tzinfo is None:
        raise GoldenImportError([f"{path}: SOURCE_DATE {raw!r} needs a UTC offset (e.g. Z)"])
    version = _setting(settings, "VERSION", path, "1.0.0")
    if not _SEMVER_RE.match(version):
        raise GoldenImportError([f"{path}: VERSION {version!r} is not MAJOR.MINOR.PATCH"])
    catalog_tables = settings.get("catalog", {})
    catalog: dict[Lang, CatalogText] = {}
    for lang in LANGS:
        table = catalog_tables.get(lang)
        if not isinstance(table, dict):
            raise GoldenImportError([f"{path}: missing [catalog.{lang}] table"])
        catalog[lang] = CatalogText(
            **{k: _setting(table, k, path) for k in ("document", "href", "title", "remarks")}
        )
    return GoldenSettings(
        path=path,
        source_date=value.astimezone(UTC).replace(microsecond=0),
        version=version,
        group_prefix=_setting(settings, "GROUP_PREFIX", path),
        source_instrument=_setting(settings, "SOURCE_INSTRUMENT", path),
        source_version=_setting(settings, "SOURCE_VERSION", path),
        source_meta_dir=(path.parent / _setting(settings, "SOURCE_META_DIR", path)).resolve(),
        statement_status=_setting(
            settings, "STATEMENT_STATUS", path, "paraphrase-pending-verification"
        ),
        catalog=catalog,
        approval_log_head=settings.get("APPROVAL_LOG_HEAD") or None,
    )


def import_golden(
    csv_path: Path,
    out_dir: Path,
    *,
    name: str | None = None,
    version: str | None = None,
    groups_path: Path | None = None,
    settings_path: Path | None = None,
    source_date: datetime | None = None,
    write: bool = True,
) -> ImportResult:
    """Import a golden-set CSV into EN and FR catalogs (validated, parity-checked)."""
    if version is not None and not _SEMVER_RE.match(version):
        raise GoldenImportError([f"version {version!r} is not MAJOR.MINOR.PATCH"])
    name = name or csv_path.name.removesuffix(".csv")
    groups_path = groups_path or csv_path.with_name(f"{name}.groups.csv")
    if not groups_path.is_file():
        raise GoldenImportError([f"groups file not found: {groups_path}"])
    groups = read_groups(groups_path)
    rows, warnings = read_rows(csv_path, groups)
    settings = read_settings(settings_path or csv_path.with_name(f"{name}.settings.toml"))
    link_errors = check_source_links(rows, settings)
    if link_errors:
        raise GoldenImportError(link_errors)
    source_date = source_date or settings.source_date
    version = version or settings.version

    kwargs: dict[str, Any] = {
        "name": name,
        "version": version,
        "source_name": csv_path.name,
        "settings": settings,
    }
    catalogs: dict[Lang, dict[str, Any]] = {
        lang: build_catalog(rows, groups, lang, last_modified=source_date, **kwargs)
        for lang in LANGS
    }
    require_parity(catalogs["en"], catalogs["fr"])

    paths: dict[Lang, Path] = {}
    changed: dict[Lang, bool] = {}
    for lang in LANGS:
        path = paths[lang] = out_dir / f"{name}.{lang}.json"
        text = dump_json(catalogs[lang])
        changed[lang] = not path.is_file() or path.read_text(encoding="utf-8") != text
        if write and changed[lang]:
            out_dir.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    return ImportResult(
        settings=settings,
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
        gid = group_id(section, result.settings.group_prefix)
        lines.append(f"    {gid:<10} {by_group[section]:>3} controls")
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
    settings = result.settings
    unlinked = [r.check_id for r in rows if not r.source_clauses]
    lines.append(
        f"  source links ({settings.source_instrument} {settings.source_version}): "
        f"{len(rows) - len(unlinked)}/{len(rows)} controls linked"
    )
    if unlinked:
        lines.append(f"    no links yet ({len(unlinked)}): {', '.join(unlinked)}")
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
