"""Minimal ServiceNow Table API client (sync, httpx).

Reads use ``sysparm_display_value=all`` so every field arrives as
``{"value": ..., "display_value": ...}``: choice fields are mapped by label and reference
fields by name or sys_id, whichever the mapping needs. Writes send raw values.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from connector_hub.servicenow.config import ServiceNowConfig

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


class ServiceNowError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        super().__init__(f"ServiceNow error {status}: {message}")


class ServiceNowAuthError(ServiceNowError):
    pass


class ServiceNowUnavailableError(ServiceNowError):
    pass


def value(record: Mapping[str, Any], field: str) -> str:
    raw = record.get(field, "")
    return str(raw.get("value", "")) if isinstance(raw, dict) else str(raw or "")


def display(record: Mapping[str, Any], field: str) -> str:
    raw = record.get(field, "")
    return str(raw.get("display_value", "")) if isinstance(raw, dict) else str(raw or "")


class ServiceNowClient:
    def __init__(
        self,
        config: ServiceNowConfig,
        *,
        http: httpx.Client | None = None,
        retries: int = 3,
        backoff_seconds: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
        timeout: float = 30.0,
    ) -> None:
        config.check()
        self.config = config
        self.retries = retries
        self.backoff_seconds = backoff_seconds
        self.sleep = sleep
        self.http = http or httpx.Client(base_url=config.instance_url, timeout=timeout)
        self.auth = httpx.BasicAuth(config.username, config.password)

    # --- transport -----------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self.http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    auth=self.auth,
                    headers={"Accept": "application/json"},
                )
            except httpx.TransportError as exc:
                if attempt > self.retries:
                    raise ServiceNowUnavailableError(
                        0, f"cannot reach {self.config.host}: {exc}"
                    ) from exc
                self.sleep(self.backoff_seconds * 2 ** (attempt - 1))
                continue
            if response.status_code in RETRY_STATUSES and attempt <= self.retries:
                self.sleep(self.backoff_seconds * 2 ** (attempt - 1))
                continue
            return self._check(response)

    def _check(self, response: httpx.Response) -> httpx.Response:
        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            text = response.text.lower()
            if "hibernat" in text:
                raise ServiceNowUnavailableError(
                    response.status_code,
                    f"{self.config.host} is hibernating: log in to the developer portal to "
                    "wake the instance, then retry",
                )
            raise ServiceNowUnavailableError(
                response.status_code, f"unexpected non-JSON response from {self.config.host}"
            )
        if response.status_code in (401, 403):
            message = response.json().get("error", {}).get("message", "not authorized")
            raise ServiceNowAuthError(
                response.status_code,
                f"{message} (check the integration user's roles and the table ACLs)",
            )
        if response.status_code >= 400:
            error = response.json().get("error", {})
            raise ServiceNowError(
                response.status_code,
                f"{error.get('message', '')} {error.get('detail', '')}".strip(),
            )
        return response

    # --- Table API -----------------------------------------------------------------------

    def query(
        self,
        table: str,
        query: str = "",
        fields: list[str] | None = None,
        *,
        page_size: int = 100,
        display_value: str = "all",
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        while True:
            params: dict[str, Any] = {
                "sysparm_query": query,
                "sysparm_display_value": display_value,
                "sysparm_limit": page_size,
                "sysparm_offset": offset,
                "sysparm_exclude_reference_link": "true",
            }
            if fields:
                params["sysparm_fields"] = ",".join(fields)
            page = self._request("GET", f"/api/now/table/{table}", params=params).json()["result"]
            records.extend(page)
            if len(page) < page_size:
                return records
            offset += page_size

    def find_one(
        self, table: str, query: str, fields: list[str] | None = None
    ) -> dict[str, Any] | None:
        found = self.query(table, query, fields, page_size=2)
        return found[0] if found else None

    def create(self, table: str, values: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "POST", f"/api/now/table/{table}", json=values
        ).json()["result"]
        return result

    def update(self, table: str, sys_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self._request(
            "PATCH", f"/api/now/table/{table}/{sys_id}", json=values
        ).json()["result"]
        return result
