"""Job feeds and public APIs, one collector function per source: Hacker News "Who is hiring?", The Muse, USAJobs, Reddit,
Mastodon, remote job boards (Remotive, RemoteOK), the user's own RSS or Atom feeds, Bluesky, and two optional aggregators that
need the user's own API key (Adzuna, and Google Jobs through SerpAPI).

Each function is a collector, `async fn(ctx) -> list[RawJob]`, listed in collectors/__init__.py. Search words come from
search/plan.py. For early-career users (every level picked is internship or entry) most sources search intern and new-grad
wording instead of the user's queries.

Social sources (Hacker News comments, Reddit, Mastodon, Bluesky) return posts, not postings: the title is the post's first
line and strict_titles is False. A post is kept only when it matches the user's level or roles (_post_re) and also uses a
hiring word. Each function's docstring notes its site's limits and API parameters."""
import asyncio
import random
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode

from jobportal.core.levels import early_career, muse_levels, posting_regex
from jobportal.core.textutil import CITY_STATE, NAME_TO_ABBR, STATES, clean, html_to_text, parse_date
from jobportal.search import plan
from jobportal.search.collectors.base import NATIONWIDE, Ctx, RawJob

# Besides matching the user's level or roles, a social post must use one of these words to count as a hiring post.
HIRING_RE = re.compile(r"hiring|opening|apply|position|role|looking for|job", re.I)  # Mastodon and Bluesky
REDDIT_HIRING_RE = re.compile(r"hiring|opening|apply|position|role|looking for", re.I)  # the same list without "job"
HN_HIRING_RE = re.compile(r"hiring|apply|we're looking|open (role|position)|join us|email me", re.I)  # HN comment search
HN_ROLE_RE = re.compile(r"engineer|developer|scientist|analyst|designer|manager", re.I)  # a part of an HN first line that is a role
HN_PLACE_RE = re.compile(r"remote|onsite|hybrid|, [A-Z]{2}\b|\bNYC\b|\bSF\b", re.I)  # a part that is a place
HN_API = "https://hn.algolia.com/api/v1"  # Hacker News search by Algolia: public, no key needed
HN_COMMENT_DAYS = 45  # how far back the HN comment search looks


def _early(ctx: Ctx) -> bool:
    """True when the user searches only at internship and entry level."""
    return early_career(plan.levels(ctx.cfg))


def _post_re(ctx: Ctx) -> re.Pattern:
    """Which free-text posts count: early-career wording for students and new grads, the user's role words for everyone
    else (core/levels.py posting_regex)."""
    return posting_regex(plan.levels(ctx.cfg), plan.role_words(ctx.cfg))


def _queries(ctx: Ctx, n: int) -> list[str]:
    """The first n search queries (plan.all_queries, which falls back to the target roles)."""
    return plan.all_queries(ctx.cfg)[:n]


# ------------------------------------------------------------------ Hacker News
def _hn_first_line(text: str, post_re: re.Pattern) -> tuple[str, str, str]:
    """Read (company, role, location) from the first line of a "Who is hiring?" comment, which by convention reads
    "Company | Role | Location | ...". A part missing from the line comes back empty; a missing company is "Unknown"."""
    head = text.split("\n", 1)[0]
    # Parts are separated by a pipe, or by a hyphen or a long dash with spaces around it.
    parts = [p.strip() for p in re.split(r"\s+[|\u2014\u2013]\s+|\s\|\s?|\s-\s", head) if p.strip()]
    company = parts[0][:80] if parts else "Unknown"
    role = next((p for p in parts[1:] if post_re.search(p) or HN_ROLE_RE.search(p)), "")
    location = next((p for p in parts[1:] if HN_PLACE_RE.search(p)), "")
    return company, role, location


async def hackernews(ctx: Ctx) -> list[RawJob]:
    """Hacker News, through its Algolia search API, in two passes.

    1. The newest monthly "Ask HN: Who is hiring?" threads (Settings sets how many). The whoishiring account posts them along
       with other monthly threads, which the title check leaves out. Each top-level comment is one employer, and its first
       line is split into company, role and location. A comment with no recognizable role gets the title
       "Opening (see comment)", which the package AI later replaces.
    2. A search of every comment from the last HN_COMMENT_DAYS days for hiring wording at the user's level ("internship",
       "new grad hiring") or "hiring <query>", which catches offers posted outside the monthly threads.

    Only comments that match _post_re are kept. Titles skip the level check (strict_titles=False)."""
    n_threads = int(ctx.cfg["sources"]["hackernews"].get("threads", 2))
    d = await ctx.get_json(f"{HN_API}/search_by_date?tags=story,author_whoishiring&hitsPerPage=12")
    threads = [h for h in d.get("hits", []) if "who is hiring" in h.get("title", "").lower()][:n_threads]
    post_re, early = _post_re(ctx), _early(ctx)
    out = []
    for thread in threads:
        item = await ctx.get_json(f"{HN_API}/items/{thread['objectID']}", timeout=60)  # the whole comment tree, which is large
        for comment in item.get("children", []):  # top-level comments only: replies are discussion, not offers
            text = html_to_text(comment.get("text") or "")
            if not text or not post_re.search(text):
                continue
            company, role, location = _hn_first_line(text, post_re)
            out.append(RawJob(source="hackernews", title=(role or "Opening (see comment)")[:140], company=company,
                              url=f"https://news.ycombinator.com/item?id={comment['id']}", location=location, description=text[:8000],
                              posted_at=parse_date(comment.get("created_at")), strict_titles=False,
                              source_detail=f"HN {thread['title']}, comment by {comment.get('author')}"))
    since = int(time.time()) - HN_COMMENT_DAYS * 86400  # numericFilters takes Unix seconds
    seen = {j.url for j in out}
    terms = ["internship", "interns hiring", "new grad hiring", "hiring intern"] if early else [f"hiring {q}" for q in _queries(ctx, 4)]
    for term in terms:
        try:
            d = await ctx.get_json(f"{HN_API}/search_by_date?" + urlencode(
                {"query": term, "tags": "comment", "numericFilters": f"created_at_i>{since}", "hitsPerPage": 100}))
        except Exception:  # noqa: BLE001 (one failed search shouldn't end the others)
            continue
        for hit in d.get("hits", []):
            url = f"https://news.ycombinator.com/item?id={hit['objectID']}"
            text = html_to_text(hit.get("comment_text") or "")
            if url in seen or not (post_re.search(text) and HN_HIRING_RE.search(text)):
                continue
            seen.add(url)
            out.append(RawJob(source="hackernews", title=clean(text.split("\n")[0])[:140], company="", url=url, description=text[:6000],
                              posted_at=parse_date(hit.get("created_at")), strict_titles=False, found_url=url,
                              source_detail=f"HN comment by {hit.get('author')} on “{(hit.get('story_title') or '')[:80]}”"))
    ctx.log("hackernews", f"{len(threads)} hiring threads plus a comment search found {len(out)} relevant mentions")
    return out


# ------------------------------------------------------------------ The Muse
def _muse_locations(allowed: list[str]) -> list[str]:
    """Turn the allowed locations into values The Muse's location filter knows, which are "City, ST" names. A state becomes
    up to six well-known cities in it (from core/textutil.CITY_STATE), DC becomes "Washington, DC", anything remote becomes
    "Flexible / Remote" (The Muse's name for remote work), and anything else is passed as typed."""
    out = []
    for a in allowed:
        low = a.lower().strip()
        if "remote" in low:
            out.append("Flexible / Remote")
            continue
        state = a.upper() if a.upper() in STATES else NAME_TO_ABBR.get(low)
        if re.search(r"\bd\.?c\.?\b", low):
            state = "DC"
        if state:
            cities = [c for c, s in CITY_STATE.items() if s == state and c not in ("washington dc", "washington d.c.")][:6]
            out += [f"{c.title()}, {state}" for c in cities] + (["Washington, DC"] if state == "DC" else [])
        else:
            out.append(a)
    return out


async def themuse(ctx: Ctx) -> list[RawJob]:
    """The Muse's public jobs API (no key needed): newest first, filtered to the user's levels and, unless the search area is
    nationwide, to its locations. Reads up to Settings' page count. Titles skip the level check (strict_titles=False)
    because the API's level filter already applied it."""
    pages = int(ctx.cfg["sources"]["themuse"].get("pages", 8))
    allowed = ctx.cfg["locations"]["allowed"]
    nationwide = any(NATIONWIDE.fullmatch(a.lower().strip()) for a in allowed)
    locations = [] if nationwide else _muse_locations(allowed)
    # Repeated parameters mean "any of these": level=Internship&level=Entry Level&location=...
    base = [("level", lv) for lv in muse_levels(plan.levels(ctx.cfg))] + [("descending", "true")] + [("location", loc) for loc in locations]
    out = []
    for page in range(pages):
        d = await ctx.get_json("https://www.themuse.com/api/public/jobs?" + urlencode(base + [("page", page)]))
        for j in d.get("results", []):
            job_locations = [loc.get("name", "") for loc in j.get("locations", [])]
            out.append(RawJob(source="themuse", title=j.get("name", ""), company=(j.get("company") or {}).get("name", ""),
                              url=(j.get("refs") or {}).get("landing_page", ""), locations=job_locations, location=" | ".join(job_locations),
                              description=html_to_text(j.get("contents", ""))[:12000],
                              posted_at=parse_date(j.get("publication_date")), source_detail="The Muse", strict_titles=False))
        if page + 1 >= d.get("page_count", 0):  # pages are numbered from 0
            break
    ctx.log("themuse", f"{len(out)} postings")
    return out


# ------------------------------------------------------------------ USAJobs
async def usajobs(ctx: Ctx) -> list[RawJob]:
    """USAJobs, the federal government's job board, through its search API. It needs a free API key and the email address the
    key was issued to (Settings, Sources); without them this source skips itself. The API wants that email as the
    User-Agent and the key in an Authorization-Key header.

    Searches the first six queries. Early-career users also get the student and recent-graduate hiring paths (Pathways) and
    intern searches. Each search asks for up to 500 postings (the API's maximum) from the last 60 days. Titles skip the level
    check (strict_titles=False): federal titles rarely name a level."""
    sc = ctx.cfg["sources"]["usajobs"]
    if not sc.get("api_key") or not sc.get("email"):
        ctx.log("usajobs", "skipped: add a free API key and email in Sources (developer.usajobs.gov/apirequest). "
                           "The 'Government and public sector' AI mission still covers USAJobs through web search.", "warn")
        return []
    headers = {"Host": "data.usajobs.gov", "User-Agent": sc["email"], "Authorization-Key": sc["api_key"]}
    searches = [{"Keyword": q} for q in _queries(ctx, 6)]
    if _early(ctx):
        searches = [{"HiringPath": "student"}, {"HiringPath": "graduates"}, {"Keyword": "intern"}, {"Keyword": "student trainee"}] + searches
    out, seen = [], set()
    for search in searches:
        params = {"ResultsPerPage": 500, "DatePosted": 60, **search}
        r = await ctx.request("GET", "https://data.usajobs.gov/api/search?" + urlencode(params), headers=headers)
        if r.status_code != 200:
            ctx.log("usajobs", f"HTTP {r.status_code} for {search}", "warn")
            continue
        for result in r.json().get("SearchResult", {}).get("SearchResultItems", []):
            m = result.get("MatchedObjectDescriptor", {})
            if m.get("PositionID") in seen:  # the same position often comes back from several searches
                continue
            seen.add(m.get("PositionID"))
            details = (m.get("UserArea") or {}).get("Details") or {}
            description = "\n\n".join(x for x in [details.get("JobSummary", ""), "\n".join(details.get("MajorDuties") or []),
                                                  m.get("QualificationSummary", ""),
                                                  f"Who may apply: {details.get('WhoMayApply', {}).get('Name', '')}"] if x)
            locations = [loc.get("LocationName", "") for loc in m.get("PositionLocation", [])]
            out.append(RawJob(source="usajobs", title=m.get("PositionTitle", ""),
                              company=f"{m.get('OrganizationName', '')} ({m.get('DepartmentName', '')})",
                              url=m.get("PositionURI", ""), apply_url=(m.get("ApplyURI") or [None])[0],
                              locations=locations, location=" | ".join(locations), description=description[:12000],
                              posted_at=parse_date(m.get("PublicationStartDate")),
                              deadline=parse_date(m.get("ApplicationCloseDate")), strict_titles=False,
                              source_detail="USAJobs" + (f" ({search.get('HiringPath')})" if search.get("HiringPath") else "")))
    ctx.log("usajobs", f"{len(out)} federal postings")
    return out


# ------------------------------------------------------------------ Reddit
async def reddit(ctx: Ctx) -> list[RawJob]:
    """Reddit search, read through its RSS feeds (no account or key needed). Searches each configured subreddit for hiring
    words (intern and new-grad words for early-career users), plus two site-wide "<query> hiring <place>" searches. Every
    search covers the last month, newest first.

    Reddit throttles anonymous feed readers hard: one request at a time, 4 to 7 seconds between searches, no retries, an 8
    second wait after a refusal, and after three refusals the rest are skipped (the AI hunt's social mission still covers
    Reddit). Only posts that read like hiring posts at the user's level are kept."""
    ctx.host_limit("www.reddit.com", 1)
    subreddits = ctx.cfg["sources"].get("reddit", {}).get("subreddits") or ["forhire", "jobbit", "hiring"]
    if _early(ctx):
        query = "(intern OR internship OR hiring OR \"new grad\" OR co-op)"
    else:
        query = "(hiring OR \"we're hiring\" OR \"now hiring\")"
    searches = [(sub, query) for sub in subreddits]
    place = next((a for a in ctx.cfg["locations"].get("allowed", []) if not re.search(r"remote|anywhere", a, re.I)), "")
    for role in _queries(ctx, 2):
        searches.append((None, f"{role} hiring {place}".strip()))  # None: search all of Reddit
    post_re = _post_re(ctx)
    out, failures = [], 0
    for sub, search in searches:
        if ctx.cancel.is_set() or failures >= 3:
            break
        url = (f"https://www.reddit.com/r/{sub}/search.rss?" if sub else "https://www.reddit.com/search.rss?") + urlencode(
            {"q": search, "restrict_sr": "1" if sub else "0",  # restrict_sr=1 keeps the search inside the subreddit
             "sort": "new", "t": "month"})
        try:
            r = await ctx.request("GET", url, retries=0)
            refused = r.status_code != 200
        except Exception:  # noqa: BLE001 (a network error counts as a refusal, so it can't end the whole source)
            refused = True
        if refused:
            failures += 1
            await asyncio.sleep(8)
            continue
        for entry in _parse_feed(r.text):
            text = entry["summary"]
            title_and_text = f"{entry['title']} {text}"
            if not (post_re.search(title_and_text) and REDDIT_HIRING_RE.search(title_and_text)):
                continue
            out.append(RawJob(source="reddit", title=entry["title"][:160], company="", url=entry["link"], description=text[:6000],
                              posted_at=entry["date"], strict_titles=False,
                              source_detail=f"Reddit r/{sub}" if sub else "Reddit search", found_url=entry["link"]))
        await asyncio.sleep(4 + random.random() * 3)
    ctx.log("reddit", f"{len(out)} relevant threads" + (" (rate limited; the AI social mission covers the rest)" if failures >= 3 else ""))
    return out


# ------------------------------------------------------------------ Mastodon
async def mastodon(ctx: Ctx) -> list[RawJob]:
    """Mastodon hashtag timelines, which are public: GET https://<instance>/api/v1/timelines/tag/<tag>?limit=40 returns a
    tag's 40 newest posts (40 is the API's maximum). Every configured instance and tag pair is fetched at once. An
    unreachable instance is skipped without retries. Only posts that read like hiring posts at the user's level are kept."""
    sc = ctx.cfg["sources"]["mastodon"]

    async def tag_timeline(instance: str, tag: str) -> tuple[str, list]:
        """(tag, the tag's newest posts on one instance), with no posts when the instance can't be reached."""
        try:
            return tag, await ctx.get_json(f"https://{instance}/api/v1/timelines/tag/{quote(tag)}?limit=40", retries=0)
        except Exception:  # noqa: BLE001 (a slow or down instance just contributes nothing)
            return tag, []

    timelines = await asyncio.gather(*(tag_timeline(i, t) for i in sc.get("instances", []) for t in sc.get("tags", [])))
    post_re = _post_re(ctx)
    out, seen = [], set()
    for tag, statuses in timelines:
        for status in statuses or []:
            text = html_to_text(status.get("content", ""))
            if status.get("url") in seen or not post_re.search(text) or not HIRING_RE.search(text):
                continue
            seen.add(status.get("url"))  # the same post shows up under several tags and instances
            account = status.get("account") or {}
            out.append(RawJob(source="mastodon", title=clean(text.split("\n")[0])[:140], company=account.get("display_name", ""),
                              url=status.get("url", ""), description=text[:5000], posted_at=parse_date(status.get("created_at")),
                              strict_titles=False, source_detail=f"Mastodon #{tag}, @{account.get('acct', '')}"))
    ctx.log("mastodon", f"{len(out)} hiring posts")
    return out


# ------------------------------------------------------------------ Remote boards
async def remote_boards(ctx: Ctx) -> list[RawJob]:
    """Two remote-only job boards with free public APIs, used only when the search area allows remote work: Remotive,
    searched once per term (up to 100 results each), and RemoteOK, whose whole feed comes in one request. The board's own
    location note, such as "USA only", stays in the location so the location filter can judge it."""
    if not any(re.search(r"remote|anywhere", a, re.I) for a in ctx.cfg["locations"]["allowed"]):
        return []
    out = []
    terms = ["intern", "junior", "entry level", "graduate"] if _early(ctx) else _queries(ctx, 4)
    for term in terms:
        try:
            d = await ctx.get_json("https://remotive.com/api/remote-jobs?" + urlencode({"search": term, "limit": 100}))
            for j in d.get("jobs", []):
                region = j.get("candidate_required_location")
                out.append(RawJob(source="remote", title=j.get("title", ""), company=j.get("company_name", ""), url=j.get("url", ""),
                                  location=f"Remote ({region})" if region else "Remote",
                                  description=html_to_text(j.get("description", ""))[:10000],
                                  posted_at=parse_date(j.get("publication_date")), source_detail="Remotive"))
        except Exception as e:  # noqa: BLE001 (one failed term shouldn't end the others)
            ctx.log("remote", f"remotive: {e}", "warn")
    try:
        d = await ctx.get_json("https://remoteok.com/api")
        for j in d[1:] if isinstance(d, list) else []:  # the first item is RemoteOK's legal notice, not a job
            out.append(RawJob(source="remote", title=j.get("position", ""), company=j.get("company", ""), url=j.get("url", ""),
                              location=f"Remote ({j['location']})" if j.get("location") else "Remote",
                              description=html_to_text(j.get("description", ""))[:10000],
                              posted_at=parse_date(j.get("date")), source_detail="RemoteOK"))
    except Exception as e:  # noqa: BLE001 (Remotive's results are still worth returning)
        ctx.log("remote", f"remoteok: {e}", "warn")
    ctx.log("remote", f"{len(out)} remote postings (pre-filter)")
    return out


# ------------------------------------------------------------------ RSS / Atom
def _child(element: ET.Element, *names: str) -> ET.Element | None:
    """The first child element with one of these tag names (namespace ignored), trying the names in order."""
    for name in names:
        found = next((c for c in element if c.tag.split("}")[-1] == name), None)
        # An Element with no children counts as False, so compare with None instead of testing truthiness.
        if found is not None:
            return found
    return None


def _parse_feed(xml: str) -> list[dict]:
    """Read the items of an RSS feed (<item>) or an Atom feed (<entry>) as dicts with title, link, summary and date. Tag
    namespaces are ignored, so both formats read the same way. Returns [] for anything that isn't valid XML."""
    try:
        root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter():
        if item.tag.split("}")[-1] not in ("item", "entry"):
            continue
        title = _child(item, "title")
        link = _child(item, "link")
        # Atom puts the address in <link href="...">, RSS in the element's text.
        href = (link.get("href") if link is not None and link.get("href") else (link.text if link is not None else "")) or ""
        summary = _child(item, "description", "content", "summary")
        date = _child(item, "pubDate", "published", "updated")
        out.append({"title": clean(html_to_text(title.text if title is not None else "")), "link": href.strip(),
                    "summary": html_to_text(summary.text if summary is not None else ""),
                    "date": parse_date(date.text if date is not None else None)})
    return out


async def rss(ctx: Ctx) -> list[RawJob]:
    """The user's own RSS or Atom feeds (Settings, Sources). Each feed is a plain URL or {"url", "name"}. Every item becomes a
    job titled with the item's headline. Titles skip the level check (strict_titles=False) because headlines aren't
    structured job titles."""
    out = []
    for feed in ctx.cfg["sources"]["rss"].get("feeds", []):
        url = feed["url"] if isinstance(feed, dict) else feed
        name = feed.get("name", url) if isinstance(feed, dict) else url
        try:
            for entry in _parse_feed(await ctx.get_text(url)):
                out.append(RawJob(source="rss", title=entry["title"][:160], company="", url=entry["link"], description=entry["summary"][:8000],
                                  posted_at=entry["date"], strict_titles=False, source_detail=f"RSS: {name}"))
        except Exception as e:  # noqa: BLE001 (one broken feed shouldn't stop the others)
            ctx.log("rss", f"{name}: {e}", "warn")
    if out:
        ctx.log("rss", f"{len(out)} feed items")
    return out


# ------------------------------------------------------------------ Optional aggregators (the user's own API key)
async def adzuna(ctx: Ctx) -> list[RawJob]:
    """Adzuna, a job aggregator with a free API key (Settings, Sources: app_id and app_key); skipped without one. Searches
    the first four queries in every allowed place except remote ones (the whole United States when only remote is allowed):
    the first page of Adzuna's US search, 50 results, posted within the last 45 days."""
    sc = ctx.cfg["sources"]["adzuna"]
    if not (sc.get("app_id") and sc.get("app_key")):
        return []
    out = []
    places = [a for a in ctx.cfg["locations"]["allowed"] if not re.search("remote", a, re.I)] or ["United States"]
    for what in _queries(ctx, 4):
        for where in places:
            params = {"app_id": sc["app_id"], "app_key": sc["app_key"], "what": what, "where": where, "max_days_old": 45,
                      "results_per_page": 50, "content-type": "application/json"}
            try:
                d = await ctx.get_json("https://api.adzuna.com/v1/api/jobs/us/search/1?" + urlencode(params))  # us = country, 1 = page
            except Exception as e:  # noqa: BLE001 (one failed search shouldn't end the others)
                ctx.log("adzuna", str(e), "warn")
                continue
            for j in d.get("results", []):
                out.append(RawJob(source="adzuna", title=clean(html_to_text(j.get("title", ""))), company=(j.get("company") or {}).get("display_name", ""),
                                  url=j.get("redirect_url", ""), location=(j.get("location") or {}).get("display_name", ""),
                                  description=html_to_text(j.get("description", "")), posted_at=parse_date(j.get("created")),
                                  source_detail="Adzuna"))
    ctx.log("adzuna", f"{len(out)} postings")
    return out


async def serpapi(ctx: Ctx) -> list[RawJob]:
    """Google Jobs results through SerpAPI, a paid service used with the user's own API key; skipped without one. Searches
    "<query> <place>" for the first three queries in up to four allowed places, leaving remote places out (so a remote-only
    search area searches nothing here). English results for the United States. The first apply link Google offers becomes
    the posting URL."""
    sc = ctx.cfg["sources"]["serpapi"]
    if not sc.get("api_key"):
        return []
    out = []
    places = [a for a in ctx.cfg["locations"]["allowed"] if not re.search("remote", a, re.I)][:4]
    for q in _queries(ctx, 3):
        for where in places:
            params = {"engine": "google_jobs", "q": f"{q} {where}", "api_key": sc["api_key"], "hl": "en", "gl": "us"}
            try:
                d = await ctx.get_json("https://serpapi.com/search.json?" + urlencode(params))
            except Exception as e:  # noqa: BLE001 (one failed search shouldn't end the others)
                ctx.log("serpapi", str(e), "warn")
                continue
            for j in d.get("jobs_results", []):
                link = next((o.get("link") for o in j.get("apply_options", []) if o.get("link")), j.get("share_link", ""))
                out.append(RawJob(source="google", title=j.get("title", ""), company=j.get("company_name", ""), url=link,
                                  location=j.get("location", ""), description=j.get("description", "")[:12000],
                                  posted_at=parse_date((j.get("detected_extensions") or {}).get("posted_at")),
                                  source_detail=f"Google Jobs via {j.get('via', '')}"))
    ctx.log("serpapi", f"{len(out)} postings")
    return out


# ------------------------------------------------------------------ Bluesky (optional, needs a free app password)
def _bsky_queries(ctx: Ctx) -> list[str]:
    """Bluesky search phrases: intern and new-grad hiring phrases for early-career users ("we're hiring" for everyone else),
    plus "hiring <query>" for the first five queries."""
    roles = _queries(ctx, 5)
    base = ["hiring interns", "summer intern hiring", "hiring new grad", "co-op hiring"] if _early(ctx) else ["we're hiring"]
    return base + [f"hiring {r}" for r in roles]


async def bluesky(ctx: Ctx) -> list[RawJob]:
    """Bluesky post search. Searching needs a signed-in session, so this uses the user's handle and an app password (Settings,
    Sources); without them it skips itself. createSession returns a token, then searchPosts returns the 50 latest posts for
    each phrase. Only posts that read like hiring posts at the user's level are kept."""
    sc = ctx.cfg["sources"].get("bluesky") or {}
    if not (sc.get("handle") and sc.get("app_password")):
        ctx.log("bluesky", "skipped: add your handle and an app password (Bluesky settings, App passwords) in Sources", "warn")
        return []
    session = await ctx.post_json("https://bsky.social/xrpc/com.atproto.server.createSession",
                                  {"identifier": sc["handle"], "password": sc["app_password"]})
    headers = {"Authorization": f"Bearer {session['accessJwt']}"}
    out, seen = [], set()
    post_re = _post_re(ctx)
    for phrase in _bsky_queries(ctx):
        try:
            d = await ctx.get_json("https://bsky.social/xrpc/app.bsky.feed.searchPosts?" + urlencode({"q": phrase, "limit": 50, "sort": "latest"}),
                                   headers=headers)
        except Exception as e:  # noqa: BLE001 (one failed search shouldn't end the others)
            ctx.log("bluesky", f"“{phrase}”: {e}", "warn")
            continue
        for post in d.get("posts", []):
            text = (post.get("record") or {}).get("text", "")
            author = post.get("author") or {}
            # A post's uri ends with its record key, which is also the last part of its web address.
            url = f"https://bsky.app/profile/{author.get('handle')}/post/{post.get('uri', '').rsplit('/', 1)[-1]}"
            if url in seen or not post_re.search(text) or not HIRING_RE.search(text):
                continue
            seen.add(url)
            out.append(RawJob(source="bluesky", title=clean(text.split("\n")[0])[:140], company=author.get("displayName", ""), url=url,
                              description=text, posted_at=parse_date((post.get("record") or {}).get("createdAt")), strict_titles=False,
                              found_url=url, source_detail=f"Bluesky @{author.get('handle')}"))
    ctx.log("bluesky", f"{len(out)} hiring posts")
    return out
