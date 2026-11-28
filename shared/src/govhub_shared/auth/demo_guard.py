"""Demo mode may only run where nobody but evaluators can reach it, on synthetic data.

``AUTH_MODE=demo`` replaces sign-in with fictional users picked on the page. A service
refuses to start in demo mode unless
1. it is bound to a loopback or private (internal) address, or to all interfaces only
   inside a deployment that declares it internal-only (``GOVHUB_INTERNAL_ONLY=1``, e.g.
   Compose publishing ports on 127.0.0.1 only), and
2. every tenant is marked synthetic.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from typing import Final

LOOPBACK_NAMES: Final = frozenset({"localhost", "ip6-localhost"})
ALL_INTERFACES: Final = frozenset({"0.0.0.0", "::", ""})  # noqa: S104 - checked, not bound
# Explicit internal ranges: loopback, RFC 1918, IPv6 unique-local (not "private" in the
# wider sense Python uses, which includes documentation ranges).
INTERNAL_NETWORKS: Final = tuple(
    ipaddress.ip_network(n)
    for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128",
              "fc00::/7")
)  # fmt: skip


class DemoModeRefusedError(RuntimeError):
    pass


def internal_bind(host: str, internal_only: bool) -> bool:
    if host in LOOPBACK_NAMES:
        return True
    if host in ALL_INTERFACES:
        return internal_only
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in INTERNAL_NETWORKS)


def check(
    auth_mode: str, host: str, internal_only: bool, tenants: Iterable[tuple[str, bool]]
) -> None:
    """Raise ``DemoModeRefusedError`` (with every reason) if demo mode is not allowed here."""
    if auth_mode != "demo":
        return
    problems = []
    if not internal_bind(host, internal_only):
        problems.append(
            f"bound to {host or 'all interfaces'}: demo mode needs a loopback or internal "
            "address (or GOVHUB_INTERNAL_ONLY=1 where ports are published internally only)"
        )
    real = sorted(t for t, synthetic in tenants if not synthetic)
    if real:
        problems.append(f"tenants not marked synthetic: {', '.join(real)}")
    if problems:
        raise DemoModeRefusedError("AUTH_MODE=demo refused: " + "; ".join(problems))
