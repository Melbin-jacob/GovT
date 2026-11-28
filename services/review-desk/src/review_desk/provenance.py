"""Conflict of interest: a reviewer cannot decide a finding of a system for which they
uploaded evidence or wrote facts (project owner's addition A, Milestone 7).

The assessment engine holds that provenance (``uploaded_by``, ``recorded_by``); review-desk
asks it with its own service token. If the engine is configured but cannot answer, the
decision is refused (fail closed); with no engine configured (tests, a review-only
deployment) there is no provenance to conflict with.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from govhub_shared.auth.client import ServiceAuth, signing_key


class ProvenanceUnavailableError(RuntimeError):
    pass


class ProvenanceSource(Protocol):
    def of(self, system_id: str) -> dict[str, Any]: ...


class NoProvenance:
    def of(self, system_id: str) -> dict[str, Any]:
        return {"system_id": system_id, "evidence_uploaders": [], "fact_writers": []}


class HttpProvenance:
    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(
            base_url=base_url, timeout=15.0,
            auth=ServiceAuth(signing_key("review-desk"), "assessment-engine", all_tenants=True),
        )  # fmt: skip

    def of(self, system_id: str) -> dict[str, Any]:
        try:
            resp = self.http.get(f"/systems/{system_id}/provenance")
        except httpx.HTTPError as exc:
            raise ProvenanceUnavailableError(exc.__class__.__name__) from exc
        if resp.status_code >= 400:
            raise ProvenanceUnavailableError(f"HTTP {resp.status_code}")
        data: dict[str, Any] = resp.json()
        return data


def conflicts(record: dict[str, Any], person: str) -> list[str]:
    """Reason codes: ``uploaded-evidence``, ``wrote-facts`` (empty: no conflict)."""
    reasons = []
    if person in record.get("evidence_uploaders", []):
        reasons.append("uploaded-evidence")
    if person in record.get("fact_writers", []):
        reasons.append("wrote-facts")
    return reasons
