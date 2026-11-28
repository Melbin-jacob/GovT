"""connector-hub test setup: trust the test keys; test clients act as one person with
every role in the fictional tenants unless a test sends its own caller."""

from __future__ import annotations

from connector_hub.app import app
from govhub_shared.auth.testing import KEYS
from govhub_shared.auth.web import install

install(app, "connector-hub", KEYS.trust)
