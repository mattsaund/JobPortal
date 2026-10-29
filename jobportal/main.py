"""HTTP API and dashboard server. It binds to 127.0.0.1 only: JobPortal is a private, single-user tool."""
import asyncio
import json
import re
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import __version__, analysis, bus, claude, db, extract, onboarding, osutil, pipeline, prompts, render
from . import profile as profile_mod
from . import settings as settings_mod
from .collectors import COLLECTORS, ats
from .collectors.base import Ctx, RawJob
from .config import APP_STATUSES, DATA, EFFORTS, LEADS_DIR, MODELS, STATIC
from .textutil import fingerprint, url_key

_tasks: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    t = asyncio.create_task(coro)
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)
    return t


async def auto_runner():
    while True:
        await asyncio.sleep(60)
        try:
            hrs = float(settings_mod.get()["run"].get("auto_run_hours") or 0)
            if hrs <= 0 or bus.state.get("running"):
                continue
            last = db.one("SELECT started_at FROM runs ORDER BY id DESC LIMIT 1")
            if last:
                started = datetime.fromisoformat(last["started_at"])
                if datetime.now(timezone.utc) - started < timedelta(hours=hrs):
                    continue
            await pipeline.start("full")
        except Exception:  # noqa: BLE001 (never let the scheduler die)
            pass


@asynccontextmanager
async def lifespan(_app):
    db.conn()
    bus.state["usage"] = db.kv_get("usage")
    settings_mod.migrate_defaults()
    db.ex("UPDATE leads SET stage='qualified' WHERE stage='packaging'")
    db.ex("UPDATE runs SET status='interrupted', finished_at=? WHERE status='running'", (db.now(),))
    profile_mod.publish_status()
    spawn(auto_runner())
    spawn(profile_mod.answers_watcher(settings_mod.get))
    yield
    claude.kill_all()
    for t in list(_tasks):
        t.cancel()


app = FastAPI(title="JobPortal", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "testserver"}


@app.middleware("http")
async def local_only(request: Request, call_next):
    """Refuse requests whose Host isn't this machine, so a web page can't reach the API through DNS rebinding."""
    host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower()
    if host not in LOCAL_HOSTS:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse("JobPortal only answers requests addressed to 127.0.0.1 or localhost.", status_code=403)
    return await call_next(request)


@app.middleware("http")
async def no_stale_assets(request: Request, call_next):
    """Always revalidate the dashboard's JS/CSS so updates show up without a hard refresh."""
    resp = await call_next(request)
    if request.url.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- live state
@app.get("/api/events")
async def events(request: Request):
    q = bus.subscribe()

    async def gen():
        try:
            yield f"data: {json.dumps({'kind': 'state', 'data': bus.state}, default=str)}\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/meta")
def meta():
    return {"version": __version__, "os": osutil.os_name(), "data_dir": str(DATA), "models": MODELS, "efforts": EFFORTS,
            "statuses": APP_STATUSES, "collectors": [{"key": k, "label": v[0]} for k, v in COLLECTORS.items()],
            "pdf_ready": bool(osutil.find_chrome()), "claude_found": bool(osutil.find_claude(settings_mod.get()["ai"].get("claude_bin")))}


@app.get("/api/stats")
def stats():
    c = lambda sql, a=(): db.one(sql, a)["n"]  # noqa: E731
    week = (date.today() - timedelta(days=7)).isoformat()
    return {
        "ready": c("SELECT COUNT(*) n FROM leads WHERE stage='ready' AND app_status IN ('new','saved')"),
        "queue": c("SELECT COUNT(*) n FROM leads WHERE stage IN ('qualified','packaging','error') AND app_status!='trashed'"),
        "applied": c("SELECT COUNT(*) n FROM leads WHERE applied_at IS NOT NULL"),
        "applied_week": c("SELECT COUNT(*) n FROM leads WHERE applied_at >= ?", (week,)),
        "interviewing": c("SELECT COUNT(*) n FROM leads WHERE app_status IN ('assessment','interviewing')"),
        "offers": c("SELECT COUNT(*) n FROM leads WHERE app_status='offer'"),
        "followups_due": c("SELECT COUNT(*) n FROM leads WHERE follow_up_at IS NOT NULL AND follow_up_at <= ? AND app_status IN ('applied','assessment','interviewing')", (date.today().isoformat(),)),
        "total": c("SELECT COUNT(*) n FROM leads"),
        "state": bus.state,
    }


# ---------------------------------------------------------------- runs
@app.post("/api/run")
async def run(body: dict):
    mode = body.get("mode", "full")
    if mode not in ("full", "boards", "hunt", "backlog"):
        raise HTTPException(400, "bad mode")
    try:
        return {"run_id": await pipeline.start(mode, body.get("overrides"))}
    except RuntimeError as e:
        raise HTTPException(409, str(e))


@app.post("/api/run/stop")
async def stop():
    await pipeline.stop()
    return {"ok": True}


@app.get("/api/runs")
def runs():
    rows = db.q("SELECT * FROM runs ORDER BY id DESC LIMIT 60")
    for r in rows:
        r["stats"] = json.loads(r["stats"] or "{}")
    return rows


@app.get("/api/runs/{run_id}/log")
def run_log(run_id: int, after: int = 0):
    return db.q("SELECT id, ts, level, source, msg FROM run_log WHERE run_id=? AND id>? ORDER BY id LIMIT 3000", (run_id, after))


@app.get("/api/ai_calls")
def ai_calls():
    return db.q("SELECT * FROM ai_calls ORDER BY id DESC LIMIT 200")


# ---------------------------------------------------------------- leads
TABS = {
    "ready": "stage='ready' AND app_status IN ('new','saved')",
    "queue": "stage IN ('qualified','packaging','error') AND app_status!='trashed'",
    "filtered": "stage='filtered' AND app_status!='trashed'",
    "closed": "stage='closed' AND app_status!='trashed'",
    "trashed": "app_status='trashed'",
    "all": "app_status!='trashed'",
}
SORTS = {"score": "score DESC, id DESC", "new": "id DESC", "industry": "COALESCE(industry,'~') ASC, score DESC", "deadline": "CASE WHEN deadline IS NULL OR deadline='' THEN 1 ELSE 0 END, deadline ASC",
         "posted": "posted_at DESC"}


@app.get("/api/leads")
def leads(tab: str = "ready", q: str = "", sort: str = "score", kind: str = "", industry: str = "", dream: int = 0, limit: int = 400):
    where = [TABS.get(tab, TABS["all"])]
    args: list = []
    base_where, base_args = list(where), []
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
    oq = profile_mod.open_counts_by_lead()
    for r in rows:
        r["open_q"] = oq.get(r["id"], 0)
    counts = {t: db.one(f"SELECT COUNT(*) n FROM leads WHERE {w}")["n"] for t, w in TABS.items()}
    by_industry = {r["industry"] or "Other": r["n"] for r in
                   db.q(f"SELECT industry, COUNT(*) n FROM leads WHERE {' AND '.join(base_where)} GROUP BY industry ORDER BY n DESC", base_args)}
    return {"leads": [db.lead_row(r) for r in rows], "counts": counts, "industries": by_industry,
            "dream_count": db.one(f"SELECT COUNT(*) n FROM leads WHERE {' AND '.join(base_where)} AND dream=1")["n"]}


def _lead_or_404(lead_id: int) -> dict:
    r = db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))
    if not r:
        raise HTTPException(404, "lead not found")
    return r


@app.get("/api/leads/{lead_id}")
def lead(lead_id: int):
    r = _lead_or_404(lead_id)
    r["events"] = db.q("SELECT * FROM events WHERE lead_id=? ORDER BY id DESC", (lead_id,))
    d = LEADS_DIR / str(lead_id)
    r["files"] = {f: (d / f).exists() for f in ("resume.pdf", "cover_letter.pdf")}
    r["questions"] = [q for q in profile_mod.questions() if q.get("lead_id") == lead_id and q.get("status") in ("open", "answered")]
    return r


@app.post("/api/leads/{lead_id}/questions/generate")
async def lead_gap_questions(lead_id: int):
    _lead_or_404(lead_id)
    try:
        return {"added": await pipeline.gap_questions(lead_id)}
    except claude.ClaudeError as e:
        raise HTTPException(502, str(e))


@app.post("/api/leads/{lead_id}/apply-answers")
async def lead_apply_answers(lead_id: int):
    _lead_or_404(lead_id)

    async def go():
        try:
            await pipeline.apply_answers(lead_id)
        except Exception as e:  # noqa: BLE001
            bus.publish("toast", {"title": "Couldn't update the resume", "body": str(e)[:200], "level": "error", "lead_id": lead_id})
    spawn(go())
    return {"ok": True}


EDITABLE = {"app_status", "notes", "follow_up_at", "resume_md", "cover_md", "title", "company", "location", "deadline", "apply_url",
            "industry", "dream"}


@app.patch("/api/leads/{lead_id}")
def patch_lead(lead_id: int, body: dict):
    cur = _lead_or_404(lead_id)
    fields = {k: v for k, v in body.items() if k in EDITABLE}
    if "package" in body and isinstance(body["package"], dict):
        pkg = cur.get("package") or {}
        pkg.update(body["package"])
        fields["package"] = pkg
    if "dream" in fields:
        fields["dream"] = 1 if fields["dream"] else 0
        fields["dream_manual"] = fields["dream"]
    st = fields.get("app_status")
    if st and st != cur["app_status"]:
        if st not in APP_STATUSES:
            raise HTTPException(400, "bad status")
        db.add_event(lead_id, "status", f"{cur['app_status']} → {st}")
        if st == "applied" and not cur.get("applied_at"):
            fields["applied_at"] = date.today().isoformat()
            fields.setdefault("follow_up_at", (date.today() + timedelta(days=7)).isoformat())
    d = LEADS_DIR / str(lead_id)
    if "resume_md" in fields and fields["resume_md"] != cur.get("resume_md"):
        for f in ("resume.pdf", "resume.docx", "resume.fit"):
            (d / f).unlink(missing_ok=True)
        kws = (cur.get("package") or {}).get("keywords") or []
        if kws:
            from .textutil import coverage
            cov, hit, miss = coverage(kws, fields["resume_md"])
            fields["ats_coverage"] = cov
            pkg = fields.get("package") or cur.get("package") or {}
            pkg["coverage"] = {"hit": hit, "miss": miss}
            fields["package"] = pkg
    if "package" in fields:
        import shutil
        shutil.rmtree(d / "exports", ignore_errors=True)
        if "resume_style" in (body.get("package") or {}):
            for f in ("resume.pdf", "resume.docx", "resume.fit"):
                (d / f).unlink(missing_ok=True)
    if "cover_md" in fields and fields["cover_md"] != cur.get("cover_md"):
        for f in ("cover_letter.pdf", "cover_letter.docx"):
            (d / f).unlink(missing_ok=True)
    db.update_lead(lead_id, **fields)
    out = pipeline.lead_summary(lead_id)
    bus.publish("lead", out)
    return out


@app.post("/api/leads/{lead_id}/events")
def add_event(lead_id: int, body: dict):
    _lead_or_404(lead_id)
    db.add_event(lead_id, body.get("type", "note"), body.get("text", ""))
    return {"ok": True}


@app.post("/api/leads/{lead_id}/package")
async def regen(lead_id: int):
    _lead_or_404(lead_id)

    async def go():
        try:
            await pipeline.build_package(lead_id)
        except Exception as e:  # noqa: BLE001
            bus.publish("toast", {"title": "Package failed", "body": str(e)[:300], "level": "error", "lead_id": lead_id})

    spawn(go())
    return {"ok": True}


@app.post("/api/leads/{lead_id}/revise")
async def revise(lead_id: int, body: dict):
    lead = _lead_or_404(lead_id)
    doc, instruction, text = body.get("doc", "resume"), body.get("instruction", "").strip(), body.get("text", "")
    if not instruction:
        raise HTTPException(400, "instruction required")
    fmt = prompts.RESUME_FORMAT if doc == "resume" else ""
    system = prompts.system("revise", prompts.REVISE_SYSTEM) + f"\n\n{fmt}\n\n=== CANDIDATE PROFILE ===\n{profile_mod.full_context()}"
    prompt = f"""DOCUMENT TYPE: {doc}
JOB: {lead['title']} at {lead['company']} ({lead['location']})
JOB DESCRIPTION (excerpt):
{(lead.get('description') or '')[:6000]}

INSTRUCTION: {instruction}

CURRENT DOCUMENT:
{text}"""
    try:
        out = await claude.run(prompt, system=system, schema=prompts.REVISE_SCHEMA, stage="revise", purpose=f"revise:{doc}",
                               lead_id=lead_id, label=f"revise {doc}", timeout=600)
    except claude.ClaudeError as e:
        raise HTTPException(502, str(e))
    db.add_event(lead_id, "revise", f"{doc}: {instruction[:200]}")
    return {"text": out["text"], "change_summary": out.get("change_summary", "")}


def _safe(s: str) -> str:
    return re.sub(r"[^\w .&()-]+", "", s or "").strip()[:60]


EXPORT_DOCS = {"resume", "cover_letter", "interview_prep", "company_intel", "answers", "emails", "contacts", "posting", "linkedin_note"}


def _doc_md(lead: dict, doc: str) -> tuple[str, str]:
    """(markdown, title) for a lead's generated document, reflecting the latest edits."""
    pkg = lead.get("package") or {}
    if doc == "interview_prep":
        return pkg.get("interview_prep_md") or "", "Interview prep"
    if doc == "company_intel":
        return pkg.get("company_brief_md") or "", "Company intel"
    if doc == "answers":
        return "\n\n".join(f"## {a['question']}\n{a['answer']}" for a in pkg.get("application_answers") or []), "Application answers"
    if doc == "emails":
        parts = [f"## {e['kind'].replace('_', ' ').title()}\n**To:** {e.get('to_addr') or e.get('to', '')}  \n**Subject:** {e['subject']}\n\n{e['body']}"
                 for e in pkg.get("emails") or []]
        if pkg.get("linkedin_note"):
            parts.append(f"## LinkedIn connection note\n{pkg['linkedin_note']}")
        return "\n\n".join(parts), "Outreach emails"
    if doc == "posting":
        return f"{lead.get('url') or ''}\n\n{lead.get('description') or ''}", "Job posting"
    if doc == "linkedin_note":
        return pkg.get("linkedin_note") or "", "LinkedIn note"
    if doc == "resume":
        return lead.get("resume_md") or "", "Resume"
    if doc == "cover_letter":
        return lead.get("cover_md") or "", "Cover letter"
    return "", doc


def _contacts_csv(lead: dict) -> str:
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "title", "org", "email", "email_confidence", "linkedin", "status", "notes", "why", "source_url"])
    for c in (lead.get("package") or {}).get("contacts") or []:
        w.writerow([c.get(k, "") for k in ("name", "title", "org", "email", "email_confidence", "linkedin", "status", "notes", "why", "source_url")])
    return buf.getvalue()


async def _export_file(lead: dict, name: str) -> tuple:
    """Render one export; returns (path, download filename)."""
    facts = profile_mod.get("facts")
    d = LEADS_DIR / str(lead["id"])
    stem, _, ext = name.rpartition(".")
    if stem not in EXPORT_DOCS or ext not in ("pdf", "docx", "md", "txt", "csv"):
        raise HTTPException(404, "unknown export")
    md, title = _doc_md(lead, stem)
    if stem == "contacts":
        if ext != "csv":
            raise HTTPException(404)
        out = d / "exports" / "contacts.csv"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_contacts_csv(lead))
    elif not md.strip():
        raise HTTPException(404, "nothing generated for this document yet")
    elif ext in ("md", "txt"):
        out = d / "exports" / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md)
    elif stem in ("resume", "cover_letter"):
        out = d / f"{stem}.{ext}"
        style = (lead.get("package") or {}).get("resume_style") or {}
        theme, max_pages = style.get("theme", "classic"), style.get("max_pages", 1)
        if not out.exists():
            if stem == "resume" and ext == "pdf":
                await render.resume_pdf(md, out, theme, max_pages)
            elif stem == "resume":
                if not (d / "resume.pdf").exists():
                    await render.resume_pdf(md, d / "resume.pdf", theme, max_pages)
                render.resume_docx(md, out, render.fit_scale(d / "resume.pdf"), theme)
            elif ext == "pdf":
                await render.cover_pdf(md, facts, lead["company"], lead["location"], out)
            else:
                render.cover_docx(md, facts, lead["company"], lead["location"], out)
    else:
        out = d / "exports" / name
        sub = f"{lead['title']}, {lead['company']}"
        if ext == "pdf":
            await render.markdown_pdf(md, out, title, sub)
        else:
            render.markdown_docx(md, out, title, sub)
    label = {"resume": "Resume", "cover_letter": "Cover Letter"}.get(stem, title)
    return out, f"{facts.get('name', '')} {label} - {_safe(lead['company'])}.{ext}".strip()


@app.get("/api/leads/{lead_id}/export/{name}")
async def export_doc(lead_id: int, name: str):
    lead = _lead_or_404(lead_id)
    if name == "package.zip":
        import zipfile
        d = LEADS_DIR / str(lead_id) / "exports"
        d.mkdir(parents=True, exist_ok=True)
        zpath = d / "package.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
            for n in ("resume.pdf", "resume.docx", "cover_letter.pdf", "cover_letter.docx", "interview_prep.pdf", "company_intel.pdf",
                      "answers.docx", "emails.md", "contacts.csv", "posting.txt"):
                try:
                    path, fname = await _export_file(lead, n)
                    z.write(path, fname)
                except HTTPException:
                    continue
            for i, e in enumerate((lead.get("package") or {}).get("emails") or []):
                z.writestr(f"email-{i + 1}-{e['kind']}.eml", render.eml(e.get("to_addr") or "", e["subject"], e["body"]))
        return FileResponse(zpath, filename=f"Application package - {_safe(lead['company'])} - {_safe(lead['title'])}.zip")
    m = re.fullmatch(r"email-(\d+)\.eml", name)
    if m:
        emails = (lead.get("package") or {}).get("emails") or []
        i = int(m.group(1))
        if i >= len(emails):
            raise HTTPException(404)
        e = emails[i]
        from fastapi.responses import Response
        return Response(render.eml(e.get("to_addr") or "", e["subject"], e["body"], profile_mod.get("facts").get("email", "")),
                        media_type="message/rfc822", headers={"Content-Disposition": f'attachment; filename="{e["kind"]}.eml"'})
    path, fname = await _export_file(lead, name)
    return FileResponse(path, filename=fname)


@app.get("/api/leads/{lead_id}/files/{name}")
async def lead_file(lead_id: int, name: str):
    return await export_doc(lead_id, name)


@app.post("/api/preview")
def preview(body: dict):
    doc, md = body.get("doc", "resume"), body.get("md", "")
    if doc == "resume":
        theme = body.get("theme")
        if not theme and body.get("lead_id"):
            pk = db.lead_row(db.one("SELECT package FROM leads WHERE id=?", (body["lead_id"],)) or {"package": "{}"})
            theme = ((pk or {}).get("package") or {}).get("resume_style", {}).get("theme")
        return HTMLResponse(render.resume_html(md, 1.0, theme if theme in render.THEMES else "classic"))
    if doc == "cover":
        lead = db.one("SELECT company, location FROM leads WHERE id=?", (body.get("lead_id") or 0,)) or {}
        return HTMLResponse(render.cover_html(md, profile_mod.get("facts"), lead.get("company", ""), lead.get("location", "")))
    return HTMLResponse(f"<div class='md'>{render.markdown_html(md)}</div>")


@app.post("/api/leads/manual")
async def manual_lead(body: dict):
    url, text = (body.get("url") or "").strip(), (body.get("text") or "").strip()
    if not url and not text:
        raise HTTPException(400, "paste a URL or the job text")
    title = body.get("title") or "(new lead, analyzing…)"
    company = body.get("company") or ""
    fp = fingerprint(company or url, title + url, body.get("location", ""))
    now = db.now()
    lead_id = db.ex("""INSERT INTO leads(fingerprint,url_key,url,title,company,location,kind,source,sources,source_detail,description,
                       score,stage,created_at,updated_at,found) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fp, url_key(url), url or "", title, company, body.get("location", ""), body.get("kind", "posting"), "manual",
                     '["manual"]', "Added manually", text, 0, "qualified", now, now,
                     json.dumps([{"source": "manual", "label": "Added by you", "url": url}] if url else [])))
    db.add_event(lead_id, "created", "Added manually")

    async def go():
        try:
            await pipeline.build_package(lead_id)
        except Exception as e:  # noqa: BLE001
            bus.publish("toast", {"title": "Package failed", "body": str(e)[:300], "level": "error", "lead_id": lead_id})

    spawn(go())
    return pipeline.lead_summary(lead_id)


# ---------------------------------------------------------------- tracker & contacts
TRACK = ["saved", "applied", "assessment", "interviewing", "offer", "rejected", "ghosted", "withdrawn"]


@app.get("/api/tracker")
def tracker():
    rows = db.q(f"SELECT {pipeline.LIST_FIELDS} FROM leads WHERE app_status IN ({','.join('?' * len(TRACK))}) ORDER BY updated_at DESC", TRACK)
    cols = {s: [] for s in TRACK}
    for r in rows:
        cols[r["app_status"]].append(db.lead_row(r))
    applied = db.one("SELECT COUNT(*) n FROM leads WHERE applied_at IS NOT NULL")["n"]
    responded = db.one("SELECT COUNT(*) n FROM leads WHERE applied_at IS NOT NULL AND app_status IN ('assessment','interviewing','offer','rejected')")["n"]
    due = db.q(f"SELECT {pipeline.LIST_FIELDS} FROM leads WHERE follow_up_at IS NOT NULL AND follow_up_at <= ? AND app_status IN ('applied','assessment','interviewing') ORDER BY follow_up_at",
               ((date.today() + timedelta(days=1)).isoformat(),))
    weekly = db.q("SELECT strftime('%Y-%W', applied_at) wk, COUNT(*) n FROM leads WHERE applied_at IS NOT NULL GROUP BY wk ORDER BY wk DESC LIMIT 12")
    return {"columns": cols, "stats": {"applied": applied, "responded": responded,
                                       "response_rate": round(responded / applied, 3) if applied else 0,
                                       "interviewing": len(cols["interviewing"]) + len(cols["assessment"]), "offers": len(cols["offer"])},
            "due": [db.lead_row(r) for r in due], "weekly": weekly}


@app.get("/api/contacts")
def contacts():
    out = []
    for r in db.q("SELECT id, title, company, app_status, package FROM leads WHERE app_status!='trashed' AND package!='{}'"):
        pkg = json.loads(r["package"] or "{}")
        for i, c in enumerate(pkg.get("contacts") or []):
            out.append({**c, "idx": i, "lead_id": r["id"], "lead_title": r["title"], "lead_company": r["company"],
                        "lead_status": r["app_status"]})
    return out


@app.post("/api/leads/{lead_id}/contacts/{idx}")
def update_contact(lead_id: int, idx: int, body: dict):
    lead = _lead_or_404(lead_id)
    pkg = lead.get("package") or {}
    cs = pkg.get("contacts") or []
    if idx == -1:
        cs.append({k: body.get(k, "") for k in ("name", "title", "org", "email", "linkedin", "source_url", "why")} | {"email_confidence": "found" if body.get("email") else "unknown"})
    elif 0 <= idx < len(cs) and body.get("delete"):
        removed = cs.pop(idx)
        db.add_event(lead_id, "contact", f"removed {removed.get('name')}")
    elif 0 <= idx < len(cs):
        cs[idx].update({k: v for k, v in body.items() if k in ("status", "notes", "email", "name", "title", "org", "linkedin", "why", "email_confidence")})
        if body.get("status"):
            db.add_event(lead_id, "contact", f"{cs[idx].get('name')}: {body['status']}")
    else:
        raise HTTPException(404)
    pkg["contacts"] = cs
    db.update_lead(lead_id, package=pkg)
    return {"ok": True, "contacts": cs}


# ---------------------------------------------------------------- settings & profile
@app.get("/api/settings")
def get_settings():
    return settings_mod.get()


@app.get("/api/resume-playbook")
def get_playbook():
    return {"text": settings_mod.resume_playbook(), "default": settings_mod.default_playbook(),
            "custom": bool((settings_mod.get().get("resume_playbook") or "").strip()), "themes": render.THEMES}


@app.put("/api/settings")
def put_settings(body: dict):
    return settings_mod.save(body)


@app.post("/api/settings/reset")
def reset_settings(body: dict):
    return settings_mod.reset_section(body["path"])


@app.get("/api/profile")
def get_profile():
    return profile_mod.get_all()


@app.put("/api/profile/{key}")
def put_profile(key: str, body: dict):
    try:
        profile_mod.save(key, body["value"])
    except KeyError:
        raise HTTPException(404, "unknown profile section")
    bus.publish("profile", {"ts": db.now(), "mode": "edit", "sections": [key]})
    return {"ok": True}


# ---------------------------------------------------------------- setup (resume + standard questions) and profile status
@app.get("/api/onboarding")
def onboarding_state():
    return onboarding.state()


def _save_to_library(text: str, filename: str):
    """Keep an editable copy of the imported resume in the Resumes collection (runs in the background)."""
    async def go():
        from . import library
        try:
            item = await library.import_text(text, filename)
            bus.publish("toast", {"title": "Saved to your resume collection", "body": item.get("name", "")})
        except Exception:  # noqa: BLE001 (a nice-to-have; the profile build doesn't depend on it)
            pass
    spawn(go())


@app.put("/api/onboarding/resume")
async def onboarding_resume(request: Request, filename: str, save_to_library: int = 1, prefill: int = 1):
    """Receive the resume file (raw body), extract its text and pre-fill the standard questions from it."""
    data = await request.body()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "file too large (25 MB max)")
    try:
        out = await onboarding.import_resume(filename, data=data, do_prefill=bool(prefill))
    except extract.ExtractError as e:
        raise HTTPException(400, str(e))
    if save_to_library:
        _save_to_library(profile_mod.resume()["text"], filename)
    return out


@app.post("/api/onboarding/resume-text")
async def onboarding_resume_text(body: dict):
    name = body.get("name") or "Pasted resume.txt"
    try:
        out = await onboarding.import_resume(name, text=body.get("text") or "", do_prefill=bool(body.get("prefill", True)))
    except extract.ExtractError as e:
        raise HTTPException(400, str(e))
    if body.get("save_to_library", True):
        _save_to_library(profile_mod.resume()["text"], name)
    return out


@app.put("/api/onboarding/answers")
async def onboarding_answers(body: dict):
    try:
        answers = onboarding.save_answers(body.get("answers") or {})
    except ValueError as e:
        raise HTTPException(400, str(e))
    building = False
    if body.get("build", True) and profile_mod.resume():
        spawn(_build("standard answers saved"))
        building = True
    return {"ok": True, "answers": answers, "building": building, "status": profile_mod.status_snapshot()}


async def _build(reason: str):
    try:
        await profile_mod.build(reason)
    except Exception:  # noqa: BLE001 (build() already toasts the error)
        pass


@app.get("/api/profile/status")
def profile_status():
    return profile_mod.status_snapshot()


@app.get("/api/profile/overview")
def profile_overview():
    return profile_mod.overview()


@app.post("/api/profile/build")
async def profile_build():
    if not profile_mod.resume():
        raise HTTPException(400, "Import a resume first.")
    spawn(_build("rebuild (dashboard)"))
    return {"ok": True}


@app.post("/api/profile/sync-answers")
async def profile_sync_answers():
    async def go():
        try:
            await profile_mod.update_from_answers("answers (dashboard)")
        except Exception:  # noqa: BLE001 (update_from_answers already toasts the error)
            pass
    spawn(go())
    return {"ok": True, "pending": len(profile_mod.unsynced())}


@app.post("/api/profile/voice")
async def profile_voice():
    try:
        return await profile_mod.learn_voice("manual")
    except claude.ClaudeError as e:
        raise HTTPException(502, str(e))


@app.get("/api/profile/resume")
def profile_resume():
    r = profile_mod.resume()
    if not r:
        raise HTTPException(404, "no resume imported yet")
    return r


@app.get("/api/profile/{key}/history")
def profile_history(key: str):
    return profile_mod.history(key)


@app.post("/api/open-data-folder")
def open_data_folder():
    """Show the folder that holds the database, generated files and the imported resume."""
    DATA.mkdir(parents=True, exist_ok=True)
    return {"ok": osutil.open_path(DATA), "path": str(DATA)}


@app.get("/api/questions")
def get_questions():
    return profile_mod.questions()


@app.post("/api/questions/answer")
def answer_question(body: dict):
    if not body.get("question") or not str(body.get("answer", "")).strip():
        raise HTTPException(400, "question and answer required")
    qs = profile_mod.answer_question(body["question"], body["answer"])
    return {"ok": True, "questions": qs, "status": profile_mod.status_snapshot()}


@app.post("/api/questions/dismiss")
def dismiss_question(body: dict):
    return profile_mod.dismiss_question(body.get("question", ""))


@app.get("/api/analysis")
def get_analysis():
    return analysis.get()


@app.post("/api/analysis/run")
async def run_analysis():
    async def go():
        try:
            await analysis.run_ai("manual")
        except Exception:  # noqa: BLE001 (run_ai toasts the error)
            pass
    spawn(go())
    return {"ok": True}


@app.get("/api/dreams")
def get_dreams():
    cfg = settings_mod.get()
    plan = (profile_mod.get("search_plan") or {}).get("dream_companies", [])
    excluded = cfg.get("dream_exclude", [])
    mine = {x.strip().lower() for x in cfg.get("dream_companies", [])}
    return {"companies": cfg.get("dream_companies", []),
            "profile_companies": [x for x in settings_mod.plan_dreams(cfg) if x.strip().lower() not in mine],
            "excluded": [x for x in excluded if x.strip().lower() in {p.strip().lower() for p in plan}] or excluded,
            "jobs": cfg.get("dream_jobs", []), "bypass": cfg["locations"].get("dream_bypass", True),
            "jobs_bypass": cfg["locations"].get("dream_jobs_bypass", False),
            "flagged": db.one("SELECT COUNT(*) n FROM leads WHERE dream=1 AND app_status!='trashed'")["n"]}


@app.put("/api/dreams")
def put_dreams(body: dict):
    cfg = settings_mod.get()
    for k in ("companies", "jobs", "excluded"):
        if k in body:
            cfg[{"companies": "dream_companies", "jobs": "dream_jobs", "excluded": "dream_exclude"}[k]] = \
                [str(x).strip() for x in body[k] if str(x).strip()]
    if "bypass" in body:
        cfg["locations"]["dream_bypass"] = bool(body["bypass"])
    if "jobs_bypass" in body:
        cfg["locations"]["dream_jobs_bypass"] = bool(body["jobs_bypass"])
    settings_mod.save(cfg)
    return get_dreams()


@app.post("/api/dreams/recheck")
def recheck_dreams():
    """Re-flag every lead against the current dream list (leads you starred/unstarred by hand are left alone)."""
    cfg = settings_mod.get()
    dreams, jobs = settings_mod.all_dreams(cfg), cfg.get("dream_jobs", [])
    changed = 0
    for r in db.q("SELECT id, company, title, dream FROM leads WHERE dream_manual IS NULL"):
        d = 1 if (pipeline.is_dream(r["company"], dreams) or pipeline.is_dream_job(r["title"], jobs)) else 0
        if d != (r["dream"] or 0):
            db.update_lead(r["id"], dream=d)
            changed += 1
    return {"changed": changed, **get_dreams()}


# ---------------------------------------------------------------- resume library
@app.get("/api/library")
def library_list():
    from . import library
    return library.list_items()


@app.get("/api/library/{item_id}")
def library_get(item_id: int):
    from . import library
    it = library.get(item_id)
    if not it:
        raise HTTPException(404)
    return it


@app.post("/api/library")
def library_create(body: dict):
    """Save a resume: pass md (+ style), or just lead_id to save that lead's current resume."""
    from . import library
    lead = _lead_or_404(int(body["lead_id"])) if body.get("lead_id") else None
    md, style = body.get("md"), body.get("style")
    if lead:
        md = md or lead.get("resume_md")
        style = style or (lead.get("package") or {}).get("resume_style")
    if not (md or "").strip():
        raise HTTPException(400, "nothing to save")
    name = body.get("name") or (f"{lead['company']}: {lead['title']}"[:90] if lead else "")
    return library.create(name, md, style, body.get("source") or ("saved from lead" if lead else "saved"),
                          lead["id"] if lead else None, body.get("tags"), body.get("notes", ""))


@app.get("/api/library/{item_id}/html")
def library_html(item_id: int):
    from . import library
    it = library.get(item_id)
    if not it:
        raise HTTPException(404)
    return HTMLResponse(render.resume_html(it["md"], 1.0, it["style"].get("theme", "classic")))


@app.post("/api/library/{item_id}/revise")
async def library_revise(item_id: int, body: dict):
    from . import library
    it = library.get(item_id)
    if not it:
        raise HTTPException(404)
    cfg = settings_mod.get()
    style = {"theme": "classic", "max_pages": 1, **it["style"]}
    system = (prompts.system("revise", prompts.REVISE_SYSTEM) + f"\n\n{prompts.RESUME_FORMAT}\n\n=== RESUME PLAYBOOK ===\n"
              f"{settings_mod.resume_playbook(cfg)}\n\n=== CANDIDATE PROFILE ===\n{profile_mod.full_context()}")
    prompt = (f"DOCUMENT TYPE: resume (layout {style['theme']}, page limit {style['max_pages']})\nJOB: none, this is a saved resume in the "
              f"candidate's collection (\"{it['name']}\")\n\nINSTRUCTION: {body.get('instruction', '')}\n\nCURRENT DOCUMENT:\n{body.get('text') or it['md']}")
    try:
        out = await claude.run(prompt, system=system, schema=prompts.REVISE_SCHEMA, stage="revise", purpose="library-revise",
                               label=f"revise saved resume: {it['name'][:24]}", timeout=600)
    except claude.ClaudeError as e:
        raise HTTPException(502, str(e))
    return {"text": out["text"], "change_summary": out.get("change_summary", "")}


@app.put("/api/library/import")
async def library_import(request: Request, filename: str, name: str = ""):
    from . import library
    data = await request.body()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "file too large")
    try:
        return await library.import_file(filename, data, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except claude.ClaudeError as e:
        raise HTTPException(502, str(e))


@app.put("/api/library/{item_id}")
def library_update(item_id: int, body: dict):
    from . import library
    return library.update(item_id, body)


@app.delete("/api/library/{item_id}")
def library_delete(item_id: int):
    from . import library
    library.delete(item_id)
    return {"ok": True}


@app.get("/api/library/{item_id}/export/{fmt}")
async def library_export(item_id: int, fmt: str):
    from . import library
    it = library.get(item_id)
    if not it or fmt not in ("pdf", "docx", "md"):
        raise HTTPException(404)
    d = library.LIB_DIR / str(item_id)
    d.mkdir(parents=True, exist_ok=True)
    theme, max_pages = it["style"].get("theme", "classic"), it["style"].get("max_pages", 1)
    out = d / f"resume.{fmt}"
    if fmt == "md":
        out.write_text(it["md"])
    elif not out.exists():
        if fmt == "pdf":
            await render.resume_pdf(it["md"], out, theme, max_pages)
        else:
            if not (d / "resume.pdf").exists():
                await render.resume_pdf(it["md"], d / "resume.pdf", theme, max_pages)
            render.resume_docx(it["md"], out, render.fit_scale(d / "resume.pdf"), theme)
    return FileResponse(out, filename=f"{_safe(it['name'])}.{fmt}")


@app.post("/api/library/{item_id}/apply/{lead_id}")
async def library_apply(item_id: int, lead_id: int, body: dict):
    """Use a saved resume for a lead: as-is, or tailored to that job by the AI."""
    from . import library
    it = library.get(item_id)
    _lead_or_404(lead_id)
    if not it:
        raise HTTPException(404)
    lead = _lead_or_404(lead_id)
    if body.get("backup") and (lead.get("resume_md") or "").strip():
        library.create(f"{lead['company']}: {lead['title']}"[:80] + " (before swap)", lead["resume_md"],
                       (lead.get("package") or {}).get("resume_style"), "saved from lead", lead_id)
    try:
        return await pipeline.use_saved_resume(lead_id, it, bool(body.get("tailor")))
    except claude.ClaudeError as e:
        raise HTTPException(502, str(e))


@app.get("/api/crm")
def crm_book():
    from . import crm
    return crm.book()


@app.post("/api/crm/snooze")
def crm_snooze(body: dict):
    from . import crm
    crm.snooze(body["key"], int(body.get("days", 3)))
    return {"ok": True}


@app.post("/api/leads/retriage")
async def retriage():
    spawn(pipeline.retriage_leads(reason="manual"))
    return {"ok": True}


@app.post("/api/leads/{lead_id}/resume-check")
async def resume_check(lead_id: int):
    lead = _lead_or_404(lead_id)
    pkg = lead.get("package") or {}
    if not lead.get("resume_md"):
        raise HTTPException(404, "no resume yet")
    style = pkg.get("resume_style") or {"theme": "classic", "max_pages": 1}
    chk = await pipeline.check_resume(lead["resume_md"], pkg.get("keywords") or [], style, (pkg.get("resume_strategy") or {}).get("archetype", ""))
    pkg["resume_check"] = chk
    db.update_lead(lead_id, package=pkg)
    return chk


@app.post("/api/leads/retag-industries")
async def retag_industries():
    """Re-tag every lead's industry with AI (the cheap triage model), e.g. after editing the industry list."""
    async def go():
        cfg = settings_mod.get()
        inds = cfg.get("industries") or []
        rows = db.q("SELECT id, company, title, description FROM leads")
        schema = {"type": "object", "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {
            "id": {"type": "integer"}, "industry": {"type": "string"}}, "required": ["id", "industry"]}}}, "required": ["results"]}
        done = 0
        for i in range(0, len(rows), 40):
            batch = [{"id": r["id"], "company": r["company"], "title": r["title"], "description": (r["description"] or "")[:400]} for r in rows[i:i + 40]]
            try:
                out = await claude.run(json.dumps(batch), system=f"Tag each employer's industry with exactly one of: {'; '.join(inds)}. "
                                       "Judge by what the employer does, not the role. Return one result per id.",
                                       schema=schema, stage="triage", purpose="retag-industries", label="retag industries", timeout=600)
            except claude.ClaudeError as e:
                bus.publish("toast", {"title": "Re-tag failed", "body": str(e)[:200], "level": "error"})
                return
            for r in out.get("results", []):
                if r.get("industry") in inds:
                    db.update_lead(int(r["id"]), industry=r["industry"])
                    done += 1
        bus.publish("toast", {"title": "Industries re-tagged", "body": f"{done} leads updated"})
        bus.publish("lead", None)
    spawn(go())
    return {"ok": True}


@app.get("/api/prompts/defaults")
def prompt_defaults():
    return {"triage": prompts.TRIAGE_SYSTEM, "hunt": prompts.HUNT_SYSTEM, "package": prompts.PACKAGE_SYSTEM,
            "revise": prompts.REVISE_SYSTEM, "profile": prompts.PROFILE_SYSTEM, "analysis": prompts.ANALYSIS_SYSTEM,
            "resume_review": prompts.RESUME_REVIEW_SYSTEM}


@app.post("/api/preview/markdown")
def preview_md(body: dict):
    return HTMLResponse(render.markdown_html(body.get("md", "")))


# ---------------------------------------------------------------- sources
@app.post("/api/sources/detect")
async def detect_source(body: dict):
    url = (body.get("url") or "").strip()
    found = ats.detect(url)
    if not found:
        ctx = Ctx(settings_mod.get(), lambda *a, **k: None)
        try:
            html = await ctx.get_text(url)
            m = re.search(r'(https?://[a-z0-9.-]*(?:myworkdayjobs\.com|greenhouse\.io|lever\.co|ashbyhq\.com|icims\.com|ultipro\.com|smartrecruiters\.com)[^"\'\s<>]*)', html, re.I)
            found = ats.detect(m.group(1)) if m else None
        except Exception:  # noqa: BLE001
            found = None
        finally:
            await ctx.close()
    if not found:
        return {"ok": False, "message": "Couldn't find a supported job board (Greenhouse, Lever, Ashby, Workday, UKG, iCIMS, SmartRecruiters) on that page. "
                                         "The AI 'Dream companies' mission can still check it: add the company to your dream companies."}
    board = {"name": body.get("name") or "", **found}
    ctx = Ctx(settings_mod.get(), lambda *a, **k: None)
    try:
        jobs = await ats.HANDLERS[board["ats"]](ctx, {**board, "name": board["name"] or "test"})
        return {"ok": True, "board": board, "count": len(jobs), "sample": [j.title for j in jobs[:8]]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "board": board, "message": f"Detected {board['ats']} but fetching failed: {e}"}
    finally:
        await ctx.close()


@app.post("/api/sources/test/{key}")
async def test_source(key: str):
    if key not in COLLECTORS:
        raise HTTPException(404)
    logs = []
    cfg = settings_mod.get()
    if key == "linkedin":
        cfg["sources"]["linkedin"]["max_requests"] = 4
    ctx = Ctx(cfg, lambda s, m, l="info": logs.append(f"[{l}] {m}"))
    try:
        jobs: list[RawJob] = await asyncio.wait_for(COLLECTORS[key][1](ctx), timeout=300)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "logs": logs}
    finally:
        await ctx.close()
    p = pipeline.Pipeline.__new__(pipeline.Pipeline)
    p.cfg = cfg
    f = cfg["filters"]
    p.inc = re.compile("|".join(f"(?:{x})" for x in f["title_include"]), re.I)
    p.exc = re.compile("|".join(f"(?:{x})" for x in f["title_exclude"]), re.I)
    p.tech = re.compile("|".join(f"(?:{x})" for x in f.get("tech_title", [])) or ".", re.I)
    from .textutil import LocationMatcher
    p.matcher = LocationMatcher(cfg["locations"]["allowed"])
    passed = [j for j in jobs if p.prefilter(j)[0]]
    return {"ok": True, "found": len(jobs), "pass_filters": len(passed), "logs": logs,
            "sample": [{"title": j.title, "company": j.company, "location": j.location, "url": j.url} for j in passed[:12]]}
