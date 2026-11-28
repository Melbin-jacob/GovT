"""Sign-in and sign-out: OIDC (AUTH_MODE=oidc) or the labelled demo mode (fictional users).

In demo mode the "Acting as" selector in the page header signs in as another fictional
user (a new session); nothing else changes between the modes: either way the hub
services receive only internal tokens minted for the signed-in user.
"""

from __future__ import annotations

import contextlib
from functools import lru_cache
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from control_centre.config import get_settings
from control_centre.db import get_session
from control_centre.identity import sessions
from control_centre.identity.demo_users import demo_users
from control_centre.identity.oidc import OidcClient, OidcConfig, OidcError
from control_centre.identity.rolemap import RoleMap
from control_centre.web import LangDep, render

router = APIRouter()
DbDep = Annotated[Session, Depends(get_session)]


def safe_next(path: str | None, lang: str) -> str:
    """Only our own pages: a path under /en/ or /fr/, never another host."""
    if path and path.startswith(("/en/", "/fr/")) and "//" not in path and "\\" not in path:
        return path
    return f"/{lang}/"


def oidc_config() -> OidcConfig:
    s = get_settings()
    return OidcConfig(
        issuer=s.oidc_issuer, client_id=s.oidc_client_id, client_secret=s.oidc_client_secret,
        redirect_url=s.oidc_redirect_url, discovery_url=s.oidc_discovery_url,
        allowed_hosts=frozenset(h.strip() for h in s.oidc_allowed_hosts.split(",") if h.strip()),
        allow_insecure_http=s.oidc_allow_insecure_http,
    )  # fmt: skip


@lru_cache
def oidc_client() -> OidcClient:
    return OidcClient(oidc_config())


def _with_session(response: RedirectResponse, token: str) -> RedirectResponse:
    response.set_cookie(
        sessions.COOKIE, token, httponly=True, samesite="lax",
        secure=get_settings().secure_cookies, max_age=int(sessions.ABSOLUTE.total_seconds()),
    )  # fmt: skip
    response.delete_cookie("govhub_draft_session")  # approval sessions belong to one person
    return response


@router.get("/{lang}/sign-in", response_class=HTMLResponse)
def sign_in_page(
    request: Request, lang: LangDep, next: str | None = None, error: str | None = None
) -> HTMLResponse:
    return render(
        request, lang, "sign-in.html", title_key="signin.title", screen=None,
        next_path=safe_next(next, lang), error=error if error in ("oidc", "unknown") else None,
    )  # fmt: skip


@router.post("/{lang}/sign-in/demo")
def demo_sign_in(
    lang: LangDep, db: DbDep, user: Annotated[str, Form()],
    next: Annotated[str, Form()] = "",
) -> RedirectResponse:  # fmt: skip
    settings = get_settings()
    if settings.auth_mode != "demo":
        raise HTTPException(404, "demo mode is off")
    people = demo_users(settings.demo_users_file)
    if user not in people:
        return RedirectResponse(f"/{lang}/sign-in?error=unknown", 303)
    token = sessions.start(db, people[user], "demo")
    return _with_session(RedirectResponse(safe_next(next, lang), 303), token)


@router.get("/auth/login")
def oidc_login(db: DbDep, next: str | None = None, lang: str = "en") -> RedirectResponse:
    if get_settings().auth_mode != "oidc":
        raise HTTPException(404, "sign-in is in demo mode")
    lang = lang if lang in ("en", "fr") else "en"
    try:
        return RedirectResponse(oidc_client().begin(db, safe_next(next, lang)), 303)
    except OidcError:
        return RedirectResponse(f"/{lang}/sign-in?error=oidc", 303)


@router.get("/auth/callback")
def oidc_callback(
    db: DbDep, state: str = "", code: str = "", error: str | None = None
) -> RedirectResponse:
    if get_settings().auth_mode != "oidc":
        raise HTTPException(404, "sign-in is in demo mode")
    if error or not state or not code:
        return RedirectResponse("/en/sign-in?error=oidc", 303)
    try:
        who, next_path = oidc_client().finish(
            db, state, code, RoleMap.from_file(get_settings().role_map_file)
        )
    except (OidcError, ValueError):
        return RedirectResponse("/en/sign-in?error=oidc", 303)
    token = sessions.start(db, who, "oidc")
    return _with_session(RedirectResponse(next_path, 303), token)


@router.post("/{lang}/sign-out")
def sign_out(request: Request, lang: LangDep, db: DbDep) -> RedirectResponse:
    sessions.end(db, request.cookies.get(sessions.COOKIE))
    target = f"/{lang}/sign-in"
    if get_settings().auth_mode == "oidc":
        base = str(request.base_url).rstrip("/")
        with contextlib.suppress(OidcError):
            target = oidc_client().end_session_url(base + target) or target
    response = RedirectResponse(target, 303)
    response.delete_cookie(sessions.COOKIE)
    response.delete_cookie("govhub_draft_session")
    return response


def sign_in_redirect(lang: str, next_path: str) -> RedirectResponse:
    return RedirectResponse(f"/{lang}/sign-in?next={quote(next_path, safe='/')}", 303)
