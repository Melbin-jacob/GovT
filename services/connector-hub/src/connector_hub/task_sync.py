"""Turn rulebook impact-report tasks (and review-desk requests) into ServiceNow tasks."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from connector_hub.tasks import TaskWriter

TaskType = Literal["reassessment", "remediation", "evidence-request", "data-gap", "smoke"]


def servicenow_due(date_text: str | None) -> str:
    """Hub due dates are dates; ServiceNow due_date is a date-time (end of that day).
    Set the integration user's time zone to UTC (docs/servicenow-setup.md)."""
    return f"{date_text} 23:59:59" if date_text else ""


class TaskRequest(BaseModel):
    """A task another hub service wants in ServiceNow (generic form)."""

    correlation_id: str = Field(min_length=1, max_length=100)
    type: TaskType
    short_description: str = Field(min_length=1, max_length=160)
    description: str = ""
    tenant: str | None = None
    owner_email: str | None = None
    system_id: str | None = None
    priority: int = Field(default=3, ge=1, le=4)
    due_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    reference: str = ""
    note: str | None = None


def upsert_request(writer: TaskWriter, request: TaskRequest) -> dict[str, Any]:
    action, record = writer.upsert(
        request.correlation_id,
        {
            "short_description": request.short_description,
            "description": request.description,
            "assignment_group": writer.group(request.tenant),
            "assigned_to": writer.user(request.owner_email),
            "cmdb_ci": writer.ci(request.system_id),
            "priority": str(request.priority),
            "due_date": servicenow_due(request.due_date),
            "state": writer.mapping.task_states["open"],
            "type": request.type,
            "reference": request.reference,
        },
        note=request.note,
    )
    return {"correlation_id": request.correlation_id, "action": action, **record}


def sync_impact_report(writer: TaskWriter, report: dict[str, Any]) -> dict[str, Any]:
    """One ServiceNow task per impact-report task (matched by its task_id)."""
    report_id = str(report.get("report_id", ""))
    results = []
    for task in report.get("tasks", []):
        request = TaskRequest(
            correlation_id=task["task_id"],
            type="reassessment",
            short_description=task["short_description"][:160],
            description=f"{task['description']}\n\nDue date basis: {task['due_date_basis']}",
            tenant=task.get("assignment_group"),
            owner_email=task.get("assigned_to"),
            system_id=task.get("system_id"),
            priority=int(task.get("priority", 3)),
            due_date=task.get("due_date"),
            reference=report_id,
            note=f"GovHub impact report {report_id}",
        )
        results.append({"task_id": task["task_id"], **upsert_request(writer, request)})
    return {"report_id": report_id, "tasks": results, "warnings": list(writer.warnings)}
