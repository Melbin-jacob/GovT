"""Internal client for the rulebook's drafting endpoints (engine identity)."""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from assessment_engine import drafting
from assessment_engine.settings_file import AssessmentConfig
from govhub_shared.model_gateway import ChatGateway

IDENTITY = {"X-GovHub-User": "assessment-engine", "X-GovHub-Role": "assessment-engine"}
LANGS = ("en", "fr")


class RulebookDrafts(Protocol):
    def batch(self, batch_id: str) -> dict[str, Any]: ...

    def put_model(self, item_id: str, lang: str, payload: dict[str, Any]) -> str: ...


class HttpRulebookDrafts:
    def __init__(self, base_url: str, http: httpx.Client | None = None) -> None:
        self.http = http or httpx.Client(base_url=base_url, timeout=60.0, headers=IDENTITY)

    def batch(self, batch_id: str) -> dict[str, Any]:
        resp = self.http.get(f"/drafts/batches/{batch_id}")
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
        return data

    def put_model(self, item_id: str, lang: str, payload: dict[str, Any]) -> str:
        resp = self.http.put(f"/drafts/items/{item_id}/model/{lang}", json=payload)
        return "sent" if resp.status_code < 400 else f"not sent: HTTP {resp.status_code}"


def inputs_for(batch: dict[str, Any], item: dict[str, Any], lang: str) -> drafting.DraftInput:
    """One language's drafting input, from that language's own clauses and catalog."""
    texts = batch["plan"]["clauses"][lang]
    current = None
    if item["target_control"]:
        current = batch["current_controls"].get(item["target_control"], {}).get(lang)
    return drafting.DraftInput(
        kind=item["kind"],
        lang=lang,
        old_clauses={n: texts["old"].get(n, "") for n in item["old_clauses"]},
        new_clauses={n: texts["new"].get(n, "") for n in item["new_clauses"]},
        current=current,
    )


def draft_batch(
    rulebook: RulebookDrafts, gateway: ChatGateway, batch_id: str, config: AssessmentConfig
) -> dict[str, Any]:
    batch = rulebook.batch(batch_id)
    results = []
    for item in batch["items"]:
        if item["kind"] not in ("edit", "new"):
            continue
        for lang in LANGS:
            if item["drafts"].get(lang, {}).get("status") != "pending":
                continue
            outcome = drafting.draft_item(gateway, inputs_for(batch, item, lang), config)
            sent = rulebook.put_model(item["id"], lang, outcome.payload())
            results.append(
                {
                    "item": item["id"],
                    "kind": item["kind"],
                    "target": item["target_control"] or item["proposed_id"],
                    "lang": lang,
                    "status": outcome.status,
                    "reason": outcome.reason,
                    "flags": outcome.flags,
                    "rulebook": sent,
                }
            )
    return {"batch": batch_id, "drafted": results}
