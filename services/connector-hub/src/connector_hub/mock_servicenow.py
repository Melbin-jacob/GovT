"""Mock ServiceNow Table API, for tests, CI and the demo only. Never for production.

Implements the subset the connector uses, with ServiceNow's shapes:

- ``GET /api/now/table/{table}`` with ``sysparm_query`` (``field=value``, ``field!=value``,
  ``fieldSTARTSWITHvalue``, ``ORDERBYfield``, joined by ``^``), ``sysparm_fields`` (with
  one level of dot-walking, e.g. ``owned_by.email``), ``sysparm_display_value``
  (``false``/``true``/``all``), ``sysparm_limit`` and ``sysparm_offset``;
  ``X-Total-Count`` header.
- ``GET/PATCH/PUT /api/now/table/{table}/{sys_id}``, ``POST /api/now/table/{table}``.
- Basic auth against the seed's accounts; per-table read/write roles mimic the ACLs from
  docs/servicenow-setup.md; journal fields (``work_notes``) append instead of replace.
- ``/__mock/*``: health, reset, a "hibernating" switch, and a state dump for tests.
"""

from __future__ import annotations

import base64
import copy
import json
import secrets
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

HIBERNATING_PAGE = (
    "<html><head><title>Instance Hibernating page</title></head>"
    "<body>Your instance is hibernating. Log in to wake it up.</body></html>"
)
_NUMBER_PREFIX = {"u_govhub_task": "GOVT"}
# Module level: with postponed annotations FastAPI cannot resolve a function-local alias.
Auth = Annotated[str | None, Header(alias="Authorization")]


class MockServiceNow:
    def __init__(self, seed: dict[str, Any]) -> None:
        self.seed = seed
        self.reset()

    def reset(self) -> None:
        self.tables: dict[str, list[dict[str, Any]]] = copy.deepcopy(self.seed["tables"])
        self.accounts: dict[str, dict[str, Any]] = self.seed["accounts"]
        self.acls: dict[str, dict[str, list[str]]] = self.seed.get("acls", {})
        self.display_fields: dict[str, str] = self.seed.get("display_fields", {})
        self.references: dict[str, dict[str, str]] = self.seed.get("references", {})
        self.journal_fields: set[str] = set(self.seed.get("journal_fields", []))
        self.hibernating = False
        self.counter = 0
        self.requests: list[dict[str, Any]] = []

    # --- auth and ACLs -------------------------------------------------------------------

    def authenticate(self, header: str | None) -> dict[str, Any] | None:
        if not header or not header.startswith("Basic "):
            return None
        try:
            user, _, password = base64.b64decode(header[6:]).decode().partition(":")
        except ValueError:
            return None
        account = self.accounts.get(user)
        if account and secrets.compare_digest(account["password"], password):
            return {"user": user, "roles": set(account["roles"])}
        return None

    def allowed(self, table: str, roles: set[str], operation: str) -> bool:
        acl = self.acls.get(table)
        if acl is None:
            return operation == "read"
        return bool(roles & set(acl[operation]))

    # --- records -------------------------------------------------------------------------

    def find(self, table: str, sys_id: str) -> dict[str, Any] | None:
        return next((r for r in self.tables.get(table, []) if r["sys_id"] == sys_id), None)

    def display(self, table: str, record: dict[str, Any], field: str) -> str:
        value = record.get(field, "")
        if field in self.journal_fields:
            return "\n\n".join(reversed(value)) if isinstance(value, list) else str(value)
        ref_table = self.references.get(table, {}).get(field)
        if ref_table and value:
            target = self.find(ref_table, str(value))
            return (
                str(target.get(self.display_fields.get(ref_table, "sys_id"), "")) if target else ""
            )
        return "" if value is None else str(value)

    def raw(self, table: str, record: dict[str, Any], field: str) -> str:
        value = record.get(field, "")
        if field in self.journal_fields:
            return self.display(table, record, field)
        return "" if value is None else str(value)

    def resolve(self, table: str, record: dict[str, Any], path: str) -> tuple[str, str]:
        """(value, display value) of a field, with one level of dot-walking."""
        if "." in path:
            ref_field, sub_field = path.split(".", 1)
            ref_table = self.references.get(table, {}).get(ref_field)
            target = self.find(ref_table, str(record.get(ref_field, ""))) if ref_table else None
            if target is None or ref_table is None:
                return "", ""
            return self.raw(ref_table, target, sub_field), self.display(
                ref_table, target, sub_field
            )
        return self.raw(table, record, path), self.display(table, record, path)

    def render(
        self, table: str, record: dict[str, Any], fields: list[str] | None, display: str
    ) -> dict[str, Any]:
        names = fields or [k for k in record if not k.startswith("_")]
        out: dict[str, Any] = {}
        for name in names:
            value, shown = self.resolve(table, record, name)
            if display == "all":
                out[name] = {"value": value, "display_value": shown}
            elif display == "true":
                out[name] = shown
            else:
                out[name] = value
        return out

    def matches(self, table: str, record: dict[str, Any], query: str) -> bool:
        for clause in filter(None, query.split("^")):
            if clause.startswith(("ORDERBY", "ORDERBYDESC")):
                continue
            for op in ("!=", "STARTSWITH", "="):
                if op in clause:
                    field, value = clause.split(op, 1)
                    actual, _ = self.resolve(table, record, field)
                    ok = {
                        "!=": actual != value,
                        "STARTSWITH": actual.startswith(value),
                        "=": actual == value,
                    }[op]
                    if not ok:
                        return False
                    break
        return True

    def order(self, table: str, rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
        for clause in reversed([c for c in query.split("^") if c.startswith("ORDERBY")]):
            desc = clause.startswith("ORDERBYDESC")
            field = clause.removeprefix("ORDERBYDESC" if desc else "ORDERBY")
            rows = sorted(rows, key=lambda r: self.resolve(table, r, field)[0], reverse=desc)
        return rows

    def write(self, table: str, record: dict[str, Any], values: dict[str, Any]) -> None:
        for key, value in values.items():
            if key in self.journal_fields:
                if value:
                    record.setdefault(key, [])
                    record[key].append(str(value))
            elif key not in ("sys_id", "number", "sys_created_on"):
                record[key] = "" if value is None else value

    def insert(self, table: str, values: dict[str, Any]) -> dict[str, Any]:
        self.counter += 1
        record: dict[str, Any] = {
            "sys_id": uuid.uuid5(uuid.NAMESPACE_URL, f"mock/{table}/{self.counter}").hex,
            "number": f"{_NUMBER_PREFIX.get(table, 'MOCK')}{self.counter:07d}",
            "state": "1",
        }
        self.write(table, record, values)
        self.tables.setdefault(table, []).append(record)
        return record


def _error(status: int, message: str, detail: str = "") -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"message": message, "detail": detail}, "status": "failure"},
    )


def create_app(seed_path: str | Path | None = None, seed: dict[str, Any] | None = None) -> FastAPI:
    if seed is None:
        path = Path(seed_path or "data/demo/servicenow/seed.json")
        seed = json.loads(path.read_text(encoding="utf-8"))
    state = MockServiceNow(seed)
    app = FastAPI(title="Mock ServiceNow (tests and demo only)")
    app.state.mock = state

    def guard(table: str, auth: str | None, operation: str) -> Response | dict[str, Any]:
        if state.hibernating:
            return HTMLResponse(HIBERNATING_PAGE)
        account = state.authenticate(auth)
        if account is None:
            return _error(401, "User Not Authenticated", "Required to provide Auth information")
        if table not in state.tables:
            return _error(400, "Invalid table", f"Invalid table {table}")
        if not state.allowed(table, account["roles"], operation):
            return _error(403, "User Not Authorized", f"{operation} access to {table} denied")
        return account

    @app.get("/__mock/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/__mock/reset")
    def reset() -> dict[str, str]:
        state.reset()
        return {"status": "reset"}

    @app.post("/__mock/hibernate")
    def hibernate(on: bool = True) -> dict[str, bool]:
        state.hibernating = on
        return {"hibernating": on}

    @app.get("/__mock/tables/{table}")
    def dump(table: str) -> list[dict[str, Any]]:
        return state.tables.get(table, [])

    @app.get("/api/now/table/{table}")
    def list_records(
        table: str,
        authorization: Auth = None,
        sysparm_query: str = "",
        sysparm_fields: str = "",
        sysparm_display_value: str = "false",
        sysparm_limit: int = 10000,
        sysparm_offset: int = 0,
    ) -> Response:
        checked = guard(table, authorization, "read")
        if isinstance(checked, Response):
            return checked
        rows = [r for r in state.tables[table] if state.matches(table, r, sysparm_query)]
        rows = state.order(table, rows, sysparm_query)
        page = rows[sysparm_offset : sysparm_offset + sysparm_limit]
        fields = [f for f in sysparm_fields.split(",") if f] or None
        result = [state.render(table, r, fields, sysparm_display_value) for r in page]
        return JSONResponse({"result": result}, headers={"X-Total-Count": str(len(rows))})

    @app.get("/api/now/table/{table}/{sys_id}")
    def get_record(
        table: str, sys_id: str, authorization: Auth = None, sysparm_display_value: str = "false"
    ) -> Response:
        checked = guard(table, authorization, "read")
        if isinstance(checked, Response):
            return checked
        record = state.find(table, sys_id)
        if record is None:
            return _error(404, "No Record found", "Record doesn't exist or ACL restricts it")
        return JSONResponse({"result": state.render(table, record, None, sysparm_display_value)})

    @app.post("/api/now/table/{table}", status_code=201)
    async def create_record(table: str, request: Request, authorization: Auth = None) -> Response:
        checked = guard(table, authorization, "write")
        if isinstance(checked, Response):
            return checked
        values = await request.json()
        record = state.insert(table, values)
        state.requests.append({"method": "POST", "table": table, "values": values})
        return JSONResponse({"result": state.render(table, record, None, "false")}, status_code=201)

    async def _update(table: str, sys_id: str, request: Request, auth: str | None) -> Response:
        checked = guard(table, auth, "write")
        if isinstance(checked, Response):
            return checked
        record = state.find(table, sys_id)
        if record is None:
            return _error(404, "No Record found", "Record doesn't exist or ACL restricts it")
        values = await request.json()
        state.write(table, record, values)
        state.requests.append(
            {"method": "PATCH", "table": table, "sys_id": sys_id, "values": values}
        )
        return JSONResponse({"result": state.render(table, record, None, "false")})

    @app.patch("/api/now/table/{table}/{sys_id}")
    async def patch_record(
        table: str, sys_id: str, request: Request, authorization: Auth = None
    ) -> Response:
        return await _update(table, sys_id, request, authorization)

    @app.put("/api/now/table/{table}/{sys_id}")
    async def put_record(
        table: str, sys_id: str, request: Request, authorization: Auth = None
    ) -> Response:
        return await _update(table, sys_id, request, authorization)

    return app
