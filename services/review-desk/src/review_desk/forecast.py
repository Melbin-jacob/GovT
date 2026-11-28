"""Reviewer-hours forecast.

hours = findings x minutes per finding / 60. The rate is the median ``review-seconds`` of
timed decisions in the log once there are at least ``min_samples`` of them; before that, a
PLACEHOLDER rate from ``data/config/review-rate.toml``, labelled as such in every result.
Each tenant's hours are compared with its weekly capacity (also a PLACEHOLDER until the
department sets it). Staged rollout when capacity is exceeded is not built yet
(TODO(review-desk)); the forecast flags it.
"""

from __future__ import annotations

import math
import statistics
import tomllib
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from govhub_shared import tenancy
from review_desk.models import DecisionRecord, Finding
from review_desk.queue import OPEN_STATES


@dataclass(frozen=True)
class RateConfig:
    minutes_per_finding: float
    status: str
    min_samples: int
    capacity_default: float
    capacity_status: str
    capacity_tenants: dict[str, float]


def load_rate_config(path: Path) -> RateConfig:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    rate, capacity = data["rate"], data.get("capacity", {})
    default = capacity.get("default", {})
    return RateConfig(
        minutes_per_finding=float(rate["minutes_per_finding"]),
        status=str(rate.get("status", "UNSPECIFIED")),
        min_samples=int(rate.get("min_samples", 20)),
        capacity_default=float(default.get("hours_per_week", 0)),
        capacity_status=str(default.get("status", "UNSPECIFIED")),
        capacity_tenants={
            t: float(v["hours_per_week"]) for t, v in capacity.get("tenants", {}).items()
        },
    )


def measured_seconds(session: Session) -> list[float]:
    """Timed review durations from every tenant's decisions: the rate is a platform
    statistic, so this reads across tenants (row-level security), the durations only."""
    seconds = DecisionRecord.record_text.cast(JSONB)["review-seconds"]
    with tenancy.widened(session, tenancy.ALL_TENANTS):
        rows = session.scalars(select(seconds).order_by(DecisionRecord.seq)).all()
    return [float(v) for v in rows if isinstance(v, int | float) and not isinstance(v, bool)]


def current_rate(session: Session, config: RateConfig) -> dict[str, Any]:
    samples = measured_seconds(session)
    if len(samples) >= config.min_samples:
        minutes = statistics.median(samples) / 60
        return {
            "minutes_per_finding": round(minutes, 2),
            "source": f"measured: median of {len(samples)} timed decisions",
            "samples": len(samples),
            "min_samples": config.min_samples,
        }
    return {
        "minutes_per_finding": config.minutes_per_finding,
        "source": (
            f"{config.status}: {config.minutes_per_finding:g} min per finding from config "
            f"({len(samples)} of {config.min_samples} timed decisions so far)"
        ),
        "samples": len(samples),
        "min_samples": config.min_samples,
    }


def forecast(
    session: Session,
    config: RateConfig,
    findings_by_tenant: Counter[str],
    findings_by_level: Counter[str],
    *,
    basis: str,
) -> dict[str, Any]:
    rate = current_rate(session, config)
    minutes = float(rate["minutes_per_finding"])
    tenants = []
    for tenant, count in sorted(findings_by_tenant.items()):
        hours = round(count * minutes / 60, 1)
        capacity = config.capacity_tenants.get(tenant, config.capacity_default)
        tenants.append(
            {
                "tenant": tenant,
                "findings": count,
                "reviewer_hours": hours,
                "capacity_hours_per_week": capacity,
                "capacity_source": (
                    "tenant setting"
                    if tenant in config.capacity_tenants
                    else config.capacity_status
                ),
                "weeks_needed": math.ceil(hours / capacity) if capacity else None,
                "exceeds_weekly_capacity": bool(capacity) and hours > capacity,
            }
        )
    total = sum(findings_by_tenant.values())
    return {
        "basis": basis,
        "findings": total,
        "reviewer_hours": round(total * minutes / 60, 1),
        "rate": rate,
        "by_impact_level": dict(findings_by_level),
        "by_tenant": tenants,
        "staged_rollout": (
            "needed: at least one tenant exceeds its weekly capacity (staged rollout planning "
            "is not built yet, TODO(review-desk))"
            if any(t["exceeds_weekly_capacity"] for t in tenants)
            else "not needed"
        ),
    }


def from_report(
    session: Session, config: RateConfig, report: dict[str, Any],
    tenants: frozenset[str] | None = None,
) -> dict[str, Any]:  # fmt: skip
    by_tenant: Counter[str] = Counter()
    by_level: Counter[str] = Counter()
    for system in report.get("systems", []):
        if tenants is not None and system["tenant"] not in tenants:
            continue
        by_tenant[system["tenant"]] += int(system["findings_to_review"])
        by_level[system["impact_level"]] += int(system["findings_to_review"])
    return forecast(
        session, config, by_tenant, by_level, basis=f"impact report {report.get('report_id')}"
    )


def from_queue(
    session: Session, config: RateConfig, tenants: frozenset[str] | None = None
) -> dict[str, Any]:
    by_tenant: Counter[str] = Counter()
    by_level: Counter[str] = Counter()
    for finding in session.scalars(select(Finding).where(Finding.state.in_(OPEN_STATES))):
        if tenants is not None and finding.tenant not in tenants:
            continue
        by_tenant[finding.tenant] += 1
        by_level[finding.impact_level] += 1
    return forecast(session, config, by_tenant, by_level, basis="open review queue")
