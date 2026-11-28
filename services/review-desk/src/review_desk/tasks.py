"""ServiceNow tasks from review decisions, sent through connector-hub (internal call).

review-desk never calls ServiceNow itself (network rule: only connector-hub calls out).
If connector-hub is not configured or fails, the decision is still recorded, and the log
record says the task was not sent and why.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from govhub_shared.auth.client import ServiceAuth, signing_key


class TaskSink(Protocol):
    def upsert(self, task: dict[str, Any]) -> dict[str, Any]: ...

    def note(self, correlation_id: str, text: str) -> dict[str, Any]: ...

    def task_notes(self) -> list[tuple[str, str]] | None:
        """(task number, work notes) of the hub's reassessment tasks; None if unavailable."""
        ...


class NullTaskSink:
    reason = "not sent: connector-hub not configured (CONNECTOR_HUB_URL)"

    def upsert(self, task: dict[str, Any]) -> dict[str, Any]:
        return {"status": self.reason}

    def note(self, correlation_id: str, text: str) -> dict[str, Any]:
        return {"status": self.reason}

    def task_notes(self) -> list[tuple[str, str]] | None:
        return None


class HttpTaskSink:
    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        # review-desk's service token for connector-hub (tasks and checkpoints of any tenant).
        self.http = http or httpx.Client(
            base_url=base_url, timeout=30.0,
            auth=ServiceAuth(signing_key("review-desk"), "connector-hub", all_tenants=True),
        )  # fmt: skip

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self.http.post(path, json=body)
        except httpx.HTTPError as exc:
            return {"status": f"not sent: connector-hub unreachable ({exc.__class__.__name__})"}
        if response.status_code >= 400:
            detail = response.json().get("detail", response.text) if response.content else ""
            return {"status": f"not sent: connector-hub {response.status_code}: {detail}"}
        data: dict[str, Any] = response.json()
        return {"status": "sent", **data}

    def upsert(self, task: dict[str, Any]) -> dict[str, Any]:
        return self._post("/tasks", task)

    def note(self, correlation_id: str, text: str) -> dict[str, Any]:
        return self._post(f"/tasks/{correlation_id}/notes", {"text": text})

    def task_notes(self) -> list[tuple[str, str]] | None:
        try:
            response = self.http.get("/tasks/notes", params={"type": "reassessment"})
        except httpx.HTTPError:
            return None
        if response.status_code >= 400:
            return None
        return [(t["number"], t["work_notes"]) for t in response.json()]
