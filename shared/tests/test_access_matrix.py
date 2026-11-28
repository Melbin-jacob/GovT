"""Every route of the five services is in docs/access-matrix.toml, with the gate the code
enforces; docs/access-matrix.md is current."""

from __future__ import annotations

import runpy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _script() -> dict[str, Any]:
    return runpy.run_path(str(ROOT / "scripts/access_matrix.py"))


def test_matrix_matches_the_code_and_the_doc_is_current() -> None:
    script = _script()
    assert script["problems"]() == []
    assert script["main"](["--check"]) == 0


def test_no_endpoint_is_open_to_any_token_without_a_role_check() -> None:
    script = _script()
    for service in script["APPS"]:
        for route in script["_routes"](service):
            if route["kind"] == "token":  # only the engine's per-system checks, declared
                entry = script["declared"]()[(service, route["method"], route["path"])]
                assert entry["gate"] == "code" and entry.get("roles"), route


def test_only_probes_and_sign_in_are_public() -> None:
    script = _script()
    public = sorted({(s, r["path"]) for s in script["APPS"] for r in script["_routes"](s)
                     if r["kind"] == "public"})  # fmt: skip
    allowed = {"/health", "/ready", "/", "/{lang}/sign-in", "/{lang}/sign-in/demo",
               "/auth/login", "/auth/callback", "/{lang}/sign-out"}  # fmt: skip
    assert {p for _, p in public} <= allowed, public


def test_an_unlisted_route_fails(tmp_path: Path) -> None:
    script = _script()
    text = (ROOT / "docs/access-matrix.toml").read_text("utf-8")
    first = text.index("[[route]]")
    second = text.index("[[route]]", first + 1)
    trimmed = tmp_path / "m.toml"
    trimmed.write_text(text[:first] + text[second:], "utf-8")
    script["problems"].__globals__["TOML"] = trimmed
    try:
        assert any(p.startswith("not in docs/access-matrix.toml") for p in script["problems"]())
    finally:
        script["problems"].__globals__["TOML"] = ROOT / "docs/access-matrix.toml"
