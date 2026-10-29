"""Community-maintained internship / new-grad lists on GitHub (SimplifyJobs, vanshb03, …)."""
import re

from .. import settings as settings_mod
from ..levels import EARLY
from ..textutil import parse_date
from .base import Ctx, RawJob


async def collect(ctx: Ctx) -> list[RawJob]:
    if not set(settings_mod.levels(ctx.cfg)) & EARLY:
        ctx.log("github", "skipped: these lists only cover internships and new-grad roles, which aren't in your levels")
        return []
    out = []
    for url in ctx.cfg["sources"]["github_lists"]["urls"]:
        repo = "/".join(url.split("githubusercontent.com/")[-1].split("/")[:2])
        try:
            data = await ctx.get_json(url, timeout=90)
        except Exception as e:  # noqa: BLE001
            ctx.log("github", f"{repo}: {e}", "warn")
            continue
        newgrad = bool(re.search(r"new-?grad", url, re.I))
        n = 0
        for x in data if isinstance(data, list) else []:
            if not x.get("active", True) or x.get("is_visible") is False:
                continue
            terms = x.get("terms") or x.get("season") or ""
            terms = ", ".join(terms) if isinstance(terms, list) else str(terms)
            locs = x.get("locations") or []
            out.append(RawJob(
                source="github", title=x.get("title", ""), company=x.get("company_name", ""), url=x.get("url", ""),
                locations=locs, location=" | ".join(locs),
                posted_at=parse_date(x.get("date_posted") or x.get("date_updated")),
                category_hint="new-grad" if newgrad else "internship",
                found_url=f"https://github.com/{repo}",
                source_detail=f"GitHub {repo}" + (f", {terms}" if terms else "") + (f", {x['category']}" if x.get("category") else ""),
                strict_titles=False,
                description=(f"Sponsorship: {x['sponsorship']}" if x.get("sponsorship") else "")))
            n += 1
        ctx.log("github", f"{repo}: {n} active listings")
    return out
