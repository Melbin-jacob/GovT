"""Helpers for tests: a ServiceNowClient wired to an in-process mock ServiceNow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from connector_hub.mock_servicenow import create_app
from connector_hub.servicenow import ServiceNowClient, ServiceNowConfig
from govhub_shared.auth import GOVERNANCE_OFFICER
from govhub_shared.auth.testing import DefaultCaller, user

REPO = Path(__file__).resolve().parents[3]
SEED = REPO / "data" / "demo" / "servicenow" / "seed.json"
MOCK_URL = "http://mock-servicenow"


def mock_config(
    username: str = "govhub.integration", password: str = "mock-only-password"
) -> ServiceNowConfig:
    return ServiceNowConfig(
        instance_url=MOCK_URL,
        username=username,
        password=password,
        allowed_hosts=("mock-servicenow",),
        allow_insecure_http=True,
    )


def mock_client(app: FastAPI | None = None, **kwargs: str) -> tuple[ServiceNowClient, FastAPI]:
    app = app or create_app(SEED)
    http = TestClient(app, base_url=MOCK_URL)
    return ServiceNowClient(mock_config(**kwargs), http=http, sleep=lambda _s: None), app


# Test clients of connector-hub act as one person with every role in the fictional
# tenants unless a test sends its own caller.
TENANTS = ["agency-sample-benefits", "dept-example-services", "office-fictional-permits"]
EVERYONE = user(
    "test-user", platform=(GOVERNANCE_OFFICER,), reviewer=TENANTS, tenant_admin=TENANTS,
    auditor=TENANTS,
)  # fmt: skip


def signed(client: Any) -> Any:
    client.auth = DefaultCaller(EVERYONE, "connector-hub")
    return client
