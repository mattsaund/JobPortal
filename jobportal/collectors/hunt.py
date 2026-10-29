"""AI hunt missions: Claude agents with WebSearch/WebFetch that dig for leads no API exposes."""
import asyncio
from datetime import date

from .. import claude, db, prompts
from .. import profile as profile_mod
from .. import settings as settings_mod
from ..textutil import parse_date
from .base import Ctx, RawJob


def _known_leads(limit: int = 120) -> str:
    rows = db.q("SELECT company, title FROM leads WHERE stage NOT IN ('filtered') ORDER BY id DESC LIMIT ?", (limit,))
    return "\n".join(f"- {r['company']}: {r['title']}" for r in rows) or "(none yet)"


async def run_mission(ctx: Ctx, m: dict) -> list[RawJob]:
    cfg = ctx.cfg
    locs = ", ".join(cfg["locations"]["allowed"])
    bypass = (" (dream companies may be anywhere in the US: " + ", ".join(settings_mod.all_dreams(cfg)[:24]) + ")"
              if cfg["locations"].get("dream_bypass") else "")
    system = prompts.system("hunt", prompts.HUNT_SYSTEM).replace("{today}", date.today().isoformat()) \
        .replace("{locations}", locs).replace("{bypass}", bypass) \
        .replace("{budget}", prompts.HUNT_DEPTH.get(cfg["sources"]["ai_hunt"].get("depth", "standard"), prompts.HUNT_DEPTH["standard"]))
    dreams = settings_mod.all_dreams(cfg)
    system += "\n\n" + profile_mod.digest() + f"\n\nDREAM COMPANIES: {'; '.join(dreams) or 'none named'}"
    prompt = f"""MISSION: {m['name']}

{m['prompt']}

ALREADY KNOWN LEADS (skip unless you found something new):
{_known_leads()}"""
    try:
        out = await claude.run(prompt, system=system, schema=prompts.HUNT_SCHEMA, stage="hunt",
                               purpose=f"hunt:{m['id']}", tools=["WebSearch", "WebFetch"], run_id=ctx.run_id,
                               label=f"hunt: {m['name']}", timeout=1800)
    except claude.UsageLimitError:
        raise
    except claude.ClaudeError as e:
        ctx.log("hunt", f"{m['name']}: {e}", "warn")
        return []
    jobs = []
    for l in out.get("leads", []):
        if not l.get("url") or not l.get("title"):
            continue
        desc = "\n\n".join(x for x in [l.get("description", ""), f"Why it matches: {l.get('why_match', '')}",
                                       f"Evidence: {l.get('evidence', '')}"] if x)
        jobs.append(RawJob(source="ai_hunt", title=l["title"], company=l.get("company", ""), url=l["url"],
                           location=l.get("location", ""), description=desc, kind=l.get("kind", "posting"),
                           category_hint=l.get("category", ""), posted_at=parse_date(l.get("posted_date")),
                           deadline=parse_date(l.get("deadline")) or (l.get("deadline") or None),
                           source_detail=f"AI hunt ({m['name']}): {l.get('where_found', '')}"[:300], strict_titles=False,
                           found_url=l.get("found_url") if str(l.get("found_url", "")).startswith("http") else l["url"]))
    t = out.get("_tools", {})
    ctx.log("hunt", f"{m['name']}: {len(jobs)} leads from {t.get('WebSearch', 0)} searches / {t.get('WebFetch', 0)} pages read (≈${out.get('_cost_usd', 0):.2f})")
    return jobs


def pick_missions(cfg: dict, everything: bool) -> list[dict]:
    """All enabled missions, or (for 'Everything' runs with a per-run limit) the next slice of a rotation, so every mission
    still runs every few searches without blowing through a 5-hour usage window. Missions marked only_levels (campus pipelines,
    for example) are skipped unless you search at one of those levels."""
    levels = set(settings_mod.levels(cfg))
    missions = [m for m in cfg["sources"]["ai_hunt"]["missions"]
                if m.get("enabled", True) and (not m.get("only_levels") or levels & set(m["only_levels"]))]
    if not missions:
        return []
    n = int(cfg["sources"]["ai_hunt"].get("missions_per_run") or 0)
    if everything or n <= 0 or n >= len(missions):
        return missions
    start = int(db.kv_get("hunt.rotation") or 0) % len(missions)
    db.kv_set("hunt.rotation", (start + n) % len(missions))
    return [missions[(start + i) % len(missions)] for i in range(n)]


async def collect(ctx: Ctx, on_batch=None, everything: bool = True) -> list[RawJob]:
    missions = pick_missions(ctx.cfg, everything)
    ctx.log("hunt", f"{len(missions)} AI missions this run: {', '.join(m['name'] for m in missions)}")
    results = []

    async def go(m):
        jobs = await run_mission(ctx, m)
        if on_batch and jobs:
            await on_batch(f"AI hunt: {m['name']}", jobs)
        results.extend(jobs)

    await asyncio.gather(*(go(m) for m in missions))
    return results
