"""FastAPI application for the connector hub (internal network only)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request
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
from connector_hub.task_sync import TaskRequest, sync_impact_report, upsert_request
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


@app.post("/tasks/sync-impact-report", tags=["tasks"])
def sync_report_tasks(
    client: Client,
    mapping: MappingDep,
    report: Annotated[dict[str, Any], Body(description="A rulebook impact report")],
) -> dict[str, Any]:
    """Create or update one ServiceNow task per impact-report task. Idempotent: tasks are
    matched by the report's task_id (stored as correlation_id); a re-sync never reopens a
    task someone has moved on."""
    return sync_impact_report(TaskWriter(client, mapping), report)


@app.post("/tasks", tags=["tasks"])
def upsert_task(client: Client, mapping: MappingDep, request: TaskRequest) -> dict[str, Any]:
    """Create or update a single hub task (used by review-desk for remediation and
    evidence requests)."""
    writer = TaskWriter(client, mapping)
    return {**upsert_request(writer, request), "warnings": writer.warnings}


@app.post("/tasks/{correlation_id}/notes", tags=["tasks"])
def add_note(
    correlation_id: str,
    client: Client,
    mapping: MappingDep,
    text: Annotated[str, Body(embed=True, min_length=1)],
    state: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, Any]:
    """Append a work note; optionally set the state by name (e.g. closed_complete)."""
    if state is not None and state not in mapping.task_states:
        raise HTTPException(422, f"unknown state {state!r}; one of {sorted(mapping.task_states)}")
    try:
        return TaskWriter(client, mapping).note(correlation_id, text, state)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
