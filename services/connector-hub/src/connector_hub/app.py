"""FastAPI application for the connector-hub service."""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Canadian AI Governance Hub - Connector hub", version="0.1.0")


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}
