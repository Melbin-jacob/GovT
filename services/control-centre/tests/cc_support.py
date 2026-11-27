"""Canned hub-service responses for page tests (captured from the synthetic demo)."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from control_centre.backends import Backends, Service

FIXTURES = Path(__file__).parent / "fixtures"
Handler = Callable[[httpx.Request], Any]


def fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text("utf-8"))


class FakeService:
    """Routes (method, path) to canned JSON (or a handler); records every request."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.routes: dict[tuple[str, str], Any] = {}
        self.requests: list[httpx.Request] = []

    def on(self, method: str, path: str, response: Any) -> None:
        self.routes[(method, path)] = response

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        key = (request.method, request.url.path)
        if key not in self.routes:
            return httpx.Response(404, json={"detail": f"no fake route {key}"})
        body = self.routes[key]
        if callable(body):
            body = body(request)
        if isinstance(body, httpx.Response):
            return body
        if isinstance(body, str):
            return httpx.Response(200, text=body)
        return httpx.Response(200, json=body)

    def service(self) -> Service:
        return Service(
            self.name,
            httpx.Client(base_url="http://fake", transport=httpx.MockTransport(self._handle)),
        )


class FakeHub:
    def __init__(self) -> None:
        self.rulebook = FakeService("rulebook")
        self.desk = FakeService("review-desk")
        self.connector = FakeService("connector-hub")

    def backends(self) -> Backends:
        return Backends(self.rulebook.service(), self.desk.service(), self.connector.service())


def stub_policy(hub: FakeHub) -> None:
    """Sources, clause diffs and source documents of the synthetic demo directive."""
    hub.rulebook.on("GET", "/sources", fixture("sources.json"))

    def diff(request: httpx.Request) -> Any:
        lang = request.url.params["lang"]
        return {lang: fixture(f"diff.{lang}.json")[lang]}

    hub.rulebook.on("GET", "/sources/example-widgets/diff", diff)
    for version in ("2023-01-01", "2025-01-01"):

        def doc(request: httpx.Request, version: str = version) -> Any:
            return fixture(f"source.{version}.{request.url.params['lang']}.json")

        hub.rulebook.on("GET", f"/sources/example-widgets/versions/{version}", doc)


def stub_impact(hub: FakeHub) -> None:
    """Catalogs, the impact report, its forecast and the tasks in (mock) ServiceNow."""
    stub_policy(hub)
    hub.rulebook.on("GET", "/catalogs", fixture("catalogs.json"))
    hub.rulebook.on("POST", "/impact-reports", fixture("impact.en.json"))
    hub.desk.on("POST", "/forecast", fixture("forecast.json"))
    hub.connector.on("GET", "/tasks/notes", fixture("task-notes.json"))
