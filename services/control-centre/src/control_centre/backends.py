"""Clients for the hub services the UI reads from (internal network only)."""

from __future__ import annotations

from typing import Any

import httpx

from control_centre.config import Settings


class BackendError(Exception):
    """A hub service failed or refused a request; shown to the user as an error page."""

    def __init__(self, service: str, status: int | None, detail: str) -> None:
        super().__init__(f"{service}: {status or 'unreachable'}: {detail}")
        self.service = service
        self.status = status
        self.detail = detail


class Service:
    def __init__(self, name: str, http: httpx.Client) -> None:
        self.name = name
        self.http = http

    def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self.http.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise BackendError(self.name, None, exc.__class__.__name__) from exc
        if response.status_code >= 400:
            try:
                detail = response.json().get("detail", response.text)
            except ValueError:
                detail = response.text
            raise BackendError(self.name, response.status_code, str(detail)[:500])
        return response

    def get(self, path: str, **params: Any) -> Any:
        return self.call("GET", path, params=params or None).json()

    def post(self, path: str, body: Any, **params: Any) -> Any:
        return self.call("POST", path, json=body, params=params or None).json()

    def text(self, path: str) -> str:
        return self.call("GET", path).text

    def upload(self, path: str, filename: str, data: bytes) -> Any:
        return self.call("POST", path, files={"file": (filename, data)}).json()


class Backends:
    def __init__(
        self, rulebook: Service, desk: Service, connector: Service, engine: Service
    ) -> None:
        self.rulebook = rulebook
        self.desk = desk
        self.connector = connector
        self.engine = engine

    @classmethod
    def from_settings(cls, settings: Settings) -> Backends:
        identity = {"X-GovHub-User": settings.demo_user, "X-GovHub-Role": settings.demo_role}

        def client(url: str, headers: dict[str, str] | None = None) -> httpx.Client:
            return httpx.Client(base_url=url, timeout=30.0, headers=headers)

        return cls(
            Service("rulebook", client(settings.rulebook_url)),
            Service("review-desk", client(settings.review_desk_url, identity)),
            Service("connector-hub", client(settings.connector_hub_url)),
            Service("assessment-engine", client(settings.assessment_engine_url, identity)),
        )
