"""Small helpers the route modules share."""
from fastapi import HTTPException, Request

from jobportal.ai import client as ai
from jobportal.core import db

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # imported resumes; real ones are far smaller


def ai_error(e: Exception) -> HTTPException:
    """Turn an AI failure into the HTTP status the dashboard expects: 401 means "sign in with ChatGPT", 429 means the plan's
    usage cap was reached, and 502 is anything else that went wrong talking to OpenAI."""
    if isinstance(e, ai.NotSignedIn):
        return HTTPException(401, str(e))
    if isinstance(e, ai.UsageLimitError):
        return HTTPException(429, str(e))
    return HTTPException(502, str(e))


def lead_or_404(lead_id: int) -> dict:
    """The lead with that id, with its JSON columns decoded, or a 404 for the dashboard."""
    lead = db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))
    if not lead:
        raise HTTPException(404, "lead not found")
    return lead


async def read_upload(request: Request) -> bytes:
    """The raw body of a file upload (the dashboard sends files as the request body), refusing anything over 25 MB."""
    data = await request.body()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "file too large (25 MB max)")
    return data
