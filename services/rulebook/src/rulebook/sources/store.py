"""Storage rules for source documents: immutable, full text required, EN/FR parity report."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import date
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from rulebook.models import SourceVersion
from rulebook.sources.model import SourceDocument
from rulebook.store import ConflictError, InvalidCatalogError, NotFoundError


def _content_hash(doc: SourceDocument) -> str:
    return hashlib.sha256(doc.to_json().encode("utf-8")).hexdigest()


def parse_document(payload: Mapping[str, Any]) -> SourceDocument:
    try:
        doc = SourceDocument.model_validate(payload)
    except ValidationError as exc:
        raise InvalidCatalogError(
            "not a valid source document",
            [f"{'/'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()],
        ) from exc
    return doc


def store_source(
    session: Session, payload: Mapping[str, Any], *, created_by: str = "anonymous"
) -> tuple[SourceDocument, bool, list[str]]:
    """Store a full source document. Returns (document, created, parity warnings)."""
    doc = parse_document(payload)
    if doc.content != "full":
        raise InvalidCatalogError(
            "only full documents (with clause text) can be stored; metadata-only documents "
            "are for the repository"
        )
    digest = _content_hash(doc)
    existing = session.scalar(
        select(SourceVersion).where(
            SourceVersion.instrument == doc.instrument,
            SourceVersion.effective_date == doc.effective_date,
            SourceVersion.lang == doc.lang,
        )
    )
    if existing is not None:
        if existing.content_hash == digest:
            return doc, False, parity_warnings(session, doc.instrument, doc.effective_date)
        raise ConflictError(
            f"{doc.instrument} {doc.version} ({doc.lang}) already exists with different "
            "content; source versions are immutable"
        )
    session.add(
        SourceVersion(
            instrument=doc.instrument,
            effective_date=doc.effective_date,
            lang=doc.lang,
            document=doc.model_dump(mode="json", exclude_none=True),
            content_hash=digest,
            file_sha256=doc.file.sha256,
            synthetic=doc.synthetic,
            created_by=created_by,
        )
    )
    session.flush()
    return doc, True, parity_warnings(session, doc.instrument, doc.effective_date)


def get_source(session: Session, instrument: str, version: str, lang: str) -> SourceDocument:
    try:
        effective = date.fromisoformat(version)
    except ValueError:
        raise InvalidCatalogError(f"version {version!r} is not a date (YYYY-MM-DD)") from None
    row = session.scalar(
        select(SourceVersion).where(
            SourceVersion.instrument == instrument,
            SourceVersion.effective_date == effective,
            SourceVersion.lang == lang,
        )
    )
    if row is None:
        raise NotFoundError(f"source {instrument} {version} ({lang}) not found")
    return SourceDocument.model_validate(row.document)


def parity_warnings(session: Session, instrument: str, effective: date) -> list[str]:
    """Clause numbers present in only one language for this version. Warnings, not errors:
    the official text is what it is."""
    rows = session.scalars(
        select(SourceVersion).where(
            SourceVersion.instrument == instrument, SourceVersion.effective_date == effective
        )
    ).all()
    by_lang = {r.lang: {c["number"] for c in r.document["clauses"]} for r in rows}
    if set(by_lang) != {"en", "fr"}:
        missing = sorted({"en", "fr"} - set(by_lang))
        return [f"{instrument} {effective.isoformat()}: no {'/'.join(missing)} version stored yet"]
    warnings = []
    only_en, only_fr = by_lang["en"] - by_lang["fr"], by_lang["fr"] - by_lang["en"]
    if only_en:
        warnings.append(f"clauses only in EN: {sorted(only_en, key=_key)}")
    if only_fr:
        warnings.append(f"clauses only in FR: {sorted(only_fr, key=_key)}")
    return warnings


def _key(number: str) -> tuple[int, ...]:
    return tuple(int(p) for p in number.split("."))


def list_sources(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(SourceVersion).order_by(
            SourceVersion.instrument, SourceVersion.effective_date, SourceVersion.lang
        )
    ).all()
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        inst = out.setdefault(
            row.instrument,
            {"instrument": row.instrument, "synthetic": row.synthetic, "versions": {}},
        )
        version = inst["versions"].setdefault(
            row.effective_date.isoformat(),
            {"version": row.effective_date.isoformat(), "langs": [], "clauses": {}},
        )
        version["langs"].append(row.lang)
        version["clauses"][row.lang] = len(row.document["clauses"])
    result = []
    for inst in out.values():
        versions = list(inst["versions"].values())
        for v in versions:
            v["parity_warnings"] = parity_warnings(
                session, inst["instrument"], date.fromisoformat(v["version"])
            )
        result.append({**inst, "versions": versions})
    return result
