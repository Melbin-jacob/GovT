"""Generate development keys and the trust file (Compose and CI; never commit keys).

    python -m govhub_shared.auth.devkeys var/keys [--if-missing]

Writes ``<issuer>.<kid>.pem`` (private, mode 0600) for control-centre and each service,
and ``trust.json`` (public keys only) that every service reads. A deployment makes its
own keys (e.g. Kubernetes secrets) and its own trust file; rotation adds the new public
key to the trust file before the issuer switches, then removes the old one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Final

from govhub_shared.auth.tokens import IssuerKind, TrustStore, generate_key

USER_ISSUERS: Final = ("control-centre",)
SERVICE_ISSUERS: Final = (
    "control-centre-service", "rulebook", "review-desk", "assessment-engine", "connector-hub",
)  # fmt: skip


def generate(folder: Path, kid_suffix: str = "dev") -> TrustStore:
    folder.mkdir(parents=True, exist_ok=True)
    trust = TrustStore()
    for issuer in (*USER_ISSUERS, *SERVICE_ISSUERS):
        kind: IssuerKind = "user" if issuer in USER_ISSUERS else "service"
        key = generate_key(issuer, f"{issuer}-{kid_suffix}")
        path = folder / f"{issuer}.pem"
        path.write_bytes(key.private_pem)
        path.chmod(0o600)
        (folder / f"{issuer}.kid").write_text(key.kid + "\n", "utf-8")
        trust.add(issuer, kind, key.kid, key.public_pem())
    (folder / "trust.json").write_text(json.dumps(trust.to_json(), indent=1) + "\n", "utf-8")
    return trust


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    folder = Path(args[0] if args else "var/keys")
    if "--if-missing" in argv and (folder / "trust.json").is_file():
        print(f"keys already in {folder}")
        return 0
    generate(folder)
    print(f"wrote development keys and trust.json to {folder} (do not commit)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
