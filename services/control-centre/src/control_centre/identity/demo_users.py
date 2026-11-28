"""Demo mode's fictional users (``data/demo/users.toml``)."""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

from govhub_shared.auth import PLATFORM_ROLES, TENANT_ROLES, Principal


@lru_cache
def demo_users(path: str) -> dict[str, Principal]:
    users: dict[str, Principal] = {}
    for entry in tomllib.loads(Path(path).read_text("utf-8"))["users"]:
        tenants: dict[str, set[str]] = {}
        for role in TENANT_ROLES:
            for tenant in entry.get(role, []):
                tenants.setdefault(tenant, set()).add(role)
        platform = frozenset(entry.get("platform", []))
        if platform - PLATFORM_ROLES:
            raise ValueError(
                f"{entry['id']}: not platform roles: {sorted(platform - PLATFORM_ROLES)}"
            )
        users[entry["id"]] = Principal(
            kind="user", id=entry["id"], name=entry["name"], platform_roles=platform,
            tenant_roles={t: frozenset(r) for t, r in tenants.items()},
        )  # fmt: skip
    return users
