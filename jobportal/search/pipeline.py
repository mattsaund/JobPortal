"""The search run: collect jobs from every source, filter them by rules, score them with AI triage, and build application
packages for the best ones, with progress streamed live to the dashboard.

Who calls it: web/routes/search.py (Run search, Stop), the auto-run timer in web/server.py, and, for the jobs at the bottom
of this file that re-check saved leads, web/routes/leads.py and the profile (retriage_leads after a profile change).
web/routes/insights.py uses is_dream and is_dream_job for the Dream list, and sources.py uses RuleFilters.

How a run flows (Pipeline.run):
1. Leads that qualified in earlier runs join the package queue first.
2. New answers to profile questions are added to the profile, so the run searches with the latest version.
3. The collectors (collectors/) and the AI hunt run at the same time. Each batch of jobs goes through add_jobs: the rule
   filters (RuleFilters), then dedupe against saved leads and against this run's pool of candidates.
4. Triage workers take batches from the pool, best pre-score first and mixed across kinds of work, and ask the AI to score
   them (stage "triage"). Every scored job is saved as a lead. Leads at or above the minimum score are "qualified" and join
   the package queue. Candidates beyond the per-run triage cap are saved to a backlog and triaged first next run.
5. Package workers build packages for queued leads (packages.build_package), best first with close deadlines jumping the
   line, up to the per-run package cap.

Stop cancels everything at once. A ChatGPT usage cap pauses the run instead: AI work stops and queued leads wait for the next
run. Building a package and other work on one lead lives in packages.py.

Side effects: rows in the runs, run_log, leads, events and candidates tables; live events (core/bus.py: log, state, lead,
toast, run_done); AI calls on the user's ChatGPT plan; HTTP requests to job sites."""
import asyncio
import json
import re
from collections import Counter
from dataclasses import asdict, fields as dataclass_fields
from datetime import date, timedelta

from jobportal.ai import client as ai, prompts
from jobportal.candidate import profile as profile_mod
from jobportal.core import bus, db, settings as settings_mod
from jobportal.core.genres import DEFAULT_INDUSTRIES, classify, classify_industry
from jobportal.core.textutil import LocationMatcher, age_days, fingerprint, url_key
from jobportal.search import plan
from jobportal.search.collectors import COLLECTORS, details, hunt
from jobportal.search.collectors.base import SOCIAL_SOURCES, Ctx, RawJob
from jobportal.search.packages import build_package, insert_lead, lead_summary

# Sources that skip the tech-role title check: their "titles" are post headlines (social posts, feed items), or an AI agent
# already judged the lead a match for the candidate (the AI hunt).
NO_TECH_GATE = SOCIAL_SOURCES | {"rss", "ai_hunt"}
TRIAGE_NOTES = ("summary", "reasons", "red_flags", "eligibility", "score")  # what a lead keeps from its triage result
RUN_OVERRIDES = ("max_packages", "max_triage", "min_score")  # run settings start() may change for a single run
BACKLOG_DAYS = 60  # candidates waiting longer than this leave the backlog
BACKLOG_MAX = 6000  # the backlog keeps at most this many candidates, the best rule scores
RETRIAGE_BATCH = 20  # leads per AI request when re-evaluating saved leads
INDUSTRY_BATCH = 40  # leads per AI request when re-tagging industries

_current: "Pipeline | None" = None  # the run in progress, if any
_retriage_lock = asyncio.Lock()  # one re-evaluation at a time


# ---------------------------------------------------------------- matching and scoring helpers


def skill_regex() -> re.Pattern | None:
    """A case-insensitive regex that finds the candidate's strong and working skills (profile skills_inventory) in text, for
    the pre-score. None when the profile lists none.

    A skill such as "C/C++" or "Python (pandas)" is split into its parts. Short names need care: "C" only matches standing
    alone (not inside C++, C# or a word), "Go" is skipped because plain text search finds it inside "good" and "Google",
    and one-letter names such as "R" are skipped. Longer names come first, so "JavaScript" wins over "Java"."""
    terms = set()
    for item in profile_mod.get("skills_inventory") or []:
        if item.get("level") not in ("strong", "working"):
            continue
        for name in re.split(r"\s*/\s*|\s*\(|\)", item["skill"]):
            name = name.strip()
            if name.lower() == "c":
                terms.add(r"(?<![\w+#])C(?![\w+#])")
            elif 2 <= len(name) <= 40 and name.lower() != "go":
                terms.add(re.escape(name))
    return re.compile("|".join(sorted(terms, key=lambda t: (-len(t), t))), re.I) if terms else None


def is_dream_job(title: str, jobs: list[str]) -> bool:
    """True when the title contains one of the Dream list's job phrases, ignoring case. The phrase must start at a word but
    may end inside one, so "data engineer" matches "Data Engineering Intern"."""
    t = (title or "").lower()
    return any(re.search(rf"\b{re.escape(j.lower().strip())}", t) for j in jobs if j and j.strip())


def is_dream(company: str, dreams: list[str]) -> bool:
    """True when the company name contains one of the dream companies as whole words, ignoring case: "Example" matches
    "Example Robotics Inc" but not "Examples"."""
    c = (company or "").lower()
    return any(re.search(rf"\b{re.escape(d.lower())}\b", c) for d in dreams if d)


def location_ok_by_settings(cfg: dict, dream: bool, title: str) -> bool:
    """What the triage AI is told about a job's location (location_ok_by_their_settings): True when a Dream list switch lets
    the job skip the search area. That means a dream lead with "Dream companies can be anywhere in the US" on
    (locations.dream_bypass), or a dream job title with "Dream jobs can be anywhere in the US too" on (dream_jobs_bypass).
    Without it, the AI would rule such a job ineligible for being outside the allowed locations."""
    locations = cfg["locations"]
    return bool((dream and locations.get("dream_bypass"))
                or (locations.get("dream_jobs_bypass") and is_dream_job(title, cfg.get("dream_jobs", []))))


def priority(score: int | None, deadline: str | None) -> int:
    """Package queue order: best fit first, but a deadline within a week adds 20 points and one within two weeks adds 8."""
    age = age_days(deadline) if deadline and re.match(r"\d{4}-\d{2}-\d{2}", deadline) else None  # None for an impossible date
    days_left = -age if age is not None else None
    if days_left is not None and 0 <= days_left <= 7:
        bonus = 20
    elif days_left is not None and 0 <= days_left <= 14:
        bonus = 8
    else:
        bonus = 0
    return (score or 0) + bonus


def _any_of(patterns: list[str], when_empty: str) -> re.Pattern:
    """One case-insensitive regex matching any of the patterns. With no patterns, when_empty decides: "$^" matches nothing
    and "." matches everything."""
    return re.compile("|".join(f"(?:{p})" for p in patterns) or when_empty, re.I)


# ---------------------------------------------------------------- rule filters


class RuleFilters:
    """The rule filters every collected job passes before any AI sees it, built from Settings.

    In order, check() drops a job that: has no title or URL; is from an excluded company; lacks a word for the user's levels
    in its title (only for sources with strict_titles); has a too-senior or excluded title (postings only); isn't a tech
    role (filters.tech_title, skipped for NO_TECH_GATE sources); is outside the search area (LocationMatcher), unless a
    Dream list switch lets it through; has an unknown location when Settings says to drop those; is older than
    run.max_age_days; or mentions an excluded keyword.

    A job that passes gets a pre-score (_pre_score). When a run finds more jobs than it can triage, the pre-score decides
    which go first. check() also flags dream jobs (RawJob.dream)."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        filters = cfg["filters"]
        self.include = _any_of(filters["title_include"], "$^")  # level words; only checked for strict_titles sources
        self.exclude = _any_of(filters["title_exclude"], "$^")  # too-senior and other unwanted title words
        self.tech = _any_of(filters.get("tech_title", []), ".")  # an empty list lets every title through
        self.matcher = LocationMatcher(cfg["locations"]["allowed"])
        self.refresh()

    def refresh(self) -> None:
        """Read again what comes from the profile (dream companies, skills). The run calls this after a profile update."""
        self.dreams = plan.all_dreams(self.cfg)
        self.skill_re = skill_regex()  # the pre-score rewards the candidate's skills, never an industry or a dream company

    def check(self, j: RawJob) -> tuple[bool, str, float]:
        """Run the filters on one job. Returns (passed, why it was dropped, pre-score); a dropped job's pre-score is 0. The
        reason becomes a "filtered: <reason>" counter in the run's stats. Side effect: sets j.dream for Dream list matches."""
        filters, loc_cfg = self.cfg["filters"], self.cfg["locations"]
        title = (j.title or "").lower()
        if not j.title or not j.url:
            return False, "incomplete", 0
        if any(x.lower() in (j.company or "").lower() for x in filters.get("exclude_companies", []) if x):
            return False, "excluded company", 0
        if j.strict_titles and not self.include.search(title):
            return False, "title doesn't match your levels", 0
        if j.kind == "posting" and self.exclude.search(title):
            return False, "too senior / excluded title", 0
        if filters.get("require_tech_title", True) and j.source not in NO_TECH_GATE and not self.tech.search(title):
            return False, "not a tech role", 0
        dream_company = j.dream or is_dream(j.company, self.dreams)  # j.dream is already True for a starred company board
        dream_job = is_dream_job(j.title, self.cfg.get("dream_jobs", []))
        j.dream = dream_company or dream_job
        in_area = self.matcher.match(j.loc_list())  # True (allowed), False (known and not allowed) or None (can't tell)
        # The two Dream list switches: dream companies, and dream job titles, may be outside the search area.
        bypass = (dream_company and loc_cfg.get("dream_bypass")) or (dream_job and loc_cfg.get("dream_jobs_bypass"))
        if in_area is False and not bypass:
            return False, "outside your locations", 0
        # The AI hunt's agents were given the allowed locations, so an unknown location from them gets the benefit of the doubt.
        if in_area is None and loc_cfg.get("unknown_policy") == "drop" and j.source != "ai_hunt":
            return False, "unknown location", 0
        age = age_days(j.posted_at)
        if age is not None and age > int(self.cfg["run"].get("max_age_days", 90)):
            return False, "too old", 0
        description = (j.description or "").lower()
        if any(k.lower() in description for k in filters.get("exclude_keywords", []) if k):
            return False, "excluded keyword", 0
        return True, "", self._pre_score(j, title, in_area, age)

    def _pre_score(self, j: RawJob, title: str, in_area: bool | None, age: int | None) -> float:
        """A rough priority for triage, between 30 and 95. It starts at 40, then adds 10 for a location known to be in the
        search area; 8 for an internship or co-op title, or 4 for new-grad, entry, junior or associate wording; up to 26 for
        the candidate's skills (4 per skill in the title, 2 per other skill in the first 2,500 characters of the
        description); 6 for an AI hunt lead, since an agent already judged it a match; and 5 for a program, event or intel
        lead. It loses 1 point per 9 days of age, at most 10."""
        score = 40.0 + (10 if in_area else 0)
        if re.search(r"intern|co-?op", title):
            score += 8
        elif re.search(r"new grad|entry|junior|early career|associate", title):
            score += 4
        if self.skill_re:
            in_title = {m.lower() for m in self.skill_re.findall(j.title or "")}
            in_description = {m.lower() for m in self.skill_re.findall((j.description or "")[:2500])}
            score += min(26, 4 * len(in_title) + 2 * len(in_description - in_title))
        if j.source == "ai_hunt":
            score += 6
        if j.kind in ("intel", "event", "program"):
            score += 5
        if age is not None:
            score -= min(age, 90) / 9
        return score


# ---------------------------------------------------------------- triage helpers (the run and retriage_leads share these)


def triage_system(cfg: dict) -> str:
    """The triage AI's instructions: the triage prompt (Settings can override it), the profile digest, the allowed
    locations, today's date, and the genre and industry lists it picks from."""
    genre_list = "; ".join(f"{g['id']} = {g['label']}" for g in cfg["analysis"]["genres"])
    industries = "; ".join(cfg.get("industries") or DEFAULT_INDUSTRIES)
    return (prompts.system("triage", prompts.TRIAGE_SYSTEM) + "\n\n" + profile_mod.digest()
            + f"\n\nALLOWED LOCATIONS: {', '.join(cfg['locations']['allowed'])}\nTODAY: {date.today().isoformat()}"
            + f"\nGENRES: {genre_list}\nINDUSTRIES: {industries}")


def _triage_item(item_id: int, *, title: str, company: str, location: str, kind: str, source: str, posted: str | None,
                 deadline: str | None, description: str | None, max_chars: int, location_ok: bool) -> dict:
    """One job as the triage AI sees it. The AI answers with the same id, which is how each result finds its job."""
    return {"id": str(item_id), "title": title, "company": company, "location": location, "kind": kind, "source": source,
            "posted": posted, "deadline": deadline, "location_ok_by_their_settings": location_ok,
            "description": (description or "(no description available)")[:max_chars]}


def _qualifies(result: dict, min_score: int) -> bool:
    """A triage result qualifies a lead for a package when it reaches the minimum score and the AI neither ruled the
    candidate ineligible nor said no."""
    return result["score"] >= min_score and result["eligibility"] != "ineligible" and result["verdict"] != "no"


async def _ask_triage(items: list[dict], system: str, *, purpose: str, label: str, run_id: int | None = None) -> tuple[dict[str, dict], int]:
    """Send one batch to the triage AI (stage "triage"). Returns (results by item id, AI tokens used). Raises ai.AIError."""
    out = await ai.run(json.dumps(items, indent=1), system=system, schema=prompts.TRIAGE_SCHEMA, stage="triage", purpose=purpose,
                       run_id=run_id, label=label, timeout=600)
    return {r["id"]: r for r in out.get("results", [])}, int(out.get("_tokens", 0))


# ---------------------------------------------------------------- dedupe helpers


def _add_place(found: list[dict], job: RawJob) -> bool:
    """Add where this job was seen to a "found" list, unless that page is already in it. Returns True when it was added."""
    place = job.where_found()
    if not place["url"] or any(f.get("url") == place["url"] for f in found):
        return False
    found.append(place)
    return True


def _note_sighting(lead: dict, job: RawJob) -> None:
    """A saved lead was found again: remember the new source and the new place it was seen, if they are new."""
    sources, found = json.loads(lead["sources"] or "[]"), json.loads(lead["found"] or "[]")
    changes = {}
    if job.source not in sources:
        changes["sources"] = sources + [job.source]
    if _add_place(found, job):
        changes["found"] = found  # the Leads page lists every place a lead was seen
    if changes:
        db.update_lead(lead["id"], **changes)


# ---------------------------------------------------------------- the run


class Pipeline:
    """One search run. start() creates it and runs run() as a background task; see the module docstring for the flow.

    State worth knowing:
    - pool: candidates waiting for triage, {fingerprint: (pre-score, RawJob)}. Collectors fill it, triage workers empty it.
    - package_q: qualified lead ids, ordered by -priority() so the best come out first.
    - stats: counters shown live and saved with the run (found, candidates, triaged, qualified, packaged, and one per
      filter reason). The dashboard reads several of them by name.
    - cancel: set by Stop or by a usage-cap pause (pause()). Workers check it, and so does every HTTP request (Ctx)."""

    def __init__(self, mode: str):
        self.mode = mode  # "full" (everything), "boards" (job boards only), "hunt" (AI hunt only) or "backlog" (package queue only)
        self.cfg = settings_mod.get()
        self.cancel = asyncio.Event()
        self.stats: Counter = Counter()
        self.pool: dict[str, tuple[float, RawJob]] = {}
        self.backlog_scores: dict[str, float] = {}  # the saved rule score of each candidate loaded from the backlog
        self.collecting_done = asyncio.Event()  # tells the triage workers that no more candidates are coming
        self.package_q: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.packages_started = 0
        self.triaged = 0
        self.paused_reason: str | None = None
        self.triagers: list[asyncio.Task] = []
        self.task: asyncio.Task | None = None  # set by start()
        self.run_id = db.ex("INSERT INTO runs(started_at, mode, status) VALUES(?,?,?)", (db.now(), mode, "running"))
        self.filters = RuleFilters(self.cfg)
        self.genres = self.cfg["analysis"]["genres"]
        self.genre_ids = {g["id"] for g in self.genres}
        self.ctx = Ctx(self.cfg, self.log, self.run_id, self.cancel)

    # ------------------------------------------------------------ logging and live counters
    def log(self, source: str, msg: str, level: str = "info") -> None:
        """Add a line to this run's log (the run_log table, shown on the Runs page) and to the live console."""
        ts = db.now()
        db.ex("INSERT INTO run_log(run_id, ts, level, source, msg) VALUES(?,?,?,?,?)", (self.run_id, ts, level, source, msg))
        bus.publish("log", {"run_id": self.run_id, "source": source, "level": level, "msg": msg, "ts": ts})

    def push_counts(self) -> None:
        """Send the current counters to the dashboard."""
        bus.set_state(counts=dict(self.stats))

    # ------------------------------------------------------------ taking in jobs
    def find_existing(self, fp: str, key: str | None) -> dict | None:
        """The saved lead this job duplicates, matched by fingerprint (company, title and state), else by URL key. Returns
        its id, sources and found list, or None."""
        row = db.one("SELECT id, sources, found FROM leads WHERE fingerprint=?", (fp,))
        if not row and key:
            row = db.one("SELECT id, sources, found FROM leads WHERE url_key=?", (key,))
        return row

    async def add_jobs(self, source_name: str, jobs: list[RawJob]) -> None:
        """Take in one source's jobs. Each one is filtered, then merged into the saved lead or pooled candidate it
        duplicates, or added to the triage pool with its pre-score. Updates the live counters and logs one line.

        It's async so the AI hunt can await it as its on_batch callback."""
        added = 0
        for j in jobs:
            self.stats["found"] += 1
            passed, reason, pre_score = self.filters.check(j)
            if not passed:
                self.stats[f"filtered: {reason}"] += 1
                continue
            fp = fingerprint(j.company, j.title, (j.loc_list() or [""])[0])
            known = self.find_existing(fp, url_key(j.url))
            if known:
                _note_sighting(known, j)
                self.stats["already known"] += 1
                continue
            for genre in classify(j.title, j.description, self.genres):
                self.stats[f"genre:{genre}"] += 1  # market demand signal for the Analysis page
            if fp in self.pool:
                self.stats["duplicate"] += 1
                pooled = self.pool[fp][1]
                _add_place(pooled.meta.setdefault("found", [pooled.where_found()]), j)
                continue
            self.pool[fp] = (pre_score, j)
            added += 1
        self.stats["candidates"] += added
        self.log(source_name, f"{len(jobs)} found → {added} new candidates")
        self.push_counts()

    # ------------------------------------------------------------ triage
    async def enrich(self, j: RawJob) -> None:
        """Fetch the full posting for a candidate that only has a snippet, so triage judges the real description. Also fills
        in apply_url, deadline and location when the posting has them. Skips social posts (nothing more to read) and AI hunt
        leads (the agent already read the page). A failed fetch, or one slower than 40 seconds, leaves the job as it was."""
        if len(j.description or "") >= details.SNIPPET_LENGTH or j.source in SOCIAL_SOURCES or j.source == "ai_hunt":
            return
        try:
            fetched = await asyncio.wait_for(details.fetch(self.ctx, j.url, j.meta), timeout=40)
        except Exception:  # noqa: BLE001 (a missing description just means thinner triage)
            return
        if fetched.get("description") and len(fetched["description"]) > len(j.description or ""):
            j.description = fetched["description"]
        j.apply_url = j.apply_url or fetched.get("apply_url")
        j.deadline = j.deadline or fetched.get("deadline")
        if fetched.get("location") and not j.location:
            j.location = fetched["location"]

    def take_batch(self, n: int) -> list[tuple[str, RawJob]]:
        """Take up to n candidates out of the pool for triage: the best pre-scores first, but taken in turns across kinds of
        work (each candidate's top genre), so one busy field can't crowd out the rest. Returns (fingerprint, job) pairs."""
        by_genre: dict[str, list] = {}
        for fp, (score, j) in self.pool.items():
            genre = (classify(j.title, j.description, self.genres, top=1) or ["other"])[0]
            by_genre.setdefault(genre, []).append((score, fp, j))
        for group in by_genre.values():
            group.sort(key=lambda x: -x[0])
        groups = sorted(by_genre.values(), key=lambda g: -g[0][0])  # the genre holding the best candidate goes first
        picked = []
        while len(picked) < n and any(groups):
            for group in groups:  # one candidate from each genre per round
                if group and len(picked) < n:
                    picked.append(group.pop(0))
        for _, fp, _ in picked:
            self.pool.pop(fp, None)
        return [(fp, j) for _, fp, j in picked]

    # ---- the backlog: candidates the triage cap didn't reach are saved, then triaged first on later runs
    def load_backlog(self) -> int:
        """Put the saved backlog into this run's pool and return how many candidates it added. Candidates older than
        BACKLOG_DAYS, and ones that became leads some other way, are deleted instead. A candidate's pre-score rises 3 points
        per day of waiting (at most 20), so old ones get triaged before new finds of the same quality."""
        known_fields = {f.name for f in dataclass_fields(RawJob)}
        db.ex("DELETE FROM candidates WHERE first_seen < ?", ((date.today() - timedelta(days=BACKLOG_DAYS)).isoformat(),))
        loaded = 0
        for row in db.q("SELECT fingerprint, data, rule_score, first_seen FROM candidates"):
            fp = row["fingerprint"]
            if db.one("SELECT 1 FROM leads WHERE fingerprint=?", (fp,)):
                db.ex("DELETE FROM candidates WHERE fingerprint=?", (fp,))
                continue
            try:
                # Only fields RawJob still has, so a backlog saved by an older version still loads.
                job = RawJob(**{k: v for k, v in json.loads(row["data"]).items() if k in known_fields})
            except (TypeError, ValueError):
                continue
            waited = max(0, (date.today() - date.fromisoformat(row["first_seen"][:10])).days)
            base = row["rule_score"] or 40
            self.backlog_scores[fp] = base
            self.pool[fp] = (base + min(20, 3 * waited), job)
            loaded += 1
        return loaded

    def save_backlog(self) -> int:
        """Save every candidate still in the pool to the backlog (the candidates table) and return how many there were. Only
        the best BACKLOG_MAX by rule score are kept. A candidate keeps the date it was first seen, which load_backlog uses."""
        now = db.now()
        for fp, (score, job) in self.pool.items():
            # Save the candidate's own rule score, not one raised for waiting, or the waiting bonus would pile up each run.
            rule_score = self.backlog_scores.get(fp, score)
            db.ex("""INSERT INTO candidates(fingerprint, data, rule_score, first_seen, last_seen) VALUES(?,?,?,?,?)
                     ON CONFLICT(fingerprint) DO UPDATE SET data=excluded.data, rule_score=excluded.rule_score, last_seen=excluded.last_seen""",
                  (fp, json.dumps(asdict(job), default=str), rule_score, now, now))
        kept = len(self.pool)
        db.ex("DELETE FROM candidates WHERE fingerprint IN (SELECT fingerprint FROM candidates ORDER BY rule_score ASC "
              "LIMIT max(0, (SELECT COUNT(*) FROM candidates) - ?))", (BACKLOG_MAX,))
        return kept

    async def triage_worker(self, worker: int) -> None:
        """One of the triage workers that run side by side. Each loops: wait until the pool holds enough candidates (or
        collection is over), enrich a batch, triage it. When the run's triage cap is reached, worker 0 saves what's left in
        the pool to the backlog. A usage cap pauses the run; any other AI error costs only that batch."""
        batch_size = int(self.cfg["run"].get("triage_batch", 20))
        cap = int(self.cfg["run"].get("max_triage", 600))
        while not self.cancel.is_set():
            if self.triaged >= cap:
                if self.pool and worker == 0:
                    kept = self.save_backlog()
                    self.log("triage", f"triage cap reached ({cap}); {kept} candidates saved to the backlog, to be triaged first next run", "warn")
                    self.stats["backlog for next run"] = kept
                    self.pool.clear()
                return
            if len(self.pool) < batch_size and not self.collecting_done.is_set():
                # Collectors are still running. Wait for at least half a batch: each AI request carries the whole triage
                # prompt, so fuller batches use the ChatGPT plan better.
                await asyncio.sleep(4)
                if len(self.pool) < batch_size // 2 and not self.collecting_done.is_set():
                    continue
            if not self.pool:
                if self.collecting_done.is_set():
                    return  # nothing left and nothing more coming
                await asyncio.sleep(2)
                continue
            batch = self.take_batch(min(batch_size, cap - self.triaged))
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
        """Score one batch with the triage AI and save every scored job as a lead: "qualified" (and queued for a package) when
        it reaches the minimum score, "filtered" (below threshold) otherwise. A job the AI skipped counts as "triage
        missing" and is dropped. Raises ai.AIError (including ai.UsageLimitError) from the AI call."""
        items = [_triage_item(i, title=j.title, company=j.company, location=j.location or ", ".join(j.locations), kind=j.kind,
                              source=j.source_detail or j.source, posted=j.posted_at, deadline=j.deadline, description=j.description,
                              max_chars=1500, location_ok=location_ok_by_settings(self.cfg, j.dream, j.title))
                 for i, (_, j) in enumerate(batch)]
        results, tokens = await _ask_triage(items, triage_system(self.cfg), purpose="triage", label=f"triage ×{len(batch)}",
                                            run_id=self.run_id)
        tokens_each = tokens // max(1, len(batch))  # the batch's tokens, shared out evenly among its leads
        min_score = int(self.cfg["run"].get("min_score", 60))
        for i, (fp, j) in enumerate(batch):
            result = results.get(str(i))
            if not result:
                self.stats["triage missing"] += 1
                continue
            qualified = _qualifies(result, min_score)
            lead_id = self._save_triaged(fp, j, result, "qualified" if qualified else "filtered", tokens_each)
            if lead_id is None:
                continue
            self.stats["triaged"] += 1
            db.ex("DELETE FROM candidates WHERE fingerprint=?", (fp,))  # it's a lead now, so it leaves the backlog
            if qualified:
                self.stats["qualified"] += 1
                await self.package_q.put((-priority(result["score"], j.deadline), lead_id))
                bus.publish("lead", lead_summary(lead_id))
                self.log("triage", f"qualified {result['score']}: {j.company}, {j.title}")
            else:
                self.stats["below threshold"] += 1
        self.push_counts()

    def _save_triaged(self, fp: str, j: RawJob, result: dict, stage: str, tokens: int) -> int | None:
        """Save a triaged job as a lead and return its id, or None when the insert failed. That is usually the same job in two
        parallel batches: a collector found it again while its first copy was being triaged."""
        industries = self.cfg.get("industries") or DEFAULT_INDUSTRIES
        genres = [g for g in (result.get("genres") or []) if g in self.genre_ids][:3] or classify(j.title, j.description, self.genres)
        industry = result.get("industry")
        if industry not in industries:  # the AI must pick from the list; otherwise guess from keywords
            industry = classify_industry(j.company, j.title, j.description, industries)
        now = db.now()
        try:
            return insert_lead({
                "fingerprint": fp, "url_key": url_key(j.url), "url": j.url, "apply_url": j.apply_url, "title": j.title,
                "company": j.company, "location": j.location or " | ".join(j.locations), "kind": j.kind,
                "category": result.get("category") or j.category_hint, "source": j.source, "sources": json.dumps([j.source]),
                "source_detail": j.source_detail, "posted_at": j.posted_at, "deadline": j.deadline, "description": j.description,
                "score": result["score"], "verdict": result["verdict"],
                "triage": json.dumps({**{k: result.get(k) for k in TRIAGE_NOTES}, "genres": genres}),
                "stage": stage, "dream": 1 if j.dream else 0, "tokens": tokens, "run_id": self.run_id,
                "created_at": now, "updated_at": now, "found": json.dumps(j.meta.get("found") or [j.where_found()]),
                "industry": industry})
        except Exception as e:  # noqa: BLE001 (one row that can't be saved must not lose the rest of the batch)
            self.log("triage", f"skip duplicate {j.company}, {j.title}: {e}", "warn")
            return None

    # ------------------------------------------------------------ packages
    def pause(self, reason: str) -> None:
        """Pause the run (a ChatGPT usage cap): stop starting AI work and wind down. Qualified leads stay queued for the next
        run. Only the first reason is kept."""
        if not self.paused_reason:
            self.paused_reason = reason
            self.log("run", f"paused: {reason}. Stopping AI work; qualified leads stay queued for the next run", "warn")
            self.cancel.set()

    async def package_worker(self) -> None:
        """One of the package workers that run side by side (Settings ai.max_parallel). Each takes the best lead from the
        queue and builds its package, until the run's package cap is reached. Leads still queued after that, or after a stop
        or pause, are only taken off the queue: they stay "qualified" and are queued again next run."""
        cap = int(self.cfg["run"].get("max_packages", 12))
        while True:
            _, lead_id = await self.package_q.get()
            try:
                if self.cancel.is_set() or self.packages_started >= cap:
                    continue
                if ai.usage_high():
                    self.pause("JobPortal reached its ChatGPT usage cap")
                    continue
                self.packages_started += 1
                try:
                    await build_package(lead_id, run_id=self.run_id, ctx=self.ctx, log=self.log)
                    self.stats["packaged"] += 1
                except ai.UsageLimitError as e:
                    self.pause(f"ChatGPT usage cap: {e}")
                except Exception as e:  # noqa: BLE001 (build_package already marked the lead as failed)
                    self.stats["package errors"] += 1
                    self.log("package", f"lead {lead_id}: {e}", "error")
                self.push_counts()
            finally:
                self.package_q.task_done()  # even for skipped leads, so waiting for an empty queue works

    # ------------------------------------------------------------ orchestration
    async def collect_all(self) -> None:
        """Run every enabled collector (modes full and boards) and the AI hunt (modes full and hunt) at the same time. Their
        jobs go to add_jobs as they arrive. Sets collecting_done at the end, so the triage workers know."""
        tasks = []
        if self.mode in ("full", "boards"):
            for key, (label, collect) in COLLECTORS.items():
                if self.cfg["sources"].get(key, {}).get("enabled", False):
                    tasks.append(self._run_collector(label, collect))
        if self.mode in ("full", "hunt") and self.cfg["sources"]["ai_hunt"].get("enabled", True):
            tasks.append(self._run_hunt())
        await asyncio.gather(*tasks)
        self.collecting_done.set()
        self.log("run", f"collection finished: {self.stats['found']} found, {self.stats['candidates']} new candidates")

    async def _run_collector(self, label: str, collect) -> None:
        """Run one collector, 15 minutes at most, and hand its jobs to add_jobs. A failure is logged and costs only this
        source. Stop still works, because asyncio.CancelledError isn't an Exception and passes through."""
        try:
            jobs = await asyncio.wait_for(collect(self.ctx), timeout=900)
            await self.add_jobs(label, jobs)
        except Exception as e:  # noqa: BLE001
            self.log(label, f"failed: {type(e).__name__}: {str(e)[:200]}", "error")

    async def _run_hunt(self) -> None:
        """Run the AI hunt. Each mission's leads go to add_jobs as soon as that mission finishes. An "AI hunt only" run runs
        every mission; an "Everything" run takes the next few in the rotation (hunt.pick_missions)."""
        try:
            await hunt.collect(self.ctx, on_batch=self.add_jobs, all_missions=self.mode == "hunt")
        except ai.UsageLimitError as e:
            self.pause(f"ChatGPT usage cap: {e}")
        except Exception as e:  # noqa: BLE001
            self.log("hunt", f"failed: {type(e).__name__}: {e}", "error")

    async def run(self) -> None:
        """The whole run, start to finish (see the module docstring). Always ends by saving the run's status and stats:
        "done", "stopped" (Stop) or "paused" (usage cap)."""
        bus.set_state(running=True, run_id=self.run_id, mode=self.mode, phase="collecting", counts={},
                      run_tokens_start=bus.state.get("tokens", 0), started_at=db.now())
        self.log("run", f"run #{self.run_id} started ({self.mode})")
        await self._queue_waiting_leads()
        searching = self.mode != "backlog"  # "backlog" only builds packages for leads already queued
        if searching:
            await self._add_waiting_answers()
            loaded = self.load_backlog()
            if loaded:
                self.log("run", f"{loaded} candidates from the backlog will be triaged alongside new finds")
                self.stats["from backlog"] = loaded
        parallel = int(self.cfg["ai"].get("max_parallel", 3))
        packagers = [asyncio.create_task(self.package_worker()) for _ in range(max(1, parallel))]
        status = "done"
        try:
            if searching:
                self.triagers = [asyncio.create_task(self.triage_worker(i)) for i in range(max(2, parallel))]
                await self.collect_all()
                bus.set_state(phase="triaging")
                await asyncio.gather(*self.triagers)
            bus.set_state(phase="packaging")
            await self._wait_for_packages()
        except asyncio.CancelledError:
            status = "stopped"
        finally:
            await self._wrap_up(status, packagers)

    async def _queue_waiting_leads(self) -> None:
        """Queue the leads that qualified in earlier runs and still have no package (stage "qualified")."""
        waiting = db.q("SELECT id, score, deadline FROM leads WHERE stage='qualified' AND app_status!='trashed' ORDER BY score DESC")
        for row in waiting:
            await self.package_q.put((-priority(row["score"] or 0, row["deadline"]), row["id"]))
        if waiting:
            self.log("run", f"{len(waiting)} qualified leads from earlier runs queued for packaging")

    async def _add_waiting_answers(self) -> None:
        """Add answers the profile hasn't taken in yet, so this run searches and scores with the latest profile. A failure is
        logged and the run goes on with the profile as it is."""
        waiting = profile_mod.unsynced()
        if not waiting:
            return
        self.log("profile", f"adding {len(waiting)} new answer(s) to your profile before searching")
        try:
            await profile_mod.update_from_answers("before run")
            self.filters.refresh()
        except Exception as e:  # noqa: BLE001 (never block a run on a profile update)
            self.log("profile", f"profile update failed, searching with the current profile: {e}", "warn")

    async def _wait_for_packages(self) -> None:
        """Wait until the package queue is empty, checking once a second whether the run was stopped or paused."""
        drained = asyncio.create_task(self.package_q.join())
        while not drained.done():
            if self.cancel.is_set():
                drained.cancel()
                break
            await asyncio.sleep(1)

    async def _wrap_up(self, status: str, packagers: list[asyncio.Task]) -> None:
        """End the run: stop the workers, save untriaged candidates to the backlog, close the HTTP client, and record the
        status, stats and AI tokens in the runs table. A package build that gets canceled here puts its lead back in the
        queue itself (packages.build_package)."""
        if self.cancel.is_set() and status == "done":
            status = "paused" if self.paused_reason else "stopped"
        for task in packagers + self.triagers:
            task.cancel()
        if self.pool:  # never lose untriaged candidates: they're triaged first next run
            self.stats["backlog for next run"] = self.save_backlog()
            self.pool.clear()
        if status == "stopped":
            ai.kill_all()
        await self.ctx.close()
        tokens = db.one("SELECT COALESCE(SUM(tokens),0) t FROM ai_calls WHERE run_id=?", (self.run_id,))["t"]
        db.ex("UPDATE runs SET finished_at=?, status=?, stats=?, tokens=? WHERE id=?",
              (db.now(), status, json.dumps(dict(self.stats)), tokens, self.run_id))
        self.log("run", f"run #{self.run_id} {status}: {self.stats['qualified']} qualified, {self.stats['packaged']} packaged, {tokens:,} AI tokens")
        bus.set_state(running=False, phase="idle", counts=dict(self.stats))
        bus.publish("run_done", {"run_id": self.run_id, "status": status, "stats": dict(self.stats)})


# ---------------------------------------------------------------- starting and stopping


async def start(mode: str = "full", overrides: dict | None = None) -> int:
    """Start a search run in the background and return its run id right away. The dashboard follows it through live events.

    mode is "full" (everything), "boards" (job boards only), "hunt" (AI hunt only) or "backlog" (package queue only).
    overrides holds one-off values for max_packages, max_triage or min_score; saved settings aren't touched. Raises
    RuntimeError when a run is already going or setup isn't finished (the message says what's missing)."""
    global _current
    if _current and bus.state.get("running"):
        raise RuntimeError("a run is already in progress")
    missing = profile_mod.ready_to_search()
    if missing:
        raise RuntimeError(missing)
    one_off = {k: int(v) for k, v in (overrides or {}).items() if k in RUN_OVERRIDES}  # a bad value fails before the run row exists
    p = Pipeline(mode)
    p.cfg["run"].update(one_off)
    _current = p

    async def run_then_clear() -> None:
        """Run the search, then clear _current however it ended, so the next run can start."""
        global _current
        try:
            await p.run()
        finally:
            _current = None

    p.task = asyncio.create_task(run_then_clear())
    return p.run_id


async def stop() -> None:
    """Stop the run in progress, if any: set its cancel flag (collectors and workers check it), cancel every AI request and
    cancel the run's task. The run then saves what it has and ends as "stopped"."""
    p = _current
    if p:
        p.cancel.set()
        ai.kill_all()
        p.task.cancel()


# ---------------------------------------------------------------- re-checking saved leads


async def retriage_leads(reason: str = "profile changed", stages: tuple = ("filtered", "qualified")) -> dict:
    """Score saved leads again against the current profile: below-threshold leads and qualified ones still waiting for a
    package. A new answer (a skill, a project, a certification) can turn an earlier "no" into a match, or the other way.

    Only leads without a resume and not in the trash are checked, RETRIAGE_BATCH per AI request (stage "triage"). Each lead's
    score, verdict, triage notes and stage are updated; a stage change is recorded in its history and shown live. Returns
    {ok, checked, promoted, demoted}, or ok False when a re-evaluation is already running. Toasts tell the user how it went;
    an AI failure stops it early with an error toast instead of raising."""
    if _retriage_lock.locked():
        return {"ok": False, "message": "Re-evaluation already running."}
    async with _retriage_lock:
        cfg = settings_mod.get()
        placeholders = ",".join("?" * len(stages))
        leads = [db.lead_row(r) for r in db.q(
            f"SELECT * FROM leads WHERE stage IN ({placeholders}) AND app_status!='trashed' AND resume_md IS NULL", stages)]
        if not leads:
            return {"ok": True, "checked": 0, "promoted": 0, "demoted": 0}
        min_score = int(cfg["run"].get("min_score", 60))
        system = triage_system(cfg)
        promoted, demoted, checked = [], [], 0
        bus.publish("toast", {"title": "Re-evaluating leads",
                              "body": f"{len(leads)} below-threshold and queued leads against your updated profile ({reason})."})
        for offset in range(0, len(leads), RETRIAGE_BATCH):
            batch = leads[offset:offset + RETRIAGE_BATCH]
            items = [_triage_item(k, title=lead["title"], company=lead["company"], location=lead["location"], kind=lead["kind"],
                                  source=lead.get("source_detail") or lead["source"], posted=lead.get("posted_at"),
                                  deadline=lead.get("deadline"), description=lead.get("description"), max_chars=2200,
                                  location_ok=location_ok_by_settings(cfg, bool(lead.get("dream")), lead["title"]))
                     for k, lead in enumerate(batch)]
            try:
                results, _ = await _ask_triage(items, system, purpose="retriage", label=f"re-evaluate ×{len(batch)}")
            except ai.AIError as e:
                bus.publish("toast", {"title": "Re-evaluation stopped", "body": str(e)[:200], "level": "error"})
                break
            for k, lead in enumerate(batch):
                result = results.get(str(k))
                if not result:
                    continue
                checked += 1
                qualifies = _qualifies(result, min_score)
                new_stage = "qualified" if qualifies else "filtered"
                triage = {**(lead.get("triage") or {}), **{key: result.get(key) for key in TRIAGE_NOTES},
                          "rescored_at": db.now(), "previous_score": lead.get("score")}
                db.update_lead(lead["id"], score=result["score"], verdict=result["verdict"], triage=triage, stage=new_stage)
                if new_stage != lead["stage"]:
                    (promoted if qualifies else demoted).append(lead)
                    db.add_event(lead["id"], "re-evaluated",
                                 f"{lead.get('score')} → {result['score']} ({reason}): now {'qualifies' if qualifies else 'below threshold'}")
                    bus.publish("lead", lead_summary(lead["id"]))
        message = f"{checked} re-scored, {len(promoted)} now qualify" + (f", {len(demoted)} dropped below" if demoted else "")
        bus.publish("toast", {"title": "Leads re-evaluated",
                              "body": message + (f": {promoted[0]['company']}, {promoted[0]['title']}" if promoted else "")})
        return {"ok": True, "checked": checked, "promoted": len(promoted), "demoted": len(demoted)}


INDUSTRY_SCHEMA = {"type": "object", "properties": {"results": {"type": "array", "items": {"type": "object", "properties": {
    "id": {"type": "integer"}, "industry": {"type": "string"}}, "required": ["id", "industry"]}}}, "required": ["results"]}


async def retag_industries() -> int:
    """Tag every saved lead's industry again with AI, for example after the industry list changed in Settings. Uses the
    triage stage's model and effort, INDUSTRY_BATCH leads per request. Only answers that name a listed industry for a lead in
    that request are saved. Returns how many leads were tagged. Raises ai.AIError when the AI fails."""
    industries = settings_mod.get().get("industries") or DEFAULT_INDUSTRIES
    rows = db.q("SELECT id, company, title, description FROM leads")
    system = (f"Tag each employer's industry with exactly one of: {'; '.join(industries)}. "
              "Judge by what the employer does, not the role. Return one result per id.")
    updated = 0
    for offset in range(0, len(rows), INDUSTRY_BATCH):
        batch = [{"id": r["id"], "company": r["company"], "title": r["title"], "description": (r["description"] or "")[:400]}
                 for r in rows[offset:offset + INDUSTRY_BATCH]]
        asked = {str(item["id"]) for item in batch}
        out = await ai.run(json.dumps(batch), system=system, schema=INDUSTRY_SCHEMA, stage="triage", purpose="retag-industries",
                           label="retag industries", timeout=600)
        for result in out.get("results", []):
            if result.get("industry") in industries and str(result.get("id")) in asked:  # never touch a lead we didn't send
                db.update_lead(int(result["id"]), industry=result["industry"])
                updated += 1
    return updated
