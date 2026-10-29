"""Fetch the full description (and apply URL / deadline when available) for a single posting URL."""
import json
import re
from urllib.parse import parse_qs, unquote, urlparse

from ..textutil import clean, html_to_text, parse_date
from .base import Ctx

MAX_DESC = 15000


def _jsonld_jobposting(html: str) -> dict | None:
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for it in items:
            if isinstance(it, dict) and "JobPosting" in str(it.get("@type")):
                return it
    return None


def _ld_location(jp: dict) -> str:
    locs = jp.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    out = []
    for l in locs:
        a = (l or {}).get("address") or {}
        if isinstance(a, dict):
            out.append(", ".join(x for x in [a.get("addressLocality"), a.get("addressRegion")] if x))
    if str(jp.get("jobLocationType", "")).upper() == "TELECOMMUTE":
        out.append("Remote")
    return " | ".join(o for o in out if o)


async def linkedin_detail(ctx: Ctx, job_id: str) -> dict:
    html = await ctx.get_text(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}")
    m = re.search(r'show-more-less-html__markup[^>]*>(.*?)</div>', html, re.S)
    out = {"description": html_to_text(m.group(1)) if m else ""}
    crit = re.findall(r'description__job-criteria-subheader">\s*([^<]+?)\s*</h3>\s*<span[^>]*>\s*([^<]+?)\s*</span>', html)
    if crit:
        out["description"] += "\n\n" + "\n".join(f"{k}: {v}" for k, v in crit)
    a = re.search(r'<code id="applyUrl"[^>]*><!--"(.*?)"--></code>', html)
    if a:
        link = a.group(1)
        q = parse_qs(urlparse(link).query)
        out["apply_url"] = unquote(q["url"][0]) if "url" in q else link
    return out


async def fetch(ctx: Ctx, url: str, meta: dict | None = None) -> dict:
    meta = meta or {}
    u = urlparse(url)
    host, segs = u.netloc.lower(), [s for s in u.path.split("/") if s]

    if meta.get("ats") == "greenhouse" or "greenhouse.io" in host:
        slug, jid = meta.get("slug"), meta.get("id")
        if not jid:
            q = parse_qs(u.query)
            if "token" in q and "for" in q:
                slug, jid = q["for"][0], q["token"][0]
            elif len(segs) >= 3 and segs[1] == "jobs":
                slug, jid = segs[0], segs[2]
        if slug and jid:
            d = await ctx.get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs/{jid}")
            return {"description": html_to_text(d.get("content", ""))[:MAX_DESC],
                    "location": (d.get("location") or {}).get("name", "")}

    if "jobs.lever.co" in host and len(segs) >= 2:
        d = await ctx.get_json(f"https://api.lever.co/v0/postings/{segs[0]}/{segs[1]}")
        desc = (d.get("descriptionPlain") or "") + "\n" + "\n".join(
            f"{l.get('text', '')}:\n{html_to_text(l.get('content', ''))}" for l in d.get("lists", []))
        return {"description": desc[:MAX_DESC], "apply_url": d.get("applyUrl")}

    if "myworkdayjobs.com" in host:
        api = meta.get("api")
        if not api:
            tenant = host.split(".")[0]
            path = [s for s in segs if not re.fullmatch(r"[a-z]{2}-[A-Z]{2}", s)]
            if len(path) >= 2:
                api = f"https://{host}/wday/cxs/{tenant}/{path[0]}/" + "/".join(path[1:])
        if api:
            d = await ctx.get_json(api, headers={"Accept": "application/json"})
            info = d.get("jobPostingInfo", {})
            locs = [info.get("location", "")] + (info.get("additionalLocations") or [])
            return {"description": html_to_text(info.get("jobDescription", ""))[:MAX_DESC],
                    "location": " | ".join(l for l in locs if l), "posted_at": parse_date(info.get("startDate")),
                    "deadline": parse_date(info.get("endDate")), "apply_url": info.get("externalUrl")}

    m = re.search(r"linkedin\.com/jobs/view/(?:[^/?]*-)?(\d{6,})", url)
    if m:
        return await linkedin_detail(ctx, m.group(1))

    if meta.get("ats") == "smartrecruiters" and meta.get("api"):
        d = await ctx.get_json(meta["api"])
        secs = (d.get("jobAd") or {}).get("sections") or {}
        txt = "\n\n".join(html_to_text((secs.get(k) or {}).get("text", "")) for k in
                          ("companyDescription", "jobDescription", "qualifications", "additionalInformation"))
        return {"description": txt[:MAX_DESC], "apply_url": d.get("applyUrl")}

    if "ashbyhq.com" in host and len(segs) >= 2:
        cache = ctx.__dict__.setdefault("_ashby_cache", {})
        if segs[0] not in cache:
            cache[segs[0]] = await ctx.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{segs[0]}")
        for j in cache[segs[0]].get("jobs", []):
            if j.get("id") == segs[1]:
                return {"description": (j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")))[:MAX_DESC],
                        "apply_url": j.get("applyUrl")}

    # Generic page: prefer schema.org JobPosting, else visible text.
    fetch_url = url + ("&" if "?" in url else "?") + "in_iframe=1" if host.endswith(".icims.com") else url
    html = await ctx.get_text(fetch_url)
    jp = _jsonld_jobposting(html)
    if jp:
        org = jp.get("hiringOrganization")
        return {"description": html_to_text(jp.get("description", ""))[:MAX_DESC],
                "posted_at": parse_date(jp.get("datePosted")), "deadline": parse_date(jp.get("validThrough")),
                "location": _ld_location(jp), "company": org.get("name") if isinstance(org, dict) else None,
                "title": clean(jp.get("title"))}
    body = re.search(r"<body[^>]*>(.*)</body>", html, re.S | re.I)
    text = html_to_text(body.group(1) if body else html)
    return {"description": text[:MAX_DESC]}
