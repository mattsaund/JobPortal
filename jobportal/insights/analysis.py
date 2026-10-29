"""Analysis tab: market demand per work genre (from real search runs), skill gaps mined from tailored packages,
pipeline funnel and source quality, plus an AI assessment of fit and interest per genre with concrete moves."""
import asyncio
import json
from collections import Counter, defaultdict
from statistics import mean

from jobportal.ai import client as ai, prompts
from jobportal.candidate import profile as profile_mod
from jobportal.core import bus, db, settings as settings_mod
from jobportal.core.genres import classify

QUALIFIED = ("qualified", "packaging", "ready", "closed", "error")
_lock = asyncio.Lock()


def _genres(cfg: dict) -> list[dict]:
    return cfg["analysis"]["genres"]


def lead_genres(lead: dict, gs: list[dict]) -> list[str]:
    tri = lead.get("triage")
    tri = json.loads(tri) if isinstance(tri, str) else (tri or {})
    ids = {g["id"] for g in gs}
    tagged = [g for g in tri.get("genres") or [] if g in ids]
    return tagged or classify(lead.get("title", ""), lead.get("description") or "", gs)


def market(cfg: dict | None = None) -> dict:
    cfg = cfg or settings_mod.get()
    gs = _genres(cfg)
    ids = [g["id"] for g in gs]
    leads = db.q("SELECT id, title, description, score, stage, app_status, source, triage, package, applied_at, industry FROM leads")

    # Demand: genre mix of every candidate that passed your filters, over the last few runs that recorded it.
    counts, runs_used = Counter(), 0
    for r in db.q("SELECT stats FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 6"):
        st = json.loads(r["stats"] or "{}")
        g = {k[6:]: v for k, v in st.items() if k.startswith("genre:")}
        if g:
            runs_used += 1
            counts.update(g)
    demand_source = f"{runs_used} recent run{'s' if runs_used != 1 else ''}" if runs_used else "triaged leads (run a search to measure the full market)"
    per = {gid: {"leads": 0, "qualified": 0, "scores": [], "applied": 0} for gid in ids}
    lead_gs = {}
    for l in leads:
        lg = lead_genres(l, gs)
        lead_gs[l["id"]] = lg
        for g in lg:
            if g not in per:
                continue
            per[g]["leads"] += 1
            if l["stage"] in QUALIFIED:
                per[g]["qualified"] += 1
                per[g]["scores"].append(l["score"] or 0)
            if l["applied_at"]:
                per[g]["applied"] += 1
    if not runs_used:
        counts = Counter(g for lg in lead_gs.values() for g in lg)
    total, top = sum(counts.values()) or 1, max(counts.values() or [1])

    # Skill gaps: job keywords your tailored resumes covered vs missed, across every packaged lead.
    req, miss, label, miss_by_genre = Counter(), Counter(), {}, defaultdict(Counter)
    for l in leads:
        if l["app_status"] == "trashed":
            continue
        cov = (json.loads(l["package"] or "{}").get("coverage") or {})
        for k in (cov.get("hit") or []) + (cov.get("miss") or []):
            key = k.lower().strip()
            label.setdefault(key, k.strip())
            req[key] += 1
        for k in cov.get("miss") or []:
            key = k.lower().strip()
            miss[key] += 1
            for g in lead_gs.get(l["id"], []):
                miss_by_genre[g][label[key]] += 1
    packaged = sum(1 for l in leads if (json.loads(l["package"] or "{}").get("coverage")))
    gaps = [{"skill": label[k], "missing_in": n, "requested_in": req[k]} for k, n in miss.most_common(18)]
    strengths = [{"skill": label[k], "requested_in": n} for k, n in req.most_common(60) if miss[k] == 0][:14]

    genres_out = []
    for g in gs:
        p = per[g["id"]]
        genres_out.append({"id": g["id"], "label": g["label"], "demand_count": counts[g["id"]],
                           "demand_share": round(counts[g["id"]] / total, 4), "demand_index": round(100 * counts[g["id"]] / top),
                           "leads": p["leads"], "qualified": p["qualified"], "applied": p["applied"],
                           "avg_score": round(mean(p["scores"])) if p["scores"] else None,
                           "top_missing": [k for k, _ in miss_by_genre[g["id"]].most_common(5)]})

    run_tot = Counter()
    for r in db.q("SELECT stats FROM runs"):
        st = json.loads(r["stats"] or "{}")
        run_tot.update({k: st.get(k, 0) for k in ("found", "candidates")})
    c = lambda sql: db.one(sql)["n"]  # noqa: E731
    funnel = [
        {"stage": "Postings scanned", "n": run_tot["found"]},
        {"stage": "Passed your filters", "n": run_tot["candidates"]},
        {"stage": "AI-triaged", "n": len(leads)},
        {"stage": "Qualified", "n": sum(1 for l in leads if l["stage"] in QUALIFIED)},
        {"stage": "Package ready", "n": c("SELECT COUNT(*) n FROM leads WHERE resume_md IS NOT NULL")},
        {"stage": "Applied", "n": c("SELECT COUNT(*) n FROM leads WHERE applied_at IS NOT NULL")},
        {"stage": "Responses", "n": c("SELECT COUNT(*) n FROM leads WHERE app_status IN ('assessment','interviewing','offer','rejected')")},
        {"stage": "Interviews", "n": c("SELECT COUNT(*) n FROM leads WHERE app_status IN ('interviewing','offer')")},
        {"stage": "Offers", "n": c("SELECT COUNT(*) n FROM leads WHERE app_status='offer'")},
    ]
    src = defaultdict(lambda: {"triaged": 0, "qualified": 0, "scores": []})
    for l in leads:
        s = src[l["source"] or "other"]
        s["triaged"] += 1
        if l["stage"] in QUALIFIED:
            s["qualified"] += 1
            s["scores"].append(l["score"] or 0)
    sources = sorted(({"source": k, "triaged": v["triaged"], "qualified": v["qualified"],
                       "avg_score": round(mean(v["scores"])) if v["scores"] else None} for k, v in src.items()),
                     key=lambda x: -x["qualified"])
    ind = defaultdict(lambda: {"triaged": 0, "qualified": 0, "scores": []})
    for l in leads:
        x = ind[l["industry"] or "Other"]
        x["triaged"] += 1
        if l["stage"] in QUALIFIED:
            x["qualified"] += 1
            x["scores"].append(l["score"] or 0)
    industries = sorted(({"industry": k, "triaged": v["triaged"], "qualified": v["qualified"],
                          "avg_score": round(mean(v["scores"])) if v["scores"] else None} for k, v in ind.items()), key=lambda x: -x["qualified"])
    return {"genres": genres_out, "industries": industries, "demand_source": demand_source, "demand_total": sum(counts.values()),
            "gaps": gaps, "strengths": strengths, "packaged_leads": packaged, "funnel": funnel, "sources": sources}


def get() -> dict:
    cfg = settings_mod.get()
    return {"market": market(cfg), "latest": db.kv_get("analysis.latest"), "history": db.kv_get("analysis.history") or [],
            "running": _lock.locked(), "genres": _genres(cfg)}


async def run_ai(reason: str = "manual") -> dict:
    if _lock.locked():
        return {"ok": False, "message": "Analysis already running."}
    async with _lock:
        bus.publish("analysis", {"running": True})
        try:
            cfg = settings_mod.get()
            gs = _genres(cfg)
            m = market(cfg)
            market_txt = "\n".join(
                f"- {g['id']} ({g['label']}): demand {g['demand_share'] * 100:.1f}% of {m['demand_total']} filtered postings; "
                f"{g['qualified']} qualified leads; avg lead score {g['avg_score'] if g['avg_score'] is not None else 'n/a'}; "
                f"missing skills seen: {', '.join(g['top_missing']) or 'n/a'}" for g in m["genres"])
            gaps_txt = ", ".join(f"{x['skill']} (missing in {x['missing_in']}/{x['requested_in']})" for x in m["gaps"]) or "not enough packaged leads yet"
            prompt = f"""GENRES (assess every one, using these ids):
{chr(10).join(f"- {g['id']}: {g['label']}" for g in gs)}

MARKET DATA (demand measured from {m['demand_source']}):
{market_txt}

MOST-REQUESTED SKILLS THE TAILORED RESUMES COULDN'T SHOW: {gaps_txt}

=== CANDIDATE PROFILE ===
{profile_mod.full_context()}

=== SEARCH PLAN ===
{json.dumps(profile_mod.get('search_plan'), indent=1)}"""
            out = await ai.run(prompt, system=prompts.system("analysis", prompts.ANALYSIS_SYSTEM), schema=prompts.ANALYSIS_SCHEMA,
                                   stage="analysis", purpose="analysis", label="analysis: fit radar", timeout=1200)
            ids = {g["id"] for g in gs}
            out["genres"] = [{**g, "fit": max(0, min(100, int(g["fit"]))), "interest": max(0, min(100, int(g["interest"])))}
                             for g in out.get("genres", []) if g.get("id") in ids]
            tokens = out.pop("_tokens", 0)
            out.pop("_tools", None)
            latest = {"ts": db.now(), "reason": reason, "result": out, "tokens": tokens,
                      "demand": {g["id"]: g["demand_index"] for g in m["genres"]}}
            db.kv_set("analysis.latest", latest)
            hist = db.kv_get("analysis.history") or []
            hist.append({"ts": latest["ts"], "fit": {g["id"]: g["fit"] for g in out["genres"]},
                         "interest": {g["id"]: g["interest"] for g in out["genres"]}})
            db.kv_set("analysis.history", hist[-40:])
            bus.publish("analysis", {"running": False, "ts": latest["ts"]})
            bus.publish("toast", {"title": "Analysis updated", "body": (out.get("summary") or "")[:160]})
            return {"ok": True, **latest}
        except Exception as e:
            bus.publish("analysis", {"running": False, "error": str(e)[:300]})
            bus.publish("toast", {"title": "Analysis failed", "body": str(e)[:300], "level": "error"})
            raise
