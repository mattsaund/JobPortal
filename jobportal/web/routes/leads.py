"""Leads: the Leads list and a lead's detail page, editing a lead, adding one by hand, re-scoring, and the Tracker and
Contacts pages. Downloads and AI edits of a lead's documents are in documents.py."""
import json
import shutil
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from jobportal.ai import client as ai
from jobportal.candidate import profile
from jobportal.core import bus, db
from jobportal.core.config import APP_STATUSES, LEADS_DIR
from jobportal.core.textutil import coverage
from jobportal.search import pipeline
from jobportal.web import background
from jobportal.web.common import ai_error, lead_or_404

router = APIRouter()

# The tabs on the Leads page and the SQL condition each one shows.
TABS = {
    "ready": "stage='ready' AND app_status IN ('new','saved')",
    "queue": "stage IN ('qualified','packaging','error') AND app_status!='trashed'",
    "filtered": "stage='filtered' AND app_status!='trashed'",
    "closed": "stage='closed' AND app_status!='trashed'",
    "trashed": "app_status='trashed'",
    "all": "app_status!='trashed'",
}
SORTS = {
    "score": "score DESC, id DESC",
    "new": "id DESC",
    "industry": "COALESCE(industry,'~') ASC, score DESC",
    "deadline": "CASE WHEN deadline IS NULL OR deadline='' THEN 1 ELSE 0 END, deadline ASC",
    "posted": "posted_at DESC",
}
# Fields the dashboard may change directly with PATCH /api/leads/{id}. The package is merged separately.
EDITABLE = {"app_status", "notes", "follow_up_at", "resume_md", "cover_md", "title", "company", "location", "deadline", "apply_url",
            "industry", "dream"}
# The Tracker board's columns, left to right.
TRACK = ["saved", "applied", "assessment", "interviewing", "offer", "rejected", "ghosted", "withdrawn"]
CONTACT_FIELDS = ("name", "title", "org", "email", "linkedin", "source_url", "why")


@router.get("/api/leads")
def leads(tab: str = "ready", q: str = "", sort: str = "score", kind: str = "", industry: str = "", dream: int = 0, limit: int = 400):
    """One tab of the Leads page, filtered and sorted, plus the counts for every tab and industry chip."""
    tab_where = TABS.get(tab, TABS["all"])
    where, args = [tab_where], []
    if industry:
        where.append("industry=?")
        args.append(industry)
    if dream:
        where.append("dream=1")
    if q:
        where.append("(title LIKE ? OR company LIKE ? OR location LIKE ? OR source_detail LIKE ?)")
        args += [f"%{q}%"] * 4
    if kind:
        where.append("kind=?")
        args.append(kind)
    rows = db.q(f"SELECT {pipeline.LIST_FIELDS} FROM leads WHERE {' AND '.join(where)} ORDER BY {SORTS.get(sort, SORTS['score'])} LIMIT ?",
                (*args, limit))
    open_questions = profile.open_counts_by_lead()
    for row in rows:
        row["open_q"] = open_questions.get(row["id"], 0)
    # The chips count the whole tab, ignoring the search box and the other filters.
    industries = db.q(f"SELECT industry, COUNT(*) n FROM leads WHERE {tab_where} GROUP BY industry ORDER BY n DESC")
    return {"leads": [db.lead_row(r) for r in rows],
            "counts": {t: db.one(f"SELECT COUNT(*) n FROM leads WHERE {w}")["n"] for t, w in TABS.items()},
            "industries": {r["industry"] or "Other": r["n"] for r in industries},
            "dream_count": db.one(f"SELECT COUNT(*) n FROM leads WHERE {tab_where} AND dream=1")["n"]}


@router.get("/api/leads/{lead_id}")
def lead(lead_id: int):
    """Everything about one lead: the lead itself, its history, which documents are rendered, and its questions."""
    row = lead_or_404(lead_id)
    row["events"] = db.q("SELECT * FROM events WHERE lead_id=? ORDER BY id DESC", (lead_id,))
    folder = LEADS_DIR / str(lead_id)
    row["files"] = {name: (folder / name).exists() for name in ("resume.pdf", "cover_letter.pdf")}
    row["questions"] = [q for q in profile.questions() if q.get("lead_id") == lead_id and q.get("status") in ("open", "answered")]
    return row


def _clear_rendered(folder, *names: str) -> None:
    """Delete rendered files so the next download renders the edited document again."""
    for name in names:
        (folder / name).unlink(missing_ok=True)


@router.patch("/api/leads/{lead_id}")
def patch_lead(lead_id: int, body: dict):
    """Save edits from the lead page: status, notes, follow-up date, the resume and cover letter text, package details.

    Side effects: marking a lead "applied" records the date and schedules a follow-up in 7 days. Editing the resume
    recomputes its keyword coverage. Editing a document deletes its rendered files so downloads stay current."""
    current = lead_or_404(lead_id)
    fields = {k: v for k, v in body.items() if k in EDITABLE}
    if isinstance(body.get("package"), dict):
        fields["package"] = {**(current.get("package") or {}), **body["package"]}
    if "dream" in fields:
        fields["dream"] = 1 if fields["dream"] else 0
        fields["dream_manual"] = fields["dream"]  # remembered, so re-checking the Dream list never overrides the user
    status = fields.get("app_status")
    if status and status != current["app_status"]:
        if status not in APP_STATUSES:
            raise HTTPException(400, "bad status")
        db.add_event(lead_id, "status", f"{current['app_status']} → {status}")
        if status == "applied" and not current.get("applied_at"):
            fields["applied_at"] = date.today().isoformat()
            fields.setdefault("follow_up_at", (date.today() + timedelta(days=7)).isoformat())
    folder = LEADS_DIR / str(lead_id)
    if "resume_md" in fields and fields["resume_md"] != current.get("resume_md"):
        _clear_rendered(folder, "resume.pdf", "resume.docx", "resume.fit")
        keywords = (current.get("package") or {}).get("keywords") or []
        if keywords:
            fields["ats_coverage"], hit, miss = coverage(keywords, fields["resume_md"])
            fields["package"] = {**(fields.get("package") or current.get("package") or {}), "coverage": {"hit": hit, "miss": miss}}
    if "package" in fields:
        shutil.rmtree(folder / "exports", ignore_errors=True)
        if "resume_style" in (body.get("package") or {}):  # a new layout or page limit changes the rendered resume
            _clear_rendered(folder, "resume.pdf", "resume.docx", "resume.fit")
    if "cover_md" in fields and fields["cover_md"] != current.get("cover_md"):
        _clear_rendered(folder, "cover_letter.pdf", "cover_letter.docx")
    db.update_lead(lead_id, **fields)
    summary = pipeline.lead_summary(lead_id)
    bus.publish("lead", summary)
    return summary


@router.post("/api/leads/{lead_id}/events")
def add_event(lead_id: int, body: dict):
    """Add a note (or another event) to a lead's history."""
    lead_or_404(lead_id)
    db.add_event(lead_id, body.get("type", "note"), body.get("text", ""))
    return {"ok": True}


@router.post("/api/leads/{lead_id}/questions/generate")
async def lead_gap_questions(lead_id: int):
    """Ask the user 1 to 3 questions whose answers could truthfully strengthen this lead's resume."""
    lead_or_404(lead_id)
    try:
        return {"added": await pipeline.gap_questions(lead_id)}
    except ai.AIError as e:
        raise ai_error(e)


@router.post("/api/leads/{lead_id}/apply-answers")
async def lead_apply_answers(lead_id: int):
    """Rework this lead's resume with the answers just given (in the background)."""
    lead_or_404(lead_id)
    background.spawn(pipeline.apply_answers(lead_id), error_title="Couldn't update the resume", lead_id=lead_id)
    return {"ok": True}


@router.post("/api/leads/{lead_id}/package")
async def rebuild_package(lead_id: int):
    """Build (or rebuild) the full application package for one lead, in the background."""
    lead_or_404(lead_id)
    background.spawn(pipeline.build_package(lead_id), error_title="Package failed", lead_id=lead_id)
    return {"ok": True}


@router.post("/api/leads/manual")
async def add_manual_lead(body: dict):
    """Add a job the user found: a link, the posting text, or both. Its package starts building right away."""
    url, text = (body.get("url") or "").strip(), (body.get("text") or "").strip()
    if not url and not text:
        raise HTTPException(400, "paste a URL or the job text")
    lead_id = pipeline.add_manual_lead(url, text, body.get("title") or "", body.get("company") or "", body.get("location", ""),
                                       body.get("kind", "posting"))
    background.spawn(pipeline.build_package(lead_id), error_title="Package failed", lead_id=lead_id)
    return pipeline.lead_summary(lead_id)


@router.post("/api/leads/retriage")
async def retriage():
    """Re-score waiting and filtered leads against the current profile (in the background; it toasts its own results)."""
    background.spawn(pipeline.retriage_leads(reason="manual"), error_title="Re-scoring failed")
    return {"ok": True}


@router.post("/api/leads/retag-industries")
async def retag_industries():
    """Re-tag every lead's industry with AI, in the background, then refresh the Leads page."""
    async def retag():
        updated = await pipeline.retag_industries()
        bus.publish("toast", {"title": "Industries re-tagged", "body": f"{updated} leads updated"})
        bus.publish("lead", None)
    background.spawn(retag(), error_title="Re-tag failed")
    return {"ok": True}


@router.get("/api/tracker")
def tracker():
    """The Tracker board: leads by application status, follow-ups due by tomorrow, response rate and applications per week."""
    rows = db.q(f"SELECT {pipeline.LIST_FIELDS} FROM leads WHERE app_status IN ({','.join('?' * len(TRACK))}) ORDER BY updated_at DESC", TRACK)
    columns = {status: [] for status in TRACK}
    for row in rows:
        columns[row["app_status"]].append(db.lead_row(row))
    applied = db.one("SELECT COUNT(*) n FROM leads WHERE applied_at IS NOT NULL")["n"]
    responded = db.one("SELECT COUNT(*) n FROM leads WHERE applied_at IS NOT NULL AND app_status IN ('assessment','interviewing','offer','rejected')")["n"]
    due = db.q(f"SELECT {pipeline.LIST_FIELDS} FROM leads WHERE follow_up_at IS NOT NULL AND follow_up_at <= ? "
               "AND app_status IN ('applied','assessment','interviewing') ORDER BY follow_up_at", ((date.today() + timedelta(days=1)).isoformat(),))
    weekly = db.q("SELECT strftime('%Y-%W', applied_at) wk, COUNT(*) n FROM leads WHERE applied_at IS NOT NULL GROUP BY wk ORDER BY wk DESC LIMIT 12")
    return {"columns": columns,
            "stats": {"applied": applied, "responded": responded, "response_rate": round(responded / applied, 3) if applied else 0,
                      "interviewing": len(columns["interviewing"]) + len(columns["assessment"]), "offers": len(columns["offer"])},
            "due": [db.lead_row(r) for r in due], "weekly": weekly}


@router.get("/api/contacts")
def contacts():
    """Every contact found for every lead (recruiters, hiring managers, alumni), for the Contacts page."""
    out = []
    for row in db.q("SELECT id, title, company, app_status, package FROM leads WHERE app_status!='trashed' AND package!='{}'"):
        for i, contact in enumerate(json.loads(row["package"] or "{}").get("contacts") or []):
            out.append({**contact, "idx": i, "lead_id": row["id"], "lead_title": row["title"], "lead_company": row["company"],
                        "lead_status": row["app_status"]})
    return out


@router.post("/api/leads/{lead_id}/contacts/{idx}")
def update_contact(lead_id: int, idx: int, body: dict):
    """Change one of a lead's contacts. idx -1 adds a contact; {"delete": true} removes one; anything else updates it."""
    lead = lead_or_404(lead_id)
    package = lead.get("package") or {}
    people = package.get("contacts") or []
    if idx == -1:
        people.append({k: body.get(k, "") for k in CONTACT_FIELDS} | {"email_confidence": "found" if body.get("email") else "unknown"})
    elif 0 <= idx < len(people) and body.get("delete"):
        removed = people.pop(idx)
        db.add_event(lead_id, "contact", f"removed {removed.get('name')}")
    elif 0 <= idx < len(people):
        people[idx].update({k: v for k, v in body.items() if k in ("status", "notes", "email_confidence", *CONTACT_FIELDS)})
        if body.get("status"):
            db.add_event(lead_id, "contact", f"{people[idx].get('name')}: {body['status']}")
    else:
        raise HTTPException(404)
    package["contacts"] = people
    db.update_lead(lead_id, package=package)
    return {"ok": True, "contacts": people}
