"""Validation against the vendored NIST OSCAL 1.1.3 JSON schemas.

The NIST schemas use Unicode property classes (``\\p{L}``) in ``pattern``, which Python's
``re`` does not support, so the ``pattern`` keyword is re-implemented with the ``regex``
module. Formats (date-time, uri, uri-reference, email) are asserted, not just annotated.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping
from functools import cache
from pathlib import Path
from typing import Any

import regex
from jsonschema import Draft7Validator, ValidationError, validators

from govhub_shared import OSCAL_VERSION
from govhub_shared.oscal.documents import OscalKind

SCHEMA_DIR_ENV = "GOVHUB_OSCAL_SCHEMA_DIR"
_SCHEMA_SUBDIR = Path("schemas") / f"oscal-{OSCAL_VERSION}"


class OscalValidationError(ValueError):
    """Raised when a document does not validate against the OSCAL schema."""

    def __init__(self, kind: OscalKind, errors: list[str]) -> None:
        self.kind = kind
        self.errors = errors
        summary = "\n".join(f"  - {e}" for e in errors[:20])
        more = f"\n  ... and {len(errors) - 20} more" if len(errors) > 20 else ""
        super().__init__(
            f"OSCAL {OSCAL_VERSION} {kind} schema validation failed "
            f"({len(errors)} error(s)):\n{summary}{more}"
        )


def schema_dir() -> Path:
    """Locate the vendored schema directory.

    ``$GOVHUB_OSCAL_SCHEMA_DIR`` wins; otherwise the nearest ancestor of this file that
    contains ``schemas/oscal-1.1.3`` (the repo checkout, or ``/app`` in the container).
    """
    override = os.environ.get(SCHEMA_DIR_ENV)
    if override:
        return Path(override)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / _SCHEMA_SUBDIR
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"cannot find {_SCHEMA_SUBDIR}; set {SCHEMA_DIR_ENV} to the vendored schema directory"
    )


def _unicode_pattern(
    validator: Any, pattern: str, instance: Any, schema: Mapping[str, Any]
) -> Iterator[ValidationError]:
    if isinstance(instance, str) and not regex.search(pattern, instance):
        yield ValidationError(f"{instance!r} does not match {pattern!r}")


# types-jsonschema leaves `extend` unannotated; the result is a Draft7Validator subclass.
_OscalValidator = validators.extend(  # type: ignore[no-untyped-call]
    Draft7Validator, {"pattern": _unicode_pattern}
)


@cache
def _validator(kind: OscalKind) -> Any:
    filename = {"plan-of-action-and-milestones": "poam"}.get(kind, kind)
    path = schema_dir() / f"oscal_{filename}_schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    return _OscalValidator(schema, format_checker=Draft7Validator.FORMAT_CHECKER)


def validate(doc: Mapping[str, Any], kind: OscalKind) -> None:
    """Validate a full ``{"<kind>": {...}}`` document; raise on any error."""
    errors = sorted(
        _validator(kind).iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path]
    )
    if errors:
        raise OscalValidationError(
            kind, [f"/{'/'.join(str(p) for p in e.absolute_path)}: {e.message}" for e in errors]
        )
