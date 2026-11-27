"""The drafting harness's synthetic batch is the planner's real output, kept current.

``data/accuracy/synthetic-demo/drafting/batches/example-widgets-2023-2025.json`` is the
batch the rulebook plans for Example Widgets 2023 -> 2025 (catalog 1.0.0), without IDs or
timestamps. The assessment engine's accuracy harness drafts from it with no database.
Regenerate with ``UPDATE_DRAFTING_BATCH=1`` when the planner or the demo data change.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from drafts_support import create_batch
from fastapi.testclient import TestClient
from test_impact import seed

ROOT = Path(__file__).resolve().parents[3]
BATCH_FILE = ROOT / "data/accuracy/synthetic-demo/drafting/batches/example-widgets-2023-2025.json"


def harness_batch(view: dict[str, Any]) -> dict[str, Any]:
    plan = view["plan"]
    return {
        "format": "govhub-drafting-batch/1",
        "note": "SYNTHETIC: planned by the rulebook from the fictional Directive on Example "
        "Widgets (2023-01-01 -> 2025-01-01) and catalog example-widgets 1.0.0.",
        "catalog": view["catalog"],
        "base_version": view["base_version"],
        "source_change": view["source_change"],
        "plan": {k: plan[k] for k in ("id_prefix", "proposed_version", "new_groups", "clauses")},
        "current_controls": view["current_controls"],
        "items": [
            {
                "id": f"item-{item['seq']:02d}",
                **{k: item[k] for k in ("seq", "kind", "old_clauses", "new_clauses",
                                        "target_control", "proposed_id", "group", "flags")},
                "drafts": {lang: {"status": "pending"} for lang in ("en", "fr")},
            }
            for item in view["items"]
        ],
    }  # fmt: skip


def test_drafting_harness_batch_is_current(client: TestClient) -> None:
    seed(client)
    current = harness_batch(create_batch(client))
    text = json.dumps(current, indent=1, ensure_ascii=False) + "\n"
    if os.environ.get("UPDATE_DRAFTING_BATCH") == "1":
        BATCH_FILE.write_text(text, "utf-8")
    assert BATCH_FILE.read_text("utf-8") == text, "run with UPDATE_DRAFTING_BATCH=1"
