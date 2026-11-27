"""Read-only Pydantic v2 views over OSCAL catalog dicts, for code outside this package."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from govhub_shared import OSCAL_NS
from govhub_shared.oscal.documents import unwrap


class PropView(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    value: str
    ns: str | None = None


class PartView(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    id: str | None = None
    prose: str | None = None


class ControlView(BaseModel):
    """A flattened control: enough for parity checks, diffs and listings."""

    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    group_id: str | None = None
    control_class: str | None = Field(default=None, alias="class")
    props: tuple[PropView, ...] = ()
    parts: tuple[PartView, ...] = ()

    def prop(self, name: str, ns: str | None = None) -> str | None:
        """Value of the first prop with this name (and namespace, if given)."""
        for p in self.props:
            if p.name == name and (ns is None or p.ns == ns):
                return p.value
        return None

    def hub_prop(self, name: str) -> str | None:
        """Value of a prop in the hub's namespace."""
        return self.prop(name, OSCAL_NS)

    def part(self, name: str) -> str | None:
        """Prose of the first top-level part with this name."""
        for p in self.parts:
            if p.name == name:
                return p.prose
        return None


def _controls(container: Mapping[str, Any], group_id: str | None) -> Iterator[ControlView]:
    for control in container.get("controls", []):
        yield ControlView.model_validate({**control, "group_id": group_id})
        yield from _controls(control, group_id)  # nested (enhancement) controls


def _walk(container: Mapping[str, Any], group_id: str | None) -> Iterator[ControlView]:
    yield from _controls(container, group_id)
    for group in container.get("groups", []):
        yield from _walk(group, group.get("id"))


def iter_controls(catalog_doc: Mapping[str, Any]) -> list[ControlView]:
    """All controls in a ``{"catalog": {...}}`` document, in document order."""
    return list(_walk(unwrap(catalog_doc, "catalog"), None))
