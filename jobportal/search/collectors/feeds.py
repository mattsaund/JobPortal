"""Feeds and public APIs: Hacker News 'Who is hiring?', The Muse, USAJobs, Reddit RSS, Mastodon,
remote boards, custom RSS/Atom feeds, plus optional keyed aggregators (Adzuna, SerpAPI Google Jobs)."""
import asyncio
import random
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlencode

from jobportal.core.levels import early_career, muse_levels, posting_regex
from jobportal.core.textutil import CITY_STATE, NAME_TO_ABBR, STATES, clean, html_to_text, parse_date
from jobportal.search import plan
from jobportal.search.collectors.base import Ctx, RawJob

HIRING_RE = re.compile(r"hiring|opening|apply|position|role|looking for|job", re.I)


def _early(ctx: Ctx) -> bool:
    return early_career(plan.levels(ctx.cfg))


def _post_re(ctx: Ctx) -> re.Pattern:
    """Which free-text posts count: early-career wording for students and new grads, your role words for everyone else."""
    return posting_regex(plan.levels(ctx.cfg), plan.role_words(ctx.cfg))


def _queries(ctx: Ctx, n: int) -> list[str]:
    return (plan.all_queries(ctx.cfg) or plan.target_roles())[:n]


# ------------------------------------------------------------------ Hacker News
async def hackernews(ctx: Ctx) -> list[RawJob]:
    n = int(ctx.cfg["sources"]["hackernews"].get("threads", 2))
    d = await ctx.get_json("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=12")
    threads = [h for h in d.get("hits", []) if "who is hiring" in h.get("title", "").lower()][:n]
    post_re, early = _post_re(ctx), _early(ctx)
    out = []
    for t in threads:
        item = await ctx.get_json(f"https://hn.algolia.com/api/v1/items/{t['objectID']}", timeout=60)
        for c in item.get("children", []):
            text = html_to_text(c.get("text") or "")
            if not text or not post_re.search(text):
                continue
            head = text.split("\n", 1)[0]
            parts = [p.strip() for p in re.split(r"\s+[|\u2014\u2013]\s+|\s\|\s?|\s-\s", head) if p.strip()]
            company = parts[0][:80] if parts else "Unknown"
            role = next((p for p in parts[1:] if post_re.search(p) or re.search(r"engineer|developer|scientist|analyst|designer|manager", p, re.I)), "")
            loc = next((p for p in parts[1:] if re.search(r"remote|onsite|hybrid|, [A-Z]{2}\b|\bNYC\b|\bSF\b", p, re.I)), "")
            out.append(RawJob(source="hackernews", title=(role or "Opening (see comment)")[:140], company=company,
                              url=f"https://news.ycombinator.com/item?id={c['id']}", location=loc, description=text[:8000],
                              posted_at=parse_date(c.get("created_at")), strict_titles=False,
                              source_detail=f"HN {t['title']}, comment by {c.get('author')}"))
    # Beyond the monthly threads: any recent HN comment offering roles at your level.
    import time as _t
    since = int(_t.time()) - 45 * 86400
    seen = {j.url for j in out}
    terms = ["internship", "interns hiring", "new grad hiring", "hiring intern"] if early else [f"hiring {q}" for q in _queries(ctx, 4)]
    for q in terms:
        try:
            d = await ctx.get_json("https://hn.algolia.com/api/v1/search_by_date?" + urlencode(
                {"query": q, "tags": "comment", "numericFilters": f"created_at_i>{since}", "hitsPerPage": 100}))
        except Exception:  # noqa: BLE001
            continue
        for h in d.get("hits", []):
            url = f"https://news.ycombinator.com/item?id={h['objectID']}"
            text = html_to_text(h.get("comment_text") or "")
            if url in seen or not (post_re.search(text) and re.search(r"hiring|apply|we're looking|open (role|position)|join us|email me", text, re.I)):
                continue
            seen.add(url)
            out.append(RawJob(source="hackernews", title=clean(text.split("\n")[0])[:140], company="", url=url, description=text[:6000],
                              posted_at=parse_date(h.get("created_at")), strict_titles=False, found_url=url,
                              source_detail=f"HN comment by {h.get('author')} on “{(h.get('story_title') or '')[:80]}”"))
    ctx.log("hackernews", f"{len(threads)} hiring threads plus a comment search found {len(out)} relevant mentions")
    return out


# ------------------------------------------------------------------ The Muse
def _muse_locations(allowed: list[str]) -> list[str]:
    out = []
    for a in allowed:
        low = a.lower().strip()
        if "remote" in low:
            out.append("Flexible / Remote")
            continue
        ab = a.upper() if a.upper() in STATES else NAME_TO_ABBR.get(low)
        if re.search(r"\bd\.?c\.?\b", low):
            ab = "DC"
        if ab:
            cities = [c for c, s in CITY_STATE.items() if s == ab and c not in ("washington dc", "washington d.c.")][:6]
            out += [f"{c.title()}, {ab}" for c in cities] + (["Washington, DC"] if ab == "DC" else [])
        else:
            out.append(a)
    return out


async def themuse(ctx: Ctx) -> list[RawJob]:
    pages = int(ctx.cfg["sources"]["themuse"].get("pages", 8))
    allowed = ctx.cfg["locations"]["allowed"]
    nationwide = any(re.fullmatch(r"(anywhere( in the)?( us| usa| united states)?|nationwide|united states|usa|us)", a.lower().strip()) for a in allowed)
    locs = [] if nationwide else _muse_locations(allowed)
    base = [("level", lv) for lv in muse_levels(plan.levels(ctx.cfg))] + [("descending", "true")] + [("location", l) for l in locs]
    out = []
    for p in range(pages):
        d = await ctx.get_json("https://www.themuse.com/api/public/jobs?" + urlencode(base + [("page", p)]))
        for j in d.get("results", []):
            jl = [l.get("name", "") for l in j.get("locations", [])]
            out.append(RawJob(source="themuse", title=j.get("name", ""), company=(j.get("company") or {}).get("name", ""),
                              url=(j.get("refs") or {}).get("landing_page", ""), locations=jl, location=" | ".join(jl),
                              description=html_to_text(j.get("contents", ""))[:12000],
                              posted_at=parse_date(j.get("publication_date")), source_detail="The Muse", strict_titles=False))
        if p + 1 >= d.get("page_count", 0):
            break
    ctx.log("themuse", f"{len(out)} postings")
    return out


# ------------------------------------------------------------------ USAJobs
async def usajobs(ctx: Ctx) -> list[RawJob]:
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
    for s in searches:
        params = {"ResultsPerPage": 500, "DatePosted": 60, **s}
        r = await ctx.request("GET", "https://data.usajobs.gov/api/search?" + urlencode(params), headers=headers)
        if r.status_code != 200:
            ctx.log("usajobs", f"HTTP {r.status_code} for {s}", "warn")
            continue
        for it in r.json().get("SearchResult", {}).get("SearchResultItems", []):
            m = it.get("MatchedObjectDescriptor", {})
            if m.get("PositionID") in seen:
                continue
            seen.add(m.get("PositionID"))
            det = (m.get("UserArea") or {}).get("Details") or {}
            desc = "\n\n".join(x for x in [det.get("JobSummary", ""), "\n".join(det.get("MajorDuties") or []),
                                           m.get("QualificationSummary", ""), f"Who may apply: {det.get('WhoMayApply', {}).get('Name', '')}"] if x)
            locs = [l.get("LocationName", "") for l in m.get("PositionLocation", [])]
            out.append(RawJob(source="usajobs", title=m.get("PositionTitle", ""),
                              company=f"{m.get('OrganizationName', '')} ({m.get('DepartmentName', '')})",
                              url=m.get("PositionURI", ""), apply_url=(m.get("ApplyURI") or [None])[0],
                              locations=locs, location=" | ".join(locs), description=desc[:12000],
                              posted_at=parse_date(m.get("PublicationStartDate")),
                              deadline=parse_date(m.get("ApplicationCloseDate")), strict_titles=False,
                              source_detail="USAJobs" + (f" ({s.get('HiringPath')})" if s.get("HiringPath") else "")))
    ctx.log("usajobs", f"{len(out)} federal postings")
    return out


# ------------------------------------------------------------------ Reddit (search RSS, slow)
async def reddit(ctx: Ctx) -> list[RawJob]:
    ctx.host_limit("www.reddit.com", 1)
    subs = ctx.cfg["sources"].get("reddit", {}).get("subreddits") or ["forhire", "jobbit", "hiring"]
    early = _early(ctx)
    q = "(intern OR internship OR hiring OR \"new grad\" OR co-op)" if early else "(hiring OR \"we're hiring\" OR \"now hiring\")"
    searches = [(s, q) for s in subs]
    place = next((a for a in ctx.cfg["locations"].get("allowed", []) if not re.search(r"remote|anywhere", a, re.I)), "")
    for role in _queries(ctx, 2):
        searches.append((None, f"{role} hiring {place}".strip()))
    post_re = _post_re(ctx)
    out, failures = [], 0
    for sub, query in searches:
        if ctx.cancel.is_set() or failures >= 3:
            break
        url = (f"https://www.reddit.com/r/{sub}/search.rss?" if sub else "https://www.reddit.com/search.rss?") + urlencode(
            {"q": query, "restrict_sr": "1" if sub else "0", "sort": "new", "t": "month"})
        r = await ctx.request("GET", url, retries=0)
        if r.status_code != 200:
            failures += 1
            await asyncio.sleep(8)
            continue
        for e in _parse_feed(r.text):
            text = e["summary"]
            if not (post_re.search(e["title"] + " " + text) and re.search(r"hiring|opening|apply|position|role|looking for", e["title"] + text, re.I)):
                continue
            out.append(RawJob(source="reddit", title=e["title"][:160], company="", url=e["link"], description=text[:6000],
                              posted_at=e["date"], strict_titles=False, kind="posting",
                              source_detail=f"Reddit r/{sub}" if sub else "Reddit search", found_url=e["link"]))
        await asyncio.sleep(4 + random.random() * 3)
    ctx.log("reddit", f"{len(out)} relevant threads" + (" (rate limited; the AI social mission covers the rest)" if failures >= 3 else ""))
    return out


# ------------------------------------------------------------------ Mastodon
async def mastodon(ctx: Ctx) -> list[RawJob]:
    sc = ctx.cfg["sources"]["mastodon"]
    out, seen = [], set()

    async def tag(inst, t):
        try:
            return inst, t, await ctx.get_json(f"https://{inst}/api/v1/timelines/tag/{quote(t)}?limit=40", retries=0)
        except Exception:  # noqa: BLE001
            return inst, t, []

    res = await asyncio.gather(*(tag(i, t) for i in sc.get("instances", []) for t in sc.get("tags", [])))
    post_re = _post_re(ctx)
    for inst, t, statuses in res:
        for s in statuses or []:
            text = html_to_text(s.get("content", ""))
            if s.get("url") in seen or not post_re.search(text):
                continue
            if not HIRING_RE.search(text):
                continue
            seen.add(s.get("url"))
            acct = (s.get("account") or {})
            out.append(RawJob(source="mastodon", title=clean(text.split("\n")[0])[:140], company=acct.get("display_name", ""),
                              url=s.get("url", ""), description=text[:5000], posted_at=parse_date(s.get("created_at")),
                              strict_titles=False, source_detail=f"Mastodon #{t}, @{acct.get('acct', '')}"))
    ctx.log("mastodon", f"{len(out)} hiring posts")
    return out


# ------------------------------------------------------------------ Remote boards
async def remote_boards(ctx: Ctx) -> list[RawJob]:
    if not any(re.search(r"remote|anywhere", a, re.I) for a in ctx.cfg["locations"]["allowed"]):
        return []
    out = []
    terms = ["intern", "junior", "entry level", "graduate"] if _early(ctx) else _queries(ctx, 4)
    for term in terms:
        try:
            d = await ctx.get_json("https://remotive.com/api/remote-jobs?" + urlencode({"search": term, "limit": 100}))
            for j in d.get("jobs", []):
                out.append(RawJob(source="remote", title=j.get("title", ""), company=j.get("company_name", ""), url=j.get("url", ""),
                                  location=f"Remote ({j['candidate_required_location']})" if j.get("candidate_required_location") else "Remote",
                                  description=html_to_text(j.get("description", ""))[:10000],
                                  posted_at=parse_date(j.get("publication_date")), source_detail="Remotive"))
        except Exception as e:  # noqa: BLE001
            ctx.log("remote", f"remotive: {e}", "warn")
    try:
        d = await ctx.get_json("https://remoteok.com/api")
        for j in d[1:] if isinstance(d, list) else []:
            out.append(RawJob(source="remote", title=j.get("position", ""), company=j.get("company", ""), url=j.get("url", ""),
                              location=f"Remote ({j['location']})" if j.get("location") else "Remote", description=html_to_text(j.get("description", ""))[:10000],
                              posted_at=parse_date(j.get("date")), source_detail="RemoteOK"))
    except Exception as e:  # noqa: BLE001
        ctx.log("remote", f"remoteok: {e}", "warn")
    ctx.log("remote", f"{len(out)} remote postings (pre-filter)")
    return out


# ------------------------------------------------------------------ RSS / Atom
def _parse_feed(xml: str) -> list[dict]:
    try:
        root = ET.fromstring(xml.encode() if isinstance(xml, str) else xml)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        def get(*names):
            # Element truthiness depends on child count, so compare against None explicitly.
            for name in names:
                el = next((c for c in it if c.tag.split("}")[-1] == name), None)
                if el is not None:
                    return el
            return None
        title = get("title")
        link = get("link")
        href = (link.get("href") if link is not None and link.get("href") else (link.text if link is not None else "")) or ""
        summ = get("description", "content", "summary")
        date = get("pubDate", "published", "updated")
        out.append({"title": clean(html_to_text(title.text if title is not None else "")), "link": href.strip(),
                    "summary": html_to_text(summ.text if summ is not None else ""),
                    "date": parse_date(date.text if date is not None else None)})
    return out


async def rss(ctx: Ctx) -> list[RawJob]:
    out = []
    for f in ctx.cfg["sources"]["rss"].get("feeds", []):
        url = f["url"] if isinstance(f, dict) else f
        name = f.get("name", url) if isinstance(f, dict) else url
        try:
            for e in _parse_feed(await ctx.get_text(url)):
                out.append(RawJob(source="rss", title=e["title"][:160], company="", url=e["link"], description=e["summary"][:8000],
                                  posted_at=e["date"], strict_titles=False, source_detail=f"RSS: {name}"))
        except Exception as e:  # noqa: BLE001
            ctx.log("rss", f"{name}: {e}", "warn")
    if out:
        ctx.log("rss", f"{len(out)} feed items")
    return out


# ------------------------------------------------------------------ Optional keyed aggregators
async def adzuna(ctx: Ctx) -> list[RawJob]:
    sc = ctx.cfg["sources"]["adzuna"]
    if not (sc.get("app_id") and sc.get("app_key")):
        return []
    out = []
    wheres = [a for a in ctx.cfg["locations"]["allowed"] if not re.search("remote", a, re.I)] or ["United States"]
    for what in _queries(ctx, 4):
        for where in wheres:
            p = {"app_id": sc["app_id"], "app_key": sc["app_key"], "what": what, "where": where, "max_days_old": 45,
                 "results_per_page": 50, "content-type": "application/json"}
            try:
                d = await ctx.get_json("https://api.adzuna.com/v1/api/jobs/us/search/1?" + urlencode(p))
            except Exception as e:  # noqa: BLE001
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
    sc = ctx.cfg["sources"]["serpapi"]
    if not sc.get("api_key"):
        return []
    out = []
    wheres = [a for a in ctx.cfg["locations"]["allowed"] if not re.search("remote", a, re.I)][:4]
    for q in _queries(ctx, 3):
        for where in wheres:
            p = {"engine": "google_jobs", "q": f"{q} {where}", "api_key": sc["api_key"], "hl": "en", "gl": "us"}
            try:
                d = await ctx.get_json("https://serpapi.com/search.json?" + urlencode(p))
            except Exception as e:  # noqa: BLE001
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
    roles = _queries(ctx, 5)
    base = ["hiring interns", "summer intern hiring", "hiring new grad", "co-op hiring"] if _early(ctx) else ["we're hiring"]
    return base + [f"hiring {r}" for r in roles]


async def bluesky(ctx: Ctx) -> list[RawJob]:
    sc = ctx.cfg["sources"].get("bluesky") or {}
    if not (sc.get("handle") and sc.get("app_password")):
        ctx.log("bluesky", "skipped: add your handle and an app password (Bluesky settings, App passwords) in Sources", "warn")
        return []
    sess = await ctx.post_json("https://bsky.social/xrpc/com.atproto.server.createSession",
                               {"identifier": sc["handle"], "password": sc["app_password"]})
    headers = {"Authorization": f"Bearer {sess['accessJwt']}"}
    out, seen = [], set()
    post_re = _post_re(ctx)
    for q in _bsky_queries(ctx):
        try:
            d = await ctx.get_json("https://bsky.social/xrpc/app.bsky.feed.searchPosts?" + urlencode({"q": q, "limit": 50, "sort": "latest"}),
                                   headers=headers)
        except Exception as e:  # noqa: BLE001
            ctx.log("bluesky", f"“{q}”: {e}", "warn")
            continue
        for post in d.get("posts", []):
            text = (post.get("record") or {}).get("text", "")
            author = post.get("author") or {}
            url = f"https://bsky.app/profile/{author.get('handle')}/post/{post.get('uri', '').rsplit('/', 1)[-1]}"
            if url in seen or not post_re.search(text) or not HIRING_RE.search(text):
                continue
            seen.add(url)
            out.append(RawJob(source="bluesky", title=clean(text.split("\n")[0])[:140], company=author.get("displayName", ""), url=url,
                              description=text, posted_at=parse_date((post.get("record") or {}).get("createdAt")), strict_titles=False,
                              found_url=url, source_detail=f"Bluesky @{author.get('handle')}"))
    ctx.log("bluesky", f"{len(out)} hiring posts")
    return out
