"""The single point of contact with compliance-trestle (OSCAL 1.1.3 models).

Trestle 3.12.4 builds its models on ``pydantic.v1``. Everything here takes and returns plain
dicts, so no v1 model type escapes this module.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from trestle.oscal import OSCAL_VERSION as TRESTLE_OSCAL_VERSION
from trestle.oscal.catalog import Catalog
from trestle.oscal.profile import Profile

from govhub_shared import OSCAL_VERSION
from govhub_shared.oscal.documents import OscalKind, unwrap

if TRESTLE_OSCAL_VERSION != OSCAL_VERSION:  # pragma: no cover - guards a bad upgrade
    raise ImportError(
        f"compliance-trestle models target OSCAL {TRESTLE_OSCAL_VERSION}, "
        f"but this repo is pinned to {OSCAL_VERSION}"
    )

_MODELS: dict[OscalKind, Any] = {"catalog": Catalog, "profile": Profile}


def normalize(doc: Mapping[str, Any], kind: OscalKind) -> dict[str, Any]:
    """Parse a document with trestle's OSCAL model and return it as a plain dict.

    This checks it against trestle's typed model (in addition to the JSON schema) and puts
    keys in OSCAL model order, so serialization is stable.
    """
    model = _MODELS[kind].parse_obj(unwrap(doc, kind))
    result: dict[str, Any] = json.loads(model.oscal_serialize_json())
    return result
