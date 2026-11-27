"""EN/FR parity: both language catalogs must contain exactly the same control IDs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from govhub_shared.oscal import iter_controls


@dataclass(frozen=True)
class ParityReport:
    only_en: tuple[str, ...]
    only_fr: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.only_en and not self.only_fr


class ParityError(ValueError):
    def __init__(self, report: ParityReport) -> None:
        self.report = report
        super().__init__(
            "EN/FR catalogs differ in control IDs: "
            f"only in EN {list(report.only_en)}, only in FR {list(report.only_fr)}"
        )


def check_parity(en_doc: Mapping[str, Any], fr_doc: Mapping[str, Any]) -> ParityReport:
    en = {c.id for c in iter_controls(en_doc)}
    fr = {c.id for c in iter_controls(fr_doc)}
    return ParityReport(only_en=tuple(sorted(en - fr)), only_fr=tuple(sorted(fr - en)))


def require_parity(en_doc: Mapping[str, Any], fr_doc: Mapping[str, Any]) -> None:
    report = check_parity(en_doc, fr_doc)
    if not report.ok:
        raise ParityError(report)
