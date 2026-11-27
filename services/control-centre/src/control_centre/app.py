"""Control centre web UI: server-rendered pages in English (/en/...) and French (/fr/...).

Demo only: no authentication (every page says so). Bind to localhost or the internal
network only. TODO(control-centre): OIDC sign-in, central roles, tenant isolation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from importlib.resources import files

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from control_centre.backends import BackendError
from control_centre.i18n import LANGS, Translator
from control_centre.screens import impact, policy, review
from control_centre.web import LangDep, env, render

app = FastAPI(
    title="GovHub control centre (demo UI)",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount(
    "/static",
    StaticFiles(directory=str(files("control_centre").joinpath("static"))),
    name="static",
)

app.include_router(policy.router)
app.include_router(impact.router)
app.include_router(review.router)

# Nothing is ever loaded from another origin: the browser enforces it too.
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
)


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    return response


def _lang_of(request: Request) -> str:
    first = request.url.path.strip("/").split("/", 1)[0]
    return first if first in LANGS else "en"


@app.exception_handler(BackendError)
def backend_error(request: Request, exc: BackendError) -> HTMLResponse:
    return render(
        request,
        _lang_of(request),
        "error.html",
        title_key="error.title",
        status_code=502 if exc.status is None or exc.status >= 500 else 400,
        error=exc,
    )


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def choose_language() -> HTMLResponse:
    """Bilingual landing page: English | Français."""
    html = env.get_template("choose-language.html").render(
        en=Translator("en"), fr=Translator("fr"), t_en=Translator("en"), t_fr=Translator("fr")
    )
    return HTMLResponse(html)


@app.get("/{lang}/", response_class=HTMLResponse)
def home(request: Request, lang: LangDep) -> HTMLResponse:
    return render(request, lang, "home.html", title_key="home.title", screen="home")
