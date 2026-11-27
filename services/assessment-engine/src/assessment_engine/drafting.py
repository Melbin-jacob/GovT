"""Drafting control changes from changed policy text (the model drafts; a person decides).

Each item is drafted separately in English and in French, from that language's own
official clause text and that language's catalog: nothing is translated from one draft
to the other. Clause texts go to the model only as delimited data (same markers, nonce
and instruction-like-text checks as evidence).

Safeguards, in order; a failure marks the language's draft **needs-human** (a person
writes it; the model's text is kept as a suggestion), never guessed:
- instruction-like text in a clause; unparseable reply; a NEW item answered with
  "no change"; a missing check type for a new control;
- ``cited_clause`` must appear word for word in the NEW clause text (clause-diff
  normalization);
- confidence (self-reported, or the probability of the obligation value's first token)
  below the drafting threshold (PLACEHOLDER 0.70).
Then the **obligation check** (deterministic, ``govhub_shared.obligations``): the draft's
obligation code and any obligation words in its statement must match the code the
detector finds in the new clause; a mismatch **flags** the draft for the approver.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from importlib.resources import files
from typing import Any, Final, Literal

from assessment_engine.judgment import parse_reply
from assessment_engine.passages import injection_flags
from assessment_engine.settings_file import AssessmentConfig
from govhub_shared.model_gateway import ChatGateway, ChatMessage, ChatRequest, GatewayError
from govhub_shared.obligations import OBLIGATION_CODES, obligation_codes, primary_obligation
from govhub_shared.text import normalize_for_match

TASK: Final = "draft-control-change"
OUTPUT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "no_change": {"type": "boolean"},
        "statement": {"type": "string"},
        "guidance": {"type": ["string", "null"]},
        "objective": {"type": ["string", "null"]},
        "check_type": {"type": "string", "enum": ["rule-based", "judgment"]},
        "obligation": {"type": "string", "enum": list(OBLIGATION_CODES)},
        "cited_clause": {"type": "string"},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "no_change", "statement", "guidance", "objective", "check_type",
        "obligation", "cited_clause", "reasoning", "confidence",
    ],
    "additionalProperties": False,
}  # fmt: skip
LABELS: Final = {
    "en": {
        "task": "Task",
        "current": "Existing check",
        "old": "Previous clause text",
        "new": "New clause text",
        "type": "check type",
    },
    "fr": {
        "task": "Tâche",
        "current": "Contrôle existant",
        "old": "Texte précédent de la disposition",
        "new": "Nouveau texte de la disposition",
        "type": "type de contrôle",
    },
}
MIN_CITATION: Final = 15


@dataclass
class DraftInput:
    kind: str  # edit | new
    lang: str
    old_clauses: dict[str, str]
    new_clauses: dict[str, str]
    current: dict[str, Any] | None = None  # statement, guidance, objective, check_type


@dataclass
class DraftOutcome:
    status: str  # drafted | needs-human
    draft: dict[str, Any]
    flags: list[str] = field(default_factory=list)
    reason: str | None = None
    expected_obligation: str | None = None
    latency_seconds: float = 0.0
    completion_tokens: int | None = None
    input_hash: str = ""

    def payload(self) -> dict[str, Any]:
        """The body of PUT /drafts/items/{id}/model/{lang} on the rulebook."""
        keys = (
            *OUTPUT_SCHEMA["properties"],
            "model_id",
            "prompt_version",
        )
        return {
            "status": self.status,
            **{k: self.draft.get(k) for k in keys},
            "flags": self.flags,
            "reason": self.reason,
        }


def _neutralize(text: str) -> str:
    left, right = chr(0x2039) * 3, chr(0x203A) * 3
    return text.replace("<<<", left).replace(">>>", right)


def build_request(data: DraftInput, version: str) -> tuple[ChatRequest, str]:
    material = json.dumps(
        [
            data.kind,
            data.current,
            sorted(data.old_clauses.items()),
            sorted(data.new_clauses.items()),
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    input_hash = hashlib.sha256(material.encode("utf-8")).hexdigest()
    nonce = input_hash[:12]
    label = LABELS[data.lang]
    lines = [f"{label['task']}: {data.kind.upper()}"]
    if data.current:
        lines += ["", f"{label['current']} ({label['type']}: {data.current.get('check_type')}):"]
        lines.append(str(data.current.get("statement") or ""))
    for heading, clauses, tag in ((label["old"], data.old_clauses, "OLD"),
                                  (label["new"], data.new_clauses, "NEW")):  # fmt: skip
        if not clauses:
            continue
        lines += ["", f"{heading}:"]
        for number, text in sorted(clauses.items()):
            lines += [
                f"<<<CLAUSE {nonce} id={tag}-{number}>>>",
                _neutralize(text),
                f"<<<END {nonce}>>>",
            ]
    system = files("assessment_engine").joinpath("prompts", f"{version}.{data.lang}.md")
    messages = [
        ChatMessage(role="system", content=system.read_text("utf-8").replace("{nonce}", nonce)),
        ChatMessage(role="user", content="\n".join(lines)),
    ]
    language: Literal["en", "fr"] = "fr" if data.lang == "fr" else "en"
    request = ChatRequest(
        task=TASK, messages=messages, language=language, json_schema=OUTPUT_SCHEMA
    )
    return request, input_hash


def _field_confidence(content: str, logprobs: list[Any] | None, field_name: str) -> float | None:
    if not logprobs:
        return None
    import math

    text, spans = "", []
    for token in logprobs:
        spans.append((len(text), len(text) + len(token.token), token.logprob))
        text += token.token
    match = re.search(rf'"{field_name}"\s*:\s*"', text)
    if not match:
        return None
    for start, end, logprob in spans:
        if start <= match.end() < end or (start >= match.end() and end > start):
            return round(math.exp(logprob), 4)
    return None


def draft_item(gateway: ChatGateway, data: DraftInput, config: AssessmentConfig) -> DraftOutcome:
    lang = data.lang
    new_text = " ".join(t for _, t in sorted(data.new_clauses.items()))
    expected = primary_obligation(new_text, lang)  # type: ignore[arg-type]
    flagged = sorted({f for t in [*data.old_clauses.values(), *data.new_clauses.values()]
                      for f in injection_flags(t)})  # fmt: skip
    request, input_hash = build_request(data, config.drafting_prompt_version)
    base = {"model_id": None, "prompt_version": config.drafting_prompt_version}

    def human(reason: str, draft: dict[str, Any] | None = None, **extra: Any) -> DraftOutcome:
        flags = ["instruction-like-text"] if flagged else []
        return DraftOutcome(
            "needs-human", {**base, **(draft or {})}, flags, reason, expected,
            input_hash=input_hash, **extra,
        )  # fmt: skip

    if flagged:
        return human("instruction-like-text")
    try:
        reply = gateway.chat(request)
    except GatewayError:
        return human("model-unavailable")
    meta: dict[str, Any] = {
        "latency_seconds": reply.latency_seconds,
        "completion_tokens": reply.completion_tokens,
    }
    base["model_id"] = reply.model_id
    data_out = parse_reply(reply.content)
    if data_out is None:
        return human("unparseable", **meta)
    draft = {**base, **{k: data_out.get(k) for k in OUTPUT_SCHEMA["properties"]}}
    token = _field_confidence(reply.content, reply.logprobs, "obligation")
    try:
        self_conf: float | None = float(data_out.get("confidence"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        self_conf = None
    confidence = token if token is not None else self_conf
    draft["confidence"] = confidence
    draft["token_confidence"], draft["self_confidence"] = token, self_conf
    no_change = bool(data_out.get("no_change"))
    if data.kind == "new" and no_change:
        return human("no-change-for-new-clause", draft, **meta)
    if not draft.get("statement") or (data.kind == "new" and not draft.get("check_type")):
        return human("incomplete", draft, **meta)
    cited = str(draft.get("cited_clause") or "")
    if len(normalize_for_match(cited)) < MIN_CITATION or normalize_for_match(cited).strip(
        " .\"'"
    ) not in normalize_for_match(new_text):
        return human("citation-not-found", draft, **meta)
    if confidence is None or confidence < config.drafting_threshold:
        return human("low-confidence", draft, **meta)
    flags: list[str] = []
    obligation = draft.get("obligation")
    statement_codes = obligation_codes(str(draft.get("statement") or ""), lang)  # type: ignore[arg-type]
    if obligation != expected or (statement_codes and statement_codes != {expected}):
        flags.append("obligation-mismatch")
    return DraftOutcome("drafted", draft, flags, None, expected, input_hash=input_hash, **meta)
