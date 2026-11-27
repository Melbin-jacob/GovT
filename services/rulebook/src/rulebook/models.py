"""SQLAlchemy models. Stored catalog versions are immutable (enforced by a DB trigger)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Catalog(Base):
    """A named catalog (e.g. ``dadm-section6``); its versions exist per language."""

    __tablename__ = "catalogs"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    versions: Mapped[list[CatalogVersion]] = relationship(back_populates="catalog")


class CatalogVersion(Base):
    """One immutable OSCAL catalog document: (catalog, semantic version, language)."""

    __tablename__ = "catalog_versions"
    __table_args__ = (
        UniqueConstraint("catalog_id", "version", "lang", name="uq_catalog_version_lang"),
        CheckConstraint("lang IN ('en', 'fr')", name="ck_catalog_versions_lang"),
        Index("ix_catalog_versions_order", "catalog_id", "lang", "major", "minor", "patch"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    catalog_id: Mapped[int] = mapped_column(ForeignKey("catalogs.id", ondelete="CASCADE"))
    version: Mapped[str] = mapped_column(String(50))
    major: Mapped[int] = mapped_column(Integer)
    minor: Mapped[int] = mapped_column(Integer)
    patch: Mapped[int] = mapped_column(Integer)
    lang: Mapped[str] = mapped_column(String(2))
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    doc_uuid: Mapped[str] = mapped_column(String(36))
    created_by: Mapped[str] = mapped_column(String(200))
    derived_from: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    catalog: Mapped[Catalog] = relationship(back_populates="versions")
    controls: Mapped[list[CatalogControl]] = relationship(
        back_populates="version", order_by="CatalogControl.position"
    )


class CatalogControl(Base):
    """Denormalized index of the controls in each stored version (for lookups)."""

    __tablename__ = "catalog_controls"
    __table_args__ = (
        UniqueConstraint("version_id", "control_id", name="uq_catalog_controls_version_control"),
        CheckConstraint("status IN ('active', 'withdrawn')", name="ck_catalog_controls_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("catalog_versions.id", ondelete="CASCADE"))
    control_id: Mapped[str] = mapped_column(String(200), index=True)
    group_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    position: Mapped[int] = mapped_column(Integer)

    version: Mapped[CatalogVersion] = relationship(back_populates="controls")


class SourceVersion(Base):
    """One immutable source document (instrument, effective date, language) with its text."""

    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint("instrument", "effective_date", "lang", name="uq_source_version_lang"),
        CheckConstraint("lang IN ('en', 'fr')", name="ck_source_versions_lang"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument: Mapped[str] = mapped_column(String(100))
    effective_date: Mapped[date] = mapped_column(Date)
    lang: Mapped[str] = mapped_column(String(2))
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    file_sha256: Mapped[str] = mapped_column(String(64))
    synthetic: Mapped[bool] = mapped_column(Boolean)
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class StoredProfile(Base):
    """A named OSCAL profile (configuration: replaceable, unlike catalog versions)."""

    __tablename__ = "profiles"

    name: Mapped[str] = mapped_column(String(200), primary_key=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(String(64))
    updated_by: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class InventorySnapshot(Base):
    """One imported inventory. The newest snapshot is the current inventory."""

    __tablename__ = "inventory_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(200))
    imported_by: Mapped[str] = mapped_column(String(200))
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    systems: Mapped[list[AISystem]] = relationship(
        back_populates="snapshot", order_by="AISystem.system_id"
    )


class AISystem(Base):
    __tablename__ = "ai_systems"
    __table_args__ = (
        UniqueConstraint("snapshot_id", "system_id", name="uq_ai_systems_snapshot_system"),
        CheckConstraint("impact_level BETWEEN 1 AND 4", name="ck_ai_systems_impact_level"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_snapshots.id", ondelete="CASCADE")
    )
    system_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(300))
    tenant: Mapped[str] = mapped_column(String(100), index=True)
    department: Mapped[str] = mapped_column(String(300))
    owner: Mapped[str] = mapped_column(String(300))
    owner_email: Mapped[str | None] = mapped_column(String(300), nullable=True)
    impact_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lifecycle: Mapped[str] = mapped_column(String(20))
    profiles: Mapped[list[str]] = mapped_column(ARRAY(String(200)))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_gaps: Mapped[list[str]] = mapped_column(ARRAY(String(100)), default=list)

    snapshot: Mapped[InventorySnapshot] = relationship(back_populates="systems")


class DraftBatch(Base):
    """Drafted control changes for one source change, waiting for human approval."""

    __tablename__ = "draft_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    catalog: Mapped[str] = mapped_column(String(200))
    base_version: Mapped[str] = mapped_column(String(50))
    instrument: Mapped[str] = mapped_column(String(200))
    from_version: Mapped[str] = mapped_column(String(50))
    to_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20))  # open | published
    new_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    plan: Mapped[dict[str, Any]] = mapped_column(JSONB)  # groups, clause texts, ID prefix
    created_by: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DraftItem(Base):
    """One proposed change: edit, new control, retirement or clause-reference update.
    ``drafts`` holds the EN and FR drafts (from the model or a person)."""

    __tablename__ = "draft_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("draft_batches.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20))  # edit | new | retire | reference
    old_clauses: Mapped[list[Any]] = mapped_column(JSONB)
    new_clauses: Mapped[list[Any]] = mapped_column(JSONB)
    target_control: Mapped[str | None] = mapped_column(String(200), nullable=True)
    proposed_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    group_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    flags: Mapped[list[Any]] = mapped_column(JSONB)  # e.g. obligation-change, split
    drafts: Mapped[dict[str, Any]] = mapped_column(JSONB)  # {"en": {...}, "fr": {...}}
    status: Mapped[str] = mapped_column(String(20))  # pending | ready | approved | rejected
    last_edited_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ApprovalRecord(Base):
    """Append-only, hash-chained log of every drafting and approval action."""

    __tablename__ = "approval_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    batch_id: Mapped[str] = mapped_column(String(36), index=True)
    item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    record_text: Mapped[str] = mapped_column(Text)
    previous_hash: Mapped[str] = mapped_column(String(71))
    record_hash: Mapped[str] = mapped_column(String(71))
