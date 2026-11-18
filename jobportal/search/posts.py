"""Jobs from posts the user pastes, from Discord servers, Slack workspaces, Facebook groups, LinkedIn, Threads, X or any
other community they're in. Apps can't read those places (their rules bar automated access, and most need a sign-in), but
the user can see the posts and copy them. The AI finds each opening in the pasted text, each one becomes a lead, and the
new leads are scored like any a search finds (pipeline.retriage_leads), so the good ones are queued for their packages.

Key ideas:
- Only what the posts say. The AI copies titles, companies, places, links and contacts from the text and never invents
  them (prompts.POSTS_SYSTEM). A link has to appear in the paste to be kept.
- A job that's already a lead isn't added twice: the same company, title and state, or the same link.
- The text is the user's own copy of what they can see. Nothing is fetched from the community itself.

Called by web/routes/leads.py for the Paste posts dialog on Leads."""
import json

from jobportal.ai import client as ai, prompts
from jobportal.core import background, bus, db
from jobportal.core.textutil import fingerprint, parse_date, url_key
from jobportal.search import pipeline
from jobportal.search.packages import insert_lead

MIN_TEXT = 20  # less than this can't hold a post
MAX_TEXT = 60000  # characters of the paste the AI reads
MAX_JOBS = 50  # openings kept from one paste


async def add_posts(text: str, where: str = "") -> dict:
    """Find the job openings in pasted posts and add each new one as a lead. `where` names the community ("Nursing jobs
    Discord"), for the lead's source. One AI call (stage "triage"), then a background re-score of the new leads. Returns
    {"found", "added", "existing", "lead_ids"}. Raises ValueError for a paste too short to hold a post, and ai.AIError when
    the AI fails."""
    text, where = (text or "").strip(), (where or "").strip()[:80]
    if len(text) < MIN_TEXT:
        raise ValueError("Paste at least one whole post.")
    out = await ai.run(f"WHERE THE POSTS ARE FROM: {where or 'not given'}\n\nPOSTS:\n{text[:MAX_TEXT]}", system=prompts.POSTS_SYSTEM,
                       schema=prompts.POSTS_SCHEMA, stage="triage", purpose="pasted-posts", label="read pasted posts", timeout=600)
    jobs = [job for job in out.get("jobs") or [] if isinstance(job, dict)][:MAX_JOBS]
    source = "Pasted posts" + (f" from {where}" if where else "")
    added, existing = [], 0
    for job in jobs:
        field = lambda name: str(job.get(name) or "").strip()[:500]  # noqa: E731
        title, company, location, url = field("title")[:200], field("company")[:200], field("location")[:200], field("url")
        if not title:
            continue
        if url and (not url.lower().startswith(("http://", "https://")) or url not in text):
            url = ""  # a link has to come from the paste itself
        key = fingerprint(company, title, location)
        if db.one("SELECT id FROM leads WHERE fingerprint=?", (key,)) or (url and db.one("SELECT id FROM leads WHERE url_key=?", (url_key(url),))):
            existing += 1
            continue
        description = "\n".join(line for line in (field("details"), f"How to apply: {field('contact')}" if field("contact") else "") if line)
        now = db.now()
        lead_id = insert_lead({"fingerprint": key, "url_key": url_key(url), "url": url, "title": title, "company": company,
                               "location": location, "kind": "posting", "source": "paste", "sources": '["paste"]',
                               "source_detail": source, "description": description, "posted_at": parse_date(field("posted")),
                               "score": 0, "stage": "filtered", "app_status": "new", "created_at": now, "updated_at": now,
                               "found": json.dumps([{"source": "paste", "label": source, "url": url}] if url else [])})
        db.add_event(lead_id, "created", source)
        added.append(lead_id)
    if added:
        bus.publish("lead", None)  # many leads at once: open lists reload
        background.spawn(pipeline.retriage_leads(reason="pasted posts", stages=("filtered",), lead_ids=added),
                         error_title="Scoring the pasted jobs failed")
    return {"found": len(jobs), "added": len(added), "existing": existing, "lead_ids": added}
