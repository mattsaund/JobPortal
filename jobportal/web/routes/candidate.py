"""The user's side: setup (import a resume and any extra documents, answer the standard questions), the Profile page, and
the questions JobPortal asks along the way.

These are the only ways JobPortal learns about the user. Nothing else feeds the profile: not saved resumes, not leads, not
anything found on the web."""
from fastapi import APIRouter, HTTPException, Request

from jobportal.ai import client as ai
from jobportal.candidate import documents, library, onboarding, profile
from jobportal.core import background, bus, db
from jobportal.documents import extract
from jobportal.web.common import ai_error, read_upload

router = APIRouter()


# ---------------------------------------------------------------- setup: the resume and the standard questions

@router.get("/api/onboarding")
def onboarding_state():
    """Everything the setup page needs: the questions, the saved answers and resume, and what's still missing."""
    return onboarding.state()


def _keep_copy_in_library(text: str, filename: str) -> None:
    """Also keep an editable copy of the imported resume on the Resumes page. It's a convenience: the copy never feeds the
    profile, and a failure here never affects setup."""
    async def save():
        item = await library.import_text(text, filename)
        bus.publish("toast", {"title": "Saved to your resume collection", "body": item.get("name", "")})
    background.spawn(save())


@router.put("/api/onboarding/resume")
async def import_resume_file(request: Request, filename: str, save_to_library: int = 1, prefill: int = 1):
    """Import the resume file (sent as the raw request body), read its text, and pre-fill the standard questions from it."""
    data = await read_upload(request)
    try:
        out = await onboarding.import_resume(filename, data=data, do_prefill=bool(prefill))
    except extract.ExtractError as e:
        raise HTTPException(400, str(e))
    if save_to_library:
        _keep_copy_in_library(profile.resume()["text"], filename)
    return out


@router.post("/api/onboarding/resume-text")
async def import_resume_text(body: dict):
    """The same as a file import, for a resume pasted as text."""
    name = body.get("name") or "Pasted resume.txt"
    try:
        out = await onboarding.import_resume(name, text=body.get("text") or "", do_prefill=bool(body.get("prefill", True)))
    except extract.ExtractError as e:
        raise HTTPException(400, str(e))
    if body.get("save_to_library", True):
        _keep_copy_in_library(profile.resume()["text"], name)
    return out


@router.put("/api/onboarding/answers")
async def save_answers(body: dict):
    """Save the standard answers. With a resume imported, this also starts building the profile in the background."""
    try:
        answers = onboarding.save_answers(body.get("answers") or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    building = bool(body.get("build", True) and profile.resume())
    if building:
        background.spawn(profile.build("standard answers saved"))  # build() reports its own errors as toasts
    return {"ok": True, "answers": answers, "building": building, "status": profile.status_snapshot()}


# ---------------------------------------------------------------- the profile

@router.get("/api/profile")
def get_profile():
    return profile.get_all()


# ---------------------------------------------------------------- extra documents
# Registered before PUT /api/profile/{key}, so "documents" is never read as a profile section's name.

@router.get("/api/profile/documents")
def list_documents():
    """The extra documents: other resumes, certificates, cover letters, awards and transcripts (without their text)."""
    return documents.listing()


@router.put("/api/profile/documents")
async def add_document(request: Request, filename: str):
    """Add one document, sent as the raw request body. The profile rebuilds about a minute after the user stops adding."""
    data = await read_upload(request)
    try:
        return documents.add(filename, data)
    except ValueError as e:  # extract.ExtractError (no readable text, unsupported type) or the document limit
        raise HTTPException(400, str(e))


@router.post("/api/profile/documents/{doc_id}/main")
async def use_document_as_main_resume(doc_id: str):
    """Swap: this document becomes the main resume, and the old main resume becomes a document."""
    try:
        return {"resume": await documents.make_main(doc_id)}
    except KeyError:
        raise HTTPException(404, "no such document")
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.delete("/api/profile/documents/{doc_id}")
def remove_document(doc_id: str):
    if not documents.remove(doc_id):
        raise HTTPException(404, "no such document")
    return {"ok": True}


@router.put("/api/profile/{key}")
def edit_profile_section(key: str, body: dict):
    """The user corrects a profile section by hand on the Profile page."""
    try:
        profile.save(key, body["value"])
    except KeyError:
        raise HTTPException(404, "unknown profile section")
    bus.publish("profile", {"ts": db.now(), "mode": "edit", "sections": [key]})
    return {"ok": True}


@router.get("/api/profile/status")
def profile_status():
    return profile.status_snapshot()


@router.get("/api/profile/overview")
def profile_overview():
    return profile.overview()


@router.post("/api/profile/build")
async def rebuild_profile():
    """Rebuild every AI-written profile section from the resume and all answers."""
    if not profile.resume():
        raise HTTPException(400, "Import a resume first.")
    background.spawn(profile.build("rebuild (dashboard)"))
    return {"ok": True}


@router.post("/api/profile/sync-answers")
async def add_answers_now():
    """Fold new answers into the profile now instead of waiting for the background watcher."""
    background.spawn(profile.update_from_answers("answers (dashboard)"))  # reports its own errors
    return {"ok": True, "pending": len(profile.unsynced())}


@router.post("/api/profile/voice")
async def learn_voice():
    """Learn how the user writes from the writing sample in the standard answers."""
    try:
        return await profile.learn_voice("manual")
    except ai.AIError as e:
        raise ai_error(e)


@router.get("/api/profile/{key}/history")
def profile_history(key: str):
    """Earlier versions of one profile section, newest first."""
    return profile.history(key)


# ---------------------------------------------------------------- questions asked along the way

@router.get("/api/questions")
def questions():
    return profile.questions()


@router.post("/api/questions/answer")
def answer_question(body: dict):
    if not body.get("question") or not str(body.get("answer", "")).strip():
        raise HTTPException(400, "question and answer required")
    updated = profile.answer_question(body["question"], body["answer"])
    return {"ok": True, "questions": updated, "status": profile.status_snapshot()}


@router.post("/api/questions/dismiss")
def dismiss_question(body: dict):
    return profile.dismiss_question(body.get("question", ""))
