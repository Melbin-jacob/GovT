#!/usr/bin/env python3
"""Write docker/keycloak/govhub-realm.json from data/demo/users.toml (fictional users).

Local and CI only: the users, passwords and client secret are fictional and dev-only.
Groups follow data/config/oidc-roles.toml: /govhub/<tenant>/<role> and
/govhub/platform/<role>; the "groups" claim carries full paths.

    python3 scripts/make_keycloak_realm.py [--check]
"""

from __future__ import annotations

import json
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USERS = ROOT / "data/demo/users.toml"
TENANTS = ROOT / "data/demo/tenants.toml"
OUT = ROOT / "docker/keycloak/govhub-realm.json"
TENANT_ROLES = ("system-owner", "reviewer", "tenant-admin", "auditor")
PLATFORM_ROLES = ("governance-officer", "platform-admin")
DEV_PASSWORD = "dev-only-fictional"  # noqa: S105 - fictional demo users, local and CI only


def realm() -> dict[str, object]:
    users = tomllib.loads(USERS.read_text("utf-8"))["users"]
    tenants = [t["id"] for t in tomllib.loads(TENANTS.read_text("utf-8"))["tenants"]]
    groups = [{
        "name": "govhub",
        "subGroups": [
            {"name": "platform", "subGroups": [{"name": r} for r in PLATFORM_ROLES]},
            *[{"name": t, "subGroups": [{"name": r} for r in TENANT_ROLES]} for t in tenants],
        ],
    }]  # fmt: skip
    kc_users = []
    for u in users:
        paths = [f"/govhub/platform/{r}" for r in u.get("platform", [])]
        for role in TENANT_ROLES:
            paths += [f"/govhub/{t}/{role}" for t in u.get(role, [])]
        first, _, last = u["name"].partition(" ")
        kc_users.append({
            "username": u["id"], "enabled": True, "emailVerified": True,
            "firstName": first, "lastName": last, "email": f"{u['id']}@example.invalid",
            "credentials": [{"type": "password", "value": DEV_PASSWORD, "temporary": False}],
            "groups": sorted(paths),
        })  # fmt: skip
    return {
        "realm": "govhub",
        "enabled": True,
        "displayName": "GovHub (fictional demo realm, local and CI only)",
        "sslRequired": "none",
        "groups": groups,
        "users": kc_users,
        "clients": [
            {
                "clientId": "control-centre",
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": False,
                "secret": "dev-only-fictional-client-secret",
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "implicitFlowEnabled": False,
                "serviceAccountsEnabled": False,
                "redirectUris": ["http://127.0.0.1:8004/auth/callback"],
                "webOrigins": ["http://127.0.0.1:8004"],
                "attributes": {
                    "pkce.code.challenge.method": "S256",
                    "post.logout.redirect.uris": "http://127.0.0.1:8004/*",
                },
                "protocolMappers": [
                    {
                        "name": "groups",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-group-membership-mapper",
                        "config": {
                            "full.path": "true",
                            "id.token.claim": "true",
                            "access.token.claim": "false",
                            "userinfo.token.claim": "true",
                            "claim.name": "groups",
                        },
                    }
                ],
            }
        ],
    }


def main(argv: list[str]) -> int:
    text = json.dumps(realm(), indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        if OUT.read_text("utf-8") != text:
            print("docker/keycloak/govhub-realm.json is stale: run scripts/make_keycloak_realm.py")
            return 1
        return 0
    OUT.write_text(text, "utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
