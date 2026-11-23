"""Company job boards: applicant tracking systems (ATS) that publish openings at public addresses. SYSTEM_NAMES lists every
system supported, from Greenhouse and Workday to the small-business and European ones. No API keys are needed.

Each board in the Sources dialog (cfg["sources"]["ats_boards"]["boards"]) names its system ("ats") and either a slug (the
company's id on that system, for example "example-robotics") or its careers page URL. HANDLERS maps each system to the
function that reads that kind of board, and collect() reads every enabled board, eight at a time. detect() turns a careers
page link into a board entry; that is how the Sources dialog adds a company from a pasted link (see sources.py).

Most systems return every opening in one request. Workday, iCIMS and the other large-employer systems need a search word,
so they are searched once per term from search_terms(). The newer systems are read from small tables (JSON_BOARDS,
CARD_BOARDS) or short functions that share the parsers in readers.py, and they stop at the first refusal (Ctx.polite). Postings from a board the user starred in the Sources dialog carry dream=True. strict_titles stays
True: these are real job titles, so the rule filters check them against the user's levels. Several systems leave
descriptions out of their lists; collectors/details.py fetches those later, one posting at a time, using what meta
keeps."""
import asyncio
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote, quote_plus, urlparse

import httpx

from jobportal.core.levels import ats_search_terms
from jobportal.core.textutil import clean, html_to_text, parse_date
from jobportal.search import plan
from jobportal.search.collectors import readers
from jobportal.search.collectors.base import Blocked, Ctx, RawJob

BOARDS_AT_ONCE = 8  # boards read in parallel; Ctx still sends at most 4 requests at a time to one host (Greenhouse's API)
# The most one board may take. collect() hands back every board's postings only at the end, and the search run gives the
# whole source 15 minutes, so one stuck board must not use them up and lose every other board's postings.
BOARD_TIMEOUT = 240
LOCALE_SEGMENT = re.compile(r"[a-z]{2}-[A-Z]{2}")  # Workday URLs may carry a language part such as /en-US/
WORKDAY_PAGE = 20  # Workday returns at most 20 postings per request
WORKDAY_MAX = 100  # postings read per search term on one Workday board
TERMS_PER_BOARD = 3  # search words per run on the newer systems that need one
# Every system a board can run on: the "ats" value of a board entry and the name people know it by.
SYSTEM_NAMES = {
    "greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday", "ukg": "UKG", "icims": "iCIMS",
    "smartrecruiters": "SmartRecruiters", "recruitee": "Recruitee", "personio": "Personio", "workable": "Workable",
    "oracle": "Oracle Recruiting", "successfactors": "SuccessFactors", "phenom": "Phenom", "taleo": "Taleo", "adp": "ADP",
    "paylocity": "Paylocity", "bamboohr": "BambooHR", "jazzhr": "JazzHR", "ukg_ready": "UKG Ready", "applicantpro": "ApplicantPro",
    "peopleadmin": "PeopleAdmin", "jibe": "iCIMS Jibe", "avature": "Avature", "jobvite": "Jobvite", "teamtailor": "Teamtailor",
    "breezy": "Breezy", "pinpoint": "Pinpoint", "rippling": "Rippling", "applicantstack": "ApplicantStack", "gem": "Gem",
    "manatal": "Manatal", "join": "JOIN", "softgarden": "softgarden", "loxo": "Loxo", "traffit": "TRAFFIT", "growthzone": "GrowthZone",
}


def search_terms(cfg: dict) -> list[str]:
    """Search words for boards that need one (Workday, iCIMS): level words such as "intern" or "apprentice" for
    early-career users, then the search queries. When neither gives anything, one empty search reads the board's newest
    openings of every kind, so no field is assumed."""
    return ats_search_terms(plan.levels(cfg), plan.all_queries(cfg)) or [""]


def _few_terms(cfg: dict) -> list[str]:
    """The search words for a system read once per word, at most TERMS_PER_BOARD: the user's own queries first, because they
    name the field, then one word for their level ("intern"). One empty search when there are neither."""
    queries = plan.all_queries(cfg)[:TERMS_PER_BOARD - 1]
    levels = [t for t in search_terms(cfg) if t and t not in plan.all_queries(cfg)][:1]
    return (queries + levels) or [""]


def _wd_parts(url: str) -> tuple[str, str, str]:
    """Split a Workday careers URL into (site root, tenant, site name). The API address is built from these three.

    https://example.wd5.myworkdayjobs.com/en-US/External -> ("https://example.wd5.myworkdayjobs.com", "example", "External")
    https://wd5.myworkdaysite.com/recruiting/example/External -> ("https://wd5.myworkdaysite.com", "example", "External")"""
    u = urlparse(url)
    segments = [s for s in u.path.split("/") if s and not LOCALE_SEGMENT.fullmatch(s)]
    if u.netloc.endswith("myworkdaysite.com") and len(segments) >= 3 and segments[0] == "recruiting":
        return f"{u.scheme}://{u.netloc}", segments[1], segments[2]
    tenant = u.netloc.split(".")[0]
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
    on, in HTML) and an optional closing section (additionalPlain, often the pay range and benefits). details.py uses it
    for a single posting, and lever() for a whole board."""
    lists = "\n".join(f"{part.get('text', '')}:\n{html_to_text(part.get('content', ''))}" for part in posting.get("lists") or [])
    return "\n".join([posting.get("descriptionPlain") or "", lists, posting.get("additionalPlain") or ""]).strip()


async def lever(ctx: Ctx, b: dict) -> list[RawJob]:
    """Lever: GET api.lever.co/v0/postings/<slug>?mode=json lists every opening with its full description."""
    d = await ctx.get_json(f"https://api.lever.co/v0/postings/{b['slug']}?mode=json")
    out = []
    for j in d if isinstance(d, list) else []:
        categories = j.get("categories") or {}
        description = lever_description(j)
        locations = categories.get("allLocations") or ([categories.get("location")] if categories.get("location") else [])
        out.append(RawJob(source="ats", title=j.get("text", ""), company=b["name"], url=j.get("hostedUrl", ""),
                          apply_url=j.get("applyUrl"), locations=locations,
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
                          apply_url=j.get("applyUrl"), locations=locations,
                          description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                          posted_at=parse_date(j.get("publishedAt")), category_hint=j.get("employmentType", ""),
                          dream=bool(b.get("dream")), source_detail=f"Ashby: {b['name']}", found_url=f"https://jobs.ashbyhq.com/{b['slug']}",
                          meta={"ats": "ashby"}))
    return out


class _Terms:
    """Bookkeeping for the boards searched once per term (Workday, iCIMS), so one failing term costs only that term.

    A term the site refuses (an error status, a page it can't build) is logged and the next term is tried. A site that
    can't be reached at all ends the board instead: every other term would wait out the same retries again (about 50
    seconds each), long enough to push the whole company-boards source past its time limit. When no term got an answer,
    the board raises its last error, so the run log and the Sources dialog's check show it as failed instead of empty."""

    def __init__(self, ctx: Ctx, board: dict):
        self.ctx, self.board, self.answered, self.error = ctx, board, False, None

    def failed(self, term: str, error: Exception) -> bool:
        """Note one failed request for `term`. Returns True when the board should stop (the site can't be reached)."""
        self.error = error
        self.ctx.log("ats", f"{self.board['name']}: {self.board.get('ats')} '{term}' failed: {type(error).__name__}: {error}", "warn")
        return isinstance(error, httpx.TransportError)

    def done(self, out: list[RawJob]) -> list[RawJob]:
        """The board's postings, or its last error raised when no term got an answer."""
        if not self.answered and self.error:
            raise self.error
        return out


async def workday(ctx: Ctx, b: dict) -> list[RawJob]:
    """Workday: the JSON API behind every Workday careers site (POST <site root>/wday/cxs/<tenant>/<site>/jobs). It needs a
    search word and pages 20 postings at a time, so each term reads up to 100. No descriptions: meta["api"] keeps each
    posting's own API address for details.py. Failed terms are handled by _Terms."""
    base, tenant, site = _wd_parts(b["url"])
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    seen, out, terms = set(), [], _Terms(ctx, b)
    for term in search_terms(ctx.cfg):
        total = 0
        for offset in range(0, WORKDAY_MAX, WORKDAY_PAGE):
            try:
                d = await ctx.post_json(api, {"appliedFacets": {}, "limit": WORKDAY_PAGE, "offset": offset, "searchText": term})
            except Exception as e:  # noqa: BLE001 (one failing term shouldn't sink the board)
                if terms.failed(term, e):
                    return terms.done(out)
                break
            terms.answered = True
            posts = d.get("jobPostings", [])
            for j in posts:
                path = j.get("externalPath")  # the posting's path on the careers site, unique per posting
                if not path or path in seen:
                    continue
                seen.add(path)
                # A myworkdaysite.com board keeps the tenant in the address of each posting.
                page = f"{base}/recruiting/{tenant}/{site}{path}" if "myworkdaysite" in base else f"{base}/{site}{path}"
                out.append(RawJob(source="ats", title=j.get("title", ""), company=b["name"], url=page,
                                  location=j.get("locationsText", ""), posted_at=parse_date(j.get("postedOn")),
                                  dream=bool(b.get("dream")), source_detail=f"Workday: {b['name']}", found_url=b["url"],
                                  meta={"ats": "workday", "api": f"{base}/wday/cxs/{tenant}/{site}{path}"}))
            # Keep the first page's total: a later page that leaves it out (0) must not end the paging early.
            total = d.get("total") or total
            if len(posts) < WORKDAY_PAGE or offset + WORKDAY_PAGE >= total:
                break
    return terms.done(out)


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
            locations.append(city_state or place.get("LocalizedName"))  # RawJob drops a place with neither
        out.append(RawJob(source="ats", title=j.get("Title", ""), company=b["name"],
                          url=f"{base}/OpportunityDetail?opportunityId={j.get('Id')}", locations=locations,
                          description=j.get("BriefDescription", ""), posted_at=parse_date(j.get("PostedDate")),
                          dream=bool(b.get("dream")), source_detail=f"UKG: {b['name']}", found_url=base, meta={"ats": "ukg"}))
    return out


async def icims(ctx: Ctx, b: dict) -> list[RawJob]:
    """iCIMS: there is no public JSON API, so this reads the careers site's search results page as HTML, once per term.
    in_iframe=1 asks for the bare results list, without the company's page around it. Each result is an
    iCIMS_JobCardItem block holding the link, title, location, posted date and a short description. Failed terms are
    handled by _Terms."""
    base = b["url"].rstrip("/")
    host = urlparse(base).netloc
    out, seen, terms = [], set(), _Terms(ctx, b)
    for term in search_terms(ctx.cfg):
        try:
            html = await ctx.get_text(f"{base}/jobs/search?ss=1&searchKeyword={quote_plus(term)}&in_iframe=1")
        except Exception as e:  # noqa: BLE001 (one failing term shouldn't sink the board)
            if terms.failed(term, e):
                break
            continue
        terms.answered = True
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
    return terms.done(out)


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


async def recruitee(ctx: Ctx, b: dict) -> list[RawJob]:
    """Recruitee: GET <slug>.recruitee.com/api/offers/ lists every published opening with its description (an official
    public API, no key)."""
    d = await ctx.get_json(f"https://{b['slug']}.recruitee.com/api/offers/")
    out = []
    for j in d.get("offers", []) if isinstance(d, dict) else []:
        places = [", ".join(x for x in [p.get("city"), p.get("country")] if x) for p in j.get("locations") or [] if isinstance(p, dict)]
        location = " | ".join(p for p in places if p) or j.get("location") or ""
        if j.get("remote"):
            location = f"{location} | Remote" if location else "Remote"
        out.append(RawJob(source="ats", title=j.get("title", ""), company=b["name"], url=j.get("careers_url") or "",
                          location=location, description=html_to_text(j.get("description") or "")[:10000],
                          posted_at=parse_date(j.get("published_at") or j.get("created_at")), dream=bool(b.get("dream")),
                          source_detail=f"Recruitee: {b['name']}", found_url=f"https://{b['slug']}.recruitee.com", meta={"ats": "recruitee"}))
    return out


async def personio(ctx: Ctx, b: dict) -> list[RawJob]:
    """Personio: GET <company>.jobs.personio.de/xml lists every published opening (an official public feed, no key). Each
    position's description comes in parts, each with a heading."""
    root = ET.fromstring(await ctx.get_text(f"{b['url'].rstrip('/')}/xml"))
    out = []
    for position in root.iter("position"):
        field = lambda name: (position.findtext(name) or "").strip()  # noqa: E731
        parts = [f"{(d.findtext('name') or '').strip()}\n{html_to_text(d.findtext('value') or '')}"
                 for d in position.iter("jobDescription")]
        out.append(RawJob(source="ats", title=field("name"), company=b["name"], url=f"{b['url'].rstrip('/')}/job/{field('id')}",
                          location=field("office"), description="\n\n".join(p.strip() for p in parts if p.strip())[:10000],
                          posted_at=parse_date(field("createdAt")), dream=bool(b.get("dream")), source_detail=f"Personio: {b['name']}",
                          found_url=b["url"], meta={"ats": "personio"}))
    return out


# ---------------------------------------------------------------- the newer systems


def _posting(b: dict, system: str, **fields) -> RawJob:
    """A posting from a board, with what every system shares. The description may be HTML, and the dates any common form."""
    fields["company"] = fields.get("company") or b["name"]
    fields["title"] = readers.text_of(fields.get("title"))
    fields["description"] = html_to_text(str(fields.get("description") or ""))[:10000]
    fields["posted_at"], fields["deadline"] = parse_date(fields.get("posted_at")), parse_date(fields.get("deadline"))
    fields.setdefault("found_url", b.get("url") or "")
    meta = {"ats": system, **fields.pop("meta", {})}
    return RawJob(source="ats", dream=bool(b.get("dream")), source_detail=f"{SYSTEM_NAMES[system]}: {b['name']}", meta=meta, **fields)


def _values(b: dict) -> dict:
    """The parts of a board's address that URL templates use: {slug}, {base} (scheme and host) and {company} (UKG Ready)."""
    u = urlparse(b.get("url") or "")
    company = re.search(r"/ta/([^./]+)\.careers", u.path)
    return {"slug": b.get("slug") or "", "base": f"{u.scheme}://{u.netloc}" if u.netloc else "", "company": company.group(1) if company else ""}


def _fill(template: str, values: dict) -> str:
    """A URL template with a board's values."""
    return re.sub(r"\{(\w+)\}", lambda m: str(values.get(m.group(1), "")), template)


def _adp_place(job: dict) -> list[str]:
    """An ADP requisition's places, as "City, ST"."""
    out = []
    for place in job.get("requisitionLocations") or []:
        address = place.get("address") or {}
        region = (address.get("countrySubdivisionLevel1") or {}).get("codeValue")
        out.append(", ".join(x for x in [address.get("cityName"), region] if x) or (place.get("nameCode") or {}).get("shortName"))
    return [x for x in out if x]


def _adp_job_id(job: dict) -> str:
    """The number ADP's career pages use for a job (its ExternalJobID field), or the start of its item id without one."""
    for field in (job.get("customFieldGroup") or {}).get("stringFields") or []:
        if (field.get("nameCode") or {}).get("codeValue") == "ExternalJobID" and field.get("stringValue"):
            return str(field["stringValue"])
    return str(job.get("itemID", "")).split("_")[0]


def _traffit_field(job: dict, name: str):
    """One of the values a TRAFFIT advert keeps in a list."""
    return next((v.get("value") for v in (job.get("advert") or {}).get("values") or [] if v.get("field_id") == name), "")


def _traffit_place(job: dict) -> str:
    """A TRAFFIT advert's town and country, which it stores as JSON text."""
    try:
        place = json.loads(_traffit_field(job, "geolocation") or "{}")
    except (TypeError, ValueError):
        return ""
    return ", ".join(x for x in [place.get("locality"), place.get("country")] if x)


def _workable_place(job: dict) -> str:
    """A Workable job's place, with "Remote" for a job marked as remote."""
    place = ", ".join(x for x in [job.get("city"), job.get("state"), job.get("country")] if x)
    return f"{place} | Remote" if job.get("telecommuting") and place else ("Remote" if job.get("telecommuting") else place)


# The systems whose list is one JSON answer. url and found are templates (_values), items is where the jobs are, map says
# where each field is (readers.pick; {_slug} and {_base} in a map's template are the board's own). terms: the URL takes {term}.
JSON_BOARDS = {
    "workable": {"url": "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true", "items": "jobs",
                 "found": "https://apply.workable.com/{slug}", "map": {
                     "title": "title", "url": "url", "location": _workable_place, "posted_at": "published_on", "description": "description"}},
    "breezy": {"url": "https://{slug}.breezy.hr/json", "items": "", "found": "https://{slug}.breezy.hr", "map": {
        "title": "name", "url": "url", "location": ["location.city", "location.state.name", "location.country.name"],
        "posted_at": "published_date", "company": "company.name"}},
    "pinpoint": {"url": "https://{slug}.pinpointhq.com/postings.json", "items": "data", "found": "https://{slug}.pinpointhq.com", "map": {
        "title": "title", "url": "url", "location": "location.name", "deadline": "deadline_at",
        "description": lambda j: "\n".join(str(j.get(k) or "") for k in ("description", "key_responsibilities"))}},
    "rippling": {"url": "https://ats.rippling.com/api/v2/board/{slug}/jobs?page=0&pageSize=50", "items": "items",
                 "found": "https://ats.rippling.com/{slug}/jobs", "map": {"title": "name", "url": "url", "locations": "locations[].name"}},
    "gem": {"url": "https://api.gem.com/job_board/v0/{slug}/job_posts/", "items": "", "found": "https://jobs.gem.com/{slug}", "map": {
        "title": "title", "url": "absolute_url", "location": "location.name", "posted_at": "first_published_at", "description": "content_plain"}},
    "manatal": {"url": "https://www.careers-page.com/api/v1.0/c/{slug}/jobs/?page=1", "items": "results",
                "found": "https://www.careers-page.com/{slug}", "map": {
                    "title": "position_name", "url": "https://www.careers-page.com/{_slug}/job/{hash}", "location": "location_display",
                    "description": "description"}},
    "adp": {"url": "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
                   "?cid={slug}&lang=en_US&locale=en_US&$top=100", "items": "jobRequisitions",
            "found": "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid={slug}", "map": {
                "title": "requisitionTitle", "url": lambda j: f"https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid={j['_slug']}&jobId={_adp_job_id(j)}&lang=en_US",
                "locations": _adp_place, "posted_at": "postDate"}},
    "bamboohr": {"url": "https://{slug}.bamboohr.com/careers/list", "items": "result", "found": "https://{slug}.bamboohr.com/careers", "map": {
        "title": "jobOpeningName", "url": "https://{_slug}.bamboohr.com/careers/{id}",
        "location": ["atsLocation.city", "atsLocation.state", "atsLocation.country"]}},
    "ukg_ready": {"url": "{base}/ta/rest/ui/recruitment/companies/%7C{company}/job-requisitions?offset=1&size=50&sort=desc",
                  "items": "job_requisitions", "found": "{base}/ta/{company}.careers", "map": {
                      "title": "job_title", "url": "{_base}/ta/{_company}.careers?ShowJob={id}",
                      "location": ["location.city", "location.state", "location.country"], "description": "job_description"}},
    "traffit": {"url": "https://{slug}.traffit.com/public/job_posts/published", "items": "", "found": "https://{slug}.traffit.com", "map": {
        "title": "advert.name", "url": "url", "location": _traffit_place, "posted_at": "valid_start",
        "description": lambda j: _traffit_field(j, "description")}},
    "jibe": {"url": "{base}/api/jobs?page=1&limit=100&keywords={term}", "items": "jobs", "found": "{base}/jobs", "terms": True, "map": {
        "title": "data.title", "company": "data.hiring_organization", "url": "data.apply_url",
        "location": ("data.location_name", "data.full_location"), "posted_at": "data.posted_date", "description": "data.description"}},
}


def _mapped(b: dict, record: dict, fields: dict, values: dict) -> RawJob | None:
    """One record as a posting, read by a table's map. None without a title or an address."""
    if not isinstance(record, dict):
        return None
    record = {**record, **{f"_{k}": v for k, v in values.items()}}
    found = {name: readers.pick(record, spec) for name, spec in fields.items()}
    if found.get("location") is not None and not isinstance(found["location"], str):
        found["location"] = ""
    found = {k: v for k, v in found.items() if v not in readers.EMPTY}
    if not found.get("title") or not found.get("url"):
        return None
    return _posting(b, b["ats"], **{**found, "title": readers.text_of(found["title"])})


async def _json_board(ctx: Ctx, b: dict) -> list[RawJob]:
    """A board on a system in JSON_BOARDS: one request, or one per search word for a system that needs one."""
    spec, values = JSON_BOARDS[b["ats"]], _values(b)
    found_url = _fill(spec["found"], values)
    terms = _few_terms(ctx.cfg) if spec.get("terms") else [""]
    out, seen = [], set()
    for term in terms:
        response = await ctx.polite("GET", _fill(spec["url"], {**values, "term": quote_plus(term)}))
        data = response.json()
        records = readers.dig(data, spec["items"]) if spec["items"] else data
        for record in records if isinstance(records, list) else []:
            job = _mapped(b, record, spec["map"], values)
            if job and job.url not in seen:
                seen.add(job.url)
                job.found_url = found_url
                out.append(job)
    return out


# The systems whose list is an HTML page: the page's address and what one job looks like on it (readers.card_records).
CARD_BOARDS = {
    "jobvite": {"url": "https://jobs.jobvite.com/{slug}/jobs", "cards": {
        "card": r'class="jv-job-list-name"', "link": r'href="(/[^"]+/job/[^"]+)">(.*?)</a>', "location": r'jv-job-list-location">\s*(.*?)\s*</td>'}},
    "applicantstack": {"url": "https://{slug}.applicantstack.com/x/openings", "cards": {
        "card": r'<tr class="(?:even|odd)row">', "link": r'href="(https://[^"]+/x/detail/[^"]+)">(.*?)</a>', "location": r'</a></td><td[^>]*>(.*?)</td>'}},
    "softgarden": {"url": "https://{slug}.softgarden.io/en/vacancies", "cards": {
        "card": r'id="job_id_\d+"|class="matchElement', "link": r'href="(\.\./job/\d+/[^"]+)"[^>]*>(.*?)</a>',
        "location": r'location-view-item">(.*?)</span>', "date": r'matchValue date">(.*?)</div>'}},
    "loxo": {"url": "https://app.loxo.co/{slug}", "cards": {
        "link": r"job-title'[^>]*href=\"(/job/[^\"]+)\"[^>]*>(.*?)</a>", "location": r"job-location'[^>]*>(?:\s*<i[^>]*>.*?</i>)?\s*(.*?)\s*</div>"}},
    "avature": {"url": "{base}/en_US/careers/SearchJobs?jobRecordsPerPage=50&jobOffset=0", "cards": {
        "card": r'class="article article--result', "link": r'article__header__text__title[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        "location": r'list-item-location">(.*?)</span>'}},
    "growthzone": {"url": "{base}/jobs", "cards": {
        "card": r'gz-jobs-card-body', "link": r'href="([^"]*/jobs/info/[^"]+)">(.*?)</a>', "description": r'gz-job-description">(.*?)</p>',
        "date": r'gz-jobs-date">\s*Posted\s*(.*?)</small>'}},
}


async def _card_board(ctx: Ctx, b: dict) -> list[RawJob]:
    """A board on a system in CARD_BOARDS."""
    spec, values = CARD_BOARDS[b["ats"]], _values(b)
    url = _fill(spec["url"], values)
    response = await ctx.polite("GET", url)
    out = []
    for card in readers.card_records(response.text, spec["cards"], str(response.url)):
        out.append(_posting(b, b["ats"], title=card["title"], url=card["url"], location=card.get("location", ""), posted_at=card.get("date"),
                            description=card.get("description", ""), found_url=url))
    return out


def _title_place(title: str) -> tuple[str, str]:
    """(title, place) from a headline with the place in parentheses at its end: "Nurse (Durham, NC, US)"."""
    found = re.fullmatch(r"(.*\S)\s*\(([^()]*,[^()]*)\)\s*", title)
    return (found.group(1), found.group(2)) if found else (title, "")


async def _feed_jobs(ctx: Ctx, b: dict, url: str, system: str, found_url: str) -> list[RawJob]:
    """A board's RSS or Atom feed."""
    out = []
    for item in readers.feed_records((await ctx.polite("GET", url)).text):
        title, place = _title_place(readers.text_of(item.get("title")))
        out.append(_posting(b, system, title=title, url=item.get("link", ""), location=place,
                            posted_at=item.get("pubDate") or item.get("published") or item.get("updated"),
                            description=item.get("description") or item.get("content") or item.get("summary") or "", found_url=found_url))
    return [j for j in out if j.title and j.url]


async def _per_term(ctx: Ctx, b: dict, read_term) -> list[RawJob]:
    """Run read_term(term) for each search word and join the postings without repeats. One failed word costs that word, a
    refusal ends the board, and a board where every word failed raises its last error (see _Terms)."""
    out, seen, terms = [], set(), _Terms(ctx, b)
    for term in _few_terms(ctx.cfg):
        try:
            jobs = await read_term(term)
        except Blocked:
            if terms.answered:
                break
            raise
        except Exception as e:  # noqa: BLE001 (one failing term shouldn't sink the board)
            if terms.failed(term, e):
                break
            continue
        terms.answered = True
        for job in jobs:
            if job.url not in seen:
                seen.add(job.url)
                out.append(job)
    return terms.done(out)


async def successfactors(ctx: Ctx, b: dict) -> list[RawJob]:
    """SAP SuccessFactors career sites: a keyword RSS feed, 20 newest per search word. The place is in the title."""
    base = _values(b)["base"]
    return await _per_term(ctx, b, lambda term: _feed_jobs(
        ctx, b, f"{base}/services/rss/job/?locale=en_US" + (f"&keywords=({quote(term)})" if term else ""), "successfactors", base))


async def peopleadmin(ctx: Ctx, b: dict) -> list[RawJob]:
    """PeopleAdmin, the system most US colleges use for all campus jobs: an Atom feed of a posting search."""
    base = _values(b)["base"]
    return await _per_term(ctx, b, lambda term: _feed_jobs(
        ctx, b, f"{base}/postings/search.atom?query={quote_plus(term)}", "peopleadmin", f"{base}/postings/search"))


async def teamtailor(ctx: Ctx, b: dict) -> list[RawJob]:
    """Teamtailor's RSS feed of a whole board, with structured places and a remote flag."""
    base = _values(b)["base"]
    out = []
    for item in readers.xml_records((await ctx.polite("GET", f"{base}/jobs.rss")).text, "item"):
        places = (item.get("locations") or {}).get("location") if isinstance(item.get("locations"), dict) else None
        places = places if isinstance(places, list) else [places] if places else []
        where = [", ".join(x for x in [p.get("city"), p.get("country")] if x) for p in places if isinstance(p, dict)]
        if str(item.get("remoteStatus") or "none") not in ("none", ""):
            where.append("Remote")
        out.append(_posting(b, "teamtailor", title=readers.text_of(item.get("title")), url=item.get("link", ""), locations=[w for w in where if w],
                            posted_at=item.get("pubDate"), description=item.get("description", ""), found_url=f"{base}/jobs"))
    return [j for j in out if j.title and j.url]


async def jazzhr(ctx: Ctx, b: dict) -> list[RawJob]:
    """JazzHR's export feed: the whole board in one XML file."""
    out = []
    for job in readers.xml_records((await ctx.polite("GET", f"https://app.jazz.co/feeds/export/jobs/{b['slug']}")).text, "job"):
        if not isinstance(job, dict):
            continue
        place = ", ".join(str(job[k]) for k in ("city", "state", "country") if job.get(k))
        out.append(_posting(b, "jazzhr", title=readers.text_of(job.get("title")), url=str(job.get("url") or ""), location=place,
                            description=job.get("description", ""), found_url=f"https://{b['slug']}.applytojob.com/apply"))
    return [j for j in out if j.title and j.url]


async def oracle(ctx: Ctx, b: dict) -> list[RawJob]:
    """Oracle Recruiting Cloud: the open JSON search behind its career sites, 25 newest per search word."""
    base, site = _values(b)["base"], re.search(r"/sites/([^/?#]+)", b["url"]).group(1)
    home = f"{base}/hcmUI/CandidateExperience/en/sites/{site}"

    async def read_term(term: str) -> list[RawJob]:
        keyword = f',keyword="{quote(term)}"' if term else ""
        d = (await ctx.polite("GET", f"{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
                                     f"&expand=requisitionList&finder=findReqs;siteNumber={site},limit=25,offset=0{keyword}")).json()
        return [_posting(b, "oracle", title=j.get("Title", ""), url=f"{home}/job/{j.get('Id')}", location=j.get("PrimaryLocation", ""),
                         posted_at=j.get("PostedDate"), description=j.get("ShortDescriptionStr", ""), found_url=home)
                for item in d.get("items") or [] for j in item.get("requisitionList") or [] if j.get("Id")]
    return await _per_term(ctx, b, read_term)


async def phenom(ctx: Ctx, b: dict) -> list[RawJob]:
    """Phenom career sites keep their results in a JSON object (phApp.ddo) inside the search page."""
    base = _values(b)["base"]

    async def read_term(term: str) -> list[RawJob]:
        page = (await ctx.polite("GET", f"{base}/us/en/search-results?keywords={quote_plus(term)}")).text
        data = readers.embedded_json(page, "phApp.ddo =") or {}
        jobs = readers.dig(data, "eagerLoadRefineSearch.data.jobs") or []
        return [_posting(b, "phenom", title=j.get("title", ""), url=f"{base}/us/en/job/{j.get('jobId')}",
                         location=", ".join(x for x in [j.get("city"), j.get("state"), j.get("country")] if x),
                         posted_at=j.get("postedDate"), description=j.get("descriptionTeaser", ""), found_url=f"{base}/us/en/search-results")
                for j in jobs if isinstance(j, dict) and j.get("jobId")]
    return await _per_term(ctx, b, read_term)


async def taleo(ctx: Ctx, b: dict) -> list[RawJob]:
    """Oracle Taleo: the JSON search its career section pages use. The portal number comes from the page once per board.
    Employers choose their columns, usually title, place and date."""
    u = urlparse(b["url"])
    section = re.search(r"/careersection/([^/]+)", u.path).group(1)
    base = f"{u.scheme}://{u.netloc}"
    page = (await ctx.polite("GET", f"{base}/careersection/{section}/jobsearch.ftl")).text
    portal = re.search(r"portal=(\d+)", page)
    if not portal:
        raise ValueError("no portal number on the page")

    async def read_term(term: str) -> list[RawJob]:
        body = {"multilineEnabled": False, "sortingSelection": {"sortBySelectionParam": "3", "ascendingSortingOrder": "false"},
                "fieldData": {"fields": {"KEYWORD": term, "LOCATION": ""}, "valid": True},
                "filterSelectionParam": {"searchFilterSelections": []},
                "advancedSearchFiltersSelectionParam": {"searchFilterSelections": []}, "pageNo": 1}
        d = (await ctx.polite("POST", f"{base}/careersection/rest/jobboard/searchjobs?lang=en&portal={portal.group(1)}", content=json.dumps(body),
                              headers={"Content-Type": "application/json", "Accept": "application/json", "tz": "GMT-05:00"})).json()
        out = []
        for j in d.get("requisitionList") or []:
            cells = j.get("column") or []
            place = cells[1] if len(cells) > 1 else ""
            try:  # the place column is a JSON list written as text
                place = ", ".join(json.loads(place)) if str(place).startswith("[") else place
            except ValueError:
                pass
            out.append(_posting(b, "taleo", title=cells[0] if cells else "", url=f"{base}/careersection/{section}/jobdetail.ftl?job={j.get('contestNo')}",
                                location=str(place), posted_at=cells[2] if len(cells) > 2 else None,
                                found_url=f"{base}/careersection/{section}/jobsearch.ftl"))
        return [x for x in out if x.title]
    return await _per_term(ctx, b, read_term)


async def paylocity(ctx: Ctx, b: dict) -> list[RawJob]:
    """Paylocity: the board page keeps its jobs in a JSON object (window.pageData)."""
    url = f"https://recruiting.paylocity.com/recruiting/jobs/All/{b['slug']}"
    data = readers.embedded_json((await ctx.polite("GET", url)).text, "window.pageData =") or {}
    return [_posting(b, "paylocity", title=j.get("JobTitle", ""), url=f"https://recruiting.paylocity.com/Recruiting/Jobs/Details/{j.get('JobId')}",
                     location=j.get("LocationName", ""), posted_at=j.get("PublishedDate"), description=j.get("Description", ""), found_url=url)
            for j in data.get("Jobs") or [] if j.get("JobId")]


async def applicantpro(ctx: Ctx, b: dict) -> list[RawJob]:
    """ApplicantPro (isolved Hire): the job page names the site's id, and the JSON list is read with it."""
    base = _values(b)["base"]
    page = (await ctx.polite("GET", f"{base}/jobs/")).text
    domain = re.search(r'"domain_id":\s*"?(\d+)', page)
    if not domain:
        raise ValueError("no site id on the page")
    d = (await ctx.polite("GET", f"{base}/core/jobs/{domain.group(1)}?getParams=" + quote('{"isInternal":0}'))).json()
    return [_posting(b, "applicantpro", title=j.get("title", ""), url=f"{base}/jobs/{j.get('id')}", company=j.get("orgTitle") or b["name"],
                     location=", ".join(str(x) for x in [j.get("city"), j.get("abbreviation")] if x), posted_at=j.get("startDateRef"),
                     found_url=f"{base}/jobs/") for j in readers.dig(d, "data.jobs") or [] if j.get("id")]


async def join(ctx: Ctx, b: dict) -> list[RawJob]:
    """JOIN company pages: the jobs are in the page's Next.js data."""
    url = f"https://join.com/companies/{b['slug']}"
    data = readers.embedded_json((await ctx.polite("GET", url)).text, '"jobs":') or {}
    return [_posting(b, "join", title=j.get("title", ""), url=f"{url}/{j.get('idParam')}", posted_at=j.get("createdAt"),
                     location=", ".join(x for x in [(j.get("city") or {}).get("cityName"), (j.get("city") or {}).get("countryName")] if x),
                     found_url=url) for j in data.get("items") or [] if j.get("idParam")]


HANDLERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday, "ukg": ukg,
            "icims": icims, "smartrecruiters": smartrecruiters, "recruitee": recruitee, "personio": personio,
            "successfactors": successfactors, "peopleadmin": peopleadmin, "teamtailor": teamtailor, "jazzhr": jazzhr,
            "oracle": oracle, "phenom": phenom, "taleo": taleo, "paylocity": paylocity, "applicantpro": applicantpro, "join": join,
            **{system: _json_board for system in JSON_BOARDS}, **{system: _card_board for system in CARD_BOARDS}}


def _board_slots(ctx: Ctx) -> asyncio.Semaphore:
    """The limit on boards read at once, shared by everything in this run that reads boards."""
    return ctx.cache.setdefault("ats_board_slots", asyncio.Semaphore(BOARDS_AT_ONCE))


async def read_board(ctx: Ctx, b: dict) -> list[RawJob]:
    """One board's postings, or [] when it can't be read (wrong slug, site down, format changed, a refusal, or no answer
    within BOARD_TIMEOUT). A failure is one line in the log. A board naming an unknown system is skipped quietly."""
    handler = HANDLERS.get(b.get("ats"))
    if not handler:
        return []
    async with _board_slots(ctx):
        try:
            return await asyncio.wait_for(handler(ctx, b), timeout=BOARD_TIMEOUT)
        except TimeoutError:
            ctx.log("ats", f"{b['name']} ({b.get('ats')}): no answer within {BOARD_TIMEOUT} seconds, skipped this run", "warn")
        except Blocked as e:
            ctx.log("ats", f"{b['name']} ({b.get('ats')}): refused ({e}), left alone this run", "warn")
        except Exception as e:  # noqa: BLE001 (one broken board shouldn't sink the rest)
            ctx.log("ats", f"{b['name']} ({b.get('ats')}): {type(e).__name__}: {str(e)[:120]}", "warn")
    return []


def board_key(b: dict) -> str:
    """What identifies a board across lists: its system and its slug or address, in lowercase."""
    return f"{b.get('ats')}:{str(b.get('slug') or b.get('url') or '').rstrip('/').lower()}"


async def collect(ctx: Ctx) -> list[RawJob]:
    """Read every enabled board, BOARDS_AT_ONCE at a time (see read_board)."""
    boards = [b for b in ctx.cfg["sources"]["ats_boards"]["boards"] if b.get("enabled", True)]
    results = await asyncio.gather(*(read_board(ctx, b) for b in boards))
    out = [job for jobs in results for job in jobs]
    ctx.log("ats", f"{len(boards)} company boards → {len(out)} postings")
    return out


# The hosts of the job boards found by slug, where the company's slug comes first in the path. Only these count: a link to
# the systems' own websites (www.greenhouse.io/privacy-policy, www.lever.co/careers) isn't a board, and boards on hosts
# the readers above don't call (jobs.eu.lever.co) would only fail later.
SLUG_HOSTS = {"greenhouse": ("boards.greenhouse.io", "job-boards.greenhouse.io"), "lever": ("jobs.lever.co",),
              "ashby": ("jobs.ashbyhq.com",), "smartrecruiters": ("jobs.smartrecruiters.com", "careers.smartrecruiters.com"),
              "workable": ("apply.workable.com",), "jobvite": ("jobs.jobvite.com",), "rippling": ("ats.rippling.com",),
              "gem": ("jobs.gem.com",), "manatal": ("www.careers-page.com", "careers-page.com"), "loxo": ("app.loxo.co",)}
# Systems where the company's slug is the first part of the host: <slug>.bamboohr.com. A host with a www, or the vendor's own
# site, is no board.
SUBDOMAIN_HOSTS = {"bamboohr.com": "bamboohr", "applytojob.com": "jazzhr", "breezy.hr": "breezy", "pinpointhq.com": "pinpoint",
                   "applicantstack.com": "applicantstack", "softgarden.io": "softgarden", "traffit.com": "traffit"}
NOT_A_SLUG = {"www", "app", "api", "help", "support", "careers", "blog", "docs"}
# Host parts that are the vendor's own pages rather than a company on the system.
VENDOR_PATHS = {"workable": {"j", "api"}, "jobvite": {"support"}, "manatal": {"api"}, "rippling": {"api"}}


def detect(url: str) -> dict | None:
    """Turn a careers page or posting URL into a board entry ({"ats": ..., plus "slug" or "url"}), or None when it isn't a
    supported board (or isn't a valid address). For example jobs.lever.co/example-robotics/123 gives {"ats": "lever",
    "slug": "example-robotics"}."""
    try:
        u = urlparse(url.strip())
        host = (u.hostname or "").lower()
    except ValueError:  # such as "https://[x", whose host can't be read
        return None
    path = u.path
    segments = [s for s in path.split("/") if s]
    if host in SLUG_HOSTS["greenhouse"]:
        embed = re.search(r"for=([\w-]+)", u.query)  # embedded boards: boards.greenhouse.io/embed/job_board?for=<slug>
        if embed:
            return {"ats": "greenhouse", "slug": embed.group(1)}
        if segments and segments[0] not in ("embed", "v1"):  # job-boards.greenhouse.io/<slug>/jobs/<id>
            return {"ats": "greenhouse", "slug": segments[0]}
        return None
    for system in ("lever", "ashby", "smartrecruiters", "workable", "jobvite", "rippling", "gem", "manatal", "loxo"):
        if host in SLUG_HOSTS[system] and segments and segments[0] not in VENDOR_PATHS.get(system, ()):
            return {"ats": system, "slug": segments[0]}
    if host.endswith(".myworkdayjobs.com"):  # <tenant>.wd5.myworkdayjobs.com
        site = [s for s in segments if not LOCALE_SEGMENT.fullmatch(s)]
        return {"ats": "workday", "url": f"https://{host}/{site[0] if site else 'External'}"}
    if host.endswith(".myworkdaysite.com"):  # wd5.myworkdaysite.com/[en-US/]recruiting/<tenant>/<site>
        parts = [s for s in segments if not LOCALE_SEGMENT.fullmatch(s)]
        if len(parts) >= 3 and parts[0] == "recruiting":
            return {"ats": "workday", "url": f"https://{host}/recruiting/{parts[1]}/{parts[2]}"}
        return None
    if host.endswith("ultipro.com") and "/jobboard/" in path.lower():
        # Everything up to the board's id, a GUID written in either case.
        board = re.search(r"(.*/JobBoard/[0-9a-f-]+)", f"https://{host}{path}", re.I)
        return {"ats": "ukg", "url": board.group(1)} if board else None
    if host.endswith(".icims.com"):
        return {"ats": "icims", "url": f"https://{host}"}
    if host.endswith(".recruitee.com") and host.count(".") == 2:  # <company>.recruitee.com
        return {"ats": "recruitee", "slug": host.split(".")[0]}
    if re.fullmatch(r"[a-z0-9-]+\.jobs\.personio\.(de|com)", host):  # <company>.jobs.personio.de
        return {"ats": "personio", "url": f"https://{host}"}
    return _detect_newer(host, path, u.query, segments)


def _detect_newer(host: str, path: str, query: str, segments: list[str]) -> dict | None:
    """detect() for the systems added later, by their addresses."""
    parts = host.split(".")
    for domain, system in SUBDOMAIN_HOSTS.items():
        if host.endswith(f".{domain}") and len(parts) == domain.count(".") + 2 and parts[0] not in NOT_A_SLUG:
            return {"ats": system, "slug": parts[0]}
    if host == "workforcenow.adp.com":
        cid = parse_qs(query).get("cid", [""])[0]
        return {"ats": "adp", "slug": cid} if cid else None
    if host == "recruiting.paylocity.com":
        guid = re.search(r"/jobs/all/([0-9a-f-]{36})", path, re.I)
        return {"ats": "paylocity", "slug": guid.group(1)} if guid else None
    if host.endswith(".oraclecloud.com"):
        site = re.search(r"/hcmUI/CandidateExperience/[^/]+/sites/([^/?#]+)", path, re.I)
        return {"ats": "oracle", "url": f"https://{host}/hcmUI/CandidateExperience/en/sites/{site.group(1)}"} if site else None
    if host.endswith(".taleo.net"):
        section = re.search(r"/careersection/([^/]+)", path)
        if section and section.group(1) != "rest":
            return {"ats": "taleo", "url": f"https://{host}/careersection/{section.group(1)}/jobsearch.ftl"}
        return None
    if host.endswith(".saashr.com"):
        company = re.search(r"/ta/([^./]+)\.careers", path)
        return {"ats": "ukg_ready", "url": f"https://{host}/ta/{company.group(1)}.careers"} if company else None
    if host.endswith((".applicantpro.com", ".isolvedhire.com")) and parts[0] not in NOT_A_SLUG:
        return {"ats": "applicantpro", "url": f"https://{host}"}
    if host.endswith(".peopleadmin.com") or "/postings/search" in path or (host.endswith(".edu") and re.match(r"/postings/\d+", path)):
        return {"ats": "peopleadmin", "url": f"https://{host}"}
    if host.endswith(".jibeapply.com") and parts[0] not in NOT_A_SLUG:
        return {"ats": "jibe", "url": f"https://{host}"}
    if host.endswith(".avature.net") or "/careers/SearchJobs" in path or "/careers/JobDetail" in path:
        return {"ats": "avature", "url": f"https://{host}"}
    if host.endswith(".teamtailor.com") and parts[0] not in NOT_A_SLUG:  # <company>.teamtailor.com or <company>.na.teamtailor.com
        return {"ats": "teamtailor", "url": f"https://{host}"}
    if host == "join.com" and len(segments) >= 2 and segments[0] == "companies":
        return {"ats": "join", "slug": segments[1]}
    if (host.endswith(".jobs2web.com") or re.match(r"career\w*\.successfactors\.", host)) and parts[0] not in NOT_A_SLUG:
        return {"ats": "successfactors", "url": f"https://{host}"}
    if re.fullmatch(r"/job/[^/]+/\d{8,}/?", path):  # the address every SuccessFactors career site gives a job
        return {"ats": "successfactors", "url": f"https://{host}"}
    if host.startswith("business.") and re.match(r"/jobs(?:/info/|/?$)", path):  # a chamber of commerce on GrowthZone
        return {"ats": "growthzone", "url": f"https://{host}"}
    return None
