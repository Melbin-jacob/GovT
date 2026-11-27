"""Model gateway: self-hosted OpenAI-compatible client, host allowlist, recordings."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import httpx
import pytest

from govhub_shared.model_gateway import (
    ChatMessage,
    ChatRequest,
    GatewayConfig,
    GatewayError,
    NullGateway,
    OpenAIGateway,
    RecordedGateway,
    gateway_from_env,
    recording_key,
)

SECRET_EVIDENCE = "Applicant SIN 046 454 286 appears in this passage"
CONFIG = GatewayConfig(
    base_url="http://model.internal:8080", model="qwen3-8b", allowed_hosts=["model.internal"]
)
REQUEST = ChatRequest(
    task="assess-judgment-check",
    messages=[
        ChatMessage(role="system", content="Return JSON."),
        ChatMessage(role="user", content=SECRET_EVIDENCE),
    ],
    json_schema={"type": "object", "properties": {"verdict": {"type": "string"}}},
)


def completion(content: str = '{"verdict": "met"}') -> dict[str, Any]:
    return {
        "model": "qwen3-8b-q4",
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "logprobs": {
                    "content": [
                        {
                            "token": "met",
                            "logprob": -0.1,
                            "top_logprobs": [
                                {"token": "met", "logprob": -0.1},
                                {"token": "not", "logprob": -2.5},
                            ],
                        }
                    ]
                },
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 9},
    }


def gateway(handler: Any) -> tuple[OpenAIGateway, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)  # type: ignore[no-any-return]

    http = httpx.Client(base_url=CONFIG.base_url, transport=httpx.MockTransport(record))
    return OpenAIGateway(CONFIG, http=http), seen


def test_request_is_deterministic_structured_and_asks_for_logprobs() -> None:
    gw, seen = gateway(lambda r: httpx.Response(200, json=completion()))
    reply = gw.chat(REQUEST)
    (sent,) = seen
    assert sent.url.path == "/v1/chat/completions"
    body = json.loads(sent.content)
    assert body["temperature"] == 0 and body["seed"] == 7 and body["model"] == "qwen3-8b"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["logprobs"] is True and body["top_logprobs"] == 5
    assert reply.content == '{"verdict": "met"}'
    assert reply.model_id == "qwen3-8b-q4"
    assert reply.logprobs is not None and reply.logprobs[0].top[1] == ("not", -2.5)
    assert (reply.prompt_tokens, reply.completion_tokens) == (120, 9)


def test_host_not_in_allowlist_is_refused() -> None:
    with pytest.raises(GatewayError, match="not in MODEL_GATEWAY_ALLOWED_HOSTS"):
        OpenAIGateway(CONFIG.model_copy(update={"base_url": "https://api.example.com"}))
    with pytest.raises(GatewayError, match="http"):
        OpenAIGateway(CONFIG.model_copy(update={"base_url": "file:///etc/passwd"}))


def test_redirects_are_not_followed() -> None:
    gw = OpenAIGateway(CONFIG)
    assert gw.http.follow_redirects is False


def test_retries_server_errors_then_gives_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("govhub_shared.model_gateway.time.sleep", lambda _s: None)
    calls = iter([httpx.Response(503), httpx.Response(200, json=completion())])
    gw, seen = gateway(lambda r: next(calls))
    assert gw.chat(REQUEST).content
    assert len(seen) == 2
    gw, seen = gateway(lambda r: httpx.Response(502))
    with pytest.raises(GatewayError, match="unreachable"):
        gw.chat(REQUEST)
    assert len(seen) == 3


def test_bad_replies_raise() -> None:
    gw, _ = gateway(lambda r: httpx.Response(400, json={"error": "bad"}))
    with pytest.raises(GatewayError, match="refused"):
        gw.chat(REQUEST)
    gw, _ = gateway(lambda r: httpx.Response(200, json={"nope": 1}))
    with pytest.raises(GatewayError, match="not an OpenAI chat completion"):
        gw.chat(REQUEST)


def test_message_content_is_never_logged(caplog: pytest.LogCaptureFixture) -> None:
    gw, _ = gateway(lambda r: httpx.Response(200, json=completion()))
    with caplog.at_level(logging.DEBUG):
        gw.chat(REQUEST)
    assert "assess-judgment-check" in caplog.text
    assert "SIN" not in caplog.text and "verdict" not in caplog.text


def test_record_then_replay(tmp_path: Path) -> None:
    gw, seen = gateway(lambda r: httpx.Response(200, json=completion()))
    recorder = RecordedGateway(tmp_path, "qwen3-8b", mode="record", inner=gw)
    original = recorder.chat(REQUEST)
    replay = RecordedGateway(tmp_path, "qwen3-8b")
    again = replay.chat(REQUEST)
    assert again.content == original.content and again.recorded is True
    assert len(seen) == 1  # the replay made no call
    assert replay.path(REQUEST).name == f"{recording_key('qwen3-8b', REQUEST)}.json"
    other = REQUEST.model_copy(update={"task": "other"})
    with pytest.raises(GatewayError, match="no recorded reply"):
        replay.chat(other)


def test_gateway_from_env() -> None:
    assert isinstance(gateway_from_env({}), NullGateway)
    with pytest.raises(GatewayError):
        NullGateway().chat(REQUEST)
    live = gateway_from_env(
        {
            "MODEL_GATEWAY_URL": "http://model.internal:8080",
            "MODEL_GATEWAY_MODEL": "qwen3-8b",
            "MODEL_GATEWAY_ALLOWED_HOSTS": "model.internal",
        }
    )
    assert isinstance(live, OpenAIGateway)
    replay = gateway_from_env(
        {"MODEL_GATEWAY_RECORDINGS": "recordings", "MODEL_GATEWAY_MODEL": "m"}
    )
    assert isinstance(replay, RecordedGateway) and replay.mode == "replay"
