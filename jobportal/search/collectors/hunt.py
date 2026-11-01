"""The AI hunt: web-search agents that dig for leads no job board API exposes, such as comment-thread mentions, recruiter
posts, unadvertised programs and hiring signals.

Each mission (the Sources dialog, AI hunt; the defaults are prompts.DEFAULT_MISSIONS) is one AI agent with web search
and page reading (ai.run with web=True). It gets the candidate's profile digest, the allowed locations, the dream
companies and the leads JobPortal already knows, and returns leads with evidence (prompts.HUNT_SCHEMA). The search run
(pipeline.py) starts collect(), which runs the missions at the same time and hands each mission's leads over as soon as
it finishes, so triage can start before the slowest mission is done.

Keeping usage in check: an "Everything" run only runs missions_per_run missions, rotating through the list so each one
still runs every few searches (pick_missions). "AI hunt only" runs them all. The depth setting ("How deep": quick,
standard, deep) sets how many searches and page reads each agent may use.

Side effects: AI calls on the user's ChatGPT plan, and the rotation position saved in the kv table (hunt.rotation)."""
import asyncio
from datetime import date

from jobportal.ai import client as ai, prompts
from jobportal.candidate import profile as profile_mod
from jobportal.core import db
from jobportal.core.textutil import parse_date
from jobportal.search import plan
from jobportal.search.collectors.base import Ctx, RawJob


def _known_leads(limit: int = 120) -> str:
    """The newest leads (not counting below-threshold ones) as "- Company: Title" lines, so agents skip what we already have."""
    rows = db.q("SELECT company, title FROM leads WHERE stage NOT IN ('filtered') ORDER BY id DESC LIMIT ?", (limit,))
    return "\n".join(f"- {r['company']}: {r['title']}" for r in rows) or "(none yet)"


def _system_prompt(cfg: dict) -> str:
    """The hunt agent's instructions: the hunt prompt (Settings can override it) with today's date, the search area, the dream
    company exception and the search budget filled in, then the profile digest and the dream companies."""
    depth = cfg["sources"]["ai_hunt"].get("depth", "standard")
    dreams = plan.all_dreams(cfg)
    # With the dream bypass on, the agent may also report dream companies outside the allowed locations.
    bypass = f" (dream companies may be anywhere in the US: {', '.join(dreams[:24])})" if cfg["locations"].get("dream_bypass") else ""
    # str.replace rather than str.format: Settings can swap in the user's own prompt text, and a stray brace in it would make
    # str.format fail.
    system = (prompts.system("hunt", prompts.HUNT_SYSTEM)
              .replace("{today}", date.today().isoformat())
              .replace("{locations}", ", ".join(cfg["locations"]["allowed"]))
              .replace("{bypass}", bypass)
              .replace("{budget}", prompts.HUNT_DEPTH.get(depth, prompts.HUNT_DEPTH["standard"])))
    return system + "\n\n" + profile_mod.digest() + f"\n\nDREAM COMPANIES: {'; '.join(dreams) or 'none named'}"


async def run_mission(ctx: Ctx, mission: dict) -> list[RawJob]:
    """Run one hunt mission and return its leads as RawJobs (source "ai_hunt").

    Leads without a URL or a title are dropped. Titles skip the level check (strict_titles=False): the agent was told the
    candidate's levels and its titles are free text. found_url is the post or page where the agent found the lead, or the
    lead's own URL. Raises ai.UsageLimitError when the ChatGPT usage cap is hit; any other AI failure is logged and the
    mission returns nothing."""
    depth = ctx.cfg["sources"]["ai_hunt"].get("depth", "standard")
    prompt = f"""MISSION: {mission['name']}

{mission['prompt']}

ALREADY KNOWN LEADS (skip unless you found something new):
{_known_leads()}"""
    try:
        out = await ai.run(prompt, system=_system_prompt(ctx.cfg), schema=prompts.HUNT_SCHEMA, stage="hunt", web=True,
                           max_steps=prompts.HUNT_STEPS.get(depth, 30), purpose=f"hunt:{mission['id']}", run_id=ctx.run_id,
                           label=f"hunt: {mission['name']}", timeout=1800)
    except ai.UsageLimitError:
        raise  # the search run pauses itself on this one
    except ai.AIError as e:
        ctx.log("hunt", f"{mission['name']}: {e}", "warn")
        return []
    jobs = []
    for lead in out.get("leads", []):
        if not lead.get("url") or not lead.get("title"):
            continue
        description = "\n\n".join(x for x in [lead.get("description", ""), f"Why it matches: {lead.get('why_match', '')}",
                                              f"Evidence: {lead.get('evidence', '')}"] if x)
        found_url = lead.get("found_url") if str(lead.get("found_url", "")).startswith("http") else lead["url"]
        jobs.append(RawJob(source="ai_hunt", title=lead["title"], company=lead.get("company", ""), url=lead["url"],
                           location=lead.get("location", ""), description=description, kind=lead.get("kind", "posting"),
                           category_hint=lead.get("category", ""), posted_at=parse_date(lead.get("posted_date")),
                           # Keep the agent's own words ("rolling") when the deadline isn't a date.
                           deadline=parse_date(lead.get("deadline")) or (lead.get("deadline") or None),
                           source_detail=f"AI hunt ({mission['name']}): {lead.get('where_found', '')}"[:300], strict_titles=False,
                           found_url=found_url))
    tools = out.get("_tools", {})
    ctx.log("hunt", f"{mission['name']}: {len(jobs)} leads from {tools.get('searches', 0)} searches and {tools.get('pages', 0)} pages read "
                    f"({out.get('_tokens', 0):,} tokens)")
    return jobs


def pick_missions(cfg: dict, all_missions: bool) -> list[dict]:
    """The missions to run this time.

    Only enabled missions count. A mission with only_levels (a campus pipeline, for example) only counts when the user
    searches at one of those levels, and one with only_groups (research labs) only when one of the user's field groups
    (plan.groups, such as "science" or "healthcare") is in it, or while their fields aren't known yet. With all_missions
    (an "AI hunt only" run), or when missions_per_run is 0 or covers them all, every one runs. Otherwise the next
    missions_per_run in a rotation run, so every mission still runs every few searches without using up the ChatGPT plan's
    usage window. Side effect: saves the rotation position (kv hunt.rotation)."""
    levels = set(plan.levels(cfg))
    groups = set(plan.groups(cfg))
    missions = [m for m in cfg["sources"]["ai_hunt"]["missions"]
                if m.get("enabled", True) and (not m.get("only_levels") or levels & set(m["only_levels"]))
                and (not m.get("only_groups") or not groups or groups & set(m["only_groups"]))]
    if not missions:
        return []
    per_run = int(cfg["sources"]["ai_hunt"].get("missions_per_run") or 0)
    if all_missions or per_run <= 0 or per_run >= len(missions):
        return missions
    start = int(db.kv_get("hunt.rotation") or 0) % len(missions)
    db.kv_set("hunt.rotation", (start + per_run) % len(missions))
    return [missions[(start + i) % len(missions)] for i in range(per_run)]


async def collect(ctx: Ctx, on_batch=None, all_missions: bool = True) -> list[RawJob]:
    """Run this time's missions at the same time and return all their leads.

    on_batch(label, jobs) is awaited with each mission's leads as soon as that mission finishes; the search run passes its
    add_jobs here. all_missions is passed to pick_missions."""
    missions = pick_missions(ctx.cfg, all_missions)
    ctx.log("hunt", f"{len(missions)} AI missions this run: {', '.join(m['name'] for m in missions)}")
    results = []

    async def run_one(mission: dict) -> None:
        """Run one mission and hand its leads over the moment it finishes."""
        jobs = await run_mission(ctx, mission)
        if on_batch and jobs:
            await on_batch(f"AI hunt: {mission['name']}", jobs)
        results.extend(jobs)

    await asyncio.gather(*(run_one(m) for m in missions))
    return results
