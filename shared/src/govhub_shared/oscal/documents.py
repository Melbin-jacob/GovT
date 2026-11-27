"""Plain-dict helpers for OSCAL documents: identity, hashing and stable serialization."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any, Literal

OscalKind = Literal["catalog", "profile", "plan-of-action-and-milestones"]

# Fixed namespace for deterministic (uuid5) identifiers minted by the hub.
HUB_UUID_NAMESPACE = uuid.UUID("5d0c8a4e-6b0f-5c38-9a52-6a1f0f1e2b7d")


def stable_uuid(*parts: str) -> str:
    """Deterministic UUID (v5) for the given name parts."""
    return str(uuid.uuid5(HUB_UUID_NAMESPACE, "\x1f".join(parts)))


def unwrap(doc: Mapping[str, Any], kind: OscalKind) -> dict[str, Any]:
    """Return the inner model object of a ``{"<kind>": {...}}`` document."""
    if set(doc) != {kind}:
        raise ValueError(f"expected a document with a single top-level '{kind}' key")
    inner = doc[kind]
    if not isinstance(inner, dict):
        raise ValueError(f"'{kind}' must be an object")
    return inner


def canonical_bytes(value: Any) -> bytes:
    """Canonical JSON: sorted keys, no whitespace, UTF-8. Used for hashing only."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def content_hash(doc: Mapping[str, Any], kind: OscalKind) -> str:
    """SHA-256 of a document's *content*.

    Excludes the fields that identify a revision rather than describe it: the top-level
    ``uuid`` and ``metadata.last-modified``. Two documents with the same controls, metadata
    and version hash equal; any content change gives a different hash.
    """
    inner = copy.deepcopy(unwrap(doc, kind))
    inner.pop("uuid", None)
    metadata = inner.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("last-modified", None)
    return hashlib.sha256(canonical_bytes({kind: inner})).hexdigest()


def dump_json(doc: Mapping[str, Any]) -> str:
    """Stable on-disk serialization: key order preserved, 2-space indent, trailing newline."""
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
