"""The Analysis and Dream list pages.

The Analysis page's role controls (add, remove and bring back a role) each answer with the whole page's data, the same as
GET /api/analysis, so the page redraws from one request."""
from fastapi import APIRouter, HTTPException

from jobportal.candidate import profile
from jobportal.core import background, db, settings
from jobportal.insights import analysis
from jobportal.search import pipeline, plan

router = APIRouter()


@router.get("/api/analysis")
def get_analysis():
    """The Analysis page: the radar's roles with their numbers and scores, the market numbers, the latest AI assessment
    and its history (see insights/analysis.get)."""
    return analysis.get()


@router.post("/api/analysis/run")
async def run_analysis():
    """Ask the AI for a fresh fit-and-demand assessment, in the background (it toasts its own result or error)."""
    background.spawn(analysis.run_ai("manual"))
    return {"ok": True}


@router.post("/api/analysis/roles/add")
def add_analysis_role(body: dict):
    """Add a job title of the user's own to the radar, {"title": "..."}. It stays until they remove it. A 400 explains a
    title that can't be added (empty, too long, only a level, or too many added already)."""
    try:
        analysis.add_role(str(body.get("title") or ""))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return analysis.get()


@router.post("/api/analysis/roles/remove")
def remove_analysis_role(body: dict):
    """Take a role off the radar for good, {"id": "<role id>"}."""
    analysis.remove_role(str(body.get("id") or ""))
    return analysis.get()


@router.post("/api/analysis/roles/restore")
def restore_analysis_role(body: dict):
    """Bring back a role the user removed, {"id": "<role id>"}."""
    analysis.restore_role(str(body.get("id") or ""))
    return analysis.get()


@router.get("/api/dreams")
def get_dreams():
    """The Dream list page. Companies come from two places: the ones the user added, and the ones the profile's search plan
    suggested (minus any the user removed)."""
    cfg = settings.get()
    suggested = (profile.get("search_plan") or {}).get("dream_companies", [])
    removed = cfg.get("dream_exclude", [])
    mine = {x.strip().lower() for x in cfg.get("dream_companies", [])}
    still_suggested = {x.strip().lower() for x in suggested}
    return {"companies": cfg.get("dream_companies", []),
            "profile_companies": [x for x in plan.plan_dreams(cfg) if x.strip().lower() not in mine],
            "excluded": [x for x in removed if x.strip().lower() in still_suggested] or removed,
            "jobs": cfg.get("dream_jobs", []),
            "bypass": cfg["locations"].get("dream_bypass", True),
            "jobs_bypass": cfg["locations"].get("dream_jobs_bypass", False),
            "flagged": db.one("SELECT COUNT(*) n FROM leads WHERE dream=1 AND app_status!='trashed'")["n"]}


@router.put("/api/dreams")
def save_dreams(body: dict):
    """Save the Dream list: companies, job titles, removed suggestions, and whether dream jobs may skip the location filter."""
    cfg = settings.get()
    for key, setting in (("companies", "dream_companies"), ("jobs", "dream_jobs"), ("excluded", "dream_exclude")):
        if key in body:
            cfg[setting] = [str(x).strip() for x in body[key] if str(x).strip()]
    if "bypass" in body:
        cfg["locations"]["dream_bypass"] = bool(body["bypass"])
    if "jobs_bypass" in body:
        cfg["locations"]["dream_jobs_bypass"] = bool(body["jobs_bypass"])
    settings.save(cfg)
    return get_dreams()


@router.post("/api/dreams/recheck")
def recheck_dreams():
    """Re-flag every lead against the current Dream list. Leads the user starred or unstarred by hand are left alone."""
    cfg = settings.get()
    companies, jobs = plan.all_dreams(cfg), cfg.get("dream_jobs", [])
    changed = 0
    for row in db.q("SELECT id, company, title, dream FROM leads WHERE dream_manual IS NULL"):
        dream = 1 if (pipeline.is_dream(row["company"], companies) or pipeline.is_dream_job(row["title"], jobs)) else 0
        if dream != (row["dream"] or 0):
            db.update_lead(row["id"], dream=dream)
            changed += 1
    return {"changed": changed, **get_dreams()}
