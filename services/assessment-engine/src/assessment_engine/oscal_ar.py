"""OSCAL 1.1.3 assessment-results for one assessment run (proposal Appendix A.4).

One result per run; one observation and one finding per assessed control. The verdict is
in ``target`` (mapping of Appendix A.1, as in the POA&M); verdict, confidence, method,
model and prompt version are props in the hub namespace. Normalized with trestle and
validated against the vendored NIST schema (a validation error is a failure).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final

from govhub_shared import OSCAL_NS, OSCAL_VERSION
from govhub_shared.oscal import content_hash, normalize, stable_uuid, validate

KIND: Final = "assessment-results"
# verdict -> (target.status.state, reason, implementation-status or None)
VERDICT_STATUS: dict[str, tuple[str, str, str | None]] = {
    "met": ("satisfied", "pass", "implemented"),
    "partially-met": ("not-satisfied", "fail", "partial"),
    "not-met": ("not-satisfied", "fail", "planned"),
    "not-applicable": ("satisfied", "other", "not-applicable"),
    "unable-to-determine": ("not-satisfied", "other", None),
}


def _prop(name: str, value: str) -> dict[str, str]:
    return {"name": name, "ns": OSCAL_NS, "value": value}


def build(
    *,
    run_id: str,
    system_id: str,
    catalog: str,
    catalog_version: str,
    started: datetime,
    assessments: list[dict[str, Any]],
) -> dict[str, Any]:
    observations, findings, controls = [], [], []
    for a in assessments:
        cid = a["control_id"]
        detail = a["detail"]
        obs_uuid = stable_uuid("ar-observation", run_id, cid)
        controls.append({"control-id": cid})
        rationale = detail.get("rationale", {})
        observation: dict[str, Any] = {
            "uuid": obs_uuid,
            "description": rationale.get("en") or cid,
            "methods": ["TEST"] if a["method"] == "rule" else ["EXAMINE"],
            "collected": started.isoformat(),
        }
        if rationale.get("fr"):
            observation["remarks"] = rationale["fr"]
        cited = detail.get("cited_passage_id")
        if cited:
            doc_id, _, seq = str(cited).partition(":")
            observation["relevant-evidence"] = [
                {
                    "href": f"evidence/{doc_id}#passage-{seq}",
                    "description": f"Cited passage: {detail.get('cited_quote', '')}"[:1000],
                }
            ]
        observations.append(observation)
        state, reason, implementation = VERDICT_STATUS[a["verdict"]]
        target: dict[str, Any] = {
            "type": "statement-id",
            "target-id": f"{cid}_smt",
            "status": {"state": state, "reason": reason},
        }
        if implementation:
            target["implementation-status"] = {"state": implementation}
        props = [_prop("verdict", a["verdict"]), _prop("method", a["method"])]
        if a.get("confidence") is not None:
            props.append(_prop("confidence", f"{a['confidence']:.2f}"))
        for key, name in (
            ("model_id", "model-id"),
            ("prompt_version", "prompt-version"),
            ("model_verdict", "model-verdict"),
            ("downgrade_reason", "downgrade-reason"),
            ("rule_status", "rule-status"),
            ("lang", "evidence-language"),
        ):
            if detail.get(key):
                props.append(_prop(name, str(detail[key])))
        if detail.get("flagged_passage_ids"):
            props.append(_prop("flagged-evidence", "true"))
        finding: dict[str, Any] = {
            "uuid": stable_uuid("ar-finding", run_id, cid),
            "title": f"{cid} on {system_id}",
            "description": rationale.get("en") or cid,
            "props": props,
            "target": target,
            "related-observations": [{"observation-uuid": obs_uuid}],
        }
        if a.get("finding_id"):
            finding["props"].append(_prop("review-finding", str(a["finding_id"])))
        findings.append(finding)
    body: dict[str, Any] = {
        "uuid": "00000000-0000-4000-8000-000000000000",
        "metadata": {
            "title": f"Assessment of {system_id} against {catalog} {catalog_version}",
            "last-modified": started.isoformat(),
            "version": "1",
            "oscal-version": OSCAL_VERSION,
            "props": [_prop("system-id", system_id), _prop("run-id", run_id)],
        },
        "import-ap": {"href": f"#assessment-plan-{system_id}"},
        "results": [
            {
                "uuid": stable_uuid("ar-result", run_id),
                "title": f"Assessment run {run_id}",
                "description": (
                    "Rule-based checks evaluated in code; judgment checks drafted by a "
                    "self-hosted model. Every finding is reviewed by a person."
                ),
                "start": started.isoformat(),
                "reviewed-controls": {
                    "control-selections": [{"include-controls": controls}] if controls else [{}]
                },
                "observations": observations,
                "findings": findings,
            }
        ],
    }
    if not findings:
        del body["results"][0]["observations"]
        del body["results"][0]["findings"]
    doc = normalize({KIND: body}, KIND)
    doc[KIND]["uuid"] = stable_uuid("assessment-results", run_id, content_hash(doc, KIND))
    doc = normalize(doc, KIND)
    validate(doc, KIND)
    return doc
