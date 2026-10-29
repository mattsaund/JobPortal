"""Work on one saved lead: building its application package and everything the lead page can do to it afterward.

Who calls it: the search run (pipeline.py) builds a package for each qualified lead with build_package. The lead page reaches
the rest through the web routes (web/routes/leads.py, documents.py and library.py): rebuild a package, ask gap questions,
rework the resume with the answers, swap in a saved resume, re-run the resume check, add a job by hand. Many of those routes
still call these functions as pipeline.<name>; pipeline.py re-exports them so that keeps working.

How a package is built (build_package):
1. When the lead only has a snippet, fetch the full posting (collectors/details.py).
2. One AI call (stage "package", with web research unless Settings turns it off) writes the fit assessment, a tailored
   resume, a cover letter, outreach emails, contacts, interview prep and questions for the candidate (prompts.PACKAGE_SCHEMA).
3. polish_resume checks the resume with fixed rules (documents/resumecheck.py), has an AI recruiter-critic fix what the check
   found, checks again and keeps the better version.
4. The lead is saved as "ready" (or "closed" when the AI found the posting closed), its PDFs are rendered
   (documents/render.py), and the dashboard hears about it through live events (core/bus.py).

The profile only learns from the user here: questions raised while packaging go to the profile's question list
(profile.ask), and apply_answers folds the user's own answers in (profile.update_from_answers).

Side effects: rows in the leads and events tables, files in the lead's folder (LEADS_DIR/<id>), live events, and AI calls on
the user's ChatGPT plan (ai.run raises ai.AIError when the AI fails)."""
import asyncio
import json
import re
import tempfile
from datetime import date
from pathlib import Path

from jobportal.ai import client as ai, prompts
from jobportal.candidate import profile as profile_mod
from jobportal.core import bus, db, settings as settings_mod
from jobportal.core.config import CACHE, LEADS_DIR
from jobportal.core.genres import DEFAULT_INDUSTRIES
from jobportal.core.textutil import coverage, extract_terms, fingerprint, url_key
from jobportal.documents import render, resumecheck
from jobportal.search.collectors import details
from jobportal.search.collectors.base import SOCIAL_SOURCES, Ctx

# The columns the Leads list, the Tracker and live "lead" events carry: everything except the long texts (description,
# resume, cover letter, package), plus has_resume. The dashboard reads these fields by name.
LIST_FIELDS = ("id, title, company, location, kind, category, source, sources, source_detail, posted_at, deadline, score, "
               "verdict, stage, stage_error, app_status, dream, ats_coverage, url, apply_url, created_at, updated_at, "
               "follow_up_at, applied_at, tokens, triage, found, industry, (COALESCE(resume_md, '') != '') AS has_resume")
DEFAULT_STYLE = {"theme": "classic", "max_pages": 1}  # resume layout and page limit when nothing else picked one
# The rendered resume in a lead's folder: the PDF, its Word copy (made on first download) and the PDF's fit info.
RENDERED_RESUME = ("resume.pdf", "resume.docx", "resume.fit")
# Sources whose title, company and location are guesses from a post or a headline, or placeholders for a job added by
# hand. Once the package AI has read the whole posting, its values replace them.
HEADLINE_SOURCES = SOCIAL_SOURCES | {"rss", "manual"}


def _load_lead(lead_id: int) -> dict | None:
    """The whole lead row with its JSON columns decoded, or None."""
    return db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))


def _live_log(source: str, msg: str, level: str = "info") -> None:
    """Log for work outside a search run: shown in the dashboard's live console, not saved to a run log."""
    bus.publish("log", {"source": source, "msg": msg, "level": level})


# ---------------------------------------------------------------- leads


def lead_summary(lead_id: int) -> dict | None:
    """One lead as the Leads list shows it: LIST_FIELDS plus open_q, its number of unanswered questions. None when the lead
    doesn't exist. Callers publish it as a live "lead" event so the dashboard can update that row."""
    row = db.lead_row(db.one(f"SELECT {LIST_FIELDS} FROM leads WHERE id=?", (lead_id,)))
    if row:
        row["open_q"] = profile_mod.open_counts_by_lead().get(lead_id, 0)
    return row


def insert_lead(row: dict) -> int:
    """Insert a lead from a {column: value} dict and return its id. Raises sqlite3.IntegrityError when a lead with the same
    fingerprint already exists. Column names come from our own code, never from user input, so building the SQL from them
    is safe."""
    placeholders = ", ".join("?" * len(row))
    return db.ex(f"INSERT INTO leads({', '.join(row)}) VALUES({placeholders})", tuple(row.values()))


def add_manual_lead(url: str = "", text: str = "", title: str = "", company: str = "", location: str = "",
                    kind: str = "posting") -> int:
    """Save a job the user pasted (a link, the posting text, or both) as a lead that is ready for a package, and return its
    id. Title and company may be empty: building the package fills them in. The caller starts build_package."""
    title = title or "(new lead, analyzing...)"
    now = db.now()
    found = [{"source": "manual", "label": "Added by you", "url": url}] if url else []
    # A collected job's fingerprint is its company, title and state. A pasted job often has none of those yet, so the link
    # (or, without a link, the pasted text) goes into the key. That keeps two different pasted jobs from colliding.
    key = fingerprint(company or url, title + (url or text), location)
    lead_id = insert_lead({"fingerprint": key, "url_key": url_key(url), "url": url, "title": title, "company": company,
                           "location": location, "kind": kind, "source": "manual", "sources": '["manual"]',
                           "source_detail": "Added manually", "description": text, "score": 0, "stage": "qualified",
                           "created_at": now, "updated_at": now, "found": json.dumps(found)})
    db.add_event(lead_id, "created", "Added manually")
    return lead_id


# ---------------------------------------------------------------- building a package


async def _fetch_full_description(ctx: Ctx, lead: dict) -> None:
    """When the lead only has a snippet, fetch the full posting and save it on the lead (and in `lead`). Social posts are
    skipped: their URL is the post itself, which has nothing more to read. A failed fetch is fine, since the package AI can
    still open the URL itself."""
    description = lead.get("description") or ""
    if len(description) >= details.SNIPPET_LENGTH or not lead.get("url") or lead.get("source") in SOCIAL_SOURCES:
        return
    try:
        fetched = await asyncio.wait_for(details.fetch(ctx, lead["url"]), timeout=45)
    except Exception:  # noqa: BLE001 (a missing description only means a thinner package)
        return
    if len(fetched.get("description") or "") > len(description):
        lead["description"] = fetched["description"]
        db.update_lead(lead["id"], description=fetched["description"])


def _package_system(cfg: dict, research: bool) -> str:
    """The package writer's instructions: the package prompt (Settings can override it) with the research and contact rules,
    the resume format and the resume playbook filled in, then today's date, the industry list and the full profile."""
    # str.replace rather than str.format: Settings can swap in the user's own prompt text, and a stray brace in it would make
    # str.format fail.
    system = (prompts.system("package", prompts.PACKAGE_SYSTEM)
              .replace("{research}", prompts.RESEARCH_ON if research else prompts.RESEARCH_OFF)
              .replace("{contacts_rule}", prompts.CONTACTS_ON if research else prompts.CONTACTS_OFF)
              .replace("{resume_format}", prompts.RESUME_FORMAT)
              .replace("{playbook}", settings_mod.resume_playbook(cfg)))
    return system + (f"\n\nTODAY: {date.today().isoformat()}\nINDUSTRIES: {'; '.join(cfg.get('industries') or DEFAULT_INDUSTRIES)}"
                     f"\n\n=== CANDIDATE PROFILE ===\n{profile_mod.full_context()}")


def _package_prompt(lead: dict) -> str:
    """The job as the package writer sees it: the lead's details, triage notes and up to 15,000 characters of posting."""
    triage = lead.get("triage") or {}
    prompt = f"""JOB / LEAD
Title: {lead['title']}
Company: {lead['company']}
Location: {lead['location']}
Kind: {lead['kind']}, category: {lead.get('category') or ''}
Posting URL: {lead['url']}
Apply URL (if known): {lead.get('apply_url') or ''}
Found via: {lead.get('source_detail') or lead.get('source')}
Posted: {lead.get('posted_at') or 'unknown'}. Deadline: {lead.get('deadline') or 'unknown'}
Triage notes: {triage.get('summary', '')} | red flags: {', '.join(triage.get('red_flags') or []) or 'none'}

DESCRIPTION:
{(lead.get('description') or '(none captured: open the URL)')[:15000]}"""
    if lead["kind"] in ("intel", "event", "program"):  # no posting to apply to, so the package works differently
        prompt += ("\n\nNOTE: this is a non-standard lead (" + lead["kind"] + "). Tailor the resume to the team/program, write the cover letter as a "
                   "speculative / program application letter, and make the emails the primary weapon (cold outreach to the best contact).")
    return prompt


def _resume_style(strategy: dict) -> dict:
    """The layout and page limit the package AI chose, made safe: an unknown layout becomes classic, and only a federal
    (USAJobs) resume or an explicit choice of two or more pages gets two pages."""
    theme = strategy.get("theme") if strategy.get("theme") in render.THEMES else "classic"
    two_pages = strategy.get("archetype") == "federal_usajobs" or int(strategy.get("max_pages") or 1) >= 2
    return {"theme": theme, "max_pages": 2 if two_pages else 1}


def _corrections(lead: dict, package: dict, cfg: dict) -> dict:
    """Lead fields the package AI may fill in or correct after reading the whole posting: title, company and location (only
    when empty or a guess, see HEADLINE_SOURCES), industry (when empty, or for a job added by hand), apply_url, deadline."""
    fields = {}
    guessed = lead["source"] in HEADLINE_SOURCES
    for key in ("title", "company", "location"):
        if package.get(key) and (not lead.get(key) or guessed):
            fields[key] = package[key][:200]
    if package.get("industry") in (cfg.get("industries") or DEFAULT_INDUSTRIES) and (not lead.get("industry") or lead["source"] == "manual"):
        fields["industry"] = package["industry"]
    if (package.get("apply_url") or "").startswith("http"):
        fields["apply_url"] = package["apply_url"]
    if re.match(r"\d{4}-\d{2}-\d{2}", package.get("deadline") or ""):
        fields["deadline"] = package["deadline"][:10]
    return fields


async def build_package(lead_id: int, run_id: int | None = None, ctx: Ctx | None = None, log=None) -> dict:
    """Build the full application package for one lead (also used to rebuild one, and for jobs added by hand). See the module
    docstring for the steps.

    run_id, ctx and log come from a search run, so its AI calls, HTTP client and log lines stay together; without them the
    package makes its own client and logs to the live console only. Returns the lead as lead_summary shows it.

    The lead's stage shows progress: "packaging" while working, then "ready" or "closed". A usage cap or a cancel (Stop, or
    the app shutting down) puts it back to "qualified" so the next run builds it; any other failure sets "error" with the
    message. Both are raised again for the caller."""
    cfg = settings_mod.get()
    lead = _load_lead(lead_id)
    if not lead:
        raise ValueError(f"lead {lead_id} not found")
    log = log or _live_log
    db.update_lead(lead_id, stage="packaging", stage_error=None)
    bus.publish("lead", lead_summary(lead_id))
    own_ctx = ctx is None
    ctx = ctx or Ctx(cfg, log, run_id)
    try:
        await _fetch_full_description(ctx, lead)
        research = bool(cfg["run"].get("package_web_research", True))
        package = await ai.run(_package_prompt(lead), system=_package_system(cfg, research), schema=prompts.PACKAGE_SCHEMA,
                               stage="package", purpose="package", web=research, max_steps=24, run_id=run_id, lead_id=lead_id,
                               label=f"package: {lead['company'][:30]}", timeout=1800)
        # The package is saved in the lead's package column. The resume and cover letter get columns of their own, and the
        # AI bookkeeping (_tokens, _tools) isn't saved at all.
        resume_md, cover_md = package.pop("resume_md", ""), package.pop("cover_letter_md", "")
        tokens = package.pop("_tokens", 0)
        package.pop("_tools", None)
        keywords = package.get("keywords") or extract_terms(lead.get("description") or "")
        strategy = package.get("resume_strategy") or {}
        package["resume_style"] = _resume_style(strategy)
        resume_md, review, critic_tokens = await polish_resume(lead, resume_md, keywords, strategy, package["resume_style"],
                                                               run_id=run_id, log=log)
        tokens += critic_tokens
        package["resume_review"] = review
        package["resume_check"] = review.get("check")
        package["original_resume_md"], package["original_cover_md"] = resume_md, cover_md  # for "revert to AI version"
        ats_coverage, hit, miss = coverage(keywords, resume_md)
        package["coverage"] = {"hit": hit, "miss": miss}
        fields = {"package": package, "resume_md": resume_md, "cover_md": cover_md, "ats_coverage": ats_coverage,
                  "tokens": (lead.get("tokens") or 0) + tokens,
                  "score": int((package.get("fit") or {}).get("score") or lead.get("score") or 0),  # the package's fit score wins
                  **_corrections(lead, package, cfg)}
        db.update_lead(lead_id, **fields)
        for q in (package.get("questions_for_candidate") or [])[:3]:
            profile_mod.ask(q.get("question", ""), q.get("why", ""), q.get("field", ""), source=f"{lead['company'][:40]} application",
                            lead_id=lead_id)
        await render_files(lead_id)
        stage = "closed" if package.get("posting_status") == "closed" else "ready"
        db.update_lead(lead_id, stage=stage)
        db.add_event(lead_id, "package", f"Application package generated (fit {fields['score']}, ATS keyword coverage {int(ats_coverage * 100)}%)")
        summary = lead_summary(lead_id)
        bus.publish("lead", summary)
        if stage == "ready":
            bus.publish("toast", {"title": f"New lead ready (fit {summary['score']})", "body": f"{summary['company']}: {summary['title']}", "lead_id": lead_id})
        log("package", f"ready {summary['score']}: {summary['company']}, {summary['title']} ({stage}, {tokens:,} tokens)")
        return summary
    except (ai.UsageLimitError, asyncio.CancelledError):
        # Not the lead's fault: put it back in the queue. (CancelledError isn't an Exception, so it needs naming here.)
        db.update_lead(lead_id, stage="qualified")
        bus.publish("lead", lead_summary(lead_id))
        raise
    except Exception as e:
        db.update_lead(lead_id, stage="error", stage_error=str(e)[:500])
        bus.publish("lead", lead_summary(lead_id))
        raise
    finally:
        if own_ctx:
            await ctx.close()


# ---------------------------------------------------------------- checking and rendering resumes


def _resume_writer_system(prompt_name: str, default: str, cfg: dict) -> str:
    """Instructions for an AI that rewrites a resume: the task prompt (Settings can override it), the resume format rules,
    the resume playbook and the full candidate profile."""
    return (f"{prompts.system(prompt_name, default)}\n\n{prompts.RESUME_FORMAT}\n\n=== RESUME PLAYBOOK ===\n"
            f"{settings_mod.resume_playbook(cfg)}\n\n=== CANDIDATE PROFILE ===\n{profile_mod.full_context()}")


async def check_resume(md: str, keywords: list[str], style: dict, archetype: str = "") -> dict:
    """Score a resume with the fixed-rule checks in documents/resumecheck.py: ATS safety, length, skills the profile backs,
    keyword coverage and style. The page count is one of the checks, so the resume is rendered to a throwaway PDF first.

    Returns the check: score (0 to 100), issues, coverage, unverified_skills, pages and max_pages. Raises when no PDF engine
    is available."""
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE, ignore_cleanup_errors=True) as tmp:
        info = await render.resume_pdf(md, Path(tmp) / "check.pdf", style.get("theme", "classic"), style.get("max_pages", 1))
    return resumecheck.check(md, inventory=profile_mod.get("skills_inventory"), keywords=keywords, pages=info["pages"],
                             max_pages=style.get("max_pages", 1), archetype=archetype, gpa=profile_mod.get("facts").get("gpa", ""))


async def polish_resume(lead: dict, resume_md: str, keywords: list[str], strategy: dict, style: dict, *,
                        run_id: int | None = None, log=None) -> tuple[str, dict, int]:
    """Check a tailored resume, have an AI recruiter-critic fix what the check found, then check the result.

    The critic (stage "revise") gets the check's issues, the posting keywords still missing and the posting, and must stay
    truthful to the profile and the playbook. Its version is kept unless it scores more than 5 points lower. Settings can
    turn the critic off (run.resume_review); then only the first check runs.

    Returns (resume Markdown, review, AI tokens the critic used). The review holds before_score, the critic's changes,
    after_score and the latest check, for the lead page. A failed critic call is logged (when log is given) and skipped; a
    usage cap is raised."""
    cfg = settings_mod.get()
    archetype = strategy.get("archetype", "")
    before = await check_resume(resume_md, keywords, style, archetype)
    review = {"before_score": before["score"], "changes": [], "check": before}
    if not cfg["run"].get("resume_review", True):
        return resume_md, review, 0
    issues = "\n".join(f"- [{i['level']}] {i['text']}" for i in before["issues"]) or "- none"
    _, _, missing = coverage(keywords, resume_md)
    prompt = f"""JOB: {lead['title']} at {lead['company']} ({lead.get('location') or ''})
STRATEGY CHOSEN: {json.dumps(strategy)}
PAGE LIMIT: {style['max_pages']}. LAYOUT: {style['theme']}
AUTOMATED CHECK ISSUES (fix all):
{issues}
POSTING KEYWORDS NOT YET IN THE RESUME: {', '.join(missing) or 'none'} (add only if truthful per the profile / inventory)
JOB DESCRIPTION (excerpt):
{(lead.get('description') or '')[:7000]}

RESUME TO REVIEW:
{resume_md}"""
    try:
        out = await ai.run(prompt, system=_resume_writer_system("resume_review", prompts.RESUME_REVIEW_SYSTEM, cfg),
                           schema=prompts.RESUME_REVIEW_SCHEMA, stage="revise", purpose="resume-review", run_id=run_id,
                           lead_id=lead["id"], label=f"resume critic: {lead['company'][:24]}", timeout=900)
    except ai.UsageLimitError:
        raise
    except ai.AIError as e:
        if log:
            log("package", f"resume review skipped: {e}", "warn")
        return resume_md, review, 0
    after = await check_resume(out["resume_md"], keywords, style, archetype)
    if after["score"] >= before["score"] - 5:  # keep the critic's version unless it clearly made things worse
        resume_md = out["resume_md"]
        review.update(changes=out.get("changes", []), after_score=after["score"], check=after)
    return resume_md, review, out.get("_tokens", 0)


async def render_files(lead_id: int) -> dict:
    """Render the lead's resume and cover letter PDFs into its folder (resume.pdf with resume.fit, and cover_letter.pdf), in
    the lead's chosen layout. Returns what render reported (pages, scale), with "error" set instead of raising when
    rendering failed: the dashboard renders again on download."""
    lead = db.lead_row(db.one("SELECT id, company, location, resume_md, cover_md, package FROM leads WHERE id=?", (lead_id,)))
    facts = profile_mod.get("facts")
    folder = LEADS_DIR / str(lead_id)
    style = (lead.get("package") or {}).get("resume_style") or {}
    info = {}
    try:
        if lead["resume_md"]:
            info["resume"] = await render.resume_pdf(lead["resume_md"], folder / "resume.pdf", style.get("theme", "classic"), style.get("max_pages", 1))
        if lead["cover_md"]:
            info["cover"] = await render.cover_pdf(lead["cover_md"], facts, lead["company"], lead["location"], folder / "cover_letter.pdf")
    except Exception as e:  # noqa: BLE001 (PDFs can be rendered again later from the dashboard)
        info["error"] = str(e)
    return info


def _delete_rendered_resume(lead_id: int) -> None:
    """Delete the lead's rendered resume files so nothing shows the old version. The Word copy is only made on download, so
    it would otherwise stay stale. Deleting the PDF too means a failed render never leaves the old resume behind."""
    folder = LEADS_DIR / str(lead_id)
    for name in RENDERED_RESUME:
        (folder / name).unlink(missing_ok=True)


# ---------------------------------------------------------------- reworking a lead's resume


async def _rework_resume(lead: dict, style: dict, instruction: str, current_md: str, *, purpose: str,
                         label: str) -> tuple[str, dict, int, str]:
    """Ask the AI (stage "revise") to rework a resume for this lead's job by instruction, then polish it with polish_resume.
    Returns (new resume, review, AI tokens used, the AI's summary of what changed)."""
    package = lead.get("package") or {}
    prompt = f"""DOCUMENT TYPE: resume (layout {style['theme']}, page limit {style['max_pages']})
JOB: {lead['title']} at {lead['company']}
JOB DESCRIPTION (excerpt):
{(lead.get('description') or '')[:6000]}

INSTRUCTION: {instruction}

CURRENT DOCUMENT:
{current_md}"""
    out = await ai.run(prompt, system=_resume_writer_system("revise", prompts.REVISE_SYSTEM, settings_mod.get()),
                       schema=prompts.REVISE_SCHEMA, stage="revise", purpose=purpose, lead_id=lead["id"], label=label, timeout=900)
    md, review, critic_tokens = await polish_resume(lead, out["text"], package.get("keywords") or [], package.get("resume_strategy") or {}, style)
    return md, review, out.get("_tokens", 0) + critic_tokens, out.get("change_summary", "")


async def _save_reworked_resume(lead: dict, md: str, review: dict, tokens: int, **package_updates) -> float:
    """Save a new resume on its lead: the review, check and keyword coverage go into the package (with any
    package_updates), the old rendered files are deleted and the PDFs are rendered again. Returns the new keyword coverage
    (0 to 1)."""
    package = lead.get("package") or {}
    ats_coverage, hit, miss = coverage(package.get("keywords") or [], md)
    package.update(resume_review=review, resume_check=review.get("check"), coverage={"hit": hit, "miss": miss}, **package_updates)
    db.update_lead(lead["id"], resume_md=md, package=package, ats_coverage=ats_coverage, tokens=(lead.get("tokens") or 0) + tokens)
    _delete_rendered_resume(lead["id"])
    await render_files(lead["id"])
    return ats_coverage


def _mark_answers_applied(lead_id: int) -> None:
    """Mark this lead's answered questions as "applied", so the lead page stops offering to use them again. Writes the
    profile's question list directly (kv profile.questions) and publishes it."""
    questions = profile_mod.questions()
    for q in questions:
        if q.get("lead_id") == lead_id and q.get("status") == "answered":
            q["status"] = "applied"
    db.kv_set("profile.questions", questions)
    bus.publish("questions", questions)


async def gap_questions(lead_id: int) -> int:
    """Ask the candidate 1 to 3 questions whose answers could truthfully strengthen this lead's resume, based on what the
    package found missing. The questions go to the profile's question list, tied to this lead. Returns how many were added
    (repeats of existing questions aren't). Side effects: one AI call (stage "revise") and live events."""
    lead = _load_lead(lead_id)
    package = lead.get("package") or {}
    check = package.get("resume_check") or {}
    prompt = f"""JOB: {lead['title']} at {lead['company']}
KEYWORDS THE RESUME IS MISSING: {', '.join((package.get('coverage') or {}).get('miss', [])) or 'none'}
FIT GAPS: {'; '.join((package.get('fit') or {}).get('gaps', [])) or 'none'}
RESUME CHECK ISSUES: {'; '.join(i['text'] for i in check.get('issues', [])) or 'none'}
POSTING (excerpt):
{(lead.get('description') or '')[:5000]}

TAILORED RESUME:
{lead.get('resume_md') or ''}

=== CANDIDATE PROFILE ===
{profile_mod.full_context()}"""
    out = await ai.run(prompt, system=prompts.GAP_QUESTIONS_SYSTEM, schema=prompts.GAP_QUESTIONS_SCHEMA, stage="revise",
                       purpose="gap-questions", lead_id=lead_id, label=f"questions: {lead['company'][:24]}", timeout=600)
    added = sum(profile_mod.ask(q["question"], q["why"], q.get("field", ""), source=f"{lead['company'][:40]} application", lead_id=lead_id)
                for q in out.get("questions", [])[:3])
    bus.publish("lead", lead_summary(lead_id))  # the Leads list shows each lead's open question count
    return added


async def apply_answers(lead_id: int) -> dict:
    """Use the questions the candidate answered for this lead: add the answers to the profile, then rework the lead's resume
    with them (polished and checked like a new one) and render it again.

    Returns {"ok", "change_summary", "coverage"}, or ok False with a message when nothing is answered yet. Side effects: a
    profile update and two or more AI calls, the lead's resume and package saved, PDFs rendered, the answered questions
    marked "applied", and live events."""
    lead = _load_lead(lead_id)
    answered = [q for q in profile_mod.questions() if q.get("lead_id") == lead_id and q.get("status") == "answered"]
    if not answered:
        return {"ok": False, "message": "Answer at least one question first."}
    await profile_mod.update_from_answers(f"answers for {lead['company']}")
    style = (lead.get("package") or {}).get("resume_style") or dict(DEFAULT_STYLE)
    qa = "\n".join(f"- Q: {q['question']}\n  A: {q.get('answer', '')}" for q in answered)
    instruction = ("The candidate just answered these questions for this application. Use every answer that strengthens the match for THIS\n"
                   "job (new skills, tools, metrics, experience), truthfully and only as far as the answer supports. Keep the page limit.\n"
                   f"{qa}")
    md, review, tokens, summary = await _rework_resume(lead, style, instruction, lead.get("resume_md") or "", purpose="apply-answers",
                                                       label=f"answers into resume: {lead['company'][:20]}")
    # The reworked resume also becomes the version "revert to AI version" goes back to.
    ats_coverage = await _save_reworked_resume(lead, md, review, tokens, original_resume_md=md)
    db.add_event(lead_id, "resume", f"Resume updated with {len(answered)} answer(s): {summary[:300]}")
    _mark_answers_applied(lead_id)
    bus.publish("lead", lead_summary(lead_id))
    bus.publish("toast", {"title": "Resume updated with your answers", "body": summary[:200], "lead_id": lead_id})
    return {"ok": True, "change_summary": summary, "coverage": ats_coverage}


async def use_saved_resume(lead_id: int, item: dict, tailor: bool) -> dict:
    """Put a resume from the library (item, from candidate/library.py) on a lead: exactly as saved, or tailored to this job by
    the AI and then polished. Either way it is checked, saved with its layout, and rendered.

    Returns {"ok", "change_summary", "coverage", "check"}, where check is the resume check's score. Side effects: AI calls when
    tailoring, the lead's resume and package saved, PDFs rendered, and a live event."""
    lead = _load_lead(lead_id)
    package = lead.get("package") or {}
    style = {**DEFAULT_STYLE, **(item.get("style") or {})}
    if tailor:
        instruction = (f"The candidate picked this saved resume (\"{item['name']}\") as the starting point for THIS job. Tailor it: reorder and\n"
                       "re-angle sections, bullets, projects and skills toward the job, mirror its real keywords where the profile backs "
                       "them, swap in stronger\n"
                       "profile material where it fits better, and keep the page limit. Everything must stay true to the candidate profile.")
        md, review, tokens, summary = await _rework_resume(lead, style, instruction, item["md"], purpose="library-tailor",
                                                           label=f"tailor saved resume: {lead['company'][:20]}")
    else:
        md, tokens, summary = item["md"], 0, ""
        check = await check_resume(md, package.get("keywords") or [], style, (package.get("resume_strategy") or {}).get("archetype", ""))
        review = {"before_score": check["score"], "changes": [], "check": check}
    ats_coverage = await _save_reworked_resume(lead, md, review, tokens, resume_style=style, resume_from_library=item["id"])
    db.add_event(lead_id, "resume", f"Resume loaded from your collection: {item['name']}" + (f" (tailored: {summary[:250]})" if tailor else ""))
    bus.publish("lead", lead_summary(lead_id))
    return {"ok": True, "change_summary": summary, "coverage": ats_coverage, "check": review.get("check", {}).get("score")}
