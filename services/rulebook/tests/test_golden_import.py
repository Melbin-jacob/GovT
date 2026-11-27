from __future__ import annotations

import copy
import csv
import json
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from govhub_shared import OSCAL_NS
from govhub_shared.oscal import iter_controls, validate
from rulebook.cli import main
from rulebook.golden import (
    CHECK_TYPE_CODES,
    NUMBERING_STATUS_CODES,
    GoldenImportError,
    import_golden,
    parse_numbering,
    section_of,
)
from rulebook.parity import ParityError, check_parity, require_parity

REPO = Path(__file__).resolve().parents[3]
GOLDEN = REPO / "data" / "golden" / "dadm-section6.csv"
GROUPS = REPO / "data" / "golden" / "dadm-section6.groups.csv"
SETTINGS = REPO / "data" / "golden" / "dadm-section6.settings.toml"
COMMITTED = REPO / "data" / "catalogs"
FIXED = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)


def _csv_rows() -> tuple[list[str], list[dict[str, str]]]:
    with GOLDEN.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader.fieldnames or []), list(reader)


def _write_variant(
    tmp_path: Path, rows: list[dict[str, str]], fieldnames: list[str] | None = None
) -> Path:
    """Write a modified copy of the golden CSV (plus its groups file) into tmp_path."""
    header = fieldnames or _csv_rows()[0]
    path = tmp_path / "dadm-section6.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=header, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    shutil.copy(GROUPS, tmp_path / "dadm-section6.groups.csv")
    shutil.copy(SETTINGS, tmp_path / "dadm-section6.settings.toml")
    return path


def _by_id(doc: dict[str, Any]) -> dict[str, Any]:
    return {c.id: c for c in iter_controls(doc)}


# --- the real golden set ---------------------------------------------------------------


def test_real_golden_set_imports(tmp_path: Path) -> None:
    result = import_golden(GOLDEN, tmp_path, source_date=FIXED)
    assert len(result.rows) == 39
    assert Counter(r.group for r in result.rows) == {
        "6.1": 6,
        "6.2": 9,
        "6.3": 19,
        "6.4": 2,
        "6.5": 3,
    }
    assert Counter(r.numbering_status for r in result.rows) == {
        "confirmed": 6,
        "likely": 14,
        "verify": 19,
    }
    assert Counter(r.check_type for r in result.rows) == {
        "judgment": 23,
        "rule-based": 15,
        "rule-based-roll-up": 1,
    }
    for lang in ("en", "fr"):
        on_disk = json.loads((tmp_path / f"dadm-section6.{lang}.json").read_text("utf-8"))
        validate(on_disk, "catalog")  # independent re-validation of the written file
        assert on_disk == result.catalogs[lang]
        meta = on_disk["catalog"]["metadata"]
        assert meta["oscal-version"] == "1.1.3"
        assert meta["version"] == "1.0.0"
        props = {p["name"]: p["value"] for p in meta["props"]}
        assert props["source-amended"] == "2025-06-24"
        assert props["statement-status"] == "paraphrase-pending-verification"
        assert props["language"] == lang
    require_parity(result.catalogs["en"], result.catalogs["fr"])


def test_committed_catalogs_are_up_to_date_and_valid() -> None:
    result = import_golden(GOLDEN, COMMITTED, write=False)
    assert result.changed == {"en": False, "fr": False}, "re-run `rulebook import-golden`"
    for lang in ("en", "fr"):
        validate(json.loads((COMMITTED / f"dadm-section6.{lang}.json").read_text()), "catalog")


def test_round_trip_matches_csv_cells(tmp_path: Path) -> None:
    """Every text field in the catalogs is copied verbatim from the CSV."""
    result = import_golden(GOLDEN, tmp_path, source_date=FIXED)
    en, fr = _by_id(result.catalogs["en"]), _by_id(result.catalogs["fr"])
    _, rows = _csv_rows()
    assert [r["Check ID"] for r in rows] == list(en)  # order preserved within the CSV
    for row in rows:
        cid = row["Check ID"]
        status, note = parse_numbering(row["Numbering"])
        for control in (en[cid], fr[cid]):
            assert control.prop("label") == row["Clause (draft numbering)"]
            assert control.hub_prop("check-type") == CHECK_TYPE_CODES[row["Check type"]]
            assert control.hub_prop("numbering-status") == NUMBERING_STATUS_CODES[status]
            assert control.hub_prop("numbering-note") == note
            assert control.hub_prop("numbering-note-lang") == ("en" if note else None)
            assert control.hub_prop("review-status") == "draft"
            assert control.title == cid
        assert en[cid].part("statement") == row["Check (EN)"]
        assert en[cid].part("guidance") == row["Applies when"]
        assert en[cid].part("assessment-objective") == row["Evidence that would satisfy it"]
        assert fr[cid].part("statement") == row["Contrôle (FR)"]
        assert fr[cid].part("guidance") is None  # no FR column yet: omitted, not translated
        assert fr[cid].part("assessment-objective") is None


def test_custom_props_are_namespaced(tmp_path: Path) -> None:
    result = import_golden(GOLDEN, tmp_path, source_date=FIXED)
    for control in iter_controls(result.catalogs["en"]):
        for prop in control.props:
            assert prop.ns == (None if prop.name == "label" else OSCAL_NS)


# --- grouping and numbering ------------------------------------------------------------


@pytest.mark.parametrize(
    ("clause", "section"),
    [
        ("6.1.1", "6.1"),
        ("6.2.6.1", "6.2"),
        ("6.3.9 or 6.3.10", "6.3"),
        ("6.3.9 (French draft only)", "6.3"),
        ("Appendix C", None),
    ],
)
def test_section_of(clause: str, section: str | None) -> None:
    assert section_of(clause) == section


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Confirmed", ("Confirmed", None)),
        ("Verify", ("Verify", None)),
        (
            "Verify: numbering differs between drafts",
            ("Verify", "numbering differs between drafts"),
        ),
        ("Verify: a: b", ("Verify", "a: b")),
    ],
)
def test_parse_numbering(value: str, expected: tuple[str, str | None]) -> None:
    assert parse_numbering(value) == expected


def test_group_ids_and_titles(tmp_path: Path) -> None:
    result = import_golden(GOLDEN, tmp_path, source_date=FIXED)
    for lang, titles in (
        (
            "en",
            [
                "Algorithmic Impact Assessment",
                "Transparency",
                "Quality assurance",
                "Recourse",
                "Reporting",
            ],
        ),
        (
            "fr",
            [
                "Évaluation de l'incidence algorithmique",
                "Transparence",
                "Assurance de la qualité",
                "Recours",
                "Établissement de rapports",
            ],
        ),
    ):
        groups = result.catalogs[lang]["catalog"]["groups"]
        assert [g["id"] for g in groups] == [f"dadm-6.{i}" for i in range(1, 6)]
        assert [g["title"] for g in groups] == titles


def test_rows_without_section_in_id_are_grouped_by_clause(tmp_path: Path) -> None:
    result = import_golden(GOLDEN, tmp_path, source_date=FIXED)
    groups = {
        c.id: c.group_id
        for c in iter_controls(result.catalogs["en"])
        if c.id in {"DADM-SECURITY", "DADM-LEGAL", "DADM-HUMAN", "DADM-APPROVAL"}
    }
    assert set(groups.values()) == {"dadm-6.3"}
    security = _by_id(result.catalogs["en"])["DADM-SECURITY"]
    assert security.prop("label") == "6.3.9 or 6.3.10"  # not normalized


# --- determinism and document identity -------------------------------------------------


def test_fresh_import_into_empty_folder_matches_committed_files(tmp_path: Path) -> None:
    """No clock involved: a clean import reproduces the committed catalogs byte for byte."""
    import_golden(GOLDEN, tmp_path)
    for lang in ("en", "fr"):
        name = f"dadm-section6.{lang}.json"
        assert (tmp_path / name).read_bytes() == (COMMITTED / name).read_bytes()


def test_rerun_is_byte_identical(tmp_path: Path) -> None:
    import_golden(GOLDEN, tmp_path)
    first = {p.name: p.read_bytes() for p in tmp_path.glob("*.json")}
    result = import_golden(GOLDEN, tmp_path)
    assert result.changed == {"en": False, "fr": False}
    assert {p.name: p.read_bytes() for p in tmp_path.glob("*.json")} == first


def test_last_modified_comes_from_source_date(tmp_path: Path) -> None:
    result = import_golden(GOLDEN, tmp_path)
    for lang in ("en", "fr"):
        stamp = result.catalogs[lang]["catalog"]["metadata"]["last-modified"]
        assert datetime.fromisoformat(stamp) == datetime(2026, 11, 26, tzinfo=UTC)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("", "SOURCE_DATE must be"),
        ('SOURCE_DATE = "26 Nov 2026"', "not ISO 8601"),
        ('SOURCE_DATE = "2026-11-26T00:00:00"', "needs a UTC offset"),
        ("SOURCE_DATE = [", "invalid TOML"),
    ],
)
def test_bad_settings_fail(tmp_path: Path, content: str, message: str) -> None:
    header, rows = _csv_rows()
    path = _write_variant(tmp_path, rows, header)
    (tmp_path / "dadm-section6.settings.toml").write_text(content, encoding="utf-8")
    with pytest.raises(GoldenImportError, match=re.escape(message)):
        import_golden(path, tmp_path / "o")


def test_same_content_same_uuid_changed_content_new_uuid(tmp_path: Path) -> None:
    a = import_golden(GOLDEN, tmp_path / "a", source_date=FIXED)
    b = import_golden(GOLDEN, tmp_path / "b", source_date=FIXED)
    assert a.catalogs == b.catalogs

    header, rows = _csv_rows()
    rows[0]["Check (EN)"] += " (edited)"
    c = import_golden(_write_variant(tmp_path, rows, header), tmp_path / "c", source_date=FIXED)
    assert c.catalogs["en"]["catalog"]["uuid"] != a.catalogs["en"]["catalog"]["uuid"]
    assert c.catalogs["fr"]["catalog"]["uuid"] == a.catalogs["fr"]["catalog"]["uuid"]


# --- review status and optional French columns ------------------------------------------


def test_agreed_wording_reviews_english_only(tmp_path: Path) -> None:
    header, rows = _csv_rows()
    rows[0]["Agreed final wording"] = "Agreed English wording."
    result = import_golden(_write_variant(tmp_path, rows, header), tmp_path / "o")
    cid = rows[0]["Check ID"]
    en, fr = _by_id(result.catalogs["en"])[cid], _by_id(result.catalogs["fr"])[cid]
    assert en.part("statement") == "Agreed English wording."
    assert en.hub_prop("review-status") == "reviewed"
    assert fr.part("statement") == rows[0]["Contrôle (FR)"]
    assert fr.hub_prop("review-status") == "draft"


def test_optional_french_columns_are_used_when_present(tmp_path: Path) -> None:
    header, rows = _csv_rows()
    header = [*header, "S'applique lorsque", "Preuves attendues", "Libellé final convenu"]
    for row in rows:
        row.update({"S'applique lorsque": "", "Preuves attendues": "", "Libellé final convenu": ""})
    rows[0].update(
        {
            "S'applique lorsque": "Condition FR.",
            "Preuves attendues": "Preuve FR.",
            "Libellé final convenu": "Libellé FR convenu.",
        }
    )
    result = import_golden(_write_variant(tmp_path, rows, header), tmp_path / "o")
    fr = _by_id(result.catalogs["fr"])
    first, second = fr[rows[0]["Check ID"]], fr[rows[1]["Check ID"]]
    assert first.part("statement") == "Libellé FR convenu."
    assert first.part("guidance") == "Condition FR."
    assert first.part("assessment-objective") == "Preuve FR."
    assert first.hub_prop("review-status") == "reviewed"
    assert second.part("guidance") is None  # blank optional cell -> omitted
    assert second.hub_prop("review-status") == "draft"
    assert _by_id(result.catalogs["en"])[rows[0]["Check ID"]].hub_prop("review-status") == "draft"


# --- failures --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda rows: rows[3].update({"Check ID": ""}), "blank Check ID"),
        (lambda rows: rows[3].update({"Check ID": rows[2]["Check ID"]}), "duplicate Check ID"),
        (lambda rows: rows[3].update({"Clause (draft numbering)": "Appendix C"}), "no section"),
        (lambda rows: rows[3].update({"Clause (draft numbering)": "7.1.1"}), "groups file"),
        (lambda rows: rows[3].update({"Numbering": "Maybe"}), "Numbering status"),
        (lambda rows: rows[3].update({"Numbering": "verify"}), "Numbering status"),
        (lambda rows: rows[3].update({"Check type": "Heuristic"}), "Check type"),
        (lambda rows: rows[3].update({"Check type": ""}), "Check type"),
        (lambda rows: rows[3].update({"Contrôle (FR)": ""}), "blank Contrôle (FR)"),
        (lambda rows: rows[3].update({"Check (EN)": " "}), "blank Check (EN)"),
        (lambda rows: rows[3].update({"Check ID": "6.1.1"}), "not a valid OSCAL token"),
    ],
)
def test_bad_rows_fail_loudly(tmp_path: Path, mutate: Any, message: str) -> None:
    header, rows = _csv_rows()
    mutate(rows)
    with pytest.raises(GoldenImportError, match=re.escape(message)):
        import_golden(_write_variant(tmp_path, rows, header), tmp_path / "o")
    assert not (tmp_path / "o").exists()  # nothing written on failure


def test_missing_required_column_fails(tmp_path: Path) -> None:
    header, rows = _csv_rows()
    header.remove("Check type")
    for row in rows:
        del row["Check type"]
    with pytest.raises(GoldenImportError, match="missing required column"):
        import_golden(_write_variant(tmp_path, rows, header), tmp_path / "o")


def test_parity_fails_when_a_control_is_missing(tmp_path: Path) -> None:
    result = import_golden(GOLDEN, tmp_path, source_date=FIXED)
    fr = copy.deepcopy(result.catalogs["fr"])
    fr["catalog"]["groups"][0]["controls"].pop(0)
    report = check_parity(result.catalogs["en"], fr)
    assert report.only_en == ("DADM-6.1.1-A",)
    assert report.only_fr == ()
    with pytest.raises(ParityError):
        require_parity(result.catalogs["en"], fr)


# --- CLI -------------------------------------------------------------------------------


def test_cli_import_and_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert main(["import-golden", str(GOLDEN), "--out-dir", str(out), "--check"]) == 1
    assert not out.exists()
    assert main(["import-golden", str(GOLDEN), "--out-dir", str(out)]) == 0
    assert "rows: 39" in capsys.readouterr().out
    assert main(["import-golden", str(GOLDEN), "--out-dir", str(out), "--check"]) == 0


def test_cli_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    header, rows = _csv_rows()
    rows[1]["Check ID"] = ""
    path = _write_variant(tmp_path, rows, header)
    assert main(["import-golden", str(path), "--out-dir", str(tmp_path / "o")]) == 2
    assert "blank Check ID" in capsys.readouterr().err
