"""Job feeds and public APIs, one collector function per source: Hacker News "Who is hiring?", The Muse, USAJobs, Reddit,
Mastodon, remote job boards (Remotive, RemoteOK, We Work Remotely), the user's own RSS or Atom feeds, Bluesky, and two
optional aggregators that need the user's own API key (Adzuna, and Google Jobs through SerpAPI).

Each function is a collector, `async fn(ctx) -> list[RawJob]`, listed in collectors/__init__.py. Search words come from
search/plan.py. For early-career users (every level picked is internship, apprenticeship or entry level) most sources
search wording for those levels instead of the user's queries.

Adapting to the user's fields: search/plan.fields() names the work genres the user's targets point at, and the maps below
turn them into The Muse's categories, extra subreddits, Mastodon hashtags and instances, and We Work Remotely feeds. Every
community, hashtag, category and feed in them was checked to exist and carry job posts (October 2026); add only ones
that do. Hacker News carries tech jobs, so it skips itself unless the user's targets are in tech (plan.in_tech).

Social sources (Hacker News comments, Reddit, Mastodon, Bluesky) return posts, not postings: the title is the post's first
line and strict_titles is False. A post is kept only when it matches the user's level or roles (_post_re) and also uses a
hiring word. Each function's docstring notes its site's limits and API parameters."""
import asyncio
import random
import re
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode

from jobportal.core.genres import DEFAULT_GENRES
from jobportal.core.levels import early_career, muse_levels, posting_regex
from jobportal.core.textutil import (
    MAJOR_CITIES,
    NAME_TO_ABBR,
    REMOTE_RE,
    STATES,
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


# The Muse's job categories for each genre (the names its API filters on; a wrong name returns nothing).
MUSE_CATEGORIES = {
    **_for(["swe", "frontend_mobile", "ml_ai", "systems_test"], ["Software Engineering"]), "data": ["Data and Analytics"],
    **_for(["cloud_devops", "cyber", "it_support"], ["Computer and IT", "Software Engineering"]),
    **_for(["embedded_hw", "robotics", "engineering", "research"], ["Science and Engineering"]),
    "product_design": ["Design and UX", "Product Management"], "solutions": ["Sales", "Account Management"],
    **_for(["nursing", "allied_health", "physicians", "health_admin"], ["Healthcare"]),
    "behavioral_health": ["Healthcare", "Social Services"], "caregiving": ["Healthcare", "Personal Care and Services"],
    **_for(["teaching", "early_childhood", "student_services"], ["Education"]), "library_museum": ["Education", "Arts"],
    "admin_office": ["Administration and Office"], "customer_service": ["Customer Service"],
    "sales": ["Sales", "Account Management"], "marketing": ["Advertising and Marketing", "Media, PR, and Communications"],
    "finance_accounting": ["Accounting and Finance"], "hr": ["Human Resources and Recruitment"],
    "management_ops": ["Business Operations", "Project Management", "Management"], "legal": ["Legal Services"],
    "food_hospitality": ["Food and Hospitality Services", "Entertainment and Travel Services"], "retail": ["Retail"],
    "personal_care": ["Personal Care and Services", "Sports, Fitness, and Recreation"],
    "skilled_trades": ["Installation, Maintenance, and Repairs", "Construction"], "construction": ["Construction"],
    "manufacturing": ["Manufacturing and Warehouse"], "maintenance_auto": ["Installation, Maintenance, and Repairs"],
    "logistics": ["Transportation and Logistics", "Manufacturing and Warehouse"], "art_design": ["Design and UX", "Arts"],
    "writing_media": ["Writing and Editing", "Media, PR, and Communications"], "performing_arts": ["Arts"],
    "environment_ag": ["Farming and Outdoors", "Animal Care"], "nonprofit": ["Social Services"],
    "public_safety": ["Protective Services"],
}
# Subreddits that carry job posts for a field, added to the general ones in Settings.
REDDIT_FIELD_SUBS = {**_for(TECH_GENRES, ["techjobs"]), "art_design": ["DesignJobs", "HungryArtists", "gameDevClassifieds"],
                     "product_design": ["DesignJobs"], "writing_media": ["writingopportunities"]}
REDDIT_REMOTE_SUBS = ["RemoteJobs"]  # added when Remote is allowed
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


# ------------------------------------------------------------------ The Muse
def _muse_locations(allowed: list[str]) -> list[str]:
    """Turn the allowed locations into values The Muse's location filter knows, which are "City, ST" names. A state becomes
    its largest cities (core/textutil.MAJOR_CITIES), DC becomes "Washington, DC", anything remote becomes "Flexible /
    Remote" (The Muse's name for remote work), and anything else is passed as typed."""
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
            out += [f"{city}, {state}" for city in MAJOR_CITIES.get(state, [])]
        else:
            out.append(a)
    return out


async def themuse(ctx: Ctx) -> list[RawJob]:
    """The Muse's public jobs API (no key needed): newest first, filtered to the user's levels, to the job categories of
    their fields (MUSE_CATEGORIES; every category while their fields aren't known) and, unless the search area is
    nationwide, to its locations. Reads up to Settings' page count. Titles skip the level check (strict_titles=False)
    because the API's level filter already applied it."""
    pages = int(ctx.cfg["sources"]["themuse"].get("pages", 8))
    allowed = ctx.cfg["locations"]["allowed"]
    nationwide = any(NATIONWIDE.fullmatch(a.lower().strip()) for a in allowed)
    locations = [] if nationwide else _muse_locations(allowed)
    categories = _field_values(ctx, MUSE_CATEGORIES)
    # Repeated parameters mean "any of these": level=Internship&level=Entry Level&category=Healthcare&location=...
    base = ([("level", lv) for lv in muse_levels(plan.levels(ctx.cfg))] + [("category", c) for c in categories]
            + [("descending", "true")] + [("location", loc) for loc in locations])
    out = []
    for page in range(pages):
        d = await ctx.get_json("https://www.themuse.com/api/public/jobs?" + urlencode(base + [("page", page)]))
        for j in d.get("results", []):
            job_locations = [loc.get("name", "") for loc in j.get("locations", [])]
            out.append(RawJob(source="themuse", title=j.get("name", ""), company=(j.get("company") or {}).get("name", ""),
                              url=(j.get("refs") or {}).get("landing_page", ""), locations=job_locations,
                              description=html_to_text(j.get("contents", ""))[:12000],
                              posted_at=parse_date(j.get("publication_date")), source_detail="The Muse", strict_titles=False))
        if page + 1 >= d.get("page_count", 0):  # pages are numbered from 0
            break
    ctx.log("themuse", f"{len(out)} postings" + (f" in {', '.join(categories)}" if categories else ""))
    return out


# ------------------------------------------------------------------ USAJobs
async def usajobs(ctx: Ctx) -> list[RawJob]:
    """USAJobs, the federal government's job board, through its search API. It needs a free API key and the email address the
    key was issued to (the Sources dialog); without them this source skips itself. The API wants that email as the
    User-Agent and the key in an Authorization-Key header.

    Searches the first six queries. Users searching at internship or entry level also get the student and recent-graduate
    hiring paths (Pathways) and intern searches, and apprenticeship searches get apprentice and trainee roles. Each search
    asks for up to 500 postings (the API's maximum) from the last 60 days. Titles skip the level check
    (strict_titles=False): federal titles rarely name a level."""
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


async def reddit(ctx: Ctx) -> list[RawJob]:
    """Reddit search, read through its RSS feeds (no account or key needed). Searches each subreddit (_reddit_subreddits)
    for hiring words (with the words of their levels for early-career users: intern, apprentice, new grad), plus two
    site-wide "<query> hiring <place>" searches. Every search covers the last month, newest first.

    Reddit throttles anonymous feed readers hard: one request at a time, 4 to 7 seconds between searches, no retries, an 8
    second wait after a refusal, and after three refusals the rest are skipped (the AI hunt's social mission still covers
    Reddit). Only posts that read like hiring posts at the user's level are kept."""
    ctx.host_limit("www.reddit.com", 1)
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
    """Three remote-only job boards, used only when the search area allows remote work: Remotive's free API, searched once
    per term; RemoteOK, whose whole feed comes in one request; and We Work Remotely's RSS feeds for the user's fields
    (_wwr_feeds), whose titles read "Company: Role". The board's own location note, such as "USA only", stays in the
    location so the location filter can judge it."""
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
