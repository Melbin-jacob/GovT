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
from sqlalchemy.dialects.postgresql import JSONB
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
