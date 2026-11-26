"""Trestle's pydantic.v1 models must not leak outside govhub_shared.oscal."""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALLOWED = REPO / "shared" / "src" / "govhub_shared" / "oscal"
FORBIDDEN = re.compile(r"^\s*(from|import)\s+(trestle|pydantic\.v1)\b", re.MULTILINE)


def test_no_trestle_or_pydantic_v1_imports_outside_oscal_package() -> None:
    offenders = [
        str(path.relative_to(REPO))
        for root in (REPO / "shared", REPO / "services")
        for path in root.rglob("*.py")
        if ALLOWED not in path.parents
        and "tests" not in path.parts
        and FORBIDDEN.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []
