"""Evidence intake and retrieval. Never logs passage text or file contents."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from assessment_engine import passages as psg
from assessment_engine.config import Settings
from assessment_engine.extract import extract
from assessment_engine.models import EvidenceDocument, Passage
from assessment_engine.storage import EvidenceStore, parse_key

log = logging.getLogger("govhub.assessment.evidence")


def store_for(settings: Settings) -> EvidenceStore:
    return EvidenceStore(Path(settings.evidence_dir), parse_key(settings.evidence_key))


def document_view(doc: EvidenceDocument, passages: list[Passage] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": doc.id,
        "system_id": doc.system_id,
        "filename": doc.filename,
        "media_type": doc.media_type,
        "sha256": doc.sha256,
        "size": doc.size,
        "encrypted": doc.encrypted,
        "language": doc.language,
        "extraction_status": doc.extraction_status,
        "extraction_detail": doc.extraction_detail,
        "uploaded_by": doc.uploaded_by,
        "uploaded_at": doc.uploaded_at.isoformat(),
    }
    if passages is not None:
        out["passages"] = len(passages)
        out["flagged_passages"] = [p.id for p in passages if p.injection_flags]
    return out


def passage_view(p: Passage) -> dict[str, Any]:
    return {
        "id": p.id,
        "document_id": p.document_id,
        "seq": p.seq,
        "language": p.language,
        "text": p.text,
        "injection_flags": list(p.injection_flags),
    }


def ingest(
    session: Session,
    store: EvidenceStore,
    *,
    system_id: str,
    filename: str,
    data: bytes,
    uploaded_by: str,
) -> tuple[EvidenceDocument, list[Passage], bool]:
    """Store and index one file. Returns (document, passages, created)."""
    extracted = extract(filename, data)
    digest, relative = store.put(data)
    existing = session.scalar(
        select(EvidenceDocument).where(
            EvidenceDocument.system_id == system_id, EvidenceDocument.sha256 == digest
        )
    )
    if existing is not None:
        return existing, passages_of(session, existing.id), False
    doc_id = str(uuid.uuid4())
    chunks = psg.chunk(extracted.paragraphs)
    language = psg.guess_language(" ".join(extracted.paragraphs)) if chunks else "unknown"
    doc = EvidenceDocument(
        id=doc_id,
        system_id=system_id,
        filename=Path(filename).name[:255],
        media_type=extracted.media_type,
        sha256=digest,
        size=len(data),
        stored_path=relative,
        encrypted=store.encrypted,
        language=language,
        extraction_status=extracted.status,
        extraction_detail=extracted.detail[:255],
        uploaded_by=uploaded_by[:128],
        uploaded_at=datetime.now(UTC),
    )
    session.add(doc)
    rows = [
        Passage(
            id=f"{doc_id}:{i}",
            document_id=doc_id,
            system_id=system_id,
            seq=i,
            text=text,
            language=psg.guess_language(text) if language == "unknown" else language,
            injection_flags=psg.injection_flags(text),
        )
        for i, text in enumerate(chunks, start=1)
    ]
    session.add_all(rows)
    session.flush()
    log.info(  # counts only, never text
        "evidence stored system=%s doc=%s status=%s passages=%d flagged=%d encrypted=%s",
        system_id,
        doc_id,
        extracted.status,
        len(rows),
        sum(1 for r in rows if r.injection_flags),
        store.encrypted,
    )
    return doc, rows, True


def passages_of(session: Session, document_id: str) -> list[Passage]:
    return list(
        session.scalars(
            select(Passage).where(Passage.document_id == document_id).order_by(Passage.seq)
        )
    )


@dataclass
class Retrieved:
    passage: Passage
    score: float


def retrieve(session: Session, system_id: str, query: str, k: int = 5) -> list[Retrieved]:
    """The k passages of the system's evidence that best match the query (score > 0)."""
    rows = list(
        session.scalars(
            select(Passage)
            .where(Passage.system_id == system_id)
            .order_by(Passage.document_id, Passage.seq)
        )
    )
    ranked = psg.bm25(query, [r.text for r in rows])
    scores = {s.index: s.score for s in ranked}
    hits = [s.index for s in ranked[:k] if s.score > 0]
    keys = [(r.document_id, r.seq) for r in rows]
    return [Retrieved(rows[i], scores[i]) for i in psg.with_neighbours(hits, keys, k)]
