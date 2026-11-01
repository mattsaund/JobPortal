"""Company job boards: applicant tracking systems (ATS) that publish openings at public addresses. Supported: Greenhouse,
Lever, Ashby, Workday, UKG (UltiPro), iCIMS and SmartRecruiters. No API keys are needed.

Each board in Settings, Sources (cfg["sources"]["ats_boards"]["boards"]) names its system ("ats") and either a slug (the
company's id on that system, for example "example-robotics") or its careers page URL. HANDLERS maps each system to the
function that reads that kind of board, and collect() reads every enabled board, eight at a time. detect() turns a careers
page link into a board entry; that is how the Sources page adds a company from a pasted link (see sources.py).

Most systems return every opening in one request. Workday and iCIMS need a search word, so they are searched once per term
from search_terms(). Postings from a board the user starred on the Sources page carry dream=True. strict_titles stays True:
these are real job titles, so the rule filters check them against the user's levels. Several systems leave descriptions
out of their lists; collectors/details.py fetches those later, one posting at a time, using what meta keeps."""
import asyncio
import re
from urllib.parse import quote_plus, urlparse

from jobportal.core.levels import ats_search_terms
from jobportal.core.textutil import clean, html_to_text, parse_date
from jobportal.search import plan
from jobportal.search.collectors.base import Ctx, RawJob

BOARDS_AT_ONCE = 8  # boards read in parallel; Ctx still sends at most 4 requests at a time to one host (Greenhouse's API)
LOCALE_SEGMENT = re.compile(r"[a-z]{2}-[A-Z]{2}")  # Workday URLs may carry a language part such as /en-US/
WORKDAY_PAGE = 20  # Workday returns at most 20 postings per request
WORKDAY_MAX = 100  # postings read per search term on one Workday board


def search_terms(cfg: dict) -> list[str]:
    """Search words for boards that need one (Workday, iCIMS): level words such as "intern" or "apprentice" for
    early-career users, then the search queries. When neither gives anything, one empty search reads the board's newest
    openings of every kind, so no field is assumed."""
    return ats_search_terms(plan.levels(cfg), plan.all_queries(cfg)) or [""]


def _wd_parts(url: str) -> tuple[str, str, str]:
    """Split a Workday careers URL into (site root, tenant, site name). The API address is built from these three.

    https://example.wd5.myworkdayjobs.com/en-US/External -> ("https://example.wd5.myworkdayjobs.com", "example", "External")"""
    u = urlparse(url)
    tenant = u.netloc.split(".")[0]
    segments = [s for s in u.path.split("/") if s and not LOCALE_SEGMENT.fullmatch(s)]
    site = segments[0] if segments else "External"
    return f"{u.scheme}://{u.netloc}", tenant, site


async def greenhouse(ctx: Ctx, b: dict) -> list[RawJob]:
    """Greenhouse: GET boards-api.greenhouse.io/v1/boards/<slug>/jobs lists every opening, without descriptions. meta keeps
    the slug and job id so details.py can fetch the full posting."""
    d = await ctx.get_json(f"https://boards-api.greenhouse.io/v1/boards/{b['slug']}/jobs")
    out = []
    for j in d.get("jobs", []):
        out.append(RawJob(source="ats", title=j.get("title", ""), company=b["name"], url=j.get("absolute_url", ""),
                          location=(j.get("location") or {}).get("name", ""),
                          posted_at=parse_date(j.get("first_published") or j.get("updated_at")),
                          dream=bool(b.get("dream")), source_detail=f"Greenhouse: {b['name']}",
                          found_url=f"https://job-boards.greenhouse.io/{b['slug']}",
                          meta={"ats": "greenhouse", "slug": b["slug"], "id": j.get("id")}))
    return out


def lever_description(posting: dict) -> str:
    """A Lever posting's text. Lever splits it into a plain-text body, titled lists (responsibilities, requirements and so
    on, in HTML) and an optional closing section."""
    lists = "\n".join(f"{part.get('text', '')}:\n{html_to_text(part.get('content', ''))}" for part in posting.get("lists", []))
    return (posting.get("descriptionPlain") or "") + "\n" + lists


async def lever(ctx: Ctx, b: dict) -> list[RawJob]:
    """Lever: GET api.lever.co/v0/postings/<slug>?mode=json lists every opening with its full description."""
    d = await ctx.get_json(f"https://api.lever.co/v0/postings/{b['slug']}?mode=json")
    out = []
    for j in d if isinstance(d, list) else []:
        categories = j.get("categories") or {}
        description = lever_description(j) + "\n" + (j.get("additionalPlain") or "")
        locations = categories.get("allLocations") or ([categories.get("location")] if categories.get("location") else [])
        out.append(RawJob(source="ats", title=j.get("text", ""), company=b["name"], url=j.get("hostedUrl", ""),
                          apply_url=j.get("applyUrl"), locations=locations, location=" | ".join(locations),
                          description=description.strip(), posted_at=parse_date(j.get("createdAt")),
                          category_hint=categories.get("commitment", ""), dream=bool(b.get("dream")),
                          source_detail=f"Lever: {b['name']}", found_url=f"https://jobs.lever.co/{b['slug']}", meta={"ats": "lever"}))
    return out


async def ashby(ctx: Ctx, b: dict) -> list[RawJob]:
    """Ashby: GET api.ashbyhq.com/posting-api/job-board/<slug> lists every opening with its description. Remote roles get
    "Remote" added to their locations so the location filter sees it."""
    d = await ctx.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{b['slug']}")
    out = []
    for j in d.get("jobs", []):
        locations = [j.get("location", "")] + [x.get("location", "") for x in j.get("secondaryLocations", []) or []]
        if j.get("isRemote"):
            locations.append("Remote")
        locations = [loc for loc in locations if loc]
        out.append(RawJob(source="ats", title=j.get("title", ""), company=b["name"], url=j.get("jobUrl", ""),
                          apply_url=j.get("applyUrl"), locations=locations, location=" | ".join(locations),
                          description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                          posted_at=parse_date(j.get("publishedAt")), category_hint=j.get("employmentType", ""),
                          dream=bool(b.get("dream")), source_detail=f"Ashby: {b['name']}", found_url=f"https://jobs.ashbyhq.com/{b['slug']}",
                          meta={"ats": "ashby"}))
    return out


async def workday(ctx: Ctx, b: dict) -> list[RawJob]:
    """Workday: the JSON API behind every Workday careers site (POST <site root>/wday/cxs/<tenant>/<site>/jobs). It needs a
    search word and pages 20 postings at a time, so each term reads up to 100. No descriptions: meta["api"] keeps each
    posting's own API address for details.py."""
    base, tenant, site = _wd_parts(b["url"])
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    seen, out = set(), []
    for term in search_terms(ctx.cfg):
        total = 0
        for offset in range(0, WORKDAY_MAX, WORKDAY_PAGE):
            try:
                d = await ctx.post_json(api, {"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": offset, "searchText": term})
            except Exception as e:  # noqa: BLE001 (one failing term shouldn't sink the board)
                ctx.log("ats", f"{b['name']}: workday '{term}' failed: {e}", "warn")
                break
            posts = d.get("jobPostings", [])
            for j in posts:
                path = j.get("externalPath")  # the posting's path on the careers site, unique per posting
                if not path or path in seen:
                    continue
                seen.add(path)
                out.append(RawJob(source="ats", title=j.get("title", ""), company=b["name"], url=f"{base}/{site}{path}",
                                  location=j.get("locationsText", ""), posted_at=parse_date(j.get("postedOn")),
                                  dream=bool(b.get("dream")), source_detail=f"Workday: {b['name']}", found_url=b["url"],
                                  meta={"ats": "workday", "api": f"{base}/wday/cxs/{tenant}/{site}{path}"}))
            # Keep the first page's total: a later page that leaves it out (0) must not end the paging early.
            total = d.get("total") or total
            if len(posts) < WORKDAY_PAGE or offset + WORKDAY_PAGE >= total:
                break
    return out


# The search UKG's own job board page sends with nothing selected: the 100 newest openings, no keyword, no filters.
UKG_BODY = {"opportunitySearch": {"Top": 100, "Skip": 0, "QueryString": "", "OrderBy": [
    {"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}], "Filters": [
    {"t": "TermsSearchFilterDto", "fieldName": 4, "extra": None, "values": []},
    {"t": "TermsSearchFilterDto", "fieldName": 5, "extra": None, "values": []},
    {"t": "TermsSearchFilterDto", "fieldName": 6, "extra": None, "values": []}]},
    "matchCriteria": {"PreferredJobs": [], "Educations": [], "LicenseAndCertifications": [], "Skills": [],
                      "hasNoLicenses": False, "SkippedSkills": []}}


async def ukg(ctx: Ctx, b: dict) -> list[RawJob]:
    """UKG (UltiPro): POST <board url>/JobBoardView/LoadSearchResults with UKG_BODY returns the 100 newest openings with a
    short description. Locations come as structured addresses, turned into "City, ST"."""
    base = b["url"].rstrip("/")
    d = await ctx.post_json(f"{base}/JobBoardView/LoadSearchResults", UKG_BODY)
    out = []
    for j in d.get("opportunities", []):
        locations = []
        for place in j.get("Locations") or []:
            address = place.get("Address") or {}
            city_state = ", ".join(x for x in [address.get("City"), (address.get("State") or {}).get("Code")] if x)
            locations.append(city_state or place.get("LocalizedName", ""))
        out.append(RawJob(source="ats", title=j.get("Title", ""), company=b["name"],
                          url=f"{base}/OpportunityDetail?opportunityId={j.get('Id')}", locations=locations, location=" | ".join(locations),
                          description=j.get("BriefDescription", ""), posted_at=parse_date(j.get("PostedDate")),
                          dream=bool(b.get("dream")), source_detail=f"UKG: {b['name']}", found_url=base, meta={"ats": "ukg"}))
    return out


async def icims(ctx: Ctx, b: dict) -> list[RawJob]:
    """iCIMS: there is no public JSON API, so this reads the careers site's search results page as HTML, once per term.
    in_iframe=1 asks for the bare results list, without the company's page around it. Each result is an
    iCIMS_JobCardItem block holding the link, title, location, posted date and a short description."""
    base = b["url"].rstrip("/")
    host = urlparse(base).netloc
    out, seen = [], set()
    for term in search_terms(ctx.cfg):
        html = await ctx.get_text(f"{base}/jobs/search?ss=1&searchKeyword={quote_plus(term)}&in_iframe=1")
        for card in html.split('class="iCIMS_JobCardItem"')[1:]:
            link = re.search(rf'href="(https://{re.escape(host)}/jobs/(\d+)/[^"]+)"', card)  # group 2 is the job number
            if not link or link.group(2) in seen:
                continue
            seen.add(link.group(2))
            title = re.search(r"<h3[^>]*>(.*?)</h3>", card, re.S)
            location = re.search(r"Job Locations?</span>\s*<span[^>]*>(.*?)</span>", card, re.S)
            posted = re.search(r'Posted Date</span>\s*<span title="([^"]+)"', card)  # the title attribute holds the exact date
            description = re.search(r'class="col-xs-12 description">(.*?)</div>', card, re.S)
            out.append(RawJob(source="ats", title=clean(html_to_text(title.group(1) if title else "")), company=b["name"],
                              url=link.group(1).replace("?in_iframe=1", ""), location=clean(location.group(1) if location else ""),
                              description=html_to_text(description.group(1) if description else ""),
                              posted_at=parse_date((posted.group(1).split(" ")[0]) if posted else None),
                              dream=bool(b.get("dream")), source_detail=f"iCIMS: {b['name']}", found_url=f"{base}/jobs/search?ss=1",
                              meta={"ats": "icims"}))
    return out


async def smartrecruiters(ctx: Ctx, b: dict) -> list[RawJob]:
    """SmartRecruiters: GET api.smartrecruiters.com/v1/companies/<slug>/postings lists the first 100 openings, without
    descriptions. meta["api"] keeps each posting's API address for details.py."""
    d = await ctx.get_json(f"https://api.smartrecruiters.com/v1/companies/{b['slug']}/postings?limit=100")
    out = []
    for j in d.get("content", []):
        place = j.get("location") or {}
        location = ", ".join(x for x in [place.get("city"), place.get("region")] if x) + (" (Remote)" if place.get("remote") else "")
        out.append(RawJob(source="ats", title=j.get("name", ""), company=b["name"],
                          url=f"https://jobs.smartrecruiters.com/{b['slug']}/{j.get('id')}", location=location,
                          posted_at=parse_date(j.get("releasedDate")), dream=bool(b.get("dream")),
                          source_detail=f"SmartRecruiters: {b['name']}", found_url=f"https://jobs.smartrecruiters.com/{b['slug']}",
                          meta={"ats": "smartrecruiters", "api": f"https://api.smartrecruiters.com/v1/companies/{b['slug']}/postings/{j.get('id')}"}))
    return out


HANDLERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday, "ukg": ukg,
            "icims": icims, "smartrecruiters": smartrecruiters}


async def collect(ctx: Ctx) -> list[RawJob]:
    """Read every enabled board, BOARDS_AT_ONCE at a time. A board that fails (wrong slug, site down, format changed) is
    logged and skipped. A board naming an unknown system is skipped quietly."""
    boards = [b for b in ctx.cfg["sources"]["ats_boards"]["boards"] if b.get("enabled", True)]
    slots = asyncio.Semaphore(BOARDS_AT_ONCE)

    async def read_board(b: dict) -> list[RawJob]:
        """One board's postings, or [] when the board can't be read."""
        async with slots:
            handler = HANDLERS.get(b.get("ats"))
            if not handler:
                return []
            try:
                return await handler(ctx, b)
            except Exception as e:  # noqa: BLE001 (one broken board shouldn't sink the rest)
                ctx.log("ats", f"{b['name']} ({b.get('ats')}): {type(e).__name__}: {str(e)[:120]}", "warn")
                return []

    results = await asyncio.gather(*(read_board(b) for b in boards))
    out = [job for jobs in results for job in jobs]
    ctx.log("ats", f"{len(boards)} company boards → {len(out)} postings")
    return out


def detect(url: str) -> dict | None:
    """Turn a careers page or posting URL into a board entry ({"ats": ..., plus "slug" or "url"}), or None when it isn't a
    supported system. For example jobs.lever.co/example-robotics/123 gives {"ats": "lever", "slug": "example-robotics"}."""
    u = urlparse(url.strip())
    host, path = u.netloc.lower(), u.path
    segments = [s for s in path.split("/") if s]
    if "greenhouse.io" in host:
        embed = re.search(r"for=([\w-]+)", u.query)  # embedded boards: boards.greenhouse.io/embed/job_board?for=<slug>
        if embed:
            return {"ats": "greenhouse", "slug": embed.group(1)}
        if segments and segments[0] not in ("embed", "v1"):  # job-boards.greenhouse.io/<slug>/jobs/<id>
            return {"ats": "greenhouse", "slug": segments[0]}
    if "lever.co" in host and segments:
        return {"ats": "lever", "slug": segments[0]}
    if "ashbyhq.com" in host and segments:
        return {"ats": "ashby", "slug": segments[0]}
    if "myworkdayjobs.com" in host:
        site = [s for s in segments if not LOCALE_SEGMENT.fullmatch(s)]
        return {"ats": "workday", "url": f"https://{host}/{site[0] if site else 'External'}"}
    if "ultipro.com" in host and "JobBoard" in path:
        board = re.search(r"(.*/JobBoard/[0-9a-f-]+)", f"https://{host}{path}")  # everything up to the board's id
        return {"ats": "ukg", "url": board.group(1)} if board else None
    if host.endswith(".icims.com"):
        return {"ats": "icims", "url": f"https://{host}"}
    if "smartrecruiters.com" in host and segments:
        return {"ats": "smartrecruiters", "slug": segments[0]}
    return None
