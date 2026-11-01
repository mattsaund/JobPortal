"""The local web server. JobPortal's dashboard and its API run here, on 127.0.0.1 only, for one person on one computer.

This module builds the FastAPI app: what happens at startup and shutdown, two safety checks on every request, the dashboard
files, and the routes. The routes live in web/routes/, one module per area of the dashboard. app/desktop.py starts the
server and shows the window."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from jobportal import __version__
from jobportal.ai import client as ai, signin
from jobportal.candidate import documents, profile
from jobportal.core import background, bus, db, settings
from jobportal.core.config import STATIC
from jobportal.search import pipeline
from jobportal.web.routes import ROUTERS

# Host names that mean "this computer". "testserver" is the name FastAPI's test client uses.
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}


async def auto_runner() -> None:
    """Start a full search every N hours when Settings, "Auto-run every N hours" is above zero. Checks once a minute."""
    while True:
        await asyncio.sleep(60)
        try:
            hours = float(settings.get()["run"].get("auto_run_hours") or 0)
            if hours <= 0 or bus.state.get("running"):
                continue
            last = db.one("SELECT started_at FROM runs ORDER BY id DESC LIMIT 1")
            if last and datetime.now(timezone.utc) - datetime.fromisoformat(last["started_at"]) < timedelta(hours=hours):
                continue
            await pipeline.start("full")
        except Exception:  # noqa: BLE001 (the scheduler must keep running; a run that can't start just waits)
            pass


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Startup: open the database, clean up after a crash or a forced quit, publish the sign-in and profile status, and
    start the two background loops and the AI reading of documents that only have their rules reading. Shutdown: stop AI
    requests and all background work."""
    db.conn()
    signin.publish()
    settings.migrate_defaults()
    # A package or run that was in progress when JobPortal stopped will never finish. Put the lead back in the queue and
    # mark the run as interrupted, so both show correctly.
    db.ex("UPDATE leads SET stage='qualified' WHERE stage='packaging'")
    db.ex("UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'", (db.now(),))
    profile.publish_status()
    background.spawn(auto_runner())
    background.spawn(profile.answers_watcher(settings.get))
    background.spawn(documents.parse_pending())  # nothing to do unless signed in; it reports its own errors
    yield
    ai.kill_all()
    background.cancel_all()


app = FastAPI(title="JobPortal", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
for router in ROUTERS:
    app.include_router(router)


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Two checks on every request. A Host that isn't this computer is refused, so a web page can't reach the API through
    DNS rebinding. A change (anything but GET) from another site's page is refused too: browsers mark those requests with
    an Origin that isn't the dashboard's own."""
    host_port = (request.headers.get("host") or "").lower()
    if host_port.rsplit(":", 1)[0] not in LOCAL_HOSTS:
        return PlainTextResponse("JobPortal only answers requests addressed to 127.0.0.1 or localhost.", status_code=403)
    origin = (request.headers.get("origin") or "").lower()
    if origin and request.method not in ("GET", "HEAD", "OPTIONS") and origin != f"http://{host_port}":
        return PlainTextResponse("JobPortal only accepts changes from its own dashboard.", status_code=403)
    return await call_next(request)


@app.middleware("http")
async def no_stale_assets(request: Request, call_next):
    """Make the browser re-check the dashboard's JavaScript and CSS on every load, so an update shows up without a hard
    refresh."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/")
def index():
    """The dashboard itself. Everything else it needs comes from /static and /api."""
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})
