"""ServiceNow configuration and client, against the mock (never a real instance in CI)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from mock_support import REPO, mock_client, mock_config

from connector_hub.servicenow import (
    ConnectorConfigError,
    ServiceNowAuthError,
    ServiceNowClient,
    ServiceNowError,
    ServiceNowUnavailableError,
    display,
    load_config,
    value,
)

ENV = {
    "SERVICENOW_INSTANCE_URL": "https://dev00000.service-now.com",
    "SERVICENOW_USERNAME": "govhub.integration",
    "SERVICENOW_PASSWORD": "secret-value",
    "CONNECTOR_ALLOWED_HOSTS": "dev00000.service-now.com",
    "SERVICENOW_ENV_FILE": "/nonexistent",
}


# --- configuration ---------------------------------------------------------------------


def test_config_from_environment() -> None:
    config = load_config(ENV)
    assert config.host == "dev00000.service-now.com"
    assert "secret-value" not in repr(config)  # never shown in logs or errors


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"SERVICENOW_PASSWORD": ""}, "SERVICENOW_PASSWORD"),
        ({"SERVICENOW_INSTANCE_URL": "http://dev00000.service-now.com"}, "must use https"),
        ({"CONNECTOR_ALLOWED_HOSTS": "other.example"}, "not in CONNECTOR_ALLOWED_HOSTS"),
        ({"SERVICENOW_INSTANCE_URL": "not a url"}, "not a URL"),
    ],
)
def test_config_errors(changes: dict[str, str], message: str) -> None:
    with pytest.raises(ConnectorConfigError, match=message):
        load_config({**ENV, **changes})


def test_config_from_local_file_and_env_wins(tmp_path: Path) -> None:
    env_file = tmp_path / ".env.servicenow"
    env_file.write_text(
        "# local only\nSERVICENOW_INSTANCE_URL=https://dev11111.service-now.com\n"
        "SERVICENOW_USERNAME=from-file\nSERVICENOW_PASSWORD='file-secret'\n"
        "CONNECTOR_ALLOWED_HOSTS=dev11111.service-now.com\n",
        encoding="utf-8",
    )
    config = load_config({"SERVICENOW_ENV_FILE": str(env_file)})
    assert (config.username, config.password) == ("from-file", "file-secret")
    overridden = load_config({"SERVICENOW_ENV_FILE": str(env_file), "SERVICENOW_USERNAME": "env"})
    assert overridden.username == "env"


def test_local_credentials_file_is_gitignored() -> None:
    result = subprocess.run(["git", "check-ignore", "-q", ".env.servicenow"], cwd=REPO, check=False)
    assert result.returncode == 0


# --- client against the mock -----------------------------------------------------------


def test_query_with_display_values_and_dot_walk() -> None:
    client, _ = mock_client()
    rows = client.query(
        "cmdb_ci_business_app",
        "correlation_id=SYS-001",
        ["correlation_id", "name", "owned_by", "owned_by.email", "u_aia_impact_level"],
    )
    (row,) = rows
    assert value(row, "correlation_id") == "SYS-001"
    assert display(row, "owned_by") == "Director, Example Benefits Program"
    assert len(value(row, "owned_by")) == 32  # sys_id
    assert value(row, "owned_by.email") == "benefits.owner@example.invalid"


def test_paging_filters_and_order() -> None:
    client, _ = mock_client()
    rows = client.query(
        "cmdb_ci_business_app",
        "correlation_idSTARTSWITHSYS-^ORDERBYDESCcorrelation_id",
        ["correlation_id"],
        page_size=2,
    )
    assert [value(r, "correlation_id") for r in rows][:3] == ["SYS-009", "SYS-008", "SYS-007"]
    assert len(rows) == 9
    assert client.query(
        "cmdb_ci_business_app",
        "install_status!=Retired^install_status!=Installed",
        ["correlation_id"],
    )


def test_create_update_and_journal_fields() -> None:
    client, _ = mock_client()
    created = client.create(
        "u_govhub_task",
        {"short_description": "Reassess", "correlation_id": "IMP-1", "work_notes": "first"},
    )
    assert created["number"].startswith("GOVT")
    client.update("u_govhub_task", created["sys_id"], {"work_notes": "second", "state": "2"})
    (row,) = client.query("u_govhub_task", "correlation_id=IMP-1", ["work_notes", "state"])
    assert display(row, "work_notes") == "second\n\nfirst"  # newest first, like ServiceNow
    assert value(row, "state") == "2"
    assert client.find_one("u_govhub_task", "correlation_id=IMP-404") is None


def test_authentication_and_acls() -> None:
    bad, _ = mock_client(password="wrong")
    with pytest.raises(ServiceNowAuthError, match="401"):
        bad.query("cmdb_ci_business_app")
    readonly, _ = mock_client(username="readonly.tester")
    assert readonly.query("cmdb_ci_business_app", "correlation_id=SYS-001")
    with pytest.raises(ServiceNowAuthError, match="roles and the table ACLs"):
        readonly.create("u_govhub_task", {"short_description": "x"})


def test_unknown_table_and_hibernation() -> None:
    client, app = mock_client()
    with pytest.raises(ServiceNowError, match="Invalid table"):
        client.query("no_such_table")
    app.state.mock.hibernating = True
    with pytest.raises(ServiceNowUnavailableError, match="hibernating"):
        client.query("cmdb_ci_business_app")


def test_retries_then_succeeds_and_gives_up() -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": {"message": "busy"}})
        return httpx.Response(200, json={"result": []})

    http = httpx.Client(base_url="http://mock-servicenow", transport=httpx.MockTransport(flaky))
    client = ServiceNowClient(mock_config(), http=http, sleep=lambda _s: None)
    assert client.query("u_govhub_task") == []
    assert calls["n"] == 3

    always = httpx.Client(
        base_url="http://mock-servicenow",
        transport=httpx.MockTransport(lambda r: httpx.Response(503, json={"error": {}})),
    )
    with pytest.raises(ServiceNowError, match="503"):
        ServiceNowClient(mock_config(), http=always, sleep=lambda _s: None).query("u_govhub_task")


def test_client_refuses_unlisted_host() -> None:
    config = mock_config()
    bad = type(config)(
        instance_url="http://elsewhere",
        username="u",
        password="p",
        allowed_hosts=("mock-servicenow",),
        allow_insecure_http=True,
    )
    with pytest.raises(ConnectorConfigError):
        ServiceNowClient(bad)


def test_seed_is_current() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/make_servicenow_seed.py", "--check"], cwd=REPO, check=False
    )
    assert result.returncode == 0, "run python3 scripts/make_servicenow_seed.py"
