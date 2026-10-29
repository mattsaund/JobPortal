"""The Settings page: every setting, the resume playbook and layouts, and the built-in AI prompts (shown greyed out as
placeholders until the user overrides one)."""
from fastapi import APIRouter

from jobportal.ai import prompts
from jobportal.core import settings
from jobportal.documents import render

router = APIRouter()


@router.get("/api/settings")
def get_settings():
    return settings.get()


@router.put("/api/settings")
def save_settings(body: dict):
    return settings.save(body)


@router.post("/api/settings/reset")
def reset_settings(body: dict):
    """Put one section back to its default, for example {"path": "sources.ats_boards"}."""
    return settings.reset_section(body["path"])


@router.get("/api/resume-playbook")
def resume_playbook():
    """The playbook in use, the built-in one, whether the user customized it, and the resume layouts to choose from."""
    return {"text": settings.resume_playbook(), "default": settings.default_playbook(),
            "custom": bool((settings.get().get("resume_playbook") or "").strip()), "themes": render.THEMES}


@router.get("/api/prompts/defaults")
def prompt_defaults():
    return {"triage": prompts.TRIAGE_SYSTEM, "hunt": prompts.HUNT_SYSTEM, "package": prompts.PACKAGE_SYSTEM,
            "revise": prompts.REVISE_SYSTEM, "profile": prompts.PROFILE_SYSTEM, "analysis": prompts.ANALYSIS_SYSTEM,
            "resume_review": prompts.RESUME_REVIEW_SYSTEM}
