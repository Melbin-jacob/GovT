"""Refuse to start when the configuration is unsafe.

- ``AUTH_MODE=demo``: only on a loopback or internal address (or all interfaces with
  ``GOVHUB_INTERNAL_ONLY=1``), and only when every tenant is synthetic.
- ``AUTH_MODE=oidc``: issuer, client and redirect set; the provider's hosts allowlisted
  (``OIDC_ALLOWED_HOSTS``) and reached over HTTPS (HTTP only with the local-only flag).
- Either mode: control-centre's signing key must be readable.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from control_centre.config import Settings
from control_centre.tenants import all_tenants
from govhub_shared.auth import demo_guard


class StartupRefusedError(RuntimeError):
    pass


def check(settings: Settings, host: str, session: Session) -> None:
    if settings.auth_mode not in ("oidc", "demo"):
        raise StartupRefusedError(f"AUTH_MODE must be oidc or demo, not {settings.auth_mode!r}")
    problems: list[str] = []
    for path in (settings.signing_key_file, settings.signing_kid_file):
        if not Path(path).is_file():
            problems.append(f"signing key file missing: {path}")
    if settings.auth_mode == "demo":
        tenants = [(t.id, t.synthetic) for t in all_tenants(session)]
        try:
            demo_guard.check("demo", host, settings.internal_only, tenants)
        except demo_guard.DemoModeRefusedError as exc:
            problems.append(str(exc))
    else:
        from control_centre.screens.signin import oidc_config

        problems += oidc_config().check()
    if problems:
        raise StartupRefusedError("control-centre refuses to start: " + "; ".join(problems))
