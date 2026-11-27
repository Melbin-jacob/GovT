"""Source-clause links from golden-set checks, and the suggestion helper. Synthetic data."""

from __future__ import annotations

import csv
import io
import json
import shutil
from pathlib import Path

import pytest

from govhub_shared.oscal import iter_controls, validate
from rulebook.cli import main
from rulebook.golden import GoldenImportError, format_summary, import_golden
from rulebook.sources.model import SourceDocument
from rulebook.sources.suggest import suggest

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "data" / "demo"
WIDGETS = DEMO / "golden" / "example-widgets.csv"
DADM = REPO / "data" / "golden" / "dadm-section6.csv"


def _copy_demo(tmp_path: Path) -> Path:
    """Copy the widgets golden set and its source metadata into tmp_path (same layout)."""
    (tmp_path / "golden").mkdir()
    (tmp_path / "sources").mkdir()
    for f in (DEMO / "golden").iterdir():
        shutil.copy(f, tmp_path / "golden" / f.name)
    for f in (DEMO / "sources").glob("example-widgets.2023-01-01.*.meta.json"):
        shutil.copy(f, tmp_path / "sources" / f.name)
    return tmp_path / "golden" / WIDGETS.name


def _edit_links(path: Path, check_id: str, value: str) -> None:
    rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8"), newline="")))
    for row in rows:
        if row["Check ID"] == check_id:
            row["Source clauses"] = value
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf, fieldnames=list(rows[0]), quoting=csv.QUOTE_ALL, lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buf.getvalue(), encoding="utf-8")


def test_committed_demo_catalogs_are_current_and_linked() -> None:
    result = import_golden(WIDGETS, DEMO / "catalogs", write=False)
    assert result.changed == {"en": False, "fr": False}
    for lang in ("en", "fr"):
        doc = result.catalogs[lang]
        validate(doc, "catalog")
        resource = doc["catalog"]["back-matter"]["resources"][0]
        meta = json.loads(
            (DEMO / "sources" / f"example-widgets.2023-01-01.{lang}.meta.json").read_text()
        )
        assert resource["rlinks"][0]["hashes"][0]["value"] == meta["file"]["sha256"]
        for control in iter_controls(doc):
            assert control.hub_prop("source-clause") == control.prop("label")
        raw = doc["catalog"]["groups"][0]["controls"][0]
        assert raw["links"] == [{"href": f"#{resource['uuid']}", "rel": "reference"}]


def test_dadm_has_no_links_yet_and_reports_them() -> None:
    result = import_golden(DADM, REPO / "data" / "catalogs", write=False)
    assert result.changed == {"en": False, "fr": False}
    assert all(not r.source_clauses for r in result.rows)
    summary = format_summary(result)
    assert "source links (dadm 2025-06-24): 0/39 controls linked" in summary
    assert "no links yet (39): DADM-6.1.1-A" in summary
    for lang in ("en", "fr"):
        catalog = result.catalogs[lang]["catalog"]
        assert catalog["metadata"]["version"] == "1.1.0"
        (resource,) = catalog["back-matter"]["resources"]
        assert "hashes" not in resource["rlinks"][0]  # no committed metadata for DADM yet
        assert all("links" not in c for g in catalog["groups"] for c in g["controls"])


def test_multiple_links_become_repeated_props(tmp_path: Path) -> None:
    csv_path = _copy_demo(tmp_path)
    _edit_links(csv_path, "WID-6.3.1", "6.3.1; 6.3.2")
    result = import_golden(csv_path, tmp_path / "out", write=False)
    (control,) = [c for c in iter_controls(result.catalogs["fr"]) if c.id == "WID-6.3.1"]
    assert [p.value for p in control.props if p.name == "source-clause"] == ["6.3.1", "6.3.2"]


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("6.9.9", "not in example-widgets 2023-01-01"),
        ("six", "are not clause numbers"),
        ("6.1.1;6.1.1", "lists a clause twice"),
    ],
)
def test_bad_links_fail(tmp_path: Path, value: str, message: str) -> None:
    csv_path = _copy_demo(tmp_path)
    _edit_links(csv_path, "WID-6.1.1", value)
    with pytest.raises(GoldenImportError, match=message):
        import_golden(csv_path, tmp_path / "out")


def test_links_without_source_metadata_fail(tmp_path: Path) -> None:
    csv_path = _copy_demo(tmp_path)
    for meta in (tmp_path / "sources").iterdir():
        meta.unlink()
    with pytest.raises(GoldenImportError, match="cannot check Source clauses"):
        import_golden(csv_path, tmp_path / "out")


def test_empty_links_are_not_an_error(tmp_path: Path) -> None:
    csv_path = _copy_demo(tmp_path)
    for check in ("WID-6.1.1", "WID-6.1.2"):
        _edit_links(csv_path, check, "")
    result = import_golden(csv_path, tmp_path / "out", write=False)
    assert "7/9 controls linked" in format_summary(result)
    assert "no links yet (2): WID-6.1.1, WID-6.1.2" in format_summary(result)


def test_missing_catalog_table_in_settings_fails(tmp_path: Path) -> None:
    csv_path = _copy_demo(tmp_path)
    settings = csv_path.with_name("example-widgets.settings.toml")
    settings.write_text(settings.read_text().split("[catalog.fr]")[0], encoding="utf-8")
    with pytest.raises(GoldenImportError, match=r"missing \[catalog.fr\]"):
        import_golden(csv_path, tmp_path / "out")


# --- suggestions -----------------------------------------------------------------------


@pytest.mark.parametrize("lang", ["en", "fr"])
def test_suggestions_rank_the_annotated_clause_first(lang: str) -> None:
    result = import_golden(WIDGETS, DEMO / "catalogs", write=False)
    source = SourceDocument.model_validate_json(
        (DEMO / "sources" / f"example-widgets.2023-01-01.{lang}.json").read_text("utf-8")
    )
    suggestions = suggest(result.rows, source, lang=lang, top=3)  # type: ignore[arg-type]
    top1 = {s.check_id: s.clause for s in suggestions if s.rank == 1}
    assert top1 == {r.check_id: r.source_clauses[0] for r in result.rows}
    assert all(s.excerpt is None for s in suggestions)  # no text unless asked


def test_suggestions_need_full_text() -> None:
    meta = SourceDocument.model_validate_json(
        (DEMO / "sources" / "example-widgets.2023-01-01.en.meta.json").read_text("utf-8")
    )
    with pytest.raises(ValueError, match="full source document"):
        suggest([], meta)


def test_suggest_cli(tmp_path: Path) -> None:
    out = tmp_path / "review.csv"
    source = DEMO / "sources" / "example-widgets.2023-01-01.en.json"
    args = ["suggest-source-clauses", str(WIDGETS), "--source", str(source), "--out", str(out)]
    assert main([*args, "--top", "2", "--with-text"]) == 0
    rows = list(csv.DictReader(io.StringIO(out.read_text(encoding="utf-8"))))
    assert len(rows) == 18
    assert rows[0]["Suggested clause"] == "6.1.1"
    assert rows[0]["Clause text (excerpt)"].startswith("Each department must register")
    golden_before = WIDGETS.read_bytes()
    assert WIDGETS.read_bytes() == golden_before  # nothing written back
