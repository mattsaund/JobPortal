"""Fetch the full text of one posting, for jobs that arrived with only a title or a short snippet.

The search run calls fetch() before triage (Pipeline.enrich in pipeline.py), and package building calls it before writing
(packages.py), so the AI judges and tailors from the real posting. Known systems are read through their JSON APIs: Greenhouse,
Lever, Workday, SmartRecruiters and Ashby, plus LinkedIn's guest posting page. Any other page is read as HTML: a schema.org
JobPosting block is preferred (many career sites embed one as JSON-LD for Google Jobs), and the page's visible text is the
last resort.

fetch() returns a dict that always has "description" and, when the source gives them, "apply_url", "deadline", "location",
"posted_at", "company" and "title". It raises on network and HTTP errors; callers treat a failure as "no extra details"."""
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

from jobportal.core.textutil import clean, html_to_text, parse_date
from jobportal.search.collectors.ats import LOCALE_SEGMENT, lever_description
from jobportal.search.collectors.base import Ctx

MAX_DESC = 15000  # characters kept from a description (each AI prompt then takes its own, often shorter, excerpt)
SNIPPET_LENGTH = 600  # a description shorter than this is probably a snippet from a list, so the full posting is worth fetching


def _jsonld_jobposting(html: str) -> dict | None:
    """The first schema.org JobPosting in the page's JSON-LD script blocks, or None. A block may hold one object, a list of
    objects, or an "@graph" list."""
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict) and "JobPosting" in str(item.get("@type")):  # @type can be a string or a list
                return item
    return None


def _ld_location(posting: dict) -> str:
    """A JobPosting's locations as "City, ST | City, ST", plus "Remote" when it is marked as telecommuting."""
    places = posting.get("jobLocation") or []
    places = places if isinstance(places, list) else [places]
    out = []
    for place in places:
        address = (place or {}).get("address") or {}
        if isinstance(address, dict):  # some sites put a plain string here, which has no parts to read
            out.append(", ".join(x for x in [address.get("addressLocality"), address.get("addressRegion")] if x))
    if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        out.append("Remote")
    return " | ".join(o for o in out if o)


async def linkedin_detail(ctx: Ctx, job_id: str) -> dict:
    """A LinkedIn posting from the guest posting page (jobs-guest/jobs/api/jobPosting/<id>, the same HTML a logged-out
    visitor gets). Returns the description with the job criteria appended (seniority, employment type and so on) and, when
    the posting links to the employer's own application page, that apply_url."""
    html = await ctx.get_text(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}")
    body = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', html, re.S)
    out = {"description": html_to_text(body.group(1)) if body else ""}
    criteria = re.findall(r'description__job-criteria-subheader">\s*([^<]+?)\s*</h3>\s*<span[^>]*>\s*([^<]+?)\s*</span>', html)
    if criteria:
        out["description"] += "\n\n" + "\n".join(f"{name}: {value}" for name, value in criteria)
    # An offsite apply link sits in an HTML comment inside <code id="applyUrl">, wrapped in a LinkedIn redirect whose "url"
    # parameter holds the real address.
    apply = re.search(r'<code id="applyUrl"[^>]*><!--"(.*?)"--></code>', html)
    if apply:
        link = apply.group(1)
        query = parse_qs(urlparse(link).query)
        out["apply_url"] = unquote(query["url"][0]) if "url" in query else link
    return out


async def fetch(ctx: Ctx, url: str, meta: dict | None = None) -> dict:
    """Fetch one posting's full details. meta is the RawJob's meta from its collector (board slug, job id, API address); it
    saves guessing them from the URL. See the module docstring for what comes back."""
    meta = meta or {}
    u = urlparse(url)
    host, segments = u.netloc.lower(), [s for s in u.path.split("/") if s]

    if meta.get("ats") == "greenhouse" or "greenhouse.io" in host:
        slug, job_id = meta.get("slug"), meta.get("id")
        if not job_id:
            query = parse_qs(u.query)
            if "token" in query and "for" in query:  # embedded board link: ...?for=<slug>&token=<job id>
                slug, job_id = query["for"][0], query["token"][0]
            elif len(segments) >= 3 and segments[1] == "jobs":  # job-boards.greenhouse.io/<slug>/jobs/<job id>
                slug, job_id = segments[0], segments[2]
        if slug and job_id:
            d = await ctx.get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{job_id}")
            return {"description": html_to_text(d.get("content", ""))[:MAX_DESC],
                    "location": (d.get("location") or {}).get("name", "")}

    if "jobs.lever.co" in host and len(segments) >= 2:  # jobs.lever.co/<slug>/<posting id>
        d = await ctx.get_json(f"https://api.lever.co/v0/postings/{segments[0]}/{segments[1]}")
        return {"description": lever_description(d)[:MAX_DESC], "apply_url": d.get("applyUrl")}

    if "myworkdayjobs.com" in host:
        api = meta.get("api")
        if not api:  # <tenant>.wd5.myworkdayjobs.com/[en-US/]<site>/job/<location>/<title>_<id> -> its API address
            tenant = host.split(".")[0]
            path = [s for s in segments if not LOCALE_SEGMENT.fullmatch(s)]
            if len(path) >= 2:
                api = f"https://{host}/wday/cxs/{tenant}/{path[0]}/" + "/".join(path[1:])
        if api:
            d = await ctx.get_json(api, headers={"Accept": "application/json"})
            info = d.get("jobPostingInfo", {})
            locations = [info.get("location", "")] + (info.get("additionalLocations") or [])
            return {"description": html_to_text(info.get("jobDescription", ""))[:MAX_DESC],
                    "location": " | ".join(loc for loc in locations if loc), "posted_at": parse_date(info.get("startDate")),
                    "deadline": parse_date(info.get("endDate")), "apply_url": info.get("externalUrl")}

    linkedin = re.search(r"linkedin\.com/jobs/view/(?:[^/?]*-)?(\d{6,})", url)  # /jobs/view/<id> or /jobs/view/<title>-<id>
    if linkedin:
        return await linkedin_detail(ctx, linkedin.group(1))

    if meta.get("ats") == "smartrecruiters" and meta.get("api"):
        d = await ctx.get_json(meta["api"])
        sections = (d.get("jobAd") or {}).get("sections") or {}
        text = "\n\n".join(html_to_text((sections.get(k) or {}).get("text", "")) for k in
                           ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))
        return {"description": text[:MAX_DESC], "apply_url": d.get("applyUrl")}

    if "ashbyhq.com" in host and len(segments) >= 2:  # jobs.ashbyhq.com/<slug>/<job id>
        # Ashby has no single-posting API, so read the whole board once per run and find the posting in it.
        boards = ctx.cache.setdefault("ashby_boards", {})
        if segments[0] not in boards:
            boards[segments[0]] = await ctx.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{segments[0]}")
        for j in boards[segments[0]].get("jobs", []):
            if j.get("id") == segments[1]:
                return {"description": (j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")))[:MAX_DESC],
                        "apply_url": j.get("applyUrl")}

    # Any other page. iCIMS pages need in_iframe=1 to return the posting without the company's page around it.
    fetch_url = (url + ("&" if "?" in url else "?") + "in_iframe=1") if host.endswith(".icims.com") else url
    html = await ctx.get_text(fetch_url)
    posting = _jsonld_jobposting(html)
    if posting:
        org = posting.get("hiringOrganization")
        return {"description": html_to_text(posting.get("description", ""))[:MAX_DESC],
                "posted_at": parse_date(posting.get("datePosted")), "deadline": parse_date(posting.get("validThrough")),
                "location": _ld_location(posting), "company": org.get("name") if isinstance(org, dict) else None,
                "title": clean(posting.get("title"))}
    body = re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I)
    return {"description": html_to_text(body.group(1) if body else html)[:MAX_DESC]}
