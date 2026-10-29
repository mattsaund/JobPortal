"""The Analysis page: where the user fits, where the market is, and what to build next.

It works in two layers:
1. market() is plain counting over the user's own search data, with no AI call. It measures:
   - demand per work genre: how the postings that passed the user's filters in recent search runs split across genres
     (each run records "genre:<id>" counts in its stats), or how triaged leads split when no run has recorded any yet;
   - per-genre lead quality: how many leads qualified and their average score;
   - skill gaps and strengths: keywords postings asked for that the tailored resumes could or couldn't show (every
     application package records its keyword coverage);
   - the funnel from postings scanned to offers, and which sources and industries produce qualified leads.
2. run_ai() sends those numbers and the full profile to the AI, which scores fit and interest (0 to 100) for every genre and
   suggests concrete moves: projects, certifications, things to add to the profile, and search changes. The result is
   stored as "analysis.latest", and a short history of fit scores ("analysis.history") lets the page show how fit changed.

Genres live in settings (analysis.genres; the defaults are in core/genres.py). The profile runs run_ai() after every build or
update (unless settings profile.auto_analyze is off), and the page has a Re-analyze button. Nothing here changes the profile.
Called by web/routes/insights.py for web/static/js/pages/analysis.js."""
import asyncio
import json
from collections import Counter, defaultdict
from statistics import mean

from jobportal.ai import client as ai, prompts
from jobportal.candidate import profile as profile_mod
from jobportal.core import bus, db, settings as settings_mod
from jobportal.core.genres import classify

# Lead stages that mean triage said yes: qualified, and every stage after it (packaging, ready, a failed package, a closed posting).
QUALIFIED = ("qualified", "packaging", "ready", "closed", "error")
_lock = asyncio.Lock()  # one AI assessment at a time


def _avg(scores: list[int]) -> int | None:
    """The rounded average score, or None when there are no scores."""
    return round(mean(scores)) if scores else None


def lead_genres(lead: dict, genres: list[dict]) -> list[str]:
    """The genre ids of one lead: the ones triage tagged, or keyword matches on the title and description when triage
    tagged none (core/genres.classify)."""
    triage = lead.get("triage")
    triage = json.loads(triage) if isinstance(triage, str) else (triage or {})
    known = {g["id"] for g in genres}
    tagged = [g for g in triage.get("genres") or [] if g in known]
    return tagged or classify(lead.get("title", ""), lead.get("description") or "", genres)


def _recent_demand() -> tuple[Counter, int]:
    """How the postings that passed the filters in the last 6 finished runs split across genres. Returns (counts per genre id,
    how many of those runs recorded genre counts)."""
    counts, runs_used = Counter(), 0
    for run in db.q("SELECT stats FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 6"):
        stats = json.loads(run["stats"] or "{}")
        genre_counts = {k.removeprefix("genre:"): v for k, v in stats.items() if k.startswith("genre:")}
        if genre_counts:
            runs_used += 1
            counts.update(genre_counts)
    return counts, runs_used


def _skill_coverage(leads: list[dict], genres_of: dict[int, list[str]]) -> dict:
    """The keywords postings asked for, split by whether the tailored resume could show them. Every package records
    {"hit": [...], "miss": [...]} as its coverage. Trashed leads don't count.

    Returns gaps (the most often missed keywords), strengths (often requested and never missed), packaged (how many leads
    the numbers come from) and missed_by_genre (a Counter of missed keywords per genre id)."""
    requested, missed, label, missed_by_genre, packaged = Counter(), Counter(), {}, defaultdict(Counter), 0
    for lead in leads:
        if lead["app_status"] == "trashed":
            continue
        coverage = json.loads(lead["package"] or "{}").get("coverage") or {}
        if not coverage:
            continue
        packaged += 1
        for keyword in (coverage.get("hit") or []) + (coverage.get("miss") or []):
            key = keyword.lower().strip()
            label.setdefault(key, keyword.strip())  # the first spelling seen is the one shown
            requested[key] += 1
        for keyword in coverage.get("miss") or []:
            key = keyword.lower().strip()
            missed[key] += 1
            for genre in genres_of.get(lead["id"], []):
                missed_by_genre[genre][label[key]] += 1
    return {"gaps": [{"skill": label[k], "missing_in": n, "requested_in": requested[k]} for k, n in missed.most_common(18)],
            "strengths": [{"skill": label[k], "requested_in": n} for k, n in requested.most_common(60) if missed[k] == 0][:14],
            "packaged": packaged, "missed_by_genre": missed_by_genre}


def _funnel(leads: list[dict]) -> list[dict]:
    """How many jobs reached each step, from postings scanned (across every run) to offers."""
    scanned = Counter()
    for run in db.q("SELECT stats FROM runs"):
        stats = json.loads(run["stats"] or "{}")
        scanned.update({k: stats.get(k, 0) for k in ("found", "candidates")})
    statuses = Counter(lead["app_status"] for lead in leads)
    return [
        {"stage": "Postings scanned", "n": scanned["found"]},
        {"stage": "Passed your filters", "n": scanned["candidates"]},
        {"stage": "AI-triaged", "n": len(leads)},
        {"stage": "Qualified", "n": sum(1 for lead in leads if lead["stage"] in QUALIFIED)},
        {"stage": "Package ready", "n": sum(1 for lead in leads if lead["has_resume"])},
        {"stage": "Applied", "n": sum(1 for lead in leads if lead["applied_at"] is not None)},
        {"stage": "Responses", "n": sum(statuses[s] for s in ("assessment", "interviewing", "offer", "rejected"))},
        {"stage": "Interviews", "n": statuses["interviewing"] + statuses["offer"]},
        {"stage": "Offers", "n": statuses["offer"]},
    ]


def _quality(leads: list[dict], column: str, missing: str) -> list[dict]:
    """How many leads from each value of one column (source or industry) were triaged and qualified, and their average
    score. Rows are named by the column, missing values count as missing, and the most qualified come first."""
    groups = defaultdict(lambda: {"triaged": 0, "qualified": 0, "scores": []})
    for lead in leads:
        group = groups[lead[column] or missing]
        group["triaged"] += 1
        if lead["stage"] in QUALIFIED:
            group["qualified"] += 1
            group["scores"].append(lead["score"] or 0)
    rows = [{column: k, "triaged": g["triaged"], "qualified": g["qualified"], "avg_score": _avg(g["scores"])} for k, g in groups.items()]
    return sorted(rows, key=lambda row: -row["qualified"])


def market(cfg: dict | None = None) -> dict:
    """The numbers behind the Analysis page, counted from the user's own leads and search runs (no AI call). See the module
    docstring for what each part means."""
    cfg = cfg or settings_mod.get()
    genres = cfg["analysis"]["genres"]
    leads = db.q("SELECT id, title, description, score, stage, app_status, source, triage, package, applied_at, industry, "
                 "resume_md IS NOT NULL AS has_resume FROM leads")
    genres_of = {lead["id"]: lead_genres(lead, genres) for lead in leads}

    demand, runs_used = _recent_demand()
    if runs_used:
        demand_source = f"{runs_used} recent run{'s' if runs_used != 1 else ''}"
    else:
        demand = Counter(g for ids in genres_of.values() for g in ids)
        demand_source = "triaged leads (run a search to measure the full market)"
    total, busiest = sum(demand.values()) or 1, max(demand.values(), default=0) or 1

    qualified, scores = Counter(), defaultdict(list)
    for lead in leads:
        if lead["stage"] in QUALIFIED:
            for genre in genres_of[lead["id"]]:
                qualified[genre] += 1
                scores[genre].append(lead["score"] or 0)
    skills = _skill_coverage(leads, genres_of)
    genre_rows = [{"id": g["id"], "label": g["label"], "demand_count": demand[g["id"]],
                   "demand_share": round(demand[g["id"]] / total, 4),
                   "demand_index": round(100 * demand[g["id"]] / busiest),  # the busiest genre is 100
                   "qualified": qualified[g["id"]], "avg_score": _avg(scores[g["id"]]),
                   "top_missing": [k for k, _ in skills["missed_by_genre"][g["id"]].most_common(5)]} for g in genres]
    return {"genres": genre_rows, "industries": _quality(leads, "industry", "Other"), "demand_source": demand_source,
            "demand_total": sum(demand.values()), "gaps": skills["gaps"], "strengths": skills["strengths"],
            "packaged_leads": skills["packaged"], "funnel": _funnel(leads), "sources": _quality(leads, "source", "other")}


def get() -> dict:
    """Everything the Analysis page shows: the market numbers, the latest AI assessment, the fit history, whether an
    assessment is running now, and the genres."""
    cfg = settings_mod.get()
    return {"market": market(cfg), "latest": db.kv_get("analysis.latest"), "history": db.kv_get("analysis.history") or [],
            "running": _lock.locked(), "genres": cfg["analysis"]["genres"]}


def _prompt(genres: list[dict], numbers: dict) -> str:
    """The assessment prompt: the genres, the market numbers, the skill gaps, the full profile and the search plan."""
    market_lines = "\n".join(
        f"- {g['id']} ({g['label']}): demand {g['demand_share'] * 100:.1f}% of {numbers['demand_total']} filtered postings; "
        f"{g['qualified']} qualified leads; avg lead score {g['avg_score'] if g['avg_score'] is not None else 'n/a'}; "
        f"missing skills seen: {', '.join(g['top_missing']) or 'n/a'}" for g in numbers["genres"])
    gaps = ", ".join(f"{x['skill']} (missing in {x['missing_in']}/{x['requested_in']})" for x in numbers["gaps"]) or "not enough packaged leads yet"
    genre_list = "\n".join(f"- {g['id']}: {g['label']}" for g in genres)
    return f"""GENRES (assess every one, using these ids):
{genre_list}

MARKET DATA (demand measured from {numbers['demand_source']}):
{market_lines}

MOST-REQUESTED SKILLS THE TAILORED RESUMES COULDN'T SHOW: {gaps}

=== CANDIDATE PROFILE ===
{profile_mod.full_context()}

=== SEARCH PLAN ===
{json.dumps(profile_mod.get('search_plan'), indent=1)}"""


def _clamp(score) -> int:
    """A score held to the 0..100 range."""
    return max(0, min(100, int(score)))


async def run_ai(reason: str = "manual") -> dict:
    """Ask the AI to score fit and interest for every genre and suggest moves (one AI call), and store the result.

    Publishes "analysis" events so the page shows the progress, then a toast with the summary. Returns
    {"ok": True, ...the stored result}, or ok=False when an assessment is already running. On failure it shows an error
    toast and raises."""
    if _lock.locked():
        return {"ok": False, "message": "Analysis already running."}
    async with _lock:
        bus.publish("analysis", {"running": True})
        try:
            cfg = settings_mod.get()
            genres = cfg["analysis"]["genres"]
            numbers = market(cfg)
            out = await ai.run(_prompt(genres, numbers), system=prompts.system("analysis", prompts.ANALYSIS_SYSTEM),
                               schema=prompts.ANALYSIS_SCHEMA, stage="analysis", purpose="analysis", label="analysis: fit radar",
                               timeout=1200)
            known = {g["id"] for g in genres}
            # Keep only genres that exist, with scores held to 0..100, so a stray answer can't break the radar chart.
            out["genres"] = [{**g, "fit": _clamp(g["fit"]), "interest": _clamp(g["interest"])}
                             for g in out.get("genres", []) if g.get("id") in known]
            tokens = out.pop("_tokens", 0)
            out.pop("_tools", None)
            latest = {"ts": db.now(), "reason": reason, "result": out, "tokens": tokens,
                      "demand": {g["id"]: g["demand_index"] for g in numbers["genres"]}}
            db.kv_set("analysis.latest", latest)
            fit_history = db.kv_get("analysis.history") or []
            fit_history.append({"ts": latest["ts"], "fit": {g["id"]: g["fit"] for g in out["genres"]},
                                "interest": {g["id"]: g["interest"] for g in out["genres"]}})
            db.kv_set("analysis.history", fit_history[-40:])
            bus.publish("analysis", {"running": False, "ts": latest["ts"]})
            bus.publish("toast", {"title": "Analysis updated", "body": (out.get("summary") or "")[:160]})
            return {"ok": True, **latest}
        except Exception as e:
            bus.publish("analysis", {"running": False, "error": str(e)[:300]})
            bus.publish("toast", {"title": "Analysis failed", "body": str(e)[:300], "level": "error"})
            raise
