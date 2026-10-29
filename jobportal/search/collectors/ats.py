"""Company job boards with public APIs: Greenhouse, Lever, Ashby, Workday, UKG (UltiPro), iCIMS, SmartRecruiters.
Also exposes detail fetchers used to pull full descriptions for a single posting URL."""
import asyncio
import re
from urllib.parse import urlparse

from jobportal.core.levels import ats_search_terms
from jobportal.core.textutil import clean, html_to_text, parse_date
from jobportal.search import plan
from jobportal.search.collectors.base import Ctx, RawJob


def search_terms(cfg: dict) -> list[str]:
    """Keywords for boards that need one (Workday, iCIMS): level words for early careers, your search queries otherwise."""
    return ats_search_terms(plan.levels(cfg), plan.all_queries(cfg)) or ["engineer", "analyst"]


def _wd_parts(url: str) -> tuple[str, str, str]:
    """https://leidos.wd5.myworkdayjobs.com/en-US/External -> (base host url, tenant, site)."""
    u = urlparse(url)
    tenant = u.netloc.split(".")[0]
    segs = [s for s in u.path.split("/") if s and not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", s)]
    site = segs[0] if segs else "External"
    return f"{u.scheme}://{u.netloc}", tenant, site


async def greenhouse(ctx: Ctx, b: dict) -> list[RawJob]:
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


async def lever(ctx: Ctx, b: dict) -> list[RawJob]:
    d = await ctx.get_json(f"https://api.lever.co/v0/postings/{b['slug']}?mode=json")
    out = []
    for j in d if isinstance(d, list) else []:
        cats = j.get("categories") or {}
        desc = (j.get("descriptionPlain") or "") + "\n" + "\n".join(
            f"{l.get('text', '')}:\n{html_to_text(l.get('content', ''))}" for l in j.get("lists", [])) + "\n" + (j.get("additionalPlain") or "")
        locs = cats.get("allLocations") or ([cats.get("location")] if cats.get("location") else [])
        out.append(RawJob(source="ats", title=j.get("text", ""), company=b["name"], url=j.get("hostedUrl", ""),
                          apply_url=j.get("applyUrl"), locations=locs, location=" | ".join(locs),
                          description=desc.strip(), posted_at=parse_date(j.get("createdAt")),
                          category_hint=cats.get("commitment", ""), dream=bool(b.get("dream")),
                          source_detail=f"Lever: {b['name']}", found_url=f"https://jobs.lever.co/{b['slug']}", meta={"ats": "lever"}))
    return out


async def ashby(ctx: Ctx, b: dict) -> list[RawJob]:
    d = await ctx.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{b['slug']}")
    out = []
    for j in d.get("jobs", []):
        locs = [j.get("location", "")] + [x.get("location", "") for x in j.get("secondaryLocations", []) or []]
        if j.get("isRemote"):
            locs.append("Remote")
        locs = [l for l in locs if l]
        out.append(RawJob(source="ats", title=j.get("title", ""), company=b["name"], url=j.get("jobUrl", ""),
                          apply_url=j.get("applyUrl"), locations=locs, location=" | ".join(locs),
                          description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
                          posted_at=parse_date(j.get("publishedAt")), category_hint=j.get("employmentType", ""),
                          dream=bool(b.get("dream")), source_detail=f"Ashby: {b['name']}", found_url=f"https://jobs.ashbyhq.com/{b['slug']}",
                          meta={"ats": "ashby"}))
    return out


async def workday(ctx: Ctx, b: dict) -> list[RawJob]:
    base, tenant, site = _wd_parts(b["url"])
    api = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    seen, out = set(), []
    for term in search_terms(ctx.cfg):
        for offset in range(0, 100, 20):
            try:
                d = await ctx.post_json(api, {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term})
            except Exception as e:  # noqa: BLE001 (one failing term shouldn't sink the board)
                ctx.log("ats", f"{b['name']}: workday '{term}' failed: {e}", "warn")
                break
            posts = d.get("jobPostings", [])
            for j in posts:
                path = j.get("externalPath")
                if not path or path in seen:
                    continue
                seen.add(path)
                out.append(RawJob(source="ats", title=j.get("title", ""), company=b["name"], url=f"{base}/{site}{path}",
                                  location=j.get("locationsText", ""), posted_at=parse_date(j.get("postedOn")),
                                  dream=bool(b.get("dream")), source_detail=f"Workday: {b['name']}", found_url=b["url"],
                                  meta={"ats": "workday", "api": f"{base}/wday/cxs/{tenant}/{site}{path}"}))
            if len(posts) < 20 or offset + 20 >= d.get("total", 0):
                break
    return out


UKG_BODY = {"opportunitySearch": {"Top": 100, "Skip": 0, "QueryString": "", "OrderBy": [
    {"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}], "Filters": [
    {"t": "TermsSearchFilterDto", "fieldName": 4, "extra": None, "values": []},
    {"t": "TermsSearchFilterDto", "fieldName": 5, "extra": None, "values": []},
    {"t": "TermsSearchFilterDto", "fieldName": 6, "extra": None, "values": []}]},
    "matchCriteria": {"PreferredJobs": [], "Educations": [], "LicenseAndCertifications": [], "Skills": [],
                      "hasNoLicenses": False, "SkippedSkills": []}}


async def ukg(ctx: Ctx, b: dict) -> list[RawJob]:
    base = b["url"].rstrip("/")
    d = await ctx.post_json(f"{base}/JobBoardView/LoadSearchResults", UKG_BODY)
    out = []
    for j in d.get("opportunities", []):
        locs = []
        for l in j.get("Locations") or []:
            a = l.get("Address") or {}
            locs.append(", ".join(x for x in [a.get("City"), (a.get("State") or {}).get("Code")] if x) or l.get("LocalizedName", ""))
        out.append(RawJob(source="ats", title=j.get("Title", ""), company=b["name"],
                          url=f"{base}/OpportunityDetail?opportunityId={j.get('Id')}", locations=locs, location=" | ".join(locs),
                          description=j.get("BriefDescription", ""), posted_at=parse_date(j.get("PostedDate")),
                          dream=bool(b.get("dream")), source_detail=f"UKG: {b['name']}", found_url=base, meta={"ats": "ukg"}))
    return out


async def icims(ctx: Ctx, b: dict) -> list[RawJob]:
    base = b["url"].rstrip("/")
    host = urlparse(base).netloc
    out, seen = [], set()
    for term in search_terms(ctx.cfg):
        html = await ctx.get_text(f"{base}/jobs/search?ss=1&searchKeyword={term.replace(' ', '+')}&in_iframe=1")
        for card in html.split('class="iCIMS_JobCardItem"')[1:]:
            m = re.search(rf'href="(https://{re.escape(host)}/jobs/(\d+)/[^"]+)"', card)
            if not m or m.group(2) in seen:
                continue
            seen.add(m.group(2))
            title = re.search(r"<h3[^>]*>(.*?)</h3>", card, re.S)
            loc = re.search(r"Job Locations?</span>\s*<span[^>]*>(.*?)</span>", card, re.S)
            posted = re.search(r'Posted Date</span>\s*<span title="([^"]+)"', card)
            desc = re.search(r'class="col-xs-12 description">(.*?)</div>', card, re.S)
            out.append(RawJob(source="ats", title=clean(html_to_text(title.group(1) if title else "")), company=b["name"],
                              url=m.group(1).replace("?in_iframe=1", ""), location=clean(loc.group(1) if loc else ""),
                              description=html_to_text(desc.group(1) if desc else ""),
                              posted_at=parse_date((posted.group(1).split(" ")[0]) if posted else None),
                              dream=bool(b.get("dream")), source_detail=f"iCIMS: {b['name']}", found_url=f"{base}/jobs/search?ss=1",
                              meta={"ats": "icims"}))
    return out


async def smartrecruiters(ctx: Ctx, b: dict) -> list[RawJob]:
    d = await ctx.get_json(f"https://api.smartrecruiters.com/v1/companies/{b['slug']}/postings?limit=100")
    out = []
    for j in d.get("content", []):
        loc = j.get("location") or {}
        out.append(RawJob(source="ats", title=j.get("name", ""), company=b["name"],
                          url=f"https://jobs.smartrecruiters.com/{b['slug']}/{j.get('id')}",
                          location=", ".join(x for x in [loc.get("city"), loc.get("region")] if x) + (" (Remote)" if loc.get("remote") else ""),
                          posted_at=parse_date(j.get("releasedDate")), dream=bool(b.get("dream")),
                          source_detail=f"SmartRecruiters: {b['name']}", found_url=f"https://jobs.smartrecruiters.com/{b['slug']}",
                          meta={"ats": "smartrecruiters", "api": f"https://api.smartrecruiters.com/v1/companies/{b['slug']}/postings/{j.get('id')}"}))
    return out


HANDLERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday, "ukg": ukg,
            "icims": icims, "smartrecruiters": smartrecruiters}


async def collect(ctx: Ctx) -> list[RawJob]:
    boards = [b for b in ctx.cfg["sources"]["ats_boards"]["boards"] if b.get("enabled", True)]
    sem = asyncio.Semaphore(8)

    async def one(b):
        async with sem:
            fn = HANDLERS.get(b.get("ats"))
            if not fn:
                return []
            try:
                jobs = await fn(ctx, b)
                return jobs
            except Exception as e:  # noqa: BLE001
                ctx.log("ats", f"{b['name']} ({b.get('ats')}): {type(e).__name__}: {str(e)[:120]}", "warn")
                return []

    results = await asyncio.gather(*(one(b) for b in boards))
    out = [j for r in results for j in r]
    ctx.log("ats", f"{len(boards)} company boards → {len(out)} postings")
    return out


def detect(url: str) -> dict | None:
    """Turn a careers/job URL into a board config, if it's a supported ATS."""
    u = urlparse(url.strip())
    host, path = u.netloc.lower(), u.path
    segs = [s for s in path.split("/") if s]
    if "greenhouse.io" in host:
        if "for=" in u.query:
            return {"ats": "greenhouse", "slug": re.search(r"for=([\w-]+)", u.query).group(1)}
        if segs and segs[0] not in ("embed", "v1"):
            return {"ats": "greenhouse", "slug": segs[0]}
    if "lever.co" in host and segs:
        return {"ats": "lever", "slug": segs[0]}
    if "ashbyhq.com" in host and segs:
        return {"ats": "ashby", "slug": segs[0]}
    if "myworkdayjobs.com" in host:
        site = [s for s in segs if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", s)]
        return {"ats": "workday", "url": f"https://{host}/{site[0] if site else 'External'}"}
    if "ultipro.com" in host and "JobBoard" in path:
        m = re.search(r"(.*/JobBoard/[0-9a-f-]+)", f"https://{host}{path}")
        return {"ats": "ukg", "url": m.group(1)} if m else None
    if host.endswith(".icims.com"):
        return {"ats": "icims", "url": f"https://{host}"}
    if "smartrecruiters.com" in host and segs:
        return {"ats": "smartrecruiters", "slug": segs[0]}
    return None
