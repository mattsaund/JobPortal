"""Job feeds and public APIs, one collector function per source: Hacker News "Who is hiring?", USAJobs, Reddit,
Mastodon, remote job boards (Remotive, RemoteOK, We Work Remotely), the user's own RSS or Atom feeds, Bluesky, and two
optional aggregators that need the user's own API key (Adzuna, and Google Jobs through SerpAPI).

Each function is a collector, `async fn(ctx) -> list[RawJob]`, listed in collectors/__init__.py. Search words come from
search/plan.py. For early-career users (every level picked is internship, apprenticeship or entry level) most sources
search wording for those levels instead of the user's queries.

Adapting to the user's fields: search/plan.fields() names the work genres the user's targets point at, and the maps below
turn them into extra subreddits, Mastodon hashtags and instances, and We Work Remotely feeds. Every
community, hashtag and feed in them was checked to exist and carry job posts (October 2026); add only ones
that do. Hacker News carries tech jobs, so it skips itself unless the user's targets are in tech (plan.in_tech).

Social sources (Hacker News comments, Reddit, Mastodon, Bluesky) return posts, not postings: the title is the post's first
line and strict_titles is False. A post is kept only when it matches the user's level or roles (_post_re) and also uses a
hiring word. Each function's docstring notes its site's limits and API parameters."""
import asyncio
import base64
import html
import random
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from jobportal import __version__
from jobportal.core.genres import DEFAULT_GENRES
from jobportal.core.levels import early_career, posting_regex
from jobportal.core.textutil import (
    REMOTE_RE,
    LocationMatcher,
    clean,
    html_to_text,
    parse_date,
    unique,
)
from jobportal.search import plan
from jobportal.search.collectors.base import NATIONWIDE, Ctx, RawJob

TECH_GENRES = [g["id"] for g in DEFAULT_GENRES if g["group"] == "tech"]


def _for(genres: list[str], values: list[str]) -> dict[str, list[str]]:
    """The same values for several genres, for building the maps below."""
    return {genre: values for genre in genres}


# Subreddits that carry job posts for a field, added to the general ones in Settings.
REDDIT_FIELD_SUBS = {**_for(TECH_GENRES, ["techjobs"]), "art_design": ["DesignJobs", "HungryArtists", "gameDevClassifieds"],
                     "product_design": ["DesignJobs"], "writing_media": ["writingopportunities"]}
REDDIT_REMOTE_SUBS = ["RemoteJobs"]  # added when Remote is allowed
# Reddit's API asks every app to name itself in its User-Agent.
REDDIT_APP = f"JobPortal/{__version__}"
# Mastodon hashtags that carry job posts for a field, and instances whose public hashtag timelines see that field's posts.
MASTODON_FIELD_TAGS = {
    **_for(TECH_GENRES, ["techjobs"]), "nursing": ["nursingjobs", "nursejobs", "healthcarejobs"],
    **_for(["allied_health", "physicians", "behavioral_health", "health_admin", "caregiving"], ["healthcarejobs"]),
    **_for(["teaching", "early_childhood"], ["teachingjobs", "teacherjobs"]), "student_services": ["academicjobs"],
    "library_museum": ["libraryjobs", "museumjobs"], "research": ["sciencejobs", "academicjobs", "postdoc"],
    "environment_ag": ["sciencejobs"], "art_design": ["designjobs", "artjobs"], "product_design": ["designjobs"],
    "writing_media": ["journalismjobs", "journojobs", "writingjobs"], "performing_arts": ["artjobs"], "nonprofit": ["nonprofitjobs"],
}
MASTODON_FIELD_INSTANCES = {**_for(TECH_GENRES, ["hachyderm.io", "fosstodon.org"]), "writing_media": ["journa.host"],
                            "library_museum": ["glammr.us"], "research": ["sciences.social"], "environment_ag": ["sciences.social"]}
MASTODON_INTERNSHIP_TAGS = ["internship", "internships"]  # added for internship searches
MASTODON_REMOTE_TAGS = ["remotejobs"]  # added when Remote is allowed
# We Work Remotely's category feeds for each genre. Fields without their own category read "all other remote jobs", and a
# user with no fields yet reads the feed of every category.
WWR_FEED = "https://weworkremotely.com/categories/{}.rss"
WWR_ALL = "https://weworkremotely.com/remote-jobs.rss"
WWR_CATEGORIES = {
    **_for(["swe", "frontend_mobile", "ml_ai", "data", "embedded_hw", "robotics", "systems_test"], ["remote-programming-jobs"]),
    **_for(["cloud_devops", "cyber", "it_support"], ["remote-devops-sysadmin-jobs"]),
    "product_design": ["remote-product-jobs", "remote-design-jobs"], "art_design": ["remote-design-jobs"],
    "customer_service": ["remote-customer-support-jobs"],
    **_for(["sales", "marketing", "solutions"], ["remote-sales-and-marketing-jobs"]),
    **_for(["finance_accounting", "management_ops", "hr", "legal", "admin_office"], ["remote-management-and-finance-jobs"]),
}
WWR_OTHER = "all-other-remote-jobs"


def _field_values(ctx: Ctx, table: dict[str, list[str]], top: int = 4) -> list[str]:
    """The values `table` gives for the user's strongest fields (plan.fields), without repeats, in field order."""
    out: list[str] = []
    for genre in plan.fields(ctx.cfg, top=top):
        out += [value for value in table.get(genre, []) if value not in out]
    return out


def _remote_allowed(ctx: Ctx) -> bool:
    """True when the search area allows remote work, decided the way the location filter decides it
    (textutil.LocationMatcher): "Anywhere in the US" covers every state but not remote jobs, so it doesn't count here.
    Otherwise the remote boards would collect jobs the filter then drops, every one."""
    return LocationMatcher(ctx.cfg["locations"]["allowed"]).allow_remote


def _places(ctx: Ctx) -> list[str]:
    """The allowed locations an aggregator's location search can take, sorted the way LocationMatcher sorts them: a
    nationwide entry ("Anywhere in the US") becomes "United States", since a place search can't read the phrase, and the
    remote entries are left out. Repeats are dropped."""
    out: list[str] = []
    for entry in ctx.cfg["locations"]["allowed"]:
        if NATIONWIDE.fullmatch(entry.lower().strip()):
            place = "United States"
        elif REMOTE_RE.search(entry):
            continue
        else:
            place = entry.strip()
        if place and place not in out:
            out.append(place)
    return out


def _level_words(ctx: Ctx) -> list[str]:
    """Search words for the user's early-career levels: "intern", "apprentice", "entry level" and the like."""
    picked = set(plan.levels(ctx.cfg))
    words = {"internship": ["intern", "internship"], "apprenticeship": ["apprentice", "apprenticeship"],
             "entry": ["entry level", "new grad", "junior"]}
    return [w for level, ws in words.items() if level in picked for w in ws]

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

    Only comments that match _post_re are kept. Titles skip the level check (strict_titles=False). The threads are almost
    all tech companies hiring tech roles, so this source skips itself unless the user's targets are in tech."""
    if not plan.in_tech(ctx.cfg):
        ctx.log("hackernews", "skipped: Hacker News hiring threads are almost all tech jobs, and your targets aren't in tech")
        return []
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


# ------------------------------------------------------------------ USAJobs
async def usajobs(ctx: Ctx) -> list[RawJob]:
    """USAJobs, the federal government's job board, through its search API. It needs a free API key and the email address the
    key was issued to (the Sources dialog); without them this source skips itself. The API wants that email as the
    User-Agent and the key in an Authorization-Key header.

    Searches the first six queries. Early-career users (every level picked is internship, apprenticeship or entry level)
    who include internship or entry level also get the student and recent-graduate hiring paths (Pathways) and intern
    searches, and any search with apprenticeship gets apprentice and trainee roles. Each search asks for up to 500
    postings (the API's maximum) from the last 60 days. Titles skip the level check (strict_titles=False): federal titles
    rarely name a level."""
    sc = ctx.cfg["sources"]["usajobs"]
    if not sc.get("api_key") or not sc.get("email"):
        ctx.log("usajobs", "skipped: add a free API key and email in Sources (developer.usajobs.gov/apirequest). "
                           "The 'Government and public sector' AI mission still covers USAJobs through web search.", "warn")
        return []
    headers = {"Host": "data.usajobs.gov", "User-Agent": sc["email"], "Authorization-Key": sc["api_key"]}
    searches = [{"Keyword": q} for q in _queries(ctx, 6)]
    picked = set(plan.levels(ctx.cfg))
    if "apprenticeship" in picked:
        searches = [{"Keyword": "apprentice"}, {"Keyword": "trainee"}] + searches
    if picked & {"internship", "entry"} and _early(ctx):
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
                              locations=locations, description=description[:12000],
                              posted_at=parse_date(m.get("PublicationStartDate")),
                              deadline=parse_date(m.get("ApplicationCloseDate")), strict_titles=False,
                              source_detail="USAJobs" + (f" ({search.get('HiringPath')})" if search.get("HiringPath") else "")))
    ctx.log("usajobs", f"{len(out)} federal postings")
    return out


# ------------------------------------------------------------------ Reddit
def _reddit_subreddits(ctx: Ctx) -> list[str]:
    """The subreddits to search: the general hiring ones in Settings, then the ones for the user's fields
    (REDDIT_FIELD_SUBS), then the remote ones when Remote is allowed. Repeats are dropped, ignoring case."""
    subs = list(ctx.cfg["sources"].get("reddit", {}).get("subreddits") or ["forhire", "jobbit", "hiring"])
    subs += _field_values(ctx, REDDIT_FIELD_SUBS) + (REDDIT_REMOTE_SUBS if _remote_allowed(ctx) else [])
    return unique(subs, key=str.lower)


async def _reddit_token(ctx: Ctx, sc: dict) -> str:
    """An app-only token for Reddit's official API, from the user's own free app (Sources dialog: client id and secret), or ""
    without one. A refused key is logged."""
    client_id, secret = str(sc.get("client_id") or "").strip(), str(sc.get("client_secret") or "").strip()
    if not (client_id and secret):
        return ""
    login = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    r = await ctx.request("POST", "https://www.reddit.com/api/v1/access_token", retries=0, content="grant_type=client_credentials",
                          headers={"Authorization": f"Basic {login}", "Content-Type": "application/x-www-form-urlencoded", "User-Agent": REDDIT_APP})
    if r.status_code != 200:
        ctx.log("reddit", f"Reddit refused the app key (HTTP {r.status_code})", "warn")
        return ""
    return r.json().get("access_token") or ""


def _reddit_entries(data: dict) -> list[dict]:
    """The posts in a Reddit API listing, in the shape _parse_feed gives."""
    posts = [child.get("data") or {} for child in (data.get("data") or {}).get("children") or []]
    return [{"title": clean(p.get("title")), "link": f"https://www.reddit.com{p.get('permalink', '')}", "summary": p.get("selftext") or "",
             "date": parse_date(p.get("created_utc"))} for p in posts if p.get("permalink")]


async def reddit(ctx: Ctx) -> list[RawJob]:
    """Reddit search. With the user's own free Reddit app (Sources dialog) it uses the official API. Without one it tries the
    public search feeds, which Reddit now mostly refuses: one refusal ends the source for this run (the AI hunt's social
    mission still covers Reddit).

    Searches each subreddit (_reddit_subreddits) for hiring words (with the words of their levels for early-career users:
    intern, apprentice, new grad), plus two site-wide "<query> hiring <place>" searches. Every search covers the last month,
    newest first, one request at a time with a pause in between. Only posts that read like hiring posts at the user's level
    are kept."""
    sc = ctx.cfg["sources"].get("reddit") or {}
    ctx.host_limit("www.reddit.com", 1)
    ctx.host_limit("oauth.reddit.com", 1)
    subreddits = _reddit_subreddits(ctx)
    if _early(ctx):
        words = [f'"{w}"' if " " in w else w for w in _level_words(ctx)]
        query = "(" + " OR ".join(words + ["hiring"]) + ")"
    else:
        query = "(hiring OR \"we're hiring\" OR \"now hiring\")"
    searches = [(sub, query) for sub in subreddits]
    place = next((a for a in ctx.cfg["locations"].get("allowed", []) if not re.search(r"remote|anywhere", a, re.I)), "")
    for role in _queries(ctx, 2):
        searches.append((None, f"{role} hiring {place}".strip()))  # None: search all of Reddit
    post_re = _post_re(ctx)
    token = await _reddit_token(ctx, sc)
    out, refused = [], False
    for i, (sub, search) in enumerate(searches):
        if ctx.cancel.is_set():
            break
        if i:  # a quiet pace either way: the API allows more, the public feeds much less
            await asyncio.sleep(1.0 if token else 4 + random.random() * 3)
        params = {"q": search, "restrict_sr": "1" if sub else "0",  # restrict_sr=1 keeps the search inside the subreddit
                  "sort": "new", "t": "month"}
        try:
            if token:
                path = f"/r/{sub}/search" if sub else "/search"
                r = await ctx.request("GET", f"https://oauth.reddit.com{path}?" + urlencode({**params, "limit": 100, "raw_json": 1}), retries=0,
                                      headers={"Authorization": f"bearer {token}", "User-Agent": REDDIT_APP})
                entries = _reddit_entries(r.json()) if r.status_code == 200 else []
            else:
                r = await ctx.request("GET", (f"https://www.reddit.com/r/{sub}/search.rss?" if sub else "https://www.reddit.com/search.rss?")
                                      + urlencode(params), retries=0)
                entries = _parse_feed(r.text) if r.status_code == 200 else []
            refused = r.status_code != 200
        except Exception:  # noqa: BLE001 (a network error counts as a refusal, so it can't end the whole run)
            refused = True
        if refused:
            break
        for entry in entries:
            text = entry["summary"]
            title_and_text = f"{entry['title']} {text}"
            if not (post_re.search(title_and_text) and REDDIT_HIRING_RE.search(title_and_text)):
                continue
            out.append(RawJob(source="reddit", title=entry["title"][:160], company="", url=entry["link"], description=text[:6000],
                              posted_at=entry["date"], strict_titles=False,
                              source_detail=f"Reddit r/{sub}" if sub else "Reddit search", found_url=entry["link"]))
    note = ""
    if refused:
        note = " (Reddit refused the request; add a free Reddit app key in Sources, and the AI social mission covers it meanwhile)"
    ctx.log("reddit", f"{len(out)} relevant threads{note}", "warn" if refused else "info")
    return out


# ------------------------------------------------------------------ Mastodon
def _mastodon_plan(ctx: Ctx) -> tuple[list[str], list[str]]:
    """(instances, hashtags) to read: the general ones in Settings, plus the instances and hashtags for the user's fields
    (MASTODON_FIELD_INSTANCES and MASTODON_FIELD_TAGS), internship hashtags for an internship search, and remote ones when
    Remote is allowed. Repeats are dropped, ignoring case."""
    sc = ctx.cfg["sources"]["mastodon"]
    instances = list(sc.get("instances", [])) + _field_values(ctx, MASTODON_FIELD_INSTANCES)
    tags = list(sc.get("tags", [])) + _field_values(ctx, MASTODON_FIELD_TAGS)
    if "internship" in plan.levels(ctx.cfg):
        tags += MASTODON_INTERNSHIP_TAGS
    if _remote_allowed(ctx):
        tags += MASTODON_REMOTE_TAGS
    return unique(instances, key=str.lower), unique(tags, key=str.lower)


async def mastodon(ctx: Ctx) -> list[RawJob]:
    """Mastodon hashtag timelines, which are public: GET https://<instance>/api/v1/timelines/tag/<tag>?limit=40 returns a
    tag's 40 newest posts (40 is the API's maximum). Every instance and hashtag pair (_mastodon_plan) is fetched at once. An
    unreachable instance is skipped without retries. Only posts that read like hiring posts at the user's level are kept."""
    instances, tags = _mastodon_plan(ctx)

    async def tag_timeline(instance: str, tag: str) -> tuple[str, list]:
        """(tag, the tag's newest posts on one instance), with no posts when the instance can't be reached."""
        try:
            return tag, await ctx.get_json(f"https://{instance}/api/v1/timelines/tag/{quote(tag)}?limit=40", retries=0)
        except Exception:  # noqa: BLE001 (a slow or down instance just contributes nothing)
            return tag, []

    timelines = await asyncio.gather(*(tag_timeline(i, t) for i in instances for t in tags))
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
def _wwr_feeds(ctx: Ctx) -> list[str]:
    """The We Work Remotely feeds for the user's fields (WWR_CATEGORIES, with "all other remote jobs" for fields that
    have no category of their own), or the feed of every category while their fields aren't known."""
    genres = plan.fields(ctx.cfg, top=4)
    if not genres:
        return [WWR_ALL]
    slugs: list[str] = []
    for genre in genres:
        slugs += [s for s in WWR_CATEGORIES.get(genre, [WWR_OTHER]) if s not in slugs]
    return [WWR_FEED.format(slug) for slug in slugs]


def _wwr_items(xml: str) -> list[dict]:
    """We Work Remotely's RSS items: title ("Company: Role"), link, description, date, and the region the job is open to
    ("USA Only", "Anywhere in the World"). Returns [] for anything that isn't valid XML."""
    try:
        root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except ET.ParseError:
        return []
    out = []
    for item in root.iter("item"):
        def text(name: str) -> str:
            child = _child(item, name)
            return (child.text or "") if child is not None else ""
        out.append({"title": clean(html_to_text(text("title"))), "link": text("link").strip(), "region": clean(text("region")),
                    "description": html_to_text(text("description")), "date": parse_date(text("pubDate") or None)})
    return out


async def remote_boards(ctx: Ctx) -> list[RawJob]:
    """Six remote-only job boards, used only when the search area allows remote work: Remotive's free API, searched once
    per term; RemoteOK, whose whole feed comes in one request; We Work Remotely's RSS feeds for the user's fields
    (_wwr_feeds), whose titles read "Company: Role"; and three free public APIs (_more_remote_boards): Himalayas and Jobicy,
    searched by term, and Working Nomads' feed. The board's own location note, such as "USA only", stays in the location so
    the location filter can judge it. Each board's link is kept as it gives it, and the lead names the board, as their terms
    ask."""
    if not _remote_allowed(ctx):
        return []
    out = []
    terms = (_level_words(ctx) or ["entry level"]) if _early(ctx) else _queries(ctx, 4)
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
    for feed in _wwr_feeds(ctx):
        try:
            items = _wwr_items(await ctx.get_text(feed))
        except Exception as e:  # noqa: BLE001 (one unreachable feed shouldn't end the others)
            ctx.log("remote", f"we work remotely: {e}", "warn")
            continue
        for item in items:
            company, _, role = item["title"].partition(": ")
            out.append(RawJob(source="remote", title=role or company, company=company if role else "", url=item["link"],
                              location=f"Remote ({item['region']})" if item["region"] else "Remote",
                              description=item["description"][:10000], posted_at=item["date"], source_detail="We Work Remotely"))
    out += await _more_remote_boards(ctx, terms[:3])
    ctx.log("remote", f"{len(out)} remote postings (pre-filter)")
    return out


def _unix_date(value) -> str | None:
    """A Unix time in seconds (Himalayas' dates) as an ISO date, or None."""
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


async def _more_remote_boards(ctx: Ctx, terms: list[str]) -> list[RawJob]:
    """Himalayas (searched per term, 20 a page), Jobicy (per term, its tag search) and Working Nomads (its whole feed): free
    public APIs with no key. A board that fails is logged and skipped."""
    out = []
    for term in terms:
        try:
            d = await ctx.get_json("https://himalayas.app/jobs/api/search?" + urlencode({"q": term, "page": 1}))
            for j in d.get("jobs", []) if isinstance(d, dict) else []:
                places = ", ".join(j.get("locationRestrictions") or [])
                out.append(RawJob(source="remote", title=j.get("title", ""), company=j.get("companyName", ""),
                                  url=j.get("applicationLink") or j.get("guid", ""), location=f"Remote ({places})" if places else "Remote",
                                  description=html_to_text(j.get("description") or j.get("excerpt") or "")[:10000],
                                  posted_at=_unix_date(j.get("pubDate")), source_detail="Himalayas", found_url=j.get("guid") or ""))
        except Exception as e:  # noqa: BLE001 (one failed term shouldn't end the others)
            ctx.log("remote", f"himalayas: {e}", "warn")
        try:
            d = await ctx.get_json("https://jobicy.com/api/jobs?" + urlencode({"count": 50, "tag": term}))
            for j in d.get("jobs", []) if isinstance(d, dict) else []:
                geo = j.get("jobGeo") or ""
                out.append(RawJob(source="remote", title=html.unescape(j.get("jobTitle", "")), company=j.get("companyName", ""),
                                  url=j.get("url", ""), location=f"Remote ({geo})" if geo else "Remote",
                                  description=html_to_text(j.get("jobDescription") or j.get("jobExcerpt") or "")[:10000],
                                  posted_at=parse_date(j.get("pubDate")), source_detail="Jobicy"))
        except Exception as e:  # noqa: BLE001
            ctx.log("remote", f"jobicy: {e}", "warn")
    try:
        d = await ctx.get_json("https://www.workingnomads.com/api/exposed_jobs/")
        for j in d if isinstance(d, list) else []:
            place = j.get("location") or ""
            out.append(RawJob(source="remote", title=j.get("title", ""), company=j.get("company_name", ""), url=j.get("url", ""),
                              location=f"Remote ({place})" if place else "Remote", description=html_to_text(j.get("description", ""))[:10000],
                              posted_at=parse_date(j.get("pub_date")), source_detail="Working Nomads"))
    except Exception as e:  # noqa: BLE001
        ctx.log("remote", f"working nomads: {e}", "warn")
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
    """The user's own RSS or Atom feeds (the Sources dialog). Each feed is a plain URL or {"url", "name"}. Every item
    becomes a job titled with the item's headline. Titles skip the level check (strict_titles=False) because headlines
    aren't structured job titles."""
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
    """Adzuna, a job aggregator with a free API key (the Sources dialog: app_id and app_key); skipped without one. Searches
    the first four queries in every allowed place (_places: remote entries left out, a nationwide one as the United
    States, and the whole United States when only remote is allowed): the first page of Adzuna's US search, 50 results,
    posted within the last 45 days."""
    sc = ctx.cfg["sources"]["adzuna"]
    if not (sc.get("app_id") and sc.get("app_key")):
        return []
    out = []
    places = _places(ctx) or ["United States"]
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
    "<query> <place>" for the first three queries in up to four allowed places (_places: remote ones left out, so a
    remote-only search area searches nothing here). English results for the United States. The first apply link Google
    offers becomes the posting URL."""
    sc = ctx.cfg["sources"]["serpapi"]
    if not sc.get("api_key"):
        return []
    out = []
    places = _places(ctx)[:4]
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
    """Bluesky search phrases: hiring phrases for each early-career level the user picked (interns, apprentices, new
    grads), or "we're hiring" for everyone else, plus "hiring <query>" for the first five queries."""
    roles = _queries(ctx, 5)
    if _early(ctx):
        picked = set(plan.levels(ctx.cfg))
        phrases = {"internship": ["hiring interns", "summer intern hiring"], "apprenticeship": ["hiring apprentices"],
                   "entry": ["hiring new grad", "entry level hiring"]}
        base = [p for level, ps in phrases.items() if level in picked for p in ps]
    else:
        base = ["we're hiring"]
    return base + [f"hiring {r}" for r in roles]


X_SEARCH = "https://api.x.com/2/tweets/search/recent"  # X's official search: public posts from the last 7 days


def _x_queries(ctx: Ctx) -> list[str]:
    """X search queries: hiring words, then the user's search terms (quoted when longer than a word), without reposts and
    replies. One query per term, up to the "searches" setting."""
    count = max(1, int((ctx.cfg["sources"].get("x") or {}).get("searches") or 3))
    terms = _queries(ctx, count) or ["jobs"]
    quoted = [f'"{t}"' if " " in t else t for t in terms]
    return [f'(hiring OR "we\'re hiring" OR "now hiring") {t} -is:retweet -is:reply lang:en' for t in quoted]


async def x_search(ctx: Ctx) -> list[RawJob]:
    """Hiring posts on X through its official API, with the user's own developer key (a Bearer token). X charges for every
    post its API returns (about half a cent each), so this is off until the user turns it on and adds a key, and
    "posts_per_search" caps each search. Scraping X is against its terms, so there's no other way in. Only posts that read
    like hiring posts at the user's level are kept."""
    sc = ctx.cfg["sources"].get("x") or {}
    token = str(sc.get("bearer_token") or "").strip()
    if not token:
        ctx.log("x", "skipped: add the Bearer token of your X developer app in Sources", "warn")
        return []
    headers = {"Authorization": f"Bearer {token}"}
    per_search = max(10, min(100, int(sc.get("posts_per_search") or 25)))
    out, seen = [], set()
    post_re = _post_re(ctx)
    for query in _x_queries(ctx):
        params = {"query": query, "max_results": per_search, "tweet.fields": "created_at,author_id", "expansions": "author_id",
                  "user.fields": "username,name"}
        try:
            d = await ctx.get_json(f"{X_SEARCH}?" + urlencode(params), headers=headers)
        except Exception as e:  # noqa: BLE001 (one failed search shouldn't end the others)
            ctx.log("x", f"“{query[:60]}”: {e}", "warn")
            continue
        users = {u.get("id"): u for u in (d.get("includes") or {}).get("users", []) if isinstance(u, dict)}
        for post in d.get("data") or []:
            text = post.get("text", "")
            user = users.get(post.get("author_id")) or {}
            url = f"https://x.com/{user.get('username') or 'i'}/status/{post.get('id')}"
            if url in seen or not post_re.search(text) or not HIRING_RE.search(text):
                continue
            seen.add(url)
            out.append(RawJob(source="x", title=clean(text.split("\n")[0])[:140], company=user.get("name", ""), url=url, description=text,
                              posted_at=parse_date(post.get("created_at")), strict_titles=False, found_url=url,
                              source_detail=f"X @{user.get('username', '')}"))
    ctx.log("x", f"{len(out)} hiring posts")
    return out


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
