"""The scripted fake model server answers the real HTTP gateway exactly like the replay."""

from __future__ import annotations

from ae_support import REPO
from fastapi.testclient import TestClient

from assessment_engine import harness
from assessment_engine.controls import FileControls
from assessment_engine.fake_model import app
from assessment_engine.settings_file import load_config
from govhub_shared.model_gateway import GatewayConfig, OpenAIGateway


def test_real_gateway_against_the_fake_model_server(monkeypatch: object) -> None:
    config = GatewayConfig(
        base_url="http://fake-model:8000", model="scripted-fake-v1", allowed_hosts=["fake-model"]
    )
    gateway = OpenAIGateway(config, http=TestClient(app))
    cases = {
        c.case_id: c for c in harness.load_cases(REPO / "data/accuracy/synthetic-demo/cases.csv")
    }
    kwargs = {
        "gateway": gateway,
        "source": FileControls(REPO / "data/demo/catalogs"),
        "rules_dir": REPO / "data/rules",
        "config": load_config(REPO / "data/config/assessment.toml"),
    }
    partial = harness.run_case(cases["SYN-EN-02"], **kwargs)  # type: ignore[arg-type]
    assert (partial.verdict, partial.model_id) == ("partially-met", "scripted-fake-v1")
    assert partial.token_confidence == 0.79  # log-probabilities came over HTTP
    injected = harness.run_case(cases["SYN-FR-06"], **kwargs)  # type: ignore[arg-type]
    assert (injected.model_verdict, injected.verdict) == ("met", "unable-to-determine")


def test_unknown_requests_are_refused() -> None:
    client = TestClient(app)
    body = {"model": "x", "messages": [{"role": "user", "content": "hi"}]}
    assert client.post("/v1/chat/completions", json=body).status_code == 404
    assert "no real model" in client.get("/health").json()["model"]
