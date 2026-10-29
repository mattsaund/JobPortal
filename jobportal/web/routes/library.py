"""The Resumes page: resume versions the user keeps, edits, downloads and applies to leads.

Saved resumes are storage. They're never used as a template and never feed the profile: every tailored resume is written
from the profile."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from jobportal.ai import client as ai
from jobportal.candidate import library
from jobportal.documents import exports, render, revise
from jobportal.search import pipeline
from jobportal.web.common import ai_error, lead_or_404, read_upload

router = APIRouter()


def _item_or_404(item_id: int) -> dict:
    item = library.get(item_id)
    if not item:
        raise HTTPException(404)
    return item


@router.get("/api/library")
def list_resumes():
    return library.list_items()


@router.post("/api/library")
def save_resume(body: dict):
    """Save a resume: pass md (and optionally a style), or just lead_id to save that lead's current resume."""
    lead = lead_or_404(int(body["lead_id"])) if body.get("lead_id") else None
    md, style = body.get("md"), body.get("style")
    if lead:
        md = md or lead.get("resume_md")
        style = style or (lead.get("package") or {}).get("resume_style")
    if not (md or "").strip():
        raise HTTPException(400, "nothing to save")
    name = body.get("name") or (f"{lead['company']}: {lead['title']}"[:90] if lead else "")
    return library.create(name, md, style, body.get("source") or ("saved from lead" if lead else "saved"),
                          lead["id"] if lead else None, body.get("tags"), body.get("notes", ""))


# Registered before PUT /api/library/{item_id}, so "import" is never read as an item id.
@router.put("/api/library/import")
async def import_resume(request: Request, filename: str, name: str = ""):
    """Add a resume file (sent as the raw request body) to the collection, wording kept exactly."""
    data = await read_upload(request)
    try:
        return await library.import_file(filename, data, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except ai.AIError as e:
        raise ai_error(e)


@router.get("/api/library/{item_id}")
def get_resume(item_id: int):
    return _item_or_404(item_id)


@router.put("/api/library/{item_id}")
def update_resume(item_id: int, body: dict):
    return library.update(item_id, body)


@router.delete("/api/library/{item_id}")
def delete_resume(item_id: int):
    library.delete(item_id)
    return {"ok": True}


@router.get("/api/library/{item_id}/html")
def resume_preview(item_id: int):
    """The saved resume rendered exactly as its PDF will look."""
    item = _item_or_404(item_id)
    return HTMLResponse(render.resume_html(item["md"], 1.0, item["style"].get("theme", "classic")))


@router.post("/api/library/{item_id}/revise")
async def revise_resume(item_id: int, body: dict):
    """Ask the AI to edit a saved resume by instruction. Returns the new text; nothing is saved."""
    item = _item_or_404(item_id)
    try:
        return await revise.revise_saved_resume(item, body.get("instruction", ""), body.get("text") or "")
    except ai.AIError as e:
        raise ai_error(e)


@router.get("/api/library/{item_id}/export/{fmt}")
async def export_resume(item_id: int, fmt: str):
    """Download a saved resume as PDF, DOCX or Markdown."""
    item = _item_or_404(item_id)
    try:
        path, filename = await exports.library_file(item, fmt)
    except exports.NotAvailable:
        raise HTTPException(404)
    return FileResponse(path, filename=filename)


@router.post("/api/library/{item_id}/apply/{lead_id}")
async def use_for_lead(item_id: int, lead_id: int, body: dict):
    """Use a saved resume for a lead, as it is or tailored to that job by the AI. {"backup": true} first saves the lead's
    current resume to the collection."""
    item = _item_or_404(item_id)
    lead = lead_or_404(lead_id)
    if body.get("backup") and (lead.get("resume_md") or "").strip():
        library.create(f"{lead['company']}: {lead['title']}"[:80] + " (before swap)", lead["resume_md"],
                       (lead.get("package") or {}).get("resume_style"), "saved from lead", lead_id)
    try:
        return await pipeline.use_saved_resume(lead_id, item, bool(body.get("tailor")))
    except ai.AIError as e:
        raise ai_error(e)
