"""Sign-in claims to hub roles (roles per tenant; governance-officer and platform-admin
platform-wide), from ``data/config/oidc-roles.toml``."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from govhub_shared.auth import PLATFORM_ROLES, TENANT_ROLES, Principal


def _pattern(template: str) -> re.Pattern[str]:
    escaped = re.escape(template).replace(r"\{tenant\}", r"(?P<tenant>[A-Za-z0-9._-]+)")
    return re.compile("^" + escaped.replace(r"\{role\}", r"(?P<role>[a-z-]+)") + "$")


@dataclass
class RoleMap:
    user_id_claim: str = "preferred_username"
    name_claim: str = "name"
    groups_claim: str = "groups"
    tenant_group_pattern: str = "/govhub/{tenant}/{role}"
    platform_group_pattern: str = "/govhub/platform/{role}"
    groups: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> RoleMap:
        data = tomllib.loads(Path(path).read_text("utf-8"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def principal(self, claims: dict[str, Any]) -> Principal:
        user_id = claims.get(self.user_id_claim) or claims.get("sub")
        if not user_id:
            raise ValueError(f"no {self.user_id_claim} or sub claim")
        platform: set[str] = set()
        tenants: dict[str, set[str]] = {}
        tenant_re, platform_re = (_pattern(self.tenant_group_pattern),
                                  _pattern(self.platform_group_pattern))  # fmt: skip
        for group in claims.get(self.groups_claim) or []:
            group = str(group)
            if group in self.groups:
                entry = self.groups[group]
                if "platform" in entry:
                    platform.add(entry["platform"])
                else:
                    tenants.setdefault(entry["tenant"], set()).add(entry["role"])
            elif m := platform_re.match(group):
                platform.add(m["role"])
            elif m := tenant_re.match(group):
                tenants.setdefault(m["tenant"], set()).add(m["role"])
        # Unknown roles are dropped (never guessed); misplaced ones too.
        platform &= PLATFORM_ROLES
        cleaned = {t: frozenset(r & TENANT_ROLES) for t, r in tenants.items() if r & TENANT_ROLES}
        return Principal(
            kind="user", id=str(user_id), name=str(claims.get(self.name_claim) or user_id),
            platform_roles=frozenset(platform), tenant_roles=cleaned,
        )  # fmt: skip
