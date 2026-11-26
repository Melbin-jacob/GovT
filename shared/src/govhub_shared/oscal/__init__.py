"""OSCAL 1.1.3 helpers.

This package is the **only** place in the repo that imports compliance-trestle. Trestle's
models are built on the ``pydantic.v1`` compatibility layer; nothing from them crosses this
boundary. Callers get plain ``dict`` documents or the Pydantic v2 models in ``views``.
"""

from govhub_shared.oscal.documents import (
    OscalKind,
    canonical_bytes,
    content_hash,
    dump_json,
    stable_uuid,
    unwrap,
)
from govhub_shared.oscal.schema import OscalValidationError, schema_dir, validate
from govhub_shared.oscal.trestle_bridge import normalize
from govhub_shared.oscal.views import ControlView, PartView, PropView, iter_controls

__all__ = [
    "ControlView",
    "OscalKind",
    "OscalValidationError",
    "PartView",
    "PropView",
    "canonical_bytes",
    "content_hash",
    "dump_json",
    "iter_controls",
    "normalize",
    "schema_dir",
    "stable_uuid",
    "unwrap",
    "validate",
]
