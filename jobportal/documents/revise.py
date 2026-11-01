"""Edit a document with AI by giving an instruction, such as "make it shorter" or "lead with the Python project".

The lead editor uses this for a lead's resume, cover letter and other documents (web/routes/documents.py), and Settings,
Resumes uses it for saved resumes (web/routes/library.py). The AI also gets the candidate profile, so it can bring in true
details the document left out. Resumes also get the format rules, the resume playbook and their layout and page limit
(resume_writer_system), so the layout survives the edit, the same as when search/packages.py reworks a resume. Nothing is
saved here: the editor shows the result and the user decides whether to keep it."""
from jobportal.ai import client as ai, prompts
from jobportal.candidate import profile
from jobportal.core import db, settings
from jobportal.documents.render import DEFAULT_STYLE


def resume_writer_system(prompt_name: str, default: str, cfg: dict | None = None) -> str:
    """Instructions for an AI that rewrites a resume: the task prompt `prompt_name` (Settings can override it; `default` is
    the built-in one), the resume format rules, the resume playbook and the full candidate profile. Every AI resume
    rewrite uses it: revisions here, and the critic and reworks in search/packages.py. Pass the settings as `cfg` when
    you have them, to skip reading them again."""
    return (f"{prompts.system(prompt_name, default)}\n\n{prompts.RESUME_FORMAT}\n\n=== RESUME PLAYBOOK ===\n"
            f"{settings.resume_playbook(cfg)}\n\n=== CANDIDATE PROFILE ===\n{profile.full_context()}")


def _result(out: dict) -> dict:
    """The part of the AI's answer the editor shows: the new text and a short summary of what changed."""
    return {"text": out["text"], "change_summary": out.get("change_summary", "")}


async def revise_lead_document(lead: dict, doc: str, instruction: str, text: str) -> dict:
    """Revise one of a lead's documents (doc is "resume", "cover", or another document's name). The job posting is included
    so edits stay aimed at that job, and a resume keeps the lead's layout and page limit. Returns {"text",
    "change_summary"}. Side effects: one AI call (stage "revise"), and the instruction is recorded in the lead's history."""
    if doc == "resume":
        style = {**DEFAULT_STYLE, **((lead.get("package") or {}).get("resume_style") or {})}
        system = resume_writer_system("revise", prompts.REVISE_SYSTEM)
        kind = f"resume (layout {style['theme']}, page limit {style['max_pages']})"
    else:
        system = f"{prompts.system('revise', prompts.REVISE_SYSTEM)}\n\n=== CANDIDATE PROFILE ===\n{profile.full_context()}"
        kind = doc
    prompt = f"""DOCUMENT TYPE: {kind}
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
    saved layout and page limit. text is the editor's current version when it has unsaved changes. Returns {"text",
    "change_summary"}. Side effect: one AI call (stage "revise")."""
    style = {**DEFAULT_STYLE, **(item.get("style") or {})}
    prompt = (f"DOCUMENT TYPE: resume (layout {style['theme']}, page limit {style['max_pages']})\n"
              f"JOB: none, this is a saved resume in the candidate's collection (\"{item['name']}\")\n\n"
              f"INSTRUCTION: {instruction}\n\nCURRENT DOCUMENT:\n{text or item['md']}")
    out = await ai.run(prompt, system=resume_writer_system("revise", prompts.REVISE_SYSTEM), schema=prompts.REVISE_SCHEMA,
                       stage="revise", purpose="library-revise", label=f"revise saved resume: {item['name'][:24]}", timeout=600)
    return _result(out)
