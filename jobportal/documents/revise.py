"""Edit a document with AI by giving an instruction, such as "make it shorter" or "lead with the Python project".

The lead editor uses this for a lead's resume, cover letter and other documents, and the Resumes page uses it for saved
resumes. The AI also gets the candidate profile, so it can bring in true details the document left out, and resumes get the
format rules and the resume playbook, so the layout survives the edit. Nothing is saved here: the editor shows the result and
the user decides whether to keep it."""
from jobportal.ai import client as ai, prompts
from jobportal.candidate import profile
from jobportal.core import db, settings


def _result(out: dict) -> dict:
    """The part of the AI's answer the editor shows: the new text and a short summary of what changed."""
    return {"text": out["text"], "change_summary": out.get("change_summary", "")}


async def revise_lead_document(lead: dict, doc: str, instruction: str, text: str) -> dict:
    """Revise one of a lead's documents (doc is "resume", "cover", or another document's name). The job posting is included
    so edits stay aimed at that job. The instruction is recorded in the lead's history."""
    resume_rules = prompts.RESUME_FORMAT if doc == "resume" else ""
    system = f"{prompts.system('revise', prompts.REVISE_SYSTEM)}\n\n{resume_rules}\n\n=== CANDIDATE PROFILE ===\n{profile.full_context()}"
    prompt = f"""DOCUMENT TYPE: {doc}
JOB: {lead['title']} at {lead['company']} ({lead['location']})
JOB DESCRIPTION (excerpt):
{(lead.get('description') or '')[:6000]}

INSTRUCTION: {instruction}

CURRENT DOCUMENT:
{text}"""
    out = await ai.run(prompt, system=system, schema=prompts.REVISE_SCHEMA, stage="revise", purpose=f"revise:{doc}",
                       lead_id=lead["id"], label=f"revise {doc}", timeout=600)
    db.add_event(lead["id"], "revise", f"{doc}: {instruction[:200]}")
    return _result(out)


async def revise_saved_resume(item: dict, instruction: str, text: str = "") -> dict:
    """Revise a resume from the library. There's no job here, so the edit follows the instruction, the playbook and the
    saved layout and page limit. text is the editor's current version when it has unsaved changes."""
    style = {"theme": "classic", "max_pages": 1, **item["style"]}
    system = (f"{prompts.system('revise', prompts.REVISE_SYSTEM)}\n\n{prompts.RESUME_FORMAT}\n\n=== RESUME PLAYBOOK ===\n"
              f"{settings.resume_playbook()}\n\n=== CANDIDATE PROFILE ===\n{profile.full_context()}")
    prompt = (f"DOCUMENT TYPE: resume (layout {style['theme']}, page limit {style['max_pages']})\n"
              f"JOB: none, this is a saved resume in the candidate's collection (\"{item['name']}\")\n\n"
              f"INSTRUCTION: {instruction}\n\nCURRENT DOCUMENT:\n{text or item['md']}")
    out = await ai.run(prompt, system=system, schema=prompts.REVISE_SCHEMA, stage="revise", purpose="library-revise",
                       label=f"revise saved resume: {item['name'][:24]}", timeout=600)
    return _result(out)
