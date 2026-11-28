"""ORM models of the assessment engine."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class EvidenceDocument(Base):
    """An uploaded evidence file for one system. The bytes live on the evidence volume."""

    __tablename__ = "evidence_documents"
    __table_args__ = (UniqueConstraint("system_id", "sha256", name="uq_evidence_system_sha"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    system_id: Mapped[str] = mapped_column(String(64), index=True)
    # The system's tenant (row-level security); set on every insert.
    tenant: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(128))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    stored_path: Mapped[str] = mapped_column(String(255))
    encrypted: Mapped[bool]
    language: Mapped[str] = mapped_column(String(8))
    extraction_status: Mapped[str] = mapped_column(String(16))
    extraction_detail: Mapped[str] = mapped_column(String(255), default="")
    uploaded_by: Mapped[str] = mapped_column(String(128))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Passage(Base):
    """A retrievable piece of an evidence document's text."""

    __tablename__ = "evidence_passages"

    id: Mapped[str] = mapped_column(String(48), primary_key=True)  # "<doc id>:<seq>"
    document_id: Mapped[str] = mapped_column(
        ForeignKey("evidence_documents.id", ondelete="CASCADE"), index=True
    )
    system_id: Mapped[str] = mapped_column(String(64), index=True)
    # The system's tenant (row-level security); set on every insert.
    tenant: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8))
    injection_flags: Mapped[list[Any]] = mapped_column(JSONB, default=list)


class SystemFact(Base):
    """A structured fact about a system, used by rule-based checks (latest value wins)."""

    __tablename__ = "system_facts"

    system_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # The system's tenant (row-level security); set on every insert.
    tenant: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(255), default="")
    recorded_by: Mapped[str] = mapped_column(String(128))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Assessment(Base):
    """One assessment of one (system, control). Immutable: the database refuses UPDATE and
    DELETE. Records what the model said even when the engine downgraded it."""

    __tablename__ = "assessments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), index=True)
    finding_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    system_id: Mapped[str] = mapped_column(String(64), index=True)
    # The system's tenant (row-level security); set on every insert.
    tenant: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    catalog: Mapped[str] = mapped_column(String(128))
    catalog_version: Mapped[str] = mapped_column(String(32))
    control_id: Mapped[str] = mapped_column(String(64))
    method: Mapped[str] = mapped_column(String(8))  # rule | model
    lang: Mapped[str] = mapped_column(String(8))
    verdict: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB)  # full outcome (no evidence text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssessmentResultsDocument(Base):
    """OSCAL 1.1.3 assessment-results for one run, schema-validated. Immutable."""

    __tablename__ = "assessment_results_documents"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    system_id: Mapped[str] = mapped_column(String(64), index=True)
    # The system's tenant (row-level security); set on every insert.
    tenant: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
