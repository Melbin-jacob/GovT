"""SQLAlchemy models for the review desk."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

VERDICTS = ("met", "partially-met", "not-met", "not-applicable", "unable-to-determine")
STATES = (
    "open",
    "awaiting-evidence",
    "accepted",
    "accepted-with-remediation",
    "rejected",
    "overridden",
)


class Base(DeclarativeBase):
    pass


class Finding(Base):
    """One system x control to review. Until the assessment engine exists, every finding
    starts as a placeholder: verdict unable-to-determine, no confidence."""

    __tablename__ = "findings"
    __table_args__ = (
        UniqueConstraint("report_id", "system_id", "control_id", name="uq_findings_report"),
        CheckConstraint(f"verdict IN {VERDICTS}", name="ck_findings_verdict"),
        CheckConstraint(f"state IN {STATES}", name="ck_findings_state"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    report_id: Mapped[str] = mapped_column(String(64), index=True)
    task_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    servicenow_task: Mapped[str | None] = mapped_column(String(40), nullable=True)
    system_id: Mapped[str] = mapped_column(String(100), index=True)
    system_name: Mapped[str] = mapped_column(String(300))
    tenant: Mapped[str] = mapped_column(String(100), index=True)
    owner_email: Mapped[str | None] = mapped_column(String(300), nullable=True)
    impact_level: Mapped[str] = mapped_column(String(10))
    catalog: Mapped[str] = mapped_column(String(200))
    catalog_version: Mapped[str] = mapped_column(String(50))
    control_id: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_requested: Mapped[str | None] = mapped_column(Text, nullable=True)
    reasons: Mapped[list[str]] = mapped_column(JSONB)
    obligation_change: Mapped[bool] = mapped_column(Boolean)
    verdict: Mapped[str] = mapped_column(String(30))
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text)
    placeholder: Mapped[bool] = mapped_column(Boolean)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    state: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ReviewSession(Base):
    """A reviewer opened a finding. Decision time - opened_at = time spent (server clock,
    so a reviewer cannot report their own timing)."""

    __tablename__ = "review_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    finding_id: Mapped[str] = mapped_column(ForeignKey("findings.id"), index=True)
    reviewer: Mapped[str] = mapped_column(String(200))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
