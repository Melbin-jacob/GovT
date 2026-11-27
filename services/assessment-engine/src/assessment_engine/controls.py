"""Control text and check type, from the rulebook (internal HTTP) or local catalog files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from govhub_shared.oscal import iter_controls


@dataclass(frozen=True)
class ControlInfo:
    control_id: str
    check_type: str
    statement: str
    objective: str | None


def controls_of(doc: dict[str, Any]) -> dict[str, ControlInfo]:
    out = {}
    for control in iter_controls(doc):
        out[control.id] = ControlInfo(
            control_id=control.id,
            check_type=control.hub_prop("check-type") or "judgment",
            statement=control.part("statement") or "",
            objective=control.part("assessment-objective"),
        )
    return out


class ControlSource(Protocol):
    def controls(self, catalog: str, version: str, lang: str) -> dict[str, ControlInfo]: ...


class RulebookControls:
    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(base_url=base_url, timeout=30.0)

    def controls(self, catalog: str, version: str, lang: str) -> dict[str, ControlInfo]:
        resp = self.http.get(f"/catalogs/{catalog}/versions/{version}", params={"lang": lang})
        resp.raise_for_status()
        return controls_of(resp.json())


class FileControls:
    """Catalog files in the repository (accuracy harness, tests)."""

    def __init__(self, *directories: Path) -> None:
        self.directories = directories

    def controls(self, catalog: str, version: str, lang: str) -> dict[str, ControlInfo]:
        for directory in self.directories:
            path = directory / f"{catalog}.{lang}.json"
            if path.is_file():
                doc = json.loads(path.read_text("utf-8"))
                found = doc["catalog"]["metadata"]["version"]
                if found != version:
                    raise LookupError(f"{path} is version {found}, not {version}")
                return controls_of(doc)
        raise LookupError(f"no catalog file for {catalog} ({lang})")
