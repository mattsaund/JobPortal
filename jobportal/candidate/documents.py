"""Extra documents: certificates, cover letters, awards, transcripts and other resumes the user adds next to their resume.

They're optional. Setup still needs only the resume and the standard questions. But every document added here goes into
the next profile build together with the resume, so the profile, and the search plan made from it, covers everything the
user has done. That's how a certificate the resume never mentions can still lead to jobs that ask for it, and why more
documents mean a wider spread of job matches.

Where they're added: the setup page (the resume step) and Profile, Resume and documents. Each file is read with
documents/extract.py and kept as text in "profile.documents", and a copy of the file goes in the data folder (documents/).
Adding or removing one stamps "profile.documents_changed_at". profile.answers_watcher() then rebuilds the profile once the
user has paused for a minute, so dropping ten files at once means one rebuild, not ten.

Not to be confused with saved resumes on the Resumes page (candidate/library.py): that's a collection of resume versions to
reuse, and it never feeds the profile."""
import hashlib
import re
import time
import uuid
from pathlib import Path

from jobportal.core import bus, db
from jobportal.core.config import DATA, RESUME_DIR
from jobportal.documents import extract

DOCS_DIR = DATA / "documents"
MAX_DOCUMENTS = 40  # plenty for one person, and it keeps the profile build's prompt a sane size
MIN_CHARS = 20  # a certificate can be one line ("CPR certified, 2025"), so documents may be much shorter than a resume
MAX_CHARS_EACH = 15000  # how much of each document the profile build reads
MAX_CHARS_TOTAL = 90000  # how much of all documents together the profile build reads
LISTED = ("id", "name", "kind", "chars", "added_at")  # what the dashboard gets: everything but the text

# What a document looks like, guessed from its file name first and then its opening text. It's only a label for the list
# and a hint for the AI, which reads the whole text either way. The first match wins, so the order matters.
KIND_HINTS = [
    ("cover letter", r"cover[ _-]?letter|dear (hiring|recruit|sir|madam|team)"),
    ("certificate", r"certif|license|licence|credential|badge"),
    ("award", r"award|honou?r|dean'?s list|scholarship|recognition|accolade|commendation"),
    ("transcript", r"transcript|cumulative gpa|credits earned|semester gpa"),
    ("resume", r"resume|résumé|curriculum vitae|\bcv\b"),
]


def _kind(filename: str, text: str) -> str:
    """A best guess at what the document is: "cover letter", "certificate", "award", "transcript", "resume" or "document"."""
    for source in (filename.lower(), text[:1500].lower()):
        for kind, pattern in KIND_HINTS:
            if re.search(pattern, source):
                return kind
    return "document"


def all_documents() -> list[dict]:
    """Every extra document, oldest first. Each one holds id, name, kind, text, chars, added_at, sha1 and stored_as."""
    return db.kv_get("profile.documents") or []


def listing() -> list[dict]:
    """The documents for the dashboard: everything but their text."""
    return [{key: doc[key] for key in LISTED} for doc in all_documents()]


def _save(docs: list[dict]) -> None:
    """Store the list, stamp the change for answers_watcher(), and tell open dashboards."""
    db.kv_set("profile.documents", docs)
    db.kv_set("profile.documents_changed_at", time.time())
    bus.publish("documents", listing())


def add(filename: str, data: bytes) -> dict:
    """Read one document and keep it. Returns its listing entry. The same file added again changes nothing and comes back
    with "duplicate": True. Raises extract.ExtractError when no text can be read (a scanned image, an unsupported type),
    and ValueError when MAX_DOCUMENTS are kept already."""
    docs = all_documents()
    sha1 = hashlib.sha1(data).hexdigest()
    same = next((doc for doc in docs if doc["sha1"] == sha1), None)
    if same:
        return {**{key: same[key] for key in LISTED}, "duplicate": True}
    if len(docs) >= MAX_DOCUMENTS:
        raise ValueError(f"You can keep up to {MAX_DOCUMENTS} documents. Remove one first.")
    text = extract.extract_text(filename, data, min_chars=MIN_CHARS).strip()
    # A file name with no folder parts and no characters Windows forbids.
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", Path(filename or "document.txt").name).strip() or "document.txt"
    doc_id = uuid.uuid4().hex[:12]
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    stored = DOCS_DIR / f"{doc_id} {name}"
    stored.write_bytes(data)
    doc = {"id": doc_id, "name": name, "kind": _kind(name, text), "text": text, "chars": len(text), "added_at": db.now(),
           "sha1": sha1, "stored_as": stored.name}
    _save(docs + [doc])
    return {key: doc[key] for key in LISTED}


def remove(doc_id: str) -> bool:
    """Forget one document and delete its copy in the data folder. Returns False when there's no such document."""
    docs = all_documents()
    doc = next((d for d in docs if d["id"] == doc_id), None)
    if not doc:
        return False
    (DOCS_DIR / doc.get("stored_as", "")).unlink(missing_ok=True)
    _save([d for d in docs if d["id"] != doc_id])
    return True


def for_prompt() -> str:
    """The documents as a section of the profile build prompt: each one labeled, cut to MAX_CHARS_EACH, and all together cut
    to MAX_CHARS_TOTAL, so a pile of long documents can't crowd out the resume."""
    docs = all_documents()
    if not docs:
        return "(none)"
    parts, budget = [], MAX_CHARS_TOTAL
    for number, doc in enumerate(docs, 1):
        if budget <= 0:
            parts.append(f"({len(docs) - number + 1} more documents left out: there was too much text)")
            break
        text = doc["text"][:min(MAX_CHARS_EACH, budget)]
        budget -= len(text)
        cut = " (cut short)" if len(text) < len(doc["text"]) else ""
        parts.append(f"--- DOCUMENT {number}: {doc['name']} (looks like: {doc['kind']}){cut} ---\n{text}")
    return "\n\n".join(parts)


def changed_at() -> float | None:
    """When the documents last changed (seconds since the epoch), or None when they never have."""
    return db.kv_get("profile.documents_changed_at")


async def make_main(doc_id: str) -> dict:
    """Make one document the main resume. The old main resume becomes an extra document, so nothing is lost. Before the
    standard answers are saved, the new resume pre-fills them again, like a first import. Returns the new resume's details.
    Raises KeyError for an unknown id, and extract.ExtractError when the document is too short to be a resume."""
    from jobportal.candidate import onboarding, profile  # imported here: both modules sit next to this one and load first
    doc = next((d for d in all_documents() if d["id"] == doc_id), None)
    if not doc:
        raise KeyError(doc_id)
    copy = DOCS_DIR / doc.get("stored_as", "")
    data = copy.read_bytes() if copy.is_file() else doc["text"].encode("utf-8")
    old = profile.resume()
    old_copy = RESUME_DIR / old["stored_as"] if old and old.get("stored_as") else None
    old_data = old_copy.read_bytes() if old_copy and old_copy.is_file() else (old or {}).get("text", "").encode("utf-8")
    answered = bool(profile.standard_answers().get("_saved_at"))
    await onboarding.import_resume(doc["name"], data=data, do_prefill=not answered)
    remove(doc_id)
    if old and old_data.strip():
        try:
            add(old["filename"], old_data)
        except ValueError:  # extract.ExtractError is a ValueError, and so is the document limit
            pass
    return profile.resume_info()
