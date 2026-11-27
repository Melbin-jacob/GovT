"""Mock ServiceNow Table API, for tests, CI and the demo only. Never for production.

TODO(connector-hub): implemented in the next commit.
"""

from __future__ import annotations

from fastapi import FastAPI


def create_app(seed_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Mock ServiceNow (tests and demo only)")

    @app.get("/__mock/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app
