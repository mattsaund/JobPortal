"""LinkedIn's public job search: the same results a logged-out visitor sees. No account or API key is used.

The guest endpoint (SEARCH) answers with a page of job cards as HTML, which parse_cards reads with regular expressions. A run
searches every query from the search plan in every allowed location (li_locations), plus "<company> <role>" searches for
dream companies when the dream bypass is on.

LinkedIn rate-limits hard, so this collector is slow on purpose: one request at a time, a 1 to 2 second pause between
searches (failed ones included), a 30 second back-off after a block (429, LinkedIn's own 999, or 403), and it gives up after
three of those. Settings caps the number of searches per run (max_requests). The list is shuffled first, so each run covers
a different sample when there are more query and location pairs than the cap.

Full descriptions are fetched later, one posting at a time, by collectors/details.py."""
import asyncio
import random
import re
from urllib.parse import urlencode

from jobportal.core.levels import linkedin_experience
from jobportal.core.textutil import NAME_TO_ABBR, STATES, clean, html_to_text, parse_date
from jobportal.search import plan
from jobportal.search.collectors.base import NATIONWIDE, Ctx, RawJob

SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?"
DREAM_SEARCHES = 12  # dream companies searched by name when the dream bypass is on
BACKOFF_SECONDS = 30  # wait after a block before the next search
MAX_429 = 3  # stop LinkedIn for this run after this many blocks
# How LinkedIn refuses a guest it thinks is too busy: 429 (too many requests), its own 999, and sometimes 403.
BLOCKED_STATUSES = (429, 999, 403)


def li_locations(allowed: list[str]) -> list[tuple[str, dict]]:
    """Turn the allowed locations (the search area) into LinkedIn searches: (location text, extra URL parameters).

    "Nationwide" or "Anywhere in the US" searches the whole United States. "Remote" also searches the whole country but adds
    f_WT=2, LinkedIn's remote work filter. A state, written out or as its two-letter code, becomes "<State name>, United
    States", DC becomes LinkedIn's own name for it, and anything else (a city such as "Pittsburgh, PA") is used as typed."""
    out = []
    for a in allowed:
        a = a.strip()
        low = a.lower()
        if NATIONWIDE.fullmatch(low):
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
    """Read the job cards from one page of LinkedIn's guest search HTML. Each card is an <li>. Returns dicts with id, title,
    company, location and posted (the card's datetime attribute, or None). Cards without a job id or a title are skipped."""
    cards = []
    for card in html.split("<li>")[1:]:
        job_id = re.search(r"urn:li:jobPosting:(\d+)", card)
        title = re.search(r'base-search-card__title[^>]*>(.*?)</h3>', card, re.S)
        company = re.search(r'base-search-card__subtitle[^>]*>(.*?)</h4>', card, re.S)
        location = re.search(r'job-search-card__location[^>]*>(.*?)</span>', card, re.S)
        posted = re.search(r'<time[^>]*datetime="([^"]+)"', card)
        if not (job_id and title):
            continue
        cards.append({"id": job_id.group(1), "title": clean(html_to_text(title.group(1))),
                      "company": clean(html_to_text(company.group(1) if company else "")),
                      "location": clean(html_to_text(location.group(1) if location else "")),
                      "posted": posted.group(1) if posted else None})
    return cards


def _searches(cfg: dict) -> list[tuple[str, str, dict]]:
    """Every (keywords, location, extra parameters) search this run could make, before shuffling and the cap."""
    queries = plan.all_queries(cfg)
    locations = li_locations(cfg["locations"]["allowed"])
    searches = [(q, location, extra) for q in queries for (location, extra) in locations]
    if cfg["locations"].get("dream_bypass"):
        # Dream companies may be anywhere in the US, so look for them by name across the whole country.
        role = (plan.target_roles() or queries or ["jobs"])[0]
        for company in plan.all_dreams(cfg)[:DREAM_SEARCHES]:
            searches.append((f"{company} {role}", "United States", {}))
    return searches


async def collect(ctx: Ctx) -> list[RawJob]:
    """Run the LinkedIn searches for this run and return the unique postings, in search order.

    Titles skip the level check (strict_titles=False) because the f_E experience filter already asks LinkedIn for the
    user's levels. found_url is the posting itself."""
    sc = ctx.cfg["sources"]["linkedin"]
    ctx.host_limit("www.linkedin.com", 1)
    searches = _searches(ctx.cfg)
    if not searches:
        ctx.log("linkedin", "skipped: no search queries or locations yet (answer the standard questions first)", "warn")
        return []
    experience = sc.get("experience") or linkedin_experience(plan.levels(ctx.cfg))
    random.shuffle(searches)
    searches = searches[: int(sc.get("max_requests", 70))]
    out, seen, blocked, made = [], set(), 0, 0
    for i, (keywords, location, extra) in enumerate(searches):
        if ctx.cancel.is_set():
            break
        if i:  # every search waits its turn, a failed or blocked one too, so LinkedIn never sees a burst
            await asyncio.sleep(1.0 + random.random() * 1.2)
        made += 1
        params = {"keywords": keywords, "location": location,
                  "f_TPR": sc.get("time_window", "r2592000"),  # posted within this many seconds ("r2592000" = 30 days)
                  "f_E": experience,  # experience levels: 1 internship, 2 entry, 3 associate, 4 mid-senior, 5 director
                  "start": 0,  # the first page of results only
                  **extra}
        try:
            r = await ctx.request("GET", SEARCH + urlencode(params), retries=1)
        except Exception as e:  # noqa: BLE001 (one failed search shouldn't end the others)
            ctx.log("linkedin", f"request failed: {e}", "warn")
            continue
        if r.status_code in BLOCKED_STATUSES:
            blocked += 1
            ctx.log("linkedin", f"rate limited by LinkedIn (HTTP {r.status_code}), backing off {BACKOFF_SECONDS}s", "warn")
            if blocked >= MAX_429:
                ctx.log("linkedin", "stopping LinkedIn early (rate limited)", "warn")
                break
            await asyncio.sleep(BACKOFF_SECONDS)
            continue
        if r.status_code != 200:
            continue
        for card in parse_cards(r.text):
            if card["id"] in seen:
                continue
            seen.add(card["id"])
            posting_url = f"https://www.linkedin.com/jobs/view/{card['id']}/"
            out.append(RawJob(source="linkedin", title=card["title"], company=card["company"], url=posting_url,
                              location=card["location"], posted_at=parse_date(card["posted"]),
                              source_detail=f"LinkedIn search: “{keywords}” in {location}", found_url=posting_url,
                              strict_titles=False, meta={"linkedin_id": card["id"]}))
        if i and i % 20 == 0:
            ctx.log("linkedin", f"{i}/{len(searches)} searches, {len(out)} unique postings so far")
    ctx.log("linkedin", f"{made} searches found {len(out)} unique postings")
    return out
