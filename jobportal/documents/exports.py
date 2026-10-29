"""Downloads. Turns a lead's documents into the files the dashboard offers: PDF, Word (DOCX), Markdown, plain text, CSV, email
(.eml) and one zip with everything. Saved resumes in the library download the same way.

A lead's documents are its resume, cover letter, interview prep, company brief, application answers, outreach emails,
contacts and the original posting. Rendered resume and cover letter files are kept in the lead's folder in the data folder
(leads/<id>/). Editing a document deletes its rendered files (routes/leads.py), so the next download shows the edit."""
import csv
import io
import re
import zipfile
from pathlib import Path

from jobportal.candidate import profile
from jobportal.candidate.library import LIB_DIR
from jobportal.core.config import LEADS_DIR
from jobportal.documents import render

DOCS = {"resume", "cover_letter", "interview_prep", "company_intel", "answers", "emails", "contacts", "posting", "linkedin_note"}
TEXT_TYPES = ("pdf", "docx", "md", "txt")  # every document except contacts, which is a CSV table
# "Download everything" (package.zip) holds these. Documents that don't exist yet are left out.
PACKAGE_FILES = ("resume.pdf", "resume.docx", "cover_letter.pdf", "cover_letter.docx", "interview_prep.pdf", "company_intel.pdf",
                 "answers.docx", "emails.md", "contacts.csv", "posting.txt")
CONTACT_COLUMNS = ("name", "title", "org", "email", "email_confidence", "linkedin", "status", "notes", "why", "source_url")


class NotAvailable(Exception):
    """That document doesn't exist yet, or can't be made in that file type."""


def safe_filename(text: str) -> str:
    """A download name that works on every system: letters, digits, spaces and . & ( ) - only, at most 60 characters."""
    return re.sub(r"[^\w .&()-]+", "", text or "").strip()[:60]


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")  # UTF-8 on every system; Windows would otherwise pick a legacy code page
    return path


def document_markdown(lead: dict, doc: str) -> tuple[str, str]:
    """A lead's document as Markdown, with the user's latest edits, and its title."""
    package = lead.get("package") or {}
    if doc == "resume":
        return lead.get("resume_md") or "", "Resume"
    if doc == "cover_letter":
        return lead.get("cover_md") or "", "Cover letter"
    if doc == "interview_prep":
        return package.get("interview_prep_md") or "", "Interview prep"
    if doc == "company_intel":
        return package.get("company_brief_md") or "", "Company intel"
    if doc == "answers":
        return "\n\n".join(f"## {a['question']}\n{a['answer']}" for a in package.get("application_answers") or []), "Application answers"
    if doc == "emails":
        parts = [f"## {e['kind'].replace('_', ' ').title()}\n**To:** {e.get('to_addr') or e.get('to', '')}  \n**Subject:** {e['subject']}\n\n{e['body']}"
                 for e in package.get("emails") or []]
        if package.get("linkedin_note"):
            parts.append(f"## LinkedIn connection note\n{package['linkedin_note']}")
        return "\n\n".join(parts), "Outreach emails"
    if doc == "linkedin_note":
        return package.get("linkedin_note") or "", "LinkedIn note"
    if doc == "posting":
        return f"{lead.get('url') or ''}\n\n{lead.get('description') or ''}", "Job posting"
    return "", doc


def contacts_csv(lead: dict) -> str:
    """The lead's contacts as CSV text, one row per person, with the columns in CONTACT_COLUMNS."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CONTACT_COLUMNS)
    for contact in (lead.get("package") or {}).get("contacts") or []:
        writer.writerow([contact.get(column, "") for column in CONTACT_COLUMNS])
    return buf.getvalue()


async def resume_file(md: str, folder: Path, fmt: str, theme: str, max_pages: int) -> Path:
    """Render a resume as resume.pdf or resume.docx in folder, reusing a file that's already there. The DOCX copies the PDF's
    fitted text size so both look the same, which is why a DOCX always renders the PDF first."""
    out, pdf = folder / f"resume.{fmt}", folder / "resume.pdf"
    if not out.exists():
        if not pdf.exists():
            await render.resume_pdf(md, pdf, theme, max_pages)
        if fmt == "docx":
            render.resume_docx(md, out, render.fit_scale(pdf), theme)
    return out


async def lead_file(lead: dict, name: str) -> tuple[Path, str]:
    """Render one download such as "resume.pdf" or "emails.md". Returns the file and the name to save it as."""
    doc, _, ext = name.rpartition(".")
    if doc not in DOCS or ext not in (("csv",) if doc == "contacts" else TEXT_TYPES):
        raise NotAvailable("unknown export")
    facts = profile.get("facts")
    folder = LEADS_DIR / str(lead["id"])
    md, title = document_markdown(lead, doc)
    if doc == "contacts":
        out = _write_text(folder / "exports" / "contacts.csv", contacts_csv(lead))
    elif not md.strip():
        raise NotAvailable("nothing generated for this document yet")
    elif ext in ("md", "txt"):
        out = _write_text(folder / "exports" / name, md)
    elif doc == "resume":
        style = (lead.get("package") or {}).get("resume_style") or {}
        out = await resume_file(md, folder, ext, style.get("theme", "classic"), style.get("max_pages", 1))
    elif doc == "cover_letter":
        out = folder / f"cover_letter.{ext}"
        if not out.exists():
            folder.mkdir(parents=True, exist_ok=True)
            if ext == "pdf":
                await render.cover_pdf(md, facts, lead["company"], lead["location"], out)
            else:
                render.cover_docx(md, facts, lead["company"], lead["location"], out)
    else:  # interview prep, company intel, answers, emails, LinkedIn note, posting: a titled document
        out = folder / "exports" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        subtitle = f"{lead['title']}, {lead['company']}"
        if ext == "pdf":
            await render.markdown_pdf(md, out, title, subtitle)
        else:
            render.markdown_docx(md, out, title, subtitle)
    label = {"resume": "Resume", "cover_letter": "Cover Letter"}.get(doc, title)
    return out, f"{facts.get('name', '')} {label} - {safe_filename(lead['company'])}.{ext}".strip()


async def package_zip(lead: dict) -> tuple[Path, str]:
    """Every document that exists, plus each outreach email as a ready-to-send .eml file, in one zip."""
    folder = LEADS_DIR / str(lead["id"]) / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "package.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name in PACKAGE_FILES:
            try:
                file, download_name = await lead_file(lead, name)
            except NotAvailable:
                continue
            z.write(file, download_name)
        for i, email in enumerate((lead.get("package") or {}).get("emails") or []):
            z.writestr(f"email-{i + 1}-{email['kind']}.eml", render.eml(email.get("to_addr") or "", email["subject"], email["body"]))
    return path, f"Application package - {safe_filename(lead['company'])} - {safe_filename(lead['title'])}.zip"


def email_file(lead: dict, index: int) -> tuple[bytes, str]:
    """One outreach email as an .eml file that opens as a ready-to-send draft in the user's mail app."""
    emails = (lead.get("package") or {}).get("emails") or []
    if not 0 <= index < len(emails):
        raise NotAvailable("no such email")
    email = emails[index]
    sender = profile.get("facts").get("email", "")
    return render.eml(email.get("to_addr") or "", email["subject"], email["body"], sender), f"{email['kind']}.eml"


async def library_file(item: dict, fmt: str) -> tuple[Path, str]:
    """A saved resume as PDF, DOCX or Markdown."""
    if fmt not in ("pdf", "docx", "md"):
        raise NotAvailable("unknown export")
    folder = LIB_DIR / str(item["id"])
    folder.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        out = _write_text(folder / "resume.md", item["md"])
    else:
        out = await resume_file(item["md"], folder, fmt, item["style"].get("theme", "classic"), item["style"].get("max_pages", 1))
    return out, f"{safe_filename(item['name'])}.{fmt}"
