"""Clients for the hub services the UI reads from (internal network only)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from control_centre.config import Settings
from govhub_shared.auth import Principal, SigningKey, mint


class BackendError(Exception):
    """A hub service failed or refused a request; shown to the user as an error page."""

    def __init__(self, service: str, status: int | None, detail: str) -> None:
        super().__init__(f"{service}: {status or 'unreachable'}: {detail}")
        self.service = service
        self.status = status
        self.detail = detail


Identity = Callable[[str], dict[str, str]]


class Service:
    """One hub service. ``identity(audience)`` gives the headers that say who is calling:
    an internal token for this service, minted for the signed-in user."""

    def __init__(self, name: str, http: httpx.Client, identity: Identity | None = None) -> None:
        self.name = name
        self.http = http
        self.identity = identity

    def call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        if self.identity is not None:
            kwargs["headers"] = {**self.identity(self.name), **(kwargs.get("headers") or {})}
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

    def post(
        self, path: str, body: Any, headers: dict[str, str] | None = None, **params: Any
    ) -> Any:
        return self.call("POST", path, json=body, params=params or None, headers=headers).json()

    def put(self, path: str, body: Any, headers: dict[str, str] | None = None) -> Any:
        return self.call("PUT", path, json=body, headers=headers).json()

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
    def for_user(cls, settings: Settings, identity: Identity | None) -> Backends:
        clients = _clients(settings)
        return cls(*(Service(name, clients[name], identity) for name in SERVICE_NAMES))


SERVICE_NAMES = ("rulebook", "review-desk", "connector-hub", "assessment-engine")
_CLIENTS: dict[str, httpx.Client] = {}


def _clients(settings: Settings) -> dict[str, httpx.Client]:
    """One connection pool per service, shared by every request."""
    if not _CLIENTS:
        urls = {
            "rulebook": settings.rulebook_url,
            "review-desk": settings.review_desk_url,
            "connector-hub": settings.connector_hub_url,
            "assessment-engine": settings.assessment_engine_url,
        }
        for name, url in urls.items():
            _CLIENTS[name] = httpx.Client(base_url=url, timeout=30.0)
    return _CLIENTS


def acting_role(principal: Principal, audience: str) -> str:
    """TRANSITIONAL (removed when every service reads tokens): the single role the old
    placeholder header carried."""
    order = (
        ("governance-officer", "reviewer") if audience == "rulebook"
        else ("reviewer", "governance-officer")
    )  # fmt: skip
    for role in (*order, "tenant-admin", "system-owner", "auditor", "platform-admin"):
        if principal.has(role):
            return role
    return "none"


def identity_for(principal: Principal, key: SigningKey) -> Identity:
    """Headers for one call: a fresh internal token for that service (5 minutes, one
    audience), plus the transitional placeholder headers."""

    def headers(audience: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {mint(key, principal, audience)}",
            "X-GovHub-User": principal.id,
            "X-GovHub-Role": acting_role(principal, audience),
        }

    return headers
