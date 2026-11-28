"""govhub_shared.tenancy without a database: scopes, validation, widening. The policies
themselves are tested against PostgreSQL in each service's tests/test_tenant_isolation.py."""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session
from starlette.requests import Request

from govhub_shared import tenancy
from govhub_shared.auth import AUDITOR, GOVERNANCE_OFFICER, REVIEWER
from govhub_shared.auth.principal import Principal
from govhub_shared.auth.testing import service, user


def _principal(who: object) -> Principal:
    assert isinstance(who, Principal)
    return who


def test_scope_of_each_kind_of_caller() -> None:
    reviewer = _principal(user("rv", reviewer=["t-a"], auditor=["t-b"]))
    assert tenancy.visible(reviewer, REVIEWER) == {"t-a"}
    assert tenancy.visible(reviewer, REVIEWER, AUDITOR) == {"t-a", "t-b"}
    officer = _principal(user("go", platform=(GOVERNANCE_OFFICER,)))
    assert tenancy.visible(officer, REVIEWER) == frozenset()  # platform role: no tenant
    assert tenancy.visible(_principal(service("connector-hub", all_tenants=True))) is None
    assert tenancy.visible(_principal(service("connector-hub"))) == frozenset()
    assert tenancy.visible(None, REVIEWER) == frozenset()  # no caller: nothing


@pytest.mark.parametrize("bad", ["a,b", "", "x y", "'; DROP", "-leading"])
def test_tenant_ids_that_could_break_the_setting_are_refused(bad: str) -> None:
    with pytest.raises(ValueError, match="not a tenant ID"):
        tenancy.bind(Session(), frozenset({bad}))


def test_widened_returns_to_the_callers_scope_even_after_an_error() -> None:
    s = Session()
    tenancy.bind(s, frozenset({"t-a"}))
    with tenancy.widened(s, tenancy.ALL_TENANTS):
        assert tenancy.scope_of(s) is None
    assert tenancy.scope_of(s) == {"t-a"}
    with pytest.raises(RuntimeError), tenancy.widened(s, tenancy.ALL_TENANTS):
        raise RuntimeError
    assert tenancy.scope_of(s) == {"t-a"}


def test_an_unbound_session_has_no_tenants() -> None:
    assert tenancy.scope_of(Session()) == frozenset()


def test_policy_sql_takes_plain_table_names_only() -> None:
    assert tenancy.policy_sql("findings")[0] == "ALTER TABLE findings ENABLE ROW LEVEL SECURITY"
    assert not any("FORCE" in s for s in tenancy.policy_sql("findings"))
    with pytest.raises(ValueError, match="not a table name"):
        tenancy.policy_sql("findings; DROP TABLE x")


def test_probes_without_a_token_have_no_caller() -> None:
    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/ready"})
    assert tenancy.caller_or_none(request) is None
