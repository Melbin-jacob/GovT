"""Rendering helpers shared by the screens."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

from control_centre.backends import Backends
from control_centre.config import Settings, get_settings
from control_centre.i18n import LANGS, OTHER, Translator

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

# (key in the navigation, path below /{lang}/, string key of its label)
SCREENS: list[tuple[str, str, str]] = [
    ("policy", "policy-change", "nav.policy"),
    ("impact", "impact", "nav.impact"),
    ("review", "review", "nav.review"),
    ("log", "decision-log", "nav.log"),
    ("inventory", "inventory", "nav.inventory"),
]

_backends: Backends | None = None


def get_backends() -> Backends:
    """Overridden in tests with canned responses."""
    global _backends
    if _backends is None:
        _backends = Backends.from_settings(get_settings())
    return _backends


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
        **context,
    )
    return HTMLResponse(html, status_code=status_code)
