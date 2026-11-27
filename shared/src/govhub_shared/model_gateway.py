"""Model gateway: the only way the hub talks to a language model.

An AI model only ever *drafts*; a human always decides.

Implementations:

- ``OpenAIGateway`` calls a **self-hosted, OpenAI-compatible** server inside the
  deployment (vLLM, llama.cpp server, Ollama) at ``/v1/chat/completions``. It refuses any
  host not in ``MODEL_GATEWAY_ALLOWED_HOSTS``: the model server is internal to the
  deployment and this is the only call the assessment engine makes besides hub services.
  Requests use temperature 0 and a fixed seed, ask for structured JSON output and for
  token log-probabilities (used for confidence where the server provides them).
- ``RecordedGateway`` replays recorded replies keyed by a hash of (model, task, messages,
  schema). CI and tests use it: no model ever runs in CI. ``record`` mode wraps a real
  gateway and saves its replies (only synthetic evidence is ever committed).
- ``NullGateway`` refuses every request (no model configured).

Never logs message content: evidence may hold personal or Protected information.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, Field

log = logging.getLogger("govhub.model_gateway")


class GatewayError(RuntimeError):
    """The model could not be reached or gave no usable reply."""


# --- requests and replies --------------------------------------------------------------


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    task: str = Field(description="Task identifier, e.g. 'assess-judgment-check'")
    messages: list[ChatMessage]
    language: Literal["en", "fr"] = "en"
    json_schema: dict[str, Any] | None = Field(
        default=None, description="Ask the server for JSON matching this schema"
    )
    max_tokens: int = 800
    logprobs: bool = True


class TokenLogprob(BaseModel):
    token: str
    logprob: float
    top: list[tuple[str, float]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    content: str
    model_id: str
    logprobs: list[TokenLogprob] | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_seconds: float = 0.0
    recorded: bool = False


@runtime_checkable
class ChatGateway(Protocol):
    def chat(self, request: ChatRequest) -> ChatResponse: ...


# Kept from Milestone 1 (drafting interface; drafting of controls is Milestone 6).
class DraftRequest(BaseModel):
    """A request for the model to draft something for human review."""

    task: str = Field(description="Task identifier, e.g. 'draft-controls-from-clause'.")
    prompt: str
    language: str = Field(default="en", pattern="^(en|fr)$")


class DraftResponse(BaseModel):
    """A model draft. Never authoritative: always routed to a human reviewer."""

    text: str
    model_id: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


@runtime_checkable
class ModelGateway(Protocol):
    """Swappable model gateway (drafting)."""

    def draft(self, request: DraftRequest) -> DraftResponse:
        """Return a draft for human review."""
        ...


class NullGateway:
    """No model configured: every request is refused."""

    def draft(self, request: DraftRequest) -> DraftResponse:
        raise NotImplementedError("No model gateway is configured.")

    def chat(self, request: ChatRequest) -> ChatResponse:
        raise GatewayError("No model gateway is configured (MODEL_GATEWAY_URL is empty).")


# --- OpenAI-compatible self-hosted server ----------------------------------------------


class GatewayConfig(BaseModel):
    base_url: str
    model: str
    allowed_hosts: list[str]
    api_key: str | None = None  # from the environment only; local servers rarely need one
    timeout_seconds: float = 300.0
    seed: int = 7
    retries: int = 2


def check_host(url: str, allowed: list[str]) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not host:
        raise GatewayError(f"model gateway URL must be http(s)://host[:port]: {url!r}")
    if host not in {h.strip().lower() for h in allowed if h.strip()}:
        raise GatewayError(
            f"model host {host!r} is not in MODEL_GATEWAY_ALLOWED_HOSTS; the model server "
            "must be internal to the deployment and listed explicitly"
        )
    return host


def _logprobs(choice: dict[str, Any]) -> list[TokenLogprob] | None:
    content = (choice.get("logprobs") or {}).get("content")
    if not isinstance(content, list):
        return None
    out = []
    for item in content:
        top = [
            (str(t.get("token", "")), float(t.get("logprob", 0.0)))
            for t in item.get("top_logprobs") or []
        ]
        out.append(
            TokenLogprob(
                token=str(item.get("token", "")), logprob=float(item.get("logprob", 0.0)), top=top
            )
        )
    return out


class OpenAIGateway:
    def __init__(self, config: GatewayConfig, http: httpx.Client | None = None) -> None:
        self.host = check_host(config.base_url, config.allowed_hosts)
        self.config = config
        headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        self.http = http or httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=config.timeout_seconds,
            headers=headers,
            follow_redirects=False,  # a redirect could leave the allowed host
        )

    def _body(self, request: ChatRequest) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [m.model_dump() for m in request.messages],
            "temperature": 0,
            "seed": self.config.seed,
            "max_tokens": request.max_tokens,
        }
        if request.json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.task,
                    "schema": request.json_schema,
                    "strict": True,
                },
            }
        if request.logprobs:
            body["logprobs"] = True
            body["top_logprobs"] = 5
        return body

    def chat(self, request: ChatRequest) -> ChatResponse:
        body = self._body(request)
        start = time.perf_counter()
        last: str = ""
        for attempt in range(self.config.retries + 1):
            try:
                response = self.http.post("/v1/chat/completions", json=body)
            except httpx.HTTPError as exc:
                last = exc.__class__.__name__
            else:
                if response.status_code < 500:
                    break
                last = f"HTTP {response.status_code}"
            time.sleep(min(2.0**attempt, 8.0))
        else:
            raise GatewayError(f"model server unreachable ({last})")
        if response.status_code >= 400:
            raise GatewayError(f"model server refused the request: HTTP {response.status_code}")
        try:
            data = response.json()
            choice = data["choices"][0]
            content = str(choice["message"]["content"] or "")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise GatewayError("model server reply is not an OpenAI chat completion") from exc
        usage = data.get("usage") or {}
        latency = time.perf_counter() - start
        log.info(  # never the content: evidence may be personal or Protected
            "model call task=%s model=%s prompt_tokens=%s completion_tokens=%s seconds=%.2f",
            request.task,
            data.get("model", self.config.model),
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            latency,
        )
        return ChatResponse(
            content=content,
            model_id=str(data.get("model") or self.config.model),
            logprobs=_logprobs(choice),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            latency_seconds=latency,
        )


# --- recorded replies (CI) -------------------------------------------------------------


def recording_key(model_id: str, request: ChatRequest) -> str:
    material = {
        "model": model_id,
        "task": request.task,
        "messages": [m.model_dump() for m in request.messages],
        "schema": request.json_schema,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


class RecordedGateway:
    """Replays recorded replies; in ``record`` mode asks ``inner`` and saves its reply."""

    def __init__(
        self,
        directory: Path,
        model_id: str,
        *,
        mode: Literal["replay", "record"] = "replay",
        inner: ChatGateway | None = None,
    ) -> None:
        if mode == "record" and inner is None:
            raise GatewayError("record mode needs a real gateway to record from")
        self.directory = directory
        self.model_id = model_id
        self.mode = mode
        self.inner = inner

    def path(self, request: ChatRequest) -> Path:
        return self.directory / f"{recording_key(self.model_id, request)}.json"

    def chat(self, request: ChatRequest) -> ChatResponse:
        path = self.path(request)
        if self.mode == "record":
            assert self.inner is not None  # noqa: S101 - checked in __init__
            reply = self.inner.chat(request)
            self.directory.mkdir(parents=True, exist_ok=True)
            saved = {"task": request.task, "response": reply.model_dump(mode="json")}
            path.write_text(json.dumps(saved, indent=1, ensure_ascii=False) + "\n", "utf-8")
            return reply
        if not path.is_file():
            raise GatewayError(f"no recorded reply for this request ({path.name})")
        saved = json.loads(path.read_text("utf-8"))
        reply = ChatResponse.model_validate(saved["response"])
        return reply.model_copy(update={"recorded": True})


def gateway_from_env(environ: dict[str, str] | None = None) -> ChatGateway:
    """MODEL_GATEWAY_URL / _MODEL / _ALLOWED_HOSTS / _API_KEY / _RECORDINGS / _MODE."""
    env = dict(os.environ if environ is None else environ)
    model = env.get("MODEL_GATEWAY_MODEL", "")
    recordings = env.get("MODEL_GATEWAY_RECORDINGS", "")
    mode = env.get("MODEL_GATEWAY_MODE", "replay" if recordings else "live")
    real: ChatGateway | None = None
    if env.get("MODEL_GATEWAY_URL"):
        real = OpenAIGateway(
            GatewayConfig(
                base_url=env["MODEL_GATEWAY_URL"],
                model=model,
                allowed_hosts=env.get("MODEL_GATEWAY_ALLOWED_HOSTS", "").split(","),
                api_key=env.get("MODEL_GATEWAY_API_KEY") or None,
                timeout_seconds=float(env.get("MODEL_GATEWAY_TIMEOUT", "300")),
            )
        )
    if recordings and mode in ("replay", "record"):
        return RecordedGateway(Path(recordings), model or "recorded", mode=mode, inner=real)  # type: ignore[arg-type]
    return real or NullGateway()
