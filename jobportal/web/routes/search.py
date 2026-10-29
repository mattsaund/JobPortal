"""Search runs and sources: start and stop a run, the Runs page (history, logs, AI call log), and the Sources page checks."""
import json

from fastapi import APIRouter, HTTPException

from jobportal.core import db
from jobportal.search import pipeline, sources
from jobportal.search.collectors import COLLECTORS

router = APIRouter()

RUN_MODES = ("full", "boards", "hunt", "backlog")  # everything, job boards only, AI hunt only, just the waiting queue


@router.post("/api/run")
async def start_run(body: dict):
    """Start a search run. Refused (409) while one is running or before setup is finished."""
    mode = body.get("mode", "full")
    if mode not in RUN_MODES:
        raise HTTPException(400, "bad mode")
    try:
        return {"run_id": await pipeline.start(mode, body.get("overrides"))}
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@router.post("/api/run/stop")
async def stop_run():
    await pipeline.stop()
    return {"ok": True}


@router.get("/api/runs")
def runs():
    """The last 60 runs, newest first, for the Runs page."""
    rows = db.q("SELECT * FROM runs ORDER BY id DESC LIMIT 60")
    for row in rows:
        row["stats"] = json.loads(row["stats"] or "{}")
    return rows


@router.get("/api/runs/{run_id}/log")
def run_log(run_id: int, after: int = 0):
    """A run's log lines. `after` lets the dashboard fetch only lines it hasn't shown yet."""
    return db.q("SELECT id, ts, level, source, msg FROM run_log WHERE run_id=? AND id>? ORDER BY id LIMIT 3000", (run_id, after))


@router.get("/api/ai_calls")
def ai_calls():
    """The last 200 AI requests with their purpose, model, tokens and outcome. The dashboard doesn't show this. It's for
    checking AI usage while developing: open http://127.0.0.1:8788/api/ai_calls in a browser."""
    return db.q("SELECT * FROM ai_calls ORDER BY id DESC LIMIT 200")


@router.post("/api/sources/detect")
async def detect_source(body: dict):
    return await sources.detect_board((body.get("url") or "").strip(), body.get("name") or "")


@router.post("/api/sources/test/{key}")
async def test_source(key: str):
    if key not in COLLECTORS:
        raise HTTPException(404)
    return await sources.test_collector(key)
