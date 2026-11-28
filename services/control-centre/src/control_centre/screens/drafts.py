"""Rulebook drafts: AI-drafted control changes after a policy change, decided by people.

Side by side per item: the current control, the clause change (old and new official
text) and the draft, all in the page language; French pages never show English drafts.
The other language's draft status is shown with a link to it. Approving approves both
languages: the rulebook records which language views the person opened (in an approval
session) and refuses approval until both were opened since the draft last changed; the
approver also confirms it explicitly. Edit, approve or reject per item;
publish the approved changes as a new catalog version.

The rulebook enforces the rules (governance officers approve; the person who last edited
a draft cannot approve it; the SOURCE_DATE must pass the guard); this screen shows the
reason when it refuses, and checks the source date itself before publishing.

Demo only: who is acting is chosen on the page ("Acting as", kept in a cookie) so the
roles and the two-person rule can be shown. TODO(control-centre): real sign-in replaces
this selector.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any, Final
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from control_centre.backends import BackendError
from control_centre.web import BackendsDep, LangDep, SettingsDep, render

router = APIRouter()

ACTORS: Final = {
    "demo-reviewer-01": "reviewer",
    "demo-officer-01": "governance-officer",
    "demo-officer-02": "governance-officer",
}
DEFAULT_ACTOR: Final = "demo-officer-01"
COOKIE: Final = "govhub_demo_actor"
# The rulebook's approval session for the acting person: "<actor> <session id>".
SESSION_COOKIE: Final = "govhub_draft_session"
# Codes the rulebook returns when it refuses (approval.ApprovalError), plus the screen's own.
ERROR_CODES: Final = (
    "two-person-rule", "role", "needs-human", "languages-differ", "not-ready", "id-used",
    "source-date", "undecided", "stale-links", "reason", "batch-closed", "item-decided",
    "no-statement", "no-check-type", "no-wording", "not-new", "confirm-both", "not-read",
    "session", "refused",
)  # fmt: skip
OBLIGATIONS: Final = ("must", "must-not", "should", "should-not", "may", "may-not", "restriction")
NOTICES: Final = ("created", "drafted", "edited", "approved", "rejected", "published")


def actor_of(cookie: str | None) -> str:
    return cookie if cookie in ACTORS else DEFAULT_ACTOR


def headers_for(actor: str) -> dict[str, str]:
    return {"X-GovHub-User": actor, "X-GovHub-Role": ACTORS[actor]}


def error_code(exc: BackendError) -> str:
    """The rulebook's refusal code (``detail.code``), or ``refused``."""
    for code in ERROR_CODES:
        if f"'code': '{code}'" in exc.detail:
            return code
    return "refused"


def session_of(cookie: str | None, actor: str) -> str | None:
    """The approval session in the cookie, if it belongs to the acting person."""
    owner, _, sid = (cookie or "").partition(" ")
    return sid if owner == actor and sid else None


def min_source_date(previous: str) -> str:
    """The earliest date the SOURCE_DATE guard accepts: the day after the previous one."""
    return (date.fromisoformat(previous[:10]) + timedelta(days=1)).isoformat()


def check_source_date(value: str, previous: str) -> str | None:
    """The chosen date as a SOURCE_DATE, or None if the guard would refuse it."""
    try:
        chosen = date.fromisoformat(value.strip())
    except ValueError:
        return None
    if chosen.isoformat() < min_source_date(previous):
        return None
    return f"{chosen.isoformat()}T00:00:00Z"


def _back(lang: str, batch_id: str, **query: str) -> RedirectResponse:
    params = urlencode({k: v for k, v in query.items() if v})
    anchor = f"#item-{query['item']}" if query.get("item") else ""
    return RedirectResponse(
        f"/{lang}/drafts/{batch_id}{'?' + params if params else ''}{anchor}", 303
    )


@router.get("/{lang}/drafts", response_class=HTMLResponse)
def drafts_list(
    request: Request,
    lang: LangDep,
    backends: BackendsDep,
    settings: SettingsDep,
    actor: Annotated[str | None, Cookie(alias=COOKIE)] = None,
) -> HTMLResponse:
    return render(
        request, lang, "drafts-list.html", title_key="drafts.title", screen="drafts",
        batches=backends.rulebook.get("/drafts/batches"),
        sources=backends.rulebook.get("/sources"), catalogs=backends.rulebook.get("/catalogs"),
        actor=actor_of(actor), actors=ACTORS,
        default_instrument=settings.default_instrument, default_catalog=settings.default_catalog,
    )  # fmt: skip


@router.post("/{lang}/drafts/actor")
def choose_actor(
    lang: LangDep, actor: Annotated[str, Form()], back: Annotated[str, Form()] = ""
) -> RedirectResponse:
    target = back if back.startswith(f"/{lang}/drafts") and "//" not in back else f"/{lang}/drafts"
    response = RedirectResponse(target, 303)
    if actor in ACTORS:
        response.set_cookie(COOKIE, actor, httponly=True, samesite="strict")
        response.delete_cookie(SESSION_COOKIE)  # another person: another approval session
    return response


@router.post("/{lang}/drafts")
def start_batch(
    lang: LangDep,
    backends: BackendsDep,
    catalog: Annotated[str, Form()],
    version: Annotated[str, Form()],
    instrument: Annotated[str, Form()],
    from_version: Annotated[str, Form(alias="from")],
    to_version: Annotated[str, Form(alias="to")],
    actor: Annotated[str | None, Cookie(alias=COOKIE)] = None,
) -> RedirectResponse:
    """Plan the drafting work (plain code), then ask the engine for the drafts."""
    body = {"catalog": catalog, "version": version, "instrument": instrument,
            "from": from_version, "to": to_version}  # fmt: skip
    batch = backends.rulebook.post("/drafts/batches", body, headers=headers_for(actor_of(actor)))
    try:
        backends.engine.post(f"/drafting/batches/{batch['id']}/draft", {})
        notice = "drafted"
    except BackendError:
        notice = "created"  # the engine is unavailable: people can still write the drafts
    return _back(lang, batch["id"], notice=notice)


@router.get("/{lang}/drafts/{batch_id}", response_class=HTMLResponse)
def batch_detail(
    request: Request,
    lang: LangDep,
    backends: BackendsDep,
    batch_id: str,
    notice: str | None = None,
    error: str | None = None,
    item: str | None = None,
    actor: Annotated[str | None, Cookie(alias=COOKIE)] = None,
    draft_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> HTMLResponse:
    """Showing this page opens this language's view of every draft: the rulebook records
    it in the person's approval session (approval needs both languages opened)."""
    person = actor_of(actor)
    sid = session_of(draft_session, person)
    status = backends.rulebook.get(f"/drafts/batches/{batch_id}")["status"]
    if status == "open":
        headers = headers_for(person)
        if sid is None:
            sid = str(backends.rulebook.post("/drafts/sessions", {}, headers=headers)["id"])
        backends.rulebook.post(
            f"/drafts/batches/{batch_id}/views", {"session_id": sid, "lang": lang},
            headers=headers,
        )  # fmt: skip
    batch = backends.rulebook.get(
        f"/drafts/batches/{batch_id}", **({"session_id": sid} if sid else {})
    )
    defaults = backends.rulebook.get(f"/drafts/batches/{batch_id}/publish-defaults")
    decided = all(i["status"] in ("approved", "rejected") for i in batch["items"])
    response = render(
        request, lang, "drafts-batch.html", title_key="drafts.batch_title", screen="drafts",
        batch=batch, defaults=defaults, decided=decided, actor=person, actors=ACTORS,
        notice=notice if notice in NOTICES else None,
        error=error if error in ERROR_CODES else None, error_item=item,
        obligations=OBLIGATIONS, min_date=min_source_date(defaults["previous"]),
    )  # fmt: skip
    if sid:
        response.set_cookie(SESSION_COOKIE, f"{person} {sid}", httponly=True, samesite="strict")
    return response


@router.post("/{lang}/drafts/{batch_id}/items/{item_id}/edit")
def edit_item(
    lang: LangDep,
    backends: BackendsDep,
    batch_id: str,
    item_id: str,
    statement: Annotated[str, Form()] = "",
    obligation: Annotated[str, Form()] = "",
    check_type: Annotated[str, Form()] = "",
    proposed_id: Annotated[str, Form()] = "",
    actor: Annotated[str | None, Cookie(alias=COOKIE)] = None,
) -> RedirectResponse:
    """A person writes or corrects the page language's draft (the other language is
    edited on its own page; the rulebook refuses approval while the two disagree)."""
    fields: dict[str, Any] = {"statement": statement.strip(), "no_change": False}
    if obligation in OBLIGATIONS:
        fields["obligation"] = obligation
    if check_type in ("rule-based", "judgment"):
        fields["check_type"] = check_type
    body: dict[str, Any] = {"languages": {lang: fields}}
    if proposed_id.strip():
        body["proposed_id"] = proposed_id.strip()
    try:
        backends.rulebook.put(
            f"/drafts/items/{item_id}", body, headers=headers_for(actor_of(actor))
        )
    except BackendError as exc:
        return _back(lang, batch_id, error=error_code(exc), item=item_id)
    return _back(lang, batch_id, notice="edited", item=item_id)


@router.post("/{lang}/drafts/{batch_id}/items/{item_id}/{action}")
def decide_item(
    lang: LangDep,
    backends: BackendsDep,
    batch_id: str,
    item_id: str,
    action: str,
    reason: Annotated[str, Form()] = "",
    both_languages: Annotated[str, Form()] = "",
    actor: Annotated[str | None, Cookie(alias=COOKIE)] = None,
    draft_session: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> RedirectResponse:
    """Approve or reject; the rulebook enforces the role and the two-person rule."""
    if action not in ("approve", "reject"):
        return _back(lang, batch_id, error="refused", item=item_id)
    if action == "approve" and both_languages != "yes":
        return _back(lang, batch_id, error="confirm-both", item=item_id)
    try:
        backends.rulebook.post(
            f"/drafts/items/{item_id}/{action}",
            {"reason": reason, "session_id": session_of(draft_session, actor_of(actor))},
            headers=headers_for(actor_of(actor)),
        )  # fmt: skip
    except BackendError as exc:
        return _back(lang, batch_id, error=error_code(exc), item=item_id)
    return _back(lang, batch_id, notice=f"{action}d", item=item_id)


@router.post("/{lang}/drafts/{batch_id}/publish")
def publish(
    lang: LangDep,
    backends: BackendsDep,
    batch_id: str,
    source_date: Annotated[str, Form()] = "",
    actor: Annotated[str | None, Cookie(alias=COOKIE)] = None,
) -> RedirectResponse:
    defaults = backends.rulebook.get(f"/drafts/batches/{batch_id}/publish-defaults")
    value = check_source_date(source_date or defaults["default"][:10], defaults["previous"])
    if value is None:  # refused here, before anything is published
        return _back(lang, batch_id, error="source-date")
    try:
        backends.rulebook.post(
            f"/drafts/batches/{batch_id}/publish", {"source_date": value},
            headers=headers_for(actor_of(actor)),
        )  # fmt: skip
    except BackendError as exc:
        return _back(lang, batch_id, error=error_code(exc))
    return _back(lang, batch_id, notice="published")
