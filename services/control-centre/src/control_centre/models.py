"""control-centre's own database: tenants and, later, their data settings and grants.

Tenants live here (not in a sixth service) so the architecture keeps the proposal's five
services (project owner's answer 5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Final

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# PLACEHOLDER residency labels (project owner's answer 8), language-neutral codes.
RESIDENCY_LABELS: Final = ("ca-only", "ca-protected-b", "unrestricted-synthetic")


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "residency IN ('ca-only', 'ca-protected-b', 'unrestricted-synthetic')",
            name="tenants_residency_label",
        ),
        CheckConstraint(
            "residency <> 'unrestricted-synthetic' OR synthetic", name="tenants_synthetic_label"
        ),
    )

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name_en: Mapped[str] = mapped_column(String(300))
    name_fr: Mapped[str] = mapped_column(String(300))
    # Synthetic (fictional) data only: required of every tenant in demo mode.
    synthetic: Mapped[bool] = mapped_column(Boolean)
    residency: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[str] = mapped_column(String(200))
