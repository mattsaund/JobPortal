"""LinkedIn public (logged-out) job search. Rate-limited and sequential to stay polite."""
import asyncio
import random
import re
from urllib.parse import urlencode

from jobportal.core.levels import linkedin_experience
from jobportal.core.textutil import NAME_TO_ABBR, STATES, clean, html_to_text, parse_date
from jobportal.search import plan
from jobportal.search.collectors.base import Ctx, RawJob

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"


def li_locations(allowed: list[str]) -> list[tuple[str, dict]]:
    out = []
    for a in allowed:
        a = a.strip()
        low = a.lower()
        if re.fullmatch(r"(anywhere( in the)?( us| usa| united states)?|nationwide|united states|usa|us)", low):
            out.append(("United States", {}))
        elif re.search(r"remote", low):
            out.append(("United States", {"f_WT": "2"}))
        elif re.search(r"\bd\.?c\.?\b|district of columbia", low):
            out.append(("Washington, District of Columbia, United States", {}))
        elif a.upper() in STATES:
            out.append((f"{STATES[a.upper()]}, United States", {}))
        elif low in NAME_TO_ABBR:
            out.append((f"{a.title()}, United States", {}))
        elif a:
            out.append((a, {}))
    return out


def parse_cards(html: str) -> list[dict]:
    cards = []
    for c in html.split("<li>")[1:]:
        jid = re.search(r"urn:li:jobPosting:(\d+)", c)
        title = re.search(r'base-search-card__title[^>]*>(.*?)</h3>', c, re.S)
        comp = re.search(r'base-search-card__subtitle[^>]*>(.*?)</h4>', c, re.S)
        loc = re.search(r'job-search-card__location[^>]*>(.*?)</span>', c, re.S)
        when = re.search(r'<time[^>]*datetime="([^"]+)"', c)
        if not (jid and title):
            continue
        cards.append({"id": jid.group(1), "title": clean(html_to_text(title.group(1))),
                      "company": clean(html_to_text(comp.group(1) if comp else "")),
                      "location": clean(html_to_text(loc.group(1) if loc else "")),
                      "posted": when.group(1) if when else None})
    return cards


async def collect(ctx: Ctx) -> list[RawJob]:
    sc = ctx.cfg["sources"]["linkedin"]
    ctx.host_limit("www.linkedin.com", 1)
    queries = plan.all_queries(ctx.cfg)
    locs = li_locations(ctx.cfg["locations"]["allowed"])
    requests = [(q, l, extra) for q in queries for (l, extra) in locs]
    if ctx.cfg["locations"].get("dream_bypass"):
        role = (plan.target_roles() or queries or ["jobs"])[0]
        for co in plan.all_dreams(ctx.cfg)[:12]:
            requests.append((f"{co} {role}", "United States", {}))
    if not requests:
        ctx.log("linkedin", "skipped: no search queries or locations yet (answer the standard questions first)", "warn")
        return []
    experience = sc.get("experience") or linkedin_experience(plan.levels(ctx.cfg))
    random.shuffle(requests)
    requests = requests[: int(sc.get("max_requests", 70))]
    out, seen, blocked = [], set(), 0
    for i, (q, loc, extra) in enumerate(requests):
        if ctx.cancel.is_set():
            break
        params = {"keywords": q, "location": loc, "f_TPR": sc.get("time_window", "r2592000"),
                  "f_E": experience, "start": 0, **extra}
        try:
            r = await ctx.request("GET", SEARCH + urlencode(params), retries=1)
        except Exception as e:  # noqa: BLE001
            ctx.log("linkedin", f"request failed: {e}", "warn")
            continue
        if r.status_code == 429:
            blocked += 1
            ctx.log("linkedin", "rate limited by LinkedIn, backing off 30s", "warn")
            if blocked >= 3:
                ctx.log("linkedin", "stopping LinkedIn early (rate limited)", "warn")
                break
            await asyncio.sleep(30)
            continue
        if r.status_code != 200:
            continue
        for c in parse_cards(r.text):
            if c["id"] in seen:
                continue
            seen.add(c["id"])
            out.append(RawJob(source="linkedin", title=c["title"], company=c["company"],
                              url=f"https://www.linkedin.com/jobs/view/{c['id']}/", location=c["location"],
                              posted_at=parse_date(c["posted"]), source_detail=f"LinkedIn search: “{q}” in {loc}",
                              found_url=f"https://www.linkedin.com/jobs/view/{c['id']}/", strict_titles=False,
                              meta={"linkedin_id": c["id"]}))
        await asyncio.sleep(1.0 + random.random() * 1.2)
        if i and i % 20 == 0:
            ctx.log("linkedin", f"{i}/{len(plan)} searches, {len(out)} unique postings so far")
    ctx.log("linkedin", f"{len(plan)} searches found {len(out)} unique postings")
    return out
