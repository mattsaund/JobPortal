"""App-wide routes: the live event stream, version and status info, the counters in the sidebar, and three things a browser
tab can't do by itself (open the data folder, open a link outside the app window, quit)."""
import asyncio
import json
import re
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from jobportal import __version__
from jobportal.core import bus, db, osutil
from jobportal.core.config import APP_STATUSES, DATA, EFFORTS
from jobportal.search.collectors import COLLECTORS

router = APIRouter()


@router.get("/api/events")
async def events(request: Request):
    """Server-Sent Events. The dashboard keeps this connection open and gets every live update as it happens: run progress,
    new leads, profile changes and toasts. A comment line every 15 seconds keeps the connection from timing out."""
    queue = bus.subscribe()

    async def stream():
        try:
            yield f"data: {json.dumps({'kind': 'state', 'data': bus.state}, default=str)}\n\n"
            while not await request.is_disconnected():
                try:
                    yield f"data: {await asyncio.wait_for(queue.get(), timeout=15)}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/api/meta")
def meta():
    """Facts the dashboard needs once at startup: version, system, data folder, choices for menus, and whether PDF export works."""
    return {"version": __version__, "os": osutil.os_name(), "data_dir": str(DATA), "efforts": EFFORTS, "statuses": APP_STATUSES,
            "collectors": [{"key": key, "label": label} for key, (label, _fn) in COLLECTORS.items()],
            "pdf_ready": bool(osutil.find_pdf_engine())}


@router.get("/api/stats")
def stats():
    """The numbers on the sidebar and the Leads page header, plus the live run state."""
    count = lambda sql, args=(): db.one(sql, args)["n"]  # noqa: E731
    week_ago = (date.today() - timedelta(days=7)).isoformat()
    today = date.today().isoformat()
    return {
        "ready": count("SELECT COUNT(*) n FROM leads WHERE stage='ready' AND app_status IN ('new','saved')"),
        "queue": count("SELECT COUNT(*) n FROM leads WHERE stage IN ('qualified','packaging','error') AND app_status!='trashed'"),
        "applied": count("SELECT COUNT(*) n FROM leads WHERE applied_at IS NOT NULL"),
        "applied_week": count("SELECT COUNT(*) n FROM leads WHERE applied_at >= ?", (week_ago,)),
        "interviewing": count("SELECT COUNT(*) n FROM leads WHERE app_status IN ('assessment','interviewing')"),
        "offers": count("SELECT COUNT(*) n FROM leads WHERE app_status='offer'"),
        "followups_due": count("SELECT COUNT(*) n FROM leads WHERE follow_up_at IS NOT NULL AND follow_up_at <= ? "
                               "AND app_status IN ('applied','assessment','interviewing')", (today,)),
        "total": count("SELECT COUNT(*) n FROM leads"),
        "state": bus.state,
    }


@router.post("/api/open-data-folder")
def open_data_folder():
    """Show the folder that holds the database, generated files and the imported resume."""
    DATA.mkdir(parents=True, exist_ok=True)
    return {"ok": osutil.open_path(DATA), "path": str(DATA)}


@router.post("/api/open-external")
def open_external(body: dict):
    """Open a web or mail link in the default browser or mail app. The app window (a browser in app mode) sends links here
    so they open outside it."""
    url = str(body.get("url") or "")
    if not re.match(r"^(https?://|mailto:)", url, re.I):
        raise HTTPException(400, "Only web and mail links can be opened.")
    return {"ok": osutil.open_url(url)}


@router.post("/api/quit")
def quit_app(request: Request):
    """Stop JobPortal. The dashboard offers this in a browser tab, where closing the tab leaves the server running.
    app/desktop.py hands the app its server object when it starts it."""
    server = getattr(request.app.state, "server", None)
    if server is None:
        raise HTTPException(409, "This server can't be stopped from the dashboard.")
    server.should_exit = True
    return {"ok": True}
