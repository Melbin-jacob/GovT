from __future__ import annotations

import json
import shutil
from pathlib import Path

import jsonschema
import pytest

from rulebook.cli import main
from rulebook.sources.importer import (
    SourceImportError,
    import_source_file,
    load_registry,
    parse_source_file,
)
from rulebook.sources.model import SourceDocument, json_schema

REPO = Path(__file__).resolve().parents[3]
DEMO = REPO / "data" / "demo" / "sources"
RAW = REPO / "data" / "sources" / "raw"
REGISTRY = REPO / "data" / "sources" / "instruments.toml"
SCHEMA = REPO / "schemas" / "govhub" / "source-document-1.schema.json"
DEMO_FILES = sorted(p for p in DEMO.iterdir() if p.suffix in {".txt", ".html"})
REAL_FILES = [
    "dadm.2023-04-24.en.html",
    "dadm.2023-04-24.fr.html",
    "dadm.2025-06-24.en.html",
    "dadm.2025-06-24.fr.html",
]


def test_committed_schema_matches_model() -> None:
    assert SCHEMA.read_text(encoding="utf-8") == json_schema(), "run `rulebook source-schema`"


@pytest.mark.parametrize("path", DEMO_FILES, ids=lambda p: p.name)
def test_demo_sources_import_and_committed_json_is_current(path: Path) -> None:
    doc, _ = import_source_file(path, registry_path=REGISTRY, write=False)
    assert doc.synthetic is True
    assert doc.warnings == []
    stem = path.name.rsplit(".", 1)[0]
    assert (DEMO / f"{stem}.json").read_text("utf-8") == doc.to_json()
    assert (DEMO / f"{stem}.meta.json").read_text("utf-8") == doc.metadata_only().to_json()
    schema = json.loads(SCHEMA.read_text("utf-8"))
    for variant in (doc, doc.metadata_only()):
        jsonschema.validate(json.loads(variant.to_json()), schema)


def test_metadata_only_has_numbers_and_hashes_but_no_text() -> None:
    doc = parse_source_file(DEMO_FILES[0], load_registry(REGISTRY))
    meta = json.loads(doc.metadata_only().to_json())
    assert meta["content"] == "metadata-only"
    for clause in meta["clauses"]:
        assert set(clause) == {"number", "section", "text_sha256", "match_sha256"}
    assert "Each department must" not in doc.metadata_only().to_json()


def test_typography_only_difference_has_same_match_hash() -> None:
    registry = load_registry(REGISTRY)
    old = parse_source_file(DEMO / "example-widgets.2023-01-01.fr.txt", registry)
    new = parse_source_file(DEMO / "example-widgets.2025-01-01.fr.html", registry)
    old_c, new_c = old.clause("6.2.3"), new.clause("6.3.3")  # ' vs ’ only
    assert old_c is not None and new_c is not None
    assert old_c.text != new_c.text
    assert old_c.match_sha256 == new_c.match_sha256


def test_full_and_meta_written_to_expected_places(tmp_path: Path) -> None:
    raw = tmp_path / "data" / "sources" / "raw"
    raw.mkdir(parents=True)
    src = raw / "example-widgets.2023-01-01.en.txt"
    shutil.copy(DEMO / src.name, src)
    import_source_file(src, registry_path=REGISTRY)
    assert (raw / "example-widgets.2023-01-01.en.json").is_file()  # full: stays in raw/
    assert (tmp_path / "data" / "sources" / "example-widgets.2023-01-01.en.meta.json").is_file()


@pytest.mark.parametrize(
    ("name", "content", "message"),
    [
        ("widgets.txt", "6.1.1 x", "expected <instrument>"),
        ("unknown.2025-01-01.en.txt", "6.1.1 x", "not in the registry"),
        ("example-widgets.2025-01-01.en.txt", "no numbers here", "no numbered clauses"),
        ("example-widgets.2025-01-01.en.txt", "6.1.1 a\n\n6.1.1 b", "duplicate clause numbers"),
    ],
)
def test_import_errors(tmp_path: Path, name: str, content: str, message: str) -> None:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SourceImportError, match=message):
        parse_source_file(path, load_registry(REGISTRY))


def test_metadata_only_document_rejects_text() -> None:
    doc = parse_source_file(DEMO_FILES[0], load_registry(REGISTRY))
    data = json.loads(doc.to_json())
    data["content"] = "metadata-only"
    with pytest.raises(ValueError, match="must not contain clause text"):
        SourceDocument.model_validate(data)


def test_cli_check_mode(capsys: pytest.CaptureFixture[str]) -> None:
    files = [str(p) for p in DEMO_FILES]
    assert main(["import-source", "--registry", str(REGISTRY), "--check", *files]) == 0
    assert main(["import-source", "--registry", str(REGISTRY), "--stdout", files[0]]) == 0
    assert '"content": "full"' in capsys.readouterr().out


@pytest.mark.parametrize("name", REAL_FILES)
def test_real_directive_text(name: str) -> None:
    """Runs only where the deploying organization has supplied the official text."""
    path = RAW / name
    if not path.is_file():
        pytest.skip(
            f"{path.relative_to(REPO)} not present: official text is not committed "
            "(see docs/decisions.md); place the saved page there to run this test locally"
        )
    doc = parse_source_file(path, load_registry(REGISTRY))
    assert doc.synthetic is False
    assert len(doc.clauses) > 20
    assert any(c.section == "6.1" for c in doc.clauses)
    print(f"{name}: {len(doc.clauses)} clauses, warnings: {doc.warnings}")


def test_no_official_text_is_tracked_in_git() -> None:
    """Only the registry and metadata-only JSON may be committed under data/sources/."""
    import subprocess

    tracked = subprocess.run(
        ["git", "ls-files", "data/sources"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    offenders = [
        f for f in tracked if f != "data/sources/instruments.toml" and not f.endswith(".meta.json")
    ]
    assert offenders == [], f"official text must not be committed: {offenders}"
    for meta in (REPO / "data" / "sources").glob("*.meta.json"):
        assert json.loads(meta.read_text("utf-8"))["content"] == "metadata-only"
