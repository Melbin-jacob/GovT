"""Rendering helpers shared by the screens."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape
from sqlalchemy.orm import Session

from control_centre.backends import Backends, identity_for
from control_centre.config import Settings, get_settings
from control_centre.db import get_session
from control_centre.i18n import LANGS, OTHER, Translator
from control_centre.identity import sessions
from control_centre.identity.demo_users import demo_users
from govhub_shared.auth import Principal, SigningKey

env = Environment(
    loader=PackageLoader("control_centre", "templates"),
    autoescape=select_autoescape(default=True, default_for_string=True),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def roman(level: object) -> str:
    """Impact level 1-4 as I-IV (values already in roman numerals pass through)."""
    numerals = {1: "I", 2: "II", 3: "III", 4: "IV"}
    return numerals[level] if isinstance(level, int) and level in numerals else str(level)


env.filters["roman"] = roman


def localized(value: object, lang: str) -> str:
    """Generated text in the page's language: a coded item carries ``text: {en, fr}``."""
    if isinstance(value, dict):
        text = value.get("text")
        if isinstance(text, dict) and lang in text:
            return str(text[lang])
        return str(value.get("detail") or value.get("reason") or value.get("code", ""))
    return str(value)


env.filters["localized"] = localized

# (key in the navigation, path below /{lang}/, string key of its label)
SCREENS: list[tuple[str, str, str]] = [
    ("policy", "policy-change", "nav.policy"),
    ("impact", "impact", "nav.impact"),
    ("review", "review", "nav.review"),
    ("log", "decision-log", "nav.log"),
    ("inventory", "inventory", "nav.inventory"),
    ("drafts", "drafts", "nav.drafts"),
]


class SignInRequiredError(Exception):
    """No (valid) session: the page redirects to the sign-in page."""

    def __init__(self, lang: str, next_path: str) -> None:
        super().__init__("sign-in required")
        self.lang = lang
        self.next_path = next_path


@lru_cache
def signing_key() -> SigningKey:
    settings = get_settings()
    kid = Path(settings.signing_kid_file).read_text("utf-8").strip()
    return SigningKey.from_file("control-centre", kid, settings.signing_key_file)


def signed_in(request: Request, db: Annotated[Session, Depends(get_session)]) -> Principal:
    """The signed-in person (or the demo mode's fictional user); else sign in first."""
    cached = getattr(request.state, "principal", None)
    if isinstance(cached, Principal):
        return cached
    who = sessions.load(db, request.cookies.get(sessions.COOKIE), get_settings().auth_mode)
    if who is None:
        lang = request.path_params.get("lang", "en")
        path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise SignInRequiredError(lang if lang in LANGS else "en", path)
    request.state.principal = who
    return who


PrincipalDep = Annotated[Principal, Depends(signed_in)]


def get_backends(who: PrincipalDep) -> Backends:
    """Hub services, called on the signed-in user's behalf (overridden in tests)."""
    return Backends.for_user(get_settings(), identity_for(who, signing_key()))


BackendsDep = Annotated[Backends, Depends(get_backends)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


def check_lang(lang: str) -> str:
    if lang not in LANGS:
        raise HTTPException(404, "unknown language")
    return lang


LangDep = Annotated[str, Depends(check_lang)]


def other_language_url(request: Request, lang: str) -> str:
    """The same page in the other language (path prefix swapped, query kept)."""
    path = request.url.path
    rest = path[len(lang) + 1 :] if path.startswith(f"/{lang}") else "/"
    url = f"/{OTHER[lang]}{rest or '/'}"
    if request.url.query:
        url += f"?{request.url.query}"
    return url


def render(
    request: Request,
    lang: str,
    template: str,
    *,
    title_key: str,
    screen: str | None = None,
    status_code: int = 200,
    **context: Any,
) -> HTMLResponse:
    t = Translator(lang)
    settings = get_settings()
    html = env.get_template(template).render(
        lang=lang,
        other_lang=OTHER[lang],
        other_url=other_language_url(request, lang),
        t=t,
        t_en=Translator("en"),
        t_fr=Translator("fr"),
        title=t(title_key),
        screen=screen,
        screens=SCREENS,
        settings=settings,
        principal=getattr(request.state, "principal", None),
        request_path=request.url.path + (f"?{request.url.query}" if request.url.query else ""),
        auth_mode=settings.auth_mode,
        demo_people=demo_users(settings.demo_users_file) if settings.auth_mode == "demo" else {},
        **context,
    )
    return HTMLResponse(html, status_code=status_code)
