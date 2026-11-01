"""A lead's documents: downloads (PDF, DOCX, Markdown, emails, the whole package as a zip), live previews for the editor,
AI edits by instruction, and the resume check. The work happens in jobportal/documents/."""
import re

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response

from jobportal.ai import client as ai
from jobportal.candidate import profile
from jobportal.core import db
from jobportal.documents import exports, render, revise
from jobportal.search import packages
from jobportal.web.common import ai_error, lead_or_404

router = APIRouter()


@router.get("/api/leads/{lead_id}/export/{name}")
async def export_document(lead_id: int, name: str):
    """Download one document ("resume.pdf", "emails.md", "email-0.eml") or everything ("package.zip")."""
    lead = lead_or_404(lead_id)
    try:
        if name == "package.zip":
            path, filename = await exports.package_zip(lead)
            return FileResponse(path, filename=filename)
        email = re.fullmatch(r"email-(\d+)\.eml", name)
        if email:
            data, filename = exports.email_file(lead, int(email.group(1)))
            return Response(data, media_type="message/rfc822", headers={"Content-Disposition": f'attachment; filename="{filename}"'})
        path, filename = await exports.lead_file(lead, name)
        return FileResponse(path, filename=filename)
    except exports.NotAvailable as e:
        raise HTTPException(404, str(e))
    except render.PDFError as e:  # no PDF engine, or it timed out: say so instead of a bare 500
        raise HTTPException(503, str(e))


@router.post("/api/preview")
def preview(body: dict):
    """The editor's live preview: a resume or cover letter rendered exactly as its PDF will look, or any other Markdown."""
    doc, md = body.get("doc", "resume"), body.get("md", "")
    if doc == "resume":
        theme = body.get("theme")
        if not theme and body.get("lead_id"):  # no layout picked in the editor: use the lead's saved layout
            row = db.lead_row(db.one("SELECT package FROM leads WHERE id=?", (body["lead_id"],)) or {"package": "{}"})
            theme = ((row or {}).get("package") or {}).get("resume_style", {}).get("theme")
        return HTMLResponse(render.resume_html(md, 1.0, theme if theme in render.THEMES else "classic"))
    if doc == "cover":
        lead = db.one("SELECT company, location FROM leads WHERE id=?", (body.get("lead_id") or 0,)) or {}
        return HTMLResponse(render.cover_html(md, profile.get("facts"), lead.get("company", ""), lead.get("location", "")))
    return HTMLResponse(f"<div class='md'>{render.markdown_html(md)}</div>")


@router.post("/api/leads/{lead_id}/revise")
async def revise_document(lead_id: int, body: dict):
    """Ask the AI to edit a lead's document by instruction. Returns the new text for the editor to show; nothing is saved."""
    lead = lead_or_404(lead_id)
    instruction = body.get("instruction", "").strip()
    if not instruction:
        raise HTTPException(400, "instruction required")
    try:
        return await revise.revise_lead_document(lead, body.get("doc", "resume"), instruction, body.get("text", ""))
    except ai.AIError as e:
        raise ai_error(e)


@router.post("/api/leads/{lead_id}/resume-check")
async def resume_check(lead_id: int):
    """Run the resume checks again on the lead's current resume (format, length, keywords, truthful skills) and save the result."""
    lead = lead_or_404(lead_id)
    if not lead.get("resume_md"):
        raise HTTPException(404, "no resume yet")
    try:
        return await packages.recheck_resume(lead)
    except render.PDFError as e:  # the page count needs a printed PDF
        raise HTTPException(503, str(e))
