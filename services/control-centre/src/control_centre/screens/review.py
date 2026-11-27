"""Screen 3: review queue, finding detail and the five human decisions.

Opening a finding for review is an explicit button (a POST): review-desk starts the timed
review session on its own clock, and the decision form carries that session's ID, so the
time is measured from the open, not reported by the browser.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from control_centre.backends import BackendError, Backends
from control_centre.i18n import Translator
from control_centre.web import BackendsDep, LangDep, render

router = APIRouter()

ACTIONS: Final = (
    "accept",
    "accept-with-remediation",
    "reject",
    "request-more-evidence",
    "override-verdict",
)
VERDICTS: Final = ("met", "partially-met", "not-met", "not-applicable", "unable-to-determine")
OPEN_STATES: Final = ("open", "awaiting-evidence")
NEEDS_ANNOTATION: Final = ("reject", "request-more-evidence", "override-verdict")


@router.get("/{lang}/review", response_class=HTMLResponse)
def review_queue(request: Request, lang: LangDep, backends: BackendsDep) -> HTMLResponse:
    queue = backends.desk.get("/queue", limit=1000)
    return render(
        request, lang, "review-queue.html", title_key="review.title", screen="review", queue=queue
    )


def control_text(backends: Backends, control_id: str, lang: str) -> dict[str, str]:
    """Statement and assessment objective from the catalog in the page's language."""
    try:
        control = backends.rulebook.get(f"/controls/{control_id}", lang=lang)
    except BackendError:
        return {}
    return {
        str(part["name"]): str(part["prose"])
        for part in control.get("control", {}).get("parts", [])
        if part.get("name") in ("statement", "assessment-objective") and part.get("prose")
    }


def _detail(
    request: Request,
    lang: str,
    backends: Backends,
    finding_id: str,
    *,
    session_id: int | None = None,
    decided: int | None = None,
    errors: list[str] | None = None,
    form: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    finding = backends.desk.get(f"/findings/{finding_id}")
    history = backends.desk.get(f"/findings/{finding_id}/decisions")
    return render(
        request,
        lang,
        "finding.html",
        title_key="finding.title",
        screen="review",
        status_code=status_code,
        finding=finding,
        catalog_text=control_text(backends, finding["control_id"], lang),
        history=history,
        decidable=finding["state"] in OPEN_STATES,
        session_id=session_id,
        decided=decided,
        errors=errors or [],
        form=form or {},
        actions=ACTIONS,
        verdicts=VERDICTS,
    )


@router.get("/{lang}/review/{finding_id}", response_class=HTMLResponse)
def finding_detail(
    request: Request,
    lang: LangDep,
    backends: BackendsDep,
    finding_id: str,
    session: int | None = None,
    decided: int | None = None,
) -> HTMLResponse:
    return _detail(request, lang, backends, finding_id, session_id=session, decided=decided)


@router.post("/{lang}/review/{finding_id}/open")
def open_for_review(lang: LangDep, backends: BackendsDep, finding_id: str) -> RedirectResponse:
    opened = backends.desk.post(f"/findings/{finding_id}/open", {})
    return RedirectResponse(
        f"/{lang}/review/{finding_id}?session={opened['session_id']}#decision", status_code=303
    )


def decision_body(form: dict[str, str], t: Translator) -> tuple[dict[str, Any], list[str]]:
    """The review-desk request for the submitted form, or translated problems."""
    action = form.get("action", "")
    annotation = form.get("annotation", "").strip()
    errors: list[str] = []
    if action not in ACTIONS:
        return {}, [t("decide.error_action")]
    body: dict[str, Any] = {"action": action, "annotation": annotation}
    if form.get("session_id", "").isdigit():
        body["session_id"] = int(form["session_id"])
    if action in NEEDS_ANNOTATION and not annotation:
        errors.append(t("decide.error_annotation"))
    if action == "override-verdict":
        if form.get("verdict") not in VERDICTS:
            errors.append(t("decide.error_verdict"))
        else:
            body["verdict"] = form["verdict"]
    if action == "accept-with-remediation":
        description = form.get("remediation_description", "").strip()
        due = form.get("remediation_due", "").strip()
        if not description or not due:
            errors.append(t("decide.error_remediation"))
        body["remediation"] = {"description": description, "due_date": due}
    return body, errors


@router.post("/{lang}/review/{finding_id}/decide", response_model=None)
def decide(
    request: Request,
    lang: LangDep,
    backends: BackendsDep,
    finding_id: str,
    action: Annotated[str, Form()] = "",
    annotation: Annotated[str, Form()] = "",
    verdict: Annotated[str, Form()] = "",
    remediation_description: Annotated[str, Form()] = "",
    remediation_due: Annotated[str, Form()] = "",
    session_id: Annotated[str, Form()] = "",
) -> HTMLResponse | RedirectResponse:
    form = {
        "action": action,
        "annotation": annotation,
        "verdict": verdict,
        "remediation_description": remediation_description,
        "remediation_due": remediation_due,
        "session_id": session_id,
    }
    body, errors = decision_body(form, Translator(lang))
    if not errors:
        try:
            result = backends.desk.post(f"/findings/{finding_id}/decisions", body)
        except BackendError as exc:
            if exc.status is None or exc.status >= 500:
                raise
            errors = [Translator(lang)("decide.error_refused", detail=exc.detail)]
        else:
            seq = result["log"]["seq"]
            return RedirectResponse(
                f"/{lang}/review/{finding_id}?decided={seq}#result", status_code=303
            )
    sid = int(session_id) if session_id.isdigit() else None
    return _detail(
        request,
        lang,
        backends,
        finding_id,
        session_id=sid,
        errors=errors,
        form=form,
        status_code=422,
    )
