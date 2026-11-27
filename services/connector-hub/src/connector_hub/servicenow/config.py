"""ServiceNow connection settings.

Read from environment variables, or from a local ``KEY=VALUE`` file (default
``.env.servicenow``, gitignored; see ``.env.servicenow.example``). Environment variables win.
Credentials are never logged, never written anywhere, and never committed.

- ``SERVICENOW_INSTANCE_URL`` e.g. ``https://dev12345.service-now.com``
- ``SERVICENOW_USERNAME``, ``SERVICENOW_PASSWORD``
- ``CONNECTOR_ALLOWED_HOSTS``: comma-separated host names the connector may call. The
  instance host must be listed (the network rule: only configured hosts).
- ``CONNECTOR_ALLOW_INSECURE_HTTP=1``: allow ``http://`` (the mock only; never a real instance)
- ``SERVICENOW_ENV_FILE``: path of the local file (default ``.env.servicenow``)
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


class ConnectorConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ServiceNowConfig:
    instance_url: str
    username: str
    password: str = field(repr=False)
    allowed_hosts: tuple[str, ...]
    allow_insecure_http: bool = False

    @property
    def host(self) -> str:
        return urlsplit(self.instance_url).hostname or ""

    def check(self) -> None:
        parts = urlsplit(self.instance_url)
        if parts.scheme not in ("https", "http") or not parts.hostname:
            raise ConnectorConfigError(
                f"SERVICENOW_INSTANCE_URL is not a URL: {self.instance_url!r}"
            )
        if parts.scheme == "http" and not self.allow_insecure_http:
            raise ConnectorConfigError(
                "SERVICENOW_INSTANCE_URL must use https (http is only for the mock, with "
                "CONNECTOR_ALLOW_INSECURE_HTTP=1)"
            )
        if self.host not in self.allowed_hosts:
            raise ConnectorConfigError(
                f"host {self.host!r} is not in CONNECTOR_ALLOWED_HOSTS; the connector only "
                "calls configured hosts"
            )


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def load_config(env: Mapping[str, str] | None = None) -> ServiceNowConfig:
    env = dict(os.environ if env is None else env)
    file_values = _read_env_file(Path(env.get("SERVICENOW_ENV_FILE", ".env.servicenow")))
    merged = {**file_values, **{k: v for k, v in env.items() if v}}
    missing = [
        k
        for k in ("SERVICENOW_INSTANCE_URL", "SERVICENOW_USERNAME", "SERVICENOW_PASSWORD")
        if not merged.get(k)
    ]
    if missing:
        raise ConnectorConfigError(
            f"ServiceNow is not configured: set {', '.join(missing)} (environment or "
            ".env.servicenow)"
        )
    config = ServiceNowConfig(
        instance_url=merged["SERVICENOW_INSTANCE_URL"].rstrip("/"),
        username=merged["SERVICENOW_USERNAME"],
        password=merged["SERVICENOW_PASSWORD"],
        allowed_hosts=tuple(
            h.strip().lower()
            for h in merged.get("CONNECTOR_ALLOWED_HOSTS", "").split(",")
            if h.strip()
        ),
        allow_insecure_http=merged.get("CONNECTOR_ALLOW_INSECURE_HTTP", "") in ("1", "true"),
    )
    config.check()
    return config
