"""Catalog loaders for profile resolution. Local only: no network access, ever."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from sqlalchemy.orm import Session

from rulebook import store

_API_HREF = re.compile(r"^/?catalogs/(?P<name>[^/]+)/versions/(?P<version>[^/?#]+)$")


def file_loader(base_dir: Path) -> Any:
    """Resolve relative file hrefs against ``base_dir`` (the profile's directory)."""

    def load(href: str) -> dict[str, Any]:
        parts = urlsplit(href)
        if parts.scheme or parts.netloc:
            raise ValueError("only relative file references are allowed (no network access)")
        data: dict[str, Any] = json.loads((base_dir / parts.path).read_text(encoding="utf-8"))
        return data

    return load


def store_loader(session: Session) -> Any:
    """Resolve hrefs of the form ``/catalogs/{name}/versions/{version}?lang=en`` (the API
    path of a stored catalog version) against the rulebook database."""

    def load(href: str) -> dict[str, Any]:
        parts = urlsplit(href)
        match = _API_HREF.match(parts.path)
        if parts.scheme or parts.netloc or match is None:
            raise ValueError(
                "href must be a stored catalog path: /catalogs/{name}/versions/{version}?lang=en"
            )
        lang = parse_qs(parts.query).get("lang", ["en"])[0]
        row = store.get_version(session, match["name"], match["version"], lang)
        return row.document

    return load
