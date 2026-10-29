"""Resume library: resumes you import or save for reuse. They are never a template for generation (every tailored resume is
composed from the profile); the library is for keeping versions you like, exporting them again, or applying one to a lead."""
import json
import shutil
from pathlib import Path

from . import claude, db, extract, prompts
from .config import DATA

LIB_DIR = DATA / "library"
SCHEMA = """CREATE TABLE IF NOT EXISTS resume_library (
  id INTEGER PRIMARY KEY, name TEXT, md TEXT, style TEXT DEFAULT '{}', source TEXT, lead_id INTEGER, tags TEXT DEFAULT '[]',
  notes TEXT DEFAULT '', original_file TEXT, created_at TEXT, updated_at TEXT)"""

IMPORT_SYSTEM = """Convert the extracted text of ONE resume into the markdown format below. Preserve the content exactly: same wording,
dates, titles, bullets, order and sections. Only repair text-extraction damage (broken lines, hyphenation, merged columns, stray page
numbers). Never add, remove, improve or reword anything."""
IMPORT_SCHEMA = {"type": "object", "properties": {"resume_md": {"type": "string"}, "suggested_name": {"type": "string"}},
                 "required": ["resume_md", "suggested_name"]}


def _ensure():
    db.conn().executescript(SCHEMA)


def _row(r: dict | None) -> dict | None:
    if not r:
        return None
    for k in ("style", "tags"):
        try:
            r[k] = json.loads(r.get(k) or ("{}" if k == "style" else "[]"))
        except json.JSONDecodeError:
            r[k] = {} if k == "style" else []
    return r


def list_items() -> list[dict]:
    _ensure()
    return [_row(r) for r in db.q("SELECT id, name, style, source, lead_id, tags, notes, created_at, updated_at, "
                                  "substr(md, 1, 400) AS preview FROM resume_library ORDER BY updated_at DESC")]


def get(item_id: int) -> dict | None:
    _ensure()
    return _row(db.one("SELECT * FROM resume_library WHERE id=?", (item_id,)))


def create(name: str, md: str, style: dict | None = None, source: str = "saved", lead_id: int | None = None,
           tags: list | None = None, notes: str = "", original_file: str | None = None) -> dict:
    _ensure()
    now = db.now()
    new_id = db.ex("INSERT INTO resume_library(name, md, style, source, lead_id, tags, notes, original_file, created_at, updated_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?)", (name.strip() or "Untitled resume", md, json.dumps(style or {"theme": "classic", "max_pages": 1}),
                                                 source, lead_id, json.dumps(tags or []), notes, original_file, now, now))
    return get(new_id)


def update(item_id: int, fields: dict) -> dict:
    _ensure()
    allowed = {k: v for k, v in fields.items() if k in ("name", "md", "style", "tags", "notes")}
    for k in ("style", "tags"):
        if k in allowed:
            allowed[k] = json.dumps(allowed[k])
    if allowed:
        cols = ", ".join(f"{k}=?" for k in allowed)
        db.ex(f"UPDATE resume_library SET {cols}, updated_at=? WHERE id=?", (*allowed.values(), db.now(), item_id))
        for f in (LIB_DIR / str(item_id)).glob("*") if (LIB_DIR / str(item_id)).exists() else []:
            f.unlink(missing_ok=True)  # rendered files are stale now
    return get(item_id)


def delete(item_id: int) -> None:
    _ensure()
    db.ex("DELETE FROM resume_library WHERE id=?", (item_id,))
    shutil.rmtree(LIB_DIR / str(item_id), ignore_errors=True)


async def import_file(filename: str, data: bytes, name: str = "") -> dict:
    """Import one resume file (or pasted text saved as .txt) as an editable markdown copy, wording kept exactly."""
    text = extract.extract_text(filename, data)
    return await import_text(text, filename, name)


async def import_text(text: str, filename: str = "resume.txt", name: str = "") -> dict:
    if text.lstrip().startswith("# ") and "\n## " in text:
        md, suggested = text, Path(filename).stem  # already in our markdown format
    else:
        out = await claude.run(f"{prompts.RESUME_FORMAT}\n\nFILE NAME: {filename}\n\nEXTRACTED TEXT:\n{text[:30000]}",
                               system=IMPORT_SYSTEM, schema=IMPORT_SCHEMA, stage="revise", purpose="library-import",
                               label=f"import resume: {filename[:30]}", timeout=600)
        md, suggested = out["resume_md"], out.get("suggested_name") or Path(filename).stem
    return create(name or suggested, md, source="imported", notes=f"Imported from {filename}", original_file=filename)
