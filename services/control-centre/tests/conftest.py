"""Control-centre page tests: the app with fake hub services (no database needed)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from cc_support import FakeHub
from fastapi.testclient import TestClient

from control_centre.app import app
from control_centre.web import get_backends


@pytest.fixture
def hub() -> FakeHub:
    return FakeHub()


@pytest.fixture
def ui(hub: FakeHub) -> Iterator[TestClient]:
    app.dependency_overrides[get_backends] = hub.backends
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
