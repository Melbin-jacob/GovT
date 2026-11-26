"""Impact report: from a rule change to the systems and tasks it affects.

Triggers (either or both):

- a **source change**: two versions of the official text. The clause diff finds changed,
  split, merged, removed and added clauses; ``source-clause`` links map them to controls.
- a **catalog change**: two catalog versions (controls edited directly, no source change).
  Changed and added controls are affected with reason "control changed" / "control added".

Each system's checks in scope are its profiles resolved against the report's catalog
version. Affected (system, control) pairs are findings that need re-review. Output is
deterministic for the same inputs: no clock is read and the report ID is a content hash.

Nothing is sent anywhere: the tasks are returned as JSON shaped like ServiceNow task
records. TODO(connector-hub): push them to ServiceNow ``sc_task`` (never ``incident``).
TODO(review-desk): persist reports and open findings in the review queue.
"""

from __future__ import annotations

import hashlib
import json
import tomllib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from govhub_shared import OSCAL_NS
from govhub_shared.oscal import (
    ControlView,
    ProfileResolutionError,
    iter_controls,
    resolve_profile,
)
from rulebook import inventory as inv
from rulebook import store
from rulebook.sources import store as source_store
from rulebook.sources.diff import (
    METHOD,
    SPLIT_THRESHOLD,
    THRESHOLD,
    SourceDiff,
    cross_check,
    diff_sources,
)

Lang = Literal["en", "fr"]
PRIORITY = {4: 1, 3: 2, 2: 3, 1: 4}  # ServiceNow priority: 1 = critical ... 4 = low


# --- request ---------------------------------------------------------------------------


class SourceTrigger(BaseModel):
    instrument: str
    from_version: str = Field(alias="from")
    to_version: str = Field(alias="to")


class CatalogTrigger(BaseModel):
    from_version: str = Field(alias="from")
    to_version: str = Field(alias="to")


class ImpactRequest(BaseModel):
    catalog: str = Field(description="Catalog name, e.g. dadm-section6")
    catalog_version: str | None = Field(
        default=None, description="Catalog version for links and scope (default: catalog_change.to)"
    )
    source: SourceTrigger | None = None
    catalog_change: CatalogTrigger | None = None
    as_of: date = Field(
        description="Reference date for due dates (the report never reads the clock)"
    )
    lang: Lang = Field(default="en", description="Language of control text in tasks")
    tenant: str | None = Field(default=None, description="Only systems of this tenant")

    @model_validator(mode="after")
    def _check(self) -> ImpactRequest:
        if self.source is None and self.catalog_change is None:
            raise ValueError("give a source change, a catalog_change, or both")
        if self.catalog_change is not None:
            if self.catalog_version is None:
                self.catalog_version = self.catalog_change.to_version
            elif self.catalog_version != self.catalog_change.to_version:
                raise ValueError("catalog_version must equal catalog_change.to")
        if self.catalog_version is None:
            raise ValueError("catalog_version is required with a source change only")
        return self


# --- due dates -------------------------------------------------------------------------


@dataclass(frozen=True)
class DueDatePolicy:
    default: dict[int, tuple[int, str]]
    tenants: dict[str, dict[int, tuple[int, str]]]
    path: str

    def due(self, tenant: str, level: int, as_of: date) -> tuple[date, str]:
        override = self.tenants.get(tenant, {}).get(level)
        days, status = override or self.default[level]
        scope = f"tenant {tenant} override" if override else "default"
        roman = inv.ROMAN_OF[level]
        return as_of + timedelta(days=days), f"{status}: level {roman} = {days} days ({scope})"


def load_due_dates(path: Path) -> DueDatePolicy:
    data = tomllib.loads(path.read_text(encoding="utf-8"))

    def table(raw: Mapping[str, Any], where: str) -> dict[int, tuple[int, str]]:
        out: dict[int, tuple[int, str]] = {}
        for key, entry in raw.items():
            level = int(key.removeprefix("level_"))
            if level not in inv.ROMAN_OF or not isinstance(entry.get("days"), int):
                raise ValueError(f"{path} [{where}] {key}: expected level_1..4 with integer days")
            out[level] = (entry["days"], str(entry.get("status", "UNSPECIFIED")))
        return out

    default = table(data.get("default", {}), "default")
    missing = sorted(set(inv.ROMAN_OF) - set(default))
    if missing:
        raise ValueError(f"{path} [default]: missing level(s) {missing}")
    tenants = {t: table(v, f"tenants.{t}") for t, v in data.get("tenants", {}).items()}
    return DueDatePolicy(default=default, tenants=tenants, path=str(path))


# --- affected controls -----------------------------------------------------------------


@dataclass
class Reason:
    trigger: Literal["source", "catalog"]
    kind: str
    detail: str
    flags: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "trigger": self.trigger,
            "kind": self.kind,
            "detail": self.detail,
            "flags": self.flags,
        }


@dataclass
class Findings:
    controls: dict[str, list[Reason]] = field(default_factory=lambda: defaultdict(list))
    maintenance: list[dict[str, Any]] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)

    def add(self, control_id: str, reason: Reason) -> None:
        self.controls[control_id].append(reason)


def _source_clauses(control: ControlView) -> list[str]:
    return [p.value for p in control.props if p.name == "source-clause" and p.ns == OSCAL_NS]


def _catalog_meta(doc: Mapping[str, Any], name: str) -> str | None:
    for prop in doc["catalog"]["metadata"].get("props", []):
        if prop.get("name") == name and prop.get("ns") == OSCAL_NS:
            return str(prop["value"])
    return None


def _source_findings(
    session: Session,
    request: ImpactRequest,
    catalog_doc: Mapping[str, Any],
    controls: list[ControlView],
    findings: Findings,
) -> dict[str, Any]:
    assert request.source is not None  # noqa: S101 - caller checks
    src = request.source
    linked_instrument = _catalog_meta(catalog_doc, "source-instrument")
    linked_version = _catalog_meta(catalog_doc, "source-version")
    if linked_instrument != src.instrument:
        raise store.InvalidCatalogError(
            f"catalog {request.catalog} {request.catalog_version} is linked to "
            f"{linked_instrument!r}, not {src.instrument!r}"
        )
    if linked_version not in (src.from_version, src.to_version):
        raise store.InvalidCatalogError(
            f"catalog source-clause links use {src.instrument} {linked_version}; the source "
            f"change must start or end there (got {src.from_version} -> {src.to_version})"
        )
    side: Literal["from", "to"] = "from" if linked_version == src.from_version else "to"

    diffs: dict[str, SourceDiff] = {}
    for lang in ("en", "fr"):
        try:
            diffs[lang] = diff_sources(
                source_store.get_source(session, src.instrument, src.from_version, lang),
                source_store.get_source(session, src.instrument, src.to_version, lang),
                include_text=False,
            )
        except store.NotFoundError:
            if lang == request.lang:
                raise
    diff = diffs[request.lang]
    divergences = (
        [d.model_dump(mode="json") for d in cross_check(diffs["en"], diffs["fr"])]
        if len(diffs) == 2
        else []
    )
    divergent = {d["clause"] for d in divergences}

    by_clause: dict[str, list[str]] = defaultdict(list)
    for control in controls:
        for clause in _source_clauses(control):
            by_clause[clause].append(control.id)

    def link_key(old: str, new: str) -> str:
        return old if side == "from" else new

    def hit(clause: str, reason: Reason) -> bool:
        ids = by_clause.get(clause, [])
        for cid in ids:
            extra = ["language-divergence"] if clause in divergent else []
            findings.add(
                cid, Reason(reason.trigger, reason.kind, reason.detail, reason.flags + extra)
            )
        return bool(ids)

    for pair in diff.pairs:
        if "split" in pair.flags or "merge" in pair.flags:
            continue  # handled with the split/merge group below
        key = link_key(pair.old, pair.new)
        if "text-changed" in pair.flags:
            flags = [f for f in pair.flags if f in ("obligation-change", "renumbered")]
            detail = f"clause {pair.old} -> {pair.new} changed (similarity {pair.score})"
            if not hit(key, Reason("source", "clause changed", detail, flags)):
                findings.maintenance.append(
                    {
                        "kind": "unmapped clause",
                        "clause": pair.new,
                        "detail": detail + "; no control is linked",
                    }
                )
        elif "renumbered" in pair.flags and side == "from" and by_clause.get(pair.old):
            findings.maintenance.append(
                {
                    "kind": "update clause reference",
                    "clause": pair.old,
                    "detail": f"text unchanged, renumbered {pair.old} -> {pair.new}",
                    "controls": sorted(by_clause[pair.old]),
                }
            )
    for split in diff.splits:
        detail = f"clause {split.old} split into {', '.join(split.into)}"
        keys = [split.old] if side == "from" else split.into
        if not any(
            [hit(k, Reason("source", "clause split", detail, list(split.flags))) for k in keys]
        ):
            findings.maintenance.append(
                {"kind": "unmapped clause", "clause": split.old, "detail": detail}
            )
    for merge in diff.merges:
        detail = f"clauses {', '.join(merge.olds)} merged into {merge.into}"
        keys = merge.olds if side == "from" else [merge.into]
        if not any(
            [hit(k, Reason("source", "clause merged", detail, list(merge.flags))) for k in keys]
        ):
            findings.maintenance.append(
                {"kind": "unmapped clause", "clause": merge.into, "detail": detail}
            )
    for old in diff.removed:
        detail = f"clause {old} removed in {src.to_version}"
        if side == "from" and not hit(old, Reason("source", "clause removed", detail)):
            findings.maintenance.append(
                {"kind": "removed clause had no control", "clause": old, "detail": detail}
            )
    for new in diff.added:
        detail = f"clause {new} added in {src.to_version}"
        if side == "from" or not hit(new, Reason("source", "clause added", detail)):
            findings.maintenance.append(
                {
                    "kind": "unmapped clause",
                    "clause": new,
                    "detail": detail + "; no control yet (draft one)",
                }
            )
    for d in divergences:
        findings.maintenance.append(
            {
                "kind": "language divergence",
                "clause": d["clause"],
                "detail": f"{d['kind']}: EN {d['en']} / FR {d['fr']}",
            }
        )
    return {
        "instrument": src.instrument,
        "from": src.from_version,
        "to": src.to_version,
        "catalog_links_use": f"{src.instrument} {linked_version} ({side} side)",
        "method": METHOD,
        "threshold": THRESHOLD,
        "split_threshold": SPLIT_THRESHOLD,
        "summary": diff.summary,
        "language_divergences": len(divergences),
    }


def _catalog_findings(
    session: Session, request: ImpactRequest, findings: Findings
) -> dict[str, Any]:
    assert request.catalog_change is not None  # noqa: S101 - caller checks
    change = request.catalog_change
    result = store.diff_versions(
        session, request.catalog, change.from_version, change.to_version, request.lang
    )
    for control in result.changed:
        fields = ", ".join(c.field for c in control.changes)
        flags = [f for f in control.flags if f == "obligation-change"]
        findings.add(
            control.id,
            Reason(
                "catalog",
                "control changed",
                f"{change.from_version} -> {change.to_version}: {fields}",
                flags,
            ),
        )
    for cid in result.added:
        findings.add(cid, Reason("catalog", "control added", f"new in {change.to_version}"))
    findings.retired.extend(result.retired)
    return {"from": change.from_version, "to": change.to_version, "summary": result.summary}


# --- systems ---------------------------------------------------------------------------


def _import_catalog_name(href: str) -> str | None:
    path = urlsplit(href).path
    parts = path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] == "catalogs":  # /catalogs/{name}/versions/{v}
        return parts[1]
    name = path.rsplit("/", 1)[-1]
    for suffix in (".en.json", ".fr.json", ".json"):
        if name.endswith(suffix):
            return name.removesuffix(suffix)
    return None


def _scope(
    profile: Mapping[str, Any], catalog: str, catalog_doc: Mapping[str, Any]
) -> set[str] | None:
    """Controls a profile selects from this catalog; None if the profile is for another one."""
    names = {_import_catalog_name(i["href"]) for i in profile["profile"]["imports"]}
    if catalog not in names:
        return None
    if names != {catalog}:
        raise store.InvalidCatalogError(
            f"profile imports several catalogs {sorted(map(str, names))}"
        )
    try:
        result = resolve_profile(profile, lambda _href: catalog_doc)
    except ProfileResolutionError as exc:
        raise store.InvalidCatalogError("profile could not be resolved", exc.errors) from exc
    return set(result.control_ids)


def _sha(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_report(
    session: Session, request: ImpactRequest, due_dates: DueDatePolicy
) -> dict[str, Any]:
    assert request.catalog_version is not None  # noqa: S101 - validated
    catalog_doc = store.get_version(
        session, request.catalog, request.catalog_version, request.lang
    ).document
    controls = [c for c in iter_controls(catalog_doc) if c.prop("status") != "withdrawn"]
    by_id = {c.id: c for c in controls}
    findings = Findings()
    triggers: dict[str, Any] = {}
    if request.source is not None:
        triggers["source"] = _source_findings(session, request, catalog_doc, controls, findings)
    if request.catalog_change is not None:
        triggers["catalog"] = _catalog_findings(session, request, findings)

    affected_controls: list[dict[str, Any]] = [
        {
            "id": cid,
            "label": by_id[cid].prop("label") if cid in by_id else None,
            "source_clauses": _source_clauses(by_id[cid]) if cid in by_id else [],
            "obligation_change": any("obligation-change" in r.flags for r in reasons),
            "reasons": [r.as_dict() for r in reasons],
        }
        for cid, reasons in sorted(findings.controls.items())
    ]
    affected_ids = {c["id"] for c in affected_controls}

    snapshot, systems = inv.current_inventory(session)
    previous_doc = (
        store.get_version(
            session, request.catalog, request.catalog_change.from_version, request.lang
        ).document
        if request.catalog_change is not None and findings.retired
        else None
    )
    profiles: dict[str, dict[str, Any]] = {}
    ranked: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    retired_in_scope: dict[str, list[str]] = defaultdict(list)
    for system in systems:
        if request.tenant and system.tenant != request.tenant:
            continue
        if system.lifecycle == "retired":
            excluded.append({"system_id": system.system_id, "reason": "lifecycle retired"})
            continue
        in_scope: set[str] = set()
        previous_scope: set[str] = set()  # scope under catalog_change.from (for retirements)
        applicable = False
        for name in system.profiles:
            if name not in profiles:
                profiles[name] = inv.get_profile(session, name)
            selected = _scope(profiles[name], request.catalog, catalog_doc)
            if selected is not None:
                applicable = True
                in_scope |= selected
                if previous_doc is not None:
                    previous_scope |= _scope(profiles[name], request.catalog, previous_doc) or set()
        if not applicable:
            excluded.append(
                {
                    "system_id": system.system_id,
                    "reason": f"no profile selects from {request.catalog}",
                }
            )
            continue
        for cid in findings.retired:
            if cid in previous_scope:
                retired_in_scope[cid].append(system.system_id)
        hits = sorted(in_scope & affected_ids)
        if not hits:
            excluded.append(
                {"system_id": system.system_id, "reason": "no affected control in scope"}
            )
            continue
        ranked.append(
            {
                "system_id": system.system_id,
                "name": system.name,
                "tenant": system.tenant,
                "owner": system.owner,
                "impact_level": system.impact_label,
                "lifecycle": system.lifecycle,
                "controls_in_scope": len(in_scope),
                "findings_to_review": len(hits),
                "obligation_changes": sum(
                    1 for c in affected_controls if c["id"] in hits and c["obligation_change"]
                ),
                "controls": hits,
                "_record": system,
            }
        )
    ranked.sort(
        key=lambda s: (-inv.ROMAN[s["impact_level"]], -s["findings_to_review"], s["system_id"])
    )

    trigger_text = " and ".join(
        f"{t['instrument']} {t['from']} -> {t['to']}"
        if k == "source"
        else f"{request.catalog} {t['from']} -> {t['to']}"
        for k, t in triggers.items()
    )
    report_core: dict[str, Any] = {
        "inputs": {
            "catalog": request.catalog,
            "catalog_version": request.catalog_version,
            "lang": request.lang,
            "tenant": request.tenant,
            "as_of": request.as_of.isoformat(),
            "inventory_snapshot_hash": snapshot.content_hash,
            "due_date_policy": f"{due_dates.path} (PLACEHOLDER values, not policy)",
        },
        "triggers": triggers,
        "affected_controls": affected_controls,
    }
    report_id = _sha({**report_core, "systems": [s["system_id"] for s in ranked]})[:16]

    tasks: list[dict[str, Any]] = []
    for rank, entry in enumerate(ranked, start=1):
        record: inv.SystemRecord = entry.pop("_record")
        entry["rank"] = rank
        due, basis = due_dates.due(record.tenant, record.impact_level, request.as_of)
        task_controls = []
        for cid in entry["controls"]:
            control = by_id.get(cid)
            info = next(c for c in affected_controls if c["id"] == cid)
            task_controls.append(
                {
                    "id": cid,
                    "statement": control.part("statement") if control else None,
                    "evidence_requested": control.part("assessment-objective") if control else None,
                    "obligation_change": info["obligation_change"],
                    "reasons": [f"{r['kind']}: {r['detail']}" for r in info["reasons"]],
                }
            )
        lines = [
            f"Rule change: {trigger_text}. Reassess the controls below and attach evidence.",
            *(
                f"- {c['id']}{' [OBLIGATION CHANGE]' if c['obligation_change'] else ''}: "
                + "; ".join(c["reasons"])
                for c in task_controls
            ),
        ]
        tasks.append(
            {
                "task_id": f"IMP-{report_id[:8]}-{record.system_id}",
                "table": "sc_task",
                "type": "reassessment",
                "short_description": (
                    f"Reassess {len(task_controls)} control(s) for {record.name} "
                    f"after {trigger_text}"
                ),
                "description": "\n".join(lines),
                "assignment_group": record.tenant,
                "assigned_to": record.owner_email,
                "priority": PRIORITY[record.impact_level],
                "due_date": due.isoformat(),
                "due_date_basis": basis,
                "system_id": record.system_id,
                "impact_level": record.impact_label,
                "controls": task_controls,
            }
        )

    maintenance = list(findings.maintenance)
    for cid in sorted(findings.retired):
        maintenance.append(
            {
                "kind": "control retired",
                "control": cid,
                "detail": "close open findings for this control",
                "systems": retired_in_scope.get(cid, []),
            }
        )
    by_level: dict[str, int] = defaultdict(int)
    for entry in ranked:
        by_level[entry["impact_level"]] += entry["findings_to_review"]
    return {
        "report_id": report_id,
        **report_core,
        "summary": {
            "affected_controls": len(affected_controls),
            "affected_systems": len(ranked),
            "findings_to_review": sum(s["findings_to_review"] for s in ranked),
            "findings_by_impact_level": dict(
                sorted(by_level.items(), key=lambda kv: -inv.ROMAN[kv[0]])
            ),
            "obligation_changes": sum(c["obligation_change"] for c in affected_controls),
            "maintenance_items": len(maintenance),
            "excluded_systems": len(excluded),
        },
        "systems": ranked,
        "tasks": tasks,
        "maintenance": maintenance,
        "excluded_systems": excluded,
    }
