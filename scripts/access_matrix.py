#!/usr/bin/env python3
"""The role-by-endpoint matrix: declared in docs/access-matrix.toml, checked against code.

Every HTTP route of the five services must have an entry; for routes gated by
``govhub_shared.auth.web.require`` the declared roles and services must equal the code's.
Routes that check roles in code (per tenant, per system) declare ``gate = "code"`` and list
the effective roles; their behaviour is covered by each service's tests/test_access.py.
docs/access-matrix.md is generated from the TOML (with the gates read from the code).

    uv run python scripts/access_matrix.py [--check]
"""

from __future__ import annotations

import importlib
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TOML = ROOT / "docs/access-matrix.toml"
DOC = ROOT / "docs/access-matrix.md"
APPS = {
    "rulebook": "rulebook.app",
    "review-desk": "review_desk.app",
    "assessment-engine": "assessment_engine.app",
    "connector-hub": "connector_hub.app",
    "control-centre": "control_centre.app",
}
ROLE_ABBR = {
    "system-owner": "SO", "reviewer": "RV", "governance-officer": "GO", "tenant-admin": "TA",
    "auditor": "AU", "platform-admin": "PA",
}  # fmt: skip
SKIP_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _gate(dependant: Any, extra: list[Any]) -> dict[str, Any]:
    """{"kind": public|token|require|session, "roles": [...], "services": [...]}"""
    found: dict[str, Any] = {"kind": "public", "roles": [], "services": []}

    def walk(d: Any) -> None:
        call = d.call
        if call is not None and hasattr(call, "govhub_roles"):
            found.update(kind="require", roles=sorted(call.govhub_roles),
                         services=sorted(call.govhub_services))  # fmt: skip
        elif (
            call is not None
            and getattr(call, "__name__", "") == "principal"
            and (call.__module__ == "govhub_shared.auth.web")
        ):
            if found["kind"] == "public":
                found["kind"] = "token"
        elif call is not None and getattr(call, "__name__", "") == "signed_in":
            found["kind"] = "session"
        for sub in d.dependencies:
            walk(sub)

    walk(dependant)
    for dep in extra:
        if getattr(dep.dependency, "__name__", "") == "signed_in":
            found["kind"] = "session"
    return found


def _routes(service: str) -> list[dict[str, Any]]:
    from fastapi.routing import APIRoute

    app = importlib.import_module(APPS[service]).app
    out: list[dict[str, Any]] = []

    def add(route: Any, path: str, extra: list[Any]) -> None:
        for method in sorted(route.methods - {"HEAD"}):
            out.append({"service": service, "method": method, "path": path,
                        **_gate(route.dependant, extra)})  # fmt: skip

    def visit(routes: list[Any]) -> None:
        for r in routes:
            if isinstance(r, APIRoute):
                add(r, r.path, [])
            elif type(r).__name__ == "_IncludedRouter":
                for c in r.effective_candidates():
                    if type(c).__name__ == "_IncludedRouter":
                        visit([c])
                    elif isinstance(c.original_route, APIRoute):
                        extra = list(getattr(c, "dependencies", None) or [])
                        add(c.original_route, c.path, extra)

    visit(app.routes)
    return [r for r in out if r["path"] not in SKIP_PATHS]


def declared() -> dict[tuple[str, str, str], dict[str, Any]]:
    data = tomllib.loads(TOML.read_text("utf-8"))
    return {(e["service"], e["method"], e["path"]): e for e in data["route"]}


def problems() -> list[str]:
    matrix = declared()
    found = [r for s in APPS for r in _routes(s)]
    issues = []
    seen = set()
    for r in found:
        key = (r["service"], r["method"], r["path"])
        seen.add(key)
        entry = matrix.get(key)
        if entry is None:
            issues.append(f"not in docs/access-matrix.toml: {' '.join(key)} (gate: {r['kind']})")
            continue
        gate = entry["gate"]
        if gate != r["kind"] and not (gate == "code" and r["kind"] == "token"):
            issues.append(f"{' '.join(key)}: declared gate {gate}, code has {r['kind']}")
        if r["kind"] == "require":
            if sorted(entry.get("roles", [])) != r["roles"]:
                issues.append(f"{' '.join(key)}: roles {entry.get('roles')} != code {r['roles']}")
            if sorted(entry.get("services", [])) != r["services"]:
                issues.append(f"{' '.join(key)}: services {entry.get('services')} != code "
                              f"{r['services']}")  # fmt: skip
    for key in sorted(set(matrix) - seen):
        issues.append(f"in docs/access-matrix.toml but not in the code: {' '.join(key)}")
    return issues


def markdown() -> str:
    data = tomllib.loads(TOML.read_text("utf-8"))
    lines = [
        "# Access matrix (role by endpoint)",
        "",
        "Generated from `docs/access-matrix.toml` by `scripts/access_matrix.py`; a test fails",
        "if any route of the five services is missing or if a declared gate differs from the",
        "code. Roles: SO system-owner, RV reviewer, GO governance-officer, TA tenant-admin,",
        "AU auditor (read-only), PA platform-admin. **Scope** says what the roles apply to:",
        "`shared` (not tenant data), `tenant` (only the caller's tenants: other tenants'",
        'records are "not found"), `platform`, `public` (probes and sign-in pages).',
        "Gates: `require` (checked before the endpoint runs), `code` (checked per tenant or",
        "per system inside the endpoint), `session` (control-centre pages: a signed-in user;",
        "the services behind them check the user's token again), `public`.",
        "",
    ]
    for service in APPS:
        rows = [e for e in data["route"] if e["service"] == service]
        header = "| Method | Path | Gate | Roles | Services | Scope | Notes |"
        lines += [f"## {service}", "", header, "|---|---|---|---|---|---|---|"]
        for e in rows:
            roles = ", ".join(ROLE_ABBR[r] for r in e.get("roles", [])) or "-"
            services = ", ".join(e.get("services", [])) or "-"
            lines.append(f"| {e['method']} | `{e['path']}` | {e['gate']} | {roles} | {services} "
                         f"| {e['scope']} | {e.get('note', '')} |")  # fmt: skip
        lines.append("")
    lines += [
        "platform-admin holds no tenant role: it reaches no tenant data (break-glass grants",
        "come in a later commit). Health and readiness probes are public on every service.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    issues = problems()
    for issue in issues:
        print(issue)
    if issues:
        return 1
    text = markdown()
    if "--check" in argv:
        if DOC.read_text("utf-8") != text:
            print("docs/access-matrix.md is stale: run scripts/access_matrix.py")
            return 1
        return 0
    DOC.write_text(text, "utf-8")
    print(f"wrote {DOC.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
