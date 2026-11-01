"""Community tech internship and new-grad lists on GitHub (SimplifyJobs and its forks).

These repositories keep every listing in one JSON file (.github/scripts/listings.json), served as a plain file by
raw.githubusercontent.com, so no API key is needed. Settings, Sources holds the file addresses. The lists only cover tech
internships and new-grad roles (software, data, hardware, product, quant), so this source skips itself unless the user's
targets are in tech (plan.in_tech) and they search at internship or entry level."""
import re

from jobportal.core.textutil import parse_date
from jobportal.search import plan
from jobportal.search.collectors.base import Ctx, RawJob


async def collect(ctx: Ctx) -> list[RawJob]:
    """Every open listing from each configured list.

    Titles skip the level check (strict_titles=False) because every listing is already an internship or a new-grad role.
    found_url points at the repository, where the user can see the whole list."""
    if not plan.in_tech(ctx.cfg):
        ctx.log("github", "skipped: these lists only carry tech internships and new-grad roles, and your targets aren't in tech")
        return []
    if not set(plan.levels(ctx.cfg)) & {"internship", "entry"}:
        ctx.log("github", "skipped: these lists only cover internships and new-grad roles, which aren't in your levels")
        return []
    out = []
    for url in ctx.cfg["sources"]["github_lists"]["urls"]:
        # ".../githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/..." -> "SimplifyJobs/New-Grad-Positions"
        repo = "/".join(url.split("githubusercontent.com/")[-1].split("/")[:2])
        try:
            data = await ctx.get_json(url, timeout=90)  # the files are large, so allow more than the usual 30 seconds
        except Exception as e:  # noqa: BLE001 (one unreachable list shouldn't stop the others)
            ctx.log("github", f"{repo}: {e}", "warn")
            continue
        newgrad = bool(re.search(r"new-?grad", url, re.I))  # the repository name tells new-grad lists from internship lists
        count = 0
        for item in data if isinstance(data, list) else []:
            if not isinstance(item, dict) or not item.get("active", True) or item.get("is_visible") is False:
                continue  # not a listing, closed, or hidden by the list's maintainers
            terms = item.get("terms") or item.get("season") or ""  # such as "Summer 2027"; some files use a list
            terms = ", ".join(str(t) for t in terms if t) if isinstance(terms, list) else str(terms)
            out.append(RawJob(
                source="github", title=item.get("title", ""), company=item.get("company_name", ""), url=item.get("url", ""),
                locations=item.get("locations") or [],  # RawJob drops empty places, which some listings have
                posted_at=parse_date(item.get("date_posted") or item.get("date_updated")),
                category_hint="new-grad" if newgrad else "internship",
                found_url=f"https://github.com/{repo}",
                source_detail=f"GitHub {repo}" + (f", {terms}" if terms else "") + (f", {item['category']}" if item.get("category") else ""),
                strict_titles=False,
                description=(f"Sponsorship: {item['sponsorship']}" if item.get("sponsorship") else "")))
            count += 1
        ctx.log("github", f"{repo}: {count} active listings")
    return out
