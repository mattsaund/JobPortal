"""The Settings page: every setting, the resume playbook and layouts, and the built-in AI prompts (shown grayed out as
placeholders until the user overrides one)."""
from fastapi import APIRouter, HTTPException

from jobportal.ai import prompts
from jobportal.core import bus, osutil, settings
from jobportal.documents import render
from jobportal.search import schedule

router = APIRouter()


@router.get("/api/settings")
def get_settings():
    """Every setting: what the user saved, merged over the defaults (core/settings.get)."""
    return settings.get()


@router.put("/api/settings")
def save_settings(body: dict):
    """Store the whole settings document the dashboard sends, replacing what was saved, and return the result. The schedule
    and the desktop alerts follow the new settings at once (search/schedule.settings_saved)."""
    before = settings.get()
    after = settings.save(body)
    schedule.settings_saved(before, after)
    bus.state["alerts"] = after["alerts"]
    return after


@router.get("/api/schedule")
def schedule_status():
    """The schedule as Settings and Home show it: on or off, the next scheduled search, the last one, and whether JobPortal
    starts in the background at login."""
    return schedule.status()


@router.post("/api/alerts/test")
def test_alert():
    """Send a desktop alert right away, the same way JobPortal sends one when its window is closed, so the user can check
    that alerts show on this computer. ok is False when the system has no way to show one."""
    return {"ok": osutil.notify("JobPortal test alert", "Desktop alerts work on this computer.")}


@router.post("/api/settings/reset")
def reset_settings(body: dict):
    """Put one section back to its default, for example {"path": "sources.ats_boards"}. Returns the settings."""
    path = body.get("path")
    if not isinstance(path, str) or not path.strip():
        raise HTTPException(400, "path required")
    return settings.reset_section(path.strip())


@router.get("/api/resume-playbook")
def resume_playbook():
    """The playbook in use, the built-in one, whether the user customized it, and the resume layouts to choose from."""
    return {"text": settings.resume_playbook(), "default": settings.default_playbook(),
            "custom": bool((settings.get().get("resume_playbook") or "").strip()), "themes": render.THEMES}


@router.get("/api/prompts/defaults")
def prompt_defaults():
    """The built-in system prompts by name, which Settings, AI shows as placeholders until the user overrides one."""
    return {"triage": prompts.TRIAGE_SYSTEM, "hunt": prompts.HUNT_SYSTEM, "package": prompts.PACKAGE_SYSTEM,
            "revise": prompts.REVISE_SYSTEM, "profile": prompts.PROFILE_SYSTEM, "analysis": prompts.ANALYSIS_SYSTEM,
            "resume_review": prompts.RESUME_REVIEW_SYSTEM, "documents": prompts.DOCUMENT_SYSTEM, "builder": prompts.BUILDER_SYSTEM}
