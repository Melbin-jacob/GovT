"""Internal client for review-desk: open findings in, assessment drafts out."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from assessment_engine.models import Assessment
from govhub_shared.auth.client import ServiceAuth, signing_key

OPEN_STATES = ("open", "awaiting-evidence")


class ReviewDesk(Protocol):
    def open_findings(self, system_id: str) -> list[dict[str, Any]]: ...

    def push(self, finding_id: str, draft: dict[str, Any]) -> str: ...


class HttpReviewDesk:
    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        # The engine's service token for review-desk; all tenants (it assesses whichever
        # system a reviewer asked for, and posts drafts the reviewer then decides on).
        self.http = http or httpx.Client(
            base_url=base_url, timeout=30.0,
            auth=ServiceAuth(signing_key("assessment-engine"), "review-desk", all_tenants=True),
        )  # fmt: skip

    def open_findings(self, system_id: str) -> list[dict[str, Any]]:
        resp = self.http.get("/queue", params={"limit": 1000})
        resp.raise_for_status()
        return [
            f
            for f in resp.json()["findings"]
            if f["system_id"] == system_id and f["state"] in OPEN_STATES
        ]

    def push(self, finding_id: str, draft: dict[str, Any]) -> str:
        try:
            resp = self.http.put(f"/findings/{finding_id}/assessment", json=draft)
        except httpx.HTTPError as exc:
            return f"not sent: {exc.__class__.__name__}"
        return "sent" if resp.status_code < 400 else f"not sent: HTTP {resp.status_code}"


def draft_of(row: Assessment) -> dict[str, Any]:
    """The review-desk payload for one stored assessment (no evidence text but the quote)."""
    d = row.detail
    return {
        "assessment_id": row.id,
        "run_id": row.run_id,
        "method": row.method,
        "verdict": row.verdict,
        "confidence": row.confidence,
        "rationale": d.get("rationale", {}),
        "model_id": d.get("model_id"),
        "prompt_version": d.get("prompt_version") or None,
        "model_verdict": d.get("model_verdict"),
        "downgrade_reason": d.get("downgrade_reason"),
        "cited_passage_id": d.get("cited_passage_id"),
        "cited_quote": d.get("cited_quote"),
        "evidence_language": row.lang if row.method == "model" else None,
        "flagged_passage_ids": d.get("flagged_passage_ids", []),
        "rule_status": d.get("rule_status"),
        "facts_used": d.get("facts_used", {}),
        "missing_facts": d.get("missing_facts", []),
    }
