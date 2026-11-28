"""Development only: mint an internal token for a demo script (needs the dev keys).

    python -m govhub_shared.auth.mint --keys var/keys --aud rulebook --user demo-officer-01
    python -m govhub_shared.auth.mint --keys var/keys --aud rulebook --service connector-hub \\
        --all-tenants

``--user`` names a fictional user of ``data/demo/users.toml`` (signed as control-centre);
``--service`` signs as that service with its own key. Production keys are secrets that
this tool never sees.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from govhub_shared.auth.principal import PLATFORM_ROLES, TENANT_ROLES, Principal
from govhub_shared.auth.tokens import SigningKey, mint


def demo_user(users_file: Path, user_id: str) -> Principal:
    for entry in tomllib.loads(users_file.read_text("utf-8"))["users"]:
        if entry["id"] == user_id:
            tenants: dict[str, set[str]] = {}
            for role in TENANT_ROLES:
                for tenant in entry.get(role, []):
                    tenants.setdefault(tenant, set()).add(role)
            platform = frozenset(entry.get("platform", [])) & PLATFORM_ROLES
            return Principal(
                kind="user", id=user_id, name=entry.get("name", user_id),
                platform_roles=platform, tenant_roles={t: frozenset(r) for t, r in tenants.items()},
            )  # fmt: skip
    raise SystemExit(f"no demo user {user_id} in {users_file}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="govhub-mint", description=__doc__)
    parser.add_argument("--keys", default="var/keys")
    parser.add_argument("--aud", required=True)
    who = parser.add_mutually_exclusive_group(required=True)
    who.add_argument("--user")
    who.add_argument("--service")
    parser.add_argument("--all-tenants", action="store_true")
    parser.add_argument("--users-file", default="data/demo/users.toml")
    args = parser.parse_args(argv)
    keys = Path(args.keys)
    issuer = "control-centre" if args.user else args.service
    kid = (keys / f"{issuer}.kid").read_text("utf-8").strip()
    key = SigningKey.from_file(issuer, kid, keys / f"{issuer}.pem")
    principal = (
        demo_user(Path(args.users_file), args.user) if args.user
        else Principal(kind="service", id=args.service, all_tenants=args.all_tenants)
    )  # fmt: skip
    print(mint(key, principal, args.aud))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
