"""The search run: collectors, then rule filters and dedupe, then AI triage, then AI application packages, all streamed live to
the dashboard."""
import asyncio
import json
import re
from collections import Counter
from datetime import date, timedelta

from . import ai, bus, db, prompts, render
from .genres import DEFAULT_INDUSTRIES, classify, classify_industry
from . import profile as profile_mod
from . import settings as settings_mod
from .collectors import COLLECTORS, details, hunt
from .collectors.base import Ctx, RawJob
from .config import LEADS_DIR
from .textutil import LocationMatcher, age_days, coverage, extract_terms, fingerprint, url_key

LIST_FIELDS = ("id, title, company, location, kind, category, source, sources, source_detail, posted_at, deadline, score, "
               "verdict, stage, stage_error, app_status, dream, ats_coverage, url, apply_url, created_at, updated_at, "
               "follow_up_at, applied_at, tokens, triage, found, industry, (COALESCE(resume_md, '') != '') AS has_resume")
NO_TECH_GATE = {"ai_hunt", "hackernews", "mastodon", "reddit", "rss", "manual", "bluesky"}
_current: "Pipeline | None" = None


def skill_regex() -> "re.Pattern | None":
    """Regex of the candidate's strong and working skills, for skill-match pre-scoring."""
    terms = []
    for x in profile_mod.get("skills_inventory") or []:
        if x.get("level") not in ("strong", "working"):
            continue
        for t in re.split(r"\s*/\s*|\s*\(|\)", x["skill"]):
            t = t.strip()
            if 2 <= len(t) <= 40 and t.lower() not in ("c", "go", "r"):
                terms.append(re.escape(t))
    terms += [r"\bC\+\+", r"(?<![\w+#])C(?![\w+#])"]
    return re.compile("|".join(sorted(set(terms), key=len, reverse=True)), re.I) if terms else None


def triage_system(cfg: dict) -> str:
    genre_list = "; ".join(f"{g['id']} = {g['label']}" for g in cfg["analysis"]["genres"])
    industries = "; ".join(cfg.get("industries") or DEFAULT_INDUSTRIES)
    return (prompts.system("triage", prompts.TRIAGE_SYSTEM) + "\n\n" + profile_mod.digest()
            + f"\n\nALLOWED LOCATIONS: {', '.join(cfg['locations']['allowed'])}\nTODAY: {date.today().isoformat()}"
            + f"\nGENRES: {genre_list}\nINDUSTRIES: {industries}")


_retriage_lock = asyncio.Lock()


async def retriage_leads(reason: str = "profile changed", stages: tuple = ("filtered", "qualified")) -> dict:
    """Re-score leads that are below the threshold (or still waiting for a package) against the CURRENT profile:
    a new answer (a skill, a project, a certification) can flip an earlier 'no'."""
    if _retriage_lock.locked():
        return {"ok": False, "message": "Re-evaluation already running."}
    async with _retriage_lock:
        cfg = settings_mod.get()
        rows = [db.lead_row(r) for r in db.q(
            f"SELECT * FROM leads WHERE stage IN ({','.join('?' * len(stages))}) AND app_status!='trashed' AND resume_md IS NULL",
            stages)]
        if not rows:
            return {"ok": True, "checked": 0, "promoted": 0, "demoted": 0}
        min_score = int(cfg["run"].get("min_score", 60))
        system = triage_system(cfg)
        promoted, demoted, checked = [], [], 0
        bus.publish("toast", {"title": "Re-evaluating leads", "body": f"{len(rows)} below-threshold and queued leads against your updated profile ({reason})."})
        for i in range(0, len(rows), 20):
            batch = rows[i:i + 20]
            items = [{"id": str(k), "title": l["title"], "company": l["company"], "location": l["location"], "kind": l["kind"],
                      "source": l.get("source_detail") or l["source"], "posted": l.get("posted_at"), "deadline": l.get("deadline"),

                      "description": (l.get("description") or "(no description available)")[:2200]} for k, l in enumerate(batch)]
            try:
                out = await ai.run(json.dumps(items, indent=1), system=system, schema=prompts.TRIAGE_SCHEMA, stage="triage",
                                       purpose="retriage", label=f"re-evaluate ×{len(batch)}", timeout=600)
            except ai.AIError as e:
                bus.publish("toast", {"title": "Re-evaluation stopped", "body": str(e)[:200], "level": "error"})
                break
            by_id = {r["id"]: r for r in out.get("results", [])}
            for k, l in enumerate(batch):
                r = by_id.get(str(k))
                if not r:
                    continue
                checked += 1
                ok = r["score"] >= min_score and r["eligibility"] != "ineligible" and r["verdict"] != "no"
                new_stage = "qualified" if ok else "filtered"
                tri = {**(l.get("triage") or {}), **{k2: r.get(k2) for k2 in ("summary", "reasons", "red_flags", "eligibility", "score")},
                       "rescored_at": db.now(), "previous_score": l.get("score")}
                db.update_lead(l["id"], score=r["score"], verdict=r["verdict"], triage=tri, stage=new_stage)
                if new_stage != l["stage"]:
                    (promoted if ok else demoted).append(l)
                    db.add_event(l["id"], "re-evaluated", f"{l.get('score')} → {r['score']} ({reason}): now {'qualifies' if ok else 'below threshold'}")
                    bus.publish("lead", lead_summary(l["id"]))
        msg = f"{checked} re-scored, {len(promoted)} now qualify" + (f", {len(demoted)} dropped below" if demoted else "")
        bus.publish("toast", {"title": "Leads re-evaluated", "body": msg + (f": {promoted[0]['company']}, {promoted[0]['title']}" if promoted else "")})
        return {"ok": True, "checked": checked, "promoted": len(promoted), "demoted": len(demoted)}


def lead_summary(lead_id: int) -> dict | None:
    r = db.lead_row(db.one(f"SELECT {LIST_FIELDS} FROM leads WHERE id=?", (lead_id,)))
    if r:
        r["open_q"] = profile_mod.open_counts_by_lead().get(lead_id, 0)
    return r


async def gap_questions(lead_id: int) -> int:
    """Ask the candidate 1-3 questions that could truthfully strengthen an already-packaged lead's resume."""
    lead = db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))
    pkg = lead.get("package") or {}
    chk = pkg.get("resume_check") or {}
    prompt = f"""JOB: {lead['title']} at {lead['company']}
KEYWORDS THE RESUME IS MISSING: {', '.join((pkg.get('coverage') or {}).get('miss', [])) or 'none'}
FIT GAPS: {'; '.join((pkg.get('fit') or {}).get('gaps', [])) or 'none'}
RESUME CHECK ISSUES: {'; '.join(i['text'] for i in chk.get('issues', [])) or 'none'}
POSTING (excerpt):
{(lead.get('description') or '')[:5000]}

TAILORED RESUME:
{lead.get('resume_md') or ''}

=== CANDIDATE PROFILE ===
{profile_mod.full_context()}"""
    out = await ai.run(prompt, system=prompts.GAP_QUESTIONS_SYSTEM, schema=prompts.GAP_QUESTIONS_SCHEMA, stage="revise",
                           purpose="gap-questions", lead_id=lead_id, label=f"questions: {lead['company'][:24]}", timeout=600)
    n = sum(profile_mod.ask(q["question"], q["why"], q.get("field", ""), source=f"{lead['company'][:40]} application", lead_id=lead_id)
            for q in out.get("questions", [])[:3])
    pkg["gap_questions_at"] = db.now()
    db.update_lead(lead_id, package=pkg)
    bus.publish("lead", lead_summary(lead_id))
    return n


async def apply_answers(lead_id: int) -> dict:
    """Add the answers to the profile, then rework this lead's resume with them (check and critic included)."""
    lead = db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))
    answered = [q for q in profile_mod.questions() if q.get("lead_id") == lead_id and q.get("status") == "answered"]
    if not answered:
        return {"ok": False, "message": "Answer at least one question first."}
    await profile_mod.update_from_answers(f"answers for {lead['company']}")
    cfg = settings_mod.get()
    pkg = lead.get("package") or {}
    style = pkg.get("resume_style") or {"theme": "classic", "max_pages": 1}
    qa = "\n".join(f"- Q: {q['question']}\n  A: {q.get('answer', '')}" for q in answered)
    system = (prompts.system("revise", prompts.REVISE_SYSTEM) + f"\n\n{prompts.RESUME_FORMAT}\n\n=== RESUME PLAYBOOK ===\n"
              f"{settings_mod.resume_playbook(cfg)}\n\n=== CANDIDATE PROFILE ===\n{profile_mod.full_context()}")
    prompt = f"""DOCUMENT TYPE: resume (layout {style['theme']}, page limit {style['max_pages']})
JOB: {lead['title']} at {lead['company']}
JOB DESCRIPTION (excerpt):
{(lead.get('description') or '')[:6000]}

INSTRUCTION: The candidate just answered these questions for this application. Use every answer that strengthens the match for THIS
job (new skills, tools, metrics, experience), truthfully and only as far as the answer supports. Keep the page limit.
{qa}

CURRENT DOCUMENT:
{lead.get('resume_md') or ''}"""
    out = await ai.run(prompt, system=system, schema=prompts.REVISE_SCHEMA, stage="revise", purpose="apply-answers",
                           lead_id=lead_id, label=f"answers into resume: {lead['company'][:20]}", timeout=900)
    kws = pkg.get("keywords") or []
    md, review, tokens = await polish_resume(lead, out["text"], kws, pkg.get("resume_strategy") or {}, style, cfg, None, lead_id,
                                             lambda *a, **k: None, out.get("_tokens", 0))
    cov, hit, miss = coverage(kws, md)
    pkg.update(resume_review=review, resume_check=review.get("check"), coverage={"hit": hit, "miss": miss}, original_resume_md=md)
    db.update_lead(lead_id, resume_md=md, package=pkg, ats_coverage=cov, tokens=(lead.get("tokens") or 0) + tokens)
    d = LEADS_DIR / str(lead_id)
    for f in ("resume.pdf", "resume.docx", "resume.fit"):
        (d / f).unlink(missing_ok=True)
    await render_files(lead_id)
    db.add_event(lead_id, "resume", f"Resume updated with {len(answered)} answer(s): {out.get('change_summary', '')[:300]}")
    qs = profile_mod.questions()
    for q in qs:
        if q.get("lead_id") == lead_id and q.get("status") == "answered":
            q["status"] = "applied"
    db.kv_set("profile.questions", qs)
    bus.publish("questions", qs)
    bus.publish("lead", lead_summary(lead_id))
    bus.publish("toast", {"title": "Resume updated with your answers", "body": out.get("change_summary", "")[:200], "lead_id": lead_id})
    return {"ok": True, "change_summary": out.get("change_summary", ""), "coverage": cov}


async def use_saved_resume(lead_id: int, item: dict, tailor: bool) -> dict:
    """Put a resume from the library on a lead: exactly as saved, or re-tailored to this job (then checked and critiqued)."""
    lead = db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))
    cfg = settings_mod.get()
    pkg = lead.get("package") or {}
    style = {"theme": "classic", "max_pages": 1, **(item.get("style") or {})}
    kws = pkg.get("keywords") or []
    md, tokens, summary = item["md"], 0, ""
    if tailor:
        system = (prompts.system("revise", prompts.REVISE_SYSTEM) + f"\n\n{prompts.RESUME_FORMAT}\n\n=== RESUME PLAYBOOK ===\n"
                  f"{settings_mod.resume_playbook(cfg)}\n\n=== CANDIDATE PROFILE ===\n{profile_mod.full_context()}")
        prompt = f"""DOCUMENT TYPE: resume (layout {style['theme']}, page limit {style['max_pages']})
JOB: {lead['title']} at {lead['company']}
JOB DESCRIPTION (excerpt):
{(lead.get('description') or '')[:6000]}

INSTRUCTION: The candidate picked this saved resume ("{item['name']}") as the starting point for THIS job. Tailor it: reorder and
re-angle sections, bullets, projects and skills toward the job, mirror its real keywords where the profile backs them, swap in stronger
profile material where it fits better, and keep the page limit. Everything must stay true to the candidate profile.

CURRENT DOCUMENT:
{md}"""
        out = await ai.run(prompt, system=system, schema=prompts.REVISE_SCHEMA, stage="revise", purpose="library-tailor",
                               lead_id=lead_id, label=f"tailor saved resume: {lead['company'][:20]}", timeout=900)
        md, review, tokens = await polish_resume(lead, out["text"], kws, pkg.get("resume_strategy") or {}, style, cfg, None, lead_id,
                                                 lambda *a, **k: None, out.get("_tokens", 0))
        summary = out.get("change_summary", "")
    else:
        chk = await check_resume(md, kws, style, (pkg.get("resume_strategy") or {}).get("archetype", ""))
        review = {"before_score": chk["score"], "changes": [], "check": chk}
    cov, hit, miss = coverage(kws, md)
    pkg.update(resume_style=style, resume_review=review, resume_check=review.get("check"), coverage={"hit": hit, "miss": miss},
               resume_from_library=item["id"])
    db.update_lead(lead_id, resume_md=md, package=pkg, ats_coverage=cov, tokens=(lead.get("tokens") or 0) + tokens)
    d = LEADS_DIR / str(lead_id)
    for f in ("resume.pdf", "resume.docx", "resume.fit"):
        (d / f).unlink(missing_ok=True)
    await render_files(lead_id)
    db.add_event(lead_id, "resume", f"Resume loaded from your collection: {item['name']}" + (f" (tailored: {summary[:250]})" if tailor else ""))
    bus.publish("lead", lead_summary(lead_id))
    return {"ok": True, "change_summary": summary, "coverage": cov, "check": review.get("check", {}).get("score")}


def priority(score: int, deadline: str | None) -> float:
    """Package order: best fit first, but anything closing within a week jumps the line."""
    left = -age_days(deadline) if deadline and re.match(r"\d{4}-\d{2}-\d{2}", deadline) else None
    return (score or 0) + (20 if left is not None and 0 <= left <= 7 else 8 if left is not None and 0 <= left <= 14 else 0)


def is_dream_job(title: str, jobs: list[str]) -> bool:
    t = (title or "").lower()
    return any(re.search(rf"\b{re.escape(j.lower().strip())}", t) for j in jobs if j and j.strip())


def is_dream(company: str, dreams: list[str]) -> bool:
    c = (company or "").lower()
    return any(re.search(rf"\b{re.escape(d.lower())}\b", c) for d in dreams if d)


class Pipeline:
    def __init__(self, mode: str):
        self.mode = mode
        self.cfg = settings_mod.get()
        self.cancel = asyncio.Event()
        self.stats: Counter = Counter()
        self.pool: dict[str, tuple[float, RawJob]] = {}
        self.collecting_done = asyncio.Event()
        self.package_q: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.packages_started = 0
        self.triaged = 0
        self.paused_reason: str | None = None
        self.inflight: set[int] = set()
        self.triagers: list[asyncio.Task] = []
        self.run_id = db.ex("INSERT INTO runs(started_at, mode, status) VALUES(?,?,?)", (db.now(), mode, "running"))
        f = self.cfg["filters"]
        self.inc = re.compile("|".join(f"(?:{p})" for p in f["title_include"]) or "$^", re.I)
        self.exc = re.compile("|".join(f"(?:{p})" for p in f["title_exclude"]) or "$^", re.I)
        self.tech = re.compile("|".join(f"(?:{p})" for p in f.get("tech_title", [])) or ".", re.I)
        self.matcher = LocationMatcher(self.cfg["locations"]["allowed"])
        self.dreams = settings_mod.all_dreams(self.cfg)
        self.genres = self.cfg["analysis"]["genres"]
        self.skill_re = skill_regex()  # pre-scoring rewards matching the candidate's skills, never an industry or a dream company
        self.genre_ids = {g["id"] for g in self.genres}
        self.ctx = Ctx(self.cfg, self.log, self.run_id, self.cancel)

    # ------------------------------------------------------------ logging / state
    def log(self, source: str, msg: str, level: str = "info") -> None:
        db.ex("INSERT INTO run_log(run_id, ts, level, source, msg) VALUES(?,?,?,?,?)", (self.run_id, db.now(), level, source, msg))
        bus.publish("log", {"run_id": self.run_id, "source": source, "level": level, "msg": msg, "ts": db.now()})

    def push_counts(self) -> None:
        bus.set_state(counts=dict(self.stats))

    # ------------------------------------------------------------ filtering
    def prefilter(self, j: RawJob) -> tuple[bool, str, float]:
        f, loc_cfg = self.cfg["filters"], self.cfg["locations"]
        tl = (j.title or "").lower()
        if not j.title or not j.url:
            return False, "incomplete", 0
        if any(x.lower() in (j.company or "").lower() for x in f.get("exclude_companies", []) if x):
            return False, "excluded company", 0
        if j.strict_titles and not self.inc.search(tl):
            return False, "title doesn't match your levels", 0
        if j.kind == "posting" and self.exc.search(tl):
            return False, "too senior / excluded title", 0
        if f.get("require_tech_title", True) and j.source not in NO_TECH_GATE and not self.tech.search(tl):
            return False, "not a tech role", 0
        dream_co = j.dream or is_dream(j.company, self.dreams)
        dream_job = is_dream_job(j.title, self.cfg.get("dream_jobs", []))
        j.dream = dream_co or dream_job
        loc = self.matcher.match(j.loc_list())
        bypass = (dream_co and loc_cfg.get("dream_bypass")) or (dream_job and loc_cfg.get("dream_jobs_bypass"))
        if loc is False and not bypass:
            return False, "outside your locations", 0
        if loc is None and loc_cfg.get("unknown_policy") == "drop" and j.source != "ai_hunt":
            return False, "unknown location", 0
        age = age_days(j.posted_at)
        if age is not None and age > int(self.cfg["run"].get("max_age_days", 90)):
            return False, "too old", 0
        low_desc = (j.description or "").lower()
        if any(k.lower() in low_desc for k in f.get("exclude_keywords", []) if k):
            return False, "excluded keyword", 0
        s = 40.0 + (10 if loc else 0)
        s += 8 if re.search(r"intern|co-?op", tl) else 4 if re.search(r"new grad|entry|junior|early career|associate", tl) else 0
        if self.skill_re:
            in_title = {m.lower() for m in self.skill_re.findall(j.title or "")}
            in_desc = {m.lower() for m in self.skill_re.findall((j.description or "")[:2500])}
            s += min(26, 4 * len(in_title) + 2 * len(in_desc - in_title))
        s += 6 if j.source == "ai_hunt" else 0
        s += 5 if j.kind in ("intel", "event", "program") else 0
        if age is not None:
            s -= min(age, 90) / 9
        return True, "", s

    def find_existing(self, fp: str, uk: str | None) -> dict | None:
        r = db.one("SELECT id, sources, found FROM leads WHERE fingerprint=?", (fp,))
        if not r and uk:
            r = db.one("SELECT id, sources, found FROM leads WHERE url_key=?", (uk,))
        return r

    async def add_jobs(self, source_name: str, jobs: list[RawJob]) -> None:
        added = 0
        for j in jobs:
            self.stats["found"] += 1
            ok, reason, rs = self.prefilter(j)
            if not ok:
                self.stats[f"filtered: {reason}"] += 1
                continue
            loc0 = (j.loc_list() or [""])[0]
            fp = fingerprint(j.company, j.title, loc0)
            uk = url_key(j.url)
            ex = self.find_existing(fp, uk)
            if ex:
                srcs, found = json.loads(ex["sources"] or "[]"), json.loads(ex["found"] or "[]")
                upd = {}
                if j.source not in srcs:
                    upd["sources"] = srcs + [j.source]
                w = j.where_found()
                if w["url"] and all(f.get("url") != w["url"] for f in found):
                    upd["found"] = found + [w]  # seen in another place: keep every location
                if upd:
                    db.update_lead(ex["id"], **upd)
                self.stats["already known"] += 1
                continue
            for g in classify(j.title, j.description, self.genres):
                self.stats[f"genre:{g}"] += 1  # market demand signal for the Analysis tab
            if fp in self.pool:
                self.stats["duplicate"] += 1
                pj = self.pool[fp][1]
                w = j.where_found()
                if all(f.get("url") != w["url"] for f in pj.meta.setdefault("found", [pj.where_found()])):
                    pj.meta["found"].append(w)
                continue
            self.pool[fp] = (rs, j)
            added += 1
        self.stats["candidates"] = self.stats["candidates"] + added
        self.log(source_name, f"{len(jobs)} found → {added} new candidates")
        self.push_counts()

    # ------------------------------------------------------------ triage
    async def enrich(self, j: RawJob) -> None:
        if len(j.description or "") >= 600 or j.source in ("ai_hunt", "hackernews", "mastodon", "reddit", "bluesky"):
            return
        try:
            d = await asyncio.wait_for(details.fetch(self.ctx, j.url, j.meta), timeout=40)
        except Exception:  # noqa: BLE001 (a missing description just means thinner triage)
            return
        if d.get("description") and len(d["description"]) > len(j.description or ""):
            j.description = d["description"]
        j.apply_url = j.apply_url or d.get("apply_url")
        j.deadline = j.deadline or d.get("deadline")
        if d.get("location") and not j.location:
            j.location = d["location"]

    def take_batch(self, n: int) -> list[tuple[str, RawJob]]:
        """Best candidates first, but interleaved across work types so one field can't crowd out the rest."""
        buckets: dict[str, list] = {}
        for fp, (sc, j) in self.pool.items():
            g = (classify(j.title, j.description, self.genres, top=1) or ["other"])[0]
            buckets.setdefault(g, []).append((sc, fp, j))
        for b in buckets.values():
            b.sort(key=lambda x: -x[0])
        order = sorted(buckets.values(), key=lambda b: -b[0][0])
        picked = []
        while len(picked) < n and any(order):
            for b in order:
                if b and len(picked) < n:
                    picked.append(b.pop(0))
        for _, fp, _ in picked:
            self.pool.pop(fp, None)
        return [(fp, j) for _, fp, j in picked]

    # ---- persistent backlog: candidates the triage cap didn't reach are kept and triaged on later runs
    def load_backlog(self) -> int:
        from dataclasses import fields as dc_fields
        known = {f.name for f in dc_fields(RawJob)}
        db.ex("DELETE FROM candidates WHERE first_seen < ?", ((date.today() - timedelta(days=60)).isoformat(),))
        n = 0
        for r in db.q("SELECT fingerprint, data, rule_score, first_seen FROM candidates"):
            if db.one("SELECT 1 FROM leads WHERE fingerprint=?", (r["fingerprint"],)):
                db.ex("DELETE FROM candidates WHERE fingerprint=?", (r["fingerprint"],))
                continue
            try:
                j = RawJob(**{k: v for k, v in json.loads(r["data"]).items() if k in known})
            except (TypeError, ValueError):
                continue
            waited = max(0, (date.today() - date.fromisoformat(r["first_seen"][:10])).days)
            self.pool[r["fingerprint"]] = ((r["rule_score"] or 40) + min(20, 3 * waited), j)  # the longer it waits, the sooner it's triaged
            n += 1
        return n

    def save_backlog(self) -> int:
        from dataclasses import asdict
        now = db.now()
        for fp, (sc, j) in self.pool.items():
            db.ex("""INSERT INTO candidates(fingerprint, data, rule_score, first_seen, last_seen) VALUES(?,?,?,?,?)
                     ON CONFLICT(fingerprint) DO UPDATE SET data=excluded.data, rule_score=excluded.rule_score, last_seen=excluded.last_seen""",
                  (fp, json.dumps(asdict(j), default=str), sc, now, now))
        n = len(self.pool)
        db.ex("DELETE FROM candidates WHERE fingerprint IN (SELECT fingerprint FROM candidates ORDER BY rule_score ASC LIMIT max(0, (SELECT COUNT(*) FROM candidates) - 6000))")
        return n

    async def triage_worker(self, wid: int) -> None:
        batch_n = int(self.cfg["run"].get("triage_batch", 20))
        cap = int(self.cfg["run"].get("max_triage", 300))
        while not self.cancel.is_set():
            if self.triaged >= cap:
                if self.pool and wid == 0:
                    kept = self.save_backlog()
                    self.log("triage", f"triage cap reached ({cap}); {kept} candidates saved to the backlog, to be triaged first next run", "warn")
                    self.stats["backlog for next run"] = kept
                    self.pool.clear()
                return
            if len(self.pool) < batch_n and not self.collecting_done.is_set():
                await asyncio.sleep(4)
                if len(self.pool) < batch_n // 2 and not self.collecting_done.is_set():
                    continue
            if not self.pool:
                if self.collecting_done.is_set():
                    return
                await asyncio.sleep(2)
                continue
            batch = self.take_batch(min(batch_n, cap - self.triaged))
            self.triaged += len(batch)
            await asyncio.gather(*(self.enrich(j) for _, j in batch))
            try:
                await self.triage_batch(batch)
            except ai.UsageLimitError as e:
                self.pause(f"ChatGPT usage cap: {e}")
                return
            except ai.AIError as e:
                self.log("triage", f"batch failed: {e}", "error")
                self.stats["triage errors"] += len(batch)

    async def triage_batch(self, batch: list[tuple[str, RawJob]]) -> None:
        items = []
        for i, (fp, j) in enumerate(batch):
            items.append({"id": str(i), "title": j.title, "company": j.company, "location": j.location or ", ".join(j.locations),
                          "kind": j.kind, "source": j.source_detail or j.source, "posted": j.posted_at, "deadline": j.deadline,
                          "location_ok_by_their_settings": bool(j.dream and self.cfg["locations"].get("dream_bypass")),
                          "description": (j.description or "(no description available)")[:1500]})
        industries = self.cfg.get("industries") or DEFAULT_INDUSTRIES
        system = triage_system(self.cfg)
        out = await ai.run(json.dumps(items, indent=1), system=system, schema=prompts.TRIAGE_SCHEMA, stage="triage",
                           purpose="triage", run_id=self.run_id, label=f"triage ×{len(batch)}", timeout=600)
        tokens_each = int(out.get("_tokens", 0)) // max(1, len(batch))
        by_id = {r["id"]: r for r in out.get("results", [])}
        min_score = int(self.cfg["run"].get("min_score", 60))
        for i, (fp, j) in enumerate(batch):
            r = by_id.get(str(i))
            if not r:
                self.stats["triage missing"] += 1
                continue
            qualified = r["score"] >= min_score and r["eligibility"] != "ineligible" and r["verdict"] != "no"
            stage = "qualified" if qualified else "filtered"
            now = db.now()
            try:
                lead_id = db.ex(
                    """INSERT INTO leads(fingerprint,url_key,url,apply_url,title,company,location,kind,category,source,sources,
                       source_detail,posted_at,deadline,description,score,verdict,triage,stage,dream,tokens,run_id,created_at,updated_at,found,industry)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (fp, url_key(j.url), j.url, j.apply_url, j.title, j.company, j.location or " | ".join(j.locations), j.kind,
                     r.get("category") or j.category_hint, j.source, json.dumps([j.source]), j.source_detail, j.posted_at,
                     j.deadline, j.description, r["score"], r["verdict"],
                     json.dumps({**{k: r.get(k) for k in ("summary", "reasons", "red_flags", "eligibility", "score")},
                                 "genres": [g for g in (r.get("genres") or []) if g in self.genre_ids][:3]
                                 or classify(j.title, j.description, self.genres)}),
                     stage, 1 if j.dream else 0, tokens_each, self.run_id, now, now,
                     json.dumps(j.meta.get("found") or [j.where_found()]),
                     r.get("industry") if r.get("industry") in industries else classify_industry(j.company, j.title, j.description, industries)))
            except Exception as e:  # noqa: BLE001 (unique-constraint race with a parallel batch)
                self.log("triage", f"skip duplicate {j.company}, {j.title}: {e}", "warn")
                continue
            self.stats["triaged"] += 1
            db.ex("DELETE FROM candidates WHERE fingerprint=?", (fp,))
            if qualified:
                self.stats["qualified"] += 1
                await self.package_q.put((-priority(r["score"], j.deadline), lead_id))
                bus.publish("lead", lead_summary(lead_id))
                self.log("triage", f"qualified {r['score']}: {j.company}, {j.title}")
            else:
                self.stats["below threshold"] += 1
        self.push_counts()

    # ------------------------------------------------------------ packages
    def pause(self, reason: str) -> None:
        if not self.paused_reason:
            self.paused_reason = reason
            self.log("run", f"paused: {reason}. Stopping AI work; qualified leads stay queued for the next run", "warn")
            self.cancel.set()

    async def package_worker(self) -> None:
        cap = int(self.cfg["run"].get("max_packages", 12))
        while True:
            _, lead_id = await self.package_q.get()
            try:
                if self.cancel.is_set() or self.packages_started >= cap:
                    continue
                if ai.usage_high(self.cfg):
                    self.pause("JobPortal reached its ChatGPT usage cap")
                    continue
                self.packages_started += 1
                self.inflight.add(lead_id)
                try:
                    await build_package(lead_id, run_id=self.run_id, ctx=self.ctx, log=self.log)
                    self.stats["packaged"] += 1
                except ai.UsageLimitError as e:
                    self.pause(f"ChatGPT usage cap: {e}")
                except Exception as e:  # noqa: BLE001
                    self.stats["package errors"] += 1
                    self.log("package", f"lead {lead_id}: {e}", "error")
                finally:
                    self.inflight.discard(lead_id)
                self.push_counts()
            finally:
                self.package_q.task_done()

    # ------------------------------------------------------------ orchestration
    async def collect_all(self) -> None:
        tasks = []
        if self.mode in ("full", "boards"):
            for key, (label, fn) in COLLECTORS.items():
                if self.cfg["sources"].get(key, {}).get("enabled", False):
                    tasks.append(self._run_collector(label, fn))
        if self.mode in ("full", "hunt") and self.cfg["sources"]["ai_hunt"].get("enabled", True):
            tasks.append(self._run_hunt())
        await asyncio.gather(*tasks)
        self.collecting_done.set()
        self.log("run", f"collection finished: {self.stats['found']} found, {self.stats['candidates']} new candidates")

    async def _run_collector(self, label: str, fn) -> None:
        try:
            jobs = await asyncio.wait_for(fn(self.ctx), timeout=900)
            await self.add_jobs(label, jobs)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            self.log(label, f"failed: {type(e).__name__}: {str(e)[:200]}", "error")

    async def _run_hunt(self) -> None:
        try:
            await hunt.collect(self.ctx, on_batch=self.add_jobs, everything=self.mode == "hunt")
        except ai.UsageLimitError as e:
            self.pause(f"ChatGPT usage cap: {e}")
        except Exception as e:  # noqa: BLE001
            self.log("hunt", f"failed: {type(e).__name__}: {e}", "error")

    async def run(self) -> None:
        bus.set_state(running=True, run_id=self.run_id, mode=self.mode, phase="collecting", counts={}, run_tokens_start=bus.state.get("tokens", 0), started_at=db.now())
        self.log("run", f"run #{self.run_id} started ({self.mode})")
        backlog = db.q("SELECT id, score, deadline FROM leads WHERE stage='qualified' AND app_status!='trashed' ORDER BY score DESC")
        for r in backlog:
            await self.package_q.put((-priority(r["score"] or 0, r["deadline"]), r["id"]))
        if backlog:
            self.log("run", f"{len(backlog)} qualified leads from earlier runs queued for packaging")
        if self.mode != "backlog" and profile_mod.unsynced():
            self.log("profile", f"adding {len(profile_mod.unsynced())} new answer(s) to your profile before searching")
            try:
                await profile_mod.update_from_answers("before run")
                self.dreams = settings_mod.all_dreams(self.cfg)
                self.skill_re = skill_regex()
            except Exception as e:  # noqa: BLE001 (never block a run on a profile update)
                self.log("profile", f"profile update failed, searching with the current profile: {e}", "warn")
        if self.mode in ("full", "boards", "hunt"):
            n_back = self.load_backlog()
            if n_back:
                self.log("run", f"{n_back} candidates from the backlog will be triaged alongside new finds")
                self.stats["from backlog"] = n_back
        workers = [asyncio.create_task(self.package_worker()) for _ in range(max(1, int(self.cfg["ai"].get("max_parallel", 3))))]
        status = "done"
        try:
            if self.mode == "backlog":
                self.collecting_done.set()
            else:
                n_tri = max(2, int(self.cfg["ai"].get("max_parallel", 3)))
                self.triagers = [asyncio.create_task(self.triage_worker(i)) for i in range(n_tri)]
                await self.collect_all()
                bus.set_state(phase="triaging")
                await asyncio.gather(*self.triagers)
            bus.set_state(phase="packaging")
            drained = asyncio.create_task(self.package_q.join())
            while not drained.done():
                if self.cancel.is_set():
                    drained.cancel()
                    break
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            status = "stopped"
        finally:
            if self.cancel.is_set() and status == "done":
                status = "paused" if self.paused_reason else "stopped"
            for t in workers + self.triagers:
                t.cancel()
            if self.pool:  # never lose untriaged candidates: they're triaged first next run
                kept = self.save_backlog()
                self.stats["backlog for next run"] = kept
                self.pool.clear()
            if status == "stopped":
                ai.kill_all()
            await self.ctx.close()
            for lid in self.inflight:
                db.ex("UPDATE leads SET stage='qualified' WHERE id=? AND stage='packaging'", (lid,))
            tokens = db.one("SELECT COALESCE(SUM(tokens),0) t FROM ai_calls WHERE run_id=?", (self.run_id,))["t"]
            db.ex("UPDATE runs SET finished_at=?, status=?, stats=?, tokens=? WHERE id=?",
                  (db.now(), status, json.dumps(dict(self.stats)), tokens, self.run_id))
            self.log("run", f"run #{self.run_id} {status}: {self.stats['qualified']} qualified, {self.stats['packaged']} packaged, {tokens:,} AI tokens")
            bus.set_state(running=False, phase="idle", counts=dict(self.stats))
            bus.publish("run_done", {"run_id": self.run_id, "status": status, "stats": dict(self.stats)})


async def build_package(lead_id: int, run_id: int | None = None, ctx: Ctx | None = None, log=None) -> dict:
    """Generate the full application package for one lead (also used for manual adds and regeneration)."""
    cfg = settings_mod.get()
    lead = db.lead_row(db.one("SELECT * FROM leads WHERE id=?", (lead_id,)))
    if not lead:
        raise ValueError(f"lead {lead_id} not found")
    log = log or (lambda s, m, l="info": bus.publish("log", {"source": s, "msg": m, "level": l}))
    db.update_lead(lead_id, stage="packaging", stage_error=None)
    bus.publish("lead", lead_summary(lead_id))
    own_ctx = ctx is None
    ctx = ctx or Ctx(cfg, log, run_id)
    try:
        if len(lead.get("description") or "") < 600 and lead.get("url") and lead.get("source") not in ("hackernews", "mastodon", "reddit", "bluesky"):
            try:
                d = await asyncio.wait_for(details.fetch(ctx, lead["url"]), timeout=45)
                if len(d.get("description", "")) > len(lead.get("description") or ""):
                    lead["description"] = d["description"]
                    db.update_lead(lead_id, description=d["description"])
            except Exception:  # noqa: BLE001
                pass
        research = bool(cfg["run"].get("package_web_research", True))
        system = (prompts.system("package", prompts.PACKAGE_SYSTEM)
                  .replace("{research}", prompts.RESEARCH_ON if research else prompts.RESEARCH_OFF)
                  .replace("{contacts_rule}", prompts.CONTACTS_ON if research else prompts.CONTACTS_OFF)
                  .replace("{resume_format}", prompts.RESUME_FORMAT)
                  .replace("{playbook}", settings_mod.resume_playbook(cfg)))
        system += (f"\n\nTODAY: {date.today().isoformat()}\nINDUSTRIES: {'; '.join(cfg.get('industries') or DEFAULT_INDUSTRIES)}"
                   f"\n\n=== CANDIDATE PROFILE ===\n{profile_mod.full_context()}")
        tri = lead.get("triage") or {}
        prompt = f"""JOB / LEAD
Title: {lead['title']}
Company: {lead['company']}
Location: {lead['location']}
Kind: {lead['kind']}, category: {lead.get('category') or ''}
Posting URL: {lead['url']}
Apply URL (if known): {lead.get('apply_url') or ''}
Found via: {lead.get('source_detail') or lead.get('source')}
Posted: {lead.get('posted_at') or 'unknown'}. Deadline: {lead.get('deadline') or 'unknown'}
Triage notes: {tri.get('summary', '')} | red flags: {', '.join(tri.get('red_flags') or []) or 'none'}

DESCRIPTION:
{(lead.get('description') or '(none captured: open the URL)')[:15000]}"""
        if lead["kind"] in ("intel", "event", "program"):
            prompt += ("\n\nNOTE: this is a non-standard lead (" + lead["kind"] + "). Tailor the resume to the team/program, write the cover letter as a "
                       "speculative / program application letter, and make the emails the primary weapon (cold outreach to the best contact).")
        out = await ai.run(prompt, system=system, schema=prompts.PACKAGE_SCHEMA, stage="package", purpose="package",
                           web=research, max_steps=24, run_id=run_id, lead_id=lead_id,
                               label=f"package: {lead['company'][:30]}", timeout=1800)
        resume_md, cover_md = out.pop("resume_md", ""), out.pop("cover_letter_md", "")
        tokens = out.pop("_tokens", 0)
        out.pop("_tools", None)
        kws = out.get("keywords") or extract_terms(lead.get("description") or "")
        strat = out.get("resume_strategy") or {}
        theme = strat.get("theme") if strat.get("theme") in render.THEMES else "classic"
        max_pages = 2 if strat.get("archetype") == "federal_usajobs" or int(strat.get("max_pages") or 1) >= 2 else 1
        out["resume_style"] = {"theme": theme, "max_pages": max_pages}
        resume_md, review, tokens = await polish_resume(lead, resume_md, kws, strat, out["resume_style"], cfg, run_id, lead_id, log, tokens)
        out["resume_review"] = review
        out["resume_check"] = review.get("check")
        out["original_resume_md"], out["original_cover_md"] = resume_md, cover_md  # for "revert to AI version"
        cov, hit, miss = coverage(kws, resume_md)
        out["coverage"] = {"hit": hit, "miss": miss}
        fields = {"package": out, "resume_md": resume_md, "cover_md": cover_md, "ats_coverage": cov,
                  "tokens": (lead.get("tokens") or 0) + tokens,
                  "score": int(out.get("fit", {}).get("score") or lead.get("score") or 0)}
        for k in ("title", "company", "location"):
            if out.get(k) and (not lead.get(k) or lead.get(k) in ("Opening (see comment)",) or lead["source"] in ("manual", "mastodon", "reddit", "rss", "bluesky", "hackernews")):
                fields[k] = out[k][:200]
        if out.get("industry") in (cfg.get("industries") or DEFAULT_INDUSTRIES) and (not lead.get("industry") or lead["source"] == "manual"):
            fields["industry"] = out["industry"]
        if out.get("apply_url", "").startswith("http"):
            fields["apply_url"] = out["apply_url"]
        if re.match(r"\d{4}-\d{2}-\d{2}", out.get("deadline") or ""):
            fields["deadline"] = out["deadline"][:10]
        db.update_lead(lead_id, **fields)
        for q in (out.get("questions_for_candidate") or [])[:3]:
            profile_mod.ask(q.get("question", ""), q.get("why", ""), q.get("field", ""), source=f"{lead['company'][:40]} application",
                            lead_id=lead_id)
        await render_files(lead_id)
        stage = "closed" if out.get("posting_status") == "closed" else "ready"
        db.update_lead(lead_id, stage=stage)
        db.add_event(lead_id, "package", f"Application package generated (fit {fields['score']}, ATS keyword coverage {int(cov * 100)}%)")
        summary = lead_summary(lead_id)
        bus.publish("lead", summary)
        if stage == "ready":
            bus.publish("toast", {"title": f"New lead ready (fit {summary['score']})", "body": f"{summary['company']}: {summary['title']}", "lead_id": lead_id})
        log("package", f"ready {summary['score']}: {summary['company']}, {summary['title']} ({stage}, {tokens:,} tokens)")
        return summary
    except ai.UsageLimitError:
        db.update_lead(lead_id, stage="qualified")
        bus.publish("lead", lead_summary(lead_id))
        raise
    except Exception as e:
        db.update_lead(lead_id, stage="error", stage_error=str(e)[:500])
        bus.publish("lead", lead_summary(lead_id))
        raise
    finally:
        if own_ctx:
            await ctx.close()


async def check_resume(md: str, keywords: list[str], style: dict, archetype: str = "") -> dict:
    """Render to measure pages, then run the deterministic resume checks."""
    import tempfile
    from pathlib import Path
    from . import resumecheck
    from .config import CACHE
    CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=CACHE, ignore_cleanup_errors=True) as tmp:
        info = await render.resume_pdf(md, Path(tmp) / "check.pdf", style.get("theme", "classic"), style.get("max_pages", 1))
    return resumecheck.check(md, inventory=profile_mod.get("skills_inventory"), keywords=keywords, pages=info["pages"],
                             max_pages=style.get("max_pages", 1), archetype=archetype, gpa=profile_mod.get("facts").get("gpa", ""))


async def polish_resume(lead, resume_md, kws, strat, style, cfg, run_id, lead_id, log, tokens):
    """Automated check → recruiter-critic revision (truthful, playbook-driven) → re-check."""
    before = await check_resume(resume_md, kws, style, strat.get("archetype", ""))
    review = {"before_score": before["score"], "changes": [], "check": before}
    if not cfg["run"].get("resume_review", True):
        return resume_md, review, tokens
    issues = "\n".join(f"- [{i['level']}] {i['text']}" for i in before["issues"]) or "- none"
    _, _, miss = coverage(kws, resume_md)
    system = (prompts.system("resume_review", prompts.RESUME_REVIEW_SYSTEM) + f"\n\n{prompts.RESUME_FORMAT}"
              f"\n\n=== RESUME PLAYBOOK ===\n{settings_mod.resume_playbook(cfg)}\n\n=== CANDIDATE PROFILE ===\n{profile_mod.full_context()}")
    prompt = f"""JOB: {lead['title']} at {lead['company']} ({lead.get('location') or ''})
STRATEGY CHOSEN: {json.dumps(strat)}
PAGE LIMIT: {style['max_pages']}. LAYOUT: {style['theme']}
AUTOMATED CHECK ISSUES (fix all):
{issues}
POSTING KEYWORDS NOT YET IN THE RESUME: {', '.join(miss) or 'none'} (add only if truthful per the profile / inventory)
JOB DESCRIPTION (excerpt):
{(lead.get('description') or '')[:7000]}

RESUME TO REVIEW:
{resume_md}"""
    try:
        r = await ai.run(prompt, system=system, schema=prompts.RESUME_REVIEW_SCHEMA, stage="revise", purpose="resume-review",
                             run_id=run_id, lead_id=lead_id, label=f"resume critic: {lead['company'][:24]}", timeout=900)
    except ai.UsageLimitError:
        raise
    except ai.AIError as e:
        log("package", f"resume review skipped: {e}", "warn")
        return resume_md, review, tokens
    tokens += r.get("_tokens", 0)
    after = await check_resume(r["resume_md"], kws, style, strat.get("archetype", ""))
    if after["score"] >= before["score"] - 5:  # keep the critic's version unless it clearly made things worse
        resume_md = r["resume_md"]
        review.update(changes=r.get("changes", []), after_score=after["score"], check=after)
    return resume_md, review, tokens


async def render_files(lead_id: int) -> dict:
    lead = db.lead_row(db.one("SELECT id, company, location, resume_md, cover_md, package FROM leads WHERE id=?", (lead_id,)))
    facts = profile_mod.get("facts")
    d = LEADS_DIR / str(lead_id)
    style = (lead.get("package") or {}).get("resume_style") or {}
    info = {}
    try:
        if lead["resume_md"]:
            info["resume"] = await render.resume_pdf(lead["resume_md"], d / "resume.pdf", style.get("theme", "classic"), style.get("max_pages", 1))
        if lead["cover_md"]:
            info["cover"] = await render.cover_pdf(lead["cover_md"], facts, lead["company"], lead["location"], d / "cover_letter.pdf")
    except Exception as e:  # noqa: BLE001 (PDFs can be re-rendered later from the dashboard)
        info["error"] = str(e)
    return info


# ---------------------------------------------------------------- control
def current() -> "Pipeline | None":
    return _current


async def start(mode: str = "full", overrides: dict | None = None) -> int:
    global _current
    if _current and bus.state.get("running"):
        raise RuntimeError("a run is already in progress")
    missing = profile_mod.ready_to_search()
    if missing:
        raise RuntimeError(missing)
    p = Pipeline(mode)
    for k, v in (overrides or {}).items():  # one-off run settings (e.g. triage-only) without touching saved settings
        if k in ("max_packages", "max_triage", "min_score"):
            p.cfg["run"][k] = int(v)
    _current = p

    async def go():
        global _current
        try:
            await p.run()
        finally:
            _current = None

    p.task = asyncio.create_task(go())
    return p.run_id


async def stop() -> None:
    p = _current
    if p:
        p.cancel.set()
        ai.kill_all()
        p.task.cancel()
