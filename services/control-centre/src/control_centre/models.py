"""control-centre's own database: tenants and, later, their data settings and grants.

Tenants live here (not in a sixth service) so the architecture keeps the proposal's five
services (project owner's answer 5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from sqlalchemy import Boolean, CheckConstraint, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
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


class WebSession(Base):
    """A signed-in browser. The cookie holds a random token; only its hash is stored."""

    __tablename__ = "web_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    mode: Mapped[str] = mapped_column(String(10))  # oidc | demo
    principal: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OidcLogin(Base):
    """A sign-in in progress (state, nonce, PKCE verifier), used once, within 10 minutes."""

    __tablename__ = "oidc_logins"

    state: Mapped[str] = mapped_column(String(64), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(64))
    verifier: Mapped[str] = mapped_column(String(128))
    next_path: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
