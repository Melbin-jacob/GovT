"""A SCRIPTED FAKE model server for the Compose demo and CI: never a real model.

Speaks the OpenAI-compatible ``/v1/chat/completions`` API and answers only requests it
has a recorded reply for (same key as ``RecordedGateway``: model, task, messages,
schema). So the engine's real HTTP gateway, host allowlist and safeguards run end to end
without any model. Unknown requests get HTTP 404, which the engine turns into
"unable to determine".
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from govhub_shared.model_gateway import ChatMessage, ChatRequest, ChatResponse, recording_key

app = FastAPI(title="Scripted fake model (demo and CI only)")


def _recordings() -> Path:
    return Path(os.environ.get("FAKE_MODEL_RECORDINGS", "data/accuracy/synthetic-demo/recordings"))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": "scripted fake (no real model)"}


@app.post("/v1/chat/completions")
def chat(body: dict[str, Any]) -> dict[str, Any]:
    schema = (body.get("response_format") or {}).get("json_schema") or {}
    request = ChatRequest(
        task=str(schema.get("name", "unknown")),
        messages=[ChatMessage(**m) for m in body.get("messages", [])],
        json_schema=schema.get("schema"),
    )
    path = _recordings() / f"{recording_key(str(body.get('model', '')), request)}.json"
    if not path.is_file():
        raise HTTPException(404, "no scripted reply for this request")
    reply = ChatResponse.model_validate(json.loads(path.read_text("utf-8"))["response"])
    choice: dict[str, Any] = {
        "index": 0,
        "message": {"role": "assistant", "content": reply.content},
    }
    if reply.logprobs:
        choice["logprobs"] = {
            "content": [
                {
                    "token": t.token,
                    "logprob": t.logprob,
                    "top_logprobs": [{"token": a, "logprob": b} for a, b in t.top],
                }
                for t in reply.logprobs
            ]
        }
    return {
        "model": reply.model_id,
        "choices": [choice],
        "usage": {
            "prompt_tokens": reply.prompt_tokens,
            "completion_tokens": reply.completion_tokens,
        },
    }
