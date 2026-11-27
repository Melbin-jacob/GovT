"""FastAPI application for the connector hub (internal network only)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from connector_hub import inventory
from connector_hub.config import get_settings
from connector_hub.mapping import Mapping, load_mapping
from connector_hub.servicenow import (
    ConnectorConfigError,
    ServiceNowClient,
    ServiceNowError,
    load_config,
)
from connector_hub.tasks import TaskWriter

app = FastAPI(title="Canadian AI Governance Hub - Connector hub", version="0.1.0")


def get_client() -> ServiceNowClient:
    """Overridden in tests. Configuration is read per request so health works without it."""
    return ServiceNowClient(load_config())


def get_mapping() -> Mapping:
    return load_mapping(Path(get_settings().mapping_path))


Client = Annotated[ServiceNowClient, Depends(get_client)]
MappingDep = Annotated[Mapping, Depends(get_mapping)]


@app.exception_handler(ConnectorConfigError)
def _config_error(_request: Request, exc: ConnectorConfigError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(ServiceNowError)
def _servicenow_error(_request: Request, exc: ServiceNowError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.get("/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/inventory/sync", tags=["inventory"])
def sync_inventory(client: Client, mapping: MappingDep, dry_run: bool = False) -> dict[str, Any]:
    """Pull the AI systems from ServiceNow, push them to the rulebook as a new inventory
    snapshot, and create/update/close data-gap tasks. ``dry_run`` only pulls."""
    result = inventory.pull_inventory(client, mapping)
    summary: dict[str, Any] = {
        "source": f"servicenow:{client.config.host}",
        "systems": len(result.systems),
        "rejected": result.rejected,
        "data_gaps": result.gaps,
    }
    if dry_run:
        summary["preview"] = result.systems
        return summary
    summary["rulebook"] = inventory.push_to_rulebook(
        get_settings().rulebook_url, result, summary["source"]
    )
    writer = TaskWriter(client, mapping)
    summary["data_gap_tasks"] = inventory.sync_data_gap_tasks(writer, result)
    summary["warnings"] = writer.warnings
    return summary
