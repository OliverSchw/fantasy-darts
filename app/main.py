"""Einstiegspunkt der Web-App (lokal: `uvicorn app.main:app --reload`, Vercel erkennt `app` automatisch)."""

from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .auth import AdminRequired, LoginRequired
from .db import create_tables
from .season import SeasonNotImported
from .settings import get_settings
from .web import account, admin, admin_players, admin_rules, admin_schedule, beerpong, confirm, darts, hub, members, my_teams, pages
from .web.common import redirect, render

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    create_tables()
    yield


settings = get_settings()
app = FastAPI(title="Fantasy Darts", lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="fd_session",
    max_age=60 * 60 * 24 * 60,  # 60 Tage eingeloggt bleiben
    same_site="lax",
    https_only=settings.secure_cookies,
)


# Fantasy Darts lag früher direkt unter "/". Alte Links, Lesezeichen und offene Tabs werden
# dauerhaft auf /fantasy/... umgeleitet (GET mit 301; Formulare mit 308, damit sie nicht verloren gehen).
LEGACY_FANTASY_PATHS = ("/teams", "/players", "/compare", "/bracket", "/insights", "/rules", "/schedule",
                        "/matches", "/my", "/admin/schedule", "/admin/players", "/admin/rules", "/admin/export",
                        "/admin/lock")


def legacy_fantasy_url(path: str) -> str | None:
    if any(path == p or path.startswith(p + "/") for p in LEGACY_FANTASY_PATHS):
        return "/fantasy" + path
    return None


@app.middleware("http")
async def redirect_legacy_fantasy(request: Request, call_next):
    target = legacy_fantasy_url(request.url.path)
    if target is None:
        return await call_next(request)
    if request.url.query:
        target += "?" + request.url.query
    return RedirectResponse(target, status_code=301 if request.method in ("GET", "HEAD") else 308)


# Service-Worker und Manifest müssen im Wurzelverzeichnis liegen (Scope der PWA).
@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript",
                        headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    # no-cache: Handys sollen geänderte Farben/Icons sofort mitbekommen
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "icons" / "icon-192.png", media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


app.include_router(hub.router)
app.include_router(pages.router)
app.include_router(account.router)
app.include_router(confirm.router)
app.include_router(members.router)
app.include_router(darts.router)
app.include_router(beerpong.router)
app.include_router(my_teams.router)
app.include_router(admin.router)
app.include_router(admin_players.router)
app.include_router(admin_rules.router)
app.include_router(admin_schedule.router)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.exception_handler(LoginRequired)
def _login_required(request: Request, _exc):
    return redirect("/login?next=" + quote(request.url.path))


@app.exception_handler(AdminRequired)
def _admin_required(request: Request, _exc):
    return render(request, "message.html", status_code=403, title="Admins only",
                  text="This page is only available to admins.")


@app.exception_handler(SeasonNotImported)
def _season_missing(request: Request, exc: SeasonNotImported):
    return render(request, "message.html", status_code=503, title="Season not set up yet",
                  text=f"The season “{exc.args[0]}” has not been imported yet. "
                       f"Run: python -m app.cli import-season {exc.args[0]}")


@app.exception_handler(StarletteHTTPException)
def _http_error(request: Request, exc: StarletteHTTPException):
    titles = {404: "Not found", 403: "Not allowed", 405: "Not allowed"}
    return render(request, "message.html", status_code=exc.status_code,
                  title=titles.get(exc.status_code, "Error"), text=str(exc.detail or ""))
