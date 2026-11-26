"""Import a local copy of a policy instrument into a source document.

File names follow ``<instrument>.<effective-date>.<en|fr>.<html|txt>`` and the instrument
must be registered in ``data/sources/instruments.toml``. The full document (with text) is
written next to the input; the metadata-only document is written to ``data/sources/``
when the input is in ``data/sources/raw/``, otherwise next to the input.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

from rulebook.sources.model import Clause, SourceDocument, SourceFile
from rulebook.sources.normalize import normalize_for_match, sha256_text
from rulebook.sources.parse import parse_file_text

FILE_NAME_RE = re.compile(
    r"^(?P<instrument>[a-z0-9][a-z0-9-]*)\.(?P<date>\d{4}-\d{2}-\d{2})\.(?P<lang>en|fr)\."
    r"(?P<kind>html|htm|txt)$"
)
DEFAULT_REGISTRY = Path("data/sources/instruments.toml")


class SourceImportError(ValueError):
    pass


@dataclass(frozen=True)
class Instrument:
    key: str
    title: dict[str, str]
    url: dict[str, str]
    synthetic: bool


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Instrument]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return {
        key: Instrument(
            key=key,
            title={"en": entry["title_en"], "fr": entry["title_fr"]},
            url={"en": entry["url_en"], "fr": entry["url_fr"]},
            synthetic=bool(entry.get("synthetic", False)),
        )
        for key, entry in data.items()
    }


def _decode(raw: bytes, name: str) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        # Pages saved by some browsers on Windows; never guess silently for text files.
        if name.endswith(".txt"):
            raise SourceImportError(f"{name}: text files must be UTF-8") from None
        return raw.decode("cp1252")


def parse_source_file(
    path: Path, registry: dict[str, Instrument], *, retrieved: date | None = None
) -> SourceDocument:
    match = FILE_NAME_RE.match(path.name)
    if not match:
        raise SourceImportError(
            f"{path.name}: expected <instrument>.<YYYY-MM-DD>.<en|fr>.<html|txt>"
        )
    instrument = registry.get(match["instrument"])
    if instrument is None:
        raise SourceImportError(
            f"{path.name}: instrument {match['instrument']!r} is not in the registry"
        )
    lang = cast(Literal["en", "fr"], match["lang"])
    raw = path.read_bytes()
    kind: Literal["html", "txt"] = "txt" if match["kind"] == "txt" else "html"
    parsed = parse_file_text(_decode(raw, path.name), kind)
    if not parsed.clauses:
        raise SourceImportError(f"{path.name}: no numbered clauses found")
    numbers = [c.number for c in parsed.clauses]
    dupes = sorted({n for n in numbers if numbers.count(n) > 1})
    if dupes:
        raise SourceImportError(f"{path.name}: duplicate clause numbers {dupes}")
    return SourceDocument(
        content="full",
        instrument=instrument.key,
        title=instrument.title[lang],
        effective_date=date.fromisoformat(match["date"]),
        lang=lang,
        source_url=instrument.url[lang],
        retrieved=retrieved,
        synthetic=instrument.synthetic,
        file=SourceFile(name=path.name, sha256=hashlib.sha256(raw).hexdigest()),
        clauses=[
            Clause(
                number=c.number,
                section=".".join(c.number.split(".")[:2]),
                heading=c.heading,
                text=c.text,
                text_sha256=sha256_text(c.text),
                match_sha256=sha256_text(normalize_for_match(c.text)),
            )
            for c in parsed.clauses
        ],
        warnings=parsed.warnings,
    )


def default_outputs(path: Path) -> tuple[Path, Path]:
    stem = path.name.rsplit(".", 1)[0]
    meta_dir = path.parent.parent if path.parent.name == "raw" else path.parent
    return path.with_name(f"{stem}.json"), meta_dir / f"{stem}.meta.json"


def import_source_file(
    path: Path,
    *,
    registry_path: Path = DEFAULT_REGISTRY,
    full_out: Path | None = None,
    meta_out: Path | None = None,
    retrieved: date | None = None,
    write: bool = True,
) -> tuple[SourceDocument, dict[str, Any]]:
    """Parse, then write the full and metadata-only JSON. Returns the doc and a summary."""
    doc = parse_source_file(path, load_registry(registry_path), retrieved=retrieved)
    default_full, default_meta = default_outputs(path)
    full_path, meta_path = full_out or default_full, meta_out or default_meta
    if write:
        full_path.write_text(doc.to_json(), encoding="utf-8")
        meta_path.write_text(doc.metadata_only().to_json(), encoding="utf-8")
    summary = {
        "file": path.name,
        "instrument": doc.instrument,
        "version": doc.version,
        "lang": doc.lang,
        "synthetic": doc.synthetic,
        "clauses": len(doc.clauses),
        "sections": sorted({c.section for c in doc.clauses}),
        "warnings": doc.warnings,
        "full": str(full_path),
        "metadata": str(meta_path),
    }
    return doc, summary
