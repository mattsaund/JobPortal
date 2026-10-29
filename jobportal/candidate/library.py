"""The resume library behind the Resumes page: resume versions the user keeps, edits, downloads and applies to leads.

Saved resumes are storage only. They never feed the profile and are never used as a template. JobPortal learns about the
user only from the imported resume, the standard answers and questions asked along the way (see candidate/profile.py), and
every tailored resume is written fresh from the profile. A saved resume reaches a lead only when the user applies it on
purpose (search/pipeline.py, use_saved_resume). The editable copy that setup can keep of the imported resume is storage too.

Each item is one row in the resume_library table: a name, the resume in JobPortal's markdown format (ai/prompts.RESUME_FORMAT),
a style (theme and page limit), tags, notes, and where it came from (source, lead_id, original_file). Downloads are rendered
on demand into LIB_DIR/<id>/ by documents/exports.py and deleted whenever the item changes.

Called by web/routes/library.py (the Resumes page) and web/routes/candidate.py (the copy of a newly imported resume)."""
import json
import shutil
from pathlib import Path

from jobportal.ai import client as ai, prompts
from jobportal.core import db
from jobportal.core.config import DATA
from jobportal.documents import extract

LIB_DIR = DATA / "library"
DEFAULT_STYLE = {"theme": "classic", "max_pages": 1}

IMPORT_SYSTEM = """Convert the extracted text of ONE resume into the markdown format below. Preserve the content exactly: same wording,
dates, titles, bullets, order and sections. Only repair text-extraction damage (broken lines, hyphenation, merged columns, stray page
numbers). Never add, remove, improve or reword anything."""
IMPORT_SCHEMA = {"type": "object", "properties": {"resume_md": {"type": "string"}, "suggested_name": {"type": "string"}},
                 "required": ["resume_md", "suggested_name"]}



def _decode(row: dict | None) -> dict | None:
    """A database row with its JSON columns turned back into Python: style into a dict and tags into a list. A missing or
    broken value reads as empty."""
    if not row:
        return None
    for column, empty in (("style", {}), ("tags", [])):
        try:
            row[column] = json.loads(row.get(column) or "null") or empty
        except json.JSONDecodeError:
            row[column] = empty
    return row


def _delete_downloads(item_id: int) -> None:
    """Delete the PDF, DOCX and Markdown files rendered for one saved resume. documents/exports.py renders them again on demand."""
    shutil.rmtree(LIB_DIR / str(item_id), ignore_errors=True)


def list_items() -> list[dict]:
    """Every saved resume, most recently changed first, with a 400-character preview in place of the full text."""
    return [_decode(r) for r in db.q("SELECT id, name, style, source, lead_id, tags, notes, created_at, updated_at, "
                                     "substr(md, 1, 400) AS preview FROM resume_library ORDER BY updated_at DESC")]


def get(item_id: int) -> dict | None:
    """One saved resume with its full markdown, or None when there's no such item."""
    return _decode(db.one("SELECT * FROM resume_library WHERE id=?", (item_id,)))


def create(name: str, md: str, style: dict | None = None, source: str = "saved", lead_id: int | None = None,
           tags: list | None = None, notes: str = "", original_file: str | None = None) -> dict:
    """Save a new resume and return it. style defaults to DEFAULT_STYLE. source says where it came from: "saved",
    "saved from lead" (with lead_id) or "imported" (with original_file, the name of the imported file)."""
    now = db.now()
    new_id = db.ex("INSERT INTO resume_library(name, md, style, source, lead_id, tags, notes, original_file, created_at, updated_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?)", (name.strip() or "Untitled resume", md, json.dumps(style or DEFAULT_STYLE),
                                                 source, lead_id, json.dumps(tags or []), notes, original_file, now, now))
    return get(new_id)


def update(item_id: int, fields: dict) -> dict:
    """Change a saved resume and return it. Only name, md, style, tags and notes can change; other keys are ignored.
    Rendered downloads are deleted, because they no longer match."""
    changes = {k: v for k, v in fields.items() if k in ("name", "md", "style", "tags", "notes")}
    for column in ("style", "tags"):
        if column in changes:
            changes[column] = json.dumps(changes[column])
    if changes:
        columns = ", ".join(f"{k}=?" for k in changes)  # names from the fixed list above, never from the request
        db.ex(f"UPDATE resume_library SET {columns}, updated_at=? WHERE id=?", (*changes.values(), db.now(), item_id))
        _delete_downloads(item_id)
    return get(item_id)


def delete(item_id: int) -> None:
    """Delete a saved resume and its rendered downloads."""
    db.ex("DELETE FROM resume_library WHERE id=?", (item_id,))
    _delete_downloads(item_id)


async def import_file(filename: str, data: bytes, name: str = "") -> dict:
    """Add a resume file to the library as editable markdown, wording kept exactly (see import_text()). Returns the new
    item. Raises extract.ExtractError (a ValueError) when no text can be read from the file."""
    return await import_text(extract.extract_text(filename, data), filename, name)


async def import_text(text: str, filename: str = "resume.txt", name: str = "") -> dict:
    """Add resume text to the library and return the new item.

    Text already in JobPortal's markdown format (a "# Name" title and "## " sections) is saved as it is. Anything else goes
    to the AI, which converts it to that format without changing the wording (one AI call). The item is called name when
    given, otherwise the AI's suggestion or the file name."""
    if text.lstrip().startswith("# ") and "\n## " in text:
        md, suggested = text, Path(filename).stem
    else:
        out = await ai.run(f"{prompts.RESUME_FORMAT}\n\nFILE NAME: {filename}\n\nEXTRACTED TEXT:\n{text[:30000]}",
                           system=IMPORT_SYSTEM, schema=IMPORT_SCHEMA, stage="revise", purpose="library-import",
                           label=f"import resume: {filename[:30]}", timeout=600)
        md, suggested = out["resume_md"], out.get("suggested_name") or Path(filename).stem
    return create(name or suggested, md, source="imported", notes=f"Imported from {filename}", original_file=filename)
